# Design: Knowledge Base MySQL Migration with Management UI

## Architecture Overview

### Current State
```
init_knowledge.py (Python dict)
    ↓
    Writes directly to ChromaDB
    ↓
KnowledgeStore.add() → ChromaDB collection
    ↓
knowledge_search tool → ChromaDB.query()
```

**Problems:**
- No structured query capability (only vector search)
- No audit trail (created_at/updated_at in metadata only)
- No easy CRUD interface
- Python code required to modify knowledge

### Target State
```
┌─────────────────────────────────────────────────────────┐
│                    Vue SPA (port 8000/ui/knowledge)     │
│  Components:                                            │
│  • KnowledgeList.vue (table with search)                │
│  • KnowledgeForm.vue (create/edit modal)                │
│  • BulkImport.vue (JSON upload)                         │
│  • InitDefaults.vue (seed data button)                  │
└─────────────────────┬───────────────────────────────────┘
                      │ Fetch API
                      ↓
┌─────────────────────────────────────────────────────────┐
│  FastAPI Backend (Enhanced)                             │
│  ┌────────────────────────────────────────────────────┐ │
│  │ /knowledge Routes (api/routes/knowledge.py)        │ │
│  │ • POST /knowledge/                (EXISTING)       │ │
│  │ • GET /knowledge/                 (EXISTING)       │ │
│  │ • PUT /knowledge/{id}             (EXISTING)       │ │
│  │ • DELETE /knowledge/{id}          (EXISTING)       │ │
│  │ • POST /knowledge/search          (EXISTING)       │ │
│  │ • POST /knowledge/bulk            (NEW)            │ │
│  │ • POST /knowledge/init-defaults   (NEW)            │ │
│  │ • GET /knowledge/export           (NEW)            │ │
│  └────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────┐ │
│  │ Static Files Middleware                            │ │
│  │ • Serves Vue SPA from /ui/knowledge                │ │
│  └────────────────────────────────────────────────────┘ │
└─────┬──────────────────────────────┬────────────────────┘
      │                              │
      ↓                              ↓
┌───────────────────────┐   ┌────────────────────────┐
│ MySQL                 │   │ ChromaDB               │
│ knowledge_entries     │   │ knowledge_base         │
│ ┌──────────────────┐  │   │ ┌──────────────────┐  │
│ │ id (PK)          │  │   │ │ doc_id (PK)      │  │
│ │ kb_id (UNIQUE)   │←─┼───┼→│ kb_id            │  │
│ │ title            │  │   │ │ embedding[1536]  │  │
│ │ content (TEXT)   │  │   │ │ metadata         │  │
│ │ category         │  │   │ └──────────────────┘  │
│ │ tags (JSON)      │  │   │                        │
│ │ source           │  │   │ Used for:              │
│ │ priority         │  │   │ • Vector search        │
│ │ active           │  │   │ • Semantic retrieval   │
│ │ created_at       │  │   │                        │
│ │ updated_at       │  │   │                        │
│ └──────────────────┘  │   └────────────────────────┘
│                       │
│ Used for:             │
│ • CRUD operations     │
│ • Listing/filtering   │
│ • Audit trail         │
│ • Exports             │
└───────────────────────┘
```

## Database Schema

### knowledge_entries Table
```sql
CREATE TABLE knowledge_entries (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    kb_id VARCHAR(50) NOT NULL UNIQUE COMMENT 'Stable knowledge base ID (e.g., kb_001)',

    -- Content
    title VARCHAR(500) NOT NULL,
    content TEXT NOT NULL,

    -- Classification
    category VARCHAR(100) DEFAULT NULL,
    tags JSON DEFAULT NULL COMMENT 'Array of tag strings',

    -- Metadata
    source VARCHAR(200) DEFAULT NULL,
    priority INT DEFAULT 0,
    active BOOLEAN DEFAULT TRUE,

    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_category (category),
    INDEX idx_active (active),
    INDEX idx_priority (priority),
    INDEX idx_created_at (created_at),
    FULLTEXT idx_content (title, content)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

## Component Design

### 1. MySQL Knowledge Store Adapter

**File**: `storage/mysql_knowledge_store.py`

```python
class MySQLKnowledgeStore:
    """MySQL-based knowledge entry storage."""

    def __init__(self, mysql_config):
        # PyMySQL connection

    def create(self, entry: KnowledgeEntry) -> bool:
        """Insert into MySQL, then sync to ChromaDB."""
        # 1. Insert to MySQL
        # 2. Generate embedding
        # 3. Add to ChromaDB
        # 4. Return success

    def update(self, kb_id: str, updates: dict) -> KnowledgeEntry:
        """Update MySQL, regenerate embedding if content changed."""
        # 1. Update MySQL
        # 2. If content changed, regenerate embedding
        # 3. Update ChromaDB
        # 4. Return updated entry

    def delete(self, kb_id: str) -> bool:
        """Delete from both MySQL and ChromaDB."""

    def get(self, kb_id: str) -> Optional[KnowledgeEntry]:
        """Fetch from MySQL."""

    def list_all(self, filters: dict, limit: int, offset: int) -> List[KnowledgeEntry]:
        """Paginated list from MySQL."""

    def search_semantic(self, query: str, top_k: int) -> List[KnowledgeSearchResult]:
        """Vector search via ChromaDB, enrich with MySQL data."""
        # 1. ChromaDB.query() to get kb_ids + distances
        # 2. Fetch full entries from MySQL by kb_ids
        # 3. Return merged results

    def bulk_create(self, entries: List[KnowledgeEntry]) -> int:
        """Batch insert. Returns count of successful inserts."""

    def export_all(self) -> List[dict]:
        """Export all knowledge as JSON-serializable dicts."""
```

### 2. Refactored KnowledgeStore

**File**: `storage/knowledge_store.py` (MODIFIED)

The current `KnowledgeStore` will be refactored to delegate to MySQL:

```python
class KnowledgeStore:
    """
    Unified knowledge store interface.
    Delegates to MySQL for CRUD, ChromaDB for search.
    """

    def __init__(self):
        self.mysql_store = MySQLKnowledgeStore(settings.mysql_*)
        self.chroma_client = chromadb.PersistentClient(...)
        self.chroma_collection = self.chroma_client.get_or_create_collection(...)

    def add(self, entry, embedding):
        """Add to MySQL first, then ChromaDB."""
        return self.mysql_store.create(entry)

    def search(self, query_embedding, top_k, ...):
        """Search ChromaDB, enrich from MySQL."""
        return self.mysql_store.search_semantic(query, top_k)

    # All other methods delegate to mysql_store
```

### 3. Enhanced API Endpoints

**File**: `api/routes/knowledge.py` (MODIFIED + NEW ENDPOINTS)

New endpoints:
```python
@router.post("/bulk")
async def bulk_import_knowledge(request: KnowledgeBulkImportRequest):
    """
    Import multiple knowledge entries.

    Request body:
    {
        "entries": [
            {"kb_id": "kb_001", "title": "...", "content": "...", ...},
            ...
        ],
        "overwrite_existing": false
    }

    Response:
    {
        "imported": 5,
        "skipped": 1,
        "errors": []
    }
    """

@router.post("/init-defaults")
async def initialize_default_knowledge():
    """
    Seed database with default 6 knowledge entries.
    Idempotent: checks if entries exist by kb_id.

    Response:
    {
        "initialized": 6,
        "skipped": 0,
        "message": "Default knowledge initialized"
    }
    """

@router.get("/export")
async def export_knowledge(active_only: bool = True):
    """
    Export all knowledge entries as JSON.

    Response:
    [
        {"kb_id": "kb_001", "title": "...", ...},
        ...
    ]
    """
```

### 4. Vue SPA Structure

**Directory**: `ui/knowledge/` (NEW)

```
ui/knowledge/
├── index.html              # SPA entry point
├── package.json
├── vite.config.js
├── src/
│   ├── main.js             # Vue app initialization
│   ├── App.vue             # Root component
│   ├── router.js           # Vue Router (SPA routing)
│   ├── api.js              # Fetch API wrapper for /knowledge/*
│   ├── components/
│   │   ├── KnowledgeList.vue     # Table with search/filter
│   │   ├── KnowledgeForm.vue     # Create/Edit modal
│   │   ├── BulkImport.vue        # JSON file upload
│   │   └── DefaultDataButton.vue # Init defaults button
│   └── styles/
│       └── main.css
└── dist/                   # Built static assets (committed)
    ├── index.html
    ├── assets/
    │   ├── index-{hash}.js
    │   └── index-{hash}.css
```

**Deployment Options:**
1. **Development**: Run `npm run dev` separately, proxy API calls to FastAPI
2. **Production**: Commit pre-built `dist/` folder, FastAPI serves static files

### 5. Static File Serving

**File**: `api/main.py` (MODIFIED)

```python
from fastapi.staticfiles import StaticFiles

# Serve Vue SPA
app.mount("/ui/knowledge", StaticFiles(directory="ui/knowledge/dist", html=True), name="knowledge-ui")
```

Access at: `http://localhost:8000/ui/knowledge`

## Data Flow

### Create Knowledge Entry
```
User submits form in Vue
    ↓
POST /knowledge/ {title, content, ...}
    ↓
api/routes/knowledge.py:create_knowledge()
    ↓
MySQLKnowledgeStore.create()
    ├→ 1. INSERT INTO knowledge_entries
    ├→ 2. generate_embedding(content)
    └→ 3. ChromaDB.add(kb_id, embedding, metadata)
    ↓
Return 201 Created
    ↓
Vue refreshes list
```

### Search Knowledge (Existing Flow - UNCHANGED)
```
knowledge_search tool called by Agent
    ↓
KnowledgeStore.search(query_embedding, top_k)
    ↓
MySQLKnowledgeStore.search_semantic()
    ├→ 1. ChromaDB.query(query_embedding) → [kb_ids, distances]
    └→ 2. SELECT * FROM knowledge_entries WHERE kb_id IN (...)
    ↓
Return merged results with full metadata
```

### Initialize Default Data
```
User clicks "Initialize Defaults" in UI
    ↓
POST /knowledge/init-defaults
    ↓
DEFAULT_KNOWLEDGE = [
    {"kb_id": "kb_001", "title": "退款政策", ...},
    ...  # 6 entries from current init_knowledge.py
]
    ↓
For each entry:
    ├→ Check if kb_id exists in MySQL
    ├→ If not exists: MySQLKnowledgeStore.create(entry)
    └→ If exists: Skip
    ↓
Return {"initialized": 6, "skipped": 0}
    ↓
Vue shows success message
```

## Migration Strategy

### For Existing Deployments

**Option A: Start Fresh**
1. Run migration script to create `knowledge_entries` table
2. Use UI to click "Initialize Defaults" (loads 6 seed entries)
3. Manually add additional knowledge via UI

**Option B: Migrate from ChromaDB**
1. Run migration script to create table
2. Write one-time script:
   ```python
   # scripts/migrate_chroma_to_mysql.py
   chroma_store = KnowledgeStore()  # old implementation
   mysql_store = MySQLKnowledgeStore()

   entries = chroma_store.list_all()
   for entry in entries:
       mysql_store.create(entry)
   ```

### For New Deployments
- Run MySQL migration
- Use `/knowledge/init-defaults` API or UI button
- Ready to use

## Testing Strategy

### Unit Tests
- `tests/unit/test_storage/test_mysql_knowledge_store.py` - MySQL CRUD operations
- `tests/unit/test_api/test_knowledge_bulk.py` - Bulk import/export endpoints

### Integration Tests
- `tests/integration/test_knowledge_mysql_sync.py` - Verify MySQL-ChromaDB consistency
- `tests/integration/test_knowledge_ui_flow.py` - End-to-end UI workflow (Playwright)

### Manual Testing
- [ ] Create knowledge via UI → appears in list
- [ ] Edit knowledge → updates content
- [ ] Delete knowledge → disappears from list
- [ ] Bulk import JSON → all entries created
- [ ] Init defaults → 6 entries appear
- [ ] Search via Agent → finds MySQL-backed knowledge

## Backward Compatibility

**No Breaking Changes:**
- Existing `/knowledge/*` API contracts preserved
- `knowledge_search` tool signature unchanged
- ChromaDB still used for vector search
- `init_knowledge.py` script refactored to use API (same CLI interface)

## Performance Considerations

1. **Dual Writes**: MySQL + ChromaDB writes are sequential. Acceptable for low-throughput admin operations.
2. **Search Performance**: ChromaDB query unchanged. MySQL JOIN adds negligible overhead.
3. **List Performance**: Pagination prevents large result sets. Indexes on category, active, priority.
4. **Bulk Import**: Batch inserts in MySQL, individual ChromaDB adds (no batch API in ChromaDB).

## Security Notes

**No Authentication (MVP):**
- Assumes deployment on private network or behind VPN
- FastAPI CORS configured to allow specific origins
- Future enhancement: Add HTTP Basic Auth or JWT middleware

## Future Enhancements (Out of Scope)

- Knowledge versioning (history table)
- Advanced search filters in UI (date ranges, multi-tag)
- Real-time sync monitoring/repair
- Knowledge approval workflow
- Markdown preview for content field
- Rich text editor
