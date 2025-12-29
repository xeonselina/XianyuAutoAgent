# Implementation Tasks

## 1. Remove Legacy Code
- [x] 1.1 Delete `main.py` (old XianyuReplyBot-based launcher)
- [x] 1.2 Delete `XianyuAgent.py` (old AI reply bot implementation)
- [x] 1.3 Delete `XianyuApis.py` if not used elsewhere
- [x] 1.4 Delete `context_manager.py` (old SQLite context manager)
- [x] 1.5 Delete `messaging_core.py` (replaced by xianyu_interceptor)
- [x] 1.6 Delete `transports.py` (replaced by xianyu_interceptor)
- [x] 1.7 Delete `browser_controller.py` (replaced by xianyu_interceptor)
- [x] 1.8 Delete `cdp_interceptor.py` (replaced by xianyu_interceptor)
- [x] 1.9 Move remaining useful utilities to xianyu_interceptor if needed
- [x] 1.10 Update imports in any files that reference deleted modules

## 2. Database Schema and Dependencies
- [x] 2.1 Create MySQL migration script (`migrations/001_create_conversations_table.sql`)
- [x] 2.2 Add MySQL driver dependency to `requirements.txt` (pymysql with cryptography)
- [x] 2.3 Test MySQL connection with sample script

## 3. Data Models
- [x] 3.1 Create conversation data model in `xianyu_interceptor/conversation_models.py`
- [x] 3.2 Define ConversationMessage model with all required fields
- [x] 3.3 Add validation for required fields (chat_id, user_id, content, etc.)

## 4. Conversation Storage Layer
- [x] 4.1 Implement `ConversationStore` class in `xianyu_interceptor/conversation_store.py`
- [x] 4.2 Add MySQL connection pool using pymysql
- [x] 4.3 Implement `save_message()` method with error handling
- [x] 4.4 Implement `get_conversation_history()` query method
- [x] 4.5 Add connection health check and auto-reconnect logic
- [x] 4.6 Add proper connection cleanup in `close()` method

## 5. Configuration Management
- [x] 5.1 Add ENABLE_AI_REPLY flag to `xianyu_interceptor/config.py`
- [x] 5.2 Add MySQL configuration fields to `xianyu_interceptor/config.py`
- [x] 5.3 Update `.env.example` with new configuration options
- [x] 5.4 Add configuration validation with helpful error messages

## 6. Message Handler Integration
- [x] 6.1 Update `MessageHandler.__init__()` to accept ConversationStore
- [x] 6.2 Add conversation logging in `handle_message()` before AI processing
- [x] 6.3 Add conditional check for ENABLE_AI_REPLY flag in `_process_with_agent()`
- [x] 6.4 Ensure user messages are logged with proper metadata
- [x] 6.5 Ensure seller manual messages are also logged
- [x] 6.6 Handle database write failures gracefully (log error but don't crash)

## 7. Main Integration Updates
- [x] 7.1 Initialize MySQL connection pool in `main_integration.py`
- [x] 7.2 Create ConversationStore instance during setup
- [x] 7.3 Pass ConversationStore to MessageHandler initialization
- [x] 7.4 Add MySQL connectivity check on startup
- [x] 7.5 Add graceful shutdown for database connections
- [x] 7.6 Create new main entry point script for xianyu_interceptor

## 8. Testing
- [ ] 8.1 Write unit test for ConversationStore.save_message()
- [ ] 8.2 Write unit test for ConversationStore connection handling
- [ ] 8.3 Write integration test for message logging flow
- [ ] 8.4 Test with ENABLE_AI_REPLY=false (messages logged, no AI calls)
- [ ] 8.5 Test with ENABLE_AI_REPLY=true (messages logged + AI replies)
- [ ] 8.6 Test database failure scenarios (connection loss, reconnect)
- [ ] 8.7 Test manual mode toggle with conversation logging

## 9. Documentation
- [ ] 9.1 Update README to remove old main.py references
- [ ] 9.2 Add xianyu_interceptor as the primary bot launcher in README
- [ ] 9.3 Document MySQL setup instructions
- [ ] 9.4 Document ENABLE_AI_REPLY configuration option
- [ ] 9.5 Document database schema and table structure
- [ ] 9.6 Add example queries for analyzing conversation data
- [ ] 9.7 Update architecture diagrams if they exist
