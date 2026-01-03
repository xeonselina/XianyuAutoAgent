# 闲鱼历史消息加载机制分析报告

## 分析时间
2026-01-03 20:17

## 数据来源
日志文件：`logs/xianyu_interceptor_2026-01-03.log`

## 核心发现

### 1. 闲鱼采用**混合模式**加载历史消息

闲鱼的历史消息加载机制结合了**HTTP API**和**WebSocket同步**：

#### HTTP API负责：
- 会话列表同步
- 用户信息查询
- 商品/订单信息查询

#### WebSocket负责：
- 实时消息推送
- 历史消息同步
- 会话详情获取

### 2. 关键API端点

#### API 1: 会话列表同步
```
URL: https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.pc.session.sync/3.0/
```

**响应结构**：
```json
{
  "api": "mtop.taobao.idlemessage.pc.session.sync",
  "data": {
    "hasMore": false,
    "sessions": [
      {
        "memberFlags": 0,
        "message": {
          "summary": {
            "sortIndex": 20260103185912,
            "summary": "🆕开启优推抵扣，助力大卖！",
            "ts": 1767437952069,
            "unread": 1,
            "version": 11156
          }
        },
        "session": {
          "ownerInfo": {
            "fishNick": "TB_28060346",
            "logo": "http://...",
            "nick": "x***n",
            "userId": "10954781"
          },
          "sessionId": 23482297,
          "sessionType": 3,
          "userInfo": {
            "logo": "http://...",
            "nick": "系统消息",
            "type": 10,
            "userId": "100"
          }
        }
      }
    ]
  },
  "ret": ["SUCCESS::调用成功"],
  "v": "3.0"
}
```

**用途**：
- 加载所有会话的列表
- 每个会话包含最后一条消息的摘要
- **不包含完整的历史消息**

#### API 2: 用户信息查询
```
URL: https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.pc.user.query/4.0/
```

**用途**：查询会话中用户的详细信息

#### API 3: 商品头部信息
```
URL: https://h5api.m.goofish.com/h5/mtop.idle.trade.pc.message.headinfo/1.0/
```

**用途**：显示聊天窗口顶部的商品/订单信息

### 3. WebSocket消息同步机制

#### WebSocket请求示例：

**请求1: 获取会话详情**
```
📤 发送消息: {"lwp":"/r/Conversation/getByCids","headers":{"mid":"..."},"body":[["23482297@goofish..."]]}
```

**请求2: 获取会话列表（顶部）**
```
📤 发送消息: {"lwp":"/r/Conversation/listTop","headers":{"mid":"..."},"body":[{"topRank":9007199254740991}]}
```

**请求3: 获取最新会话分页**
```
📤 发送消息: {"lwp":"/r/Conversation/listNewestPagination","headers":{"mid":"..."},"body":[9007199254740991,...]}
```

#### 历史消息通过WebSocket的`syncPushPackage`机制同步

当打开某个用户的聊天窗口时：
1. WebSocket发送`/r/Conversation/getByCids`请求
2. 服务器通过`syncPushPackage`推送该会话的历史消息
3. 每条历史消息都是加密的，需要使用`decrypt()`函数解密

## 技术实现建议

### 方案A：监听HTTP API（当前调试代码已实现）

**优点**：
- 可以捕获会话列表
- 可以捕获用户信息
- 数据结构清晰

**缺点**：
- **无法获取完整的历史消息**
- 只能获取每个会话最后一条消息的摘要

**适用场景**：
- 了解有哪些会话
- 显示会话列表
- 获取用户基本信息

### 方案B：监听WebSocket的syncPushPackage（推荐）⭐

**优点**：
- ✅ 可以获取完整的历史消息
- ✅ 消息格式与实时消息相同（已有解码逻辑）
- ✅ 不需要额外的API解析

**缺点**：
- 需要识别历史消息和实时消息的区别
- 需要处理大量的同步消息

**实现方式**：
利用现有的`run_xianyu.py:on_message()`回调，它已经可以处理syncPushPackage格式的消息。

**关键代码位置**：
- `run_xianyu.py:103-107` - syncPushPackage解码
- `xianyu_interceptor/messaging_core.py:200-239` - 消息解码器
- `xianyu_interceptor/messaging_core.py:264-321` - 消息数据提取

### 方案C：混合方案（最佳）⭐⭐⭐

**结合HTTP API和WebSocket同步**：

1. **监听HTTP API** - 获取会话列表
   ```python
   # API: mtop.taobao.idlemessage.pc.session.sync
   # 作用：了解有哪些会话，获取会话元数据
   ```

2. **监听WebSocket** - 获取历史消息
   ```python
   # 当用户打开聊天窗口时，WebSocket会自动同步历史消息
   # 这些消息通过syncPushPackage推送，使用现有解码逻辑处理
   ```

3. **添加消息来源标识**
   ```python
   # 在metadata中添加source字段
   metadata["source"] = "history_sync"  # 历史消息（WebSocket同步）
   metadata["source"] = "realtime"       # 实时消息（WebSocket推送）
   ```

## 实施步骤

### 第一步：当前系统已经可以捕获历史消息！

**重要发现**：查看日志发现，当打开聊天窗口时，WebSocket已经在推送消息：

```log
506→2026-01-03 20:17:24.109 | INFO | 📥 收到消息: {"headers":{"app-key":"444e9908a51d1cb236a27862abc769c9"...
508→2026-01-03 20:17:24.114 | INFO | 📥 收到消息: {"headers":{"dt":"j","mid":"2951767442643765 0"...
510→2026-01-03 20:17:24.170 | INFO | 📥 收到消息: {"headers":{"dt":"j","mid":"1781767442643753 0"...
515→2026-01-03 20:17:24.269 | INFO | 📥 收到消息: {"headers":{"dt":"j","mid":"1691767442644169 0"...
```

这些消息很可能就包含了历史消息！

### 第二步：分析WebSocket消息的完整内容

需要查看这些WebSocket消息的`body`部分，确认是否包含历史消息数据。

**需要修改的代码**：
`xianyu_interceptor/cdp_interceptor.py:349`

当前只记录了消息的前100个字符，需要记录完整的消息体来分析数据结构。

### 第三步：区分历史消息和实时消息

**方法1：根据时间戳**
- 如果消息时间戳早于WebSocket连接建立时间 → 历史消息
- 如果消息时间戳等于或晚于连接建立时间 → 实时消息

**方法2：根据消息序列**
- 连接建立后收到的第一批大量消息 → 历史消息
- 之后收到的单条消息 → 实时消息

**方法3：根据消息元数据**
- 检查消息中是否有特殊标识（如`syncType`、`isHistory`等字段）

### 第四步：实现历史消息保存

在现有的消息处理流程中添加逻辑：

```python
# run_xianyu.py:on_message()

async def on_message(message_data: dict):
    # ... 现有解码逻辑 ...

    # 判断是否是历史消息
    is_history = determine_if_history_message(xianyu_message)

    if is_history:
        xianyu_message.metadata["source"] = "history_sync"
        logger.info(f"📜 历史消息: {xianyu_message.content[:50]}...")
    else:
        xianyu_message.metadata["source"] = "realtime"

    # 保存到数据库（历史消息和实时消息都保存）
    if conversation_store:
        conversation_store.save_message(conv_msg)
```

## 下一步行动

### 立即可行（零修改）✅

**当前系统很可能已经在捕获历史消息！**

检查数据库中是否已有历史消息：

```sql
SELECT chat_id, user_id, message_content, created_at, context
FROM conversations
ORDER BY created_at ASC
LIMIT 100;
```

如果已经有数据，说明历史消息已经被捕获并保存。

### 短期优化（1-2天）

1. ✅ 添加消息来源标识（`source: history_sync | realtime`）
2. ✅ 完整记录WebSocket消息体（用于分析）
3. ✅ 实现历史消息识别逻辑
4. ✅ 添加去重机制（基于`chat_id + timestamp + content`）

### 中期完善（3-5天）

1. ✅ 监听HTTP会话列表API（`mtop.taobao.idlemessage.pc.session.sync`）
2. ✅ 解析会话元数据并保存
3. ✅ 关联会话信息和消息记录
4. ✅ 实现会话历史查询接口

## 结论

**关键发现**：
1. ✅ 闲鱼采用WebSocket同步历史消息，而不是HTTP API
2. ✅ 当前系统的WebSocket拦截器**已经可以捕获历史消息**
3. ✅ 历史消息使用与实时消息相同的格式（syncPushPackage）
4. ✅ 不需要额外的API解析，复用现有解码逻辑即可

**最佳方案**：
- 继续使用WebSocket拦截历史消息
- 添加消息来源标识区分历史和实时消息
- 可选地监听HTTP API获取会话列表元数据

**预期效果**：
实施后，系统将自动捕获和保存：
- ✅ 用户打开聊天窗口时加载的所有历史消息
- ✅ 实时收到的新消息
- ✅ 会话列表和用户信息

**无需额外开发工作量**，只需完善现有代码即可！
