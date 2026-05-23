"""
Thin message relay for Xianyu Interceptor.

Responsibilities (transport only):
1. Deduplicate WebSocket redeliveries
2. POST decoded XianyuMessage to the AI API (/xianyu/inbound)
3. If the API returns a reply, send it via transport

All business logic (manual mode, AI agent, conversation logging, etc.)
has been moved to ai_kefu/api/routes/xianyu.py.
"""

import time
from collections import OrderedDict
from typing import Optional

import httpx
from loguru import logger

from .models import XianyuMessage, XianyuMessageType
from .uid_mapper import record_uid_mapping


# ──────────────────────────────────────────────────────────────
# Message deduplicator (transport concern — stays here)
# ──────────────────────────────────────────────────────────────

class MessageDeduplicator:
    """
    Prevents duplicate processing when WebSocket delivers the same frame twice.
    Uses message_id (preferred) or content hash as dedup key, with TTL eviction.
    """

    def __init__(self, ttl_seconds: float = 30.0, max_size: int = 1000):
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._ttl = ttl_seconds
        self._max_size = max_size

    def is_duplicate(
        self,
        chat_id: str,
        message_id: Optional[str],
        content: Optional[str] = None,
    ) -> bool:
        if message_id:
            key = f"{chat_id}:{message_id}"
        elif content:
            key = f"{chat_id}:content:{hash(content)}"
        else:
            return False

        now = time.monotonic()
        self._evict_expired(now)

        if key in self._seen:
            logger.info(f"Duplicate message detected, skipping: key={key}")
            return True

        self._seen[key] = now
        while len(self._seen) > self._max_size:
            self._seen.popitem(last=False)

        return False

    def _evict_expired(self, now: float):
        expired = [k for k, t in self._seen.items() if now - t > self._ttl]
        for k in expired:
            del self._seen[k]


# ──────────────────────────────────────────────────────────────
# Thin relay handler
# ──────────────────────────────────────────────────────────────

class MessageHandler:
    """
    Thin relay: decode → dedup → POST /xianyu/inbound → send reply.
    """

    def __init__(self, inbound_url: str, transport=None):
        """
        Args:
            inbound_url: Full URL of the AI API inbound endpoint,
                         e.g. "http://localhost:8000/xianyu/inbound".
            transport:   BrowserTransport (or similar) for sending replies.
                         Can be set after construction.
        """
        self.inbound_url = inbound_url
        self.transport = transport
        self._deduplicator = MessageDeduplicator(ttl_seconds=30.0)

    async def handle_message(self, message: XianyuMessage) -> Optional[str]:
        """
        Relay a decoded Xianyu message to the AI API.

        Returns the reply text if one was produced, otherwise None.
        """
        try:
            logger.info(
                f"[relay] chat_id={message.chat_id}, "
                f"user_id={message.user_id}, "
                f"is_self={message.is_self_sent}, "
                f"content={message.content!r}"
            )

            # Record UID mapping while we still have the raw frame
            if message.user_id and message.encrypted_uid:
                record_uid_mapping(message.user_id, message.encrypted_uid)

            # Only relay CHAT messages; other types (order, typing, system) are ignored
            if message.message_type != XianyuMessageType.CHAT:
                logger.debug(f"Skipping non-chat message: {message.message_type}")
                return None

            # Dedup — drop WS redeliveries
            if self._deduplicator.is_duplicate(
                message.chat_id, message.message_id, message.content
            ):
                return None

            # POST to AI API
            payload = message.model_dump()
            logger.debug(
                f"[relay] POSTing to {self.inbound_url}: "
                f"chat_id={message.chat_id}, item_id={message.item_id}"
            )
            async with httpx.AsyncClient(timeout=130.0) as client:
                resp = await client.post(self.inbound_url, json=payload)

            logger.info(
                f"[relay] API response: status={resp.status_code}, "
                f"chat_id={message.chat_id}"
            )

            if resp.status_code >= 400:
                logger.error(
                    f"[relay] API returned error {resp.status_code} for "
                    f"chat_id={message.chat_id}: {resp.text[:500]}"
                )
                resp.raise_for_status()

            data = resp.json()
            logger.debug(
                f"[relay] API response body: chat_id={message.chat_id}, data={data}"
            )

            reply: Optional[str] = data.get("reply")

            logger.info(
                f"[relay] reply decision: chat_id={message.chat_id}, "
                f"reply={'<none>' if reply is None else repr(reply[:80])}"
            )

            # Send reply via transport if one was returned
            if reply and self.transport:
                await self.transport.send_message(
                    chat_id=message.chat_id,
                    user_id=message.user_id,
                    content=reply,
                )
                logger.info(f"[relay] Sent reply to chat {message.chat_id}")
            elif reply and not self.transport:
                logger.warning(
                    f"[relay] Reply generated but no transport available: "
                    f"chat_id={message.chat_id}"
                )

            return reply

        except Exception as e:
            logger.error(f"[relay] Error handling message: {e}", exc_info=True)
            return None
