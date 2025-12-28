"""
End-to-end workflow test for complete conversation.
T034 - Test full conversation flow with knowledge search and completion.
"""

import pytest
from fastapi.testclient import TestClient
from ai_kefu.api.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.mark.skip(reason="Requires full implementation and running services")
def test_complete_conversation_flow(client):
    """Test complete conversation from start to completion."""
    # Step 1: User asks about refund
    response1 = client.post(
        "/chat",
        json={"query": "如何申请退款？"}
    )
    
    assert response1.status_code == 200
    session_id = response1.json()["session_id"]
    
    # Step 2: User provides order ID
    response2 = client.post(
        "/chat",
        json={
            "query": "订单号是 #12345",
            "session_id": session_id
        }
    )
    
    assert response2.status_code == 200
    
    # Step 3: Agent completes task
    # (This would happen automatically via complete_task tool)
    
    # Verify session status
    session_response = client.get(f"/sessions/{session_id}")
    assert session_response.status_code == 200
    session_data = session_response.json()
    
    # Should have multiple messages
    assert len(session_data["messages"]) >= 4  # 2 user + 2 assistant


@pytest.mark.skip(reason="Requires full implementation and running services")
def test_conversation_with_knowledge_search(client):
    """Test conversation that triggers knowledge search."""
    response = client.post(
        "/chat",
        json={"query": "退款政策是什么？"}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Response should contain information from knowledge base
    assert len(data["response"]) > 0


@pytest.mark.skip(reason="Requires full implementation and running services")
def test_multi_turn_conversation(client):
    """Test multi-turn conversation."""
    # Create session
    response1 = client.post("/chat", json={"query": "你好"})
    session_id = response1.json()["session_id"]
    
    # Turn 2
    response2 = client.post("/chat", json={"query": "我要退款", "session_id": session_id})
    assert response2.json()["turn_counter"] == 2
    
    # Turn 3
    response3 = client.post("/chat", json={"query": "订单 #12345", "session_id": session_id})
    assert response3.json()["turn_counter"] == 3
    
    # Turn 4
    response4 = client.post("/chat", json={"query": "谢谢", "session_id": session_id})
    assert response4.json()["turn_counter"] == 4
