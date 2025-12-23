"""
Integration tests for /chat endpoint (synchronous).
T032 - Test chat endpoint end-to-end.
"""

import pytest
from fastapi.testclient import TestClient
from ai_kefu.api.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.mark.skip(reason="Requires full implementation and running services")
def test_chat_endpoint_basic(client):
    """Test basic chat endpoint."""
    response = client.post(
        "/chat",
        json={
            "query": "如何退款？",
            "user_id": "test_user_001"
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert "session_id" in data
    assert "response" in data
    assert "status" in data
    assert data["status"] == "active"


@pytest.mark.skip(reason="Requires full implementation and running services")
def test_chat_endpoint_with_session_id(client):
    """Test chat endpoint with existing session."""
    # First message
    response1 = client.post(
        "/chat",
        json={"query": "你好"}
    )
    
    session_id = response1.json()["session_id"]
    
    # Second message with same session
    response2 = client.post(
        "/chat",
        json={
            "query": "我要退款",
            "session_id": session_id
        }
    )
    
    assert response2.status_code == 200
    assert response2.json()["session_id"] == session_id


@pytest.mark.skip(reason="Requires full implementation and running services")
def test_chat_endpoint_validation_error(client):
    """Test chat endpoint with validation error."""
    response = client.post(
        "/chat",
        json={}  # Missing required 'query' field
    )
    
    assert response.status_code == 422  # Validation error


@pytest.mark.skip(reason="Requires full implementation and running services")
def test_chat_endpoint_empty_query(client):
    """Test chat endpoint with empty query."""
    response = client.post(
        "/chat",
        json={"query": ""}
    )
    
    assert response.status_code == 422


@pytest.mark.skip(reason="Requires full implementation and running services")
def test_chat_endpoint_with_context(client):
    """Test chat endpoint with additional context."""
    response = client.post(
        "/chat",
        json={
            "query": "我要退款",
            "context": {
                "order_id": "12345",
                "product": "测试产品"
            }
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
