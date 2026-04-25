# Deploy Xianyu Interceptor to Fresh Mac - Complete Checklist

## Pre-Flight Check

- [ ] Mac with macOS 10.15+ (10.14+ for Python 3.8+)
- [ ] Git installed: `git --version`
- [ ] Python 3.8+: `python3 --version` (3.10+ recommended)
- [ ] Node.js 18+: `node --version` (needed for JS execution in provider)

---

## Step 1: Clone Repository

```bash
git clone https://github.com/<org>/XianyuAutoAgent.git ~/XianyuAutoAgent
cd ~/XianyuAutoAgent/ai_kefu
```

**Verification:**
```bash
ls -la run_xianyu.py .env.example requirements.txt
# Should show 3 files
```

---

## Step 2: Create Python Virtual Environment

```bash
# Create venv
python3 -m venv .venv

# Activate (macOS/Linux)
source .venv/bin/activate

# Verify (should show .venv in prompt)
which python3
# Output: /Users/jimmypan/XianyuAutoAgent/ai_kefu/.venv/bin/python3
```

**Verification:**
```bash
python3 --version   # Should be 3.8+
pip --version        # Should be recent
```

---

## Step 3: Install Python Dependencies

```bash
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

**This installs:**
- `playwright>=1.40.0` — Browser automation
- `loguru==0.7.3` — Logging
- `pydantic==2.5.0` — Data validation
- `python-dotenv==1.0.1` — .env loading
- `httpx>=0.27.0` — Async HTTP client
- `aiohttp>=3.9.0` — Image download
- + 20+ other packages

**Expected time:** 2-3 minutes

**Verification:**
```bash
pip list | grep -E "playwright|loguru|pydantic|httpx"
# Should show all 4 packages
```

---

## Step 4: Install Playwright Browsers

```bash
python3 -m playwright install chromium
```

**What it does:**
- Downloads Chromium binary (~200MB)
- Installs to `~/.cache/ms-playwright/chromium-*/`
- Creates `~/.cache/ms-playwright/chromium-*/chrome-linux/` (or similar)

**Expected time:** 30 seconds - 2 minutes (depends on network)

**Verification:**
```bash
python3 -c "from playwright.async_api import async_playwright; print('✅ Playwright OK')"
# Should print: ✅ Playwright OK
```

---

## Step 5: Get Xianyu Cookies

### Option A: From Browser DevTools (Recommended)

1. Open any browser (Chrome, Safari, etc.)
2. Go to https://www.xianyu.taobao.com or https://www.goofish.com
3. Log in to your account
4. Open DevTools: `Cmd+Option+I` (macOS) or `F12`
5. Go to **Application** → **Cookies** (or **Storage**)
6. Copy all cookies (select all, Cmd+C)
7. Or export as "Copy as cURL" and extract the cookie header

**Result:** Long string like:
```
_bl_uid=abc123...; bid=xyz789...; unb=user_id...; ...
```

### Option B: From Network Tab

1. Open DevTools → **Network** tab
2. Send a message on Xianyu
3. Look for `wss://` WebSocket request
4. View **Request Headers** → **Cookie** header

---

## Step 6: Configure .env File

```bash
# Create .env from template
cp .env.example .env

# Edit .env (use nano, vim, or IDE)
nano .env
```

**REQUIRED settings:**

```env
# Your Xianyu cookies (from Step 5)
COOKIES_STR=your_entire_cookie_string_here

# AI API backend URL
# For local dev: http://localhost:8000
# For remote: http://api-server.com:8000
AGENT_SERVICE_URL=http://localhost:8000

# Show browser window (false = headless)
BROWSER_HEADLESS=false

# Log level
LOG_LEVEL=INFO
```

**OPTIONAL settings:**

```env
# Browser profile directory (for persistent cookies)
BROWSER_USER_DATA_DIR=./browser_data

# Window size
BROWSER_VIEWPORT_WIDTH=1280
BROWSER_VIEWPORT_HEIGHT=720

# Image save directory
IMAGE_SAVE_DIR=./xianyu_images

# Log format: "text" (colored) or "json" (structured)
LOG_FORMAT=text
```

**DO NOT EDIT these** (API-layer only):
```env
# These are for the FastAPI backend, not the interceptor:
# MYSQL_HOST, MYSQL_PASSWORD, REDIS_URL, DINGTALK_*, etc.
```

**Verification:**
```bash
# Check syntax
python3 -c "from dotenv import load_dotenv; load_dotenv(); print('✅ .env OK')"

# Check key variables loaded
python3 -c "from xianyu_interceptor.config import config; print(f'API: {config.agent_service_url}'); print(f'Headless: {config.browser_headless}')"
```

---

## Step 7: Verify System Configuration

### Option A: Quick Check

```bash
# 1. Check Python
python3 --version

# 2. Check packages
python3 -c "import playwright, loguru, pydantic, httpx; print('✅ All packages OK')"

# 3. Check Playwright
python3 -m playwright --version

# 4. Check .env
python3 -c "import os; from dotenv import load_dotenv; load_dotenv(); assert os.getenv('COOKIES_STR'), 'COOKIES_STR missing'; assert os.getenv('AGENT_SERVICE_URL'), 'AGENT_SERVICE_URL missing'; print('✅ .env configured')"
```

### Option B: Full Diagnostic Script

```bash
bash check_boot.sh
```

**Expected output:**
```
==========================================
AI KEFU Boot Diagnostic Check
==========================================

1. Python Environment
   Python: Python 3.10.x
   Executable: /Users/jimmypan/XianyuAutoAgent/ai_kefu/.venv/bin/python3

2. Required Packages
   ✓ playwright
   ✓ loguru
   ✓ pydantic
   ✓ httpx
   ...

3. Services
   ⚠ Redis (installed but not responding)
   ⚠ MySQL (installed but not responding)

4. App Import Test
   ✓ App imports successfully
```

---

## Step 8: Start Xianyu Interceptor

```bash
# Make sure venv is activated
source .venv/bin/activate

# Start interceptor
python3 run_xianyu.py
```

**Expected output (first 30 seconds):**

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
✅ 钉钉回复服务已注入 transport  (warning OK if fails)
拦截器已启动！
正在监听闲鱼消息...
按 Ctrl+C 停止
```

**If you see this, the interceptor is running! ✅**

---

## Step 9: Verify WebSocket Detection

1. Browser window should open automatically
2. Navigate to Xianyu message page
3. Click into a chat conversation
4. Look at interceptor console for:

```
📄 设置页面监控: https://www.goofish.com/...
✅ 在页面中检测到 WebSocket: https://...
```

**If you see this, WebSocket is detected! ✅**

---

## Step 10: Test with Sample Message

1. Send a test message from your Xianyu account (or use another account)
2. Watch the logs:

```bash
# In another terminal, watch logs
tail -f logs/xianyu_*.log
```

**Expected log output:**
```
[relay] chat_id=..., user_id=..., is_self=False, content='测试消息'
[relay] POSTing to http://localhost:8000/xianyu/inbound: ...
[relay] API response: status=200, chat_id=...
```

**If you see this, messages are relaying! ✅**

---

## Step 11: Set Up Log Monitoring (Optional)

```bash
# Watch logs in real-time
tail -f logs/xianyu_*.log

# Or with color/filtering (if jq installed)
tail -f logs/xianyu_*.log | jq .

# Or search for specific patterns
tail -f logs/xianyu_*.log | grep "relay"
```

---

## Step 12: Start API Backend (if needed)

**In a NEW terminal:**

```bash
# Navigate to ai_kefu directory
cd ~/XianyuAutoAgent/ai_kefu

# Activate venv
source .venv/bin/activate

# Start API backend
python3 -m ai_kefu.api.main
# Or: python3 api/main.py

# Should show:
# Uvicorn running on http://0.0.0.0:8000
```

**Now the full flow works:**
```
Interceptor → HTTP POST → API → LLM Response → Browser Send
```

---

## Troubleshooting Checklist

### ❌ "ModuleNotFoundError: No module named 'playwright'"

```bash
# Solution 1: Install playwright
pip install playwright>=1.40.0

# Solution 2: Verify venv is activated
which python3
# Should show: /Users/.../XianyuAutoAgent/ai_kefu/.venv/bin/python3
# NOT: /usr/bin/python3

# Solution 3: Reinstall from requirements.txt
pip install -r requirements.txt
```

### ❌ "playwright command not found"

```bash
# Solution: Install playwright browsers
python3 -m playwright install chromium
```

### ❌ ".env not found"

```bash
# Solution: Create from template
cp .env.example .env
# Then edit with your cookies and API URL
```

### ❌ "No WebSocket detected"

1. Check browser window is open
2. Click into Xianyu message conversation
3. Wait 5-10 seconds
4. Check logs: `tail -f logs/xianyu_*.log`
5. If "WebSocket created" shows, it's working

### ❌ "Connection refused" on `/xianyu/inbound`

```bash
# Solution 1: Start API backend in another terminal
# Terminal 2:
cd ~/XianyuAutoAgent/ai_kefu
source .venv/bin/activate
python3 -m ai_kefu.api.main

# Solution 2: Check AGENT_SERVICE_URL in .env
grep AGENT_SERVICE_URL .env
# Should show: http://localhost:8000 (or your API address)

# Solution 3: Verify API is running
curl http://localhost:8000/health
# Should return 200
```

### ❌ "BROWSER_HEADLESS" config ignored

Env var precedence (highest to lowest):
1. Environment variables (`export BROWSER_HEADLESS=true`)
2. `.env` file values
3. Defaults in `xianyu_interceptor/config.py`

```bash
# If .env not working, try shell env var:
BROWSER_HEADLESS=false python3 run_xianyu.py
```

---

## Cleanup / Uninstall

If you need to remove the venv and start over:

```bash
# Deactivate venv
deactivate

# Remove venv directory
rm -rf .venv

# Remove runtime directories (optional)
rm -rf browser_data xianyu_images logs data

# Then start from Step 2 (create new venv)
```

---

## Summary

| Step | Action | Time | Critical |
|------|--------|------|----------|
| 1 | Clone repo | <1m | YES |
| 2 | Create venv | <1m | YES |
| 3 | Install pip packages | 2-3m | YES |
| 4 | Install Playwright browsers | 1-2m | YES |
| 5 | Get Xianyu cookies | 5m | YES |
| 6 | Configure .env | 2m | YES |
| 7 | Verify config | <1m | YES |
| 8 | Start interceptor | <1m | YES |
| 9 | Verify WebSocket | 5m | NO (troubleshoot) |
| 10 | Test message relay | 5m | NO (troubleshoot) |
| 11 | Monitor logs | - | NO (optional) |
| 12 | Start API backend | 2m | NO (if separate) |

**Total Setup Time:** ~15-20 minutes (first time)

---

## File Sizes

```
Repository:          ~50MB  (code + docs)
Playwright Install:  ~200MB (Chromium binary)
Python venv:         ~500MB (dependencies)
Runtime per day:     ~50MB  (logs only)

Total disk needed:   ~800MB minimum
```

---

## Security Notes

1. **COOKIES_STR**: Do NOT commit to git
   - Use `.gitignore` to exclude `.env`
   - Or use environment variables

2. **Browser Profile**: Do NOT share `browser_data/`
   - Contains login cookies
   - Persists between runs

3. **Logs**: May contain sensitive info
   - Store securely
   - Rotate daily (automatic)

---

## Support Resources

- **Full Analysis:** `XIANYU_INTERCEPTOR_ANALYSIS.md`
- **Quick Reference:** `INTERCEPTOR_QUICK_START.md`
- **Logs:** `ai_kefu/logs/xianyu_YYYY-MM-DD.log`
- **Debug:** Set `LOG_LEVEL=DEBUG` in `.env`

---

## Success Criteria

✅ **Installation complete when:**
- [ ] Python venv created and activated
- [ ] All pip packages installed
- [ ] Playwright browsers installed
- [ ] .env configured with COOKIES_STR and AGENT_SERVICE_URL
- [ ] `python3 run_xianyu.py` starts without errors
- [ ] Browser window opens to goofish.com
- [ ] Logs show "WebSocket 连接已建立"

✅ **Full system complete when:**
- [ ] Interceptor running (Step 8)
- [ ] API backend running (Step 12)
- [ ] Message sent to Xianyu relays through API
- [ ] Logs show successful HTTP POST to `/xianyu/inbound`

---

