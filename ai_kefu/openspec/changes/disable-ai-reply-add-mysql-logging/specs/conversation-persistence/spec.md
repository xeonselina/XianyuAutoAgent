# Conversation Persistence Specification

## ADDED Requirements

### Requirement: MySQL Conversation Storage
The system SHALL persistently store all Xianyu conversations to a MySQL database for future analysis and evaluation of the auto-reply system.

#### Scenario: User message storage
- **WHEN** a user sends a message through Xianyu
- **THEN** the message SHALL be saved to MySQL with chat_id, user_id, item_id, content, timestamp, and message_type=user
- **AND** the save operation SHALL complete within 500ms
- **AND** if database write fails, an error SHALL be logged but message processing SHALL continue

#### Scenario: Seller message storage
- **WHEN** a seller manually sends a message
- **THEN** the message SHALL be saved to MySQL with chat_id, user_id (seller), item_id, content, timestamp, and message_type=seller
- **AND** the save operation SHALL not block the message sending flow

#### Scenario: Conversation history retrieval
- **WHEN** requesting conversation history for a chat_id
- **THEN** the system SHALL return all messages ordered by timestamp ascending
- **AND** SHALL include user_id, content, message_type, timestamp, and item_id for each message

#### Scenario: Database connection failure
- **WHEN** MySQL connection is lost or unavailable
- **THEN** the system SHALL log the error with full context
- **AND** SHALL attempt to reconnect automatically with exponential backoff
- **AND** SHALL NOT crash the xianyu_interceptor process

### Requirement: AI Reply Configuration Control
The system SHALL support disabling AI auto-reply functionality while preserving the backend AI Agent API for independent testing.

#### Scenario: AI reply disabled (default)
- **WHEN** ENABLE_AI_REPLY environment variable is set to false or not set
- **THEN** xianyu_interceptor SHALL NOT call the backend AI Agent API
- **AND** SHALL still log all conversations to MySQL
- **AND** manual mode toggle SHALL still function normally

#### Scenario: AI reply enabled
- **WHEN** ENABLE_AI_REPLY environment variable is set to true
- **THEN** xianyu_interceptor SHALL call the backend AI Agent API as before
- **AND** SHALL log both user messages and AI responses to MySQL
- **AND** SHALL maintain the original behavior for manual mode

#### Scenario: Configuration validation on startup
- **WHEN** xianyu_interceptor starts
- **THEN** it SHALL validate all MySQL configuration parameters (host, port, user, password, database)
- **AND** SHALL attempt to connect to MySQL and log connection status
- **AND** if MySQL is unreachable, SHALL log a warning but continue startup
- **AND** SHALL log the ENABLE_AI_REPLY status clearly

### Requirement: Data Schema
The MySQL database SHALL use a well-defined schema to store conversation data with proper indexing for query performance.

#### Scenario: Conversations table structure
- **WHEN** the database is initialized
- **THEN** a `conversations` table SHALL be created with the following columns:
  - `id` BIGINT AUTO_INCREMENT PRIMARY KEY
  - `chat_id` VARCHAR(255) NOT NULL (Xianyu conversation ID)
  - `user_id` VARCHAR(255) NOT NULL (sender user ID)
  - `item_id` VARCHAR(255) (product ID, nullable)
  - `message_type` ENUM('user', 'seller', 'system') NOT NULL
  - `content` TEXT NOT NULL (message content)
  - `timestamp` BIGINT NOT NULL (Unix timestamp in milliseconds)
  - `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
  - `metadata` JSON (additional context, nullable)

#### Scenario: Database indexes
- **WHEN** the conversations table is created
- **THEN** indexes SHALL be created on:
  - `chat_id` for fast conversation retrieval
  - `user_id` for user-level analytics
  - `timestamp` for time-based queries
  - `(chat_id, timestamp)` composite index for ordered conversation history

#### Scenario: Character encoding
- **WHEN** storing messages with Chinese characters and emojis
- **THEN** the database SHALL use UTF8MB4 character encoding
- **AND** SHALL correctly store and retrieve all Unicode characters including emojis

### Requirement: Connection Pool Management
The system SHALL manage MySQL connections efficiently using a connection pool with automatic health checks and reconnection.

#### Scenario: Connection pool initialization
- **WHEN** ConversationStore is initialized
- **THEN** a connection pool SHALL be created with configurable min/max connections
- **AND** SHALL test initial connectivity and log the result

#### Scenario: Graceful shutdown
- **WHEN** xianyu_interceptor is shutting down
- **THEN** all active MySQL connections SHALL be closed gracefully
- **AND** pending write operations SHALL be completed or logged as failed

#### Scenario: Connection health monitoring
- **WHEN** a database operation fails with a connection error
- **THEN** the system SHALL mark the connection as unhealthy
- **AND** SHALL attempt to reconnect before the next operation
- **AND** SHALL use exponential backoff with max 3 retry attempts
