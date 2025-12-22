# 技术研究报告: AI 客服 Agent 系统

**日期**: 2025-12-22  
**项目**: 001-ai-customer-service-agent  
**目的**: 解决技术上下文中的 NEEDS CLARIFICATION 项,为实施提供明确的技术选型决策

---

## 1. 知识库存储方案选型

### 决策
**Chroma** (轻量级向量数据库)

### 理由
1. **内网部署友好**: 单进程嵌入式部署,无需复杂的分布式配置
2. **Python 原生支持**: 优秀的 Python API,与 FastAPI 生态集成良好
3. **轻量级**: 资源占用低,适合初期规模 (<10k 文档)
4. **语义检索**: 原生支持向量相似度搜索,配合 Gemini Embeddings API
5. **持久化简单**: 支持本地文件持久化,无需额外数据库

### 备选方案考虑
- **Elasticsearch**: 功能强大但过于重量级,部署复杂,内网环境不友好
- **Milvus**: 适合大规模场景 (>100k 文档),当前需求过度设计
- **Qdrant**: 性能优秀,但部署复杂度高于 Chroma

### 实施要点
```python
# 依赖安装
pip install chromadb

# 初始化
import chromadb
client = chromadb.PersistentClient(path="./chroma_data")
collection = client.create_collection(name="knowledge_base")

# 知识检索示例
results = collection.query(
    query_embeddings=[embedding],
    n_results=5
)
```

**性能预估**: 检索延迟 <100ms (本地部署,5k 文档规模)

---

## 2. 会话状态存储方案

### 决策
**Redis** (非持久化,纯内存缓存)

### 理由
1. **非持久化需求**: 客服会话是临时状态,无需长期保存
2. **性能优异**: 内存操作,延迟 <1ms,支持高并发
3. **TTL 自动过期**: 原生支持会话超时自动清理
4. **简单运维**: Redis 成熟稳定,内网部署简单
5. **分布式友好**: 后续支持多实例部署时,共享会话状态

### 配置建议
```python
# Redis 非持久化配置 (redis.conf)
# 关闭 RDB 快照
save ""

# 关闭 AOF
appendonly no

# 最大内存限制 (例如 2GB)
maxmemory 2gb

# 内存淘汰策略: LRU 删除带过期时间的键
maxmemory-policy volatile-lru
```

### 实施要点
```python
# 依赖安装
pip install redis

# 会话管理
import redis
import json
from datetime import timedelta

class SessionStore:
    def __init__(self, redis_url="redis://localhost:6379"):
        self.client = redis.from_url(redis_url)
        self.ttl = 1800  # 30分钟
    
    def get(self, session_id: str) -> dict | None:
        data = self.client.get(f"session:{session_id}")
        return json.loads(data) if data else None
    
    def set(self, session_id: str, data: dict):
        self.client.setex(
            f"session:{session_id}",
            self.ttl,
            json.dumps(data)
        )
    
    def delete(self, session_id: str):
        self.client.delete(f"session:{session_id}")
```

**并发性能预估**: 
- 单 Redis 实例: 10,000+ req/s (GET/SET 操作)
- 满足 100-400 并发用户需求

---

## 3. FastAPI 异步流式响应最佳实践

### 决策
**StreamingResponse + AsyncGenerator**

### 理由
1. **原生支持**: FastAPI 内置流式响应支持
2. **背压控制**: AsyncGenerator 自动处理背压,避免内存溢出
3. **客户端友好**: SSE (Server-Sent Events) 协议,前端易集成
4. **取消支持**: 支持客户端中断连接时清理资源

### 实施要点
```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator
import asyncio

app = FastAPI()

async def event_generator(session_id: str, query: str) -> AsyncGenerator[str, None]:
    """流式生成 Agent 响应"""
    async for chunk in agent_executor.stream(session_id, query):
        # SSE 格式
        yield f"data: {json.dumps({'text': chunk})}\n\n"
        await asyncio.sleep(0)  # 让出控制权

@app.post("/chat/stream")
async def chat_stream(session_id: str, query: str):
    return StreamingResponse(
        event_generator(session_id, query),
        media_type="text/event-stream"
    )
```

**依赖注入模式**:
```python
from fastapi import Depends

def get_session_store():
    """依赖工厂"""
    return SessionStore()

def get_agent_executor(
    store: SessionStore = Depends(get_session_store)
):
    return AgentExecutor(session_store=store)

@app.post("/chat")
async def chat(
    session_id: str,
    query: str,
    executor: AgentExecutor = Depends(get_agent_executor)
):
    return await executor.run(session_id, query)
```

**错误处理**:
```python
from fastapi import HTTPException, status
from fastapi.exception_handlers import http_exception_handler
import logging

logger = logging.getLogger(__name__)

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return await http_exception_handler(
        request,
        HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )
    )
```

---

## 4. Gemini API 使用建议

### 模型选择
**gemini-2.0-flash-exp** (实验版)

**特性**:
- 多模态支持 (文本、图像)
- 原生 Function Calling (工具调用)
- 流式响应
- 思考链 (Thought) 能力

**推荐配置**:
```python
generation_config = {
    "temperature": 0.7,        # 客服场景: 平衡创造性和准确性
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 2048,
}
```

### 流式响应处理

```python
import google.generativeai as genai

async def stream_response(prompt: str, tools: list):
    model = genai.GenerativeModel(
        'gemini-2.0-flash-exp',
        tools=tools
    )
    
    response = model.generate_content(
        prompt,
        generation_config=generation_config,
        stream=True
    )
    
    for chunk in response:
        if chunk.text:
            yield chunk.text
        # 处理 function_calls
        if hasattr(chunk, 'function_calls'):
            for fc in chunk.function_calls:
                yield {"tool_call": fc.name, "args": fc.args}
```

### Function Calling 最佳实践

参考 gemini-cli 的工具定义格式:

```python
tools = [
    {
        "name": "knowledge_search",
        "description": "搜索知识库获取相关信息",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词"
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回结果数量",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "complete_task",
        "description": "标记客服对话完成",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "对话总结"
                },
                "resolved": {
                    "type": "boolean",
                    "description": "问题是否已解决"
                }
            },
            "required": ["summary", "resolved"]
        }
    }
]
```

### 速率限制和重试策略

```python
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
from google.api_core.exceptions import ResourceExhausted

@retry(
    retry=retry_if_exception_type(ResourceExhausted),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(5)
)
async def call_gemini_with_retry(prompt: str):
    return await model.generate_content_async(prompt)
```

**速率限制** (gemini-2.0-flash-exp):
- QPM (Queries Per Minute): 1000
- TPM (Tokens Per Minute): 4,000,000
- RPD (Requests Per Day): 1500

**建议**: 实现客户端限流器,避免触发 API 配额

---

## 5. 并发用户数和性能预估

### 基于参考架构的性能分析

参考 gemini-cli 的循环检测和超时机制:
- 单次对话最大轮次: 50 turns
- 单轮超时: 2 分钟
- 循环检测阈值: 5 次重复工具调用

### 客服场景预估

**假设**:
- 平均对话轮次: 3-5 turns
- 平均单轮处理时间: 2s (包括 API 调用 + 知识库检索)
- 对话总时长: 6-10s

**并发能力**:
- 单进程 (异步 IO): 100 并发
- 多进程 (4 workers): 400 并发
- Redis 瓶颈: 10,000+ QPS
- Chroma 检索: 1,000+ QPS

**推荐配置**:
- **初期**: 单进程 FastAPI,预期支持 100 并发用户
- **扩展**: Gunicorn + 4 workers,支持 400+ 并发

**部署建议**:
```bash
# 单进程开发模式
uvicorn main:app --host 0.0.0.0 --port 8000

# 生产模式 (多进程)
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120
```

---

## 6. 日志和审计要求

### 决策
**结构化日志 (JSON 格式)**

### 实施方案

```python
import logging
import json
from datetime import datetime

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "session_id": getattr(record, 'session_id', None),
            "event_type": getattr(record, 'event_type', None),
            "duration_ms": getattr(record, 'duration_ms', None),
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data, ensure_ascii=False)

# 配置日志
logging.basicConfig(level=logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger = logging.getLogger("ai_kefu")
logger.addHandler(handler)
```

**日志级别**:
- DEBUG: 开发调试,包含完整上下文
- INFO: 业务事件 (对话开始/结束、工具调用)
- WARNING: 异常情况 (重试、降级)
- ERROR: 错误事件 (API 失败、超时)

**审计字段**:
- `session_id`: 会话 ID
- `timestamp`: 时间戳
- `event_type`: 事件类型 (chat_start, tool_call, chat_end)
- `tool_name`: 工具名称
- `duration_ms`: 处理时长

---

## 7. 总结与后续行动

### 已解决的 NEEDS CLARIFICATION

| 项目 | 决策 | 状态 |
|------|------|------|
| 知识库存储 | Chroma (持久化) | ✅ 已解决 |
| 会话存储 | Redis (非持久化) | ✅ 已解决 |
| 知识库检索延迟 | <100ms (预估) | ✅ 已解决 |
| 日志审计 | 结构化 JSON 日志 | ✅ 已解决 |
| 并发用户数 | 100 (单进程) / 400+ (多进程) | ✅ 已解决 |
| 工单系统集成 | Phase 2 功能,暂不实现 | ⚠️ 延后 |

### Phase 1 设计输入

基于本研究,Phase 1 设计需包含:

1. **数据模型** (data-model.md):
   - Session 实体 (会话状态,存储在 Redis)
   - Message 实体 (对话消息,存储在 Session 中)
   - KnowledgeEntry 实体 (知识库条目,存储在 Chroma)
   - ToolCall 实体 (工具调用记录,用于循环检测)

2. **API 契约** (contracts/openapi.yaml):
   - POST /chat/stream - 流式对话
   - POST /chat - 同步对话
   - GET /sessions/{id} - 查询会话
   - POST /knowledge/search - 知识库检索 (管理接口)

3. **快速开始指南** (quickstart.md):
   - 环境搭建 (Python 3.11+, Redis, Gemini API Key)
   - 依赖安装
   - 配置说明
   - 启动服务

### 技术栈总结

```yaml
运行时:
  - Python: 3.11+
  - FastAPI: 最新稳定版
  - Redis: 7.x (非持久化配置)

AI/ML:
  - google-generativeai: Gemini SDK
  - chromadb: 向量数据库

工具:
  - uvicorn: ASGI 服务器
  - gunicorn: 多进程管理 (生产)
  - pytest: 测试框架
  - httpx: HTTP 客户端 (测试)

可选:
  - tenacity: 重试机制
  - pydantic: 数据验证
```

---

**研究完成日期**: 2025-12-22  
**下一步**: 执行 Phase 1 设计,生成 data-model.md 和 contracts/
