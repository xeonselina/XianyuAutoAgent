# System Prompt Architecture Analysis: Tool Continuation & Message Flow

**Analysis Date:** 2026-04-12  
**Key Files:**
- `/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/agent/turn.py` (main executor)
- `/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/agent/executor.py` (orchestrator)
- `/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/llm/qwen_client.py` (LLM client)
- `/Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu/xianyu_interceptor/conversation_store.py` (persistence)

---

## Executive Summary

**KEY FINDING:** On tool-continuation turns (`is_tool_continue=True`), **the FULL system prompt is RE-SENT** to the LLM, identical to the initial turn. This includes:

1. The base system prompt (loaded from DB or code default)
2. Injected item_info slot (if available)
3. Injected context_summary (if available)

The system prompt is **NOT** omitted on tool-continuation turns. Every turn (first, tool-continuation, final) sends the complete system prompt.

---

## Message Flow Architecture

### High-Level Overview

```
User Query
    ↓
AgentExecutor.run() 
    ↓ (detect_skills + get_prompt_key)
    ↓ (load/create session)
    ↓ 
┌─────────────────────────────────────┐
│ Turn 1 (is_tool_continue=False)     │
│ - Load system prompt from DB/code   │
│ - Build message history with        │
│   system message + history + new    │
│   user message                      │
│ - Call Qwen API                     │
│ - Process response (text + tools)   │
│ - Execute tools, create tool msgs   │
└─────────────────────────────────────┘
    ↓ (if tool_calls exist)
┌─────────────────────────────────────┐
│ Tool Continuation Turns             │
│ (is_tool_continue=True)             │
│ - Load same system prompt AGAIN     │
│ - Build message history with:       │
│   • system message (full prompt)    │
│   • all historical msgs             │
│   • recent tool messages            │
│ - Call Qwen API                     │
│ - Process response                  │
│ - If more tools: loop again         │
│ - If no tools & text: DONE          │
└─────────────────────────────────────┘
    ↓
Return response_text
```

---

## Part 1: System Prompt Loading

### 1.1 Loading Strategy (turn.py:635-700)

**Function:** `_load_system_prompt(prompt_key: str = "rental_system") -> str`

**Flow:**
1. **Check in-memory cache** (5-minute TTL)
   - Per-key caching: `_system_prompt_cache: dict[str, tuple]`
   - Location: turn.py:616-618
   - If cached and fresh: return immediately

2. **Try database** (MySQL system_prompts table)
   - Calls: `PromptStore.get_active(prompt_key)`
   - PromptStore location: `/ai_kefu/storage/prompt_store.py`
   - Looks for: `active=True` record matching prompt_key
   - If found: render template (expand date variables)

3. **Fallback to code default** if DB fails
   - For "rental_system" → `get_rental_system_prompt()`
   - For other keys → falls back to rental system prompt

**Code Path:**
```python
# turn.py:197-204
if system_prompt is None:
    _t0 = datetime.utcnow()
    system_prompt = _load_system_prompt(prompt_key)  # <-- Loaded here
    _t1 = datetime.utcnow()
    logger.info(f"[perf] _load_system_prompt(key={prompt_key!r}): ...")
```

### 1.2 System Prompt Content Composition

Once loaded, the base prompt can be **injected with two additional context slots:**

**Location:** turn.py:206-246

#### a) Item Info Slot (Fixed Product Context)
```python
# turn.py:209-240
item_info = session.context.get("item_info")
if item_info and item_info.get("success"):
    item_slot = """## 当前商品信息
商品标题：{title}
价格：{price} 元
当前咨询型号：{model}      [OPTIONAL - detected from title]
商品描述：{desc}           [OPTIONAL]
商品状态：{status_label}
所在地：{location}         [OPTIONAL]"""
    system_prompt = system_prompt + f"\n\n{item_slot}"
```

#### b) Context Summary Slot (Conversation History)
```python
# turn.py:243-246
context_summary = session.context.get("context_summary", "")
if context_summary:
    system_prompt = system_prompt + f"\n\n## 之前的对话上下文摘要\n{context_summary}"
```

**This injected system prompt is the FINAL version sent to the LLM on ALL turns.**

---

## Part 2: First Turn Message Construction

### 2.1 Normal Turn (is_tool_continue=False)

**Location:** turn.py:254-266

```python
if not is_tool_continue:
    user_msg = Message(
        role=MessageRole.USER,
        content=user_message,
        timestamp=datetime.utcnow()
    )
    new_messages.append(user_msg)
    
    # Build message history with new user message
    messages = _build_message_history(session, user_msg, system_prompt)
```

**Function:** `_build_message_history()` (turn.py:550-604)

**Output structure:**
```python
[
    {"role": "system", "content": system_prompt},  # <-- FULL PROMPT HERE
    
    # Historical messages (from session.messages):
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "...", "tool_calls": [...]},
    {"role": "tool", "content": "...", "tool_call_id": "..."},
    
    # New user message:
    {"role": "user", "content": user_message}
]
```

---

## Part 3: TOOL CONTINUATION TURNS

### 3.1 Key Finding: System Prompt IS Re-Sent

**Location:** turn.py:267-296

When `is_tool_continue=True`:

```python
else:
    # For tool continuation, build message history without adding new user message
    # The tool results are already in session.messages
    messages = [{"role": "system", "content": system_prompt}]  # <-- FULL PROMPT AGAIN
    
    # Add all historical messages (including recent tool results)
    for msg in session.messages:
        if msg.role == MessageRole.USER:
            messages.append({"role": "user", "content": msg.content})
        elif msg.role == MessageRole.ASSISTANT:
            msg_dict = {"role": "assistant", "content": msg.content}
            if msg.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json_serialize(tc.args)
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
```

### 3.2 Message Structure on Tool Continuation

**Exact structure passed to Qwen API:**

```python
[
    {
        "role": "system",
        "content": system_prompt  # <-- FULL prompt with all injections
    },
    
    # All prior conversation (from session.messages):
    {"role": "user", "content": "用户第一条消息"},
    {"role": "assistant", "content": "助手回复1", "tool_calls": [...]},
    {"role": "tool", "content": "工具结果1", "tool_call_id": "call_xxx"},
    
    # ... potentially more user/assistant/tool exchanges ...
    
    {"role": "assistant", "content": "助手回复2", "tool_calls": [...]},  # <-- Just executed
    {"role": "tool", "content": "工具结果2", "tool_call_id": "call_yyy"},  # <-- Added in current turn
    
    # NOTE: NO new user message added on tool continuation!
]
```

### 3.3 System Prompt Loading on Tool Continuation

**The system prompt is loaded FRESH on every turn:**

```python
# turn.py:196-204 (executed EVERY turn, including tool-continuation)
if system_prompt is None:
    _t0 = datetime.utcnow()
    system_prompt = _load_system_prompt(prompt_key)  # <-- Reloaded
    _t1 = datetime.utcnow()
    logger.info(f"[perf] _load_system_prompt(key={prompt_key!r}): ...")
```

**However, in executor.py lines 338-345, the same prompt_key is used across ALL turns in a run():**

```python
# executor.py:338-345 (called in a loop for each turn)
turn_result = execute_turn(
    session=session,
    user_message=query,
    tools_registry=self.tools_registry,
    is_tool_continue=not is_first_turn,  # <-- Flag for tool continuation
    active_skill_tools=active_skill_tools,
    prompt_key=active_prompt_key,  # <-- SAME prompt_key for all turns
)
```

The `prompt_key` is set once at the start and reused:

```python
# executor.py:300-307
active_skills = detect_skills(query, session_context=session.context)
active_skill_tools = get_active_tool_names(active_skills)
active_prompt_key = get_prompt_key(active_skills)  # <-- Set ONCE
logger.info(
    f"[skill_selector] active_skills={active_skills}, "
    f"active_tool_count={len(active_skill_tools)}, "
    f"prompt_key={active_prompt_key!r}"
)
```

---

## Part 4: Message Validation

### 4.1 Validation on Every Turn

**Location:** turn.py:300

```python
# Validate message sequence (auto_fix removes orphan tool messages
# that may result from context summarisation trimming)
is_valid, error_msg = validate_message_sequence(messages, auto_fix=True)
if not is_valid:
    logger.error(f"Invalid message sequence: {error_msg}")
    raise ValueError(f"Invalid message sequence: {error_msg}")
```

**Validation Rules (turn.py:40-106):**
- Assistant message with tool_calls MUST have corresponding tool messages
- Tool message tool_call_id must match a preceding assistant tool_call
- User message must not have pending unresolved tool_call_ids
- All tool_calls must be resolved by end of message sequence

---

## Part 5: Persistence - agent_turns Table

### 5.1 Schema

**Location:** conversation_store.py:122-150

```sql
CREATE TABLE IF NOT EXISTS agent_turns (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    turn_number INT NOT NULL,
    interaction_id VARCHAR(255),              -- Groups all turns from one user message
    local_turn_number INT,                    -- Turn number within interaction (1, 2, 3...)
    user_query TEXT,                          -- Original user query
    
    llm_input LONGTEXT,                       -- FULL messages array sent to LLM (JSON)
    llm_output LONGTEXT,                      -- Raw LLM response (JSON)
    response_text TEXT,                       -- Extracted text from response
    
    tool_calls JSON,                          -- Tool calls in this turn
    tool_results JSON,                        -- Tool execution results
    
    duration_ms INT,
    success BOOLEAN,
    error_message TEXT,
    
    confidence_percent INT,                   -- Confidence score (0-100)
    response_suppressed BOOLEAN,              -- Suppressed by confidence guard?
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_session_id (session_id),
    INDEX idx_session_turn (session_id, turn_number),
    INDEX idx_interaction_id (interaction_id),
    INDEX idx_created_at (created_at)
)
```

### 5.2 What Gets Persisted

**Location:** executor.py:366-396

```python
if self.conversation_store:
    try:
        self.conversation_store.save_turn(
            session_id=session.session_id,
            turn_number=session.turn_counter,
            user_query=query,
            llm_input=turn_result.llm_input,           # <-- Full messages
            llm_output=turn_result.llm_output,         # <-- Raw response
            response_text=turn_result.response_text,   # <-- Text only
            tool_calls=turn_result.tool_calls,
            tool_results=tool_results,
            duration_ms=turn_result.metadata.get("duration_ms"),
            success=turn_result.success,
            error_message=turn_result.error_message,
            interaction_id=interaction_id,             # <-- Groups all turns
            local_turn_number=local_turn_counter,      # <-- 1, 2, 3...
            confidence_percent=turn_result.metadata.get("confidence_percent"),
            response_suppressed=turn_result.metadata.get("response_suppressed", False)
        )
    except Exception as e:
        logger.warning(f"Failed to persist turn data (non-fatal): {e}")
```

**Captured Data (turn.py:321-322):**

```python
# Capture LLM input/output for debugging
llm_input_snapshot = [dict(m) for m in messages]  # Shallow copy of messages sent to LLM
llm_output_snapshot = response  # Raw LLM response
```

So `agent_turns.llm_input` contains the EXACT messages sent, INCLUDING the full system prompt.

---

## Part 6: LLM API Call

### 6.1 Qwen API Call

**Location:** turn.py:313-318

```python
# Call Qwen API
logger.info(f"Calling Qwen API for turn {turn_counter}")
_t_qwen_start = datetime.utcnow()
response = call_qwen(messages=messages, tools=tools if tools else None)
_t_qwen_end = datetime.utcnow()
logger.info(f"[perf] call_qwen: {int((_t_qwen_end - _t_qwen_start).total_seconds() * 1000)}ms")
```

**Function:** `call_qwen()` in qwen_client.py:107-158

```python
@retry(
    retry=retry_if_exception_type(_RETRYABLE_ERRORS),
    wait=wait_exponential(multiplier=1, min=QWEN_API_RETRY_DELAY, max=QWEN_API_RETRY_MAX_DELAY),
    stop=stop_after_attempt(QWEN_API_RETRY_ATTEMPTS)
)
def call_qwen(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None
) -> Dict[str, Any]:
    client = _get_client()
    
    effective_model = model or settings.model_name
    
    kwargs: Dict[str, Any] = {
        "model": effective_model,
        "messages": messages,  # <-- Full message history with system prompt
        "temperature": temperature or settings.qwen_temperature,
        "top_p": top_p or settings.qwen_top_p,
        "max_tokens": max_tokens or settings.qwen_max_tokens,
        "stream": False,
    }
    if tools:
        kwargs["tools"] = tools
    
    completion = client.chat.completions.create(**kwargs)
    return _completion_to_dict(completion)
```

### 6.2 Key Parameters
- **messages**: Full history with system prompt (ALWAYS included)
- **tools**: Filtered by active_skill_tools (if specified), ALL tools otherwise
- **temperature**: From settings
- **max_tokens**: From settings
- **model**: Qwen model name (qwen-3.5-plus or qwen-3.5-plus-flash)

---

## Part 7: Tool Execution & Continuation Loop

### 7.1 Tool Execution

**Location:** turn.py:394-492

When LLM returns tool_calls:

```python
if tool_calls_data:
    for tc in tool_calls_data:
        tool_name = tc["function"]["name"]
        tool_call_id = tc["id"]
        
        try:
            # Parse & execute tool
            args = json.loads(tc["function"]["arguments"])
            result = tools_registry.execute_tool(tool_name, args)
            
            # Create tool response message
            tool_msg = Message(
                role=MessageRole.TOOL,
                content=json_serialize(result),
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                timestamp=datetime.utcnow()
            )
            new_messages.append(tool_msg)
        except Exception as e:
            # Error handling...
            pass
```

### 7.2 Continuation Loop in Executor

**Location:** executor.py:326-509

```python
while True:
    # Check loop conditions...
    
    # Execute turn (first=False means tool-continuation)
    turn_result = execute_turn(
        session=session,
        user_message=query,
        tools_registry=self.tools_registry,
        is_tool_continue=not is_first_turn,  # <-- Toggle for tool continuation
        active_skill_tools=active_skill_tools,
        prompt_key=active_prompt_key,
    )
    
    is_first_turn = False
    
    if not turn_result.success:
        # Error handling...
        return {...}
    
    # Update session with new messages
    session.messages.extend(turn_result.new_messages)
    session.turn_counter += 1
    
    # ... persist turn ...
    
    # Check if task completed
    task_completed = any(
        tc_dict["name"] == TOOL_COMPLETE_TASK
        for tc_dict in turn_result.tool_calls
    )
    
    if task_completed:
        session.status = SessionStatus.COMPLETED
        response_text = turn_result.response_text
        break
    
    # Update response text
    response_text = turn_result.response_text
    
    # If there were tool calls, continue to next turn to get LLM's response
    if turn_result.tool_calls:
        logger.info(f"Turn {session.turn_counter} had {len(turn_result.tool_calls)} tool calls, continuing to next turn")
        continue  # <-- LOOP BACK HERE
    
    # If no tool calls and we have response text, we're done
    if response_text:
        last_turn_metadata = turn_result.metadata
        # ... handle confidence guard suppression ...
        break
```

---

## Part 8: Concrete Example - Two-Turn Interaction

### Scenario: User asks about rental availability

**User Query:** "4月15号怎么租呢？" (How to rent on Apr 15?)

---

### Turn 1 (is_tool_continue=False)

**Messages sent to Qwen:**
```python
[
    {
        "role": "system",
        "content": """你是闲鱼平台上一个手机租赁卖家的客服...
        
## 当前商品信息
商品标题：iPhone 14 Pro Max
价格：2999 元
当前咨询型号：X300U

## 之前的对话上下文摘要
【老客户】该用户之前有过付款记录。
用户：你好，想租个手机
客服：好的，想租哪个型号呢？
        """
    },
    {
        "role": "user",
        "content": "4月15号怎么租呢？"
    }
]
```

**Qwen Response:**
```json
{
    "choices": [
        {
            "message": {
                "content": "好的，让我查一下4月15号的档期",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "check_availability",
                            "arguments": "{\"receive_date\": \"2026-04-15\", \"model\": \"X300U\"}"
                        }
                    }
                ]
            }
        }
    ]
}
```

**Session state after Turn 1:**
```
session.messages = [
    Message(role=USER, content="4月15号怎么租呢？"),
    Message(role=ASSISTANT, content="好的，让我查一下4月15号的档期", 
            tool_calls=[ToolCall(id="call_123", name="check_availability", ...)]),
    Message(role=TOOL, content="{\"available\": true, \"price\": 168}", 
            tool_call_id="call_123")
]
session.turn_counter = 1
```

---

### Turn 2 (is_tool_continue=True)

**Messages sent to Qwen:**
```python
[
    {
        "role": "system",
        "content": """你是闲鱼平台上一个手机租赁卖家的客服...
        
## 当前商品信息
商品标题：iPhone 14 Pro Max
价格：2999 元
当前咨询型号：X300U

## 之前的对话上下文摘要
【老客户】该用户之前有过付款记录。
用户：你好，想租个手机
客服：好的，想租哪个型号呢？
        """
    },
    {
        "role": "user",
        "content": "4月15号怎么租呢？"
    },
    {
        "role": "assistant",
        "content": "好的，让我查一下4月15号的档期",
        "tool_calls": [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "check_availability",
                    "arguments": "{\"receive_date\": \"2026-04-15\", \"model\": \"X300U\"}"
                }
            }
        ]
    },
    {
        "role": "tool",
        "content": "{\"available\": true, \"price\": 168}",
        "tool_call_id": "call_123"
    }
]
```

**Key observation:** System prompt is RE-SENT identically!

**Qwen Response (no more tool calls):**
```json
{
    "choices": [
        {
            "message": {
                "content": "4月15号有货，X300U 168元/天，要租吗？",
                "tool_calls": []
            }
        }
    ]
}
```

**Agent returns:** "4月15号有货，X300U 168元/天，要租吗？"

---

## Part 9: Summary Table

| Aspect | Turn 1 (First) | Turn N (Tool-Continuation) |
|--------|---|---|
| **is_tool_continue** | False | True |
| **User message added?** | YES | NO |
| **System prompt sent?** | YES (full) | YES (full, identical) |
| **Prompt loaded fresh?** | YES | YES (from cache) |
| **Message history** | [system, history, NEW user] | [system, history with tool msgs, NO new user] |
| **Tools available?** | Filtered by active_skill_tools | Same filtered set |
| **Validation** | YES | YES |
| **Persisted to DB?** | YES (llm_input + llm_output) | YES (llm_input + llm_output) |

---

## Part 10: Performance Characteristics

### System Prompt Loading

**Location:** turn.py:615-618 (5-minute cache)

```python
_system_prompt_cache: dict[str, tuple] = {}
_SYSTEM_PROMPT_CACHE_TTL = 300  # 5 minutes
```

**Performance impact:**
- First turn: DB query + render (100-300ms)
- Tool-continuation turns: Cache hit (0-2ms)

**Example timing:** turn.py:201-203
```
[perf] _load_system_prompt(key='rental_system'): 150ms
[perf] call_qwen: 2345ms
[perf] tool_execution_total (1 tools): 123ms
```

### Message Array Size

- **Turn 1:** system + historical + 1 user = 3+ messages
- **Turn 2:** system + historical + 1 user + 1 assistant + 1 tool = 6 messages
- **Turn 3+:** Grows with each tool call

System prompt contributes ~2-5KB per turn (typical).

---

## Conclusions

### Key Findings

1. **System prompt is ALWAYS included** on every turn, including tool-continuation
2. **The prompt is IDENTICAL** across all turns within a single run()
3. **The prompt is loaded fresh** each turn (but cached in-memory for 5 minutes)
4. **Tool-continuation does NOT omit the system prompt** — this is essential for Qwen to maintain context
5. **All messages (including system prompt) are persisted** to agent_turns.llm_input in JSON
6. **Tool results are injected** as tool messages (role=tool) in the same conversation thread
7. **Skill-based filtering** is applied once and reused across all turns (reducing prompt size via active_skill_tools)

### Architectural Rationale

The design ensures:
- **Consistency:** LLM always has full context from start
- **Determinism:** Same instructions apply to tool-continuation logic
- **Debuggability:** Full message history in agent_turns table shows exact LLM input/output
- **Flexibility:** Prompts can be updated via DB (with 5-min cache TTL) without code change

