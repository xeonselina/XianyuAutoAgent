-- Migration: Add user_nickname column to conversations table
-- Created: 2026-03-30
-- Purpose: Store user nickname (from reminderTitle) alongside user_id for better readability

-- Add user_nickname column (idempotent: only adds if not exists)
-- Note: The application code also auto-adds this column on startup via _ensure_table_exists
SET @column_exists = (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'conversations'
      AND COLUMN_NAME = 'user_nickname'
);

SET @sql = IF(@column_exists = 0,
    'ALTER TABLE conversations ADD COLUMN user_nickname VARCHAR(255) COMMENT ''User nickname (from reminderTitle)'' AFTER user_id',
    'SELECT ''Column user_nickname already exists'' AS info'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Rollback script (for reference, run manually if needed):
-- ALTER TABLE conversations DROP COLUMN user_nickname;
