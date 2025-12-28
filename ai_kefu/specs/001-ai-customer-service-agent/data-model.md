# 数据模型设计: AI 客服 Agent 系统

**项目**: 001-ai-customer-service-agent  
**日期**: 2025-12-22  
**版本**: 1.0

---

## 概述

本文档定义 AI 客服 Agent 系统的核心数据模型,包括会话状态、消息、知识库条目和工具调用记录。

**存储策略**:
- **Redis**: 会话状态 (Session, Message) - 非持久化,TTL 30分钟
- **Chroma**: 知识库条目 (KnowledgeEntry) - 持久化
- **内存**: 工具调用记录 (ToolCall) - 运行时状态

---

## 1. Session (会话)

### 用途
跟踪单个客服对话的完整状态,包括消息历史、上下文和元数据。

### 存储位置
Redis - Key: `session:{session_id}`

### 数据结构

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional, Dict, Any

class Session(BaseModel):
    """客服会话模型"""
    
    # 基本信息
    session_id: str = Field(..., description="唯一会话 ID (UUID)")
    user_id: Optional[str] = Field(None, description="用户 ID (可选)")
    
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # 消息历史
    messages: List["Message"] = Field(default_factory=list, description="对话消息列表")
    
    # Agent 状态
    turn_counter: int = Field(default=0, description="当前轮次计数")
    status: str = Field(
        default="active", 
        description="会话状态: active, completed, aborted, waiting_for_human, error"
    )
    
    # 上下文信息
    context: Dict[str, Any] = Field(default_factory=dict, description="会话上下文 (业务自定义)")
    
    # 终止原因
    terminate_reason: Optional[str] = Field(
        None, 
        description="终止原因: goal, timeout, error, max_turns"
    )
    
    # Human-in-the-Loop 相关
    pending_human_request: Optional["HumanRequest"] = Field(
        None, 
        description="当前等待人工回复的请求"
    )
    human_request_history: List["HumanRequest"] = Field(
        default_factory=list,
        description="历史人工协助记录"
    )
    
    # 元数据
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据 (如来源渠道、设备信息)"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "550e8400-e29b-41d4-a716-446655440000",
                "user_id": "user_12345",
                "created_at": "2025-12-22T10:30:00Z",
                "updated_at": "2025-12-22T10:35:00Z",
                "messages": [],
                "turn_counter": 5,
                "status": "active",
                "context": {"intent": "退款咨询"},
                "metadata": {"channel": "web", "ip": "192.168.1.100"}
            }
        }
```

### 状态转换

```
active (活跃) 
  ├──> waiting_for_human (等待人工回复 - Human-in-the-Loop)
  │      ├──> active (人工已回复，Agent 继续执行)
  │      └──> error (超时或错误)
  ├──> completed (完成) - Agent 调用 complete_task
  ├──> aborted (中止) - 用户主动结束或超时
  └──> error (错误) - 系统异常
```

### Redis 存储示例

```python
import redis
import json

def save_session(session: Session):
    r = redis.Redis()
    r.setex(
        f"session:{session.session_id}",
        1800,  # 30 分钟 TTL
        session.model_dump_json()
    )

def load_session(session_id: str) -> Optional[Session]:
    r = redis.Redis()
    data = r.get(f"session:{session_id}")
    return Session.model_validate_json(data) if data else None
```

---

## 2. Message (消息)

### 用途
表示对话中的单条消息,可以是用户输入、Agent 响应或工具调用结果。

### 存储位置
嵌套在 Session 的 `messages` 字段中

### 数据结构

```python
from typing import Literal

class Message(BaseModel):
    """对话消息模型"""
    
    # 基本信息
    role: Literal["user", "assistant", "tool"] = Field(..., description="消息角色")
    content: str = Field(..., description="消息内容")
    
    # 时间戳
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # 工具调用相关 (仅当 role=assistant 且有工具调用时)
    tool_calls: Optional[List["ToolCall"]] = Field(None, description="工具调用列表")
    
    # 工具响应相关 (仅当 role=tool 时)
    tool_call_id: Optional[str] = Field(None, description="关联的工具调用 ID")
    tool_name: Optional[str] = Field(None, description="工具名称")
    
    # 元数据
    metadata: Dict[str, Any] = Field(default_factory=dict, description="扩展元数据")
    
    class Config:
        json_schema_extra = {
            "example": {
                "role": "user",
                "content": "我想退款",
                "timestamp": "2025-12-22T10:30:00Z",
                "metadata": {}
            }
        }
```

### 消息类型示例

**1. 用户消息**
```json
{
  "role": "user",
  "content": "我的订单什么时候发货?",
  "timestamp": "2025-12-22T10:30:00Z"
}
```

**2. Assistant 消息 (纯文本)**
```json
{
  "role": "assistant",
  "content": "让我帮您查询订单信息",
  "timestamp": "2025-12-22T10:30:01Z"
}
```

**3. Assistant 消息 (带工具调用)**
```json
{
  "role": "assistant",
  "content": "正在搜索相关信息...",
  "timestamp": "2025-12-22T10:30:02Z",
  "tool_calls": [
    {
      "id": "call_abc123",
      "name": "knowledge_search",
      "args": {"query": "发货时间查询"}
    }
  ]
}
```

**4. 工具响应消息**
```json
{
  "role": "tool",
  "content": "订单通常在付款后 24 小时内发货",
  "tool_call_id": "call_abc123",
  "tool_name": "knowledge_search",
  "timestamp": "2025-12-22T10:30:03Z"
}
```

---

## 3. ToolCall (工具调用)

### 用途
记录单次工具调用的详细信息,用于循环检测和调试。

### 存储位置
- 嵌套在 Message 的 `tool_calls` 字段中 (持久化到 Redis)
- Agent 执行器的内存队列 (用于循环检测)

### 数据结构

```python
class ToolCall(BaseModel):
    """工具调用模型"""
    
    # 基本信息
    id: str = Field(..., description="工具调用唯一 ID")
    name: str = Field(..., description="工具名称")
    args: Dict[str, Any] = Field(..., description="工具参数")
    
    # 执行状态
    status: Literal["pending", "executing", "success", "error"] = Field(
        default="pending",
        description="执行状态"
    )
    
    # 结果
    result: Optional[Any] = Field(None, description="工具执行结果")
    error: Optional[str] = Field(None, description="错误信息 (如果失败)")
    
    # 性能指标
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = Field(None, description="执行耗时(毫秒)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "call_abc123",
                "name": "knowledge_search",
                "args": {"query": "退款流程", "top_k": 5},
                "status": "success",
                "result": {"documents": ["退款需在7天内..."]},
                "duration_ms": 85
            }
        }
```

### 状态转换

```
pending (待执行)
  └──> executing (执行中)
         ├──> success (成功)
         └──> error (失败)
```

---

## 4. KnowledgeEntry (知识库条目)

### 用途
存储客服知识库的文档内容和向量嵌入。

### 存储位置
Chroma 向量数据库

### 数据结构

```python
class KnowledgeEntry(BaseModel):
    """知识库条目模型"""
    
    # 基本信息
    id: str = Field(..., description="文档唯一 ID")
    title: str = Field(..., description="文档标题")
    content: str = Field(..., description="文档内容")
    
    # 分类
    category: Optional[str] = Field(None, description="分类标签")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    
    # 元数据
    source: Optional[str] = Field(None, description="来源")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # 业务字段
    priority: int = Field(default=0, description="优先级 (用于排序)")
    active: bool = Field(default=True, description="是否启用")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "kb_001",
                "title": "退款政策",
                "content": "用户在收到商品后7天内可申请无理由退款...",
                "category": "售后服务",
                "tags": ["退款", "售后"],
                "source": "官方文档",
                "priority": 10,
                "active": True
            }
        }
```

### Chroma 存储示例

```python
import chromadb

def add_knowledge(entry: KnowledgeEntry, embedding: List[float]):
    client = chromadb.PersistentClient(path="./chroma_data")
    collection = client.get_or_create_collection(name="knowledge_base")
    
    collection.add(
        ids=[entry.id],
        embeddings=[embedding],
        documents=[entry.content],
        metadatas=[{
            "title": entry.title,
            "category": entry.category,
            "tags": ",".join(entry.tags),
            "priority": entry.priority
        }]
    )

def search_knowledge(query_embedding: List[float], top_k: int = 5):
    client = chromadb.PersistentClient(path="./chroma_data")
    collection = client.get_collection(name="knowledge_base")
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )
    return results
```

---

## 5. HumanRequest (人工协助请求)

### 用途
当 Agent 需要人工协助时（查询信息、做决策、确认风险等），创建此请求并暂停执行，等待人工回复后继续。

### 存储位置
- 当前待处理: 嵌套在 Session 的 `pending_human_request` 字段中
- 历史记录: 嵌套在 Session 的 `human_request_history` 字段中

### 数据结构

```python
from typing import Literal

class HumanRequestOption(BaseModel):
    """人工决策选项"""
    id: str = Field(..., description="选项 ID")
    label: str = Field(..., description="选项标签")
    description: Optional[str] = Field(None, description="选项说明")

class HumanRequest(BaseModel):
    """人工协助请求 (Human-in-the-Loop)"""
    
    # 基本信息
    request_id: str = Field(..., description="请求唯一 ID")
    
    # 请求内容
    question: str = Field(..., description="向人工提出的具体问题")
    question_type: Literal[
        "information_query",      # 信息查询
        "decision_required",      # 需要决策
        "risk_confirmation",      # 风险确认
        "knowledge_gap"           # 知识缺失
    ] = Field(..., description="问题类型")
    
    # 上下文
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="提供给人工的上下文信息"
    )
    
    # 决策选项 (可选，用于选择题)
    options: Optional[List[HumanRequestOption]] = Field(
        None,
        description="如果是选择题，提供选项列表"
    )
    
    # 紧急程度
    urgency: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="紧急程度"
    )
    
    # 状态
    status: Literal["pending", "answered", "timeout"] = Field(
        default="pending",
        description="请求状态"
    )
    
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow)
    answered_at: Optional[datetime] = None
    
    # 人工回复
    human_agent_id: Optional[str] = Field(None, description="处理该请求的人工客服 ID")
    response: Optional[str] = Field(None, description="人工的文本回复")
    selected_option: Optional[str] = Field(None, description="人工选择的选项 ID")
    
    # 元数据
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="扩展元数据"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "request_id": "req_abc123",
                "question": "请帮我查询订单 #12345 的发货时间和物流单号",
                "question_type": "information_query",
                "context": {
                    "user_question": "我的订单什么时候发货?",
                    "order_id": "#12345"
                },
                "urgency": "medium",
                "status": "pending",
                "created_at": "2025-12-22T10:35:00Z"
            }
        }
```

### 请求类型说明

| 类型 | 说明 | 示例 |
|------|------|------|
| `information_query` | 查询外部系统信息 | "请查询订单 #12345 的发货时间" |
| `decision_required` | 需要人工决策 | "用户退款拆封商品，选择处理策略 A/B/C" |
| `risk_confirmation` | 高风险操作确认 | "用户要取消 5 个订单，是否执行？" |
| `knowledge_gap` | 知识库缺失，需要补充 | "会员积分规则是什么？" |

### 示例场景

**场景 1: 信息查询**
```python
request = HumanRequest(
    request_id="req_001",
    question="请帮我查询订单 #12345 的发货时间和物流单号",
    question_type="information_query",
    context={
        "user_question": "我的订单什么时候发货?",
        "order_id": "#12345"
    },
    urgency="medium"
)
```

**场景 2: 决策选择**
```python
request = HumanRequest(
    request_id="req_002",
    question="用户要求退款拆封商品，请选择处理策略",
    question_type="decision_required",
    context={
        "user_question": "我要退款，但商品已经拆封了",
        "order_id": "#12345",
        "product": "iPhone 15"
    },
    options=[
        HumanRequestOption(
            id="A",
            label="批准全额退款",
            description="100% 退款"
        ),
        HumanRequestOption(
            id="B",
            label="批准部分退款",
            description="50% 退款 (拆封折损)"
        ),
        HumanRequestOption(
            id="C",
            label="拒绝退款",
            description="已拆封不支持退款"
        )
    ],
    urgency="high"
)
```

**场景 3: 风险确认**
```python
request = HumanRequest(
    request_id="req_003",
    question="用户请求取消 5 个订单，总金额 5000 元，是否执行?",
    question_type="risk_confirmation",
    context={
        "user_question": "帮我取消所有待支付的订单",
        "order_ids": ["#001", "#002", "#003", "#004", "#005"],
        "total_amount": 5000
    },
    urgency="high"
)
```

---

## 6. AgentState (Agent 运行时状态)

### 用途
跟踪 Agent 执行器的运行时状态,用于循环检测和恢复机制。

### 存储位置
Agent 执行器内存 (不持久化)

### 数据结构

```python
class AgentState(BaseModel):
    """Agent 运行时状态"""
    
    # 会话关联
    session_id: str
    
    # 循环检测
    recent_tool_calls: List[str] = Field(
        default_factory=list,
        description="最近的工具调用签名 (用于循环检测)"
    )
    loop_detected: bool = Field(default=False)
    loop_count: int = Field(default=0)
    
    # 执行统计
    total_turns: int = Field(default=0)
    total_tool_calls: int = Field(default=0)
    start_time: datetime = Field(default_factory=datetime.utcnow)
    
    # 中止信号
    aborted: bool = Field(default=False)
    abort_reason: Optional[str] = None

def check_tool_loop(state: AgentState, tool_call: ToolCall) -> bool:
    """检测工具调用循环"""
    signature = f"{tool_call.name}:{json.dumps(tool_call.args, sort_keys=True)}"
    
    # 检查最近 5 次调用中是否有重复
    if state.recent_tool_calls.count(signature) >= 3:
        return True
    
    state.recent_tool_calls.append(signature)
    if len(state.recent_tool_calls) > 10:
        state.recent_tool_calls.pop(0)
    
    return False
```

---

## 6. 数据流图

```
┌─────────────────────────────────────────────────────────────────┐
│                       用户请求                                    │
│                    POST /chat/stream                             │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  1. 加载/创建 Session (Redis)                                     │
│     session = load_session(session_id) or create_session()      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  2. 添加用户消息到 Session                                        │
│     session.messages.append(Message(role="user", ...))          │
│     save_session(session)                                        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  3. Agent 执行循环                                                │
│     while not terminated:                                        │
│       - 调用 Gemini API (携带 messages 历史)                     │
│       - 获取 tool_calls                                          │
│       - 执行工具 (knowledge_search 查询 Chroma)                  │
│       - 添加 tool 消息到 Session                                 │
│       - 检查循环 (AgentState)                                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  4. 保存最终状态                                                  │
│     session.status = "completed"                                 │
│     session.terminate_reason = "goal"                            │
│     save_session(session)                                        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                        返回响应给用户
```

---

## 7. 索引和查询模式

### Redis 键模式

```
session:{session_id}                  # 会话数据
session:{session_id}:lock             # 分布式锁 (可选)
```

### Chroma 查询模式

```python
# 1. 语义检索
results = collection.query(
    query_embeddings=[embedding],
    n_results=5,
    where={"active": True}  # 过滤条件
)

# 2. 分类检索
results = collection.query(
    query_embeddings=[embedding],
    n_results=5,
    where={"category": "售后服务"}
)

# 3. 混合检索 (向量 + 元数据)
results = collection.query(
    query_embeddings=[embedding],
    n_results=10,
    where={"priority": {"$gte": 5}}  # 优先级 >= 5
)
```

---

## 8. 数据生命周期

### Session (Redis TTL)
- **创建**: 用户首次发送消息
- **更新**: 每次对话更新 `updated_at` 并刷新 TTL
- **过期**: 30 分钟无活动自动删除
- **手动删除**: 用户主动结束或 complete_task 后可选删除

### KnowledgeEntry (持久化)
- **创建**: 通过管理接口添加
- **更新**: 通过管理接口修改
- **删除**: 软删除 (`active=False`) 或硬删除

---

## 9. 验证规则

### Session
- `session_id`: UUID 格式
- `status`: 枚举值 (active, completed, aborted, error)
- `turn_counter`: >= 0,<= 50 (最大轮次限制)

### Message
- `role`: 枚举值 (user, assistant, tool)
- `content`: 非空字符串,长度 <= 10000
- `tool_calls`: 当 role=assistant 时可选

### KnowledgeEntry
- `content`: 非空字符串,长度 >= 10
- `priority`: 0-100
- `tags`: 最多 10 个标签

---

**文档版本**: 1.0  
**最后更新**: 2025-12-22  
**下一步**: 生成 API 契约 (contracts/openapi.yaml)
