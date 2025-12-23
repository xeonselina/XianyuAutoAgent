"""
Agent type definitions.
T041 - Agent configuration and result types.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from ai_kefu.models.session import Message, ToolCall


class TurnResult(BaseModel):
    """Result of a single agent turn."""
    
    success: bool = Field(..., description="Whether turn succeeded")
    response_text: str = Field(default="", description="Agent's text response")
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list, description="Tool calls made")
    new_messages: List[Message] = Field(default_factory=list, description="Messages generated in this turn")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class AgentConfig(BaseModel):
    """Agent executor configuration."""
    
    max_turns: int = Field(default=50, description="Maximum conversation turns")
    turn_timeout_seconds: int = Field(default=120, description="Timeout for single turn")
    loop_detection_threshold: int = Field(default=5, description="Loop detection threshold")
    enable_intent_extraction: bool = Field(default=True, description="Enable intent extraction")
    enable_sentiment_analysis: bool = Field(default=True, description="Enable sentiment analysis")
    enable_loop_detection: bool = Field(default=True, description="Enable loop detection")
