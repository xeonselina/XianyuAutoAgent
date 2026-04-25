# Xianyu Interceptor - Quick Start

## TL;DR: Run the Interceptor on Fresh Mac

```bash
# 1. Clone and enter directory
cd /path/to/XianyuAutoAgent/ai_kefu

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
python3 -m playwright install chromium

# 4. Configure .env
cp .env.example .env
# Edit .env and set:
#   COOKIES_STR=<your_xianyu_cookies>
#   AGENT_SERVICE_URL=http://localhost:8000
#   BROWSER_HEADLESS=false

# 5. Start interceptor
python3 run_xianyu.py

# Expected output:
# ============================================================
# 闲鱼消息拦截器 (传输层中继)
# ============================================================
# AI 自动回复: 禁用
# AI API 地址: http://localhost:8000
# ============================================================
```

---

## What Gets Started

| Component | Status | Purpose |
|-----------|--------|---------|
| **Xianyu Interceptor** | ✅ Started | Watches for WebSocket messages via browser |
| **Chromium Browser** | ✅ Started | Displays Xianyu.com, captures messages |
| **FastAPI Backend** | ⚠️ SEPARATE | Must run `python -m ai_kefu.api.main` in another terminal |
| **MySQL/Redis** | ⚠️ OPTIONAL | Only needed by API (conversation store, sessions) |

---

## Required Config (.env essentials)

```env
COOKIES_STR=<your_long_cookie_string>
AGENT_SERVICE_URL=http://localhost:8000
BROWSER_HEADLESS=false
```

**How to get COOKIES_STR:**
1. Open browser → Xianyu.com
2. DevTools (F12) → Application → Cookies
3. Copy all cookies as header string

---

## File Structure (Interceptor Only)

```
ai_kefu/
├── run_xianyu.py                 ← Entry point
├── .env                          ← Config (create from .env.example)
├── requirements.txt              ← Dependencies
├── xianyu_interceptor/           ← Core (20 Python files)
├── xianyu_provider/              ← Provider abstraction
├── utils/xianyu_utils.py         ← Utilities
└── config/settings.py            ← Settings (seller_user_id)
```

**Runtime Output:**
- `logs/xianyu_*.log` — Daily JSON logs
- `xianyu_images/` — Downloaded images from messages
- `browser_data/` — Browser profile (persistent)

---

## Key Dependencies

```
playwright>=1.40.0    ← Browser automation (Chromium)
loguru==0.7.3         ← Logging
pydantic==2.5.0       ← Data validation
python-dotenv==1.0.1  ← Load .env
httpx>=0.27.0         ← HTTP client (POST to API)
aiohttp>=3.9.0        ← Image download
```

All in `requirements.txt` — just install once: `pip install -r requirements.txt`

---

## Browser Details

- **Type:** Chromium (via Playwright)
- **Instances:** 1 main browser
- **Tabs:** Monitor all pages (existing + new)
- **Detection:** Hidden (webdriver flag disabled)
- **WebSocket:** Captured via Chrome DevTools Protocol (CDP)

---

## How Messages Flow

```
Xianyu WebSocket
    ↓
CDP Interceptor (browser)
    ↓
Message Handler (decode + dedup)
    ↓
HTTP POST → /xianyu/inbound (FastAPI backend)
    ↓
API Response (optional reply)
    ↓
BrowserTransport (send reply via CDP)
    ↓
Xianyu WebSocket (send message)
```

**No business logic in interceptor** — pure relay to API.

---

## Environment Variables (Essential)

| Var | Example | Need? |
|-----|---------|-------|
| `COOKIES_STR` | `_bl_uid=xxx; bid=yyy; ...` | YES |
| `AGENT_SERVICE_URL` | `http://localhost:8000` | YES |
| `BROWSER_HEADLESS` | `false` | NO (default: false) |
| `BROWSER_USER_DATA_DIR` | `./browser_data` | NO |
| `LOG_LEVEL` | `INFO` | NO |

**Others are API-layer only** (MYSQL_*, REDIS_*, etc.)

---

## Troubleshooting

### "playwright not found"
```bash
pip install -r requirements.txt
python3 -m playwright install chromium
```

### "No WebSocket detected"
- Browser window must be open
- Click into Xianyu message page
- Wait 5-10 seconds for detection
- Check logs: `tail -f logs/xianyu_*.log`

### ".env not found"
```bash
cp .env.example .env
# Edit COOKIES_STR and AGENT_SERVICE_URL
```

### "Connection refused" (API)
- Ensure FastAPI backend running: `python -m ai_kefu.api.main` (separate terminal)
- Check `AGENT_SERVICE_URL` in .env

---

## File Size / Setup Time

- **Download:** ~200MB (Chromium binary)
- **Install:** ~2 minutes (first time)
- **Setup:** ~1 minute (configure .env)
- **Runtime:** ~512MB RAM, ~50MB disk per day (logs)

---

## Next Steps

1. ✅ Install dependencies + Playwright browsers
2. ✅ Configure `.env` with cookies + API URL
3. ✅ Start interceptor: `python3 run_xianyu.py`
4. 🌐 Open browser → Xianyu message page
5. 📡 Wait for WebSocket detection (~10 seconds)
6. 💬 Send test message from Xianyu
7. 📊 Check logs: `tail -f logs/xianyu_*.log`

---

## Support

- **Logs:** `ai_kefu/logs/xianyu_YYYY-MM-DD.log`
- **Debug:** Set `LOG_LEVEL=DEBUG` in `.env`
- **Analysis:** See `XIANYU_INTERCEPTOR_ANALYSIS.md`

