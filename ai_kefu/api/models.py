"""
API request and response models.
FastAPI endpoint data models.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from ai_kefu.config.constants import SessionStatus, HumanRequestType, Urgency


# ============================================================
# Chat Endpoints
# ============================================================

class ChatRequest(BaseModel):
    """Chat request model."""
    query: str = Field(..., description="User query", min_length=1, max_length=10000)
    session_id: Optional[str] = Field(None, description="Session ID (optional, will create new if not provided)")
    user_id: Optional[str] = Field(None, description="User ID (optional)")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context")


class ChatResponse(BaseModel):
    """Chat response model (sync)."""
    session_id: str
    response: str
    status: SessionStatus
    turn_counter: int
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ============================================================
# Session Endpoints
# ============================================================

class SessionResponse(BaseModel):
    """Session detail response."""
    session_id: str
    user_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    status: SessionStatus
    turn_counter: int
    messages: List[Dict[str, Any]]
    context: Dict[str, Any]
    terminate_reason: Optional[str]
    metadata: Dict[str, Any]


# ============================================================
# Human-in-the-Loop Endpoints
# ============================================================

class HumanRequestResponse(BaseModel):
    """Human request response."""
    request_id: str
    session_id: str
    question: str
    question_type: HumanRequestType
    context: Dict[str, Any]
    options: Optional[List[Dict[str, str]]]
    urgency: Urgency
    status: str
    created_at: datetime


class PendingRequestsResponse(BaseModel):
    """List of pending human requests."""
    total: int
    items: List[HumanRequestResponse]


class HumanResponseRequest(BaseModel):
    """Human agent response submission."""
    request_id: str = Field(..., description="Request ID to respond to")
    human_agent_id: str = Field(..., description="Human agent ID")
    response: Optional[str] = Field(None, description="Text response")
    selected_option: Optional[str] = Field(None, description="Selected option ID")


class HumanResponseResult(BaseModel):
    """Result of human response submission."""
    success: bool
    message: str
    session_status: SessionStatus


# ============================================================
# Knowledge Management Endpoints
# ============================================================

class KnowledgeCreateRequest(BaseModel):
    """Create knowledge entry request."""
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=10, max_length=10000)
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list, max_items=10)
    source: Optional[str] = None
    priority: int = Field(default=0, ge=0, le=100)


class KnowledgeResponse(BaseModel):
    """Knowledge entry response."""
    id: str
    title: str
    content: str
    category: Optional[str]
    tags: List[str]
    source: Optional[str]
    priority: int
    active: bool
    created_at: datetime
    updated_at: datetime


class KnowledgeListResponse(BaseModel):
    """List of knowledge entries."""
    total: int
    items: List[KnowledgeResponse]
    offset: int = 0
    limit: int = 20


class KnowledgeUpdateRequest(BaseModel):
    """Update knowledge entry request."""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = Field(None, min_length=10, max_length=10000)
    category: Optional[str] = None
    tags: Optional[List[str]] = Field(None, max_items=10)
    source: Optional[str] = None
    priority: Optional[int] = Field(None, ge=0, le=100)
    active: Optional[bool] = None


class KnowledgeSearchRequest(BaseModel):
    """Knowledge search request."""
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)
    category: Optional[str] = None


class KnowledgeSearchResult(BaseModel):
    """Single knowledge search result."""
    id: str
    title: str
    content: str
    category: Optional[str]
    score: float = Field(..., description="Relevance score")


class KnowledgeSearchResponse(BaseModel):
    """Knowledge search response."""
    query: str
    results: List[KnowledgeSearchResult]
    total: int


# ============================================================
# System Endpoints
# ============================================================

class HealthCheckResponse(BaseModel):
    """Health check response."""
    status: str
    checks: Dict[str, str] = Field(
        default_factory=dict,
        description="Component health checks (redis, chroma, qwen_api)"
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)
