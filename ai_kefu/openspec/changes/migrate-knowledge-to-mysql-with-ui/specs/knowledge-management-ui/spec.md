# Spec: Knowledge Management UI and MySQL Storage

## ADDED Requirements

### Requirement: MySQL Knowledge Entry Storage
The system SHALL store knowledge base entries in MySQL as the authoritative source of truth, with ChromaDB serving as a synchronized search index.

#### Scenario: Create knowledge entry
- **WHEN** a knowledge entry is created via API with title, content, category, tags, source, and priority
- **THEN** the system SHALL insert a record into the `knowledge_entries` MySQL table with a unique `kb_id`
- **AND** SHALL generate a vector embedding from the content using Qwen text-embedding-v3
- **AND** SHALL add the embedding to ChromaDB collection `knowledge_base` with `kb_id` as the document ID
- **AND** SHALL set `created_at` and `updated_at` timestamps
- **AND** SHALL return HTTP 201 with the created entry including the auto-generated `kb_id`

#### Scenario: Update knowledge entry
- **WHEN** a knowledge entry is updated via API with new content or metadata
- **THEN** the system SHALL update the corresponding row in MySQL by `kb_id`
- **AND** if content changed, SHALL regenerate the vector embedding
- **AND** SHALL update the ChromaDB document with new embedding and metadata
- **AND** SHALL update the `updated_at` timestamp
- **AND** SHALL return HTTP 200 with the updated entry

#### Scenario: Delete knowledge entry
- **WHEN** a knowledge entry is deleted via API
- **THEN** the system SHALL delete the row from MySQL `knowledge_entries` table
- **AND** SHALL delete the corresponding document from ChromaDB collection
- **AND** SHALL return HTTP 200 with success confirmation

#### Scenario: List knowledge entries with pagination
- **WHEN** requesting a list of knowledge entries with offset and limit parameters
- **THEN** the system SHALL query MySQL (not ChromaDB) with pagination
- **AND** SHALL support filtering by `active` status (default: active_only=true)
- **AND** SHALL return entries ordered by `priority DESC, created_at DESC`
- **AND** SHALL include total count for pagination UI
- **AND** SHALL complete the query within 500ms for up to 1000 entries

#### Scenario: Handle MySQL-ChromaDB sync failure
- **WHEN** MySQL write succeeds but ChromaDB write fails
- **THEN** the system SHALL log the sync error with full context (kb_id, error message)
- **AND** SHALL still return success to the client (MySQL is source of truth)
- **AND** SHALL NOT roll back the MySQL transaction
- **AND** the entry SHALL be searchable via MySQL but not via vector search until manual sync

### Requirement: Bulk Knowledge Operations API
The system SHALL provide API endpoints for bulk importing, exporting, and initializing knowledge entries to streamline knowledge management workflows.

#### Scenario: Bulk import from JSON
- **WHEN** posting to `/knowledge/bulk` with an array of knowledge entry objects
- **THEN** the system SHALL validate each entry (required fields: title, content)
- **AND** if `overwrite_existing=false` (default), SHALL skip entries with existing `kb_id`
- **AND** if `overwrite_existing=true`, SHALL update existing entries
- **AND** SHALL insert valid entries into MySQL and sync to ChromaDB
- **AND** SHALL return a summary: `{imported: N, skipped: M, errors: [...]}`
- **AND** SHALL process at least 50 entries per second

#### Scenario: Initialize default knowledge
- **WHEN** posting to `/knowledge/init-defaults`
- **THEN** the system SHALL check if entries with kb_ids `kb_001` through `kb_006` exist
- **AND** SHALL create only non-existing entries with predefined content:
  - kb_001: 退款政策 (Refund Policy)
  - kb_002: 发货时间 (Shipping Time)
  - kb_003: 会员积分规则 (Membership Points)
  - kb_004: 商品质量问题处理 (Quality Issues)
  - kb_005: 支付方式 (Payment Methods)
  - kb_006: 优惠券使用规则 (Coupon Rules)
- **AND** SHALL be idempotent (safe to call multiple times)
- **AND** SHALL return `{initialized: N, skipped: M, message: "..."}`

#### Scenario: Export all knowledge as JSON
- **WHEN** requesting GET `/knowledge/export?active_only=true`
- **THEN** the system SHALL query all knowledge entries from MySQL (filtered by active if specified)
- **AND** SHALL serialize entries as JSON array with all fields except `id` (use `kb_id` instead)
- **AND** SHALL return Content-Type: application/json
- **AND** SHALL support downloading as a file (Content-Disposition: attachment)

### Requirement: Web UI for Knowledge Management
The system SHALL provide a Vue.js single-page application for managing knowledge entries through a visual interface.

#### Scenario: View knowledge list
- **WHEN** accessing `/ui/knowledge` in a web browser
- **THEN** the system SHALL serve the Vue SPA with a knowledge list page
- **AND** the list SHALL display columns: Title, Category, Tags, Priority, Active, Created At
- **AND** SHALL support client-side search/filter by title or content (via API call)
- **AND** SHALL support pagination with configurable page size (default: 20)
- **AND** SHALL display total count and current page range

#### Scenario: Create knowledge entry via UI
- **WHEN** clicking "New Knowledge" button in the UI
- **THEN** a modal form SHALL appear with fields:
  - Title (required, max 500 chars)
  - Content (required, textarea, max 10000 chars)
  - Category (optional, dropdown with existing categories + custom input)
  - Tags (optional, multi-input chips)
  - Source (optional, text input)
  - Priority (optional, number input 0-100, default 0)
  - Active (checkbox, default checked)
- **AND** form submission SHALL POST to `/knowledge/`
- **AND** on success, SHALL close modal and refresh the list
- **AND** on error, SHALL display validation errors inline

#### Scenario: Edit knowledge entry via UI
- **WHEN** clicking the "Edit" button on a knowledge entry row
- **THEN** the modal form SHALL open pre-filled with existing values
- **AND** form submission SHALL PUT to `/knowledge/{kb_id}`
- **AND** on success, SHALL update the list without full page reload
- **AND** SHALL show "Last updated: {timestamp}" in the form

#### Scenario: Delete knowledge entry via UI
- **WHEN** clicking the "Delete" button on a knowledge entry row
- **THEN** a confirmation dialog SHALL appear: "Are you sure you want to delete '{title}'?"
- **AND** on confirmation, SHALL DELETE to `/knowledge/{kb_id}`
- **AND** on success, SHALL remove the row from the list
- **AND** on error, SHALL display an error message

#### Scenario: Bulk import via UI
- **WHEN** clicking "Import JSON" button
- **THEN** a file upload dialog SHALL appear accepting `.json` files
- **AND** SHALL validate JSON structure client-side (array of objects with title/content)
- **AND** SHALL display file preview showing number of entries
- **AND** SHALL POST to `/knowledge/bulk` with parsed JSON
- **AND** on success, SHALL display import summary: "Imported 10, Skipped 2"
- **AND** SHALL refresh the knowledge list

#### Scenario: Initialize default knowledge via UI
- **WHEN** clicking "Initialize Defaults" button (visible when DB is empty or always available)
- **THEN** a confirmation dialog SHALL appear: "This will add 6 default knowledge entries"
- **AND** on confirmation, SHALL POST to `/knowledge/init-defaults`
- **AND** SHALL display loading indicator during initialization
- **AND** on success, SHALL show success message and refresh list
- **AND** on error (e.g., already initialized), SHALL display informative message

#### Scenario: Export knowledge via UI
- **WHEN** clicking "Export All" button
- **THEN** SHALL GET from `/knowledge/export`
- **AND** SHALL trigger browser download of `knowledge_export_{timestamp}.json`
- **AND** the downloaded file SHALL be valid JSON importable via bulk import

### Requirement: MySQL Database Schema
The system SHALL create and maintain a `knowledge_entries` table in MySQL with proper schema design for CRUD operations and audit tracking.

#### Scenario: Table structure and constraints
- **WHEN** the database migration is applied
- **THEN** a table named `knowledge_entries` SHALL be created with:
  - `id` BIGINT AUTO_INCREMENT PRIMARY KEY
  - `kb_id` VARCHAR(50) UNIQUE NOT NULL (stable knowledge ID like 'kb_001')
  - `title` VARCHAR(500) NOT NULL
  - `content` TEXT NOT NULL
  - `category` VARCHAR(100) NULL
  - `tags` JSON NULL (array of strings)
  - `source` VARCHAR(200) NULL
  - `priority` INT DEFAULT 0
  - `active` BOOLEAN DEFAULT TRUE
  - `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  - `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
- **AND** SHALL use `utf8mb4` character set with `utf8mb4_unicode_ci` collation
- **AND** SHALL use InnoDB engine

#### Scenario: Database indexes for performance
- **WHEN** the `knowledge_entries` table is created
- **THEN** the following indexes SHALL be created:
  - INDEX `idx_kb_id` on `kb_id` (unique constraint already creates this)
  - INDEX `idx_category` on `category`
  - INDEX `idx_active` on `active`
  - INDEX `idx_priority` on `priority`
  - INDEX `idx_created_at` on `created_at`
  - FULLTEXT INDEX `idx_content_search` on (`title`, `content`) for MySQL full-text search (future use)

#### Scenario: Query performance for pagination
- **WHEN** querying `/knowledge/?limit=20&offset=0` from a database with 500 entries
- **THEN** the MySQL query SHALL complete within 100ms
- **AND** SHALL use the appropriate index for filtering and sorting
- **AND** SHALL return exactly 20 results (or remaining if less than 20)

### Requirement: Static Asset Serving for Vue SPA
The system SHALL serve the Vue SPA static assets through FastAPI for seamless integration without requiring a separate web server.

#### Scenario: Serve Vue SPA at /ui/knowledge
- **WHEN** accessing `GET http://localhost:8000/ui/knowledge`
- **THEN** FastAPI SHALL serve `ui/knowledge/dist/index.html`
- **AND** SHALL serve JS/CSS assets from `ui/knowledge/dist/assets/`
- **AND** SHALL return Content-Type: text/html for index.html
- **AND** SHALL support SPA routing (fallback to index.html for non-asset paths)

#### Scenario: CORS configuration for API access
- **WHEN** the Vue SPA makes API requests to `/knowledge/*` endpoints
- **THEN** FastAPI SHALL allow requests from `http://localhost:8000` origin
- **AND** SHALL include CORS headers: `Access-Control-Allow-Origin`, `Access-Control-Allow-Methods`, `Access-Control-Allow-Headers`
- **AND** SHALL support preflight OPTIONS requests

## MODIFIED Requirements

### Requirement: Knowledge Search Tool Integration (MODIFIED)
The existing `knowledge_search` tool SHALL continue to work without code changes, now fetching enriched data from MySQL after ChromaDB vector search.

**Change**: Previously, `knowledge_search` retrieved all data from ChromaDB metadata. Now it retrieves kb_ids from ChromaDB, then enriches with full records from MySQL.

#### Scenario: Search knowledge via Agent tool
- **WHEN** the Agent executor calls `knowledge_search(query="退款政策", top_k=3)`
- **THEN** the system SHALL generate an embedding for the query text
- **AND** SHALL query ChromaDB collection `knowledge_base` with the embedding vector
- **AND** SHALL retrieve top_k matching kb_ids with similarity scores
- **AND** SHALL fetch full entry details from MySQL by kb_ids (batch SELECT WHERE kb_id IN (...))
- **AND** SHALL return results with fields: title, content, category, score (1 - distance)
- **AND** SHALL complete the search within 1 second

## REMOVED Requirements

None. This change is additive and does not remove existing functionality.
