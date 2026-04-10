"""
Integration test for get_buyer_info tool.
Tests that the tool is properly exposed and can be called.
"""

import json
from ai_kefu.tools.xianyu.get_buyer_info import get_tool_definition, get_buyer_info


def test_tool_definition():
    """Test that get_buyer_info_definition returns valid tool structure."""
    definition = get_tool_definition()
    
    # Check required fields
    assert "name" in definition
    assert definition["name"] == "get_buyer_info"
    
    assert "description" in definition
    assert "查询闲鱼买家信息" in definition["description"]
    
    assert "parameters" in definition
    params = definition["parameters"]
    assert params["type"] == "object"
    assert "properties" in params
    assert "buyer_id" in params["properties"]
    assert "required" in params
    assert "buyer_id" in params["required"]
    
    print("✓ Tool definition is valid")
    return True


def test_tool_registration():
    """Test that get_buyer_info can be imported in executor."""
    from ai_kefu.tools.xianyu import get_buyer_info, get_buyer_info_definition
    
    assert callable(get_buyer_info)
    assert callable(get_buyer_info_definition)
    
    print("✓ Tool is properly exported from __init__.py")
    return True


def test_tool_in_executor():
    """Test that get_buyer_info is registered in executor."""
    from ai_kefu.agent.executor import AgentExecutor
    from ai_kefu.storage.session_store import SessionStore
    from ai_kefu.models.session import Session
    
    # Create a minimal executor to check tool registration
    store = SessionStore()
    executor = AgentExecutor(session_store=store)
    
    # Check that get_buyer_info is registered
    tool = executor.tools_registry.get_tool("get_buyer_info")
    assert tool is not None, "get_buyer_info tool not found in registry"
    
    # Get all tools and verify get_buyer_info is in the list
    all_tools = executor.tools_registry.get_all_tools()
    assert "get_buyer_info" in all_tools, "get_buyer_info not in tool list"
    
    print("✓ Tool is registered in AgentExecutor")
    return True


def test_tool_definition_completeness():
    """Test that tool definition includes all important information."""
    definition = get_tool_definition()
    
    # Check description includes use cases
    desc = definition["description"]
    assert "重复客户" in desc or "has_bought" in desc
    assert "购买能力" in desc or "buy_count" in desc
    assert "地区" in desc or "location" in desc
    
    # Check parameter description
    buyer_id_param = definition["parameters"]["properties"]["buyer_id"]
    assert "description" in buyer_id_param
    assert "买家" in buyer_id_param["description"] or "buyer" in buyer_id_param["description"]
    
    print("✓ Tool definition is complete and informative")
    return True


if __name__ == "__main__":
    print("\n=== Testing get_buyer_info Tool Integration ===\n")
    
    try:
        test_tool_definition()
        test_tool_registration()
        test_tool_definition_completeness()
        
        print("\n✓ Running executor registration test...")
        test_tool_in_executor()
        
        print("\n=== All tests passed! ===\n")
        print("Summary:")
        print("- Tool definition is valid and complete")
        print("- Tool is exported from xianyu/__init__.py")
        print("- Tool is registered in AgentExecutor.tools_registry")
        print("- Tool definition includes proper descriptions and parameters")
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
