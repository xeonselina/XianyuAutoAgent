# XianyuAutoAgent/ai_kefu - Architecture Summary

## 🏗️ High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        XIANYU AUTO AGENT                            │
│              AI-Powered Customer Service System                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    EXTERNAL SERVICES                                │
├─────────────────────────────────────────────────────────────────────┤
│  • Goofish.com (闲鱼)      [Xianyu marketplace platform]           │
│  • Qwen API (DashScope)    [AI model via OpenAI-compatible API]    │
│  • DingTalk                [Team communication notifications]       │
│  • Rental Business API     [Equipment availability & pricing]       │
└─────────────────────────────────────────────────────────────────────┘

┌──────────────────────────┐
│  BROWSER INTERCEPTOR     │
│   (run_xianyu.py)        │
│                          │
│  • Playwright browser    │
│  • Chrome DevTools Prot  │
│  • WebSocket intercept   │
│  • Message forwarding    │
└──────────────┬───────────┘
               │ HTTP POST /xianyu/inbound
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      FASTAPI BACKEND                                │
│                      (api/main.py)                                  │
│                      Port: 8000                                     │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │              API ROUTES                                    │   │
│  ├────────────────────────────────────────────────────────────┤   │
│  │  • /chat              - Chat endpoint                      │   │
│  │  • /sessions          - Session management                │   │
│  │  • /knowledge         - Knowledge base                    │   │
│  │  • /conversations     - History & analytics               │   │
│  │  • /xianyu/inbound    - Message receiver                  │   │
│  │  • /xianyu/outbound   - Message sender                    │   │
│  │  • /human-agent       - Human workflow                    │   │
│  │  • /prompts           - Prompt management                 │   │
│  │  • /dingtalk          - DingTalk integration              │   │
│  │  • /eval              - Evaluation endpoints              │   │
│  │  • /ui/knowledge      - Knowledge UI (static)             │   │
│  │  • /ui/conversations  - Conversations UI (static)         │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │              AGENT ENGINE                                 │   │
│  ├────────────────────────────────────────────────────────────┤   │
│  │  • Turn management (agent/)                               │   │
│  │  • Tool execution                                         │   │
│  │  • Response generation (Qwen LLM)                         │   │
│  │  • Confidence scoring                                     │   │
│  │  • Loop detection                                         │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │              TOOLS / FUNCTIONS                             │   │
│  ├────────────────────────────────────────────────────────────┤   │
│  │  • knowledge_search          - Semantic search            │   │
│  │  • calculate_logistics       - Shipping time calculation  │   │
│  │  • calculate_price           - Dynamic pricing            │   │
│  │  • check_availability        - Equipment availability     │   │
│  │  • collect_rental_info       - Information gathering      │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                      │
└──────────┬───────────────────────────────────────┬─────────────────┘
           │                                       │
           │                                       │
     ┌─────▼─────────────────────────────────────▼──────┐
     │         STORAGE LAYER                           │
     ├───────────────────────────────────────────────────┤
     │                                                   │
     │  ┌──────────────┐  ┌──────────┐  ┌─────────┐   │
     │  │   CHROMA     │  │  REDIS   │  │ MYSQL   │   │
     │  │(Embeddings)  │  │(Cache)   │  │(Persist)│   │
     │  ├──────────────┤  ├──────────┤  ├─────────┤   │
     │  │ • Knowledge  │  │ • Sess.  │  │ • Conv. │   │
     │  │   vectors    │  │   cache  │  │   data  │   │
     │  │ • Documents  │  │ • State  │  │ • Know. │   │
     │  │ • Collections│  │ • TTL    │  │   base  │   │
     │  │ (./chroma_   │  │ (6379)   │  │ (3306)  │   │
     │  │  data/)      │  │          │  │         │   │
     │  └──────────────┘  └──────────┘  └─────────┘   │
     │                                                   │
     └───────────────────────────────────────────────────┘
           │                    │
           │                    │
        Local FS          External Services
        SQLite            (Container network)
```

---

## 🎯 Request Flow: Message Interception → Response

```
1. USER IN XIANYU
   └─ Opens goofish.com/chat
   └─ Sends a message

2. BROWSER INTERCEPTOR (run_xianyu.py)
   └─ CDP detects WebSocket message
   └─ Extracts message data
   └─ Parses sender, content, chat_id
   └─ HTTP POST → /xianyu/inbound

3. API RECEIVES MESSAGE
   └─ FastAPI route handler
   └─ Validates payload
   └─ Stores in MySQL
   └─ Checks enable_ai_reply flag
   
4. AGENT PROCESSES
   ├─ Retrieves conversation history
   ├─ Builds system prompt
   ├─ Executes tools as needed
   │  ├─ knowledge_search (Chroma)
   │  ├─ calculate_price (business logic)
   │  └─ check_availability (external API)
   ├─ Calls Qwen LLM
   ├─ Scores confidence
   └─ Generates response

5. API SENDS RESPONSE
   └─ Returns to interceptor
   └─ If enable_ai_reply=true:
      └─ Passes response to outbound handler

6. INTERCEPTOR SENDS TO XIANYU
   └─ Browser sends message through Xianyu UI
   └─ CDP injects response
   └─ User sees AI reply in chat

7. UPDATE STORAGE
   └─ Store response in MySQL
   └─ Update session in Redis
   └─ Update embeddings if applicable
```

---

## 🔄 Data Models

### Xianyu Message Flow
```
XianyuMessage (xianyu_interceptor/models.py)
├─ chat_id: str                    # Conversation ID
├─ user_id: str                    # Customer ID
├─ encrypted_uid: str              # Encrypted customer identifier
├─ user_nickname: str              # Customer display name
├─ content: str                    # Message content
├─ message_id: str                 # Unique message ID
├─ item_id: str                    # Product ID (optional)
├─ item_title: str                 # Product title (optional)
├─ timestamp: int                  # Unix timestamp
├─ metadata: Dict                  # Additional context
└─ is_self_sent: bool             # True if seller sent it
```

### Conversation Storage (MySQL)
```
conversations table
├─ id: UUID                        # Primary key
├─ chat_id: str                    # Xianyu chat ID
├─ user_id: str                    # Customer identifier
├─ message: str                    # Message content
├─ response: str                   # AI response (if generated)
├─ timestamp: datetime             # When sent
├─ metadata: JSON                  # Context data
└─ deleted_at: datetime (soft del)
```

### Session Management (Redis)
```
session:{session_id}
├─ chat_id: str
├─ user_id: str
├─ conversation_history: List
├─ state: enum (idle|manual|ai_response)
├─ last_activity: timestamp
├─ ttl: 1800 seconds (configurable)
└─ manual_mode_active: bool
```

---

## 🔌 External API Integrations

### 1. Qwen LLM (Alibaba DashScope)
```
FastAPI → OpenAI SDK (compatible-mode)
        → https://dashscope.aliyuncs.com/compatible-mode/v1
        → POST /chat/completions

Parameters:
├─ model: "qwen3.5-plus" or "qwen3.5-flash"
├─ messages: conversation history
├─ temperature: 0.3
├─ top_p: 0.9
├─ max_tokens: 256
├─ tools: agent tools definition
└─ timeout: 30 seconds
```

### 2. Rental Business API
```
FastAPI → check_availability()
       → POST http://13uy63225pa7.vicp.fun/api/rentals/find-slot
       ├─ start_date: "2024-02-11"
       ├─ end_date: "2024-02-19"
       └─ device_type: "iPhone 15 Pro"
```

### 3. DingTalk (Team Notifications)
```
FastAPI → POST https://oapi.dingtalk.com/robot/send
       ├─ webhook_url: (configured in .env)
       ├─ message: "Customer inquiry: ..."
       ├─ timestamp: Unix time
       └─ sign: HMAC-SHA256 signature
```

---

## 🗂️ File Organization

### Critical Application Files
```
ai_kefu/
├── run_xianyu.py              ◄── START HERE for browser interceptor
├── api/main.py                ◄── START HERE for backend API
├── requirements.txt           ◄── Python dependencies
├── Dockerfile                 ◄── Production image
├── docker-compose.yml         ◄── Services (MySQL, Redis)
├── Makefile                   ◄── Build automation
├── .env.example               ◄── Configuration template
│
├── config/settings.py         ◄── Configuration schema
├── xianyu_interceptor/        ◄── Message interception (CDP)
├── xianyu_provider/           ◄── Xianyu API wrapper
├── api/routes/                ◄── API endpoint handlers
├── agent/                     ◄── Agent engine
├── tools/                     ◄── Tool implementations
├── storage/                   ◄── DB abstractions
├── llm/                       ◄── LLM client
├── services/                  ◄── Business logic
├── models/                    ◄── Data models
├── prompts/                   ◄── AI system prompts
├── ui/knowledge/              ◄── Knowledge Management UI (Vue)
├── ui/conversations/          ◄── Conversations UI (Vue)
└── scripts/                   ◄── Setup & utilities
```

---

## 🚀 Deployment Architectures

### Development Setup
```
┌─────────────────┐
│  Local Machine  │
├─────────────────┤
│ • Python venv   │
│ • Redis local   │
│ • MySQL local   │
│ • Node.js (UI)  │
└─────────────────┘
     ▲ │ ▼
   Port 8000    (API)
   Port 3306    (MySQL)
   Port 6379    (Redis)
   Port 5173    (Vite dev)
```

### Docker-Compose Setup (Recommended)
```
┌──────────────────────────────┐
│   Docker Compose Network     │
├──────────────────────────────┤
│                              │
│  ┌─────┐  ┌────┐  ┌────┐   │
│  │ API │  │ DB │  │ RD │   │
│  │8000 │  │3306│  │6379│   │
│  └─────┘  └────┘  └────┘   │
│                              │
└──────────────────────────────┘
      ▲
  localhost mapping
```

### Kubernetes / Cloud
```
┌────────────────────────────────────┐
│   Kubernetes Cluster               │
├────────────────────────────────────┤
│ ┌──────────┐  ┌──────────────────┐ │
│ │ API Pod  │  │  Interceptor Pod │ │
│ │(Scaled)  │◄─►(For each bot)    │ │
│ └────┬─────┘  └────────┬─────────┘ │
│      │                 │            │
│      └─────────┬───────┘            │
│                │                    │
│     ┌──────────▼──────────┐        │
│     │ Persistent Storage  │        │
│     ├─────────────────────┤        │
│     │ • MySQL ClusterIP   │        │
│     │ • Redis Sentinel    │        │
│     │ • Chroma PVC        │        │
│     └─────────────────────┘        │
│                                    │
└────────────────────────────────────┘
```

---

## 📊 Component Dependencies

### Python Package Hierarchy
```
FastAPI
├─ Uvicorn (ASGI server)
├─ Pydantic (data validation)
├─ SQLAlchemy (ORM, if used)
│
Qwen LLM Integration
├─ openai (SDK for compatible API)
├─ requests (HTTP client)
├─ tenacity (retry logic)
│
Browser Automation
├─ Playwright
├─ websockets
│
Vector Database
├─ chromadb
├─ numpy
│
Cache & Session
├─ redis
│
Persistence
├─ pymysql
├─ SQLAlchemy
│
Notifications
└─ dingtalk-stream
```

---

## 🔐 Security Considerations

### Authentication
- **Browser Session**: Stored in Chromium user data dir
- **Xianyu Cookies**: From browser or environment variable
- **API Key**: Qwen API key in environment only
- **Database**: MySQL credentials in environment

### Data Protection
- **Redis**: In-memory (no persistence by default)
- **MySQL**: Conversations stored, softly deleted
- **Encryption**: cryptography module for sensitive data
- **CORS**: Configured (currently allow_origins="*")

### Best Practices
1. **Never commit .env** - use .env.example
2. **Secure cookies** - Chromium handles automatically
3. **Validate inputs** - Pydantic models enforce
4. **Rate limiting** - Can be added to routes
5. **Logging** - Sensitive data filtered

---

## 📈 Performance Characteristics

### Throughput
- **Messages/sec**: Limited by Qwen API rate limits (~10 RPS base)
- **Concurrent sessions**: Redis/MySQL handle 100+ concurrent
- **KB search**: Chroma semantic search ~50-200ms

### Latency
- **Message intercept → API**: ~100ms
- **Qwen API call**: 1-5 seconds typical
- **Full response cycle**: 2-8 seconds
- **Redis lookup**: <10ms
- **MySQL query**: 50-200ms typical

### Scalability
- **Horizontal**: Multiple API instances (use load balancer)
- **Vertical**: More workers in Gunicorn
- **Storage**: MySQL replication, Redis sentinel
- **Cache**: Redis persistence, pub/sub support

---

## 🛠️ Technology Versions

```
Python:         3.10+
FastAPI:        0.108.0
Uvicorn:        0.25.0
Pydantic:       2.5.0
Playwright:     >=1.40.0
ChromaDB:       1.4.0
Redis:          7-alpine (docker)
MySQL:          8.0
Node.js:        18+ (for UI build)
Vue:            3.4.15
Vite:           5.0.11
```

---

## 🎓 Learning Resources

### Code Entry Points (Read in This Order)
1. `README.md` - Overview and quick start
2. `api/main.py` - FastAPI structure
3. `api/routes/chat.py` - Request handling
4. `agent/executor.py` - Agent logic
5. `tools/` - Tool implementations
6. `xianyu_interceptor/` - Message capture

### Configuration
- `.env.example` - All available settings
- `config/settings.py` - Schema & validation
- `Makefile` - Build & runtime examples

### Documentation
- `docs/PROJECT_OVERVIEW.md` - Architecture
- `docs/start-api.md` - API setup
- `QUICK_REFERENCE.md` - Commands cheat sheet

---

## 🎯 Quick Decision Tree

**I want to...**

- **Run locally**: `make install && make run-api && make run-xianyu`
- **Run in Docker**: `make docker-build && make docker-up`
- **Develop the API**: `make run-api-dev`
- **Develop the UI**: `make ui-dev`
- **Deploy to cloud**: Build Docker image, set env vars, run
- **Debug issues**: Check logs/ directory, verify .env
- **Test endpoints**: Go to http://localhost:8000/docs
- **Monitor conversations**: Visit http://localhost:8000/ui/conversations

---

## 📞 Support & Documentation

| Resource | Location |
|----------|----------|
| Full README | `README.md` |
| Quick Start | `QUICK_REFERENCE.md` |
| Detailed Exploration | `CODEBASE_EXPLORATION_DETAILED.md` |
| Architecture Docs | `docs/PROJECT_OVERVIEW.md` |
| API Setup | `docs/start-api.md` |
| Knowledge UI | `docs/KNOWLEDGE_UI_SETUP.md` |
| Environment Config | `.env.example` |

---

**Last Updated**: 2026-04-24
**Project**: XianyuAutoAgent/ai_kefu
**Status**: Production-Ready ✅
