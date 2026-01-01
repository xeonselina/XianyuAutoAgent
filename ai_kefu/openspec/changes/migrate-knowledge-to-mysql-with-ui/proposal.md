# Proposal: Migrate Knowledge Base to MySQL with Management UI

## Change ID
`migrate-knowledge-to-mysql-with-ui`

## Problem Statement

Currently, the knowledge base is initialized from hardcoded Python data in `scripts/init_knowledge.py` and stored only in ChromaDB. This creates several limitations:

1. **No Structured CRUD Interface**: Knowledge entries cannot be easily managed after initialization without writing Python code
2. **No Persistence Layer**: ChromaDB stores data in a vector format optimized for search, not for structured querying or management
3. **Poor Auditability**: No timestamps, change tracking, or audit trail for knowledge modifications
4. **Manual Seeding Required**: Adding new knowledge requires editing Python code and re-running the init script
5. **No Bulk Operations**: Cannot export, import, or bulk edit knowledge entries

## Proposed Solution

Introduce a **hybrid storage architecture** where:
- **MySQL** serves as the source of truth for knowledge entries with full CRUD capabilities
- **ChromaDB** continues to handle vector embeddings for semantic search
- **Vue SPA web UI** provides user-friendly knowledge management

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Vue SPA Web UI                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Knowledge Management Pages:                     │  │
│  │  • List/Search Knowledge                         │  │
│  │  • Create/Edit/Delete Entries                    │  │
│  │  • Bulk Import (JSON)                            │  │
│  │  • Initialize Default Data                       │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────┬───────────────────────────────────┘
                      │ HTTP API
                      ↓
┌─────────────────────────────────────────────────────────┐
│          FastAPI Backend (Existing + Enhanced)          │
│  ┌──────────────────────────────────────────────────┐  │
│  │  /knowledge/* endpoints (ENHANCED)               │  │
│  │  • POST /knowledge/bulk (new)                    │  │
│  │  • POST /knowledge/init-defaults (new)           │  │
│  │  • GET /knowledge/export (new)                   │  │
│  └──────────────────────────────────────────────────┘  │
└────┬─────────────────────────────┬──────────────────────┘
     │                             │
     ↓                             ↓
┌──────────────────┐      ┌─────────────────────┐
│  MySQL Database  │      │  ChromaDB           │
│  ┌────────────┐  │      │  ┌───────────────┐  │
│  │ knowledge  │←─┼──────┼─→│ knowledge_base│  │
│  │ _entries   │  │ sync │  │ (vectors)     │  │
│  └────────────┘  │      │  └───────────────┘  │
│  Source of Truth │      │  Search Index       │
└──────────────────┘      └─────────────────────┘
```

### Key Design Decisions

1. **Hybrid Storage**: MySQL stores structured data, ChromaDB stores vectors. Synced on every create/update.
2. **Vue SPA**: Modern reactive UI without backend templating complexity. Communicates via REST API.
3. **No Authentication (MVP)**: Assumes deployment on private network. Can add later if needed.
4. **Seed Data Preserved**: Current 6 hardcoded entries become database seed data via `/knowledge/init-defaults` endpoint.
5. **Backward Compatibility**: Existing `/knowledge/*` API endpoints remain functional. `knowledge_search` tool unchanged.

## Capabilities Added

### 1. Knowledge Management UI (`specs/knowledge-management-ui`)
- Vue SPA with Vite for knowledge CRUD operations
- Table view with search/filter
- Form-based create/edit
- JSON bulk import/export
- One-click default data initialization

### 2. MySQL Knowledge Storage (`specs/mysql-knowledge-storage`)
- New `knowledge_entries` table in MySQL
- Migration script to create table
- Dual-write: MySQL (primary) + ChromaDB (search index)
- KnowledgeStore refactored to use MySQL as source of truth

### 3. Bulk Operations API (`specs/bulk-operations`)
- POST `/knowledge/bulk` - Import multiple entries from JSON
- POST `/knowledge/init-defaults` - Seed database with default 6 entries
- GET `/knowledge/export` - Export all knowledge as JSON

## Out of Scope

- User authentication/authorization (can add in future change)
- Real-time collaboration features
- Knowledge versioning/history tracking
- Full-text search in MySQL (relies on ChromaDB semantic search)
- Automated ChromaDB sync repair (assumes MySQL is always correct source)

## Migration Path

1. **Phase 1**: Add MySQL table and storage layer
2. **Phase 2**: Enhance API with bulk operations
3. **Phase 3**: Build Vue SPA UI
4. **Phase 4**: Update `init_knowledge.py` to use API endpoint instead of direct writes

Existing deployments:
- Run migration script to create `knowledge_entries` table
- Use `/knowledge/init-defaults` to populate from existing ChromaDB (or use seed data)
- Optionally deploy UI (can run headless)

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| MySQL-ChromaDB sync failures | Dual-write wrapped in try-catch. MySQL write succeeds even if ChromaDB fails. Background sync job possible future enhancement. |
| Vue build complexity | Provide pre-built static assets in repo. Optional development mode with Vite. |
| Breaking existing workflows | Keep all existing API contracts. `init_knowledge.py` script still works (refactored to use API). |
| MySQL performance for large datasets | Index on category, tags (JSON), active. Pagination on list endpoint. |

## Success Criteria

- [ ] MySQL table created and integrated
- [ ] Web UI can list, create, edit, delete knowledge entries
- [ ] Bulk import from JSON works correctly
- [ ] Init defaults button populates 6 sample entries
- [ ] Existing knowledge search tool still returns correct results
- [ ] All existing API tests pass
- [ ] New UI accessible at `http://localhost:8000/ui/knowledge` (served as static SPA)

## Dependencies

- Requires MySQL database (same instance as `conversations` table from previous change)
- Requires Node.js 18+ for Vue development (but can use pre-built assets)
- No blocking dependencies on other changes
