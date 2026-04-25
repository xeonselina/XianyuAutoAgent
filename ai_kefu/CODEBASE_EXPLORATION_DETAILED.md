# XianyuAutoAgent/ai_kefu - Codebase Exploration Report

## Project Overview

**闲鱼AI客服系统** (Xianyu AI Customer Service System) - A comprehensive AI-powered customer service solution for Xianyu (Alibaba's second-hand marketplace) with support for automated responses, human takeover, and intelligent conversations.

**Repository**: `/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu`
**Date**: 2026-04-24

---

## 1. Overall Project Structure

### Top-Level Directories

```
ai_kefu/
├── .claude/                 # Claude Code configuration
├── .codebuddy/              # Code buddy tools
├── .specify/                # OpenSpec change management
├── .venv/                   # Python virtual environment
├── agent/                   # Agent core engine
├── api/                     # AI Agent API Backend (FastAPI)
├── chroma_data/             # Vector database storage
├── config/                  # Configuration management
├── data/                    # Data files
├── docs/                    # Documentation
├── hooks/                   # Git hooks
├── legacy/                  # Legacy code
├── llm/                     # LLM client implementations
├── logs/                    # Application logs
├── migrations/              # Database migrations
├── models/                  # Data models
├── openspec/                # OpenSpec specifications
├── prompts/                 # AI system prompts
├── reports/                 # Report generation
├── scripts/                 # Utility and setup scripts
├── services/                # Business services
├── specs/                   # Specification documents
├── storage/                 # Storage layer (Redis, Chroma, MySQL)
├── testcases/               # Test case definitions
├── tests/                   # Test suites (unit, integration)
├── tools/                   # Agent tools (knowledge search, pricing, logistics, etc.)
├── ui/                      # Frontend UIs (Vue 3)
│   ├── knowledge/           # Knowledge Management UI
│   └── conversations/       # Conversations UI
├── utils/                   # Utility functions
├── xianyu_images/           # Xianyu-related images
├── xianyu_interceptor/      # Message interception layer (CDP-based)
├── xianyu_provider/         # Xianyu API provider
```

### Top-Level Files

| File | Purpose |
|------|---------|
| `run_xianyu.py` | Main entry point for Xianyu bot interceptor |
| `main.py` | Legacy/alternative entry point |
| `api/main.py` | FastAPI application entry point |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Docker image definition (multi-stage) |
| `docker-compose.yml` | Docker Compose configuration |
| `Makefile` | Build and run automation |
| `.env.example` | Environment variables template |
| `.dockerignore` | Docker build exclusions |
| `README.md` | Project documentation |

---

## 2. API Backend

### Backend Language & Framework
- **Language**: Python 3.10+
- **Framework**: FastAPI
- **Server**: Uvicorn (with Gunicorn for production)
- **Entry Point**: `/api/main.py`

### Key Features
- RESTful API with OpenAPI documentation
- Async/await support
- CORS middleware configured
- WebSocket support
- Static file serving (for frontend UIs)
- Health check endpoints

### Core Components

**Main Application** (`api/main.py`):
- FastAPI app initialization with lifespan management
- Route registration from multiple modules
- CORS configuration (allow_origins="*")
- Static file mounting for Vue UIs

**API Routes** (`api/routes/`):
```
├── system.py              # System health and info endpoints
├── chat.py                # Conversation endpoints
├── session.py             # Session management
├── human_agent.py         # Human agent workflow
├── knowledge.py           # Knowledge base operations
├── conversations.py       # Conversation history
├── prompts.py             # Prompt management
├── eval.py                # Evaluation endpoints
├── ignore_patterns.py     # Pattern ignore rules
├── dingtalk.py            # DingTalk integration
├── xianyu.py              # Xianyu-specific endpoints
└── settings.py            # Settings management
```

**Data Models** (`api/models.py`):
- Pydantic models for request/response validation
- Data serialization

**Dependencies** (`api/dependencies.py`):
- Dependency injection setup for FastAPI

### Port Configuration
- **API Service Port**: `8000` (default)
- Configured in: `config/settings.py` (api_port: int = 8000)
- Can be overridden via command line or environment

### Startup Command
```bash
# Development (with hot reload)
python -m uvicorn ai_kefu.api.main:app --host 0.0.0.0 --port 8000 --reload

# Production (from Dockerfile)
gunicorn ai_kefu.api.main:app \
    -w 10 \
    -k uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --timeout 120
```

---

## 3. Xianyu Bot System

### Component: Xianyu Message Interceptor
- **Language**: Python
- **Entry Point**: `run_xianyu.py`
- **Purpose**: Intercept Xianyu messages via browser CDP and forward to AI API

### Key Components

**Message Interception** (`xianyu_interceptor/`):
- `cdp_interceptor.py` - Chrome DevTools Protocol interceptor
- `browser_controller.py` - Browser automation (Playwright)
- `messaging_core.py` - Message encoding/decoding
- `transports.py` - WebSocket transport
- `browser_transport.py` - Browser-based transport

**Xianyu API Provider** (`xianyu_provider/`):
- API wrapper for Xianyu operations
- Authentication and session management

**Related Files**:
- `XianyuAgent.py` - AI agent for Xianyu responses
- `XianyuApis.py` - Xianyu API encapsulation
- `context_manager.py` - Context management

### Configuration
- Browser headless mode: `BROWSER_HEADLESS` (default: false)
- Browser user data dir: `BROWSER_USER_DATA_DIR` (default: `./browser_data`)
- Viewport size: `BROWSER_VIEWPORT_WIDTH`, `BROWSER_VIEWPORT_HEIGHT`
- Optional proxy: `BROWSER_PROXY`

### How It Works
1. Uses Playwright to automate Chromium browser
2. Injects CDP (Chrome DevTools Protocol) scripts
3. Intercepts WebSocket messages from Xianyu
4. Parses and forwards to AI Agent API at `/xianyu/inbound`
5. API processes and returns response
6. Bot sends response through browser interface

---

## 4. Management Consoles (Frontend UIs)

### UI Technology Stack
- **Framework**: Vue 3
- **Build Tool**: Vite
- **Runtime**: Node.js (for build only)

### Knowledge Management UI
- **Location**: `ui/knowledge/`
- **Package Name**: `knowledge-management-ui`
- **Port**: Accessed via `http://localhost:8000/ui/knowledge`
- **Build Output**: `ui/knowledge/dist`
- **Package.json Scripts**:
  ```json
  {
    "dev": "vite",           # Dev server (localhost:5173)
    "build": "vite build",   # Production build
    "preview": "vite preview"
  }
  ```

### Conversations UI
- **Location**: `ui/conversations/`
- **Package Name**: `conversations-ui`
- **Port**: Accessed via `http://localhost:8000/ui/conversations`
- **Build Output**: `ui/conversations/dist`
- **Package.json Scripts**: Same as knowledge UI

### UI Features
- Knowledge base management
- Conversation history viewing
- Real-time message monitoring
- Session management interface

### Dependencies
- `vue@^3.4.15`
- `vue-router@^4.2.5`
- `@vitejs/plugin-vue@^5.0.3`
- `vite@^5.0.11`

### Build/Run Commands
```bash
# Install dependencies
make ui-install
cd ui/knowledge && npm install
cd ui/conversations && npm install

# Development
make ui-dev
cd ui/knowledge && npm run dev    # Port 5173

# Production build
make ui-build
cd ui/knowledge && npm run build
cd ui/conversations && npm run build

# Access UIs
# Knowledge: http://localhost:8000/ui/knowledge
# Conversations: http://localhost:8000/ui/conversations
```

---

## 5. Docker Configuration

### Dockerfile
- **Location**: `Dockerfile`
- **Base Image**: `python:3.10-alpine` (multi-stage build)
- **Size Optimization**: Uses Alpine Linux + multi-stage build
- **Timezone**: Asia/Shanghai
- **Python Encoding**: UTF-8

### Multi-Stage Build
**Stage 1 (Builder)**:
- Installs build dependencies (gcc, musl-dev, libffi-dev, build-base)
- Creates virtual environment
- Installs Python dependencies from requirements.txt

**Stage 2 (Final)**:
- Copies virtual environment from builder
- Sets environment variables (TZ, PYTHONIOENCODING, etc.)
- Copies application code
- Installs prompt examples
- Entry point: Gunicorn with Uvicorn worker

### Docker Compose Configuration
- **Location**: `docker-compose.yml`
- **Services**:
  1. **XianyuAutoAgent** (Main application)
     - Image: `shaxiu/xianyuautoagent:latest`
     - Ports: Internal (mapped via depends_on)
     - Volumes: data, prompts, .env
     - Network: `xianyu-network`
  
  2. **MySQL 8.0**
     - Container: `xianyu-mysql`
     - Port: `3306:3306`
     - Database: `xianyu`
     - Volumes: `mysql_data`
  
  3. **Redis 7-alpine**
     - Container: `xianyu-redis`
     - Port: `6379:6379`
     - Volumes: `redis_data`

### Docker Commands
```bash
make docker-build      # Build image: xianyuautoagent:latest
make docker-up         # Start containers: docker-compose up -d
make docker-down       # Stop containers: docker-compose down
make docker-logs       # View logs: docker-compose logs -f
```

---

## 6. Environment Variables & Configuration

### Location
- **Template**: `.env.example`
- **Active**: `.env`
- **Settings Module**: `config/settings.py`

### Configuration Categories

#### AI Model Configuration
```ini
API_KEY=your_api_key_here                                  # Qwen API Key
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen3.5-plus                                    # Main model
MODEL_NAME_LIGHT=qwen3.5-flash                             # Light model
```

#### Browser Configuration
```ini
BROWSER_HEADLESS=false                                     # Show/hide browser
BROWSER_USER_DATA_DIR=./browser_data                       # Session storage
BROWSER_VIEWPORT_WIDTH=1280
BROWSER_VIEWPORT_HEIGHT=720
BROWSER_DEBUG_PORT=9222                                    # Optional debug port
BROWSER_PROXY=http://proxy:port                            # Optional proxy
```

#### Database Configuration
```ini
# MySQL (for conversations persistence)
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password_here
MYSQL_DATABASE=xianyu_conversations
MYSQL_POOL_SIZE=5

# Redis (session cache)
REDIS_URL=redis://localhost:6379
REDIS_SESSION_TTL=1800                                     # 30 minutes
```

#### API Configuration
```ini
ENABLE_AI_REPLY=false                                      # AI auto-reply toggle
AGENT_SERVICE_URL=http://localhost:8000                    # Agent API URL
AGENT_TIMEOUT=10.0                                         # Request timeout
AGENT_MAX_RETRIES=3
AGENT_RETRY_DELAY=1.0
```

#### Xianyu Business Configuration
```ini
COOKIES_STR=your_cookies_here                              # Xianyu cookies
SELLER_USER_ID=your_seller_id                              # Seller identification
TOGGLE_KEYWORDS=。                                          # Manual/auto toggle key
MESSAGE_EXPIRE_TIME=300000                                 # Message expiry (ms)
MANUAL_MODE_TIMEOUT=3600                                   # Manual mode timeout (s)
```

#### Rental Business Configuration
```ini
RENTAL_API_BASE_URL=http://13uy63225pa7.vicp.fun/api/rentals
RENTAL_FIND_SLOT_ENDPOINT=/find-slot
```

#### DingTalk Integration
```ini
DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=...
DINGTALK_SECRET=SEC_your_secret_here
DINGTALK_APP_KEY=your_app_key_here
DINGTALK_APP_SECRET=your_app_secret_here
```

#### Logging
```ini
LOG_LEVEL=INFO                                             # DEBUG, INFO, WARNING, ERROR
```

### Settings Class Location
- File: `config/settings.py`
- Class: `Settings(BaseSettings)`
- Framework: Pydantic v2 with pydantic-settings

---

## 7. Port Numbers Summary

| Service | Port | Protocol | Purpose | Configuration |
|---------|------|----------|---------|----------------|
| FastAPI/Uvicorn | 8000 | HTTP | Main API server | `api_port` in settings |
| MySQL | 3306 | TCP | Database | `mysql_port` in settings |
| Redis | 6379 | TCP | Cache & sessions | `redis_url` in settings |
| Vite Dev Server | 5173 | HTTP | UI development | Default Vite port |
| Browser Debug | 9222 | TCP | Chrome DevTools | `BROWSER_DEBUG_PORT` (optional) |

---

## 8. Build & Run Commands

### Using Makefile

```bash
# Installation
make install                  # Install production dependencies
make install-dev              # Install development dependencies
make check-env                # Verify environment setup

# Running Services
make run-xianyu               # Start Xianyu interceptor bot
make run-api                  # Start FastAPI backend
make run-api-dev              # Start FastAPI (development mode, hot reload)
make init-knowledge           # Initialize knowledge base

# UI Development
make ui-install               # Install UI dependencies
make ui-dev                   # Start UI dev server (port 5173)
make ui-build                 # Build production UIs

# Testing
make test                     # Run all tests
make test-unit                # Unit tests only
make test-integration         # Integration tests only
make test-cov                 # Tests with coverage report

# Code Quality
make lint                     # Ruff + MyPy checks
make format                   # Code formatting (Ruff)

# Docker
make docker-build             # Build Docker image
make docker-up                # Start Docker containers
make docker-down              # Stop Docker containers
make docker-logs              # View container logs

# Cleanup
make clean                    # Remove cache/temp files
make clean-all                # Remove .venv, data, browser_data
```

### Manual Commands

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Run Xianyu bot
python run_xianyu.py

# Run API
python -m uvicorn ai_kefu.api.main:app --host 0.0.0.0 --port 8000

# Initialize knowledge base
python scripts/init_knowledge.py

# Run tests
pytest tests/ -v
pytest tests/unit/ -v
pytest tests/integration/ -v
```

---

## 9. Key Dependencies

### Python Dependencies (`requirements.txt`)

#### AI/LLM
- `openai==1.65.5` - OpenAI SDK (used for compatible API)
- `pydantic==2.5.0` - Data validation
- `pydantic-settings==2.1.0` - Settings management

#### Web Framework
- `fastapi==0.108.0` - Web framework
- `uvicorn[standard]==0.25.0` - ASGI server
- `gunicorn==21.2.0` - Production server

#### Browser Automation
- `playwright>=1.40.0` - Browser control

#### Vector Database
- `chromadb==1.4.0` - Vector embeddings storage

#### Storage
- `redis==5.0.1` - Cache & session storage
- `pymysql==1.1.0` - MySQL adapter
- `cryptography==41.0.7` - Encryption

#### Utilities
- `loguru==0.7.3` - Logging
- `websockets==13.1` - WebSocket support
- `python-dotenv==1.0.1` - Environment variables
- `requests==2.32.3` - HTTP client
- `tenacity==8.2.3` - Retry logic

#### Data Processing
- `pandas>=1.5.0` - Data analysis
- `openpyxl>=3.0.0` - Excel support

#### Testing
- `pytest>=7.0.0`
- `pytest-asyncio>=0.21.0`
- `pytest-cov>=4.0.0`
- `pytest-mock>=3.10.0`
- `httpx>=0.27.0,<1`

#### Code Quality
- `ruff==0.1.9` - Linter
- `mypy==1.7.1` - Type checker
- `aiohttp>=3.9.0` - Async HTTP

#### Special
- `dingtalk-stream>=0.24.0` - DingTalk integration
- `PyExecJS>=1.5.1` - JavaScript execution (for XianYuApis)

### JavaScript Dependencies (UI)

**Knowledge & Conversations UIs**:
- `vue@^3.4.15` - Vue 3 framework
- `vue-router@^4.2.5` - Routing
- `@vitejs/plugin-vue@^5.0.3` - Vite plugin
- `vite@^5.0.11` - Build tool

---

## 10. Database Configuration

### MySQL
- **Purpose**: Conversation persistence, knowledge entries
- **Default Port**: 3306
- **Default Database**: `xianyu_conversations`
- **Default User**: `root`
- **Connection String Format**: 
  ```
  mysql+pymysql://user:password@host:port/database
  ```
- **Migrations**: Located in `migrations/` directory

### Redis
- **Purpose**: Session cache, state management
- **Default Port**: 6379
- **URL Format**: `redis://[password@]host[:port][/db]`
- **Session TTL**: 1800 seconds (30 minutes, configurable)
- **Data Storage**: In-memory with optional persistence

### Chroma (Vector Database)
- **Purpose**: Knowledge base embeddings
- **Storage Path**: `./chroma_data/` (default)
- **SQLite Backend**: Chroma uses SQLite for metadata
- **Data Format**: Collections with embedding vectors

---

## 11. Configuration Files

### .env.example Structure
- 150+ lines of configuration documentation
- Organized by sections: AI, Browser, Database, API, DingTalk, etc.
- All configuration keys with descriptions

### Settings Module
- **File**: `config/settings.py`
- **Class**: `Settings(BaseSettings)`
- Uses Pydantic v2 for validation
- Auto-loads from `.env` file
- Type hints for all configurations

### Configuration Validation
```python
@model_validator(mode="after")
def _fill_xianyu_cookie_from_cookies_str(self) -> "Settings":
    """Automatic fallback: COOKIES_STR → xianyu_cookie"""
```

---

## 12. Project Features & Capabilities

### AI Customer Service Features
- Intelligent response generation (Qwen API)
- Knowledge base retrieval (semantic search via Chroma)
- Human-in-the-loop workflow
- Session management (Redis)
- Multi-turn conversations

### Xianyu Integration
- Browser-based message interception (CDP)
- WebSocket message handling
- Session persistence
- Automatic/manual mode toggle

### Rental Business System
- Equipment availability checking
- Logistics time calculation
- Dynamic pricing
- Deposit policy management
- Knowledge base for FAQs

### Administration & Monitoring
- Knowledge management UI (Vue)
- Conversation history viewer
- System health endpoints
- DingTalk notifications
- Comprehensive logging

---

## 13. Entry Points Summary

| Component | Entry Point | Command | Port |
|-----------|-------------|---------|------|
| Xianyu Bot | `run_xianyu.py` | `python run_xianyu.py` | N/A (browser) |
| API Backend | `api/main.py` | `python -m uvicorn ai_kefu.api.main:app --port 8000` | 8000 |
| Knowledge UI | `ui/knowledge/` | `npm run dev` | 5173 |
| Conversations UI | `ui/conversations/` | `npm run dev` | 5173 |
| Docker | `docker-compose.yml` | `docker-compose up` | Varies |

---

## 14. Typical Deployment Architecture

```
┌─────────────────────────────────────────────────────────┐
│          Docker Compose / Kubernetes / Cloud           │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌────────────────┐  ┌──────────┐  ┌──────────────┐   │
│  │ FastAPI Server │  │  MySQL   │  │    Redis     │   │
│  │  (Port 8000)   │  │ (3306)   │  │   (6379)     │   │
│  │                │  │          │  │              │   │
│  │ - Chat API     │  │ Conv.DB  │  │ Session Cache│   │
│  │ - Knowledge    │  │ Knowledge│  │              │   │
│  │ - Sessions     │  │          │  │              │   │
│  │ - Admin UIs    │  │          │  │              │   │
│  └────────────────┘  └──────────┘  └──────────────┘   │
│         ▲                                                 │
│         │ HTTP/WebSocket                                │
│         │                                                 │
└─────────│────────────────────────────────────────────────┘
          │
    ┌─────▼──────────────┐
    │ Xianyu Interceptor │
    │   (run_xianyu.py)  │
    │                    │
    │  ┌──────────────┐  │
    │  │ CDP Browser  │  │
    │  │ (Chromium)   │  │
    │  └──────────────┘  │
    └────────────────────┘
          │
    ┌─────▼──────────┐
    │ Xianyu Website │
    │  (goofish.com) │
    └────────────────┘
```

---

## Summary

The **XianyuAutoAgent/ai_kefu** project is a sophisticated, production-ready AI customer service system with:

✅ **Dual Frontend Components**:
- Python-based Xianyu message interceptor (browser CDP)
- FastAPI backend API service

✅ **Multiple UIs**:
- Knowledge Management (Vue 3)
- Conversations History (Vue 3)

✅ **Enterprise Features**:
- Docker containerization
- Redis session management
- MySQL persistence
- DingTalk notifications
- Comprehensive logging

✅ **Developer-Friendly**:
- Makefile automation
- Comprehensive documentation
- Environment-based configuration
- Development & production modes
- Full test suite support

✅ **Port Summary**:
- API: 8000
- MySQL: 3306
- Redis: 6379
- UI Dev: 5173
- Browser Debug: 9222 (optional)
