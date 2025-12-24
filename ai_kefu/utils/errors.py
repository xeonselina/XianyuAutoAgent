"""
Custom exception classes for the AI customer service agent.
"""

from typing import Optional


class AIKefuError(Exception):
    """Base exception for AI Kefu errors."""
    pass


class SessionNotFoundError(AIKefuError):
    """Raised when session is not found in storage."""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Session not found: {session_id}")


class SessionExpiredError(AIKefuError):
    """Raised when session has expired."""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Session expired: {session_id}")


class QwenAPIError(AIKefuError):
    """Raised when Qwen API call fails."""
    
    def __init__(self, message: str, status_code: Optional[int] = None):
        self.status_code = status_code
        super().__init__(f"Qwen API Error: {message}")


class EmbeddingError(AIKefuError):
    """Raised when embedding generation fails."""
    
    def __init__(self, message: str):
        super().__init__(f"Embedding Error: {message}")


class KnowledgeStoreError(AIKefuError):
    """Raised when knowledge store operation fails."""
    
    def __init__(self, message: str):
        super().__init__(f"Knowledge Store Error: {message}")


class ToolExecutionError(AIKefuError):
    """Raised when tool execution fails."""
    
    def __init__(self, tool_name: str, message: str):
        self.tool_name = tool_name
        super().__init__(f"Tool '{tool_name}' execution failed: {message}")


class LoopDetectedError(AIKefuError):
    """Raised when agent loop is detected."""
    
    def __init__(self, session_id: str, tool_signature: str):
        self.session_id = session_id
        self.tool_signature = tool_signature
        super().__init__(
            f"Loop detected in session {session_id}: repeated tool call '{tool_signature}'"
        )


class MaxTurnsExceededError(AIKefuError):
    """Raised when maximum turns limit is exceeded."""
    
    def __init__(self, session_id: str, max_turns: int):
        self.session_id = session_id
        self.max_turns = max_turns
        super().__init__(
            f"Maximum turns ({max_turns}) exceeded for session {session_id}"
        )


class TurnTimeoutError(AIKefuError):
    """Raised when a turn exceeds timeout."""
    
    def __init__(self, session_id: str, timeout_seconds: int):
        self.session_id = session_id
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Turn timeout ({timeout_seconds}s) exceeded for session {session_id}"
        )


class HumanRequestError(AIKefuError):
    """Raised when human request handling fails."""
    
    def __init__(self, message: str):
        super().__init__(f"Human Request Error: {message}")


class ValidationError(AIKefuError):
    """Raised when input validation fails."""
    
    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(f"Validation error for '{field}': {message}")

