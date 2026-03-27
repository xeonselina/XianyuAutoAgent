-- Migration: Create system_prompts table for dynamic system prompt management
-- Created: 2026-03-25
-- Purpose: Store system prompts in database for runtime editing without code changes

CREATE TABLE IF NOT EXISTS system_prompts (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT 'Auto-increment primary key',
    prompt_key VARCHAR(100) NOT NULL COMMENT 'Prompt identifier (e.g., rental_system, general_system)',

    -- Content
    title VARCHAR(200) NOT NULL COMMENT 'Human-readable title',
    content TEXT NOT NULL COMMENT 'Full system prompt content (supports template variables like {today_str})',
    description VARCHAR(500) DEFAULT NULL COMMENT 'Description of what this prompt does',

    -- Status
    active BOOLEAN DEFAULT FALSE COMMENT 'Is this the active version for its prompt_key',

    -- Audit trail
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Creation timestamp',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp',

    -- Indexes
    INDEX idx_prompt_key (prompt_key),
    INDEX idx_active (active),
    INDEX idx_prompt_key_active (prompt_key, active),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='System prompts for AI agent - supports versioning and runtime editing';

-- Rollback script (for reference, run manually if needed):
-- DROP TABLE IF EXISTS system_prompts;
