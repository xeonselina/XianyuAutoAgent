# AI 客服后端完整流程解读

本文档详细解析 ai_kefu 后端从接收请求到返回结果的完整流程，包含所有关键代码片段。

---

## 📋 目录

1. [整体架构](#整体架构)
2. [请求接收层](#请求接收层)
3. [Agent 执行器](#agent-执行器)
4. [单轮对话执行](#单轮对话执行)
5. [工具调用机制](#工具调用机制)
6. [大模型调用](#大模型调用)
7. [响应返回](#响应返回)
8. [完整流程图](#完整流程图)

---

## 🏗️ 整体架构

```
HTTP Request (用户问题)
    ↓
FastAPI Router (/chat)
    ↓
AgentExecutor.run()
    ↓
execute_turn() [单轮执行]
    ↓
call_qwen() [调用通义千问]
    ↓
ToolRegistry.execute_tool() [工具调用]
    ↓
Response (AI 回复)
```

---

## 1️⃣ 请求接收层

### 1.1 FastAPI 应用入口

**文件**: `api/main.py`

```python
# 创建 FastAPI 应用
app = FastAPI(
    title="AI Customer Service Agent",
    description="AI-powered customer service agent",
    version="1.0.0",
    lifespan=lifespan  # 生命周期管理
)

# 注册聊天路由
from ai_kefu.api.routes import chat
app.include_router(chat.router, prefix="/chat", tags=["chat"])
```

**关键点**:
- 使用 `lifespan` 管理启动/关闭事件
- CORS 中间件允许跨域请求
- 注册 5 个路由模块：system, chat, session, human_agent, knowledge

### 1.2 聊天接口

**文件**: `api/routes/chat.py`

```python
@router.post("/", response_model=ChatResponse)
async def chat_sync(
    request: ChatRequest,  # 请求体：{query, session_id?, user_id?}
    session_store: SessionStore = Depends(get_session_store)  # 依赖注入
):
    """
    同步聊天接口 - 完整响应后返回
    """
    logger.info(f"Chat request: query='{request.query[:50]}...', session_id={request.session_id}")
    
    # 1. 创建 Agent 执行器
    executor = AgentExecutor(session_store=session_store)
    
    # 2. 运行 Agent（核心逻辑）
    result = executor.run(
        query=request.query,
        session_id=request.session_id,
        user_id=request.user_id
    )
    
    # 3. 检查错误
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    
    # 4. 返回响应
    return ChatResponse(
        session_id=result["session_id"],
        response=result.get("response", ""),
        status=result["status"],
        turn_counter=result.get("turn_counter", 0),
        metadata=result.get("metadata", {})
    )
```

**请求示例**:
```json
{
  "query": "如何退货？",
  "session_id": "optional-session-id",
  "user_id": "user-123"
}
```

**响应示例**:
```json
{
  "session_id": "uuid-generated",
  "response": "根据退货政策，您可以在收到商品后7天内申请退货...",
  "status": "active",
  "turn_counter": 1,
  "metadata": {
    "duration_ms": 1234
  }
}
```

### 1.3 流式接口

```python
@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    session_store: SessionStore = Depends(get_session_store)
):
    """
    流式聊天接口 - SSE (Server-Sent Events)
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        executor = AgentExecutor(session_store=session_store)
        
        # 流式返回响应
        async for chunk in executor.stream(
            query=request.query,
            session_id=request.session_id,
            user_id=request.user_id
        ):
            # SSE 格式
            event_data = {"text": chunk, "type": "chunk"}
            yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
        
        # 完成标记
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
```

**SSE 响应示例**:
```
data: {"text": "根据", "type": "chunk"}

data: {"text": "退货", "type": "chunk"}

data: {"text": "政策", "type": "chunk"}

data: {"type": "done"}
```

---

## 2️⃣ Agent 执行器

**文件**: `agent/executor.py`

### 2.1 初始化

```python
class AgentExecutor:
    def __init__(
        self,
        session_store: SessionStore,
        config: Optional[AgentConfig] = None
    ):
        self.session_store = session_store  # Session 存储
        
        # 配置参数
        self.config = config or AgentConfig(
            max_turns=settings.max_turns,  # 最大轮数（防止死循环）
            turn_timeout_seconds=settings.turn_timeout_seconds,  # 超时时间
            loop_detection_threshold=settings.loop_detection_threshold  # 循环检测阈值
        )
        
        # 初始化工具注册表
        self.tools_registry = ToolRegistry()
        self._register_tools()  # 注册所有工具
```

### 2.2 工具注册

```python
def _register_tools(self):
    """注册所有可用工具"""
    # 1. 知识库搜索
    self.tools_registry.register_tool(
        "knowledge_search",
        knowledge_search.knowledge_search,  # 工具函数
        knowledge_search.get_tool_definition()  # 工具定义（Qwen Function Calling 格式）
    )
    
    # 2. 完成任务
    self.tools_registry.register_tool(
        "complete_task",
        complete_task.complete_task,
        complete_task.get_tool_definition()
    )
    
    # 3. 请求人工客服
    from ai_kefu.tools import ask_human_agent
    self.tools_registry.register_tool(
        "ask_human_agent",
        ask_human_agent.ask_human_agent,
        ask_human_agent.get_tool_definition()
    )
    
    logger.info(f"Registered {len(self.tools_registry.get_all_tools())} tools")
```

### 2.3 主执行循环

```python
def run(
    self,
    query: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> dict:
    """
    同步运行 Agent（完整对话）
    """
    start_time = datetime.utcnow()
    
    # 1. 加载或创建 Session
    session = self._get_or_create_session(session_id, user_id)
    
    # 2. 创建 Agent 状态（用于循环检测）
    agent_state = AgentState(session_id=session.session_id)
    
    # 3. 执行轮次循环
    response_text = ""
    
    try:
        while True:
            # 检查最大轮数
            if session.turn_counter >= self.config.max_turns:
                raise MaxTurnsExceededError(session.session_id, self.config.max_turns)
            
            # 🔥 执行单轮对话（核心）
            turn_result = execute_turn(
                session=session,
                user_message=query,
                tools_registry=self.tools_registry
            )
            
            # 检查执行失败
            if not turn_result.success:
                session.status = SessionStatus.ERROR
                session.terminate_reason = TerminateReason.ERROR
                self.session_store.set(session)
                return {
                    "session_id": session.session_id,
                    "status": session.status,
                    "error": turn_result.error_message
                }
            
            # 更新 Session
            session.messages.extend(turn_result.new_messages)
            session.turn_counter += 1
            session.updated_at = datetime.utcnow()
            
            # 循环检测
            if self.config.enable_loop_detection and turn_result.tool_calls:
                for tc_dict in turn_result.tool_calls:
                    tc = ToolCall(
                        id=tc_dict["id"],
                        name=tc_dict["name"],
                        args=tc_dict["args"]
                    )
                    if check_tool_loop(agent_state, tc):
                        raise LoopDetectedError(session.session_id, tc.name)
            
            # 检查是否完成任务
            task_completed = any(
                tc_dict["name"] == TOOL_COMPLETE_TASK
                for tc_dict in turn_result.tool_calls
            )
            
            if task_completed:
                session.status = SessionStatus.COMPLETED
                session.terminate_reason = TerminateReason.GOAL
                response_text = turn_result.response_text
                break
            
            response_text = turn_result.response_text
            
            # 同步模式：第一轮后停止（多轮需要用户继续输入）
            break
        
        # 保存 Session
        self.session_store.set(session)
        
        # 返回结果
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        log_agent_complete(session.session_id, session.status, session.turn_counter, duration_ms)
        
        return {
            "session_id": session.session_id,
            "response": response_text,
            "status": session.status,
            "turn_counter": session.turn_counter,
            "metadata": {"duration_ms": duration_ms}
        }
        
    except Exception as e:
        logger.error(f"Agent execution failed: {e}", exc_info=True)
        session.status = SessionStatus.ERROR
        self.session_store.set(session)
        return {"session_id": session.session_id, "status": session.status, "error": str(e)}
```

---

## 3️⃣ 单轮对话执行

**文件**: `agent/turn.py`

```python
def execute_turn(
    session: Session,
    user_message: str,
    tools_registry: ToolRegistry,
    system_prompt: str = CUSTOMER_SERVICE_SYSTEM_PROMPT
) -> TurnResult:
    """
    执行一轮对话
    
    流程：
    1. 添加用户消息
    2. 构建消息历史
    3. 调用 Qwen API
    4. 执行工具调用
    5. 返回结果
    """
    start_time = datetime.utcnow()
    turn_counter = session.turn_counter + 1
    
    log_turn_start(session.session_id, turn_counter, user_message)
    
    try:
        # 1️⃣ 创建用户消息
        user_msg = Message(
            role=MessageRole.USER,
            content=user_message,
            timestamp=datetime.utcnow()
        )
        new_messages = [user_msg]
        
        # 2️⃣ 构建消息历史（包含系统提示词）
        messages = _build_message_history(session, user_msg, system_prompt)
        
        # 3️⃣ 获取工具定义（Qwen Function Calling 格式）
        tools = tools_registry.to_qwen_format()
        
        # 4️⃣ 调用 Qwen API（核心）
        logger.info(f"Calling Qwen API for turn {turn_counter}")
        response = call_qwen(messages=messages, tools=tools if tools else None)
        
        # 5️⃣ 解析响应
        assistant_message = response["choices"][0]["message"]
        response_text = assistant_message.get("content", "")
        tool_calls_data = assistant_message.get("tool_calls", [])
        
        # 6️⃣ 创建助手消息
        assistant_msg = Message(
            role=MessageRole.ASSISTANT,
            content=response_text,
            timestamp=datetime.utcnow()
        )
        
        tool_call_objects = []
        
        # 7️⃣ 执行工具调用
        if tool_calls_data:
            for tc in tool_calls_data:
                tool_name = tc["function"]["name"]
                tool_call_id = tc["id"]
                
                try:
                    # 解析参数
                    args = json.loads(tc["function"]["arguments"])
                    
                    log_tool_call(session.session_id, tool_name, tool_call_id, args)
                    
                    # 创建工具调用对象
                    tool_call = ToolCall(
                        id=tool_call_id,
                        name=tool_name,
                        args=args,
                        status=ToolCallStatus.EXECUTING,
                        started_at=datetime.utcnow()
                    )
                    
                    # 🔥 执行工具
                    tool_start = datetime.utcnow()
                    result = tools_registry.execute_tool(tool_name, args)
                    tool_end = datetime.utcnow()
                    
                    # 更新工具调用状态
                    tool_call.result = result
                    tool_call.status = ToolCallStatus.SUCCESS
                    tool_call.completed_at = tool_end
                    tool_call.duration_ms = int((tool_end - tool_start).total_seconds() * 1000)
                    
                    tool_call_objects.append(tool_call)
                    
                    log_tool_result(
                        session.session_id,
                        tool_name,
                        tool_call_id,
                        success=True,
                        duration_ms=tool_call.duration_ms
                    )
                    
                    # 创建工具响应消息
                    tool_msg = Message(
                        role=MessageRole.TOOL,
                        content=json.dumps(result, ensure_ascii=False),
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        timestamp=datetime.utcnow()
                    )
                    new_messages.append(tool_msg)
                    
                except Exception as e:
                    logger.error(f"Tool execution failed: {e}")
                    tool_call.status = ToolCallStatus.ERROR
                    tool_call.error = str(e)
                    tool_call.completed_at = datetime.utcnow()
                    tool_call_objects.append(tool_call)
        
        # 添加工具调用到助手消息
        if tool_call_objects:
            assistant_msg.tool_calls = tool_call_objects
        
        new_messages.insert(1, assistant_msg)  # 插入到用户消息后
        
        # 计算耗时
        end_time = datetime.utcnow()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        
        log_turn_end(session.session_id, turn_counter, duration_ms, success=True)
        
        # 8️⃣ 返回结果
        return TurnResult(
            success=True,
            response_text=response_text,
            tool_calls=[
                {
                    "id": tc.id,
                    "name": tc.name,
                    "args": tc.args,
                    "result": tc.result
                }
                for tc in tool_call_objects
            ],
            new_messages=new_messages,
            metadata={
                "duration_ms": duration_ms,
                "turn_counter": turn_counter
            }
        )
        
    except Exception as e:
        error_msg = f"Turn execution failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        log_turn_end(session.session_id, turn_counter, duration_ms, success=False)
        
        return TurnResult(
            success=False,
            error_message=error_msg
        )
```

### 3.1 消息历史构建

```python
def _build_message_history(
    session: Session,
    new_user_message: Message,
    system_prompt: str
) -> List[Dict[str, Any]]:
    """
    构建 Qwen API 的消息历史
    
    格式：
    [
      {"role": "system", "content": "系统提示词"},
      {"role": "user", "content": "用户消息1"},
      {"role": "assistant", "content": "助手回复1", "tool_calls": [...]},
      {"role": "tool", "content": "工具结果", "tool_call_id": "xxx"},
      ...
    ]
    """
    messages = [
        {"role": "system", "content": system_prompt}
    ]
    
    # 添加历史消息
    for msg in session.messages:
        if msg.role == MessageRole.USER:
            messages.append({"role": "user", "content": msg.content})
            
        elif msg.role == MessageRole.ASSISTANT:
            msg_dict = {"role": "assistant", "content": msg.content}
            
            # 添加工具调用
            if msg.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.args, ensure_ascii=False)
                        }
                    }
                    for tc in msg.tool_calls
                ]
            messages.append(msg_dict)
            
        elif msg.role == MessageRole.TOOL:
            messages.append({
                "role": "tool",
                "content": msg.content,
                "tool_call_id": msg.tool_call_id
            })
    
    # 添加新用户消息
    messages.append({"role": "user", "content": new_user_message.content})
    
    return messages
```

---

## 4️⃣ 工具调用机制

### 4.1 工具注册表

**文件**: `tools/tool_registry.py`

```python
class ToolRegistry:
    """工具注册表 - 管理所有可用工具"""
    
    def __init__(self):
        self._tools: Dict[str, Callable] = {}  # 工具函数
        self._tool_definitions: Dict[str, Dict[str, Any]] = {}  # 工具定义
    
    def register_tool(
        self,
        name: str,
        function: Callable,
        definition: Dict[str, Any]
    ) -> None:
        """注册工具"""
        self._tools[name] = function
        self._tool_definitions[name] = definition
        logger.info(f"Registered tool: {name}")
    
    def to_qwen_format(self) -> List[Dict[str, Any]]:
        """
        转换为 Qwen Function Calling 格式
        
        返回格式：
        [
          {
            "type": "function",
            "function": {
              "name": "knowledge_search",
              "description": "搜索知识库...",
              "parameters": {
                "type": "object",
                "properties": {...},
                "required": [...]
              }
            }
          }
        ]
        """
        qwen_tools = []
        
        for name, definition in self._tool_definitions.items():
            qwen_tools.append({
                "type": "function",
                "function": {
                    "name": definition["name"],
                    "description": definition["description"],
                    "parameters": definition["parameters"]
                }
            })
        
        return qwen_tools
    
    def execute_tool(self, name: str, args: Dict[str, Any]) -> Any:
        """
        执行工具
        
        Args:
            name: 工具名称
            args: 工具参数
        
        Returns:
            工具执行结果
        """
        tool = self.get_tool(name)
        
        if tool is None:
            raise ToolExecutionError(name, f"Tool '{name}' not found")
        
        try:
            logger.info(f"Executing tool: {name} with args: {args}")
            result = tool(**args)  # 🔥 调用工具函数
            logger.info(f"Tool {name} executed successfully")
            return result
        except Exception as e:
            error_msg = f"Tool execution failed: {str(e)}"
            logger.error(f"Tool {name} failed: {error_msg}")
            raise ToolExecutionError(name, error_msg)
```

### 4.2 知识库搜索工具

**文件**: `tools/knowledge_search.py`

```python
def knowledge_search(query: str, top_k: int = DEFAULT_TOP_K) -> Dict[str, Any]:
    """
    搜索知识库获取相关信息
    
    Args:
        query: 搜索查询
        top_k: 返回结果数量（默认 5）
    
    Returns:
        {
            "success": bool,
            "results": [
                {
                    "id": str,
                    "title": str,
                    "content": str,
                    "score": float
                }
            ],
            "total": int,
            "message": str
        }
    """
    try:
        logger.info(f"Knowledge search: query='{query}', top_k={top_k}")
        
        # 1️⃣ 生成查询向量
        query_embedding = generate_embedding(query, task_type="retrieval_query")
        
        # 2️⃣ 搜索知识库（向量检索）
        knowledge_store = get_knowledge_store()
        search_results = knowledge_store.search(
            query_embedding=query_embedding,
            top_k=top_k,
            active_only=True
        )
        
        # 3️⃣ 格式化结果
        results = []
        if search_results["ids"] and len(search_results["ids"][0]) > 0:
            for i, doc_id in enumerate(search_results["ids"][0]):
                metadata = search_results["metadatas"][0][i]
                distance = search_results["distances"][0][i]
                
                results.append({
                    "id": doc_id,
                    "title": metadata.get("title", ""),
                    "content": search_results["documents"][0][i],
                    "category": metadata.get("category", ""),
                    "score": 1.0 - distance  # 距离转相似度
                })
        
        message = f"找到 {len(results)} 条相关信息" if results else "未找到相关信息"
        
        logger.info(f"Knowledge search completed: {len(results)} results")
        
        return {
            "success": True,
            "results": results,
            "total": len(results),
            "message": message
        }
        
    except Exception as e:
        error_msg = f"Knowledge search failed: {str(e)}"
        logger.error(error_msg)
        return {
            "success": False,
            "results": [],
            "total": 0,
            "error": error_msg
        }


def get_tool_definition() -> Dict[str, Any]:
    """
    工具定义（Qwen Function Calling 格式）
    """
    return {
        "name": "knowledge_search",
        "description": """搜索知识库获取相关信息。

使用场景：
- 用户询问产品信息、政策、流程等问题时
- 需要查找具体的业务规则或说明时
- 回答用户问题前，优先检索知识库

注意：使用准确的关键词进行搜索，参考检索结果用自己的语言回答用户。
""",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或问题（使用简洁的关键词效果更好）"
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回结果数量（默认 5 条）",
                    "default": DEFAULT_TOP_K
                }
            },
            "required": ["query"]
        }
    }
```

---

## 5️⃣ 大模型调用

**文件**: `llm/qwen_client.py`

```python
@retry(
    retry=retry_if_exception_type((RequestFailure, ServiceUnavailableError)),
    wait=wait_exponential(multiplier=1, min=QWEN_API_RETRY_DELAY, max=60),
    stop=stop_after_attempt(QWEN_API_RETRY_ATTEMPTS)
)
def call_qwen(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    max_tokens: Optional[int] = None
) -> Dict[str, Any]:
    """
    调用 Qwen API（带重试机制）
    
    Args:
        messages: 对话消息列表
        tools: 工具定义（Function Calling）
        temperature: 采样温度（0-2，默认 0.7）
        top_p: 核采样参数（0-1，默认 0.9）
        max_tokens: 最大生成 token 数（默认 2000）
    
    Returns:
        Qwen API 响应
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "回复内容",
                        "tool_calls": [
                            {
                                "id": "call_xxx",
                                "type": "function",
                                "function": {
                                    "name": "knowledge_search",
                                    "arguments": "{\"query\": \"退货政策\"}"
                                }
                            }
                        ]
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 123,
                "completion_tokens": 456,
                "total_tokens": 579
            }
        }
    """
    # 确保 API Key 已设置
    _ensure_api_key()
    
    # 调用 DashScope SDK
    response = Generation.call(
        model=settings.model_name,  # "qwen3.5-plus" 等
        messages=messages,
        tools=tools,  # 工具定义
        result_format='message',  # 消息格式
        temperature=temperature or settings.qwen_temperature,
        top_p=top_p or settings.qwen_top_p,
        max_tokens=max_tokens or settings.qwen_max_tokens,
        stream=False  # 同步调用
    )
    
    # 检查状态码
    if response.status_code != 200:
        raise RequestFailure(f"Qwen API Error: {response.message}")
    
    return response.output
```

**调用示例**:

```python
# 输入消息
messages = [
    {"role": "system", "content": "你是闲鱼客服助手"},
    {"role": "user", "content": "如何退货？"}
]

# 工具定义
tools = [
    {
        "type": "function",
        "function": {
            "name": "knowledge_search",
            "description": "搜索知识库",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                },
                "required": ["query"]
            }
        }
    }
]

# 调用
response = call_qwen(messages=messages, tools=tools)

# 响应
print(response["choices"][0]["message"]["content"])
print(response["choices"][0]["message"]["tool_calls"])
```

---

## 6️⃣ 响应返回

### 6.1 成功响应

```python
# TurnResult 对象
TurnResult(
    success=True,
    response_text="根据退货政策，您可以在收到商品后7天内申请退货...",
    tool_calls=[
        {
            "id": "call_abc123",
            "name": "knowledge_search",
            "args": {"query": "退货政策", "top_k": 5},
            "result": {
                "success": True,
                "results": [
                    {
                        "id": "doc_001",
                        "title": "退货政策",
                        "content": "7天无理由退货...",
                        "score": 0.95
                    }
                ],
                "total": 1
            }
        }
    ],
    new_messages=[
        Message(role="user", content="如何退货？"),
        Message(role="assistant", content="...", tool_calls=[...]),
        Message(role="tool", content="{...}", tool_call_id="call_abc123")
    ],
    metadata={
        "duration_ms": 1234,
        "turn_counter": 1
    }
)
```

### 6.2 最终 HTTP 响应

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "response": "根据退货政策，您可以在收到商品后7天内申请退货。请在'我的订单'中找到对应订单，点击'申请退货'按钮，填写退货原因并提交。审核通过后，您将收到退货地址。",
  "status": "active",
  "turn_counter": 1,
  "metadata": {
    "duration_ms": 1234
  }
}
```

---

## 7️⃣ 完整流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                        HTTP POST /chat                           │
│  Body: {"query": "如何退货?", "session_id": null}               │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    chat.py::chat_sync()                          │
│  1. 接收请求                                                     │
│  2. 创建 AgentExecutor                                           │
│  3. 调用 executor.run()                                          │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                  executor.py::run()                              │
│  1. 加载/创建 Session                                            │
│  2. While True:                                                  │
│     - 检查最大轮数                                               │
│     - execute_turn() ←────────┐                                 │
│     - 检查循环                 │                                 │
│     - 检查任务完成             │                                 │
│  3. 保存 Session               │                                 │
│  4. 返回结果                   │                                 │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    turn.py::execute_turn()                       │
│  1. 创建用户消息                                                 │
│  2. 构建消息历史（包含系统提示词 + 历史对话）                    │
│  3. 获取工具定义（tools_registry.to_qwen_format()）             │
│  4. call_qwen(messages, tools) ────────┐                        │
│  5. 解析响应                           │                        │
│  6. 执行工具调用 ──────────────────────┤                        │
│  7. 返回 TurnResult                    │                        │
└────────────────────────────────────────┼────────────────────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    │                    │                    │
                    ▼                    ▼                    ▼
    ┌───────────────────────┐  ┌─────────────────┐  ┌────────────────┐
    │  qwen_client.py       │  │ tool_registry.py│  │ 返回到 chat.py │
    │  ::call_qwen()        │  │ ::execute_tool()│  │                │
    ├───────────────────────┤  ├─────────────────┤  │ ChatResponse(  │
    │ 1. _ensure_api_key()  │  │ 1. 获取工具函数  │  │   session_id,  │
    │ 2. Generation.call(   │  │ 2. tool(**args) │  │   response,    │
    │      model=qwen3.5-plus,  │  │ 3. 返回结果     │  │   status,      │
    │      messages=[...],  │  │                 │  │   metadata     │
    │      tools=[...],     │  │ 示例：          │  │ )              │
    │      temperature=0.7, │  │ knowledge_search│  └────────────────┘
    │      stream=False     │  │   (query, top_k)│
    │    )                  │  │ ↓               │
    │ 3. 返回 response.output│  │ - generate_     │
    │                       │  │   embedding()   │
    │ 响应格式：            │  │ - knowledge_    │
    │ {                     │  │   store.search()│
    │   "choices": [{       │  │ - 返回搜索结果  │
    │     "message": {      │  │                 │
    │       "content": "...",│  └─────────────────┘
    │       "tool_calls": [ │
    │         {             │
    │           "id": "...",│
    │           "function": {│
    │             "name": "knowledge_search",
    │             "arguments": "{...}"
    │           }           │
    │         }             │
    │       ]               │
    │     }                 │
    │   }]                  │
    │ }                     │
    └───────────────────────┘
```

---

## 8️⃣ 关键数据结构

### 8.1 Session

```python
@dataclass
class Session:
    session_id: str  # 会话 ID
    user_id: Optional[str]  # 用户 ID
    messages: List[Message]  # 消息历史
    turn_counter: int = 0  # 轮次计数
    status: str = SessionStatus.ACTIVE  # 状态：active/completed/error
    terminate_reason: Optional[str] = None  # 终止原因
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
```

### 8.2 Message

```python
@dataclass
class Message:
    role: str  # user/assistant/tool/system
    content: str  # 消息内容
    timestamp: datetime
    tool_calls: Optional[List[ToolCall]] = None  # 工具调用
    tool_call_id: Optional[str] = None  # 工具调用 ID（tool 角色）
    tool_name: Optional[str] = None  # 工具名称
```

### 8.3 ToolCall

```python
@dataclass
class ToolCall:
    id: str  # 工具调用 ID
    name: str  # 工具名称
    args: Dict[str, Any]  # 工具参数
    status: str = ToolCallStatus.PENDING  # 状态
    result: Optional[Any] = None  # 执行结果
    error: Optional[str] = None  # 错误信息
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
```

---

## 9️⃣ 配置参数

**文件**: `config/settings.py`

```python
class Settings(BaseSettings):
    # API 配置
    api_key: str  # 通义千问 API Key
    model_name: str = "qwen3.5-plus"
    
    # Qwen 参数
    qwen_temperature: float = 0.7  # 创造性（0-2）
    qwen_top_p: float = 0.9  # 核采样
    qwen_max_tokens: int = 2000  # 最大 token
    
    # Agent 配置
    max_turns: int = 10  # 最大轮数
    turn_timeout_seconds: int = 60  # 单轮超时
    loop_detection_threshold: int = 3  # 循环检测阈值
    
    # 知识库配置
    default_top_k: int = 5  # 默认检索数量
    
    # Redis 配置
    redis_url: str = "redis://localhost:6379"
    session_ttl: int = 3600  # Session 过期时间（秒）
```

---

## 🔟 日志示例

```
2025-12-29 10:00:00.123 | INFO | Chat request: query='如何退货?', session_id=None
2025-12-29 10:00:00.125 | INFO | Created new session: 550e8400-e29b-41d4-a716-446655440000
2025-12-29 10:00:00.126 | INFO | Turn 1 started: session=550e8400..., query='如何退货?'
2025-12-29 10:00:00.127 | INFO | Calling Qwen API for turn 1
2025-12-29 10:00:01.234 | INFO | Tool call: session=550e8400..., tool=knowledge_search, id=call_abc123, args={'query': '退货政策', 'top_k': 5}
2025-12-29 10:00:01.345 | INFO | Knowledge search: query='退货政策', top_k=5
2025-12-29 10:00:01.456 | INFO | Knowledge search completed: 3 results
2025-12-29 10:00:01.457 | INFO | Tool knowledge_search executed successfully
2025-12-29 10:00:01.458 | INFO | Tool result: session=550e8400..., tool=knowledge_search, id=call_abc123, success=True, duration_ms=111
2025-12-29 10:00:01.459 | INFO | Turn 1 completed: session=550e8400..., duration_ms=1333, success=True
2025-12-29 10:00:01.460 | INFO | Agent completed: session=550e8400..., status=active, turns=1, duration_ms=1335
```

---

## 📝 总结

### 关键流程

1. **请求接收**: FastAPI `/chat` 接口接收用户查询
2. **Session 管理**: 加载或创建会话，维护对话历史
3. **消息构建**: 组装系统提示词 + 历史对话 + 用户问题
4. **工具注册**: 将可用工具转换为 Function Calling 格式
5. **大模型调用**: 调用通义千问 API，获取回复和工具调用指令
6. **工具执行**: 根据模型返回的 tool_calls 执行相应工具
7. **结果组装**: 将模型回复和工具结果组装成最终响应
8. **Session 更新**: 保存新消息到会话历史
9. **响应返回**: 返回 JSON 响应给客户端

### 设计亮点

- **重试机制**: 使用 `tenacity` 库实现 API 调用自动重试
- **循环检测**: 检测工具调用循环，防止死循环
- **最大轮数**: 限制单次请求的轮数，防止资源耗尽
- **流式响应**: 支持 SSE 实时返回响应
- **工具抽象**: ToolRegistry 提供统一的工具注册和执行接口
- **Session 持久化**: Redis 存储会话，支持多轮对话

---

**生成时间**: 2025-12-29  
**作者**: AI Assistant  
**版本**: 1.0
