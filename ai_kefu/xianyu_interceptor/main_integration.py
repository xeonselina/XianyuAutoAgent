"""
Main integration module for Xianyu Interceptor with AI Agent.

This module sets up all the components and starts the interceptor.
"""

import asyncio
from loguru import logger

from .config import config
from .models import AgentClientConfig
from .http_client import AgentClient
from .session_mapper import MemorySessionMapper, RedisSessionMapper
from .manual_mode import ManualModeManager
from .message_handler import MessageHandler
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


async def initialize_interceptor():
    """
    Initialize all interceptor components.
    
    Returns:
        Tuple of (agent_client, session_mapper, manual_mode_manager, message_handler)
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
    
    # Create message handler (transport will be set later)
    message_handler = MessageHandler(
        agent_client=agent_client,
        session_mapper=session_mapper,
        manual_mode_manager=manual_mode_manager,
        transport=None  # Will be set after transport is created
    )
    
    logger.info("=" * 60)
    logger.info("Configuration:")
    logger.info(f"  Agent Service: {config.agent_service_url}")
    logger.info(f"  Session Mapper: {config.session_mapper_type}")
    logger.info(f"  Manual Mode Timeout: {config.manual_mode_timeout}s")
    logger.info(f"  Toggle Keywords: {config.toggle_keywords}")
    logger.info("=" * 60)
    
    return agent_client, session_mapper, manual_mode_manager, message_handler


async def run_interceptor(message_handler: MessageHandler, transport):
    """
    Run the interceptor main loop.
    
    Args:
        message_handler: Message handler instance
        transport: Transport instance for browser communication
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
