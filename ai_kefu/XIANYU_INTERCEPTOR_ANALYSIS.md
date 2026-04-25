# Xianyu Interceptor - Complete Analysis

## 1. What is the Xianyu Interceptor? What does it do at runtime?

### Overview
The **Xianyu Interceptor** is a **transport-layer relay** that intercepts Xianyu (second-hand marketplace) messages via a browser and relays them to an AI API backend.

### Runtime Workflow
```
┌─────────────────────────────────────────────────────────────┐
│ Xianyu Interceptor (run_xianyu.py)                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ 1. Launch Chromium Browser (via Playwright)                 │
│    ↓                                                        │
│ 2. Navigate to https://www.goofish.com/                     │
│    ↓                                                        │
│ 3. Inject CDP (Chrome DevTools Protocol) WebSocket          │
│    interceptor to capture all messages                      │
│    ↓                                                        │
│ 4. Monitor all pages for new WebSocket connections          │
│    • Existing pages (context.pages)                         │
│    • New pages (context.on("page"))                         │
│    • Page navigation events (framenavigated)                │
│    ↓                                                        │
│ 5. Decode WebSocket messages using XianyuMessageCodec      │
│    ↓                                                        │
│ 6. Deduplicate messages (MessageDeduplicator)               │
│    ↓                                                        │
│ 7. POST decoded messages to AI API (/xianyu/inbound)        │
│    ↓                                                        │
│ 8. If API returns a reply, send it back via browser         │
│    (BrowserTransport → CDPInterceptor)                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Key Responsibilities
- **Pure transport relay**: No business logic (all moved to API layer)
- **WebSocket interception**: Uses CDP to capture browser WebSocket frames
- **Message decoding**: Converts binary Xianyu protocol to standard format
- **Deduplication**: Prevents duplicate processing from WebSocket redeliveries
- **HTTP relay**: POSTs messages to `/xianyu/inbound` endpoint
- **Reply sending**: Sends AI responses back through the browser
- **Multi-page support**: Handles messages from any page/tab/iframe
- **Cookie management**: Pushes browser cookies to API every 30 minutes
- **History parsing**: Detects and saves historical messages
- **Image handling**: Extracts and downloads images from messages

---

## 2. Files Used by the Interceptor

### Core Directory Structure
```
ai_kefu/
├── xianyu_interceptor/          # Transport relay implementation
│   ├── __init__.py              # Public API exports
│   ├── config.py                # Transport-level config (cookies, browser, image_save_dir)
│   ├── models.py                # Data models (XianyuMessage, XianyuMessageType, etc.)
│   ├── browser_controller.py    # Chromium browser lifecycle (Playwright)
│   ├── browser_transport.py     # Wrapper for sending replies via CDP
│   ├── cdp_interceptor.py       # CDP WebSocket interception + injection
│   ├── messaging_core.py        # Message encoding/decoding (XianyuMessageCodec)
│   ├── message_handler.py       # Thin relay (POST to API + send replies)
│   ├── image_handler.py         # Image extraction and downloading
│   ├── history_message_parser.py # Parse historical message API responses
│   ├── uid_mapper.py            # Map user IDs to encrypted UIDs
│   ├── logging_setup.py         # Loguru configuration
│   ├── main_integration.py      # Initialization function (initialize_interceptor)
│   ├── exceptions.py            # Custom exceptions
│   ├── conversation_store.py    # (Optional, mostly used by API layer)
│   ├── session_mapper.py        # (Legacy, not used by transport)
│   ├── manual_mode.py           # (Legacy, moved to API layer)
│   └── __pycache__/             # Compiled bytecode
│
├── xianyu_provider/             # Xianyu API abstraction
│   ├── __init__.py              # Exports provider implementation
│   ├── base.py                  # XianyuProvider ABC (abstract interface)
│   ├── goofish_provider.py      # GoofishProvider (implements XianyuProvider)
│   └── upstream/                # Git submodule: cv-cat/XianYuApis
│       ├── goofish_apis.py      # Upstream API wrapper
│       ├── utils/
│       │   ├── goofish_utils.py # Message encoding, signing, JS execution
│       │   └── ...
│       ├── static/
│       │   └── goofish_js_version_2.js  # JS for signing + device ID
│       └── ...
│
├── run_xianyu.py                # ⭐ Main entry point for interceptor
├── start.sh                     # Startup script (legacy, for main.py)
├── check_boot.sh                # Environment diagnostics script
├── .env                         # Runtime configuration (actual secrets)
├── .env.example                 # Configuration template
├── requirements.txt             # Python dependencies
├── prompts/                     # AI system prompts (not used by interceptor)
├── data/                        # Runtime database (chat_history.db)
├── logs/                        # Log directory (created at runtime)
├── xianyu_images/               # Downloaded images directory (created at runtime)
└── browser_data/                # Playwright browser profile (created at runtime)
```

### Key Files for the Interceptor

| File | Purpose | Runtime Need |
|------|---------|--------------|
| `run_xianyu.py` | Main entry point | ✅ YES |
| `xianyu_interceptor/__init__.py` | Module exports | ✅ YES |
| `xianyu_interceptor/config.py` | Config loading | ✅ YES |
| `xianyu_interceptor/models.py` | Data structures | ✅ YES |
| `xianyu_interceptor/browser_controller.py` | Browser automation | ✅ YES |
| `xianyu_interceptor/cdp_interceptor.py` | WebSocket interception | ✅ YES |
| `xianyu_interceptor/messaging_core.py` | Message codec | ✅ YES |
| `xianyu_interceptor/message_handler.py` | Relay logic | ✅ YES |
| `xianyu_interceptor/browser_transport.py` | Reply sending | ✅ YES |
| `xianyu_interceptor/image_handler.py` | Image download | ✅ YES |
| `xianyu_interceptor/history_message_parser.py` | History parsing | ✅ YES |
| `xianyu_interceptor/logging_setup.py` | Logging config | ✅ YES |
| `xianyu_interceptor/uid_mapper.py` | UID mapping | ✅ YES |
| `xianyu_interceptor/main_integration.py` | Initialization | ✅ YES |
| `.env` | Runtime secrets | ✅ YES (AGENT_SERVICE_URL, COOKIES_STR) |
| `.env.example` | Config template | ⭕ Reference only |
| `requirements.txt` | Dependencies | ✅ YES (install before run) |

**NOT needed by interceptor:**
- `api/` - FastAPI backend (separate process)
- `prompts/` - AI system prompts (used by API, not interceptor)
- `xianyu_provider/goofish_provider.py` - Not used by interceptor (interceptor uses browser, not API)
- `ai_kefu/services/` - API-layer services
- `ai_kefu/models/` - Database models

---

## 3. Python Packages Required (from requirements.txt)

### Minimum for Interceptor Only
```
Core Transport:
  - playwright>=1.40.0           ⭐ Browser automation (Chromium)
  - websockets==13.1             📡 WebSocket support
  - loguru==0.7.3                📝 Logging
  - python-dotenv==1.0.1         ⚙️ Load .env config
  - requests==2.32.3             🌐 HTTP requests (alternative to httpx)

Message Processing:
  - httpx>=0.27.0,<1             🌐 Async HTTP client (POST to API)
  - aiohttp>=3.9.0               🌐 Async image downloading

Extended Functionality:
  - pydantic==2.5.0              ✔️ Data validation
  - pydantic-settings==2.1.0     ⚙️ Settings management (BaseSettings)

Optional for Xianyu API calls:
  - PyExecJS>=1.5.1              ✨ JS execution (for message signing)
  - blackboxprotobuf>=1.0.1      🔐 Message deserialization
  (Requires Node.js >= 18 installed on system)
```

### NOT Needed by Interceptor (API/FastAPI only)
```
❌ fastapi==0.108.0              - API server
❌ uvicorn[standard]==0.25.0     - ASGI server
❌ gunicorn==21.2.0              - Production WSGI
❌ redis==5.0.1                  - Session cache
❌ pymysql==1.1.0                - Database (conversation store)
❌ chromadb==1.4.0               - Vector search
❌ dingtalk-stream>=0.24.0       - DingTalk group messages
❌ pandas>=1.5.0                 - Inventory management
❌ openpyxl>=3.0.0               - Excel handling
❌ openai==1.65.5                - Not used (Qwen via dashscope)
❌ pytest, pytest-asyncio, etc.  - Testing only
❌ mypy, ruff                    - Development only
```

### Minimal requirements-interceptor-only.txt
```
playwright>=1.40.0
websockets==13.1
loguru==0.7.3
python-dotenv==1.0.1
requests==2.32.3
httpx>=0.27.0,<1
aiohttp>=3.9.0
pydantic==2.5.0
pydantic-settings==2.1.0
tenacity==8.2.3

# Optional for Xianyu API calls (requires Node.js)
PyExecJS>=1.5.1
blackboxprotobuf>=1.0.1
```

---

## 4. Playwright Browser Usage

### Browser Launch Details
From `xianyu_interceptor/browser_controller.py`:

```python
self.browser = await self.playwright.chromium.launch(
    headless=False,  # Or True from BROWSER_HEADLESS env var
    args=[
        "--disable-blink-features=AutomationControlled",  # Hide automation
        "--disable-dev-shm-usage",                        # Fix shared memory
        "--no-sandbox",                                   # Linux/Docker
        "--remote-debugging-port=9222",                   # Optional debug
    ]
)

# Browser context (tab/session)
self.context = await self.browser.new_context(
    viewport={"width": 1280, "height": 720},
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) ..."
)

# Main page
self.page = await self.context.new_page()
await self.page.goto("https://www.goofish.com/", wait_until="networkidle")
```

### Browser Launches
- **One Chromium instance** with:
  - One browser context (session)
  - Multiple pages (tabs) monitored
  - CDP session per page for WebSocket interception

### Browser Configuration (.env)
```env
BROWSER_HEADLESS=false              # true = no UI, false = show window
BROWSER_USER_DATA_DIR=./browser_data  # Persistent profile (cookies, cache)
BROWSER_VIEWPORT_WIDTH=1280         # Window width
BROWSER_VIEWPORT_HEIGHT=720         # Window height
BROWSER_DEBUG_PORT=9222             # Optional: remote debugging (Chrome DevTools)
BROWSER_PROXY=                      # Optional: http://proxy:port
```

### Playwright Browser Detection
```python
# Injected JavaScript to hide webdriver detection
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});
```

This prevents Xianyu from detecting automated browser.

---

## 5. Config/Environment Variables Required

### Interceptor Transport Config (.env)
```env
# ============================================================
# REQUIRED FOR INTERCEPTOR
# ============================================================

# 1. Xianyu Account (Cookie-based auth)
COOKIES_STR=your_cookies_here
  # Get from: Chrome DevTools → Network → Messages → Cookies
  # Or: Xianyu website → Cookies header

# 2. AI API Backend (where to relay messages)
AGENT_SERVICE_URL=http://localhost:8000
  # Must run FastAPI backend on separate process/machine
  # Interceptor POSTs messages to: {AGENT_SERVICE_URL}/xianyu/inbound

# 3. Browser Configuration
BROWSER_HEADLESS=false
  # false = show window (can see WebSocket detection)
  # true = headless mode (faster, no display needed)

BROWSER_USER_DATA_DIR=./browser_data
  # Persistent browser profile (saves cookies between runs)

BROWSER_VIEWPORT_WIDTH=1280
BROWSER_VIEWPORT_HEIGHT=720

# 4. Image Handling
IMAGE_SAVE_DIR=./xianyu_images
  # Where to save downloaded images from chat

# 5. Logging
LOG_LEVEL=INFO
  # DEBUG, INFO, WARNING, ERROR
LOG_FORMAT=text
  # "text" (colored terminal) or "json" (structured)

# ============================================================
# OPTIONAL FOR INTERCEPTOR
# ============================================================

ENABLE_AI_REPLY=false
  # true = call AI for every message
  # false = relay to API, let API decide

AGENT_TIMEOUT=120.0
  # HTTP request timeout to API (seconds)

BROWSER_PROXY=
  # Leave empty or set to: http://proxy-host:port

BROWSER_DEBUG_PORT=9222
  # Optional: enable Chrome DevTools remote debugging

# ============================================================
# NOT NEEDED BY INTERCEPTOR (API-layer only)
# ============================================================

# API_KEY, MODEL_NAME, MYSQL_*, REDIS_*, DINGTALK_*, etc.
# These are used by the FastAPI backend in ai_kefu/api/main.py
```

### Config Load Order
1. Load `.env` file (via `python-dotenv`)
2. Override with environment variables
3. Use defaults from `xianyu_interceptor/config.py`

---

## 6. Runtime Files Needed

### Directory Structure on Fresh Mac

```
/path/to/XianyuAutoAgent/ai_kefu/
├── run_xianyu.py                          ✅ Entry point
├── requirements.txt                       ✅ Dependencies
├── .env                                   ✅ Secrets + config
├── .env.example                           📖 Reference
│
├── xianyu_interceptor/                    ✅ Core package
│   ├── __init__.py
│   ├── *.py                               (20 Python files)
│   └── upstream/ (git submodule)          ✅ For API calls
│
├── xianyu_provider/                       ✅ Provider abstraction
│   ├── __init__.py
│   ├── base.py
│   ├── goofish_provider.py
│   └── upstream/                          ✅ Git submodule
│
├── utils/                                 ✅ Shared utilities
│   ├── xianyu_utils.py                    (Cookie parsing)
│   └── ...
│
├── config/                                ⭕ For settings.seller_user_id
│   └── settings.py
│
├── prompts/                               ❌ Not needed
├── data/                                  🗂️ Runtime (created)
│   └── chat_history.db                    (Optional, API-layer)
│
├── logs/                                  🗂️ Runtime (auto-created)
│   └── xianyu_YYYY-MM-DD.log
│
├── xianyu_images/                         🗂️ Runtime (auto-created)
│   └── chat_id/user_id/*.jpg
│
└── browser_data/                          🗂️ Runtime (auto-created)
    └── Chromium profile (cookies, cache)
```

### Files Created at Runtime
- `logs/xianyu_YYYY-MM-DD.log` — Daily log file (JSONL format)
- `xianyu_images/[chat_id]/[user_id]/*.jpg` — Downloaded message images
- `browser_data/` — Chromium profile with cookies/cache
- `data/chat_history.db` — SQLite database (optional, API-layer)

### System Requirements
```
macOS:
  - Python 3.8+ (3.10+ recommended)
  - Node.js >= 18 (for JS execution in goofish_provider)
  - Disk space: ~500MB (Chromium + dependencies)
  - RAM: ~512MB minimum, ~2GB recommended
```

---

## 7. Output Files Written

### Logs
- **Location**: `ai_kefu/logs/`
- **Format**: JSONL (one JSON object per line for structured parsing)
- **Rotation**: Daily at midnight, 30-day retention, auto-zip
- **Files**: `xianyu_2026-04-23.log`, `xianyu_2026-04-24.log`, etc.

### Downloaded Images
- **Location**: `ai_kefu/xianyu_images/[chat_id]/[user_id]/`
- **Naming**: `YYYYMMDD_HHMMSS_[timestamp].[ext]`
- **Example**: `20260423_143022_1713878422000.jpg`

### Browser Data
- **Location**: `ai_kefu/browser_data/`
- **Contents**: Chromium profile (cookies, localStorage, cache)
- **Purpose**: Persist login session between runs

### Optional: Database
- **Location**: `ai_kefu/data/chat_history.db`
- **Type**: SQLite (if conversation_store used)
- **Purpose**: Store conversation history (API-layer feature)

### HTTP Relay Responses
- **Destination**: Posted to API at `{AGENT_SERVICE_URL}/xianyu/inbound`
- **Response**: JSON from API with optional reply text

---

## 8. Entry Point Command

### Run the Interceptor

```bash
#!/bin/bash

cd /path/to/XianyuAutoAgent/ai_kefu

# Install dependencies (first time only)
pip install -r requirements.txt

# Install Playwright browsers (first time only)
playwright install chromium

# Start interceptor (must have .env configured)
python run_xianyu.py
```

### What Happens
1. Load `.env` configuration
2. Setup logging (console + file)
3. Initialize `MessageHandler` relay
4. Launch Chromium browser → navigate to `https://www.goofish.com/`
5. Inject CDP WebSocket interceptor
6. Monitor for new pages/messages
7. Relay messages to AI API via HTTP POST
8. Send replies back through browser

### Expected Output
```
============================================================
闲鱼消息拦截器 (传输层中继)
============================================================
AI 自动回复: 禁用
AI API 地址: http://localhost:8000
============================================================
正在启动浏览器...
浏览器启动成功
============================================================
🔔 请在浏览器中点击进入消息中心（或聊天页面）
   WebSocket 连接将在新页面中建立
============================================================

✅ BrowserTransport 已创建并注入 message_handler
✅ 钉钉回复服务已注入 transport
拦截器已启动！
正在监听闲鱼消息...
按 Ctrl+C 停止
```

---

## 9. Shell Scripts

### start.sh (Legacy - calls main.py, not interceptor)
```bash
#!/bin/bash
# 启动闲鱼智能客服系统

# Checks:
# 1. Python 3 available
# 2. Dependencies installed (openai, websockets, loguru, dotenv, requests)
# 3. .env exists
# 4. Prompt files exist (classify_prompt.txt, price_prompt.txt, etc.)
# 5. data/ directory created

# Then runs: python3 main.py

# ❌ NOT used by interceptor (calls main.py, not run_xianyu.py)
```

### check_boot.sh (Diagnostics - checks environment)
```bash
#!/bin/bash
# AI KEFU Boot Diagnostic Check

# Checks:
# 1. Python version
# 2. Installed packages: pydantic-settings, gunicorn, redis, chromadb, 
#    pymysql, dingtalk-stream, fastapi, uvicorn, pydantic, openai, playwright
# 3. Services: Redis, MySQL
# 4. App imports: ai_kefu.api.main.app

# Output: Status (Ready or Missing packages)

# Usage: cd ai_kefu && bash check_boot.sh

# ⭕ Good for system diagnostics, but doesn't start interceptor
```

### To Start Interceptor (No script currently exists)

Create `start_interceptor.sh`:
```bash
#!/bin/bash

cd "$(dirname "$0")"

echo "🚀 Xianyu Interceptor Startup"
echo "===================================="

# Check Python
python3 --version || { echo "❌ Python 3 not found"; exit 1; }

# Check playwright installed
python3 -c "import playwright" 2>/dev/null || {
    echo "📦 Installing dependencies..."
    pip install -r requirements.txt
    python3 -m playwright install chromium
}

# Check .env
if [ ! -f ".env" ]; then
    echo "❌ .env not found. Copy from .env.example and configure."
    exit 1
fi

# Start interceptor
echo "▶️  Starting interceptor..."
python3 run_xianyu.py
```

---

## 10. Summary: Files Needed on Fresh Mac for Interceptor Only

### Absolute Minimum (Bootstrap)
```
✅ Required:
   /path/to/ai_kefu/run_xianyu.py
   /path/to/ai_kefu/.env (configured with COOKIES_STR, AGENT_SERVICE_URL)
   /path/to/ai_kefu/requirements.txt

✅ Package/Module:
   /path/to/ai_kefu/xianyu_interceptor/      (entire directory)
   /path/to/ai_kefu/xianyu_provider/         (for API integration)
   /path/to/ai_kefu/utils/                   (xianyu_utils.py)
   /path/to/ai_kefu/config/settings.py       (seller_user_id)

❌ NOT Needed:
   /path/to/ai_kefu/api/                     (FastAPI backend)
   /path/to/ai_kefu/prompts/                 (AI prompts)
   /path/to/ai_kefu/services/                (API services)
   /path/to/ai_kefu/models/                  (DB models)
```

### Created at Runtime
```
🗂️  Auto-created:
   logs/xianyu_YYYY-MM-DD.log
   xianyu_images/[chat_id]/[user_id]/*.jpg
   browser_data/                              (Chromium profile)
```

### Install Commands for Fresh Mac
```bash
# 1. Clone repo
git clone <repo> XianyuAutoAgent
cd XianyuAutoAgent/ai_kefu

# 2. Create Python venv
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Playwright browsers
python3 -m playwright install chromium

# 5. Configure .env
cp .env.example .env
# Edit .env:
#   - Set COOKIES_STR (from browser DevTools)
#   - Set AGENT_SERVICE_URL (e.g., http://localhost:8000)
#   - Set BROWSER_HEADLESS=false (to see window)

# 6. Start interceptor
python3 run_xianyu.py
```

---

## Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│ Xianyu Interceptor Process (run_xianyu.py)                             │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ BrowserController (Playwright)                                  │ │
│  │  - Launches Chromium browser                                    │ │
│  │  - Maintains browser context (tabs)                             │ │
│  │  - Handles cookies and profile data                             │ │
│  └─────────────────────────────────┬──────────────────────────────┘ │
│                                    │                                 │
│  ┌─────────────────────────────────▼──────────────────────────────┐ │
│  │ CDPInterceptor (Chrome DevTools Protocol)                      │ │
│  │  - Monitors WebSocket frames via Network domain                │ │
│  │  - Injects JavaScript interceptor                              │ │
│  │  - Routes messages to on_message callback                      │ │
│  │  - Sends replies via CDP send_message()                        │ │
│  └─────────────────────────────────┬──────────────────────────────┘ │
│                                    │                                 │
│  ┌─────────────────────────────────▼──────────────────────────────┐ │
│  │ Message Processing Pipeline                                    │ │
│  │  1. XianyuMessageCodec.decode_message()                         │ │
│  │  2. XianyuMessageCodec.extract_message_data()                   │ │
│  │  3. Convert to XianyuMessage model                              │ │
│  │  4. ImageHandler.handle_image_message() (if [图片])             │ │
│  │  5. Pass to MessageHandler.handle_message()                     │ │
│  └─────────────────────────────────┬──────────────────────────────┘ │
│                                    │                                 │
│  ┌─────────────────────────────────▼──────────────────────────────┐ │
│  │ MessageHandler (Thin Relay)                                    │ │
│  │  1. MessageDeduplicator.is_duplicate() - drop WS redeliveries  │ │
│  │  2. HTTP POST to AI API /xianyu/inbound                        │ │
│  │  3. If reply in response:                                       │ │
│  │      - BrowserTransport.send_message()                         │ │
│  │      - Encode reply via XianyuMessageCodec                      │ │
│  │      - Send via CDPInterceptor.send_message()                   │ │
│  └─────────────────────────────────┬──────────────────────────────┘ │
│                                    │                                 │
│  ┌─────────────────────────────────▼──────────────────────────────┐ │
│  │ HTTP Client (httpx)                                            │ │
│  │  - POST messages to: {AGENT_SERVICE_URL}/xianyu/inbound         │ │
│  │  - Receive replies: {"reply": "...", ...}                       │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
                                  │
                                  │ HTTP
                                  ▼
                ┌─────────────────────────────────┐
                │ FastAPI Backend (ai_kefu/api/)  │
                │ (Separate process)              │
                │  POST /xianyu/inbound           │
                │   - Conversation logic          │
                │   - AI agent (calls Qwen LLM)   │
                │   - Manual mode handling        │
                │   - Return reply text           │
                └─────────────────────────────────┘
```

---

## Quick Ref: Environment Variables

| Var | Required | Example | Purpose |
|-----|----------|---------|---------|
| `COOKIES_STR` | YES | (long cookie string) | Xianyu auth |
| `AGENT_SERVICE_URL` | YES | `http://localhost:8000` | AI API endpoint |
| `BROWSER_HEADLESS` | NO | `false` | Show/hide window |
| `BROWSER_USER_DATA_DIR` | NO | `./browser_data` | Browser profile |
| `BROWSER_VIEWPORT_WIDTH` | NO | `1280` | Window width |
| `BROWSER_VIEWPORT_HEIGHT` | NO | `720` | Window height |
| `IMAGE_SAVE_DIR` | NO | `./xianyu_images` | Downloaded images |
| `LOG_LEVEL` | NO | `INFO` | Log verbosity |
| `LOG_FORMAT` | NO | `text` | `text` or `json` |
| `ENABLE_AI_REPLY` | NO | `false` | Debug mode flag |

---

## Key Dependencies

### Core (Interceptor will not run without)
- `playwright>=1.40.0` — Browser automation
- `loguru==0.7.3` — Logging
- `pydantic==2.5.0` — Data validation
- `pydantic-settings==2.1.0` — Config loading
- `python-dotenv==1.0.1` — .env parsing
- `httpx>=0.27.0` — Async HTTP client

### Extended (Optional but recommended)
- `aiohttp>=3.9.0` — Image downloading
- `websockets==13.1` — WebSocket support
- `PyExecJS>=1.5.1` — JS execution (for API calls)
- `blackboxprotobuf>=1.0.1` — Message deserialization

---

