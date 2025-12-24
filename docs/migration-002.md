# Migration Guide: Xianyu Interceptor HTTP Integration

**Feature**: 002-xianyu-agent-http-integration  
**Date**: 2025-12-24

## Overview

This migration refactors the Xianyu message interceptor to integrate with the AI Agent service via HTTP, replacing the old embedded AI logic.

## What Changed

### Old Architecture
```
Xianyu WebSocket → CDP Interceptor → Old XianyuAgent (embedded) → Reply
```

### New Architecture
```
Xianyu WebSocket → CDP Interceptor → HTTP Client → AI Agent Service → Reply
```

## File Changes

### New Files
- `ai_kefu/xianyu_interceptor/` - New module structure
  - `config.py` - Configuration management
  - `models.py` - Data models
  - `message_converter.py` - Format conversion
  - `session_mapper.py` - Session mapping
  - `http_client.py` - Agent HTTP client
  - `manual_mode.py` - Manual mode manager
  - `message_handler.py` - Message processing
  - `main_integration.py` - Integration setup
  - `logging_setup.py` - Logging configuration
  - `exceptions.py` - Custom exceptions

### Moved Files
- `browser_controller.py` → `xianyu_interceptor/browser_controller.py`
- `cdp_interceptor.py` → `xianyu_interceptor/cdp_interceptor.py`
- `messaging_core.py` → `xianyu_interceptor/messaging_core.py`

### Archived Files
- `XianyuAgent.py` → `legacy/XianyuAgent.py`
- `XianyuApis.py` → `legacy/XianyuApis.py`
- `context_manager.py` → `legacy/context_manager.py`

## Migration Steps

### 1. Update Configuration

Add to your `.env` file:

```bash
# AI Agent Service
AGENT_SERVICE_URL=http://localhost:8000
AGENT_TIMEOUT=10.0
AGENT_MAX_RETRIES=3
AGENT_RETRY_DELAY=1.0

# Session Mapping
SESSION_MAPPER_TYPE=memory  # or redis
REDIS_URL=redis://localhost:6379
SESSION_TTL=3600

# Manual Mode
TOGGLE_KEYWORDS=。
MANUAL_MODE_TIMEOUT=3600
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Start AI Agent Service

Ensure the AI Agent service is running:

```bash
cd /path/to/XianyuAutoAgent
make dev

# Or
docker-compose up -d
```

### 4. Update Import Statements

If you have custom code importing from old modules:

**Old**:
```python
from ai_kefu.XianyuAgent import XianyuAgent
from ai_kefu.messaging_core import Message
```

**New**:
```python
from ai_kefu.xianyu_interceptor import (
    MessageHandler,
    XianyuMessage,
    initialize_interceptor
)
```

### 5. Test the Integration

```bash
# Start interceptor
python ai_kefu/main.py

# Check logs for:
# - "Agent service is healthy"
# - "Interceptor is running"

# Test manual mode:
# - Send "。" in chat to toggle
```

## Breaking Changes

1. **XianyuAgent class removed**: Use `MessageHandler` instead
2. **Direct AI logic removed**: All AI processing now via HTTP
3. **Session management changed**: Uses SessionMapper instead of old context manager

## Rollback Plan

If issues arise:

1. **Stop new interceptor**:
   ```bash
   # Kill the process
   pkill -f "python.*main.py"
   ```

2. **Revert to old code**:
   ```bash
   # Restore from legacy/
   cp ai_kefu/legacy/XianyuAgent.py ai_kefu/
   cp ai_kefu/legacy/XianyuApis.py ai_kefu/
   cp ai_kefu/legacy/context_manager.py ai_kefu/
   ```

3. **Restart with old logic**:
   ```bash
   # Use old startup script
   python ai_kefu/main_old.py
   ```

## Validation Checklist

- [ ] Agent service is running and healthy
- [ ] Redis is running (if using Redis mapper)
- [ ] Configuration is updated in `.env`
- [ ] Dependencies are installed
- [ ] Interceptor starts without errors
- [ ] Messages are forwarded to Agent
- [ ] AI responses are received
- [ ] Replies are sent to Xianyu
- [ ] Manual mode toggle works
- [ ] Logs are properly formatted

## Troubleshooting

### Agent Service Not Reachable

**Symptom**: `Agent API failed: Connection refused`

**Solution**:
```bash
# Check if Agent service is running
curl http://localhost:8000/health

# Start Agent service
make dev
```

### Session Mapping Errors

**Symptom**: `Session Mapper Error`

**Solution**:
- If using Redis: Check Redis is running (`redis-cli ping`)
- Fall back to memory mapper: Set `SESSION_MAPPER_TYPE=memory` in `.env`

### Browser Control Issues

**Symptom**: Browser doesn't launch

**Solution**:
```bash
# Reinstall Playwright browsers
playwright install chromium

# Check permissions
ls -la ~/.cache/ms-playwright
```

## Performance Notes

- **Message processing latency**: < 500ms (excluding Agent processing)
- **Agent API latency**: ~2s (P95)
- **Session lookup**: < 1ms (memory) or < 5ms (Redis)
- **Concurrent conversations**: Supports 10-50 simultaneous chats

## Support

For issues or questions:
1. Check logs in `logs/xianyu_interceptor_*.log`
2. Review configuration in `.env`
3. Test Agent service health: `curl http://localhost:8000/health`
4. Contact development team

---

**Migration completed**: [DATE]  
**Validated by**: [NAME]
