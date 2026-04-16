"""
Unit tests for cross-conversation context loading.
Tests the new _load_user_history_as_context() feature.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, PropertyMock
from datetime import datetime, timedelta
from ai_kefu.agent.executor import AgentExecutor
from ai_kefu.models.session import Session, Message
from ai_kefu.config.constants import MessageRole


@pytest.fixture
def mock_session_store():
    """Create a mock session store."""
    mock_store = Mock()
    mock_store.client = Mock()  # Redis client
    return mock_store


@pytest.fixture
def mock_conversation_store():
    """Create a mock conversation store."""
    mock_store = Mock()
    return mock_store


@pytest.fixture
def mock_config():
    """Create a mock config."""
    mock_cfg = Mock()
    return mock_cfg


@pytest.fixture
def agent_executor(mock_session_store, mock_config, mock_conversation_store):
    """Create an AgentExecutor instance for testing."""
    executor = AgentExecutor(
        session_store=mock_session_store,
        config=mock_config,
        conversation_store=mock_conversation_store
    )
    return executor


class TestCrossConversationContextLoading:
    """Tests for cross-conversation context loading."""
    
    def test_load_user_history_as_context_cache_hit(self, agent_executor, mock_session_store):
        """Test that cached summary is used when fingerprint matches."""
        session = Session(session_id="test-001", user_id="user-001", messages=[])
        
        # Mock Redis cache hit
        cached_data = {
            "summary": "Previous conversations about iPhone rental",
            "is_returning_customer": True,
            "fingerprint": {"message_count": 10, "last_message_at": "2026-04-15"}
        }
        mock_session_store.client.get.return_value = '{"summary": "Previous conversations about iPhone rental", "is_returning_customer": true, "fingerprint": {"message_count": 10, "last_message_at": "2026-04-15"}}'
        
        # Mock user fingerprint (no change)
        with patch.object(agent_executor.conversation_store, 'get_user_fingerprint') as mock_finger:
            mock_finger.return_value = {"message_count": 10, "last_message_at": "2026-04-15"}
            
            agent_executor._load_user_history_as_context(session, "user-001")
            
            # Verify cache was used
            assert session.context.get("context_summary") == "Previous conversations about iPhone rental"
            assert session.context.get("is_returning_customer") is True
    
    def test_load_user_history_as_context_cache_miss_no_history(self, agent_executor, mock_session_store):
        """Test handling when no cached data and no history exists."""
        session = Session(session_id="test-001", user_id="user-001", messages=[])
        
        # Mock cache miss
        mock_session_store.client.get.return_value = None
        
        # Mock no history
        with patch.object(agent_executor.conversation_store, 'get_user_fingerprint') as mock_finger:
            mock_finger.return_value = {"message_count": 0, "last_message_at": None}
            
            with patch.object(agent_executor.conversation_store, 'get_conversation_history_by_user_id') as mock_hist:
                mock_hist.return_value = []
                
                agent_executor._load_user_history_as_context(session, "user-001")
                
                # Verify context is set appropriately
                assert "context_summary" in session.context
    
    def test_compress_by_time_proximity_recent_messages_verbatim(self, agent_executor):
        """Test that recent 20 messages are kept verbatim."""
        # Create 25 messages with timestamps
        messages = []
        base_time = datetime.now()
        for i in range(25):
            msg = {
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"Message {i}",
                "timestamp": (base_time - timedelta(minutes=25-i)).isoformat()
            }
            messages.append(msg)
        
        compressed = agent_executor._compress_by_time_proximity(messages)
        
        # Verify recent 20 are preserved
        assert len([m for m in compressed if m.get("compression_type") == "verbatim"]) >= 20
    
    def test_compress_by_time_proximity_old_messages_summarized(self, agent_executor):
        """Test that messages 20-60 are summarized."""
        # Create 60 messages with timestamps
        messages = []
        base_time = datetime.now()
        for i in range(60):
            msg = {
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"Message {i}",
                "timestamp": (base_time - timedelta(hours=24) - timedelta(minutes=60-i)).isoformat()
            }
            messages.append(msg)
        
        compressed = agent_executor._compress_by_time_proximity(messages)
        
        # Verify some messages were summarized
        assert len(compressed) < len(messages)
    
    @patch('ai_kefu.agent.executor.ThreadPoolExecutor')
    def test_fetch_xianyu_api_history_timeout(self, mock_executor_class, agent_executor):
        """Test that API fetch handles timeout gracefully."""
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        # Simulate timeout
        mock_executor.submit.return_value.result.side_effect = TimeoutError("API timeout")
        
        result = agent_executor._fetch_xianyu_api_history("user-001")
        
        # Verify graceful degradation
        assert result == []
    
    @patch('ai_kefu.agent.executor.ThreadPoolExecutor')
    def test_fetch_xianyu_api_history_success(self, mock_executor_class, agent_executor):
        """Test successful API history fetch."""
        mock_executor = Mock()
        mock_executor_class.return_value = mock_executor
        
        expected_messages = [
            {
                "role": "user",
                "content": "Do you have iPhone 15 Pro available?",
                "timestamp": datetime.now().isoformat()
            }
        ]
        
        mock_executor.submit.return_value.result.return_value = expected_messages
        
        result = agent_executor._fetch_xianyu_api_history("user-001")
        
        # Verify messages returned
        assert len(result) > 0
    
    def test_get_user_summary_cache_key(self, agent_executor):
        """Test cache key generation."""
        cache_key = agent_executor._get_user_summary_cache_key("user-001")
        
        assert cache_key == "user_history_summary:user-001"
    
    def test_get_cached_user_summary_not_found(self, agent_executor, mock_session_store):
        """Test cache retrieval when key doesn't exist."""
        mock_session_store.client.get.return_value = None
        
        result = agent_executor._get_cached_user_summary("user-001")
        
        assert result is None
    
    def test_get_cached_user_summary_found(self, agent_executor, mock_session_store):
        """Test cache retrieval when key exists."""
        import json
        
        cache_data = {
            "summary": "Test summary",
            "is_returning_customer": True,
            "fingerprint": {"message_count": 5, "last_message_at": "2026-04-15"}
        }
        mock_session_store.client.get.return_value = json.dumps(cache_data)
        
        result = agent_executor._get_cached_user_summary("user-001")
        
        assert result is not None
        assert result["summary"] == "Test summary"
        assert result["is_returning_customer"] is True
    
    def test_set_cached_user_summary(self, agent_executor, mock_session_store):
        """Test cache storage."""
        agent_executor._set_cached_user_summary(
            user_id="user-001",
            summary="Test summary",
            is_returning_customer=True,
            fingerprint={"message_count": 5, "last_message_at": "2026-04-15"}
        )
        
        # Verify cache.setex was called
        assert mock_session_store.client.setex.called
        call_args = mock_session_store.client.setex.call_args
        
        # Verify TTL is 1 hour (3600 seconds)
        assert call_args[0][2] == 3600


class TestContextInjection:
    """Tests for context injection into session."""
    
    def test_context_injected_into_session(self, agent_executor):
        """Test that context is properly injected into session."""
        session = Session(session_id="test-001", user_id="user-001", messages=[])
        
        test_context = "Test context about previous rentals"
        
        with patch.object(agent_executor.conversation_store, 'get_user_fingerprint'):
            with patch.object(agent_executor.conversation_store, 'get_conversation_history_by_user_id') as mock_hist:
                mock_hist.return_value = [
                    {
                        "role": "user",
                        "content": "Previous rental query",
                        "timestamp": datetime.now().isoformat()
                    }
                ]
                
                # Mock the summarization
                with patch('ai_kefu.agent.executor.call_qwen_fast') as mock_qwen:
                    mock_qwen.return_value = test_context
                    
                    agent_executor._load_user_history_as_context(session, "user-001")
                    
                    # Verify context was set
                    assert session.context.get("context_summary") is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
