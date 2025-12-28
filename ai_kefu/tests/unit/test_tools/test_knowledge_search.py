"""
Unit tests for knowledge_search tool.
T027 - Test knowledge search tool functionality.
"""

import pytest
from unittest.mock import Mock, patch
from ai_kefu.tools.knowledge_search import knowledge_search, get_tool_definition


def test_get_tool_definition():
    """Test knowledge_search tool definition."""
    tool_def = get_tool_definition()
    
    assert tool_def["name"] == "knowledge_search"
    assert "description" in tool_def
    assert "parameters" in tool_def
    assert tool_def["parameters"]["type"] == "object"
    assert "query" in tool_def["parameters"]["properties"]
    assert "top_k" in tool_def["parameters"]["properties"]
    assert "query" in tool_def["parameters"]["required"]


@patch('ai_kefu.tools.knowledge_search.generate_embedding')
@patch('ai_kefu.tools.knowledge_search.get_knowledge_store')
def test_knowledge_search_success(mock_get_store, mock_generate_embedding):
    """Test successful knowledge search."""
    # Mock embedding generation
    mock_generate_embedding.return_value = [0.1] * 1024
    
    # Mock knowledge store
    mock_store = Mock()
    mock_store.search.return_value = {
        "ids": [["kb_001", "kb_002"]],
        "documents": [["退款政策内容", "发货时间说明"]],
        "metadatas": [[
            {"title": "退款政策", "category": "售后"},
            {"title": "发货时间", "category": "物流"}
        ]],
        "distances": [[0.2, 0.3]]
    }
    mock_get_store.return_value = mock_store
    
    result = knowledge_search(query="退款流程", top_k=2)
    
    assert result["success"] is True
    assert len(result["results"]) == 2
    assert result["results"][0]["title"] == "退款政策"
    assert result["results"][1]["title"] == "发货时间"
    
    mock_generate_embedding.assert_called_once()
    mock_store.search.assert_called_once()


@patch('ai_kefu.tools.knowledge_search.generate_embedding')
def test_knowledge_search_embedding_error(mock_generate_embedding):
    """Test knowledge search with embedding error."""
    mock_generate_embedding.side_effect = Exception("Embedding API error")
    
    result = knowledge_search(query="测试")
    
    assert result["success"] is False
    assert "error" in result
    assert "Embedding API error" in result["error"]


@patch('ai_kefu.tools.knowledge_search.generate_embedding')
@patch('ai_kefu.tools.knowledge_search.get_knowledge_store')
def test_knowledge_search_no_results(mock_get_store, mock_generate_embedding):
    """Test knowledge search with no results."""
    mock_generate_embedding.return_value = [0.1] * 1024
    
    mock_store = Mock()
    mock_store.search.return_value = {
        "ids": [[]],
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]]
    }
    mock_get_store.return_value = mock_store
    
    result = knowledge_search(query="不存在的查询")
    
    assert result["success"] is True
    assert len(result["results"]) == 0
    assert result["message"] == "未找到相关信息"


def test_knowledge_search_default_top_k():
    """Test knowledge search with default top_k."""
    with patch('ai_kefu.tools.knowledge_search.generate_embedding') as mock_embed, \
         patch('ai_kefu.tools.knowledge_search.get_knowledge_store') as mock_store:
        
        mock_embed.return_value = [0.1] * 1024
        mock_store_instance = Mock()
        mock_store_instance.search.return_value = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]]
        }
        mock_store.return_value = mock_store_instance
        
        knowledge_search(query="测试")
        
        # Verify default top_k=5 is used
        call_args = mock_store_instance.search.call_args
        assert call_args[1]["top_k"] == 5
