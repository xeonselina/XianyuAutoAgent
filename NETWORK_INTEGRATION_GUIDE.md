# XianyuAutoAgent 网络交互集成指南

**快速参考** - 适用于开发者和集成者

---

## 📋 快速查表

### HTTP 端点

| 功能 | 方法 | 路由 | 来源 | 响应 |
|------|------|------|------|------|
| 健康检查 | GET | `/health` | 拦截器 | `{"status": "ok"}` |
| 消息入站 | POST | `/xianyu/inbound` | 拦截器 | `{"reply": "..."}` |
| 更新Cookie | POST | `/xianyu/update-cookies` | 拦截器 | `{"success": true, "user_id": "..."}` |
| AI聊天 | POST | `/chat` | 内部/外部 | `{"response": "..."}` |
| 聊天流 | POST | `/chat/stream` | 内部/外部 | Server-Sent Events |

### WebSocket 连接

| 服务 | URL | 目的 | 认证 |
|------|-----|------|------|
| Xianyu | `wss://wss-goofish.dingtalk.com/` | 消息接收 | Cookie + Headers |
| 钉钉 | TBD | 群消息 | Token |

---

## 🔧 配置清单

### 环境变量 (`.env`)

```bash
# Xianyu认证
XIANYU_COOKIE="unb=xxx; tb_token=yyy; ..."

# 服务配置
AGENT_SERVICE_URL=http://localhost:8000
BROWSER_HEADLESS=false
BROWSER_VIEWPORT_WIDTH=1280
BROWSER_VIEWPORT_HEIGHT=720

# AI配置
MODEL_NAME=claude-3-5-sonnet
SELLER_USER_ID=<卖家ID>

# 可选
BROWSER_DEBUG_PORT=9222
BROWSER_PROXY=socks5://proxy:port
```

### 启动步骤

```bash
# 1. 启动API服务
cd /Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu
uvicorn api.main:app --host 0.0.0.0 --port 8000

# 2. 在另一个终端启动拦截器
python run_xianyu.py

# 3. 在浏览器中打开闲鱼并点击进入消息中心
# 拦截器会自动检测WebSocket连接
```

---

## 🌍 网络请求流程

### 消息处理流程

```
1️⃣ 浏览器(Xianyu)
   ↓ WebSocket消息
2️⃣ CDP拦截器 (Network.webSocketFrameReceived)
   ↓ JSON负载
3️⃣ 消息编解码 (XianyuMessageCodec)
   ↓ 标准化数据
4️⃣ HTTP POST /xianyu/inbound
   ↓ XianyuInboundRequest
5️⃣ FastAPI处理
   ↓ 业务逻辑检查
6️⃣ AI Agent调用 (/chat)
   ↓ Claude API
7️⃣ HTTP 200 with reply
   ↓ BrowserTransport
8️⃣ 发送回复到Xianyu
```

### 错误重试机制

```python
# HTTP重试配置（httpx + Tenacity）
最多重试: 4次
退避策略: 指数退避
  第1次: 1秒
  第2次: 2秒
  第3次: 4秒
  第4次: 8秒 (最多15秒)

可重试错误:
  ✅ ConnectError      - 连接失败
  ✅ PoolTimeout       - 连接池超时
  ✅ ReadTimeout       - 读取超时
  ✅ HTTP 500/502/503/504 - 服务端错误

不可重试错误:
  ❌ HTTP 4xx - 客户端错误
  ❌ 其他异常 - 需要人工处理
```

---

## 🔐 认证和授权

### Cookie 流程

```
1. 初始化
   ├─ 从.env读取XIANYU_COOKIE
   └─ 解析为Dict[str, str]

2. 浏览器注入
   ├─ trans_cookies(cookie_str) → List[Dict]
   └─ context.add_cookies(cookies_list)

3. 运行时更新
   ├─ 每30分钟检查一次
   ├─ extract_cookies() → 新Cookie字符串
   └─ POST /xianyu/update-cookies

4. Provider初始化
   ├─ GoofishProvider(cookies_str)
   ├─ 自动提取user_id (unb字段)
   └─ 创建upstream XianyuApis实例
```

### 用户识别

```python
# 关键字段

卖家ID:
  - 来源: Cookie中的"unb"字段
  - 用途: 区分消息方向（自己/买家）
  - 设置: settings.SELLER_USER_ID 或自动提取

用户ID (Message):
  - 来源: WebSocket消息的user_id
  - 用途: 标识消息发送者
  - 使用: 数据库记录、会话管理

加密UID:
  - 来源: WebSocket消息的encrypted_uid
  - 用途: 隐私保护，记录到数据库
  - 映射: uid_mapper.record_uid_mapping(user_id, encrypted_uid)
```

---

## 📡 WebSocket 拦截详解

### CDP 监控启用流程

```python
# 1. 启用Network域
await cdp_session.send("Network.enable")

# 2. 订阅WebSocket事件
cdp_session.on("Network.webSocketCreated", callback)
cdp_session.on("Network.webSocketFrameReceived", callback)
cdp_session.on("Network.webSocketFrameSent", callback)
cdp_session.on("Network.webSocketClosed", callback)

# 3. 启用Fetch域（底层拦截）
await cdp_session.send("Fetch.enable", {
    "patterns": [
        {"urlPattern": "*wss://*", "requestStage": "Request"},
        {"urlPattern": "*ws://*", "requestStage": "Request"}
    ]
})
cdp_session.on("Fetch.requestPaused", callback)

# 4. 监听HTTP响应（历史消息）
cdp_session.on("Network.responseReceived", callback)
cdp_session.on("Network.loadingFinished", callback)

# 5. 启用Runtime（JavaScript执行）
await cdp_session.send("Runtime.enable")
```

### Xianyu WebSocket检测

```python
# 闲鱼服务器地址
XIANYU_SERVERS = [
    "wss-goofish.dingtalk.com",    # 主服务器
    "msgacs.m.taobao.com",          # 备用服务器
    "wss.goofish.com"               # 其他
]

# 检测逻辑
if any(domain in websocket_url for domain in XIANYU_SERVERS):
    # ✅ 这是Xianyu WebSocket，开始拦截
    self.websocket_id = request_id
else:
    # ❌ 其他WebSocket，忽略
    pass
```

### 多页面监听机制

```python
# ⚠️ 重要：必须监听多个页面

# 1. 监听所有已存在页面
for page in browser_context.pages:
    await setup_page_monitoring(page)

# 2. 监听新打开的页面
browser_context.on("page", async def on_new_page(page):
    await setup_page_monitoring(page)
)

# 3. 监听页面导航（SPA路由刷新）
page.on("framenavigated", async def on_navigation(frame):
    if frame == page.main_frame:
        await setup_page_monitoring(page)  # 重新设置
)
```

---

## 📊 性能和调试

### 启用详细日志

```python
# 日志级别
DEBUG - 详细的事件日志
INFO  - 关键事件（消息接收、API调用等）
WARNING - 可恢复的错误（重试、超时）
ERROR - 严重错误（API失败、拦截失败）

# 查看日志
tail -f logs/xianyu_interceptor.log

# 搜索特定事件
grep "WebSocket" logs/xianyu_interceptor.log
grep "❌" logs/xianyu_interceptor.log  # 错误
grep "✅" logs/xianyu_interceptor.log  # 成功
```

### 性能指标

```python
# HTTP客户端指标
client.metrics.get_metrics() → HTTPClientMetrics {
    total_requests: int,
    successful_requests: int,
    failed_requests: int,
    average_response_time: float,  # 秒
    is_healthy: bool,
    last_health_check: float
}

# WebSocket指标
interceptor.websocket_id: str  # 活跃WebSocket ID
interceptor.message_count: int  # 已接收的消息数
```

### 常见问题排查

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| WebSocket未检测到 | 未打开消息中心 | 在浏览器中点击进入消息中心 |
| API连接失败 | 服务未启动 | 检查 `uvicorn api.main:app` 是否运行 |
| Cookie已过期 | 长时间未更新 | 重新登录浏览器或手动更新Cookie |
| 消息解码失败 | 消息格式未知 | 检查日志中的消息结构 |
| 多页面监听丢失 | 事件监听器未设置 | 确保framenavigated事件已注册 |

---

## 🔄 集成检查清单

- [ ] `.env` 文件配置了 `XIANYU_COOKIE`
- [ ] `.env` 文件配置了 `SELLER_USER_ID`
- [ ] API服务正在运行（端口8000）
- [ ] 拦截器正在运行（`python run_xianyu.py`）
- [ ] 浏览器已打开Xianyu消息中心
- [ ] 日志中看到 `✅ WebSocket 连接已建立`
- [ ] 发送测试消息，API返回 HTTP 200
- [ ] 消息已记录到数据库（`conversations` 表）
- [ ] AI回复已通过Xianyu发送

---

## 📞 常用命令

```bash
# 查看日志
tail -f ai_kefu/logs/xianyu_interceptor.log

# 检查API健康状态
curl http://localhost:8000/health

# 查看CDP调试端口
# 浏览器访问: http://localhost:9222

# 提取当前浏览器Cookie
# 在浏览器开发者工具中：
# 复制 document.cookie

# 测试API端点
curl -X POST http://localhost:8000/xianyu/inbound \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "test",
    "user_id": "buyer_123",
    "content": "你好，商品还在吗？"
  }'
```

---

## 📚 相关文档

- `PROJECT_DETAILED_EXPLORATION.md` - 完整项目结构分析
- `PROJECT_CODE_SNIPPETS.md` - 代码实现详解
- `ai_kefu/ARCHITECTURE_SUMMARY.md` - 系统架构
- `ai_kefu/README.md` - 项目README

---

**最后更新:** 2026年5月4日

