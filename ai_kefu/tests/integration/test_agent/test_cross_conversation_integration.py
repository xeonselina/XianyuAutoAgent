"""
Integration tests for cross-conversation context loading.
Tests end-to-end flow of loading context from multiple conversations.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta
from ai_kefu.agent.executor import AgentExecutor
from ai_kefu.models.session import Session


class TestCrossConversationIntegration:
    """Integration tests for cross-conversation context feature."""
    
    @pytest.fixture
    def executor_with_mocks(self):
        """Create executor with all dependencies mocked."""
        session_store = Mock()
        session_store.client = Mock()  # Redis
        
        conversation_store = Mock()
        config = Mock()
        
        executor = AgentExecutor(
            session_store=session_store,
            config=config,
            conversation_store=conversation_store
        )
        
        return executor, session_store, conversation_store
    
    def test_cross_conversation_context_workflow(self, executor_with_mocks):
        """Test the complete workflow of loading cross-conversation context."""
        executor, session_store, conversation_store = executor_with_mocks
        
        # Setup: User has multiple conversations
        conversation_store.get_user_fingerprint.return_value = {
            "message_count": 20,
            "last_message_at": "2026-04-15T10:00:00"
        }
        
        # Mock multiple conversations
        conversation_store.get_conversation_history_by_user_id.return_value = [
            {
                "chat_id": "chat-001",
                "role": "user",
                "content": "Do you have iPhone 15 Pro available for rental?",
                "timestamp": "2026-04-14T10:00:00"
            },
            {
                "chat_id": "chat-001",
                "role": "assistant",
                "content": "Yes, we have iPhone 15 Pro available.",
                "timestamp": "2026-04-14T10:01:00"
            },
            {
                "chat_id": "chat-002",
                "role": "user",
                "content": "Can I upgrade to the Pro Max version?",
                "timestamp": "2026-04-15T09:00:00"
            },
            {
                "chat_id": "chat-002",
                "role": "assistant",
                "content": "Yes, you can upgrade for an additional fee.",
                "timestamp": "2026-04-15T09:01:00"
            }
        ]
        
        # Mock cache miss
        session_store.client.get.return_value = None
        
        # Mock LLM summarization
        with patch('ai_kefu.agent.executor.call_qwen_fast') as mock_qwen:
            mock_qwen.return_value = "Customer previously inquired about iPhone 15 Pro rental and upgrade options."
            
            # Create new session and load context
            session = Session(session_id="test-001", user_id="user-001", messages=[])
            executor._load_user_history_as_context(session, "user-001")
            
            # Verify context was loaded and summarized
            assert "context_summary" in session.context
            assert session.context["context_summary"] is not None
            
            # Verify cache was set
            assert session_store.client.setex.called
    
    def test_cross_conversation_context_with_api_fallback(self, executor_with_mocks):
        """Test API fallback when MySQL history is unavailable."""
        executor, session_store, conversation_store = executor_with_mocks
        
        # Setup: API available but MySQL fails
        conversation_store.get_user_fingerprint.return_value = {
            "message_count": 15,
            "last_message_at": "2026-04-15T10:00:00"
        }
        
        conversation_store.get_conversation_history_by_user_id.side_effect = Exception("MySQL connection failed")
        
        # Mock cache miss
        session_store.client.get.return_value = None
        
        # Mock API history fetch with ThreadPoolExecutor
        with patch('ai_kefu.agent.executor.ThreadPoolExecutor') as mock_executor_class:
            mock_executor = Mock()
            mock_executor_class.return_value = mock_executor
            
            api_messages = [
                {
                    "role": "user",
                    "content": "Looking for camera rental",
                    "timestamp": datetime.now().isoformat()
                }
            ]
            mock_executor.submit.return_value.result.return_value = api_messages
            
            with patch('ai_kefu.agent.executor.call_qwen_fast') as mock_qwen:
                mock_qwen.return_value = "Customer is interested in camera rental."
                
                session = Session(session_id="test-001", user_id="user-001", messages=[])
                executor._load_user_history_as_context(session, "user-001")
                
                # Verify fallback worked
                assert "context_summary" in session.context


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
