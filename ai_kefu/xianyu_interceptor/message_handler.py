"""
Message handler that integrates Xianyu messages with AI Agent service.

This module handles the core message processing flow:
1. Receive Xianyu message
2. Check manual mode
3. Get/create Agent session
4. Convert message format
5. Call Agent API
6. Convert response
7. Send reply
"""

import asyncio
import time
from collections import OrderedDict
from typing import Optional
from datetime import datetime
from loguru import logger

from .models import XianyuMessage, XianyuMessageType
from .message_converter import convert_xianyu_to_agent, convert_agent_to_xianyu
from .session_mapper import SessionMapper
from .manual_mode import ManualModeManager
from .http_client import AgentClient
from .exceptions import AgentAPIError
from .config import config
from .conversation_models import ConversationMessage, MessageType
from .conversation_store import ConversationStore


class MessageDeduplicator:
    """
    Simple in-memory message deduplicator using message_id + chat_id.
    
    Prevents duplicate processing of the same message when WebSocket
    delivers it multiple times (common with Xianyu sync protocol).
    """
    
    def __init__(self, ttl_seconds: float = 30.0, max_size: int = 1000):
        """
        Args:
            ttl_seconds: How long to remember a message_id (default 30s)
            max_size: Max entries to keep (LRU eviction)
        """
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._ttl = ttl_seconds
        self._max_size = max_size
    
    def is_duplicate(self, chat_id: str, message_id: Optional[str], content: Optional[str] = None) -> bool:
        """
        Check if this message was already seen recently.
        
        Args:
            chat_id: Chat/conversation ID
            message_id: Unique message ID (if available)
            content: Message content (fallback dedup key)
            
        Returns:
            True if this is a duplicate message
        """
        # Build dedup key
        if message_id:
            key = f"{chat_id}:{message_id}"
        elif content:
            # Fallback: use chat_id + content hash for dedup
            key = f"{chat_id}:content:{hash(content)}"
        else:
            # No way to dedup, treat as unique
            return False
        
        now = time.monotonic()
        self._evict_expired(now)
        
        if key in self._seen:
            logger.info(f"Duplicate message detected, skipping: key={key}")
            return True
        
        # Mark as seen
        self._seen[key] = now
        
        # Enforce max size (LRU)
        while len(self._seen) > self._max_size:
            self._seen.popitem(last=False)
        
        return False
    
    def _evict_expired(self, now: float):
        """Remove entries older than TTL."""
        expired_keys = [
            k for k, t in self._seen.items()
            if now - t > self._ttl
        ]
        for k in expired_keys:
            del self._seen[k]


class MessageHandler:
    """
    Handles message processing with AI Agent integration.
    """
    
    def __init__(
        self,
        agent_client: AgentClient,
        session_mapper: SessionMapper,
        manual_mode_manager: ManualModeManager,
        conversation_store: Optional[ConversationStore] = None,
        transport: Optional[any] = None
    ):
        """
        Initialize message handler.

        Args:
            agent_client: HTTP client for Agent service
            session_mapper: Session mapping manager
            manual_mode_manager: Manual mode manager
            conversation_store: Conversation persistence layer (optional)
            transport: Message transport for sending replies (optional)
        """
        self.agent_client = agent_client
        self.session_mapper = session_mapper
        self.manual_mode_manager = manual_mode_manager
        self.conversation_store = conversation_store
        self.transport = transport
        self.toggle_keywords = config.toggle_keywords.split(',')
        self._deduplicator = MessageDeduplicator(ttl_seconds=30.0)
    
    async def handle_message(self, message: XianyuMessage) -> Optional[str]:
        """
        Handle an incoming Xianyu message.

        Args:
            message: Xianyu message object

        Returns:
            Agent response text, or None if no response
        """
        try:
            logger.info(
                f"Received message from chat_id={message.chat_id}, "
                f"user_id={message.user_id}, is_self={message.is_self_sent}, "
                f"content={message.content}"
            )

            # Skip non-chat messages
            if message.message_type != XianyuMessageType.CHAT:
                logger.debug(f"Skipping non-chat message: {message.message_type}")
                return None

            # Dedup check: skip duplicate WebSocket messages
            message_id = message.message_id or getattr(message, 'message_id', None)
            if self._deduplicator.is_duplicate(message.chat_id, message_id, message.content):
                return None

            # ============================================================
            # 【关键】区分消息方向：自己发的 vs 用户发的
            # ============================================================
            if message.is_self_sent:
                # 自己（卖家）发送的消息：只记录到数据库，不触发 AI 回复
                logger.info(
                    f"Self-sent message in chat {message.chat_id}, "
                    f"logging only (no AI reply)"
                )
                await self._log_message(
                    message=message,
                    message_type=MessageType.SELLER,
                    is_manual_mode=self.manual_mode_manager.is_manual_mode(message.chat_id)
                )
                return None

            # 用户发来的消息：记录并处理
            # Log user message to database (before any processing)
            await self._log_message(
                message=message,
                message_type=MessageType.USER,
                is_manual_mode=self.manual_mode_manager.is_manual_mode(message.chat_id)
            )

            # Check for manual mode toggle
            if self._is_toggle_keyword(message.content):
                return await self._handle_manual_mode_toggle(message)

            # Check if in manual mode
            if self.manual_mode_manager.is_manual_mode(message.chat_id):
                logger.info(f"Chat {message.chat_id} is in manual mode, skipping AI")
                return None

            # Process with AI Agent (if enabled)
            return await self._process_with_agent(message)

        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
            return None
    
    def _is_toggle_keyword(self, content: Optional[str]) -> bool:
        """Check if message is a manual mode toggle keyword."""
        if not content:
            return False
        return content.strip() in self.toggle_keywords
    
    async def _handle_manual_mode_toggle(self, message: XianyuMessage) -> str:
        """
        Handle manual mode toggle.
        
        Args:
            message: Xianyu message
            
        Returns:
            Status message
        """
        is_manual = self.manual_mode_manager.toggle_manual_mode(message.chat_id)
        
        # Update session mapper
        self.session_mapper.set_manual_mode(message.chat_id, is_manual)
        
        mode_text = "手动" if is_manual else "自动"
        response_text = f"已切换到{mode_text}模式"
        
        logger.info(f"Chat {message.chat_id} toggled to {mode_text} mode")
        
        # Send reply if transport available
        if self.transport:
            await self._send_reply(message, response_text)
        
        return response_text
    
    async def _process_with_agent(self, message: XianyuMessage) -> Optional[str]:
        """
        Process message with AI Agent.

        Args:
            message: Xianyu message

        Returns:
            Agent response text, or None on error
        """
        try:
            is_debug_mode = not config.enable_ai_reply

            # Get or create Agent session
            agent_session_id = self.session_mapper.get_or_create(
                chat_id=message.chat_id,
                user_id=message.user_id,
                item_id=message.item_id
            )

            logger.info(
                f"Processing with Agent: chat_id={message.chat_id}, "
                f"session_id={agent_session_id}, debug_mode={is_debug_mode}"
            )

            # Convert to Agent format
            agent_request = convert_xianyu_to_agent(message, agent_session_id)

            # Call Agent API
            logger.info("Calling Agent API...")
            agent_response = await self.agent_client.send_message(
                query=agent_request.query,
                session_id=agent_request.session_id,
                user_id=agent_request.user_id,
                context=agent_request.context
            )

            logger.info(
                f"Agent response received: {agent_response.response[:100]}..."
            )

            # Check if Agent returned an error status with fallback response
            agent_error = agent_response.metadata.get("error") if agent_response.metadata else None
            if agent_error:
                logger.warning(
                    f"Agent returned error status for chat {message.chat_id}: {agent_error}"
                )
                # If there's a fallback response from the Agent (e.g. "抱歉，系统暂时繁忙"), use it
                if agent_response.response:
                    reply = agent_response.response
                    if is_debug_mode:
                        reply = f"【调试】{reply}"
                    await self._log_message(
                        message=message,
                        message_type=MessageType.SELLER,
                        agent_response=reply,
                        session_id=agent_session_id,
                        is_manual_mode=False
                    )
                    if not is_debug_mode and self.transport:
                        await self._send_reply(message, reply)
                    return reply
                # No fallback response — treat as full error, use configured fallback
                if self.agent_client.config.enable_fallback and \
                   self.agent_client.config.fallback_message:
                    fallback_msg = self.agent_client.config.fallback_message
                    await self._log_message(
                        message=message,
                        message_type=MessageType.SELLER,
                        agent_response=f"[Agent Error Fallback] {agent_error}",
                        session_id=agent_session_id,
                        is_manual_mode=False
                    )
                    if self.transport:
                        await self._send_reply(message, fallback_msg)
                    return fallback_msg
                return None

            # Update session activity
            self.session_mapper.update_activity(message.chat_id)

            if is_debug_mode:
                # Debug mode: add marker, log to DB only, do NOT send to Xianyu
                debug_response = f"【调试】{agent_response.response}"
                logger.info(
                    f"Debug mode: AI reply logged but not sent. "
                    f"chat_id={message.chat_id}"
                )
                await self._log_message(
                    message=message,
                    message_type=MessageType.SELLER,
                    agent_response=debug_response,
                    session_id=agent_session_id,
                    is_manual_mode=False
                )
                return debug_response
            else:
                # Normal mode: log to DB and send to Xianyu
                await self._log_message(
                    message=message,
                    message_type=MessageType.SELLER,
                    agent_response=agent_response.response,
                    session_id=agent_session_id,
                    is_manual_mode=False
                )
                if self.transport:
                    await self._send_reply(message, agent_response.response)
                return agent_response.response

        except AgentAPIError as e:
            logger.error(f"Agent API failed for chat {message.chat_id}: {e}")

            # Log the failure to conversations table so we know what happened
            error_note = f"[Agent API Error] {str(e)}"
            await self._log_message(
                message=message,
                message_type=MessageType.SELLER,
                agent_response=error_note,
                session_id=self.session_mapper.get_or_create(
                    chat_id=message.chat_id,
                    user_id=message.user_id,
                    item_id=message.item_id
                ),
                is_manual_mode=False
            )

            # Fallback strategy: send fallback message if configured
            if self.agent_client.config.enable_fallback and \
               self.agent_client.config.fallback_message:
                fallback_msg = self.agent_client.config.fallback_message
                if self.transport:
                    await self._send_reply(message, fallback_msg)
                return fallback_msg

            return None

        except Exception as e:
            logger.error(f"Unexpected error processing message: {e}", exc_info=True)

            # Log unexpected errors too
            try:
                error_note = f"[Unexpected Error] {str(e)}"
                await self._log_message(
                    message=message,
                    message_type=MessageType.SELLER,
                    agent_response=error_note,
                    session_id=None,
                    is_manual_mode=False
                )
            except Exception:
                pass  # Don't let error logging break the handler

            return None
    
    async def _send_reply(self, original_message: XianyuMessage, content: str):
        """
        Send reply through transport.

        Args:
            original_message: Original Xianyu message
            content: Reply content
        """
        if not self.transport:
            logger.warning("No transport available, cannot send reply")
            return

        try:
            success = await self.transport.send_message(
                chat_id=original_message.chat_id,
                user_id=original_message.user_id,
                content=content
            )

            if success:
                logger.info(f"Sent reply to chat {original_message.chat_id}")
            else:
                logger.warning(f"Failed to send reply to chat {original_message.chat_id}")

        except Exception as e:
            logger.error(f"Error sending reply: {e}", exc_info=True)

    async def _log_message(
        self,
        message: XianyuMessage,
        message_type: MessageType,
        agent_response: Optional[str] = None,
        session_id: Optional[str] = None,
        is_manual_mode: bool = False
    ):
        """
        Log a conversation message to the database.

        Args:
            message: Original Xianyu message
            message_type: Type of message (user/seller)
            agent_response: AI-generated response (if any)
            session_id: Agent session ID (if any)
            is_manual_mode: Whether manual mode is active
        """
        if not self.conversation_store:
            logger.debug("No conversation store configured, skipping message logging")
            return

        try:
            # Build context metadata from actual XianyuMessage fields
            context = {
                "item_title": message.item_title,
                "item_price": message.item_price,
                "message_id": message.message_id,
                "is_self_sent": message.is_self_sent,
            }

            # Create conversation message
            conversation_msg = ConversationMessage(
                chat_id=message.chat_id,
                user_id=message.user_id,
                seller_id=None,  # Will be set if we know the seller
                item_id=message.item_id,
                message_content=agent_response if agent_response else message.content,
                message_type=message_type,
                session_id=session_id,
                agent_response=agent_response,
                context=context,
                created_at=datetime.now()
            )

            # Save to database (run in thread pool to avoid blocking)
            await asyncio.to_thread(
                self.conversation_store.save_message,
                conversation_msg
            )

            logger.debug(
                f"Logged message: chat_id={message.chat_id}, "
                f"type={message_type}, manual={is_manual_mode}"
            )

        except Exception as e:
            # Log error but don't crash the message handler
            logger.error(
                f"Failed to log message to database: {e}. "
                f"Continuing with message processing.",
                exc_info=True
            )
