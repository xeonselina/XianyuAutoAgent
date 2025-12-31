-- Migration: Create knowledge_entries table for MySQL-backed knowledge management
-- Created: 2025-12-30
-- Purpose: Migrate knowledge base from ChromaDB-only to MySQL + ChromaDB hybrid storage

CREATE TABLE IF NOT EXISTS knowledge_entries (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT 'Auto-increment primary key',
    kb_id VARCHAR(50) NOT NULL UNIQUE COMMENT 'Stable knowledge base ID (e.g., kb_001)',

    -- Content
    title VARCHAR(500) NOT NULL COMMENT 'Knowledge entry title',
    content TEXT NOT NULL COMMENT 'Full knowledge content',

    -- Classification
    category VARCHAR(100) DEFAULT NULL COMMENT 'Category tag',
    tags JSON DEFAULT NULL COMMENT 'Array of tag strings',

    -- Metadata
    source VARCHAR(200) DEFAULT NULL COMMENT 'Source of knowledge (e.g., Official Documentation)',
    priority INT DEFAULT 0 COMMENT 'Priority for sorting (0-100)',
    active BOOLEAN DEFAULT TRUE COMMENT 'Is entry active',

    -- Audit trail
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Creation timestamp',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp',

    -- Indexes for performance
    INDEX idx_kb_id (kb_id),
    INDEX idx_category (category),
    INDEX idx_active (active),
    INDEX idx_priority (priority),
    INDEX idx_created_at (created_at),
    FULLTEXT INDEX idx_content_search (title, content)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Knowledge base entries - MySQL source of truth for ChromaDB vector search';

-- Rollback script (for reference, run manually if needed):
-- DROP TABLE IF EXISTS knowledge_entries;
