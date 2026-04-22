# Logging Architecture Overview

## System Logging Structure

The AI Kefu system uses **TWO independent logging systems** designed for different purposes:

### 1. AI Agent Logging (utils/logging.py)
- **Purpose:** Application-level event tracking
- **Library:** Python `logging` module
- **Output:** Console (stdout)
- **Format:** JSON (structured) or Text (development)
- **Logger Name:** `"ai_kefu"`

### 2. Xianyu Interceptor Logging (xianyu_interceptor/logging_setup.py)
- **Purpose:** Transport layer diagnostics
- **Library:** `loguru` (enhanced logging)
- **Output:** Console + File (auto-rotated daily)
- **Format:** Colored text (console) or JSON (production)
- **Log Files:** `logs/xianyu_interceptor_YYYY-MM-DD.log`

---

## Message Flow & Logging Points

```
┌─ XIANYU BROWSER (INTERCEPTOR) ─────────────────────────────┐
│  [Logger: loguru, Level: INFO/DEBUG, Output: console + file]  │
│                                                                │
│  ✓ Browser startup/shutdown                                   │
│  ✓ Page monitoring setup                                      │
│  ✓ CDP WebSocket interception                                 │
│  ✓ Message decoding (protobuf)                               │
│  ✓ History message parsing                                   │
│  ✓ Image download/storage                                    │
│  ✓ WebSocket connection status                               │
│                                                                │
│  Example:                                                      │
│  2026-04-13 14:31:16.455 | INFO | __main__:main | 卖家      │
│  user_id: 2200687521877                                       │
└────────────────────┬────────────────────────────────────────┘
                     │ POST /xianyu/inbound
                     ▼
┌─ API LAYER (BUSINESS LOGIC) ───────────────────────────────┐
│  [Logger: ai_kefu, Level: INFO, Output: console (JSON)]       │
│                                                                │
│  ✓ Message direction detection                               │
│  ✓ Ignore pattern filtering                                  │
│  ✓ Manual mode status                                        │
│  ✓ AI suppression detection                                  │
│  ✓ Order-placed event handling                               │
│  ✓ Agent invocation                                          │
│                                                                │
│  Logged Fields:                                                │
│  - session_id                                                 │
│  - chat_id                                                    │
│  - user_id                                                    │
│  - message_type                                               │
│  - response_length                                            │
└────────────────────┬────────────────────────────────────────┘
                     │ AgentExecutor.run()
                     ▼
┌─ AI AGENT LAYER ──────────────────────────────────────────┐
│  [Logger: ai_kefu, Level: INFO, Output: console (JSON)]       │
│                                                                │
│  ✓ Turn start/end                                            │
│  ✓ Tool detection                                            │
│  ✓ Tool call start/end                                       │
│  ✓ LLM API calls                                             │
│  ✓ Loop detection                                            │
│  ✓ Context summarization                                     │
│  ✓ Agent completion                                          │
│                                                                │
│  Helper Functions:                                             │
│  - log_turn_start(session_id, turn, query)                   │
│  - log_turn_end(session_id, turn, duration, success)         │
│  - log_tool_call(session_id, tool, tool_id, args)            │
│  - log_tool_result(session_id, tool, tool_id, success, dur)  │
│  - log_agent_complete(session_id, status, turns, duration)   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
        ┌────────────────────────┐
        │ MySQL (conversations)  │
        │ MySQL (xianyu_orders)  │
        └────────────────────────┘
```

---

## Configuration

### Environment Variables

```bash
# AI Kefu Logging
LOG_LEVEL=INFO                    # DEBUG, INFO, WARNING, ERROR
LOG_FORMAT=json                   # json or text

# Interceptor is configured via xianyu_interceptor/config.py
# But mirrors these settings from ai_kefu/config/settings.py:
# ENABLE_AI_REPLY=false           # Debug mode affects logging
```

### Settings Files

**ai_kefu/config/settings.py:**
```python
log_level: str = "INFO"
log_format: str = "json"  # or "text"
```

**xianyu_interceptor/config.py:**
```python
log_level: str = "INFO"
log_format: str = "text"  # or "json"
```

### Startup Logging

**api/main.py:**
```python
setup_logging()  # Initialize ai_kefu logger
```

**run_xianyu.py:**
```python
setup_logging()  # Initialize loguru logger (interceptor)
```

---

## Log Formats

### JSON Format (Production)

**AI Agent Logs:**
```json
{
  "timestamp": "2026-04-13T14:31:16.455Z",
  "level": "INFO",
  "logger": "ai_kefu",
  "message": "Turn 0 started",
  "session_id": "sess_abc123",
  "event_type": "turn_start",
  "turn_counter": 0,
  "query_length": 28
}
```

**With Exception:**
```json
{
  "timestamp": "2026-04-13T14:31:20.123Z",
  "level": "ERROR",
  "logger": "ai_kefu",
  "message": "Tool call failed",
  "session_id": "sess_abc123",
  "event_type": "tool_call_end",
  "tool_name": "knowledge_search",
  "success": false,
  "duration_ms": 1500,
  "exception": "Traceback (most recent call last):\n  ..."
}
```

### Text Format (Development)

**AI Agent Logs:**
```
2026-04-13 14:31:16 - ai_kefu - INFO - [sess_abc123] Turn 0 started
```

**Interceptor Logs:**
```
2026-04-13 14:31:16.455 | INFO     | __main__:main:153 | 卖家 user_id: 2200687521877
2026-04-13 14:31:17.587 | SUCCESS  | __main__:main:456 | 拦截器已启动！
```

---

## Structured Fields in Logs

### Standard JSON Fields
- `timestamp` - ISO 8601 with timezone
- `level` - Log level name
- `logger` - Logger name
- `message` - Log message

### Custom Fields (when provided)
- `session_id` - Agent session ID
- `event_type` - Event type (turn_start, tool_call_end, etc.)
- `duration_ms` - Operation duration
- `tool_name` - Tool being called
- `user_id` - Xianyu user ID
- `chat_id` - Xianyu chat ID
- `success` - Boolean operation status
- `tool_call_id` - Unique tool invocation ID
- `tool_args` - Tool arguments (stringified)
- `total_turns` - Total agent turns executed
- `status` - Completion status

---

## Log Levels

### DEBUG
- Detailed diagnostic information
- LLM API requests/responses
- Tool execution details
- WebSocket frame analysis

### INFO
- High-level events (turn start/end)
- Tool calls initiated/completed
- Agent completion
- Business logic decisions (manual mode, ignore patterns)
- Configuration loaded

### WARNING
- Configuration missing
- Fallback behavior triggered
- Non-critical failures recovered
- Unusual conditions

### ERROR
- Critical failures
- Exceptions during execution
- Tool execution failures
- API call failures (logged but handled)

---

## File Rotation & Retention

### Interceptor Log Files

**Location:** `/logs/`

**File Naming:** `xianyu_interceptor_YYYY-MM-DD.log`

**Rotation Policy:**
- **Trigger:** Daily at 00:00 UTC
- **Compression:** Automatically zipped to `.log.zip`
- **Retention:** 7 days (oldest files deleted)
- **Size per day:** ~1-8 MB (depending on activity)

**Example:**
```
logs/
├── xianyu_interceptor_2026-04-07.log.zip  (archived)
├── xianyu_interceptor_2026-04-08.log.zip  (archived)
├── xianyu_interceptor_2026-04-09.log.zip  (archived)
├── xianyu_interceptor_2026-04-10.log      (current, rolling)
└── xianyu_interceptor_2026-04-13.log      (latest)
```

### API Agent Logs

**Output:** Console (stdout)
- No file rotation
- Output captured by container/systemd
- Can be redirected to file via Docker/systemd config

---

## Event Types

The system tracks these event types via `LoggingHook`:

### Agent Events
- `turn_start` - Beginning of a conversation turn
- `turn_end` - End of a conversation turn
- `agent_complete` - Full agent execution completed
- `agent_error` - Unhandled error in agent

### Tool Events
- `tool_call_start` - Tool invocation begins
- `tool_call_end` - Tool execution completes

### Human Workflow
- `human_request_created` - Human escalation requested
- `human_response_received` - Human provided response

---

## Logging Best Practices

### What to Log
✓ Business logic decisions (manual mode, AI suppression)
✓ Performance metrics (duration, turn count, token count)
✓ State transitions (mode changes, agent completion)
✓ Tool calls and results
✓ Error conditions with context

### What NOT to Log
✗ User messages (sensitive data)
✗ Xianyu cookies/credentials
✗ Full LLM responses (privacy)
✗ Medical/personal information

### Current Data Masking
The system applies filtering via `hooks/sensitive_filter.py` to:
- Remove usernames from logs
- Mask sensitive identifiers
- Truncate very long messages

---

## Integration Points

### Receiving Logs
1. **Console Output:** Docker logs, systemd journal
2. **File Output:** `/logs/` directory (interceptor only)
3. **Database:** MySQL `conversations` table
4. **Metrics:** Via `log_*` helper functions

### Consumers
- Developers (debugging)
- Operations (monitoring)
- Analytics (performance tracking)
- Security (audit trail)

---

## Future Logging Enhancements

### Proposed Additions
- [ ] OpenTelemetry integration for distributed tracing
- [ ] Metrics collection (response times, error rates, tool success rate)
- [ ] Structured logging with correlation IDs
- [ ] Log aggregation (ELK stack, Loki, etc.)
- [ ] Real-time alerts on errors/anomalies
- [ ] Performance dashboards
- [ ] A/B test tracking
- [ ] Cost tracking (LLM tokens, API calls)

### Example Enhancements
```python
# Add correlation ID to all logs in a request
context = contextvars.ContextVar('correlation_id')
context.set(str(uuid.uuid4()))

# Add custom formatter that includes correlation_id
log_data["correlation_id"] = context.get()

# Track metrics
metrics.increment("agent.turns.total", tags={"model": "qwen-plus"})
metrics.histogram("agent.turn.duration_ms", duration_ms)
metrics.increment("tool.calls", tags={"tool": tool_name, "success": success})
```

