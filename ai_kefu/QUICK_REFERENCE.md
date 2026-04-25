# XianyuAutoAgent/ai_kefu - Quick Reference Guide

## 🎯 Quick Start

### What This Project Does
AI-powered customer service system for Xianyu (Alibaba's second-hand marketplace) with:
- Automated message interception and response
- Human-in-the-loop workflow
- Knowledge base management
- Conversation analytics

### Prerequisites
- Python 3.10+
- Node.js 18+ (for UI)
- Docker & Docker Compose (optional, for containers)
- Qwen API Key (from Alibaba DashScope)

---

## 🚀 Running the Services

### Quick Setup (5 minutes)
```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu

# Install dependencies
make install

# Copy environment template
cp .env.example .env
# Edit .env and add your API_KEY

# Initialize knowledge base
make init-knowledge

# Start API backend
make run-api

# In another terminal, start Xianyu interceptor
make run-xianyu
```

### Service Ports
| Service | Port | URL |
|---------|------|-----|
| API Backend | 8000 | http://localhost:8000 |
| Knowledge UI | 8000 | http://localhost:8000/ui/knowledge |
| Conversations UI | 8000 | http://localhost:8000/ui/conversations |
| UI Dev Server | 5173 | http://localhost:5173 |
| MySQL | 3306 | localhost:3306 |
| Redis | 6379 | localhost:6379 |

---

## 📁 Project Structure at a Glance

### Core Components
```
Run Xianyu interceptor:     run_xianyu.py          → Port: Browser
                            ↓
                    xianyu_interceptor/ (CDP)
                            ↓
                    → POST /xianyu/inbound
                            ↓
            api/main.py (FastAPI)              → Port: 8000
            ├── Chat endpoints                 ↗
            ├── Knowledge base                 |
            ├── Session management            |
            └── Admin UIs (Vue)       ────────┘
                ├── /ui/knowledge
                └── /ui/conversations
                            ↓
            Storage Layer (Redis, MySQL, Chroma)
```

### Key Directories
| Directory | Purpose |
|-----------|---------|
| `api/` | FastAPI backend with all routes |
| `xianyu_interceptor/` | Browser message interception (CDP) |
| `ui/` | Vue 3 frontend applications |
| `tools/` | Agent tools (pricing, logistics, knowledge search) |
| `storage/` | Database abstraction layers |
| `config/` | Configuration management |
| `scripts/` | Setup and utility scripts |

---

## 🔧 Common Makefile Commands

```bash
# Installation & Setup
make install              # Install dependencies
make install-dev          # Install dev dependencies
make check-env            # Verify .env setup

# Running Services
make run-xianyu           # Start message interceptor bot
make run-api              # Start FastAPI backend
make run-api-dev          # Start API with hot reload
make init-knowledge       # Initialize knowledge base

# UI Development
make ui-install           # Install UI dependencies
make ui-dev               # Start Vite dev server (port 5173)
make ui-build             # Build production UIs

# Development
make test                 # Run all tests
make lint                 # Code quality checks
make format               # Code formatting

# Docker
make docker-build         # Build Docker image
make docker-up            # Start Docker containers
make docker-down          # Stop Docker containers
```

---

## ⚙️ Configuration

### Environment Variables (.env)

**Must Set**:
```ini
API_KEY=your_qwen_api_key_here
```

**Optional but Recommended**:
```ini
ENABLE_AI_REPLY=true                    # Enable AI responses
BROWSER_HEADLESS=false                  # Show browser window
REDIS_URL=redis://localhost:6379        # Redis connection
MYSQL_USER=root                         # MySQL user
MYSQL_PASSWORD=your_password            # MySQL password
SELLER_USER_ID=your_seller_id           # For Xianyu
```

All options in `.env.example` (150+ lines)

---

## 📊 Technology Stack

| Component | Technology |
|-----------|-----------|
| **Backend API** | FastAPI (Python) |
| **Frontend UI** | Vue 3 + Vite |
| **Browser Bot** | Playwright + Chrome CDP |
| **LLM** | Alibaba Qwen (via OpenAI SDK) |
| **Vector DB** | Chroma (embeddings) |
| **Cache** | Redis |
| **Persistence** | MySQL |
| **Containerization** | Docker + Docker Compose |

---

## 🐳 Docker Quick Start

```bash
# Build image
make docker-build

# Start all services (API, MySQL, Redis)
make docker-up

# View logs
make docker-logs

# Stop services
make docker-down
```

Services started:
- API on port 8000
- MySQL on port 3306
- Redis on port 6379

---

## 🧪 Testing

```bash
make test                 # All tests
make test-unit            # Unit tests only
make test-integration     # Integration tests
make test-cov             # With coverage report
```

---

## 📝 API Endpoints (Main)

### Chat & Conversations
```
POST   /chat              # Send a message
POST   /chat/stream       # Stream responses
GET    /sessions/{id}     # Get session
DELETE /sessions/{id}     # Delete session
```

### Knowledge Base
```
GET    /knowledge/search  # Search knowledge base
POST   /knowledge         # Add to KB
GET    /knowledge/export  # Export KB
```

### System
```
GET    /docs              # Swagger UI
GET    /redoc             # ReDoc API docs
GET    /health            # Health check
```

Full API docs at: `http://localhost:8000/docs`

---

## 🔍 File Locations - Important Files

| File | Purpose |
|------|---------|
| `api/main.py` | FastAPI app entry point |
| `run_xianyu.py` | Xianyu interceptor entry point |
| `config/settings.py` | Configuration management |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Docker image definition |
| `docker-compose.yml` | Docker services |
| `Makefile` | Build automation |
| `.env` | Environment variables (create from .env.example) |
| `.env.example` | Configuration template |

---

## 🆘 Troubleshooting

### API won't start
```bash
# Check Redis
redis-cli ping  # Should return PONG

# Check environment
make check-env

# Check logs
tail -f logs/api.log
```

### Xianyu interceptor not connecting
```bash
# Ensure you're logged into Xianyu in the browser
# Manually open https://www.goofish.com/
# Click into a message
# Then run: make run-xianyu
```

### Can't find dependencies
```bash
# Reinstall
make clean
make install
```

### Database connection error
```bash
# MySQL
mysql -h localhost -u root -p

# Redis
redis-cli ping

# Check config in .env
```

---

## 📚 Documentation

- Full guide: `README.md`
- Detailed exploration: `CODEBASE_EXPLORATION_DETAILED.md` (new!)
- Architecture: `docs/PROJECT_OVERVIEW.md`
- API setup: `docs/start-api.md`
- UI setup: `docs/KNOWLEDGE_UI_SETUP.md`

---

## 🎓 Learning Path

1. **Understand the system**: Read `README.md` project overview
2. **Set up environment**: `make install` + `cp .env.example .env`
3. **Start API**: `make init-knowledge` + `make run-api`
4. **Try API**: Visit `http://localhost:8000/docs`
5. **Start bot**: Open Xianyu in browser, then `make run-xianyu`
6. **Explore UI**: Check knowledge and conversations UIs

---

## 🔗 Important URLs (after starting services)

```
API & Docs:
  http://localhost:8000              # API root
  http://localhost:8000/docs         # Swagger UI
  http://localhost:8000/redoc        # ReDoc docs
  
Frontend UIs:
  http://localhost:8000/ui/knowledge      # Knowledge Management
  http://localhost:8000/ui/conversations  # Conversation History
  
Development:
  http://localhost:5173              # Vite dev server (if running UI dev)
```

---

## 💡 Pro Tips

1. **Hot reload development**: Use `make run-api-dev` for automatic reloads
2. **Enable AI responses**: Set `ENABLE_AI_REPLY=true` in `.env`
3. **Debug mode**: Set `LOG_LEVEL=DEBUG` in `.env`
4. **Database inspection**: 
   - MySQL: `mysql -h localhost -u root -p xianyu_conversations`
   - Redis: `redis-cli`
5. **UI development**: `make ui-dev` for instant Vite reload
6. **Production build UIs**: `make ui-build` then rebuild Docker image

---

## 🏃 One-Liner Quick Starts

```bash
# Full development environment
make install && make init-knowledge && make run-api-dev

# Just the API
make run-api

# Just the bot
make run-xianyu

# Docker everything
make docker-build && make docker-up

# Run tests with coverage
make test-cov

# Full development with UIs
make install ui-install run-api-dev ui-dev  # Run in separate terminals
```

---

## 📞 Support

- **Issues**: GitHub repository issues
- **Docs**: See `docs/` directory
- **Config**: Check `.env.example` for all options
- **Logs**: Check `logs/` directory for error messages

---

## 🚀 Next Steps

1. Start with `make install`
2. Configure `.env`
3. Run `make init-knowledge`
4. Start API with `make run-api`
5. Start bot with `make run-xianyu` (in another terminal)
6. Access APIs at `http://localhost:8000/docs`
7. Monitor conversations at `http://localhost:8000/ui/conversations`

---

**Happy hacking!** 🎉

*For detailed information, see `CODEBASE_EXPLORATION_DETAILED.md`*
