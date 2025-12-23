"""
Logging hook - Logs all agent events.
T045 - LoggingHook implementation.
"""

from typing import Dict, Any
from ai_kefu.hooks.event_handler import EventHandler
from ai_kefu.config.constants import EventType
from ai_kefu.utils.logging import logger


class LoggingHook(EventHandler):
    """Hook that logs all agent events."""
    
    def __init__(self, log_level: str = "INFO"):
        """
        Initialize logging hook.
        
        Args:
            log_level: Log level (INFO, DEBUG, etc.)
        """
        self.log_level = log_level
    
    def handle(self, event_type: EventType, event_data: Dict[str, Any]) -> None:
        """
        Handle event by logging it.
        
        Args:
            event_type: Type of event
            event_data: Event data
        """
        # Build log message
        session_id = event_data.get("session_id", "unknown")
        
        if event_type == EventType.TURN_START:
            turn = event_data.get("turn_counter", 0)
            logger.info(f"[{session_id}] Turn {turn} started")
        
        elif event_type == EventType.TURN_END:
            turn = event_data.get("turn_counter", 0)
            duration = event_data.get("duration_ms", 0)
            success = event_data.get("success", False)
            status = "✓" if success else "✗"
            logger.info(f"[{session_id}] Turn {turn} ended {status} ({duration}ms)")
        
        elif event_type == EventType.TOOL_CALL_START:
            tool_name = event_data.get("tool_name", "unknown")
            logger.info(f"[{session_id}] Tool called: {tool_name}")
        
        elif event_type == EventType.TOOL_CALL_END:
            tool_name = event_data.get("tool_name", "unknown")
            duration = event_data.get("duration_ms", 0)
            success = event_data.get("success", False)
            status = "✓" if success else "✗"
            logger.info(f"[{session_id}] Tool {tool_name} completed {status} ({duration}ms)")
        
        elif event_type == EventType.AGENT_COMPLETE:
            status = event_data.get("status", "unknown")
            total_turns = event_data.get("total_turns", 0)
            logger.info(f"[{session_id}] Agent completed: {status} ({total_turns} turns)")
        
        elif event_type == EventType.AGENT_ERROR:
            error = event_data.get("error", "unknown error")
            logger.error(f"[{session_id}] Agent error: {error}")
        
        elif event_type == EventType.HUMAN_REQUEST_CREATED:
            request_id = event_data.get("request_id", "unknown")
            question_type = event_data.get("question_type", "unknown")
            logger.info(f"[{session_id}] Human request created: {request_id} ({question_type})")
        
        elif event_type == EventType.HUMAN_RESPONSE_RECEIVED:
            request_id = event_data.get("request_id", "unknown")
            logger.info(f"[{session_id}] Human response received for: {request_id}")
        
        else:
            logger.debug(f"[{session_id}] Event: {event_type.value}")
    
    def get_name(self) -> str:
        """Get handler name."""
        return "LoggingHook"
