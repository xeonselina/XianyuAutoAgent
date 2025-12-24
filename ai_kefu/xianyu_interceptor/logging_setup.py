"""
Logging setup for Xianyu Interceptor.

Configures loguru for structured logging.
"""

import sys
from loguru import logger
from .config import config


def setup_logging():
    """
    Configure logging based on configuration.
    """
    # Remove default handler
    logger.remove()
    
    # Determine format
    if config.log_format == "json":
        # JSON format for production
        log_format = (
            "{{"
            '"timestamp": "{time:YYYY-MM-DD HH:mm:ss.SSS}", '
            '"level": "{level}", '
            '"module": "{name}", '
            '"function": "{function}", '
            '"line": {line}, '
            '"message": "{message}"'
            "}}"
        )
    else:
        # Human-readable format for development
        log_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        )
    
    # Add console handler
    logger.add(
        sys.stderr,
        format=log_format,
        level=config.log_level,
        colorize=(config.log_format != "json")
    )
    
    # Add file handler
    logger.add(
        "logs/xianyu_interceptor_{time:YYYY-MM-DD}.log",
        format=log_format,
        level=config.log_level,
        rotation="00:00",  # Rotate at midnight
        retention="7 days",
        compression="zip"
    )
    
    logger.info(f"Logging initialized: level={config.log_level}, format={config.log_format}")
