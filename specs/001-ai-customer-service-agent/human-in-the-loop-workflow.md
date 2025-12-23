# 人机协作工作流 (Human-in-the-Loop)

**项目**: 001-ai-customer-service-agent  
**日期**: 2025-12-22  
**版本**: 1.0

---

## 概述

参考 gemini-cli 和 Claude Code 的人机协作模式，当 AI Agent 遇到不确定的情况时，**暂停执行**并向人工客服请求帮助（信息补充、策略选择、风险确认等），人工回答后 Agent **继续执行**，完成用户请求。

这不是"转接人工"，而是"请求人工协助"。

---

## 核心理念

```
传统转人工:
  用户 → Agent (无法回答) → 转接 → 人工接管 → 人工回答用户

人机协作 (Human-in-the-Loop):
  用户 → Agent (需要帮助) → 暂停 → 询问人工 → 人工回答 → Agent 继续 → Agent 回答用户
                                    ↑_______________|
```

**关键区别**:
- Agent 始终是用户的对话对象
- 人工是 Agent 的"后台顾问"
- 用户感知: "AI 正在为您核实信息..."

---

## 使用场景

### 场景 1: 信息补充

```
用户: "帮我查一下订单 #12345 的发货时间"
Agent: [知识库查询失败]
Agent: [需要访问订单系统，但没有权限]
Agent → 人工: "请帮我查询订单 #12345 的发货时间"
人工 → Agent: "该订单已于 2025-12-20 发货，物流单号 SF123456"
Agent → 用户: "您的订单已于 12 月 20 日发货，物流单号为 SF123456..."
```

### 场景 2: 策略选择

```
用户: "我要退款，但商品已经拆封了"
Agent: [知识库: 拆封商品退款需要特殊审批]
Agent → 人工: "用户要求退款拆封商品，是否批准？
              选项 A: 批准全额退款
              选项 B: 批准 50% 退款  
              选项 C: 拒绝退款"
人工 → Agent: "选择 B: 批准 50% 退款"
Agent → 用户: "您的退款申请已审批，由于商品已拆封，将退款 50%..."
```

### 场景 3: 风险确认

```
用户: "帮我取消所有待支付的订单"
Agent: [检测到批量操作，风险高]
Agent → 人工: "用户请求取消 5 个待支付订单，是否执行？
              - 订单 #001, #002, #003, #004, #005
              - 总金额: 5000 元"
人工 → Agent: "确认执行"
Agent → 用户: "已为您取消 5 个订单..."
```

### 场景 4: 知识补充

```
用户: "你们的会员积分规则是什么？"
Agent: [知识库无结果]
Agent → 人工: "用户咨询会员积分规则，知识库无相关内容，请提供信息"
人工 → Agent: "1 元消费 = 1 积分，积分可抵扣现金，100 积分 = 1 元"
Agent → 用户: "我们的积分规则是: 每消费 1 元获得 1 积分..."
Agent: [同时将此信息添加到知识库]
```

---

## 工具定义: `ask_human_agent`

### 工具规范

```python
{
    "name": "ask_human_agent",
    "description": """
向人工客服请求帮助，暂停当前对话等待人工回复。

**使用场景**:
1. 需要访问外部系统数据 (订单、库存、物流)
2. 需要人工决策 (退款审批、特殊请求)
3. 知识库无相关信息，需要补充
4. 高风险操作需要确认

**重要**: 这不是转接人工，而是请求协助。你仍然负责回答用户。
    """,
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "向人工提出的具体问题或请求"
            },
            "question_type": {
                "type": "string",
                "enum": [
                    "information_query",      # 信息查询
                    "decision_required",      # 需要决策
                    "risk_confirmation",      # 风险确认
                    "knowledge_gap"           # 知识缺失
                ],
                "description": "问题类型"
            },
            "context": {
                "type": "object",
                "description": "提供给人工的上下文信息",
                "properties": {
                    "user_question": {
                        "type": "string",
                        "description": "用户的原始问题"
                    },
                    "relevant_info": {
                        "type": "string",
                        "description": "已知的相关信息"
                    }
                }
            },
            "options": {
                "type": "array",
                "description": "如果是选择题，提供选项列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "label": {"type": "string"},
                        "description": {"type": "string"}
                    }
                }
            },
            "urgency": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "default": "medium",
                "description": "紧急程度"
            }
        },
        "required": ["question", "question_type"]
    }
}
```

### 调用示例

**示例 1: 信息查询**
```json
{
    "name": "ask_human_agent",
    "args": {
        "question": "请帮我查询订单 #12345 的发货时间和物流单号",
        "question_type": "information_query",
        "context": {
            "user_question": "我的订单什么时候发货?",
            "relevant_info": "订单号: #12345"
        },
        "urgency": "medium"
    }
}
```

**示例 2: 决策请求**
```json
{
    "name": "ask_human_agent",
    "args": {
        "question": "用户要求退款拆封商品，请选择处理策略",
        "question_type": "decision_required",
        "context": {
            "user_question": "我要退款，但商品已经拆封了",
            "relevant_info": "订单: #12345, 商品: iPhone 15, 已拆封"
        },
        "options": [
            {
                "id": "A",
                "label": "批准全额退款",
                "description": "100% 退款"
            },
            {
                "id": "B",
                "label": "批准部分退款",
                "description": "50% 退款 (拆封折损)"
            },
            {
                "id": "C",
                "label": "拒绝退款",
                "description": "已拆封不支持退款"
            }
        ],
        "urgency": "high"
    }
}
```

**示例 3: 风险确认**
```json
{
    "name": "ask_human_agent",
    "args": {
        "question": "用户请求取消 5 个订单，总金额 5000 元，是否执行?",
        "question_type": "risk_confirmation",
        "context": {
            "user_question": "帮我取消所有待支付的订单",
            "relevant_info": "订单列表: #001, #002, #003, #004, #005"
        },
        "urgency": "high"
    }
}
```

---

## 执行流程

### 流程图

```
┌─────────────────────────────────────────────────────────────┐
│  Turn 1: 用户提问                                             │
│  "帮我查一下订单 #12345 的发货时间"                           │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  Turn 2: Agent 执行                                           │
│  - 调用 knowledge_search("发货时间查询") → 无结果            │
│  - 需要访问订单系统，但无权限                                 │
│  - 决策: 调用 ask_human_agent                                │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  Turn 2 (续): ask_human_agent 执行                            │
│  1. 工具返回: {"status": "pending", "request_id": "req_001"}  │
│  2. Session 状态: waiting_for_human                          │
│  3. Agent 生成等待消息给用户                                  │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  Agent → 用户                                                 │
│  "正在为您核实订单信息，请稍候..."                            │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  系统推送通知到人工客服                                       │
│  [通知] 会话 #550e 需要协助                                   │
│  问题: "请帮我查询订单 #12345 的发货时间和物流单号"           │
│  类型: information_query                                     │
│  紧急度: medium                                              │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  人工客服查看详情                                             │
│  GET /sessions/{session_id}/pending-request                  │
│  返回:                                                        │
│  - 完整对话历史                                               │
│  - Agent 的问题                                               │
│  - 上下文信息                                                 │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  人工客服回答                                                 │
│  POST /sessions/{session_id}/human-response                  │
│  {                                                           │
│    "request_id": "req_001",                                  │
│    "response": "订单已于 2025-12-20 发货，物流单号 SF123456"  │
│  }                                                           │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  Turn 3: Agent 继续执行                                       │
│  - 接收人工回复: "订单已于 2025-12-20 发货..."               │
│  - ask_human_agent 工具返回: {"response": "..."}             │
│  - Agent 基于此信息生成回复                                  │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  Agent → 用户                                                 │
│  "您的订单已于 12 月 20 日发货，物流单号为 SF123456。        │
│   您可以通过顺丰官网或 App 查询物流详情..."                  │
└─────────────────────────────────────────────────────────────┘
                        ↓
                    对话继续...
```

### 状态机

```
Session.status 状态转换:

active (活跃)
  ├──> waiting_for_human (等待人工回复)
  │      ├──> active (人工已回复，Agent 继续)
  │      └──> timeout (超时未回复，自动恢复或终止)
  ├──> completed (对话完成)
  └──> error (错误)
```

---

## 数据模型扩展

### Session 增加字段

```python
class Session(BaseModel):
    # ... 现有字段 ...
    
    # Human-in-the-Loop 相关
    pending_human_request: Optional["HumanRequest"] = Field(
        None, 
        description="当前等待人工回复的请求"
    )
    human_request_history: List["HumanRequest"] = Field(
        default_factory=list,
        description="历史人工协助记录"
    )
```

### HumanRequest 模型

```python
class HumanRequest(BaseModel):
    """人工协助请求"""
    
    request_id: str = Field(..., description="请求唯一 ID")
    
    # 请求内容
    question: str = Field(..., description="向人工提出的问题")
    question_type: Literal[
        "information_query",
        "decision_required", 
        "risk_confirmation",
        "knowledge_gap"
    ]
    context: Dict[str, Any] = Field(default_factory=dict)
    options: Optional[List[Dict[str, str]]] = None
    urgency: Literal["low", "medium", "high"] = "medium"
    
    # 状态
    status: Literal["pending", "answered", "timeout"] = "pending"
    
    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow)
    answered_at: Optional[datetime] = None
    
    # 人工回复
    human_agent_id: Optional[str] = None
    response: Optional[str] = None
    selected_option: Optional[str] = None  # 如果是选择题
    
    class Config:
        json_schema_extra = {
            "example": {
                "request_id": "req_001",
                "question": "请帮我查询订单 #12345 的发货时间",
                "question_type": "information_query",
                "context": {
                    "user_question": "我的订单什么时候发货?",
                    "order_id": "#12345"
                },
                "status": "pending",
                "urgency": "medium"
            }
        }
```

---

## API 接口

### 1. 查询待处理请求 (人工客服端)

```bash
GET /human-agent/pending-requests?urgency=high&page=1&page_size=20
```

**响应**:
```json
{
    "items": [
        {
            "request_id": "req_001",
            "session_id": "550e8400-e29b-41d4-a716-446655440000",
            "question": "请帮我查询订单 #12345 的发货时间",
            "question_type": "information_query",
            "context": {
                "user_question": "我的订单什么时候发货?",
                "order_id": "#12345"
            },
            "urgency": "medium",
            "created_at": "2025-12-22T10:35:00Z",
            "waiting_seconds": 15
        }
    ],
    "total": 3,
    "page": 1
}
```

### 2. 查看请求详情

```bash
GET /sessions/{session_id}/pending-request
```

**响应**:
```json
{
    "request": {
        "request_id": "req_001",
        "question": "请帮我查询订单 #12345 的发货时间",
        "question_type": "information_query",
        "context": {...},
        "urgency": "medium"
    },
    "conversation_history": [
        {
            "role": "user",
            "content": "我的订单什么时候发货?",
            "timestamp": "2025-12-22T10:34:00Z"
        },
        {
            "role": "assistant",
            "content": "正在为您核实订单信息，请稍候...",
            "timestamp": "2025-12-22T10:35:00Z"
        }
    ]
}
```

### 3. 人工回复请求

```bash
POST /sessions/{session_id}/human-response
Content-Type: application/json

{
    "request_id": "req_001",
    "human_agent_id": "agent_001",
    "response": "订单已于 2025-12-20 发货，物流单号 SF123456"
}
```

**响应**:
```json
{
    "success": true,
    "request_id": "req_001",
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "answered",
    "message": "Agent 已继续执行"
}
```

---

## 系统提示词

### Agent 主系统提示

```markdown
# 人工协作指南

你有一个特殊的工具: `ask_human_agent`，用于请求人工客服的帮助。

## 何时使用 ask_human_agent

你应该在以下情况下调用此工具:

1. **需要外部系统数据**
   - 订单查询、库存查询、物流查询
   - 你没有权限访问这些系统
   
2. **需要人工决策**
   - 退款审批、特殊折扣、例外处理
   - 涉及金额或权限的操作
   
3. **知识库无答案**
   - knowledge_search 返回 0 结果
   - 这是补充知识库的机会
   
4. **高风险操作**
   - 批量操作、账户修改、敏感信息
   - 需要人工确认

## 如何使用 ask_human_agent

**重要原则**:
- 这不是"转接人工"，你仍然负责回答用户
- 人工是你的"后台顾问"，不是接管对话
- 调用后立即告诉用户: "正在为您核实信息，请稍候..."

**示例**:

用户: "帮我查一下订单 #12345 的发货时间"

你的思考:
- 我需要访问订单系统
- 我没有这个权限
- 调用 ask_human_agent 请求帮助

你的行动:
```json
{
    "tool": "ask_human_agent",
    "args": {
        "question": "请帮我查询订单 #12345 的发货时间和物流单号",
        "question_type": "information_query",
        "context": {
            "user_question": "帮我查一下订单 #12345 的发货时间",
            "order_id": "#12345"
        }
    }
}
```

你对用户说:
"正在为您核实订单 #12345 的发货信息，请稍候..."

人工回复:
"订单已于 2025-12-20 发货，物流单号 SF123456"

你对用户说:
"您的订单已于 12 月 20 日发货，物流单号为 SF123456。您可以通过顺丰官网或 App 实时查询物流详情。预计 3-5 天送达，请您留意签收。"

## 决策类问题

如果需要人工做选择，使用 `options` 参数:

```json
{
    "tool": "ask_human_agent",
    "args": {
        "question": "用户要求退款拆封商品，请选择处理策略",
        "question_type": "decision_required",
        "options": [
            {"id": "A", "label": "批准全额退款"},
            {"id": "B", "label": "批准 50% 退款"},
            {"id": "C", "label": "拒绝退款"}
        ]
    }
}
```

人工选择后，你基于选择继续回答用户。

## 超时处理

如果人工 5 分钟内未回复:
- 工具会返回 timeout 错误
- 你应该告诉用户: "抱歉，当前客服繁忙，建议您稍后再试或留下联系方式，我们会尽快回复您。"
```

---

## 实现要点

### 1. ask_human_agent 工具实现

```python
class AskHumanAgentTool:
    """人工协助请求工具"""
    
    async def execute(
        self,
        session_id: str,
        question: str,
        question_type: str,
        context: dict = None,
        options: list = None,
        urgency: str = "medium"
    ) -> dict:
        """执行人工协助请求"""
        
        # 1. 创建请求
        request = HumanRequest(
            request_id=f"req_{uuid.uuid4().hex[:8]}",
            question=question,
            question_type=question_type,
            context=context or {},
            options=options,
            urgency=urgency,
            status="pending"
        )
        
        # 2. 更新 Session
        session = await self.session_store.get(session_id)
        session.status = "waiting_for_human"
        session.pending_human_request = request
        await self.session_store.save(session)
        
        # 3. 推送通知给人工客服系统
        await self.notify_human_agents(request, session_id)
        
        # 4. 等待人工回复 (异步等待，带超时)
        try:
            response = await self.wait_for_human_response(
                session_id, 
                request.request_id,
                timeout=300  # 5 分钟
            )
            return {"status": "answered", "response": response}
        except TimeoutError:
            return {"status": "timeout", "error": "人工客服暂时无法响应"}
    
    async def wait_for_human_response(
        self, 
        session_id: str, 
        request_id: str, 
        timeout: int
    ) -> str:
        """等待人工回复 (轮询或事件驱动)"""
        
        start_time = datetime.utcnow()
        
        while (datetime.utcnow() - start_time).seconds < timeout:
            # 检查请求状态
            session = await self.session_store.get(session_id)
            request = session.pending_human_request
            
            if request.status == "answered":
                # 人工已回复
                session.status = "active"
                session.pending_human_request = None
                session.human_request_history.append(request)
                await self.session_store.save(session)
                
                return request.response
            
            # 等待 1 秒后重试
            await asyncio.sleep(1)
        
        # 超时
        raise TimeoutError("等待人工回复超时")
```

### 2. 人工客服通知

**选项 A: WebSocket 推送 (推荐)**
```python
# 实时推送给在线的人工客服
await websocket_manager.broadcast_to_agents({
    "event": "human_request",
    "request_id": "req_001",
    "session_id": "...",
    "question": "...",
    "urgency": "high"
})
```

**选项 B: 轮询**
```python
# 人工客服端每 3 秒轮询
GET /human-agent/pending-requests
```

### 3. 超时与降级

```python
# ask_human_agent 超时后的降级策略
if response.status == "timeout":
    # 选项 1: 告知用户等待
    return "当前客服繁忙，我们会尽快处理您的问题..."
    
    # 选项 2: 转为异步工单
    create_ticket(session_id, question)
    return "已为您创建工单，我们会在 24 小时内回复..."
    
    # 选项 3: 提供自助方案
    return "您也可以通过以下方式自助查询: ..."
```

---

## 监控指标

### 1. 人工协助率
```python
human_assist_rate = (使用 ask_human_agent 的会话数 / 总会话数) * 100%
# 目标: 10-20%
```

### 2. 人工响应时长
```python
response_time = answered_at - created_at
# 目标: P95 < 60 秒
```

### 3. 问题类型分布
```python
{
    "information_query": 60%,
    "decision_required": 25%,
    "risk_confirmation": 10%,
    "knowledge_gap": 5%
}
```

---

## 与传统转人工的对比

| 维度 | 传统转人工 | Human-in-the-Loop |
|------|-----------|-------------------|
| **对话主体** | 人工接管 | Agent 始终主导 |
| **用户感知** | "正在转接客服..." | "正在为您核实..." |
| **人工角色** | 接管对话 | 后台顾问 |
| **适用场景** | 完全无法回答 | 需要特定信息/决策 |
| **知识积累** | 无 | 可补充到知识库 |
| **一致性** | 依赖人工水平 | Agent 保证一致性 |

---

**文档版本**: 1.0  
**最后更新**: 2025-12-22  
**相关文档**: data-model.md, research.md, contracts/openapi.yaml
