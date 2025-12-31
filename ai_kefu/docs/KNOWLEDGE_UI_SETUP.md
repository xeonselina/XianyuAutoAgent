# Knowledge Management UI Setup Guide

This guide explains how to set up and use the knowledge management system with MySQL backend and optional Vue.js UI.

## ✅ What's Already Implemented

### Backend (Complete)
- ✅ MySQL schema (`migrations/002_create_knowledge_entries_table.sql`)
- ✅ MySQLKnowledgeStore with ChromaDB sync (`storage/mysql_knowledge_store.py`)
- ✅ Refactored KnowledgeStore to use MySQL (`storage/knowledge_store.py`)
- ✅ Enhanced API endpoints:
  - `POST /knowledge/bulk` - Bulk import
  - `POST /knowledge/init-defaults` - Initialize 6 default entries
  - `GET /knowledge/export` - Export all knowledge as JSON
- ✅ MySQL configuration in `config/settings.py`

## 🚀 Quick Start (Backend Only)

### 1. Run MySQL Migration

```bash
# Connect to MySQL
mysql -u root -p

# Create database if not exists
CREATE DATABASE IF NOT EXISTS xianyu_conversations;

# Run migration
mysql -u root -p xianyu_conversations < migrations/002_create_knowledge_entries_table.sql
```

### 2. Update `.env` File

```bash
# MySQL Configuration (same instance as conversations)
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=your_mysql_user
MYSQL_PASSWORD=your_mysql_password
MYSQL_DATABASE=xianyu_conversations
```

### 3. Initialize Default Knowledge

**Option A: Using API (Recommended)**
```bash
# Start the API server
make run-api

# In another terminal, initialize defaults
curl -X POST http://localhost:8000/knowledge/init-defaults
```

**Option B: Using old init script**
```bash
python scripts/init_knowledge.py
```

### 4. Verify Knowledge Entries

```bash
# List all knowledge
curl http://localhost:8000/knowledge/

# Or check MySQL directly
mysql -u root -p xianyu_conversations -e "SELECT kb_id, title, category FROM knowledge_entries;"
```

## 📊 Using the REST API

### Create Knowledge Entry
```bash
curl -X POST http://localhost:8000/knowledge/ \
  -H "Content-Type: application/json" \
  -d '{
    "title": "新知识条目",
    "content": "这是知识内容...",
    "category": "测试分类",
    "tags": ["标签1", "标签2"],
    "priority": 5
  }'
```

### Bulk Import from JSON
```bash
curl -X POST http://localhost:8000/knowledge/bulk \
  -H "Content-Type: application/json" \
  -d '{
    "entries": [
      {
        "kb_id": "kb_custom_001",
        "title": "自定义知识1",
        "content": "知识内容1...",
        "category": "自定义",
        "tags": [],
        "priority": 5,
        "active": true
      }
    ],
    "overwrite_existing": false
  }'
```

### Export All Knowledge
```bash
curl -O http://localhost:8000/knowledge/export?active_only=true
```

### Search Knowledge (Semantic)
```bash
curl -X POST http://localhost:8000/knowledge/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "退款怎么办",
    "top_k": 3
  }'
```

## 🎨 Vue.js UI (已实现)

The Vue SPA provides a user-friendly interface for knowledge management and has been fully implemented:

### Quick Start

The UI has been pre-built and is ready to use:

```bash
# Start the API server (if not already running)
make run-api

# Access the UI in your browser
open http://localhost:8000/ui/knowledge
```

### Development Mode

To run the UI in development mode with hot reload:

```bash
# Install dependencies (first time only)
make ui-install

# Start dev server
make ui-dev

# Access at http://localhost:5173
```

### Production Build

To rebuild the production assets:

```bash
# Build UI
make ui-build

# Restart API server to serve updated assets
make run-api
```

### Alternative: Use API Directly (No UI)

You can manage knowledge entirely through:
1. **Direct API calls** (curl, Postman, HTTPie)
2. **OpenAPI Docs** - Visit `http://localhost:8000/docs`
3. **Python scripts** - Write custom management scripts

### Component Examples (for Vue SPA)

**src/api.js** - API wrapper
```javascript
const API_BASE = '/knowledge';

export const knowledgeAPI = {
  list: async (offset = 0, limit = 20) => {
    const res = await fetch(`${API_BASE}/?offset=${offset}&limit=${limit}`);
    return res.json();
  },

  create: async (data) => {
    const res = await fetch(`${API_BASE}/`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    return res.json();
  },

  update: async (id, data) => {
    const res = await fetch(`${API_BASE}/${id}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    return res.json();
  },

  delete: async (id) => {
    const res = await fetch(`${API_BASE}/${id}`, {method: 'DELETE'});
    return res.json();
  },

  bulkImport: async (entries, overwrite = false) => {
    const res = await fetch(`${API_BASE}/bulk`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({entries, overwrite_existing: overwrite})
    });
    return res.json();
  },

  initDefaults: async () => {
    const res = await fetch(`${API_BASE}/init-defaults`, {method: 'POST'});
    return res.json();
  },

  export: async () => {
    const res = await fetch(`${API_BASE}/export`);
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `knowledge_export_${new Date().toISOString()}.json`;
    a.click();
  }
};
```

## 🔍 Troubleshooting

### MySQL Connection Error
```
Error: Can't connect to MySQL server
```
**Solution**: Check `.env` file has correct MySQL credentials and server is running.

### ChromaDB Sync Failed (Warning)
```
ChromaDB sync failed for kb_001: ...
```
**Impact**: Entry is saved to MySQL (source of truth) but not searchable via vector search.
**Solution**: Check ChromaDB permissions and disk space. Re-run init to sync.

### Knowledge Search Returns Empty
```
GET /knowledge/search returns no results
```
**Possible Causes**:
1. No entries in database → Run `init-defaults`
2. ChromaDB not synced → Check logs for sync errors
3. Query embedding failed → Check API key for Qwen

### Bulk Import Errors
```
{imported: 0, skipped: 10, errors: [...]}
```
**Solution**: Check `errors` array in response. Common issues:
- Duplicate `kb_id` with `overwrite_existing=false`
- Invalid required fields (title, content)
- MySQL connection issue

## 📝 Next Steps

1. **Production Deployment**:
   - Run MySQL migration on production DB
   - Set production environment variables
   - Initialize defaults via API
   - (Optional) Build and deploy Vue UI

2. **Custom Knowledge**:
   - Use bulk import to add your domain-specific knowledge
   - Export existing knowledge from other systems as JSON
   - Gradually migrate from init_knowledge.py to database

3. **Monitoring**:
   - Check MySQL table size: `SELECT COUNT(*) FROM knowledge_entries;`
   - Monitor ChromaDB sync success rate in logs
   - Set up alerts for knowledge search failures

## 🔗 Related Documentation

- API Documentation: `http://localhost:8000/docs`
- MySQL Schema: `migrations/002_create_knowledge_entries_table.sql`
- Design Document: `openspec/changes/migrate-knowledge-to-mysql-with-ui/design.md`
- Tasks Checklist: `openspec/changes/migrate-knowledge-to-mysql-with-ui/tasks.md`

## 🎯 API Endpoints Summary

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/knowledge/` | GET | List entries (paginated) |
| `/knowledge/` | POST | Create new entry |
| `/knowledge/{id}` | GET | Get single entry |
| `/knowledge/{id}` | PUT | Update entry |
| `/knowledge/{id}` | DELETE | Delete entry |
| `/knowledge/search` | POST | Semantic search |
| **`/knowledge/bulk`** | **POST** | **Bulk import** |
| **`/knowledge/init-defaults`** | **POST** | **Init 6 defaults** |
| **`/knowledge/export`** | **GET** | **Export all as JSON** |

**New endpoints in bold**
