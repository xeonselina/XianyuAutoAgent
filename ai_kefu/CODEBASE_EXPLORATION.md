# XianyuAutoAgent/ai_kefu Codebase Exploration Summary

**Date**: April 11, 2026  
**Project**: 闲鱼自动客服系统 (Xianyu Auto Customer Service System)  
**Type**: AI-powered customer service agent for Xianyu (second-hand marketplace)

---

## 1. Overall Project Structure

### Top-Level Directories

```
/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/
├── agent/                    # Agent execution engine (Agent turns management)
├── api/                      # FastAPI REST API service
├── config/                   # Configuration management
├── docs/                     # Project documentation
├── hooks/                    # Git hooks and lifecycle hooks
├── llm/                      # LLM client (Qwen/DashScope integration)
├── migrations/               # Database migration scripts (SQL)
├── models/                   # Data models (Pydantic)
├── prompts/                  # System and business prompts
├── scripts/                  # Utility scripts (init, setup, testing)
├── services/                 # Business service layer
├── storage/                  # Data storage (Redis, Chroma, MySQL)
├── tests/                    # Test suite (unit + integration)
├── tools/                    # Agent tools (knowledge search, pricing, etc.)
├── ui/                       # Frontend UIs (knowledge management, conversations)
├── utils/                    # Utility functions
├── xianyu_interceptor/       # Xianyu message interception via CDP
├── xianyu_provider/          # Xianyu API providers
├── chroma_data/              # Vector DB storage (Chroma embeddings)
├── data/                     # Runtime data files
└── logs/                     # Application logs
```

### Key Files

- **README.md** - Main documentation (Chinese)
- **Makefile** - Comprehensive automation commands
- **.env.example** - Configuration template (comprehensive)
- **Dockerfile** - Docker image definition
- **docker-compose.yml** - Multi-container orchestration
- **requirements.txt** - Python dependencies
- **start.sh** - Shell startup script
- **run_xianyu.py** - Main entry for Xianyu interceptor
- **api/main.py** - FastAPI application entry

---

## 2. Database Migration Scripts

### Location
`/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/migrations/`

### Migration Files (5 total)

| File | Purpose | Status |
|------|---------|--------|
| **001_create_conversations_table.sql** | Create `conversations` table for storing Xianyu chat history | ✅ Active |
| **002_create_knowledge_entries_table.sql** | Create `knowledge_entries` table for MySQL-backed knowledge management | ✅ Active |
| **003_create_system_prompts_table.sql** | Create `system_prompts` table for dynamic system prompt management | ✅ Active |
| **004_add_user_nickname_to_conversations.sql** | Add `user_nickname` column to conversations table | ✅ Active |
| **005_create_ignore_patterns_table.sql** | Create `ignore_patterns` table for message filtering | ✅ Active |

### Migration Details

**001_create_conversations_table.sql**
- Table: `conversations`
- Purpose: Xianyu conversation history
- Key columns: chat_id, user_id, seller_id, item_id, message_content, message_type, agent_response
- Includes view: `conversation_summary`

**002_create_knowledge_entries_table.sql**
- Table: `knowledge_entries`
- Purpose: MySQL source of truth for ChromaDB vector search
- Key columns: kb_id (stable ID), title, content, category, tags (JSON), priority
- Indexes on: kb_id, category, active, priority, content (FULLTEXT)

**003_create_system_prompts_table.sql**
- Table: `system_prompts`
- Purpose: Runtime-editable system prompts without code changes
- Supports versioning and prompt_key based lookup
- Columns: prompt_key, title, content, description, active, created_at, updated_at

**004_add_user_nickname_to_conversations.sql**
- Adds `user_nickname` column (VARCHAR 255) to conversations
- Stores user nickname from Xianyu reminderTitle field
- Idempotent - checks if column exists first

**005_create_ignore_patterns_table.sql**
- Table: `ignore_patterns`
- Purpose: Message pattern whitelist for AI filtering
- Default patterns include system messages like [图片], [我已付款], etc.
- 22 default ignore patterns pre-inserted

---

## 3. Knowledge Base Initialization Scripts

### Location
`/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/scripts/`

### Knowledge Base Init Scripts (2 total)

#### 1. **init_knowledge.py**
**Purpose**: Initialize general/generic knowledge base  
**Type**: Python script  
**Output**: Adds 6 sample knowledge entries to Chroma + MySQL

**Included Sample Knowledge**:
- kb_001: 退款政策 (Refund Policy)
- kb_002: 发货时间 (Shipping Time)
- kb_003: 会员积分规则 (Member Points Rules)
- kb_004: 商品质量问题处理 (Product Quality Issues)
- kb_005: 支付方式 (Payment Methods)
- kb_006: 优惠券使用规则 (Coupon Usage Rules)

**Process**:
1. Initialize KnowledgeStore (Chroma vector DB)
2. For each knowledge item:
   - Create KnowledgeEntry object
   - Generate embedding via Qwen API (retrieval_document task)
   - Add to knowledge store
3. Report success/failure count

#### 2. **init_rental_knowledge.py**
**Purpose**: Initialize phone rental business knowledge base  
**Type**: Python script with DB setup  
**Output**: Adds 11 rental-specific knowledge entries + creates MySQL schema

**Included Rental Knowledge**:
- rental_001: 租赁定价规则 (Rental Pricing Rules) - Comprehensive pricing tables, formulas, discounts
- rental_002: 免押金条件 (Deposit-Free Conditions) - Huabei, Sesame Credit, old customer rules
- rental_003: 租赁流程说明 (Rental Process Flow)
- rental_004: 设备使用注意事项 (Device Usage Notes)
- rental_005: 激光免责说明 (Laser Exemption Policy)
- rental_006: 设备磕碰划痕处理 (Device Damage Handling)
- rental_007: 物流配送说明 (Logistics Info)
- rental_008: 议价与优惠策略 (Negotiation & Discount Strategy)
- rental_009: 已下单后处理流程 (Post-Order Process)
- rental_010: 演唱会场景FAQ (Concert Scenario FAQ)
- rental_011: 缺货替代方案模板 (Out-of-Stock Alternative Templates)

**Features**:
- ✅ API Key validation
- ✅ MySQL database auto-creation if missing
- ✅ Knowledge entries table auto-creation
- ✅ Error handling with user guidance
- ✅ Progress reporting
- ✅ Embedding generation via Qwen API

**Related Setup Scripts**:
- `check_env.py` - Validate configuration before initialization
- `sync_prompt_to_db.py` - Sync prompts to database
- `update_rental_knowledge.py` - Update existing rental knowledge

---

## 4. Configuration Files

### Location & Types

#### **Environment Configuration**

**`.env.example`** (Template with all options)
- **Path**: `/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/.env.example`
- **Format**: INI-style key=value
- **Size**: ~150 lines with detailed comments
- **Sections**:
  - AI Model Configuration (API_KEY, MODEL_NAME, etc.)
  - Xianyu Account Configuration
  - Browser Configuration
  - AI Auto-Reply Configuration
  - Message Processing Configuration
  - MySQL Database Configuration
  - Redis Configuration
  - Rental Business API Configuration
  - DingTalk Robot Configuration (notification webhook)
  - Logging Configuration

**`.env`** (Actual config)
- Created by copying `.env.example`
- Contains actual credentials and secrets

#### **Settings Management**

**`config/settings.py`** (Pydantic Settings)
- **Type**: Python configuration class
- **Framework**: Pydantic BaseSettings (v2)
- **Features**:
  - Loads from `.env` file automatically
  - Type validation and coercion
  - Nested configuration
  - Model validators
  - Case-insensitive env vars
- **Key Config Classes**:
  - Qwen API settings (api_key, model_name, temperatures, timeout)
  - Redis settings (connection URL, session TTL)
  - Chroma settings (persistent path)
  - MySQL settings (host, port, user, password, database)
  - API service settings (host, port)
  - Agent settings (max_turns, timeout, loop detection)
  - Rental business settings (API base URL, endpoints)
  - DingTalk settings (webhook, secrets)
  - Xianyu settings (cookies, session TTL)
  - Confidence guard thresholds

**`config/constants.py`** (Static constants)
- Business logic constants
- System defaults

**`config/inventory_config.py`** (Inventory/device configuration)
- Device pricing information

#### **Docker Configuration**

**`docker-compose.yml`**
- Defines XianyuAutoAgent service container
- Mounts: data, prompts, .env
- Network: xianyu-network (bridge)

**`Dockerfile`**
- Multi-stage builds for efficiency
- Python base image
- Installs dependencies from requirements.txt

---

## 5. README and Documentation

### Main README

**`README.md`** (Comprehensive guide in Chinese)
- **Length**: ~650 lines
- **Covers**:
  - Feature overview (3 main subsystems)
  - Quick start guide
  - Prerequisites (Python 3.8+, API Key, Redis 7.x)
  - Installation steps
  - Configuration instructions
  - Running Xianyu bot
  - Running AI Agent API
  - API usage examples
  - Makefile commands reference
  - Project structure diagram
  - Configuration explanation
  - Phone rental business system details
  - Troubleshooting FAQ
  - Links to additional docs

### Additional Documentation Files

1. **QUICK_START.md** - Quick onboarding guide
2. **START_API.md** - API service startup guide (3 ways to start)
3. **SETUP_KNOWLEDGE.md** - Knowledge base initialization detailed guide
4. **MIGRATION_GUIDE.md** - Version migration instructions
5. **BUYER_INFO_API_GUIDE.md** - Buyer info API integration
6. **WEBSOCKET_DETECTION.md** - WebSocket connection detection guide

### In `/docs/` Directory

- **PROJECT_OVERVIEW.md** - Architecture and design (detailed)
- **KNOWLEDGE_UI_SETUP.md** - Knowledge UI setup
- **CHAT_HISTORY_CAPTURE.md** - Chat history capture mechanisms
- **HISTORY_API_ANALYSIS.md** - History API analysis
- **Debug guides** - Various debugging documentation
- **Integration guides** - Tencent docs, third-party integrations

---

## 6. Makefile and Setup Scripts

### **Makefile** (Comprehensive automation)

**Location**: `/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/Makefile`

**Key Commands**:

| Category | Command | Purpose |
|----------|---------|---------|
| **Installation** | `make install` | Install production dependencies |
| | `make install-dev` | Install dev dependencies (pytest, ruff, mypy) |
| | `make check-env` | Check and validate environment config |
| **Running** | `make run-xianyu` | Start Xianyu bot (browser mode) |
| | `make run-api` | Start FastAPI service |
| | `make init-knowledge` | Initialize knowledge base |
| **UI** | `make ui-install` | Install UI dependencies |
| | `make ui-dev` | Start UI dev server |
| | `make ui-build` | Build production UI |
| **Testing** | `make test` | Run all tests |
| | `make test-unit` | Run unit tests only |
| | `make test-integration` | Run integration tests only |
| | `make test-cov` | Run with coverage reporting |
| **Code Quality** | `make lint` | Run ruff + mypy |
| | `make format` | Auto-format code |
| **Docker** | `make docker-build` | Build Docker image |
| | `make docker-up` | Start containers |
| | `make docker-down` | Stop containers |
| | `make docker-logs` | View container logs |
| **Cleanup** | `make clean` | Clean temp files |
| | `make clean-all` | Full cleanup (venv, data, browser) |

### **Shell Scripts**

#### **start.sh** (Main startup script)
- **Path**: `/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/start.sh`
- **Purpose**: Automated environment validation before startup
- **Checks**:
  1. Python 3 installation
  2. Python dependencies (openai, websockets, loguru, dotenv, requests)
  3. .env file exists
  4. Required prompt files exist
- **Actions**:
  - Creates data directory
  - Shows important reminders
  - Prompts user confirmation
  - Starts main.py

#### **Setup Scripts in `.specify/scripts/bash/`**
- `setup-plan.sh` - Setup planning
- `check-prerequisites.sh` - Prerequisites validation
- `common.sh` - Common bash functions
- `update-agent-context.sh` - Agent context updates
- `create-new-feature.sh` - Feature scaffolding

---

## 7. Summary Table

| Category | Item | Location | Type | Status |
|----------|------|----------|------|--------|
| **DB Migrations** | Conversations table | migrations/001_*.sql | SQL | ✅ Active |
| | Knowledge entries | migrations/002_*.sql | SQL | ✅ Active |
| | System prompts | migrations/003_*.sql | SQL | ✅ Active |
| | User nickname | migrations/004_*.sql | SQL | ✅ Active |
| | Ignore patterns | migrations/005_*.sql | SQL | ✅ Active |
| **KB Init** | Generic KB | scripts/init_knowledge.py | Python | ✅ Active |
| | Rental KB | scripts/init_rental_knowledge.py | Python | ✅ Active |
| **Config** | Environment template | .env.example | INI | ✅ Reference |
| | Settings manager | config/settings.py | Python | ✅ Active |
| | Constants | config/constants.py | Python | ✅ Active |
| **Automation** | Task runner | Makefile | Makefile | ✅ Active |
| | Startup | start.sh | Bash | ✅ Active |
| | Setup helpers | .specify/scripts/bash/* | Bash | ✅ Active |
| **Documentation** | Main guide | README.md | Markdown | ✅ Comprehensive |
| | Quick start | QUICK_START.md | Markdown | ✅ Active |
| | API startup | START_API.md | Markdown | ✅ Active |
| | KB setup | SETUP_KNOWLEDGE.md | Markdown | ✅ Active |
| | Architecture | docs/PROJECT_OVERVIEW.md | Markdown | ✅ Detailed |

---

## 8. Tech Stack

- **Language**: Python 3.8+
- **Web Framework**: FastAPI
- **LLM**: Qwen (via DashScope API)
- **Vector DB**: Chroma (persistent embeddings)
- **SQL DB**: MySQL 8.0+
- **Cache**: Redis 7.x
- **Browser Automation**: Playwright
- **Config**: Pydantic Settings v2
- **Frontend**: Vue.js (TypeScript)
- **Containerization**: Docker & Docker Compose
- **Testing**: pytest, pytest-asyncio

---

## 9. Key Observations

### Strengths
✅ **Well-structured migrations**: 5 clear, numbered, idempotent SQL migrations  
✅ **Comprehensive documentation**: Multiple guides for different use cases  
✅ **Strong automation**: Makefile covers all common tasks  
✅ **Configuration management**: Pydantic-based with good validation  
✅ **Knowledge base**: Dual-system (MySQL + Chroma) for reliability  
✅ **Business-focused**: Specialized tools for phone rental use case  

### Areas to Note
⚠️ **MySQL hardcoded defaults**: Some hardcoded connections in scripts  
⚠️ **API Key in config**: Secrets in .env (needs proper vault in production)  
⚠️ **Docker-compose minimal**: Basic setup, may need enhancement for prod  
⚠️ **Knowledge seeding**: Hard-coded data in Python scripts (consider external files)  

---

## 10. Getting Started Checklist

- [ ] Clone repository
- [ ] Copy `.env.example` to `.env` and fill in credentials
- [ ] Run `make install`
- [ ] Run `make check-env` to validate
- [ ] Run `make init-knowledge` to setup KB
- [ ] Run `make run-api` to start service
- [ ] Access API at http://localhost:8000/docs

