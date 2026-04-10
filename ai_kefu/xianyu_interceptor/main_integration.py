"""
Simplified integration module for the Xianyu Interceptor (transport relay only).

After the SRP refactor the interceptor only handles:
- Transport (BrowserTransport / CDPInterceptor)
- Message deduplication
- Relaying decoded messages to the AI API via POST /xianyu/inbound

All business logic (session mapping, manual mode, AI agent, conversation
logging, etc.) lives in the AI API layer (ai_kefu/api/routes/xianyu.py).
"""

import asyncio
from loguru import logger

from .config import config
from .message_handler import MessageHandler
from .exceptions import InterceptorConfigError


async def initialize_interceptor() -> MessageHandler:
    """
    Initialize the interceptor relay.

    Returns:
        MessageHandler (thin relay) configured to POST to the AI API.
    """
    logger.info("=" * 60)
    logger.info("Xianyu Interceptor (transport relay)")
    logger.info("=" * 60)

    if not config.agent_service_url:
        raise InterceptorConfigError("AGENT_SERVICE_URL is not configured")

    inbound_url = f"{config.agent_service_url.rstrip('/')}/xianyu/inbound"
    logger.info(f"  AI API inbound URL: {inbound_url}")
    logger.info(f"  AI Auto-Reply: {'Enabled' if config.enable_ai_reply else 'Disabled (debug mode)'}")
    logger.info("=" * 60)

    return MessageHandler(inbound_url=inbound_url, transport=None)


async def run_interceptor(message_handler: MessageHandler, transport):
    """
    Run the interceptor main loop.

    Args:
        message_handler: Thin relay instance.
        transport:       BrowserTransport (or similar) for sending replies.
    """
    message_handler.transport = transport

    logger.info("Interceptor relay is running. Press Ctrl+C to stop.")

    try:
        await asyncio.Future()  # Run forever
    except asyncio.CancelledError:
        logger.info("Interceptor shutting down...")
