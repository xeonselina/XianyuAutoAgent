-- Migration: Create conversations table for storing Xianyu chat history
-- Created: 2025-12-28

CREATE TABLE IF NOT EXISTS conversations (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT 'Auto-increment primary key',
    chat_id VARCHAR(255) NOT NULL COMMENT 'Xianyu chat ID',
    user_id VARCHAR(255) NOT NULL COMMENT 'User ID who sent the message',
    seller_id VARCHAR(255) COMMENT 'Seller ID (owner of the account)',
    item_id VARCHAR(255) COMMENT 'Item ID if available',

    message_content TEXT NOT NULL COMMENT 'Message content',
    message_type ENUM('user', 'seller', 'system') NOT NULL COMMENT 'Message sender type',

    session_id VARCHAR(255) COMMENT 'AI Agent session ID if AI was used',
    agent_response TEXT COMMENT 'AI Agent response if this was an AI reply',

    context JSON COMMENT 'Additional context metadata',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Message timestamp',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Record update timestamp',

    INDEX idx_chat_id (chat_id),
    INDEX idx_user_id (user_id),
    INDEX idx_seller_id (seller_id),
    INDEX idx_created_at (created_at),
    INDEX idx_chat_created (chat_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Xianyu conversation history';

-- Optional: Create a view for easier querying of conversations
CREATE OR REPLACE VIEW conversation_summary AS
SELECT
    chat_id,
    user_id,
    seller_id,
    item_id,
    COUNT(*) as message_count,
    MIN(created_at) as first_message_at,
    MAX(created_at) as last_message_at,
    SUM(CASE WHEN message_type = 'user' THEN 1 ELSE 0 END) as user_messages,
    SUM(CASE WHEN message_type = 'seller' THEN 1 ELSE 0 END) as seller_messages,
    SUM(CASE WHEN agent_response IS NOT NULL THEN 1 ELSE 0 END) as ai_replies
FROM conversations
GROUP BY chat_id, user_id, seller_id, item_id;
