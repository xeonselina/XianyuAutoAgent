"""
Unit tests for complete_task tool.
T028 - Test complete_task tool functionality.
"""

import pytest
from ai_kefu.tools.complete_task import complete_task, get_tool_definition


def test_get_tool_definition():
    """Test complete_task tool definition."""
    tool_def = get_tool_definition()
    
    assert tool_def["name"] == "complete_task"
    assert "description" in tool_def
    assert "parameters" in tool_def
    assert "summary" in tool_def["parameters"]["properties"]
    assert "resolved" in tool_def["parameters"]["properties"]
    assert "summary" in tool_def["parameters"]["required"]
    assert "resolved" in tool_def["parameters"]["required"]


def test_complete_task_resolved():
    """Test completing task with resolved=True."""
    result = complete_task(
        summary="用户退款问题已解决",
        resolved=True
    )
    
    assert result["success"] is True
    assert result["status"] == "completed"
    assert result["resolved"] is True
    assert result["summary"] == "用户退款问题已解决"
    assert "message" in result


def test_complete_task_unresolved():
    """Test completing task with resolved=False."""
    result = complete_task(
        summary="用户需要进一步确认信息",
        resolved=False
    )
    
    assert result["success"] is True
    assert result["status"] == "completed"
    assert result["resolved"] is False
    assert result["summary"] == "用户需要进一步确认信息"


def test_complete_task_with_empty_summary():
    """Test complete_task with empty summary."""
    result = complete_task(summary="", resolved=True)
    
    # Should still succeed but with empty summary
    assert result["success"] is True
    assert result["summary"] == ""


def test_complete_task_with_long_summary():
    """Test complete_task with long summary."""
    long_summary = "A" * 1000
    result = complete_task(summary=long_summary, resolved=True)
    
    assert result["success"] is True
    assert len(result["summary"]) == 1000
