"""
Unit tests for intent recognition service.
T031 - Test intent extraction from user messages.
"""

import pytest
from unittest.mock import patch
from ai_kefu.services.intent_service import extract_intent, IntentType


def test_intent_type_enum():
    """Test IntentType enum values."""
    assert IntentType.CONSULTATION == "consultation"
    assert IntentType.COMPLAINT == "complaint"
    assert IntentType.REFUND == "refund"
    assert IntentType.LOGISTICS == "logistics"
    assert IntentType.AFTER_SALES == "after_sales"
    assert IntentType.OTHER == "other"


@patch('ai_kefu.services.intent_service.call_qwen')
def test_extract_intent_refund(mock_call_qwen):
    """Test intent extraction for refund queries."""
    mock_call_qwen.return_value = {
        "choices": [{
            "message": {
                "content": "refund"
            }
        }]
    }
    
    intent = extract_intent("我要退款")
    
    assert intent == IntentType.REFUND
    mock_call_qwen.assert_called_once()


@patch('ai_kefu.services.intent_service.call_qwen')
def test_extract_intent_logistics(mock_call_qwen):
    """Test intent extraction for logistics queries."""
    mock_call_qwen.return_value = {
        "choices": [{
            "message": {
                "content": "logistics"
            }
        }]
    }
    
    intent = extract_intent("我的订单什么时候发货")
    
    assert intent == IntentType.LOGISTICS


@patch('ai_kefu.services.intent_service.call_qwen')
def test_extract_intent_consultation(mock_call_qwen):
    """Test intent extraction for consultation queries."""
    mock_call_qwen.return_value = {
        "choices": [{
            "message": {
                "content": "consultation"
            }
        }]
    }
    
    intent = extract_intent("这个产品有什么功能")
    
    assert intent == IntentType.CONSULTATION


@patch('ai_kefu.services.intent_service.call_qwen')
def test_extract_intent_complaint(mock_call_qwen):
    """Test intent extraction for complaint queries."""
    mock_call_qwen.return_value = {
        "choices": [{
            "message": {
                "content": "complaint"
            }
        }]
    }
    
    intent = extract_intent("你们的服务太差了")
    
    assert intent == IntentType.COMPLAINT


@patch('ai_kefu.services.intent_service.call_qwen')
def test_extract_intent_api_error_returns_other(mock_call_qwen):
    """Test that API errors return OTHER intent."""
    mock_call_qwen.side_effect = Exception("API Error")
    
    intent = extract_intent("测试消息")
    
    assert intent == IntentType.OTHER


@patch('ai_kefu.services.intent_service.call_qwen')
def test_extract_intent_invalid_response_returns_other(mock_call_qwen):
    """Test that invalid responses return OTHER intent."""
    mock_call_qwen.return_value = {
        "choices": [{
            "message": {
                "content": "invalid_intent_type"
            }
        }]
    }
    
    intent = extract_intent("测试消息")
    
    assert intent == IntentType.OTHER


@patch('ai_kefu.services.intent_service.call_qwen')
def test_extract_intent_empty_message(mock_call_qwen):
    """Test intent extraction with empty message."""
    mock_call_qwen.return_value = {
        "choices": [{
            "message": {
                "content": "other"
            }
        }]
    }
    
    intent = extract_intent("")
    
    # Should still attempt extraction
    assert intent == IntentType.OTHER
