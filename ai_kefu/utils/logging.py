"""
Logging infrastructure with structured JSON logging.
"""

import logging
import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional
from ai_kefu.config.settings import settings


class JSONFormatter(logging.Formatter):
    """Custom formatter for JSON structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.
        
        Args:
            record: Log record
            
        Returns:
            JSON formatted log string
        """
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add custom fields
        if hasattr(record, 'session_id'):
            log_data["session_id"] = record.session_id
        if hasattr(record, 'event_type'):
            log_data["event_type"] = record.event_type
        if hasattr(record, 'duration_ms'):
            log_data["duration_ms"] = record.duration_ms
        if hasattr(record, 'tool_name'):
            log_data["tool_name"] = record.tool_name
        if hasattr(record, 'user_id'):
            log_data["user_id"] = record.user_id
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Simple text formatter for development."""
    
    def __init__(self):
        super().__init__(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )


def setup_logging(
    level: Optional[str] = None,
    log_format: Optional[str] = None
) -> logging.Logger:
    """
    Setup application logging.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_format: Log format ("json" or "text")
        
    Returns:
        Configured logger
    """
    level = level or settings.log_level
    log_format = log_format or settings.log_format
    
    # Create logger
    logger = logging.getLogger("ai_kefu")
    logger.setLevel(getattr(logging, level.upper()))
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    
    # Set formatter
    if log_format.lower() == "json":
        formatter = JSONFormatter()
    else:
        formatter = TextFormatter()
    
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    # Prevent propagation to root logger
    logger.propagate = False
    
    return logger


def get_logger(name: str = "ai_kefu") -> logging.Logger:
    """
    Get logger instance.
    
    Args:
        name: Logger name
        
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


# Initialize default logger
logger = setup_logging()


# Helper functions for structured logging
def log_turn_start(session_id: str, turn_counter: int, query: str):
    """Log turn start event."""
    logger.info(
        f"Turn {turn_counter} started",
        extra={
            "session_id": session_id,
            "event_type": "turn_start",
            "turn_counter": turn_counter,
            "query_length": len(query)
        }
    )


def log_turn_end(session_id: str, turn_counter: int, duration_ms: int, success: bool):
    """Log turn end event."""
    logger.info(
        f"Turn {turn_counter} completed",
        extra={
            "session_id": session_id,
            "event_type": "turn_end",
            "turn_counter": turn_counter,
            "duration_ms": duration_ms,
            "success": success
        }
    )


def log_tool_call(session_id: str, tool_name: str, tool_call_id: str, args: Dict[str, Any]):
    """Log tool call event."""
    logger.info(
        f"Tool called: {tool_name}",
        extra={
            "session_id": session_id,
            "event_type": "tool_call_start",
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "args": str(args)
        }
    )


def log_tool_result(
    session_id: str,
    tool_name: str,
    tool_call_id: str,
    success: bool,
    duration_ms: int
):
    """Log tool call result."""
    logger.info(
        f"Tool completed: {tool_name}",
        extra={
            "session_id": session_id,
            "event_type": "tool_call_end",
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "success": success,
            "duration_ms": duration_ms
        }
    )


def log_agent_complete(session_id: str, status: str, total_turns: int, total_duration_ms: int):
    """Log agent completion."""
    logger.info(
        f"Agent completed with status: {status}",
        extra={
            "session_id": session_id,
            "event_type": "agent_complete",
            "status": status,
            "total_turns": total_turns,
            "total_duration_ms": total_duration_ms
        }
    )
