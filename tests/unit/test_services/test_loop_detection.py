"""
Unit tests for loop detection service.
T030 - Test loop detection logic.
"""

import pytest
from ai_kefu.services.loop_detection import check_tool_loop, reset_loop_state
from ai_kefu.models.session import AgentState, ToolCall
from ai_kefu.config.constants import ToolCallStatus


@pytest.fixture
def agent_state():
    """Create a sample agent state for testing."""
    return AgentState(session_id="test-session-001")


def test_check_tool_loop_no_loop(agent_state):
    """Test loop detection with no loop."""
    tool_call = ToolCall(
        id="call_001",
        name="knowledge_search",
        args={"query": "退款"},
        status=ToolCallStatus.SUCCESS
    )
    
    is_loop = check_tool_loop(agent_state, tool_call)
    
    assert is_loop is False
    assert len(agent_state.recent_tool_calls) == 1


def test_check_tool_loop_different_tools(agent_state):
    """Test loop detection with different tools."""
    tool1 = ToolCall(id="call_001", name="knowledge_search", args={"query": "退款"}, status=ToolCallStatus.SUCCESS)
    tool2 = ToolCall(id="call_002", name="complete_task", args={"summary": "完成"}, status=ToolCallStatus.SUCCESS)
    tool3 = ToolCall(id="call_003", name="knowledge_search", args={"query": "发货"}, status=ToolCallStatus.SUCCESS)
    
    check_tool_loop(agent_state, tool1)
    check_tool_loop(agent_state, tool2)
    is_loop = check_tool_loop(agent_state, tool3)
    
    assert is_loop is False
    assert len(agent_state.recent_tool_calls) == 3


def test_check_tool_loop_detected(agent_state):
    """Test loop detection when loop is detected."""
    # Same tool with same arguments called multiple times
    tool_call = ToolCall(
        id="call_001",
        name="knowledge_search",
        args={"query": "退款", "top_k": 5},
        status=ToolCallStatus.SUCCESS
    )
    
    # Call same tool 3 times (threshold is 3)
    check_tool_loop(agent_state, tool_call)
    check_tool_loop(agent_state, tool_call)
    is_loop = check_tool_loop(agent_state, tool_call)
    
    assert is_loop is True
    assert agent_state.loop_detected is True


def test_check_tool_loop_different_args_no_loop(agent_state):
    """Test that same tool with different args doesn't trigger loop."""
    tool1 = ToolCall(id="call_001", name="knowledge_search", args={"query": "退款"}, status=ToolCallStatus.SUCCESS)
    tool2 = ToolCall(id="call_002", name="knowledge_search", args={"query": "发货"}, status=ToolCallStatus.SUCCESS)
    tool3 = ToolCall(id="call_003", name="knowledge_search", args={"query": "售后"}, status=ToolCallStatus.SUCCESS)
    
    check_tool_loop(agent_state, tool1)
    check_tool_loop(agent_state, tool2)
    is_loop = check_tool_loop(agent_state, tool3)
    
    assert is_loop is False


def test_check_tool_loop_max_history_size(agent_state):
    """Test that tool call history is limited to max size."""
    # Add 15 different tool calls (max is 10)
    for i in range(15):
        tool = ToolCall(
            id=f"call_{i:03d}",
            name="knowledge_search",
            args={"query": f"query_{i}"},
            status=ToolCallStatus.SUCCESS
        )
        check_tool_loop(agent_state, tool)
    
    # History should be limited to 10
    assert len(agent_state.recent_tool_calls) == 10


def test_reset_loop_state(agent_state):
    """Test resetting loop state."""
    # Create a loop
    tool_call = ToolCall(id="call_001", name="test", args={}, status=ToolCallStatus.SUCCESS)
    check_tool_loop(agent_state, tool_call)
    check_tool_loop(agent_state, tool_call)
    check_tool_loop(agent_state, tool_call)
    
    assert agent_state.loop_detected is True
    
    # Reset
    reset_loop_state(agent_state)
    
    assert agent_state.loop_detected is False
    assert len(agent_state.recent_tool_calls) == 0
    assert agent_state.loop_count == 0


def test_check_tool_loop_increments_count(agent_state):
    """Test that loop detection increments loop count."""
    tool_call = ToolCall(id="call_001", name="test", args={}, status=ToolCallStatus.SUCCESS)
    
    check_tool_loop(agent_state, tool_call)
    check_tool_loop(agent_state, tool_call)
    check_tool_loop(agent_state, tool_call)
    
    assert agent_state.loop_count > 0
