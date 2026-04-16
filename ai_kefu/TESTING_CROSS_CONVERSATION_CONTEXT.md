# Testing Guide: Cross-Conversation Context Loading

## Overview
This document provides a comprehensive testing guide for the cross-conversation context loading feature implemented in commit `ad202fa`.

## Test Files

### 1. Unit Tests: `tests/unit/test_agent/test_cross_conversation_context.py`

**Purpose:** Test individual components of the cross-conversation context loading system.

#### Test Cases:

**a) Cache Hit Tests**
- `test_load_user_history_as_context_cache_hit`
  - Verifies that when a cached summary exists with matching fingerprint, it's reused
  - Expected: Session context populated from Redis cache in ~5-10ms
  
**b) Cache Miss Tests**
- `test_load_user_history_as_context_cache_miss_no_history`
  - Tests behavior when no cache exists and user has no history
  - Expected: Context gracefully handles empty history
  
**c) Time-Proximity Compression Tests**
- `test_compress_by_time_proximity_recent_messages_verbatim`
  - Verifies recent 20 messages are kept verbatim (not compressed)
  - Expected: Recent messages preserve exact text for accuracy
  
- `test_compress_by_time_proximity_old_messages_summarized`
  - Tests that messages 20-60 are summarized, and messages 60+ are further compressed
  - Expected: Compressed output has fewer tokens than input

**d) API Fetch Tests**
- `test_fetch_xianyu_api_history_timeout`
  - Verifies timeout handling with 30-second limit
  - Expected: Gracefully returns empty list on timeout
  
- `test_fetch_xianyu_api_history_success`
  - Tests successful API history retrieval
  - Expected: Messages returned from API with proper format

**e) Cache Management Tests**
- `test_get_user_summary_cache_key`
  - Verifies cache key format: `user_history_summary:{user_id}`
  
- `test_get_cached_user_summary_not_found`
  - Tests Redis GET on non-existent key
  
- `test_get_cached_user_summary_found`
  - Tests Redis GET on existing key
  
- `test_set_cached_user_summary`
  - Tests Redis SETEX with 1-hour TTL

### 2. Integration Tests: `tests/integration/test_agent/test_cross_conversation_integration.py`

**Purpose:** Test end-to-end workflows involving multiple components.

#### Test Cases:

**a) Full Workflow Tests**
- `test_cross_conversation_context_workflow`
  - Tests complete flow: fetch multiple conversations → compress → summarize → cache
  - Setup: User with 2 previous conversations about iPhone rentals
  - Expected: Context summary properly reflects both conversations
  - Performance: Should complete in <2 seconds

**b) Fallback Tests**
- `test_cross_conversation_context_with_api_fallback`
  - Tests fallback to Xianyu API when MySQL fails
  - Setup: MySQL connection error, API available
  - Expected: System gracefully switches to API source
  - Error handling: No user-facing errors

**c) Compression Tests**
- `test_cross_conversation_context_time_compression`
  - Tests compression with large history (100+ messages)
  - Setup: 100 messages spanning 24 hours
  - Expected: Compression reduces tokens significantly
  - Performance: LLM summarization should complete in <5 seconds

**d) Cache Invalidation Tests**
- `test_context_summary_invalidation_on_fingerprint_change`
  - Tests that cache is invalidated when message fingerprint changes
  - Setup: Cached summary with old fingerprint, new messages available
  - Expected: New summary generated, cache updated

## Running Tests

### Prerequisites
```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu
python -m pip install pytest pytest-asyncio pytest-mock pytest-cov
```

### Run Unit Tests
```bash
PYTHONPATH=. python -m pytest tests/unit/test_agent/test_cross_conversation_context.py -v
```

### Run Integration Tests
```bash
PYTHONPATH=. python -m pytest tests/integration/test_agent/test_cross_conversation_integration.py -v
```

### Run All Tests with Coverage
```bash
PYTHONPATH=. python -m pytest tests/ -v --cov=ai_kefu --cov-report=html
```

## Test Coverage

### Code Coverage Targets
- `agent/executor.py`: 85%+ (focus on `_load_user_history_as_context`, compression, caching)
- `xianyu_interceptor/conversation_store.py`: 90%+ (focus on history retrieval)
- `utils/logging.py`: 80%+ (focus on new loguru integration)

### Critical Paths to Test
1. ✓ Cache hit path (lines 600-616 in executor.py)
2. ✓ Cache miss + history loading path (lines 642-720)
3. ✓ API fallback path (lines 720-760)
4. ✓ Compression path (lines 761-823)
5. ✓ Fingerprint validation (lines 680-690)

## Performance Benchmarks

### Expected Timings
- **Cache hit:** 5-10ms
- **Cache miss (MySQL hit):** 500-1000ms
- **API fallback:** 1000-2000ms
- **Large history compression:** 2000-5000ms
- **Redis operations:** 1-5ms per operation

### Memory Usage
- Session context size: ~10-50KB (typical)
- Large history buffer (100 messages): ~200KB
- Compression reduces by ~70%

## Error Scenarios

### Scenario 1: MySQL Connection Failure
```
Setup: MySQL down, Redis available, API available
Expected: Fallback to API successfully
Result: User gets context from API, system continues normally
```

### Scenario 2: Redis Connection Failure
```
Setup: Redis down, MySQL available
Expected: System continues without caching (performance impact)
Result: Context loaded each turn from MySQL (slower but functional)
```

### Scenario 3: API Rate Limit
```
Setup: API rate limited, MySQL available
Expected: Fallback to MySQL gracefully
Result: User gets context from MySQL cache
```

### Scenario 4: Large History (1000+ messages)
```
Setup: User with very large conversation history
Expected: Compression reduces to manageable size
Result: Summary quality maintained with ~70% compression
```

## Load Testing

### Test with Different User Profiles

**Profile A: New User (0 conversations)**
- Expected: Context loading <10ms
- Cache: Fresh content

**Profile B: Regular User (10-50 messages)**
- Expected: Context loading 500-800ms (MySQL)
- Cache: Likely hit rate 80%+

**Profile C: Power User (100+ messages across 5+ conversations)**
- Expected: Context loading 2-5 seconds (first time)
- Compression: ~70% reduction
- Cache: Essential for performance

**Profile D: Historical User (1000+ messages)**
- Expected: Context loading 5-10 seconds (first time)
- Compression: Multi-tier (verbatim recent, summarize mid, compress old)
- Caching: Critical for performance

## Monitoring & Metrics

### Metrics to Track

1. **Cache Performance**
   - Cache hit rate: target 85%+
   - Cache eviction rate: <5%
   - Cache TTL effectiveness

2. **History Loading**
   - MySQL query time
   - API fetch time
   - Compression effectiveness (token reduction %)

3. **Error Rates**
   - MySQL connection failures
   - API timeouts
   - Fingerprint mismatches
   - Cache corruption

4. **User Impact**
   - First response time (with context loading)
   - Subsequent response time (cache hit)
   - Context summary accuracy (manual review)

## Validation Checklist

Before production deployment:

- [ ] All unit tests pass (8/8)
- [ ] All integration tests pass (4/4)
- [ ] Code coverage >80% for critical paths
- [ ] Performance benchmarks met
- [ ] Error scenarios handled gracefully
- [ ] Backward compatibility maintained
- [ ] Logging properly captures all operations
- [ ] Redis connection pooling working
- [ ] MySQL query optimization verified
- [ ] API timeout handling tested

## Known Limitations & Future Improvements

### Current Limitations
1. Time-proximity compression hardcoded to 3 tiers (recent 20, mid 40, old all)
2. Max history size: 100 messages per API call
3. Compression occurs on every cache miss

### Future Improvements
1. Implement adaptive compression based on message volume
2. Add configurable compression thresholds
3. Implement incremental history updates (vs. full reload)
4. Add ML-based summary quality scoring
5. Implement user preference for context detail level

## Troubleshooting

### Issue: Cache Always Misses
**Diagnosis:**
- Check fingerprint values in Redis
- Verify cache TTL not expiring too quickly
- Monitor Redis memory usage

**Solution:**
- Adjust TTL in `_set_cached_user_summary()` (currently 3600s)
- Verify Redis connection pool size

### Issue: Context Summary Poor Quality
**Diagnosis:**
- Check LLM summarization prompt
- Verify message ordering in compression
- Review sample summaries in logs

**Solution:**
- Tune LLM prompt in `_summarize_history()`
- Increase verbatim message count (currently 20)
- Add domain-specific prompts for rental context

### Issue: Slow Context Loading
**Diagnosis:**
- Profile MySQL queries with EXPLAIN
- Monitor API response times
- Check compression algorithm efficiency

**Solution:**
- Add database indexes on user_id, chat_id
- Implement query caching
- Optimize compression algorithm

## Test Maintenance

### When to Update Tests
- When new compression algorithm is added
- When cache invalidation strategy changes
- When API contract changes
- When new error scenarios discovered
- When performance requirements change

### Test Review Cadence
- After each production deployment
- When users report context-related issues
- Quarterly performance review
- After major system changes

