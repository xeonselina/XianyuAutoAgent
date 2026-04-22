# 历史消息捕获：调研与实现

本文档记录了闲鱼历史消息捕获功能的完整调研过程与最终实现方案。

---

## 背景与问题

在浏览器模式下，系统通过 CDP 拦截 WebSocket 消息实现实时对话。但用户打开旧对话窗口时，历史消息通过独立的 API 加载，不经过实时消息通道，因此需要单独捕获。

**目标**：在用户打开对话窗口时，自动将历史消息存入数据库，用于对话上下文还原。

---

## 调研过程

### 第一阶段：HTTP 拦截方案（最终放弃）

**思路**：通过 CDP 的 `Network.responseReceived` + `Network.loadingFinished` 事件，拦截浏览器对闲鱼后端的 HTTP 调用。

目标端点：
- `h5api.m.goofish.com` — 闲鱼 mtop 网关
- 预期 API：`idlemessage.queryMessageList`、`idlemessage.queryHistoryMessage`

实施草图（在 `cdp_interceptor.py` 中）：
```python
self._pending_history_requests = {}

async def _on_loading_finished(self, event):
    request_id = event["requestId"]
    if request_id in self._pending_history_requests:
        body = await self._cdp.send("Network.getResponseBody", {"requestId": request_id})
        # parse body ...
```

**结论**：调查后发现 HTTP API `mtop.taobao.idlemessage.pc.session.sync` 只返回每个会话的最后一条消息摘要（`session.message.summary`），**不包含完整历史记录**。该方案放弃。

---

### 第二阶段：调试日志定位 API（定向搜索）

在 `cdp_interceptor.py:943–1111` 添加了调试日志，监控所有进出 WebSocket 的消息，并在关键字匹配时打印 `[调试]` 标记的日志行。

同时在 `run_xianyu.py:103–141` 增加了 WebSocket 关键字检测，以及 `cdp_interceptor.py:962–971` 扩展 HTTP API 关键字匹配。

监控的 lwp 路径包括：
- `/r/Conversation/getByCids`
- `/r/Message/query`
- `/r/MessageManager/listUserMessages`

---

### 第三阶段：发现正确的 WebSocket API

从调试日志中（行 819、853）确认了实际使用的 API：

```
📤 [历史API请求]  /r/MessageManager/listUserMessages
📜 [历史API响应]  /r/MessageManager/listUserMessages  code=200
```

在 `cdp_interceptor.py:346–418` 增加了针对 `listUserMessages` 的专项捕获逻辑，添加 `📤 [历史API请求]` 和 `📜 [历史API响应]` 日志标记。

---

### 第四阶段：API 数据结构分析

**HTTP API 响应格式**（只含摘要，不可用）：
```json
{
  "api": "mtop.taobao.idlemessage.pc.session.sync",
  "data": {
    "sessions": [
      {
        "message": { "summary": { "...": "最后一条消息摘要" } },
        "session": { "...": "会话元数据" }
      }
    ]
  }
}
```

**三种方案对比**：

| 方案 | 原理 | 结果 |
|------|------|------|
| 仅 HTTP API | 拦截 mtop HTTP 调用 | 只含摘要，数据不完整 ❌ |
| 仅 WebSocket | 捕获 `syncPushPackage` 中的 `userMessageModels` | 包含完整历史 ✅（推荐） |
| 混合方案 | HTTP 获取会话列表 + WebSocket 获取详情 | 数据最全，复杂度高 |

**结论**：完整历史记录通过 WebSocket `syncPushPackage` 推送，字段为 `userMessageModels`。

---

## 最终实现

### 触发条件

WebSocket 响应满足以下两个条件时触发历史消息解析：
1. `code == 200`
2. 响应体包含 `userMessageModels` 字段

### 数据结构

```json
{
  "code": 200,
  "body": {
    "userMessageModels": [
      {
        "message": {
          "extension": {
            "reminderContent": "租赁套装包括手机...",
            "senderUserId": "2200687521877",
            "reminderUrl": "fleamarket://message_chat?itemId=962268817352&...",
            "reminderTitle": "光影租界"
          },
          "messageId": "3904088724982.PNM",
          "createAt": 1767431099453,
          "cid": "56122393755@goofish"
        },
        "readStatus": 2
      }
    ],
    "nextCursor": 1767411360356
  }
}
```

字段说明：
- `extension.reminderContent` — 消息正文
- `extension.senderUserId` — 发送者用户 ID
- `message.cid` — 会话 ID（格式：`{id}@goofish`）
- `message.createAt` — 消息时间戳（毫秒）
- `extension.reminderUrl` — 包含 `itemId` 的商品链接
- `body.nextCursor` — 分页游标，用于加载更早的消息

### 核心组件

**`xianyu_interceptor/history_message_parser.py`**（189 行）

`HistoryMessageParser` 类：
- 检测 `code: 200` + `userMessageModels` 字段
- 从 `extension.reminderContent` 提取消息内容
- 从 `extension.senderUserId` 确定发送方
- 从 `message.cid` 提取 `chat_id`（去掉 `@goofish` 后缀）
- 从 `extension.reminderUrl` 提取 `item_id`
- 输出 `XianyuMessage` 对象，`metadata` 中标记 `"source": "history_api"`

**集成点：`run_xianyu.py:137–162`**

历史消息检测、解析、存库均在此区块完成。

### 输出格式

```python
XianyuMessage(
    chat_id="56122393755",
    user_id="2200687521877",
    content="租赁套装包括手机...",
    item_id="962268817352",
    metadata={"source": "history_api", "message_id": "3904088724982.PNM", ...}
)
```

数据库中 `source: "history_api"` 标签用于区分历史消息与实时消息。

---

## 验证方法

1. 启动系统：`make run` + `make run-xianyu`
2. 在闲鱼网页打开任意历史对话窗口
3. 在 `run_xianyu.py` 日志中查找：`📜 [历史API响应]  /r/MessageManager/listUserMessages  code=200`
4. 在数据库中查询 `source = 'history_api'` 的记录，确认消息已存入
5. 查看 `nextCursor` 字段值，确认分页游标已提取（可用于后续翻页实现）
