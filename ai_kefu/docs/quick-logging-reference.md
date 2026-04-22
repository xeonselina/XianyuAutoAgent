# Quick Logging Reference Guide

## Quick Start

### How to Find Logs

1. **Interceptor Logs** (Transport layer - Xianyu WebSocket)
   ```bash
   tail -f logs/xianyu_interceptor_$(date +%Y-%m-%d).log
   ```

2. **API Logs** (Business logic - via console)
   ```bash
   # Docker: docker logs <container_id> | grep "ai_kefu"
   # or grep JSON logs: | grep "event_type"
   ```

### How to Check Specific Events

```bash
# Find all turn completions
grep '"event_type":"turn_end"' logs/xianyu_interceptor_*.log

# Find all tool calls
grep '"event_type":"tool_call"' logs/xianyu_interceptor_*.log

# Find errors
grep '"level":"ERROR"' logs/xianyu_interceptor_*.log

# Find specific session
grep 'sess_abc123' logs/xianyu_interceptor_*.log
```

---

## Logging Checklist

### When Adding New Features

- [ ] Add logging at entry point (INFO level)
- [ ] Log decisions/branches (INFO level)
- [ ] Log completion with status (INFO level)
- [ ] Log errors with context (ERROR level)
- [ ] Add session_id to all logs (via extra= parameter)
- [ ] Consider performance impact (avoid logging in hot loops)
- [ ] Ensure no sensitive data logged (credentials, full messages)

### When Debugging

1. **Interceptor Issue?** Check interceptor logs first
   ```bash
   grep "📄 设置页面监控" logs/xianyu_interceptor_*.log
   ```

2. **API/Agent Issue?** Check API logs (console output)
   ```bash
   # Look for "turn_start" → "tool_call" → "turn_end" sequence
   ```

3. **Manual Mode Problem?** Search for manual_mode logs
   ```bash
   grep "manual" logs/xianyu_interceptor_*.log
   ```

4. **Order Not Saved?** Check conversation store logs
   ```bash
   grep "Logged message" logs/xianyu_interceptor_*.log
   ```

---

## Log Level Guidelines

### When to Use Each Level

| Level | Use Case | Example |
|-------|----------|---------|
| DEBUG | Detailed diagnostics | LLM request/response, WebSocket frames |
| INFO | High-level events | Turn start, tool call, agent complete |
| WARNING | Unusual but handled | Config missing, fallback used |
| ERROR | Failures | Tool failed, API error |

### Setting Log Level

```bash
# In .env
LOG_LEVEL=DEBUG    # More verbose
LOG_LEVEL=INFO     # Normal (default)
LOG_LEVEL=WARNING  # Less verbose
LOG_LEVEL=ERROR    # Only errors
```

---

## Common Log Patterns

### Successful Message Flow
```
[14:31:16] INFO  - Browser startup
[14:31:17] INFO  - 📄 设置页面监控
[14:31:18] INFO  - 🔍 WebSocket message received
[14:31:19] INFO  - 🔬 [解码成功] 消息分类=chat
[14:31:20] INFO  - [xianyu/inbound] ▶ chat_id=...
[14:31:21] INFO  - [xianyu/inbound] 🤖 calling agent
[14:31:22] INFO  - [agent] Turn 0 started
[14:31:23] INFO  - [agent] Tool called: knowledge_search
[14:31:25] INFO  - [agent] Tool completed ✓
[14:31:26] INFO  - [agent] Turn 0 completed ✓
[14:31:27] INFO  - [xianyu/inbound] ✅ done: reply='...'
```

### Manual Mode Toggle
```
[14:31:20] INFO  - [xianyu/inbound] ▶ content='。'
[14:31:21] INFO  - Chat <chat_id> toggled to 手动 mode
[14:31:22] INFO  - [xianyu/inbound] ✅ done: reply='已切换到手动模式'
```

### AI Suppression
```
[14:31:20] INFO  - Seller sent suppress keyword in chat <chat_id>
[14:31:21] INFO  - AI suppressed for 600s
[14:31:22] INFO  - [xianyu/inbound] 🔇 AI suppressed, remaining 599s
```

### Order Placed
```
[14:31:20] INFO  - [xianyu/inbound] ▶ content='[我已拍下，待付款]'
[14:31:21] INFO  - 📦 用户拍下商品: chat_id=... 准备生成租机摘要
[14:31:22] INFO  - 📋 租机摘要生成成功
[14:31:23] INFO  - 🎉 已转发 1 条历史消息到 API 层入库
```

---

## Structured JSON Logs (Production)

### AI Agent JSON Log Example
```json
{
  "timestamp": "2026-04-13T14:31:22.123Z",
  "level": "INFO",
  "logger": "ai_kefu",
  "message": "Turn 0 started",
  "session_id": "sess_abc123",
  "event_type": "turn_start",
  "turn_counter": 0,
  "query_length": 28
}
```

### Extracting Specific Fields
```bash
# Get all sessions that completed
cat logs/xianyu_interceptor_*.log | jq 'select(.event_type=="agent_complete")'

# Average turn duration
cat logs/xianyu_interceptor_*.log | jq 'select(.event_type=="turn_end") | .duration_ms' | awk '{sum+=$1; count++} END {print sum/count}'

# Tool success rate
cat logs/xianyu_interceptor_*.log | jq 'select(.event_type=="tool_call_end") | .success' | sort | uniq -c
```

---

## Troubleshooting Common Issues

### Issue: No Messages Being Processed

**Check:**
```bash
# 1. Is interceptor running?
ps aux | grep run_xianyu.py

# 2. Is browser connected?
grep "WebSocket 连接已建立" logs/xianyu_interceptor_*.log

# 3. Are messages being received?
grep "消息分类=" logs/xianyu_interceptor_*.log
```

### Issue: Messages Not Being Replied To

**Check:**
```bash
# 1. Is manual mode on?
grep "manual mode active" logs/xianyu_interceptor_*.log

# 2. Is AI suppressed?
grep "AI suppressed" logs/xianyu_interceptor_*.log

# 3. Is debug mode on?
grep "enable_ai_reply.*false" logs/xianyu_interceptor_*.log

# 4. Did agent return response?
grep '"response_len=' logs/xianyu_interceptor_*.log
```

### Issue: Agent Returning Empty/Bad Response

**Check:**
```bash
# 1. Is agent running?
grep "Turn.*started" logs/xianyu_interceptor_*.log

# 2. Did any tools fail?
grep "Tool.*completed ✗" logs/xianyu_interceptor_*.log

# 3. Check confidence guard
grep "置信度抑制" logs/xianyu_interceptor_*.log

# 4. Check for errors
grep '"level":"ERROR"' logs/xianyu_interceptor_*.log | head -20
```

### Issue: Infinite Loop Detected

**Check:**
```bash
# Look for loop detection
grep "loop_detection" logs/xianyu_interceptor_*.log

# Check max turns reached
grep "MaxTurnsExceededError" logs/xianyu_interceptor_*.log

# Count tool calls per session
grep '"event_type":"tool_call_start"' logs/xianyu_interceptor_*.log | wc -l
```

---

## Performance Monitoring

### Turn Timing
```bash
# Get average turn duration
grep '"event_type":"turn_end"' logs/xianyu_interceptor_*.log | jq '.duration_ms' | awk '{sum+=$1; count++} END {print "Avg:", sum/count "ms"}'
```

### Tool Performance
```bash
# Tool success rate by name
grep '"event_type":"tool_call_end"' logs/xianyu_interceptor_*.log | jq '[.tool_name, .success] | @csv' | sort | uniq -c
```

### Session Metrics
```bash
# Total sessions
grep '"event_type":"agent_complete"' logs/xianyu_interceptor_*.log | jq '.session_id' | sort -u | wc -l

# Messages processed
grep '"event_type":"turn_start"' logs/xianyu_interceptor_*.log | wc -l
```

---

## Log Storage & Cleanup

### Current Setup
- **Interceptor:** Auto-rotates daily, keeps 7 days, auto-compresses
- **API:** Outputs to stdout, captured by Docker/systemd
- **Database:** Conversation messages stored in MySQL

### Manual Cleanup (if needed)
```bash
# Remove logs older than 30 days
find logs/ -name "*.log*" -mtime +30 -delete

# Clear specific date
rm logs/xianyu_interceptor_2026-04-01.log*

# Archive logs for long-term storage
tar -czf logs_backup_2026-04.tar.gz logs/xianyu_interceptor_2026-04-*.log*
```

---

## Integration with Monitoring

### Prometheus Metrics (Future)
```
ai_kefu_turns_total
ai_kefu_turn_duration_seconds
ai_kefu_tool_calls_total{tool="knowledge_search"}
ai_kefu_tool_errors_total{tool="knowledge_search"}
ai_kefu_agent_response_latency_seconds
```

### ELK Stack Integration (Future)
```
POST /ai-kefu-logs/_doc
{
  "timestamp": "2026-04-13T14:31:16.455Z",
  "session_id": "sess_abc123",
  "event_type": "turn_end",
  "duration_ms": 1234,
  "success": true,
  "host": "prod-server-1",
  "environment": "production"
}
```

---

## Useful Commands

### Watch Real-time Logs
```bash
# Interceptor logs with color
tail -f logs/xianyu_interceptor_$(date +%Y-%m-%d).log | grep --color=auto "INFO\|ERROR\|WARNING"

# API logs (from docker)
docker logs -f <container_id> 2>&1 | grep "ai_kefu"
```

### Search Patterns
```bash
# Find specific user's messages
grep 'user_id.*12345' logs/xianyu_interceptor_*.log

# Find failed operations
grep '✗' logs/xianyu_interceptor_*.log

# Find with timestamps
grep -E '2026-04-13 14:3[0-2]' logs/xianyu_interceptor_*.log

# Extract just the message part
grep 'INFO' logs/xianyu_interceptor_*.log | awk '{print $NF}'
```

### Export Logs
```bash
# To JSON (if already JSON)
cat logs/xianyu_interceptor_*.log | jq '.' > exported.json

# To CSV (extract specific fields)
grep '"event_type"' logs/xianyu_interceptor_*.log | jq -r '[.timestamp, .event_type, .session_id] | @csv' > events.csv

# To human-readable
grep -v DEBUG logs/xianyu_interceptor_*.log > production.log
```

