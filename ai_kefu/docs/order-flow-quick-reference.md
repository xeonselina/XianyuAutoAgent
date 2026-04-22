# 订单流程快速参考

## 🎯 核心触发条件

**订单进入 `xianyu_orders` 表的唯一条件**:

```
消息内容 === "[我已拍下，待付款]" 或 "[我已付款，等待你发货]"
且
消息类型 === CHAT
且
消息不在 ignore_patterns 表中
```

---

## 📍 三道防线位置

### 防线 1: 消息分类
- **文件**: `xianyu_interceptor/messaging_core.py`
- **行号**: 501-511 (`_is_order_message`)
- **问题**: ORDER 消息被分类为不同类型，无法进入后续流程
- **检查日志**: `"判断是否为订单消息"` 或 `"Skipping non-chat message"`

### 防线 2: 传输层过滤
- **文件**: `xianyu_interceptor/message_handler.py`
- **行号**: 110-113
- **过滤条件**: `if message.message_type != XianyuMessageType.CHAT: return None`
- **问题**: ORDER 类型消息永远不会被POST到 `/xianyu/inbound`

### 防线 3: 业务层过滤
- **文件**: `api/routes/xianyu.py`
- **行号**: 566-572
- **过滤条件**: `ignore_pattern_store.should_ignore(req.content)`
- **问题**: 内容匹配 ignore_patterns 表则直接返回

---

## 🔍 快速诊断

### 问题: 订单没有被保存到 xianyu_orders

**检查清单**:

```bash
# 1️⃣ 检查 ignore_patterns 表
mysql> SELECT * FROM ignore_patterns WHERE active = TRUE;
# 查找是否包含 "[我已拍下" 或 "[我已付款"

# 2️⃣ 查看消息分类日志
grep "Skipping non-chat message" app.log | grep -i order

# 3️⃣ 查看业务层过滤日志
grep "ignored by pattern" app.log

# 4️⃣ 检查订单处理日志
grep "📦 用户拍下商品\|_handle_order_placed\|\[order_id\]" app.log

# 5️⃣ 检查订单表
mysql> SELECT COUNT(*) FROM xianyu_orders;
mysql> SELECT * FROM xianyu_orders WHERE chat_id = '<TARGET_CHAT_ID>';
```

---

## 📊 关键数据流

```
XianyuMessage
    ↓
[messaging_core.py:242] classify_message()
    ├─ CHAT → ✓ 继续
    └─ ORDER → ✗ 停止
    ↓
[message_handler.py:110] 检查 message_type == CHAT
    ├─ YES → POST /xianyu/inbound
    └─ NO → 返回 None
    ↓
[xianyu.py:566] should_ignore() 检查 ignore_patterns
    ├─ 匹配 → return None ✗
    └─ 不匹配 → 继续
    ↓
[xianyu.py:97] _is_order_placed_message()
    ├─ YES → _handle_order_placed()
    │   ├─ 提取 order_id
    │   ├─ _record_order_detail()
    │   └─ INSERT xianyu_orders
    └─ NO → AI Agent 处理
```

---

## 🛠️ 快速修复

### 问题: Ignore Pattern 阻止了订单消息

**解决方案**:

```sql
-- 找到有问题的 pattern
SELECT id, pattern FROM ignore_patterns 
WHERE pattern LIKE '%拍下%' OR pattern LIKE '%付款%';

-- 禁用它
UPDATE ignore_patterns SET active = FALSE WHERE id = <ID>;

-- 或直接删除
DELETE FROM ignore_patterns WHERE id = <ID>;
```

### 问题: 订单 ID 无法提取

**检查三个提取方法的优先级** (xianyu.py:262-308):

1. ✓ **reminderUrl** 中的 `?orderId=<id>`
2. ✓ **extJson.updateKey** 格式: `<chat>:<order_id>:<seq>:<status>`
3. ✓ **Nested dxCard URL** 中的 `order_detail?id=<id>`

查看日志:
```
grep "\[order_id\] 从.*提取" app.log
```

---

## 📋 表结构速查

### xianyu_orders 表

| 字段 | 类型 | 说明 |
|-----|------|------|
| `id` | BIGINT | 主键 |
| `chat_id` | VARCHAR | 闲鱼聊天ID |
| `user_id` | VARCHAR | 买家ID |
| `order_id` | VARCHAR | **订单号 (UNIQUE)** |
| `order_status` | VARCHAR | 订单状态码 |
| `order_status_label` | VARCHAR | 人类可读状态 |
| `order_amount` | VARCHAR | 支付金额 |
| `sku` | TEXT | SKU信息 |
| `quantity` | VARCHAR | 购买数量 |
| `buyer_nickname` | VARCHAR | 买家昵称 |
| `item_title` | TEXT | 商品标题 |
| `raw_detail` | JSON | 完整订单字段 |
| `raw_api_response` | JSON | Xianyu API原始响应 |
| `created_at` | TIMESTAMP | 创建时间 |
| `updated_at` | TIMESTAMP | 更新时间 |

### ignore_patterns 表

| 字段 | 类型 | 说明 |
|-----|------|------|
| `id` | INT | 主键 |
| `pattern` | VARCHAR | **要忽略的消息 (UNIQUE)** |
| `description` | VARCHAR | 描述 |
| `active` | BOOLEAN | 是否启用 |
| `created_at` | DATETIME | 创建时间 |
| `updated_at` | DATETIME | 更新时间 |

---

## 🔗 代码位置导航

| 功能 | 文件 | 行号 |
|-----|------|------|
| 触发关键词定义 | xianyu.py | 73-76 |
| 触发条件检查 | xianyu.py | 97-100 |
| 订单处理函数 | xianyu.py | 235-381 |
| 订单记录函数 | xianyu.py | 147-189 |
| 消息分类逻辑 | messaging_core.py | 242-261 |
| 传输层过滤 | message_handler.py | 110-113 |
| 业务层过滤 | xianyu.py | 566-572 |
| Ignore 检查函数 | ignore_pattern_store.py | 154-174 |
| 表创建 SQL | conversation_store.py | 95-120 |
| 订单保存函数 | conversation_store.py | 357-449 |

---

## ⚡ 测试订单流程

### 手动触发订单

```bash
curl -X POST http://localhost:8000/xianyu/inbound \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "test_chat_123",
    "user_id": "test_user_456",
    "content": "[我已拍下，待付款]",
    "item_id": "test_item_789",
    "item_title": "测试商品",
    "user_nickname": "测试用户",
    "is_self_sent": false,
    "raw_data": {
      "1": {
        "10": {
          "reminderUrl": "https://example.com?orderId=12345&itemId=test_item_789"
        }
      }
    }
  }'
```

**预期输出**: HTTP 200, 返回 `{"reply": "...租机摘要..."}` 或 AI 回复

### 查看处理结果

```sql
-- 查看订单是否被保存
SELECT * FROM xianyu_orders 
WHERE chat_id = 'test_chat_123' 
ORDER BY created_at DESC LIMIT 1;

-- 查看聊天记录
SELECT * FROM conversations 
WHERE chat_id = 'test_chat_123' 
ORDER BY created_at DESC LIMIT 10;
```

---

## 🚨 常见问题

### Q: 为什么订单消息没有到达 xianyu_orders?

**A**: 检查三个过滤点 (优先级从高到低):

1. **消息分类错误** → 查看日志 `"Skipping non-chat message"`
2. **Ignore Pattern 阻止** → 查询 `ignore_patterns` 表
3. **触发条件不满足** → 检查消息内容是否精确匹配

### Q: Ignore Pattern 对订单有什么影响?

**A**: 如果订单触发关键词在 ignore_patterns 中:
- ✗ 订单消息被完全过滤
- ✗ `_handle_order_placed()` 永不执行
- ✗ 订单永不进入 xianyu_orders
- ✓ 建议定期检查 ignore_patterns

### Q: ORDER 和 CHAT 消息的区别?

**A**: 使用完全不同的 JSON 字段结构:

| | CHAT | ORDER |
|---|------|-------|
| **JSON路径** | `message["1"]["10"]["reminderContent"]` | `message["3"]["redReminder"]` |
| **中继** | ✓ 由 message_handler 中继 | ✗ 被过滤 |
| **业务处理** | ✓ 进入 xianyu.py | ✗ 无法处理 |

---

## 📞 联系支持

如需调试订单流程问题:

1. 启用详细日志 (设置 LOG_LEVEL=DEBUG)
2. 收集相关日志 grep 结果
3. 提供 chat_id 和时间范围
4. 查询对应的 ignore_patterns 和 xianyu_orders 记录

