"""
Main integration module for Xianyu Interceptor with AI Agent.

This module sets up all the components and starts the interceptor.
"""

import asyncio
from typing import Optional
from loguru import logger

from .config import config
from .models import AgentClientConfig
from .http_client import AgentClient
from .session_mapper import MemorySessionMapper, RedisSessionMapper
from .manual_mode import ManualModeManager
from .message_handler import MessageHandler
from .conversation_store import ConversationStore
from .exceptions import InterceptorConfigError


async def setup_agent_client() -> AgentClient:
    """
    Set up and initialize Agent HTTP client.
    
    Returns:
        Configured AgentClient instance
    """
    client_config = AgentClientConfig(
        base_url=config.agent_service_url,
        timeout=config.agent_timeout,
        max_retries=config.agent_max_retries,
        retry_delay=config.agent_retry_delay,
        enable_fallback=True
    )
    
    client = AgentClient(client_config)
    
    # Health check
    logger.info(f"Checking Agent service at {config.agent_service_url}...")
    is_healthy = await client.health_check()
    
    if not is_healthy:
        logger.warning(
            f"Agent service at {config.agent_service_url} is not healthy. "
            "Interceptor will start but may fail on first message."
        )
    else:
        logger.info("Agent service is healthy")
    
    return client


def setup_session_mapper():
    """
    Set up session mapper based on configuration.
    
    Returns:
        SessionMapper instance (Memory or Redis)
    """
    mapper_type = config.session_mapper_type.lower()
    
    if mapper_type == "redis":
        logger.info(f"Using Redis session mapper: {config.redis_url}")
        try:
            return RedisSessionMapper(config.redis_url)
        except Exception as e:
            logger.error(f"Failed to initialize Redis session mapper: {e}")
            logger.info("Falling back to memory session mapper")
            return MemorySessionMapper()
    else:
        logger.info("Using memory session mapper")
        return MemorySessionMapper()


def setup_manual_mode_manager():
    """
    Set up manual mode manager.

    Returns:
        ManualModeManager instance
    """
    return ManualModeManager(timeout=config.manual_mode_timeout)


def setup_conversation_store() -> Optional[ConversationStore]:
    """
    Set up MySQL conversation store.

    Returns:
        ConversationStore instance or None if MySQL not configured
    """
    # Check if MySQL is configured
    if not config.mysql_user or not config.mysql_password:
        logger.warning(
            "MySQL credentials not configured. "
            "Conversation logging is disabled. "
            "Set MYSQL_USER and MYSQL_PASSWORD to enable."
        )
        return None

    try:
        logger.info(
            f"Initializing MySQL conversation store: "
            f"{config.mysql_database}@{config.mysql_host}:{config.mysql_port}"
        )

        store = ConversationStore(
            host=config.mysql_host,
            port=config.mysql_port,
            user=config.mysql_user,
            password=config.mysql_password,
            database=config.mysql_database,
            pool_size=config.mysql_pool_size
        )

        # Health check
        if store.health_check():
            logger.info("MySQL conversation store is healthy")
            return store
        else:
            logger.error("MySQL health check failed")
            return None

    except Exception as e:
        logger.error(f"Failed to initialize MySQL conversation store: {e}")
        logger.warning("Conversation logging is disabled")
        return None


async def initialize_interceptor():
    """
    Initialize all interceptor components.

    Returns:
        Tuple of (agent_client, session_mapper, manual_mode_manager, conversation_store, message_handler)
    """
    logger.info("=" * 60)
    logger.info("Xianyu Interceptor + AI Agent Integration")
    logger.info("=" * 60)

    # Validate configuration
    if not config.agent_service_url:
        raise InterceptorConfigError("AGENT_SERVICE_URL is not configured")

    # Initialize components
    agent_client = await setup_agent_client()
    session_mapper = setup_session_mapper()
    manual_mode_manager = setup_manual_mode_manager()
    conversation_store = setup_conversation_store()

    # Create message handler (transport will be set later)
    message_handler = MessageHandler(
        agent_client=agent_client,
        session_mapper=session_mapper,
        manual_mode_manager=manual_mode_manager,
        conversation_store=conversation_store,
        transport=None  # Will be set after transport is created
    )

    logger.info("=" * 60)
    logger.info("Configuration:")
    logger.info(f"  AI Auto-Reply: {'Enabled' if config.enable_ai_reply else 'Disabled'}")
    logger.info(f"  Agent Service: {config.agent_service_url}")
    logger.info(f"  Session Mapper: {config.session_mapper_type}")
    logger.info(f"  Manual Mode Timeout: {config.manual_mode_timeout}s")
    logger.info(f"  Toggle Keywords: {config.toggle_keywords}")
    logger.info(f"  Conversation Logging: {'Enabled' if conversation_store else 'Disabled'}")
    if conversation_store:
        logger.info(f"  MySQL Database: {config.mysql_database}@{config.mysql_host}:{config.mysql_port}")
    logger.info("=" * 60)

    return agent_client, session_mapper, manual_mode_manager, conversation_store, message_handler


async def run_interceptor(
    message_handler: MessageHandler,
    transport,
    conversation_store: Optional[ConversationStore] = None
):
    """
    Run the interceptor main loop.

    Args:
        message_handler: Message handler instance
        transport: Transport instance for browser communication
        conversation_store: Conversation store for database cleanup
    """
    # Set transport in message handler
    message_handler.transport = transport

    # Start periodic cleanup
    async def cleanup_loop():
        while True:
            await asyncio.sleep(300)  # Every 5 minutes
            logger.debug("Running periodic cleanup...")
            message_handler.session_mapper.cleanup_expired(config.session_ttl)
            message_handler.manual_mode_manager.cleanup_expired()

    cleanup_task = asyncio.create_task(cleanup_loop())

    logger.info("Interceptor is running. Press Ctrl+C to stop.")

    try:
        # Keep running
        await asyncio.Future()  # Run forever
    except asyncio.CancelledError:
        logger.info("Interceptor shutting down...")
        cleanup_task.cancel()
        await message_handler.agent_client.close()

        # Close database connection
        if conversation_store:
            logger.info("Closing MySQL conversation store...")
            conversation_store.close()
