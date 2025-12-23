"""
Unit tests for ToolRegistry.
T026 - Test tool registration, retrieval, and Qwen format conversion.
"""

import pytest
from ai_kefu.tools.tool_registry import ToolRegistry


def test_tool_registry_initialization():
    """Test ToolRegistry initialization."""
    registry = ToolRegistry()
    assert registry is not None
    assert len(registry.get_all_tools()) == 0


def test_register_tool():
    """Test registering a tool."""
    registry = ToolRegistry()
    
    def sample_tool(arg1: str, arg2: int = 5):
        """Sample tool for testing."""
        return f"Result: {arg1}, {arg2}"
    
    tool_def = {
        "name": "sample_tool",
        "description": "A sample tool",
        "parameters": {
            "type": "object",
            "properties": {
                "arg1": {"type": "string", "description": "First argument"},
                "arg2": {"type": "integer", "description": "Second argument", "default": 5}
            },
            "required": ["arg1"]
        }
    }
    
    registry.register_tool("sample_tool", sample_tool, tool_def)
    
    assert "sample_tool" in registry.get_all_tools()
    assert registry.get_tool("sample_tool") is not None


def test_get_tool_not_found():
    """Test getting a non-existent tool."""
    registry = ToolRegistry()
    assert registry.get_tool("non_existent") is None


def test_to_qwen_format():
    """Test converting tools to Qwen Function Calling format."""
    registry = ToolRegistry()
    
    def tool1(query: str):
        """Tool 1."""
        pass
    
    tool_def = {
        "name": "tool1",
        "description": "Tool 1 description",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Query"}
            },
            "required": ["query"]
        }
    }
    
    registry.register_tool("tool1", tool1, tool_def)
    
    qwen_format = registry.to_qwen_format()
    
    assert len(qwen_format) == 1
    assert qwen_format[0]["type"] == "function"
    assert qwen_format[0]["function"]["name"] == "tool1"
    assert qwen_format[0]["function"]["description"] == "Tool 1 description"


def test_execute_tool():
    """Test executing a registered tool."""
    registry = ToolRegistry()
    
    def add_tool(a: int, b: int):
        """Add two numbers."""
        return a + b
    
    tool_def = {
        "name": "add_tool",
        "description": "Add numbers",
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"}
            },
            "required": ["a", "b"]
        }
    }
    
    registry.register_tool("add_tool", add_tool, tool_def)
    
    result = registry.execute_tool("add_tool", {"a": 3, "b": 5})
    assert result == 8


def test_execute_tool_not_found():
    """Test executing a non-existent tool raises error."""
    registry = ToolRegistry()
    
    with pytest.raises(Exception):
        registry.execute_tool("non_existent", {})
