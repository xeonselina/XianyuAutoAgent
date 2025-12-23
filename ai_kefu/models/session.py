"""
Session and message data models.
Based on data-model.md specifications.
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional, Dict, Any, Literal
from ai_kefu.config.constants import (
    SessionStatus,
    MessageRole,
    ToolCallStatus,
    TerminateReason,
    HumanRequestType,
    HumanRequestStatus,
    Urgency
)


class ToolCall(BaseModel):
    """Tool call model."""
    
    id: str = Field(..., description="Tool call unique ID")
    name: str = Field(..., description="Tool name")
    args: Dict[str, Any] = Field(..., description="Tool arguments")
    
    status: ToolCallStatus = Field(
        default=ToolCallStatus.PENDING,
        description="Execution status"
    )
    
    result: Optional[Any] = Field(None, description="Tool execution result")
    error: Optional[str] = Field(None, description="Error message if failed")
    
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = Field(None, description="Execution duration in milliseconds")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "call_abc123",
                "name": "knowledge_search",
                "args": {"query": "退款流程", "top_k": 5},
                "status": "success",
                "result": {"documents": ["退款需在7天内..."]},
                "duration_ms": 85
            }
        }


class Message(BaseModel):
    """Conversation message model."""
    
    role: MessageRole = Field(..., description="Message role")
    content: str = Field(..., description="Message content")
    
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Tool call related (only when role=assistant and has tool calls)
    tool_calls: Optional[List[ToolCall]] = Field(None, description="Tool call list")
    
    # Tool response related (only when role=tool)
    tool_call_id: Optional[str] = Field(None, description="Associated tool call ID")
    tool_name: Optional[str] = Field(None, description="Tool name")
    
    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Extended metadata")
    
    class Config:
        json_schema_extra = {
            "example": {
                "role": "user",
                "content": "我想退款",
                "timestamp": "2025-12-22T10:30:00Z",
                "metadata": {}
            }
        }


class HumanRequestOption(BaseModel):
    """Human decision option."""
    id: str = Field(..., description="Option ID")
    label: str = Field(..., description="Option label")
    description: Optional[str] = Field(None, description="Option description")


class HumanRequest(BaseModel):
    """Human assistance request (Human-in-the-Loop)."""
    
    request_id: str = Field(..., description="Request unique ID")
    
    question: str = Field(..., description="Question to ask human agent")
    question_type: HumanRequestType = Field(..., description="Question type")
    
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Context information for human agent"
    )
    
    options: Optional[List[HumanRequestOption]] = Field(
        None,
        description="Options list if this is a multiple choice question"
    )
    
    urgency: Urgency = Field(
        default=Urgency.MEDIUM,
        description="Urgency level"
    )
    
    status: HumanRequestStatus = Field(
        default=HumanRequestStatus.PENDING,
        description="Request status"
    )
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    answered_at: Optional[datetime] = None
    
    human_agent_id: Optional[str] = Field(None, description="Human agent ID who handled this")
    response: Optional[str] = Field(None, description="Human agent's text response")
    selected_option: Optional[str] = Field(None, description="Selected option ID")
    
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extended metadata"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "request_id": "req_abc123",
                "question": "请帮我查询订单 #12345 的发货时间和物流单号",
                "question_type": "information_query",
                "context": {
                    "user_question": "我的订单什么时候发货?",
                    "order_id": "#12345"
                },
                "urgency": "medium",
                "status": "pending",
                "created_at": "2025-12-22T10:35:00Z"
            }
        }


class Session(BaseModel):
    """Customer service session model."""
    
    # Basic information
    session_id: str = Field(..., description="Unique session ID (UUID)")
    user_id: Optional[str] = Field(None, description="User ID (optional)")
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Message history
    messages: List[Message] = Field(default_factory=list, description="Conversation messages")
    
    # Agent state
    turn_counter: int = Field(default=0, description="Current turn count")
    status: SessionStatus = Field(
        default=SessionStatus.ACTIVE,
        description="Session status"
    )
    
    # Context information
    context: Dict[str, Any] = Field(default_factory=dict, description="Session context")
    
    # Termination reason
    terminate_reason: Optional[TerminateReason] = Field(
        None,
        description="Termination reason"
    )
    
    # Human-in-the-Loop related
    pending_human_request: Optional[HumanRequest] = Field(
        None,
        description="Current pending human request"
    )
    human_request_history: List[HumanRequest] = Field(
        default_factory=list,
        description="Human assistance request history"
    )
    
    # Metadata
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extended metadata"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "user_12345",
                "created_at": "2025-12-22T10:30:00Z",
                "updated_at": "2025-12-22T10:35:00Z",
                "messages": [],
                "turn_counter": 5,
                "status": "active",
                "context": {"intent": "退款咨询"},
                "metadata": {"channel": "web", "ip": "192.168.1.100"}
            }
        }


class AgentState(BaseModel):
    """Agent runtime state for loop detection."""
    
    session_id: str
    
    # Loop detection
    recent_tool_calls: List[str] = Field(
        default_factory=list,
        description="Recent tool call signatures for loop detection"
    )
    loop_detected: bool = Field(default=False)
    loop_count: int = Field(default=0)
    
    # Execution statistics
    total_turns: int = Field(default=0)
    total_tool_calls: int = Field(default=0)
    start_time: datetime = Field(default_factory=datetime.utcnow)
    
    # Abort signal
    aborted: bool = Field(default=False)
    abort_reason: Optional[str] = None
