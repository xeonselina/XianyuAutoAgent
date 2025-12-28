# 技术研究报告: 闲鱼拦截器 HTTP 集成

**日期**: 2025-12-24  
**项目**: 002-xianyu-agent-http-integration

---

## 1. 闲鱼消息格式分析

### 决策: 保留现有解析逻辑，转换为 Agent API 格式

### 理由

通过分析 `cdp_interceptor.py` 和 `messaging_core.py`，闲鱼消息已经有完整的解析逻辑：

**消息类型**:
- `CHAT`: 用户聊天消息
- `ORDER`: 订单状态更新
- `TYPING`: 输入状态
- `SYSTEM`: 系统通知

**已提取字段**:
```python
Message(
    message_type=MessageType.CHAT,
    chat_id="闲鱼对话ID",
    user_id="买家用户ID",
    item_id="商品ID",
    content="消息内容",
    timestamp=1234567890000  # 毫秒时间戳
)
```

**转换为 Agent API 格式**:
```python
# 闲鱼 Message → Agent ChatRequest
{
    "query": message.content,
    "session_id": get_or_create_agent_session(message.chat_id),
    "user_id": message.user_id,
    "context": {
        "conversation_id": message.chat_id,
        "source": "xianyu",
        "item_id": message.item_id,
        "timestamp": message.timestamp
    }
}
```

### 实施要点

1. 保留 `XianyuMessageCodec` 类用于消息解析
2. 新增 `message_converter.py` 转换模块
3. 在 `messaging_core.py` 中集成 HTTP 客户端调用

---

## 2. 会话映射策略

### 决策: 使用内存映射 + Redis（可选）

### 理由

**需求分析**:
- 闲鱼 chat_id 是唯一标识
- AI Agent 使用 UUID session_id
- 需要双向映射: `chat_id ↔ session_id`
- 会话生命周期: 通常几分钟到几小时

**方案选择**:

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| 内存映射 | 快速，简单 | 重启丢失 | 单机，低并发 |
| Redis | 持久化，支持分布式 | 需要额外服务 | 高并发，多实例 |
| SQLite | 持久化，无额外依赖 | 读写性能较低 | 低并发，需持久化 |

**推荐**: 内存映射为默认，支持 Redis 扩展

### 实施要点

```python
class SessionMapper:
    """会话映射管理器"""
    
    def __init__(self, storage_type: str = "memory"):
        if storage_type == "redis":
            self.storage = RedisSessionMapper()
        else:
            self.storage = MemorySessionMapper()
    
    def get_or_create_agent_session(
        self,
        chat_id: str,
        user_id: str
    ) -> str:
        """获取或创建 Agent session ID"""
        session_id = self.storage.get(chat_id)
        if not session_id:
            session_id = str(uuid.uuid4())
            self.storage.set(chat_id, session_id, user_id)
        return session_id
    
    def get_chat_id(self, session_id: str) -> Optional[str]:
        """反向查找 chat_id"""
        return self.storage.reverse_get(session_id)
    
    def cleanup_expired(self, ttl: int = 3600):
        """清理过期映射"""
        self.storage.cleanup(ttl)
```

**Redis 数据结构**:
```
xianyu_session:chat_id → agent_session_id
xianyu_session:reverse:agent_session_id → chat_id
xianyu_session:meta:{chat_id} → {user_id, created_at, last_active}
```

---

## 3. HTTP 客户端设计

### 决策: 使用 httpx 异步客户端

### 理由

**对比**:
- `requests`: 同步，简单，但会阻塞
- `httpx`: 异步，支持 HTTP/2，API 类似 requests
- `aiohttp`: 异步，但 API 不同

**选择 httpx 的原因**:
1. 与 FastAPI 生态一致
2. 支持同步和异步
3. API 熟悉（类似 requests）
4. 支持流式响应（SSE）

### 实施要点

```python
class AgentClient:
    """AI Agent HTTP 客户端"""
    
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url
        self.client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout
        )
    
    async def send_message(
        self,
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        context: Optional[Dict] = None
    ) -> AgentResponse:
        """发送消息到 AI Agent（同步模式）"""
        try:
            response = await self.client.post(
                "/chat",
                json={
                    "query": query,
                    "session_id": session_id,
                    "user_id": user_id,
                    "context": context or {}
                }
            )
            response.raise_for_status()
            return AgentResponse(**response.json())
        except httpx.HTTPError as e:
            logger.error(f"Agent API error: {e}")
            raise AgentAPIError(str(e))
    
    async def stream_message(
        self,
        query: str,
        session_id: Optional[str] = None
    ) -> AsyncIterator[str]:
        """流式接收 Agent 响应"""
        async with self.client.stream(
            "POST",
            "/chat/stream",
            json={"query": query, "session_id": session_id}
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    if data.get("type") == "chunk":
                        yield data["text"]
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            response = await self.client.get("/health")
            return response.status_code == 200
        except:
            return False
```

**错误处理**:
- 重试机制: 最多 3 次，指数退避
- 超时处理: 默认 10 秒
- 降级策略: Agent 不可用时记录日志，不影响主流程

---

## 4. 降级策略

### 决策: 记录日志 + 跳过回复

### 理由

**场景分析**:
1. Agent 服务不可用（网络、服务宕机）
2. Agent 响应超时
3. Agent 返回错误（500）

**降级方案**:

| 策略 | 优点 | 缺点 | 推荐 |
|------|------|------|------|
| 预设回复 | 用户有反馈 | 可能不相关 | ❌ |
| 跳过回复 | 简单，不影响系统 | 用户无响应 | ✅ |
| 转人工 | 保证服务质量 | 需要人工在线 | 可选 |
| 队列重试 | 最终一致 | 延迟高 | 可选 |

**推荐**: 跳过回复 + 日志告警

### 实施要点

```python
async def handle_xianyu_message(message: Message):
    """处理闲鱼消息"""
    try:
        # 1. 获取 Agent session
        session_id = session_mapper.get_or_create(
            message.chat_id,
            message.user_id
        )
        
        # 2. 调用 Agent API
        response = await agent_client.send_message(
            query=message.content,
            session_id=session_id,
            user_id=message.user_id,
            context={
                "conversation_id": message.chat_id,
                "item_id": message.item_id
            }
        )
        
        # 3. 发送回复到闲鱼
        await transport.send_message(
            chat_id=message.chat_id,
            user_id=message.user_id,
            content=response.response
        )
        
    except AgentAPIError as e:
        # 降级: 记录日志，不回复
        logger.error(
            f"Agent API failed for chat {message.chat_id}: {e}"
        )
        # 可选: 发送告警通知
        # alert_manager.send_alert("agent_api_down", str(e))
        
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
```

**监控指标**:
- Agent API 可用率
- 响应时间（P50, P95, P99）
- 错误率
- 降级次数

---

## 5. 手动模式管理

### 决策: 保留现有逻辑，增加 Agent 状态同步

### 理由

现有 `messaging_core.py` 已实现手动模式切换：
- 关键词触发: "。"
- 超时自动恢复: 默认 1 小时
- 状态存储: 内存

**需要调整**:
- 手动模式下，不调用 Agent API
- 恢复自动模式时，同步会话状态

### 实施要点

```python
class ManualModeManager:
    """手动模式管理"""
    
    def __init__(self):
        self.manual_sessions = {}  # {chat_id: timestamp}
    
    def toggle_manual_mode(self, chat_id: str) -> bool:
        """切换手动模式"""
        if chat_id in self.manual_sessions:
            # 退出手动模式
            del self.manual_sessions[chat_id]
            logger.info(f"Chat {chat_id} exited manual mode")
            return False
        else:
            # 进入手动模式
            self.manual_sessions[chat_id] = time.time()
            logger.info(f"Chat {chat_id} entered manual mode")
            return True
    
    def is_manual_mode(self, chat_id: str, timeout: int = 3600) -> bool:
        """检查是否手动模式"""
        if chat_id not in self.manual_sessions:
            return False
        
        # 检查超时
        elapsed = time.time() - self.manual_sessions[chat_id]
        if elapsed > timeout:
            del self.manual_sessions[chat_id]
            logger.info(f"Chat {chat_id} manual mode timed out")
            return False
        
        return True
```

**集成到消息处理**:
```python
async def process_message(message: Message):
    # 检查是否切换关键词
    if message.content.strip() == "。":
        is_manual = manual_mode_manager.toggle_manual_mode(
            message.chat_id
        )
        mode = "手动" if is_manual else "自动"
        await send_reply(
            message.chat_id,
            message.user_id,
            f"已切换到{mode}模式"
        )
        return
    
    # 检查是否手动模式
    if manual_mode_manager.is_manual_mode(message.chat_id):
        logger.info(f"Chat {message.chat_id} in manual mode, skipping AI")
        return
    
    # 调用 AI Agent
    await handle_with_agent(message)
```

---

## 6. 代码重构计划

### 文件迁移

**保留并移动到 `xianyu_interceptor/`**:
1. `browser_controller.py` → 浏览器控制（无需修改）
2. `cdp_interceptor.py` → CDP 拦截（精简，移除旧 Agent 调用）
3. `messaging_core.py` → 消息解析（精简，集成 HTTP 客户端）

**新增文件**:
1. `http_client.py` → Agent HTTP 客户端
2. `session_mapper.py` → 会话映射管理
3. `config.py` → 配置管理
4. `message_converter.py` → 消息格式转换

**归档到 `legacy/`**:
1. `XianyuAgent.py` → 旧 AI 逻辑
2. `XianyuApis.py` → 旧 API 包装（部分可能仍需要）
3. `context_manager.py` → 旧上下文管理（可能仍需要）

### 依赖更新

**新增依赖**:
```txt
httpx>=0.25.0          # HTTP 客户端
redis>=5.0.0           # Redis 会话映射（可选）
```

**环境变量**:
```bash
# 新增配置
AGENT_SERVICE_URL=http://localhost:8000
SESSION_MAPPER_TYPE=memory  # or redis
REDIS_URL=redis://localhost:6379  # 如果使用 Redis

# 保留配置
COOKIES_STR=...
USE_BROWSER_MODE=true
BROWSER_HEADLESS=false
TOGGLE_KEYWORDS=。
MANUAL_MODE_TIMEOUT=3600
```

---

## 7. 性能优化建议

### 异步处理

**当前问题**: 同步阻塞可能影响消息处理

**优化方案**:
1. 使用 `asyncio` 异步处理
2. 消息队列: 拦截 → 队列 → 处理 → 回复
3. 并发限制: 控制同时处理的对话数

```python
import asyncio
from asyncio import Queue

class MessageProcessor:
    def __init__(self, max_workers: int = 10):
        self.queue = Queue()
        self.max_workers = max_workers
    
    async def enqueue(self, message: Message):
        await self.queue.put(message)
    
    async def worker(self):
        while True:
            message = await self.queue.get()
            try:
                await process_message(message)
            finally:
                self.queue.task_done()
    
    async def start(self):
        workers = [
            asyncio.create_task(self.worker())
            for _ in range(self.max_workers)
        ]
        await asyncio.gather(*workers)
```

### 缓存策略

**缓存 Agent 响应**（可选）:
- 相似问题缓存（基于向量相似度）
- 短期缓存（5 分钟内重复问题）

**缓存 Session 映射**:
- 内存 LRU 缓存
- 定期同步到 Redis

---

## 8. 测试策略

### 单元测试

**测试覆盖**:
1. `http_client.py` - Mock Agent API 响应
2. `session_mapper.py` - 映射逻辑
3. `message_converter.py` - 格式转换
4. 手动模式管理

### 集成测试

**测试场景**:
1. 完整流程: 拦截 → 转换 → Agent → 回复
2. Agent 不可用场景
3. 超时场景
4. 手动模式切换

### 压力测试

**目标**:
- 并发 10 个对话
- 每秒 5 条消息
- Agent 响应时间 < 2s

---

## 总结

### 已解决的 NEEDS CLARIFICATION

| 项目 | 决策 | 状态 |
|------|------|------|
| 闲鱼消息格式 | 保留现有解析，新增转换层 | ✅ 已解决 |
| 会话映射策略 | 内存 + Redis（可选） | ✅ 已解决 |
| 通信方式 | HTTP (httpx) | ✅ 已解决 |
| 降级策略 | 跳过回复 + 日志 | ✅ 已解决 |
| 手动模式 | 保留逻辑，增加 Agent 同步 | ✅ 已解决 |

### Phase 1 设计输入

基于本研究，Phase 1 设计需包含:

1. **数据模型** (data-model.md):
   - XianyuMessage → Agent API 映射
   - SessionMapping 实体
   - 配置模型

2. **API 契约** (contracts/):
   - HTTP Client → Agent API 规范
   - 消息格式转换规范

3. **快速开始指南** (quickstart.md):
   - 环境搭建
   - 配置说明
   - 测试流程

---

**研究完成日期**: 2025-12-24  
**下一步**: 执行 Phase 1 设计，生成 data-model.md 和 contracts/
