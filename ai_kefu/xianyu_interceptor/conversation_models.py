"""
Conversation data models for MySQL persistence.

This module defines the data models for storing Xianyu conversations
in MySQL database.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator


class MessageType(str, Enum):
    """Message sender type."""
    USER = "user"           # Message from user (buyer)
    SELLER = "seller"       # Message from seller (manual reply)
    SYSTEM = "system"       # System message


class ConversationMessage(BaseModel):
    """
    Represents a single message in a conversation.

    This model is used for both saving to and reading from the database.
    """

    # Primary identifiers
    id: Optional[int] = Field(None, description="Database auto-increment ID")
    chat_id: str = Field(..., description="Xianyu chat ID")
    user_id: str = Field(..., description="User ID who sent the message")
    seller_id: Optional[str] = Field(None, description="Seller ID (account owner)")
    item_id: Optional[str] = Field(None, description="Item ID if available")

    # Message content
    message_content: str = Field(..., description="Message content")
    message_type: MessageType = Field(..., description="Message sender type")

    # AI Agent integration
    session_id: Optional[str] = Field(None, description="AI Agent session ID")
    agent_response: Optional[str] = Field(None, description="AI Agent response")

    # Additional context
    context: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")

    # Timestamps
    created_at: Optional[datetime] = Field(None, description="Message timestamp")
    updated_at: Optional[datetime] = Field(None, description="Record update timestamp")

    @field_validator('message_content')
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Ensure message content is not empty."""
        if not v or not v.strip():
            raise ValueError("Message content cannot be empty")
        return v

    @field_validator('chat_id', 'user_id')
    @classmethod
    def validate_required_ids(cls, v: str) -> str:
        """Ensure required IDs are not empty."""
        if not v or not v.strip():
            raise ValueError("Required ID field cannot be empty")
        return v

    class Config:
        """Pydantic config."""
        from_attributes = True
        use_enum_values = True


class ConversationSummary(BaseModel):
    """
    Summary statistics for a conversation.

    This corresponds to the conversation_summary view in the database.
    """

    chat_id: str
    user_id: str
    seller_id: Optional[str]
    item_id: Optional[str]

    message_count: int = 0
    first_message_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None

    user_messages: int = 0
    seller_messages: int = 0
    ai_replies: int = 0

    class Config:
        """Pydantic config."""
        from_attributes = True
