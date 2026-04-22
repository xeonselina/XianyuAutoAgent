# AI KEFU Boot Failure - Quick Fix Guide

## TL;DR - The Problem

Your `ai_kefu` FastAPI app crashes on gunicorn startup with **"Worker failed to boot" (exit code 3)** because **6 required Python packages are not installed**.

## The Root Cause

```
gunicorn ai_kefu.api.main:app
  ↓
Tries to import: from ai_kefu.config.settings import settings
  ↓
config/settings.py tries: from pydantic_settings import BaseSettings
  ↓
❌ ModuleNotFoundError: No module named 'pydantic_settings'
```

## What's Missing

| Package | Why | Install |
|---------|-----|---------|
| `pydantic-settings` | Loads `.env` config | `pip install pydantic-settings` |
| `gunicorn` | WSGI server launcher | `pip install gunicorn` |
| `redis` | Session storage | `pip install redis` |
| `pymysql` | MySQL connections | `pip install pymysql` |
| `chromadb` | Vector database | `pip install chromadb` |
| `dingtalk-stream` | DingTalk integration | `pip install dingtalk-stream` |

## The Fix (Choose One)

### Option A: Install from requirements.txt (Recommended)
```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu
pip install -r requirements.txt
```

### Option B: Install individual packages
```bash
pip install pydantic-settings gunicorn redis pymysql chromadb dingtalk-stream
```

## Verify the Fix

```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent

# Test 1: Can Python load the app?
python3 -c "from ai_kefu.api.main import app; print('✓ App loaded')"

# Test 2: Run diagnostic check
cd ai_kefu && bash check_boot.sh
```

## Then Start the App

```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu
make run-api
```

## If It Still Fails

1. **Check for missing services** (if you get past import):
   - Redis: `redis-cli ping` (should return PONG)
   - MySQL: `mysql -u root -p -e "SELECT 1"` (should connect)

2. **Check `.env` file** for required variables:
   - `API_KEY` (Alibaba Qwen key)
   - `RENTAL_API_BASE_URL`
   - `RENTAL_FIND_SLOT_ENDPOINT`

3. **See full report**: `cat BOOT_FAILURE_DEBUG_REPORT.md`

---

**Status:** This is a **dependency installation issue**, not a code bug. Once you run `pip install -r requirements.txt`, it should work.
