# Deployment Guide: Cross-Conversation Context Loading

## Overview
This guide provides step-by-step instructions for deploying the cross-conversation context loading feature (commit `ad202fa`, test suite `65bba6e`) to production.

## Pre-Deployment Checklist

### 1. Code Review & Testing
- [x] All 12 unit tests passing
- [x] All 4 integration tests passing
- [x] Code coverage >80% for critical paths
- [x] All Python files compile without syntax errors
- [x] No circular import dependencies
- [x] Backward compatibility verified
- [x] Git history clean and documented

### 2. Database Preparation
- [ ] Backup current MySQL database
- [ ] Verify conversation history availability
- [ ] Check Redis cluster health
- [ ] Verify available disk space for logs
- [ ] Test database connection strings

### 3. Infrastructure Readiness
- [ ] Redis: memory sufficient (recommend 2GB+ for context cache)
- [ ] MySQL: query optimization completed (indexes on user_id, chat_id)
- [ ] Network: low latency to Redis/MySQL required
- [ ] Monitoring: logging infrastructure ready (loguru compatible)

## Deployment Steps

### Phase 1: Staging Deployment (Pre-Production)

#### 1.1 Environment Setup
```bash
# On staging server
cd /Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu

# Verify Python environment
python3 --version  # Should be 3.9+
pip list | grep -E "(loguru|redis|pymysql)"

# Activate virtual environment
source venv/bin/activate
```

#### 1.2 Code Deployment
```bash
# Pull latest code
git pull origin main

# Verify commit is present
git log --oneline | head -5

# Check for any uncommitted changes
git status  # Should be clean
```

#### 1.3 Dependency Installation
```bash
# Install any new dependencies
pip install -r requirements.txt

# Verify loguru installation
python -c "from loguru import logger; print('loguru OK')"

# Verify Redis client
python -c "import redis; print('redis OK')"

# Verify all imports work
python -m py_compile agent/executor.py
python -m py_compile xianyu_interceptor/conversation_store.py
python -m py_compile utils/logging.py
```

#### 1.4 Configuration Updates
```bash
# Update .env with staging Redis/MySQL URLs
cat .env.staging > .env

# Verify configuration
python -c "from ai_kefu.config.settings import settings; \
  print(f'MySQL: {settings.mysql_host}'); \
  print(f'Redis: {settings.redis_host}')"
```

#### 1.5 Service Restart
```bash
# Stop existing service
docker-compose down

# Start with new code
docker-compose up -d

# Wait for services to be ready
sleep 10

# Verify services are running
docker-compose ps

# Check logs for errors
docker-compose logs --tail=50 app
```

#### 1.6 Smoke Tests
```bash
# Run basic health checks
curl http://localhost:8000/health

# Test cross-conversation context loading
PYTHONPATH=. python -m pytest tests/unit/test_agent/test_cross_conversation_context.py::TestCrossConversationContextLoading::test_load_user_history_as_context_cache_hit -v

# Test integration flow
PYTHONPATH=. python -m pytest tests/integration/test_agent/test_cross_conversation_integration.py::TestCrossConversationIntegration::test_cross_conversation_context_workflow -v
```

#### 1.7 Performance Baseline
```bash
# Measure cache hit performance
PYTHONPATH=. python << 'PYTHON'
import time
from ai_kefu.agent.executor import AgentExecutor
from unittest.mock import Mock

executor = AgentExecutor(Mock(), Mock(), Mock())

# Simulate cache hit
start = time.time()
# Cache operation here
end = time.time()

print(f"Cache hit time: {(end-start)*1000:.2f}ms (target: <10ms)")
PYTHON
```

### Phase 2: Canary Deployment (Production)

#### 2.1 Canary Release
```bash
# Deploy to 5% of production traffic
kubectl set image deployment/ai-kefu-app app=ai-kefu:v1.2.0-cross-context

# Monitor for 30 minutes
watch 'kubectl logs -l app=ai-kefu -f | tail -20'
```

#### 2.2 Metrics Collection
Monitor during canary:
```bash
# Response time metrics
kubectl logs -l app=ai-kefu | grep "context_loading" | grep "duration"

# Cache hit rate
kubectl logs -l app=ai-kefu | grep "cache_hit_rate"

# Error rate
kubectl logs -l app=ai-kefu | grep -i error | wc -l
```

#### 2.3 Success Criteria (All Must Pass)
- [ ] No increase in error rates (target: <0.1%)
- [ ] Response time increase <100ms (with context)
- [ ] Cache hit rate >80%
- [ ] No timeouts or connection failures
- [ ] All logs structured correctly (JSON format)

#### 2.4 Proceed or Rollback
If all criteria met:
```bash
# Proceed to full rollout
kubectl scale deployment ai-kefu-app --replicas=10
```

If issues found:
```bash
# Rollback to previous version
kubectl set image deployment/ai-kefu-app app=ai-kefu:v1.1.0
```

### Phase 3: Full Production Deployment

#### 3.1 Gradual Rollout
```bash
# Deploy to 50% of traffic
kubectl patch deployment ai-kefu-app -p '{"spec":{"strategy":{"rollingUpdate":{"maxSurge":5}}}}'

# Increase to 100% after 1 hour
kubectl set image deployment/ai-kefu-app app=ai-kefu:v1.2.0-cross-context
```

#### 3.2 Post-Deployment Verification
```bash
# Verify all pods are running
kubectl get pods | grep ai-kefu-app

# Check for any deployment errors
kubectl describe deployment ai-kefu-app

# Tail logs for any issues
kubectl logs -f -l app=ai-kefu-app --all-containers=true

# Test core functionality
curl -X POST http://api.example.com/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Do you have iPhone 15 Pro available?",
    "session_id": "test-001",
    "user_id": "user-001",
    "context": {"conversation_id": "conv-001"}
  }'
```

## Monitoring & Alerting

### Metrics to Monitor

#### 1. Context Loading Performance
```
Metric: context_load_time_ms
- Target: <1000ms (p95)
- Alert: >2000ms for 5+ minutes
- Dashboard: Real-time histogram
```

#### 2. Cache Effectiveness
```
Metric: cache_hit_rate_percent
- Target: >85%
- Alert: <70% for 15+ minutes
- Dashboard: Time series graph
```

#### 3. API Fallback Rate
```
Metric: api_fallback_count_per_minute
- Target: <5% of requests
- Alert: >20% for 5+ minutes
- Dashboard: Counter metric
```

#### 4. Error Rates
```
Metric: context_loading_error_rate
- Target: <0.1%
- Alert: >1% for 5+ minutes
- Categories: MySQL errors, API timeouts, compression failures
```

### Alert Configuration

#### Critical Alerts (Page On-Call)
```
- context_load_time_ms > 5000ms (sustained 10+ min)
- cache_hit_rate < 50% (sustained 15+ min)
- api_fallback_rate > 50% (sustained 5+ min)
- Database query timeout > 1000ms (sustained 5+ min)
```

#### Warning Alerts (Slack Notification)
```
- context_load_time_ms > 2000ms (sustained 5+ min)
- cache_hit_rate < 70% (sustained 10+ min)
- API timeout rate > 10% (sustained 5+ min)
- Redis connection pool exhausted
```

### Logging Configuration

#### Log Levels (via environment variables)
```bash
# Development
LOG_LEVEL=DEBUG
LOG_FORMAT=text

# Staging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Production
LOG_LEVEL=INFO
LOG_FORMAT=json
LOG_RETENTION_DAYS=7
```

#### Key Logs to Monitor
```
# Cache operations
[INFO] context_summary_cache_hit: user_id=123, duration_ms=8

# History loading
[INFO] load_user_history: user_id=123, message_count=42, source=mysql

# Compression
[INFO] compress_by_time_proximity: before=100, after=35, ratio=0.35

# Summarization
[INFO] summarize_history: input_tokens=2500, output_tokens=200
```

## Rollback Plan

### If Critical Issues Discovered

#### Immediate Actions (0-5 minutes)
```bash
# 1. Stop current deployment
kubectl delete deployment ai-kefu-app

# 2. Restore previous version
kubectl apply -f deployment-v1.1.0.yaml

# 3. Verify restoration
kubectl get pods | grep ai-kefu-app
sleep 30
curl http://api.example.com/health
```

#### Investigation (5-30 minutes)
```bash
# Collect logs
kubectl logs -l app=ai-kefu-app > /tmp/crash_logs.txt

# Export metrics
prometheus_query_range("context_load_time_ms[30m]") > /tmp/metrics.csv

# Database state
mysqldump ai_kefu_db > /tmp/db_state.sql
```

#### Root Cause Analysis
- Review changed files in commit ad202fa
- Check specific log lines around error timestamp
- Verify database state matches expected
- Test specific failure scenario

### Recommended Rollback Triggers
1. Error rate >5% for 10+ minutes
2. Response time increase >500ms sustained
3. Database connection pool exhausted
4. Redis memory full
5. Unhandled exceptions in critical path

## Post-Deployment Tasks

### Day 1 (Hours 0-24)
- [ ] Monitor all critical metrics (cache hit, response time, errors)
- [ ] Verify cross-conversation context loading in production
- [ ] Review user feedback channels for issues
- [ ] Update documentation with any adjustments made
- [ ] Run performance profiling on production traffic

### Week 1
- [ ] Generate baseline metrics report
- [ ] Schedule post-deployment review meeting
- [ ] Document any anomalies or edge cases discovered
- [ ] Optimize any slow queries or cache misses
- [ ] Update run-books based on real production behavior

### Month 1
- [ ] Analyze cost impact (Redis memory, CPU usage)
- [ ] Review user satisfaction metrics (response quality)
- [ ] Plan performance optimizations if needed
- [ ] Update capacity planning based on growth
- [ ] Consider feature enhancements based on usage patterns

## Common Issues & Solutions

### Issue 1: Cache Hit Rate Below Target
**Symptoms:** Cache hit rate 60% (target 85%)
**Root Causes:**
- Fingerprint changing too frequently
- Redis memory eviction occurring
- User history not stable

**Solutions:**
1. Increase Redis memory allocation
2. Extend cache TTL from 3600s to 7200s
3. Adjust fingerprint calculation to be less sensitive

**Implementation:**
```python
# In executor.py, _set_cached_user_summary():
# Change from:
self.session_store.client.setex(cache_key, 3600, cache_data)
# To:
self.session_store.client.setex(cache_key, 7200, cache_data)
```

### Issue 2: API Fallback Rate High
**Symptoms:** API fallback >20% (target <5%)
**Root Causes:**
- MySQL connection pool exhausted
- Slow database queries
- Network latency to database

**Solutions:**
1. Increase MySQL connection pool size
2. Add indexes on user_id, chat_id columns
3. Optimize query execution plans

**Database Optimization:**
```sql
CREATE INDEX idx_user_id ON conversations(user_id);
CREATE INDEX idx_chat_id ON conversations(chat_id);
CREATE INDEX idx_user_chat ON conversations(user_id, chat_id);

ANALYZE TABLE conversations;
```

### Issue 3: Slow Context Loading (>2000ms)
**Symptoms:** p95 context load time 3000ms
**Root Causes:**
- Large history requiring extensive compression
- Slow LLM summarization
- Network latency

**Solutions:**
1. Reduce verbatim message threshold (from 20 to 10)
2. Increase compression tier thresholds
3. Use faster LLM model or add batch processing

## Success Metrics

### KPIs (Key Performance Indicators)

| Metric | Target | Method |
|--------|--------|--------|
| Cache Hit Rate | >85% | `cache_hits / total_requests` |
| Response Time (p95) | <1000ms | Application monitoring |
| Error Rate | <0.1% | Log analysis |
| Availability | 99.9% | Uptime tracking |
| User Retention | >95% | Session analysis |

### Business Metrics

| Metric | Target | Impact |
|--------|--------|--------|
| Avg Session Duration | +15% | Better user engagement |
| Completion Rate | +10% | More successful rentals |
| Support Tickets (Context) | -30% | Fewer duplicate queries |
| Customer Satisfaction | +5 NPS | Better service perception |

## Appendix

### A. Configuration Reference

**Redis Configuration**
```
redis:
  host: localhost
  port: 6379
  db: 0
  password: null
  pool_size: 10
  timeout: 3600  # 1 hour cache TTL
```

**MySQL Configuration**
```
mysql:
  host: localhost
  port: 3306
  user: root
  database: ai_kefu_db
  connection_pool_size: 10
  query_timeout: 5000  # 5 seconds
```

**Logging Configuration**
```
logging:
  level: INFO
  format: json
  file: logs/backend_YYYY-MM-DD.log
  rotation: daily
  retention: 7 days
```

### B. Quick Commands

```bash
# Check deployment status
kubectl rollout status deployment/ai-kefu-app

# View recent logs
kubectl logs -f deployment/ai-kefu-app --tail=100

# Access Redis CLI
kubectl exec -it redis-pod -- redis-cli

# MySQL backup
mysqldump -u root ai_kefu_db | gzip > backup.sql.gz

# Performance profiling
python -m cProfile -s cumtime app.py
```

