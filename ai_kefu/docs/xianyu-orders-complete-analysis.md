# Complete XianYu Orders Table Analysis

## Overview
The `xianyu_orders` table stores order details when buyers place orders on the XianYu (闲鱼) rental platform. It's a critical component of the order tracking system that captures order information at the moment of purchase.

---

## 1. TABLE SCHEMA DEFINITION

### Location
**File**: `/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/xianyu_interceptor/conversation_store.py`
**Lines**: 95-120

### Complete SQL Definition
```sql
CREATE TABLE IF NOT EXISTS xianyu_orders (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT 'Auto-increment primary key',
    chat_id VARCHAR(255) NOT NULL COMMENT 'Xianyu chat ID',
    user_id VARCHAR(255) NOT NULL COMMENT 'Buyer user ID',
    item_id VARCHAR(255) COMMENT 'Item ID',
    order_id VARCHAR(255) NOT NULL COMMENT 'Xianyu order ID (订单号)',
    order_status VARCHAR(64) COMMENT 'Raw order status code',
    order_status_label VARCHAR(128) COMMENT 'Human-readable order status',
    order_amount VARCHAR(64) COMMENT 'Payment amount in 元',
    sku TEXT COMMENT 'SKU / spec info',
    quantity VARCHAR(32) COMMENT 'Purchase quantity',
    buyer_nickname VARCHAR(255) COMMENT 'Buyer nickname',
    item_title TEXT COMMENT 'Item title at time of order',
    raw_detail JSON COMMENT 'Parsed order fields returned by get_order_detail()',
    raw_api_response JSON COMMENT 'Complete unmodified JSON from Xianyu API (res[data])',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation time',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last upsert time',

    UNIQUE KEY uq_order_id (order_id),
    INDEX idx_chat_id (chat_id),
    INDEX idx_user_id (user_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Xianyu order details recorded when buyer places an order'
```

### Key Characteristics:
- **Primary Key**: `id` (auto-increment)
- **Unique Constraint**: `uq_order_id` on `order_id` (ensures no duplicate orders)
- **Indexes**: 
  - `idx_chat_id` - for conversation lookups
  - `idx_user_id` - for buyer history queries
  - `idx_created_at` - for time-based queries
- **Character Set**: utf8mb4 (supports Chinese characters)
- **Storage Engine**: InnoDB (transactional)

---

## 2. RECORD INSERTION / UPSERT FLOW

### Location
**File**: `/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/xianyu_interceptor/conversation_store.py`
**Method**: `save_order_detail()`
**Lines**: 357-449

### Trigger Point
**File**: `/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/api/routes/xianyu.py`
**Lines**: 147-190 (`_record_order_detail()`)

### Complete Flow Code

#### Step 1: Order Placed Detection
```python
# xianyu.py, lines 664-674
# ── Order placed: generate rental summary first ──────────────────────
if _is_order_placed_message(req.content):
    summary = await _handle_order_placed(
        req=req,
        session_mapper=session_mapper,
        conversation_store=conversation_store,
    )
```

#### Step 2: Order ID Extraction
```python
# xianyu.py, lines 235-316
# Extract order_id from raw_data with multiple fallback methods:

# Method 1: reminderUrl query parameter
reminder_url = meta_10.get("reminderUrl", "")
if "orderId=" in reminder_url:
    order_id = reminder_url.split("orderId=")[1].split("&")[0]

# Method 2: extJson.updateKey (format: "chat_id:order_id:seq:status:ct")
ext_json_str = meta_10.get("extJson", "")
if ext_json_str:
    ext = json.loads(ext_json_str)
    update_key = ext.get("updateKey", "")
    parts = update_key.split(":")
    if len(parts) >= 2:
        candidate = parts[1]
        if candidate.isdigit() and len(candidate) >= 10:
            order_id = candidate

# Method 3: nested dxCard JSON in content field
# Look for "orderId=" or "order_detail?id=" in nested structures
```

#### Step 3: Fire-and-Forget Order Detail Recording
```python
# xianyu.py, lines 318-321
# Async fire-and-forget: record order detail WITHOUT blocking
asyncio.ensure_future(
    _record_order_detail(req=req, order_id=order_id, conversation_store=conversation_store)
)
```

#### Step 4: Order Detail Fetching
```python
# xianyu.py, lines 147-189
async def _record_order_detail(
    req: XianyuInboundRequest,
    order_id: Optional[str],
    conversation_store: ConversationStore,
):
    """Fire-and-forget: fetch order detail from Xianyu API and persist to xianyu_orders table."""
    if not order_id:
        logger.warning(f"[record_order_detail] chat_id={req.chat_id}: 无法从 raw_data 提取 order_id")
        return

    try:
        from ai_kefu.tools.xianyu import get_order_detail

        detail = await asyncio.to_thread(get_order_detail, order_id)

        if not detail.get("success"):
            logger.warning(
                f"[record_order_detail] get_order_detail 失败: "
                f"order_id={order_id}, error={detail.get('error')}"
            )
            return

        # Persist to database
        await asyncio.to_thread(
            conversation_store.save_order_detail,
            chat_id=req.chat_id,
            user_id=req.user_id,
            order_id=order_id,
            item_id=req.item_id,
            order_detail=detail,
        )
    except Exception as e:
        logger.error(f"[record_order_detail] 订单详情记录失败: {e}", exc_info=True)
```

#### Step 5: Database Upsert
```python
# conversation_store.py, lines 357-449
def save_order_detail(
    self,
    chat_id: str,
    user_id: str,
    order_id: str,
    item_id: Optional[str],
    order_detail: Dict[str, Any],
) -> int:
    """
    Upsert a Xianyu order detail record into the xianyu_orders table.
    Uses INSERT ... ON DUPLICATE KEY UPDATE so that if the same order_id
    is recorded again, the row is refreshed with latest status and raw data.
    """
    with self._lock:
        conn = None
        try:
            conn = self._get_connection()
            raw_api = order_detail.pop("_raw_api_response", None)

            sql = """
                INSERT INTO xianyu_orders (
                    chat_id, user_id, item_id, order_id,
                    order_status, order_status_label, order_amount,
                    sku, quantity, buyer_nickname, item_title,
                    raw_detail, raw_api_response
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s
                )
                ON DUPLICATE KEY UPDATE
                    order_status       = VALUES(order_status),
                    order_status_label = VALUES(order_status_label),
                    order_amount       = VALUES(order_amount),
                    sku                = VALUES(sku),
                    quantity           = VALUES(quantity),
                    buyer_nickname     = VALUES(buyer_nickname),
                    item_title         = VALUES(item_title),
                    raw_detail         = VALUES(raw_detail),
                    raw_api_response   = VALUES(raw_api_response)
            """

            values = (
                chat_id,
                user_id,
                item_id or order_detail.get("item_id") or "",
                order_id,
                order_detail.get("status") or "",
                order_detail.get("status_label") or "",
                order_detail.get("amount") or "",
                order_detail.get("sku") or "",
                order_detail.get("quantity") or "",
                order_detail.get("buyer_nickname") or "",
                order_detail.get("item_title") or "",
                json.dumps(order_detail, ensure_ascii=False, default=str),
                json.dumps(raw_api, ensure_ascii=False, default=str) if raw_api is not None else None,
            )

            with conn.cursor() as cursor:
                cursor.execute(sql, values)
                conn.commit()
                row_id = cursor.lastrowid or 0

            logger.info(
                f"Upserted order detail: chat_id={chat_id}, order_id={order_id}, "
                f"status={order_detail.get('status_label')!r}, row_id={row_id}"
            )
            return row_id

        except Exception as e:
            logger.error(f"Failed to save order detail: {e}")
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            return -1
```

---

## 3. ORDER DETAIL FETCHING

### Location
**File**: `/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/tools/xianyu/get_order_detail.py`
**Lines**: 1-88

### Function Definition
```python
def get_order_detail(order_id: str) -> Dict[str, Any]:
    """
    Fetch Xianyu order details by order ID.

    Args:
        order_id: The Xianyu order ID (订单号).

    Returns:
        {
            "success": bool,
            "order_id": str,
            "item_id": str,
            "item_title": str,
            "sku": str,            # e.g. "颜色: 红色；尺码: L"
            "quantity": str,       # quantity purchased
            "amount": str,         # total payment in 元, e.g. "199.00"
            "status": str,         # raw status code
            "status_label": str,   # human-readable status
            "buyer_id": str,
            "buyer_nickname": str,
            "create_time": str,
            "error": str           # only when success=False
        }
    """
    try:
        logger.info(f"[get_order_detail] Fetching order: {order_id}")
        provider = get_provider()
        result = asyncio.run(provider.get_order_detail(str(order_id)))

        if result["success"]:
            logger.info(
                f"[get_order_detail] OK: order_id={order_id}, "
                f"status={result.get('status_label')!r}, "
                f"amount={result.get('amount')!r}"
            )
        else:
            logger.warning(
                f"[get_order_detail] FAILED: order_id={order_id}, error={result.get('error')}"
            )
        return result

    except ValueError as e:
        msg = str(e)
        logger.error(f"[get_order_detail] Config error: {msg}")
        return {"success": False, "error": msg}

    except Exception as e:
        msg = f"get_order_detail failed: {e}"
        logger.error(msg, exc_info=True)
        return {"success": False, "error": msg}
```

---

## 4. XIANYU API IMPLEMENTATION

### Location
**File**: `/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/xianyu_provider/goofish_provider.py`
**Method**: `_sync_get_order_detail()`
**Lines**: 343-425

### Xianyu API Call
```python
def _sync_get_order_detail(self, order_id: str) -> dict[str, Any]:
    """
    订单详情。上游 XianyuApis 未提供此接口，使用上游 session 直接调用 h5api。
    签名函数复用上游 generate_sign（JS-based via execjs）。
    """
    # Prepare request data
    data_val = json.dumps(
        {"orderId": str(order_id)}, ensure_ascii=False, separators=(",", ":")
    )
    t = str(int(time.time()) * 1000)
    token = self._apis.session.cookies.get("_m_h5_tk", "").split("_")[0]
    sign = generate_sign(t, token, data_val)  # JS-based signing via execjs

    # Build request parameters (typical Taobao API pattern)
    params = {
        "jsv": "2.7.2",
        "appKey": "34839810",
        "t": t,
        "sign": sign,
        "v": "1.0",
        "type": "originaljson",
        "accountSite": "xianyu",
        "dataType": "json",
        "timeout": "20000",
        "api": "mtop.taobao.idle.order.detail",  # Order detail API
        "sessionOption": "AutoLoginOnly",
    }

    # Call API at https://h5api.m.goofish.com/h5/mtop.taobao.idle.order.detail/1.0/
    resp = self._apis.session.post(
        _ORDER_DETAIL_URL,
        params=params,
        data={"data": data_val},
    )
    res = resp.json()

    # Parse response
    ret = res.get("ret", [])
    if not any("SUCCESS" in r for r in ret):
        return {"success": False, "error": f"API returned: {ret}", "raw_ret": ret}

    data = res.get("data", {})
    order_info = data.get("orderInfo", {}) or data

    # Extract order fields with safe defaults
    def _get(*keys: str, default: Any = "") -> Any:
        node = order_info
        for k in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(k, default)
        return node if node is not None else default

    # Map raw status to human-readable label
    raw_status = _get("orderStatus") or _get("status")
    _ORDER_STATUS_MAP = {
        "WAIT_BUYER_PAY": "等待买家付款",
        "WAIT_SELLER_SEND_GOODS": "等待卖家发货",
        "WAIT_BUYER_CONFIRM_GOODS": "等待买家确认收货",
        "TRADE_FINISHED": "交易完成",
        "TRADE_CLOSED": "交易关闭",
        "TRADE_CLOSED_BY_TAOBAO": "交易关闭（系统）",
        "WAIT_SELLER_DECIDE": "等待卖家处理退款",
        "REFUND_SUCCESS": "退款成功",
    }
    status_label = _ORDER_STATUS_MAP.get(str(raw_status), str(raw_status))

    # Parse SKU list
    sku_list = _get("skuInfoList") or []
    sku_text = ""
    if isinstance(sku_list, list) and sku_list:
        parts = []
        for sku in sku_list:
            if isinstance(sku, dict):
                name = sku.get("name") or sku.get("specName", "")
                value = sku.get("value") or sku.get("specValue", "")
                if name:
                    parts.append(f"{name}: {value}")
        sku_text = "；".join(parts)

    return {
        "success": True,
        "order_id": str(order_id),
        "item_id": str(_get("itemId") or _get("goodsId") or ""),
        "item_title": _get("itemTitle") or _get("goodsTitle") or _get("title") or "",
        "sku": sku_text,
        "quantity": str(_get("buyAmount") or _get("quantity") or "1"),
        "amount": str(_get("actualFee") or _get("payment") or _get("totalAmount") or ""),
        "status": raw_status,
        "status_label": status_label,
        "buyer_id": str(_get("buyerId") or _get("userId") or ""),
        "buyer_nickname": _get("buyerNick") or _get("buyerName") or "",
        "create_time": str(_get("gmtCreate") or _get("createTime") or ""),
        "_raw_api_response": data,  # full raw API data for archival
    }

async def get_order_detail(self, order_id: str) -> dict[str, Any]:
    return await asyncio.get_event_loop().run_in_executor(
        None, self._sync_get_order_detail, str(order_id)
    )
```

---

## 5. DATABASE INITIALIZATION

### Location
**File**: `/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/xianyu_interceptor/conversation_store.py`
**Method**: `_ensure_table_exists()`
**Lines**: 62-238

### Initialization Code
```python
def _ensure_table_exists(self):
    """
    Ensure the conversations and agent_turns tables exist, create them if not.
    """
    # ... table creation SQL executed here ...
    
    try:
        conn = self._get_connection()
        with conn.cursor() as cursor:
            # Creates xianyu_orders table automatically on startup
            cursor.execute(create_xianyu_orders_sql)
            conn.commit()
        logger.info("Ensured 'conversations', 'xianyu_orders', 'agent_turns' tables exist")
    except Exception as e:
        logger.error(f"Failed to ensure tables exist: {e}")
```

**When**: Executed automatically when `ConversationStore` is instantiated during application startup.

---

## 6. DATA FLOW DIAGRAM

```
┌─────────────────────────────────────────────────────────────────┐
│ Xianyu Interceptor receives buyer message                       │
│ (e.g., "[我已拍下，待付款]" - "I've placed, awaiting payment")  │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ xianyu.py: xianyu_inbound() endpoint                            │
│ - Detects order-placed message                                  │
│ - Extracts order_id from raw_data (3 methods)                   │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ _handle_order_placed()                                          │
│ - Fires _record_order_detail() async (non-blocking)            │
│ - Generates rental summary from conversation history           │
│ - Logs summary to conversations table                          │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────────┐
        │ asyncio.ensure_future()                 │
        │ (Fire-and-forget)                       │
        └─────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
                    ▼                   ▼
        ┌──────────────────────┐  ┌─────────────────┐
        │ Continue processing  │  │_record_order    │
        │ (don't block)        │  │_detail()        │
        └──────────────────────┘  └────────┬────────┘
                                           │
                                           ▼
                        ┌──────────────────────────────────┐
                        │ get_order_detail()               │
                        │ Call Xianyu API                  │
                        └──────────────┬───────────────────┘
                                       │
                                       ▼
                        ┌──────────────────────────────────┐
                        │ GoofishProvider                  │
                        │ _sync_get_order_detail()         │
                        │ POST to h5api.m.goofish.com      │
                        │ Returns: order details + raw API │
                        └──────────────┬───────────────────┘
                                       │
                                       ▼
                        ┌──────────────────────────────────┐
                        │ conversation_store               │
                        │ save_order_detail()              │
                        │ INSERT ... ON DUPLICATE KEY      │
                        └──────────────┬───────────────────┘
                                       │
                                       ▼
                        ┌──────────────────────────────────┐
                        │ MySQL xianyu_orders table        │
                        │ - Order ID (unique)              │
                        │ - Order status                   │
                        │ - Order amount, SKU, quantity    │
                        │ - Buyer info                     │
                        │ - Raw API response (JSON)        │
                        └──────────────────────────────────┘
```

---

## 7. KEY IMPLEMENTATION DETAILS

### Order ID Extraction Methods (Priority Order)

1. **Method 1: From reminderUrl Query Parameter**
   - Pattern: `?orderId=12345678901234`
   - Most reliable when present

2. **Method 2: From extJson.updateKey**
   - Format: `"chat_id:order_id:seq:status:ct"`
   - Second fallback
   - Validates order_id: must be digits, length >= 10

3. **Method 3: From Nested dxCard JSON**
   - Searches for `orderId=` or `order_detail?id=` patterns
   - Last resort fallback

### Data Persistence Strategy

- **INSERT ... ON DUPLICATE KEY UPDATE**: If the same order_id appears again (e.g., after payment confirmation), the row is updated with latest status rather than creating duplicates
- **Atomic Transaction**: Each save wrapped in connection commit/rollback
- **JSON Storage**: Both parsed fields (`raw_detail`) and complete API response (`raw_api_response`) stored for full auditability

### Error Handling

- **Non-blocking**: Order recording doesn't block main message processing (fire-and-forget with `asyncio.ensure_future()`)
- **Graceful degradation**: If order_id extraction fails, logs warning but continues
- **Fallback for missing data**: If API call fails, logs warning and returns early

### Thread Safety

```python
with self._lock:
    conn = self._get_connection()
    # ... database operations ...
```
Uses threading lock to protect concurrent access from multiple async tasks

---

## 8. RELATED TABLES & REFERENCES

### conversations table
- Stores all messages in a conversation
- Foreign relationship: `chat_id` and `user_id` match `xianyu_orders`
- Contains `session_id` that may reference `agent_turns` table

### agent_turns table
- Logs LLM input/output for each agent turn
- Referenced when agent processes order-placed messages

### conversation_reviews table
- Stores operator feedback on conversation quality
- May reference the same `chat_id`

---

## 9. ORDER STATUS MAPPINGS

```python
_ORDER_STATUS_MAP = {
    "WAIT_BUYER_PAY": "等待买家付款",
    "WAIT_SELLER_SEND_GOODS": "等待卖家发货",
    "WAIT_BUYER_CONFIRM_GOODS": "等待买家确认收货",
    "TRADE_FINISHED": "交易完成",
    "TRADE_CLOSED": "交易关闭",
    "TRADE_CLOSED_BY_TAOBAO": "交易关闭（系统）",
    "WAIT_SELLER_DECIDE": "等待卖家处理退款",
    "REFUND_SUCCESS": "退款成功",
}
```

The `status_label` field stores the human-readable version for display in UI/logs.

---

## 10. FILE LOCATIONS SUMMARY

| Component | File Path | Line Range |
|-----------|-----------|-----------|
| Table Schema | `xianyu_interceptor/conversation_store.py` | 95-120 |
| Initialization | `xianyu_interceptor/conversation_store.py` | 62-238 |
| Upsert Method | `xianyu_interceptor/conversation_store.py` | 357-449 |
| Order Detection | `api/routes/xianyu.py` | 664-674 |
| Order ID Extraction | `api/routes/xianyu.py` | 235-316 |
| Fire-and-Forget Logic | `api/routes/xianyu.py` | 147-190 |
| Order Detail Fetch | `tools/xianyu/get_order_detail.py` | 1-88 |
| Xianyu API Call | `xianyu_provider/goofish_provider.py` | 343-425 |
| Order Status Query Tool | `tools/get_order_status.py` | 1-108 |

---

## 11. EXAMPLE RECORD IN xianyu_orders

```json
{
  "id": 12345,
  "chat_id": "1234567890123456",
  "user_id": "buyer_user_id_123",
  "item_id": "item_id_567",
  "order_id": "20240316123456789",
  "order_status": "WAIT_SELLER_SEND_GOODS",
  "order_status_label": "等待卖家发货",
  "order_amount": "199.00",
  "sku": "颜色: 红色；尺码: L",
  "quantity": "1",
  "buyer_nickname": "买家昵称",
  "item_title": "商品标题",
  "raw_detail": {
    "status": "WAIT_SELLER_SEND_GOODS",
    "status_label": "等待卖家发货",
    "amount": "199.00",
    "sku": "颜色: 红色；尺码: L",
    "quantity": "1",
    "buyer_nickname": "买家昵称",
    "item_title": "商品标题",
    "buyer_id": "buyer_id_123",
    "create_time": "2024-03-16 12:34:56"
  },
  "raw_api_response": {
    "orderInfo": {
      "orderId": "20240316123456789",
      "orderStatus": "WAIT_SELLER_SEND_GOODS",
      "itemTitle": "商品标题",
      "itemId": "item_id_567",
      "actualFee": "199.00",
      "buyAmount": "1",
      "buyerNick": "买家昵称",
      "skuInfoList": [
        {
          "name": "颜色",
          "value": "红色"
        },
        {
          "name": "尺码",
          "value": "L"
        }
      ]
    }
  },
  "created_at": "2024-03-16 12:34:57",
  "updated_at": "2024-03-16 12:34:57"
}
```

---

## 12. QUERY EXAMPLES

### Find all orders for a specific user
```sql
SELECT * FROM xianyu_orders 
WHERE user_id = 'buyer_user_id_123' 
ORDER BY created_at DESC;
```

### Find order by order_id (unique lookup)
```sql
SELECT * FROM xianyu_orders 
WHERE order_id = '20240316123456789';
```

### Find pending orders
```sql
SELECT * FROM xianyu_orders 
WHERE order_status IN ('WAIT_BUYER_PAY', 'WAIT_SELLER_SEND_GOODS', 'WAIT_BUYER_CONFIRM_GOODS')
ORDER BY created_at DESC;
```

### Count orders by status
```sql
SELECT order_status_label, COUNT(*) as count
FROM xianyu_orders
GROUP BY order_status_label
ORDER BY count DESC;
```

### Join with conversations to find all messages for an order
```sql
SELECT c.* 
FROM conversations c
JOIN xianyu_orders o ON c.chat_id = o.chat_id
WHERE o.order_id = '20240316123456789'
ORDER BY c.created_at ASC;
```

---

## 13. APPLICATION STARTUP FLOW

1. **FastAPI app starts** (`api/main.py`)
2. **Routes registered** - includes `xianyu` router
3. **ConversationStore instantiated** (`dependencies.py`)
   - Constructor calls `_ensure_table_exists()`
   - Creates `xianyu_orders` table if not exists
4. **Ready to receive** `/xianyu/inbound` POST requests

---

## Summary

The `xianyu_orders` table is a **fire-and-forget async-recorded** order snapshot table that captures:
- **When**: Moment buyer places an order (system message received)
- **What**: Complete order details from Xianyu API
- **How**: INSERT ... ON DUPLICATE KEY UPDATE (upsert pattern)
- **Why**: Audit trail, order status tracking, rental management

The implementation prioritizes **non-blocking operation** (async fire-and-forget) to ensure message processing latency is not affected by API calls or database writes.

