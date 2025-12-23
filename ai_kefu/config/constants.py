"""
Application constants and enumerations.
"""

from enum import Enum
from typing import Final


# Agent Limits
MAX_TURNS: Final[int] = 50
TURN_TIMEOUT_SECONDS: Final[int] = 120
LOOP_DETECTION_THRESHOLD: Final[int] = 5
MAX_TOOL_CALL_RETRIES: Final[int] = 3

# Session Configuration
DEFAULT_SESSION_TTL: Final[int] = 1800  # 30 minutes in seconds

# Knowledge Base
DEFAULT_TOP_K: Final[int] = 5
MAX_KNOWLEDGE_CONTENT_LENGTH: Final[int] = 10000

# Message Limits
MAX_MESSAGE_LENGTH: Final[int] = 10000
MAX_CONVERSATION_HISTORY: Final[int] = 100

# Qwen API Limits
QWEN_FREE_TIER_QPS: Final[int] = 10
QWEN_API_RETRY_ATTEMPTS: Final[int] = 5
QWEN_API_RETRY_DELAY: Final[float] = 2.0  # seconds

# Tool Names
TOOL_KNOWLEDGE_SEARCH: Final[str] = "knowledge_search"
TOOL_ASK_HUMAN_AGENT: Final[str] = "ask_human_agent"
TOOL_COMPLETE_TASK: Final[str] = "complete_task"


class SessionStatus(str, Enum):
    """Session status enumeration."""
    ACTIVE = "active"
    COMPLETED = "completed"
    ABORTED = "aborted"
    WAITING_FOR_HUMAN = "waiting_for_human"
    ERROR = "error"


class MessageRole(str, Enum):
    """Message role enumeration."""
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class TerminateReason(str, Enum):
    """Session termination reason enumeration."""
    GOAL = "goal"
    TIMEOUT = "timeout"
    ERROR = "error"
    MAX_TURNS = "max_turns"
    USER_ABORTED = "user_aborted"


class ToolCallStatus(str, Enum):
    """Tool call execution status."""
    PENDING = "pending"
    EXECUTING = "executing"
    SUCCESS = "success"
    ERROR = "error"


class HumanRequestType(str, Enum):
    """Type of human assistance request."""
    INFORMATION_QUERY = "information_query"
    DECISION_REQUIRED = "decision_required"
    RISK_CONFIRMATION = "risk_confirmation"
    KNOWLEDGE_GAP = "knowledge_gap"


class HumanRequestStatus(str, Enum):
    """Status of human assistance request."""
    PENDING = "pending"
    ANSWERED = "answered"
    TIMEOUT = "timeout"


class Urgency(str, Enum):
    """Urgency level for requests."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Event Types for Hooks
class EventType(str, Enum):
    """Event types for hook system."""
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    AGENT_COMPLETE = "agent_complete"
    AGENT_ERROR = "agent_error"
    HUMAN_REQUEST_CREATED = "human_request_created"
    HUMAN_RESPONSE_RECEIVED = "human_response_received"
