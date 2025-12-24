"""
Data models for Xianyu Interceptor.

Includes models for session mapping, message conversion, and Agent API communication.
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum


class XianyuMessageType(str, Enum):
    """Xianyu message types."""
    CHAT = "chat"
    ORDER = "order"
    TYPING = "typing"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class XianyuMessage(BaseModel):
    """Xianyu message model (parsed from WebSocket)."""
    
    message_type: XianyuMessageType
    chat_id: str
    user_id: str
    content: Optional[str] = None
    item_id: Optional[str] = None
    timestamp: Optional[int] = None
    raw_data: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class SessionMapping(BaseModel):
    """Session mapping between Xianyu chat ID and Agent session ID."""
    
    xianyu_chat_id: str
    agent_session_id: str
    user_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_active: datetime = Field(default_factory=datetime.utcnow)
    manual_mode: bool = False
    manual_mode_entered_at: Optional[datetime] = None
    item_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentChatRequest(BaseModel):
    """Request to AI Agent service."""
    
    query: str = Field(..., min_length=1)
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)


class AgentChatResponse(BaseModel):
    """Response from AI Agent service."""
    
    session_id: str
    response: str
    status: str
    turn_counter: int
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentClientConfig(BaseModel):
    """Configuration for Agent HTTP client."""
    
    base_url: str = "http://localhost:8000"
    timeout: float = 10.0
    connect_timeout: float = 5.0
    max_retries: int = 3
    retry_delay: float = 1.0
    retry_backoff: float = 2.0
    health_check_interval: int = 60
    health_check_path: str = "/health"
    enable_fallback: bool = True
    fallback_message: Optional[str] = None


class HTTPClientMetrics(BaseModel):
    """Metrics for HTTP client performance."""
    
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_response_time: float = 0.0
    min_response_time: Optional[float] = None
    max_response_time: Optional[float] = None
    error_counts: Dict[str, int] = Field(default_factory=dict)
    is_healthy: bool = True
    last_health_check: Optional[datetime] = None
    
    def add_request(self, success: bool, response_time: float, error: Optional[str] = None):
        """Record a request."""
        self.total_requests += 1
        
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
            if error:
                if error not in self.error_counts:
                    self.error_counts[error] = 0
                self.error_counts[error] += 1
        
        self.total_response_time += response_time
        
        if self.min_response_time is None or response_time < self.min_response_time:
            self.min_response_time = response_time
        
        if self.max_response_time is None or response_time > self.max_response_time:
            self.max_response_time = response_time
    
    def get_avg_response_time(self) -> float:
        """Get average response time."""
        if self.total_requests == 0:
            return 0.0
        return self.total_response_time / self.total_requests
    
    def get_success_rate(self) -> float:
        """Get success rate."""
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests


class ManualModeState(BaseModel):
    """Manual mode state for a conversation."""
    
    chat_id: str
    enabled: bool = False
    entered_at: datetime = Field(default_factory=datetime.utcnow)
    timeout: int = 3600  # seconds
    
    def is_expired(self) -> bool:
        """Check if manual mode has expired."""
        elapsed = (datetime.utcnow() - self.entered_at).total_seconds()
        return elapsed > self.timeout
    
    def refresh(self):
        """Refresh the entered_at timestamp."""
        self.entered_at = datetime.utcnow()
