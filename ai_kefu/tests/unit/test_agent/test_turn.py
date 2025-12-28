"""
Unit tests for Turn management.
T029 - Test single turn execution logic.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from ai_kefu.agent.turn import execute_turn, TurnResult
from ai_kefu.models.session import Session, Message
from ai_kefu.config.constants import MessageRole


@pytest.fixture
def sample_session():
    """Create a sample session for testing."""
    return Session(
        session_id="test-session-001",
        user_id="user-001",
        messages=[],
        turn_counter=0
    )


@patch('ai_kefu.agent.turn.call_qwen')
@patch('ai_kefu.agent.turn.ToolRegistry')
def test_execute_turn_text_response(mock_registry_class, mock_call_qwen, sample_session):
    """Test turn execution with text response (no tool calls)."""
    # Mock Qwen API response
    mock_call_qwen.return_value = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "您好！我可以帮您查询退款政策。"
            }
        }]
    }
    
    # Mock tool registry
    mock_registry = Mock()
    mock_registry.to_qwen_format.return_value = []
    mock_registry_class.return_value = mock_registry
    
    result = execute_turn(
        session=sample_session,
        user_message="如何退款？",
        tools_registry=mock_registry
    )
    
    assert result.success is True
    assert result.response_text == "您好！我可以帮您查询退款政策。"
    assert result.tool_calls == []
    assert len(result.new_messages) == 2  # user message + assistant message


@patch('ai_kefu.agent.turn.call_qwen')
@patch('ai_kefu.agent.turn.ToolRegistry')
def test_execute_turn_with_tool_calls(mock_registry_class, mock_call_qwen, sample_session):
    """Test turn execution with tool calls."""
    # Mock Qwen API response with tool calls
    mock_call_qwen.return_value = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "让我帮您查询一下",
                "tool_calls": [{
                    "id": "call_001",
                    "type": "function",
                    "function": {
                        "name": "knowledge_search",
                        "arguments": '{"query": "退款政策", "top_k": 5}'
                    }
                }]
            }
        }]
    }
    
    # Mock tool registry
    mock_registry = Mock()
    mock_registry.to_qwen_format.return_value = []
    mock_registry.execute_tool.return_value = {
        "success": True,
        "results": [{"title": "退款政策", "content": "7天内可退款"}]
    }
    mock_registry_class.return_value = mock_registry
    
    result = execute_turn(
        session=sample_session,
        user_message="如何退款？",
        tools_registry=mock_registry
    )
    
    assert result.success is True
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["name"] == "knowledge_search"
    assert mock_registry.execute_tool.called


@patch('ai_kefu.agent.turn.call_qwen')
def test_execute_turn_qwen_api_error(mock_call_qwen, sample_session):
    """Test turn execution with Qwen API error."""
    mock_call_qwen.side_effect = Exception("API Error")
    
    mock_registry = Mock()
    mock_registry.to_qwen_format.return_value = []
    
    result = execute_turn(
        session=sample_session,
        user_message="测试",
        tools_registry=mock_registry
    )
    
    assert result.success is False
    assert "error" in result.error_message.lower()


@patch('ai_kefu.agent.turn.call_qwen')
def test_execute_turn_updates_session(mock_call_qwen, sample_session):
    """Test that turn execution updates session properly."""
    mock_call_qwen.return_value = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "回复内容"
            }
        }]
    }
    
    mock_registry = Mock()
    mock_registry.to_qwen_format.return_value = []
    
    initial_message_count = len(sample_session.messages)
    
    result = execute_turn(
        session=sample_session,
        user_message="测试消息",
        tools_registry=mock_registry
    )
    
    # Verify new messages were created
    assert len(result.new_messages) > initial_message_count
    assert result.new_messages[0].role == MessageRole.USER
    assert result.new_messages[0].content == "测试消息"
