# XianYu Orders - Quick Reference Guide

## At a Glance

| Aspect | Details |
|--------|---------|
| **What** | Stores order snapshots when buyers place Xianyu rental orders |
| **Where** | MySQL table: `xianyu_orders` |
| **When** | Created on app startup; records added when order-placed messages detected |
| **How** | Async fire-and-forget: fetch from Xianyu API, upsert to DB |
| **Key File** | `xianyu_interceptor/conversation_store.py` (schema + upsert) |

---

## Quick Lookup: Where Is X?

### Table Schema?
→ `xianyu_interceptor/conversation_store.py` lines 95-120

### Order Inserted/Updated?
→ `xianyu_interceptor/conversation_store.py` method `save_order_detail()` lines 357-449

### Order Detection?
→ `api/routes/xianyu.py` lines 664-674

### Order ID Extraction?
→ `api/routes/xianyu.py` lines 235-316

### API Fetch?
→ `xianyu_provider/goofish_provider.py` method `_sync_get_order_detail()` lines 343-425

### Tool Definition?
→ `tools/xianyu/get_order_detail.py` or `tools/get_order_status.py`

---

## Data Flow in 10 Steps

1. **Buyer sends order-placed message** → Interceptor POSTs to `/xianyu/inbound`
2. **Detect order message** → Check if content is `[我已拍下，待付款]` or similar
3. **Extract order_id** → Try 3 methods: reminderUrl, extJson.updateKey, nested JSON
4. **Fire async task** → `asyncio.ensure_future(_record_order_detail())`
5. **Continue processing** → Don't block main flow
6. **Call Xianyu API** → `provider.get_order_detail(order_id)`
7. **Parse response** → Extract status, amount, SKU, etc.
8. **Prepare for DB** → Convert to JSON, add raw response
9. **Upsert to DB** → `INSERT ... ON DUPLICATE KEY UPDATE`
10. **Log result** → Info/warning in logs

---

## Key Columns

```
order_id           - Unique constraint key
chat_id            - Links to conversations table
user_id            - Buyer's Xianyu user ID
order_status       - Raw status code (e.g. "WAIT_SELLER_SEND_GOODS")
order_status_label - Human-readable (e.g. "等待卖家发货")
order_amount       - Price in 元 (Chinese currency)
sku                - Product specs (e.g. "颜色: 红色；尺码: L")
quantity           - How many units ordered
buyer_nickname     - Buyer's display name
item_title         - Product name at time of order
raw_detail         - Parsed JSON from API
raw_api_response   - Complete unmodified API response
created_at         - When record was first inserted
updated_at         - When record was last updated
```

---

## Order Status Codes

| Code | Chinese | Meaning |
|------|---------|---------|
| `WAIT_BUYER_PAY` | 等待买家付款 | Waiting for buyer payment |
| `WAIT_SELLER_SEND_GOODS` | 等待卖家发货 | Seller preparing shipment |
| `WAIT_BUYER_CONFIRM_GOODS` | 等待买家确认收货 | Buyer received, awaiting confirmation |
| `TRADE_FINISHED` | 交易完成 | Transaction complete |
| `TRADE_CLOSED` | 交易关闭 | Trade closed |
| `REFUND_SUCCESS` | 退款成功 | Refund processed |

---

## Code Snippets

### Detect Order Placed
```python
# In xianyu.py line 73-100
_ORDER_PLACED_KEYWORDS = [
    "[我已拍下，待付款]",      # I've placed, awaiting payment
    "[我已付款，等待你发货]",  # I've paid, waiting for shipment
]

if _is_order_placed_message(req.content):
    # Order was just placed!
```

### Extract Order ID (3 Methods)
```python
# Method 1: From URL parameter
if "orderId=" in reminder_url:
    order_id = reminder_url.split("orderId=")[1].split("&")[0]

# Method 2: From structured field
update_key = ext.get("updateKey", "")  # "chat_id:order_id:seq:status:ct"
order_id = update_key.split(":")[1]

# Method 3: From nested JSON
if "order_detail?id=" in nested_str:
    order_id = nested_str.split("order_detail?id=")[1].split("&")[0]
```

### Fire-and-Forget Task
```python
# Don't block main flow - run async in background
asyncio.ensure_future(
    _record_order_detail(req=req, order_id=order_id, conversation_store=conversation_store)
)
```

### Upsert to DB
```python
sql = """
    INSERT INTO xianyu_orders (chat_id, user_id, item_id, order_id, ...)
    VALUES (%s, %s, %s, %s, ...)
    ON DUPLICATE KEY UPDATE
        order_status = VALUES(order_status),
        order_amount = VALUES(order_amount),
        ...
"""
cursor.execute(sql, values)
conn.commit()
```

---

## Debugging: Common Issues

### Order ID not extracted?
- Check `raw_data` structure in request logs
- Verify order message is one of `_ORDER_PLACED_KEYWORDS`
- Try all 3 extraction methods manually

### API call fails?
- Check Xianyu API token (auth may have expired)
- Verify network connectivity to `h5api.m.goofish.com`
- Check logs for `[get_order_detail] FAILED`

### Record not in DB?
- Fire-and-forget is async - wait a moment
- Check MySQL `xianyu_orders` table directly:
  ```sql
  SELECT * FROM xianyu_orders WHERE order_id = '...';
  ```
- Check application logs for `Upserted order detail`

### Duplicate records?
- Shouldn't happen - `UNIQUE KEY uq_order_id` prevents duplicates
- Same `order_id` will UPDATE existing row, not insert new one

---

## SQL Queries (Copy-Paste Ready)

### All orders for a user
```sql
SELECT * FROM xianyu_orders 
WHERE user_id = 'buyer_id_here' 
ORDER BY created_at DESC;
```

### Get specific order
```sql
SELECT * FROM xianyu_orders 
WHERE order_id = '12345678901234';
```

### Orders by status
```sql
SELECT order_status_label, COUNT(*) as cnt
FROM xianyu_orders
GROUP BY order_status_label
ORDER BY cnt DESC;
```

### Recent orders
```sql
SELECT order_id, buyer_nickname, order_status_label, order_amount, created_at
FROM xianyu_orders
ORDER BY created_at DESC
LIMIT 20;
```

### Join with conversation messages
```sql
SELECT c.*, o.order_status_label, o.order_amount
FROM conversations c
JOIN xianyu_orders o ON c.chat_id = o.chat_id
WHERE o.order_id = '12345678901234'
ORDER BY c.created_at;
```

---

## Architecture Notes

### Why Fire-and-Forget?
- Order API fetch is slow (network round-trip)
- Database write can take milliseconds
- User expects fast response to their message
- Decoupling: message handling ≠ order recording

### Why Upsert Pattern?
- Order might be recorded twice (order-placed → payment-confirmed)
- Rather than duplicate, UPDATE with latest info
- Single `UNIQUE KEY uq_order_id` prevents duplicates
- `updated_at` tracks when status last changed

### Why Store Raw API Response?
- Xianyu API may change over time
- Raw response is audit trail for debugging
- Can re-parse if extraction logic changes
- Full transparency for data recovery

### Thread Safety
- Connection pool protected with `threading.Lock`
- Each database operation is atomic (commit/rollback)
- Async tasks coordinated with `asyncio.ensure_future()`

---

## Testing Checklist

- [ ] Order message is detected (`_is_order_placed_message()`)
- [ ] Order ID extracted from raw_data
- [ ] API call succeeds (check logs for `OK:`)
- [ ] Record appears in `xianyu_orders` table
- [ ] `order_status_label` is human-readable
- [ ] `raw_detail` and `raw_api_response` are valid JSON
- [ ] Duplicate order ID updates existing row (doesn't create new)
- [ ] Null/missing fields handled gracefully

---

## Performance Considerations

- **Index Strategy**: 
  - `UNIQUE uq_order_id` for fast lookups
  - `idx_chat_id` for conversation joins
  - `idx_user_id` for buyer history
  - `idx_created_at` for time-range queries

- **JSON Storage**: 
  - Efficient for unstructured API data
  - Searchable with JSON operators if needed
  - Indexes not needed on JSON fields (usually)

- **Fire-and-Forget**: 
  - Improves user-facing latency
  - Background task failures logged but don't crash main flow

---

## Contacts / Next Steps

- **Schema Changes**: Update `_ensure_table_exists()` in `conversation_store.py`
- **Status Mappings**: Update `_ORDER_STATUS_MAP` in `goofish_provider.py`
- **API URL Changes**: Update `_ORDER_DETAIL_URL` in `goofish_provider.py`
- **Tool Integration**: Modify `tools/xianyu/get_order_detail.py`

