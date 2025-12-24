"""
Message format conversion between Xianyu and AI Agent.

Converts Xianyu messages to Agent API format and vice versa.
"""

from typing import Dict
from .models import (
    XianyuMessage,
    AgentChatRequest,
    AgentChatResponse
)


def convert_xianyu_to_agent(
    xianyu_msg: XianyuMessage,
    agent_session_id: str
) -> AgentChatRequest:
    """
    Convert Xianyu message to Agent API request format.
    
    Args:
        xianyu_msg: Xianyu message object
        agent_session_id: AI Agent session ID
        
    Returns:
        AgentChatRequest object
    """
    return AgentChatRequest(
        query=xianyu_msg.content or "",
        session_id=agent_session_id,
        user_id=xianyu_msg.user_id,
        context={
            "conversation_id": xianyu_msg.chat_id,
            "source": "xianyu",
            "item_id": xianyu_msg.item_id,
            "timestamp": xianyu_msg.timestamp,
            "message_type": xianyu_msg.message_type.value,
            **(xianyu_msg.metadata or {})
        }
    )


def convert_agent_to_xianyu(
    agent_response: AgentChatResponse,
    xianyu_chat_id: str,
    xianyu_user_id: str
) -> Dict[str, str]:
    """
    Convert Agent response to Xianyu reply format.
    
    Args:
        agent_response: AI Agent response object
        xianyu_chat_id: Xianyu conversation ID
        xianyu_user_id: Xianyu user ID
        
    Returns:
        Dictionary with chat_id, user_id, and content
    """
    return {
        "chat_id": xianyu_chat_id,
        "user_id": xianyu_user_id,
        "content": agent_response.response
    }
