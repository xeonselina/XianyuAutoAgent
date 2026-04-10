"""
Single turn execution logic.
T042 - Execute one turn of agent conversation.
"""

import json
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Set
from ai_kefu.agent.types import TurnResult
from ai_kefu.models.session import Session, Message, ToolCall
from ai_kefu.config.constants import MessageRole, ToolCallStatus
from ai_kefu.llm.qwen_client import call_qwen, call_qwen_fast
from ai_kefu.tools.tool_registry import ToolRegistry
from ai_kefu.utils.logging import logger, log_turn_start, log_turn_end, log_tool_call, log_tool_result
from ai_kefu.prompts.rental_system_prompt import get_rental_system_prompt, render_system_prompt
from ai_kefu.storage.prompt_store import PromptStore
from ai_kefu.config.settings import settings


def json_serialize(obj: Any) -> str:
    """
    Safely serialize objects to JSON, handling datetime and other non-serializable types.
    
    Args:
        obj: Object to serialize
        
    Returns:
        JSON string
    """
    def default_handler(o):
        """Handle non-serializable objects."""
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        # Add more type handlers as needed
        return str(o)
    
    return json.dumps(obj, ensure_ascii=False, default=default_handler)


def validate_message_sequence(messages: List[Dict[str, Any]], *, auto_fix: bool = False) -> tuple[bool, str]:
    """
    Validate that message sequence follows Qwen API requirements.
    
    An assistant message with tool_calls must be followed by tool messages
    for each tool_call_id.
    
    Args:
        messages: List of message dicts to validate.
        auto_fix: If True, silently remove orphan tool messages (tool messages
                  whose tool_call_id doesn't match any preceding assistant
                  tool_call) instead of just logging a warning.  The *messages*
                  list is modified **in-place**.
    
    Returns:
        (is_valid, error_message)
    """
    pending_tool_call_ids = set()

    orphan_indices: List[int] = []
    
    for i, msg in enumerate(messages):
        role = msg.get("role")
        
        if role == "assistant":
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                # Collect all tool_call_ids that need responses
                for tc in tool_calls:
                    pending_tool_call_ids.add(tc["id"])
                logger.debug(f"Message[{i}] (assistant): added {len(tool_calls)} pending tool_call_ids: {pending_tool_call_ids}")
        
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id")
            if tool_call_id in pending_tool_call_ids:
                pending_tool_call_ids.remove(tool_call_id)
                logger.debug(f"Message[{i}] (tool): resolved tool_call_id={tool_call_id}, remaining: {pending_tool_call_ids}")
            else:
                if auto_fix:
                    logger.warning(
                        f"Message[{i}] (tool): orphan tool_call_id={tool_call_id} "
                        f"(no matching assistant tool_call), auto-removing"
                    )
                    orphan_indices.append(i)
                else:
                    logger.warning(f"Message[{i}] (tool): unexpected tool_call_id={tool_call_id}")
        
        elif role == "user":
            # A new user message means any pending tool calls should have been resolved
            if pending_tool_call_ids:
                error_msg = f"Message[{i}] (user): found user message but {len(pending_tool_call_ids)} tool_call_ids are still pending: {pending_tool_call_ids}"
                logger.error(error_msg)
                return False, error_msg
    
    # Remove orphan tool messages (iterate in reverse to preserve indices)
    if orphan_indices:
        for idx in reversed(orphan_indices):
            messages.pop(idx)
        logger.info(f"Auto-fixed: removed {len(orphan_indices)} orphan tool message(s)")
    
    # At the end, all tool calls should be resolved
    if pending_tool_call_ids:
        error_msg = f"End of messages: {len(pending_tool_call_ids)} tool_call_ids still pending: {pending_tool_call_ids}"
        logger.error(error_msg)
        return False, error_msg
    
    return True, ""


def _estimate_response_confidence_percent(
    user_message: str,
    response_text: str,
    tool_calls_summary: str = ""
) -> int:
    """
    使用轻量二次评估给出回答置信度（0~100）。

    说明：这里是启发式置信度，不等同于模型真实概率。
    tool_calls_summary: 本次交互中工具调用的摘要，帮助评估器判断回复中的数据是否有依据。
    """
    tool_context = ""
    if tool_calls_summary:
        tool_context = f"""
工具调用记录（回复中的数据来源）：
{tool_calls_summary}
"""

    prompt = f"""请评估下面客服回复对用户问题的置信度（0-100），仅返回一个整数。

用户消息：{user_message}
客服回复：{response_text}
{tool_context}
评分标准：
- 回复内容有工具调用结果作为依据，信息明确：85-100
- 信息明确且有依据，不猜测：80-100
- 基本合理但有不确定成分：60-79
- 可能答非所问或存在明显猜测：0-59

注意：如果客服回复中的具体数据（如价格、库存、日期等）来自工具调用结果，应视为有依据的信息，给予较高置信度。

只返回数字，不要其他内容。"""

    try:
        _t_conf_start = datetime.utcnow()
        response = call_qwen_fast(
            messages=[
                {"role": "system", "content": "你是严格的客服回复置信度评估器，只输出0到100之间的整数。"},
                {"role": "user", "content": prompt}
            ],
            tools=None,
            max_tokens=16,
            temperature=0.0,
            model=settings.model_name_light,  # 轻量任务，使用 flash 模型降低成本
        )
        _t_conf_end = datetime.utcnow()
        _conf_ms = int((_t_conf_end - _t_conf_start).total_seconds() * 1000)
        logger.info(f"[perf] confidence_guard_call_qwen: {_conf_ms}ms")
        content = response["choices"][0]["message"].get("content", "").strip()
        confidence = int("".join(ch for ch in content if ch.isdigit()) or "0")
        return max(0, min(100, confidence))
    except Exception as e:
        _t_conf_end = datetime.utcnow()
        _conf_ms = int((_t_conf_end - _t_conf_start).total_seconds() * 1000)
        logger.warning(f"Confidence estimation failed after {_conf_ms}ms, fallback to 100: {e}")
        return 100


def execute_turn(
    session: Session,
    user_message: str,
    tools_registry: ToolRegistry,
    system_prompt: str = None,
    is_tool_continue: bool = False,
    active_skill_tools: Optional[Set[str]] = None,
) -> TurnResult:
    """
    Execute one turn of conversation.

    Args:
        session: Current session
        user_message: User's message (only used if is_tool_continue=False)
        tools_registry: Tool registry
        system_prompt: System prompt (if None, uses default with current date)
        is_tool_continue: If True, don't add new user message (for tool result continuation)
        active_skill_tools: Optional set of tool names to expose to the LLM.
            When provided only those tools are included in the Qwen request,
            reducing per-turn prompt size.  Pass ``None`` to include all tools.

    Returns:
        TurnResult with turn execution results
    """
    # Use default system prompt with current date if not provided
    if system_prompt is None:
        _t0 = datetime.utcnow()
        system_prompt = _load_system_prompt()
        _t1 = datetime.utcnow()
        logger.info(f"[perf] _load_system_prompt: {int((_t1 - _t0).total_seconds() * 1000)}ms")
    
    # Inject item info into system prompt if available (fixed context slot)
    # This is prefetched once at session start so the LLM knows the exact
    # product title / price / model without asking the buyer.
    item_info = session.context.get("item_info")
    if item_info and item_info.get("success"):
        import re as _re
        item_status_label = "在售" if item_info.get("item_status") == 0 else "已售/下架"
        item_slot_lines = [
            "## 当前商品信息",
            f"商品标题：{item_info.get('title', '')}",
            f"价格：{item_info.get('price', '')} 元",
        ]
        # Extract device model from title so LLM never needs to ask the buyer
        _title = item_info.get("title", "")
        _model_patterns = ["X300Ultra", "X300Pro", "X300U", "X300P", "X200Ultra", "X200U"]
        _detected_model: Optional[str] = None
        for _pat in _model_patterns:
            if _re.search(_pat, _title, _re.IGNORECASE):
                _detected_model = _pat
                break
        if _detected_model:
            item_slot_lines.insert(1, f"当前咨询型号：{_detected_model}")
            logger.info(f"[item_model] Detected model={_detected_model!r} from title={_title!r}")
        else:
            logger.debug(f"[item_model] No known model pattern found in title={_title!r}")
        desc = item_info.get("desc", "")
        if desc:
            item_slot_lines.append(f"商品描述：{desc}")
        item_slot_lines.append(f"商品状态：{item_status_label}")
        location = item_info.get("location", "")
        if location:
            item_slot_lines.append(f"所在地：{location}")
        item_slot = "\n".join(item_slot_lines)
        system_prompt = system_prompt + f"\n\n{item_slot}"
        logger.info(f"Injected item_info (item_id={item_info.get('item_id', '')}) into system prompt")

    # Inject context summary into system prompt if available
    context_summary = session.context.get("context_summary", "")
    if context_summary:
        system_prompt = system_prompt + f"\n\n## 之前的对话上下文摘要\n以下是与该用户之前对话的摘要，请基于此理解用户需求的完整上下文：\n{context_summary}"
        logger.info(f"Injected context summary ({len(context_summary)} chars) into system prompt")
    
    start_time = datetime.utcnow()
    turn_counter = session.turn_counter + 1
    
    log_turn_start(session.session_id, turn_counter, user_message)
    
    try:
        new_messages = []
        
        # Add user message only if this is not a tool continuation turn
        if not is_tool_continue:
            user_msg = Message(
                role=MessageRole.USER,
                content=user_message,
                timestamp=datetime.utcnow()
            )
            new_messages.append(user_msg)
            
            # Build message history with new user message
            messages = _build_message_history(session, user_msg, system_prompt)
        else:
            # For tool continuation, build message history without adding new user message
            # The tool results are already in session.messages
            messages = [{"role": "system", "content": system_prompt}]
            
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
        
        # Validate message sequence (auto_fix removes orphan tool messages
        # that may result from context summarisation trimming)
        is_valid, error_msg = validate_message_sequence(messages, auto_fix=True)
        if not is_valid:
            logger.error(f"Invalid message sequence: {error_msg}")
            logger.error(f"Full message history: {json.dumps([{'role': m.get('role'), 'has_tool_calls': 'tool_calls' in m, 'tool_call_id': m.get('tool_call_id')} for m in messages], indent=2)}")
            raise ValueError(f"Invalid message sequence: {error_msg}")
        
        # Get tools in Qwen format — filtered to active skill group if provided
        tools = tools_registry.to_qwen_format(skill_names=active_skill_tools)
        logger.info(
            f"Tools for this turn: {len(tools)} "
            f"({'filtered: ' + repr(active_skill_tools) if active_skill_tools is not None else 'all'})"
        )
        
        # Call Qwen API
        logger.info(f"Calling Qwen API for turn {turn_counter}")
        _t_qwen_start = datetime.utcnow()
        response = call_qwen(messages=messages, tools=tools if tools else None)
        _t_qwen_end = datetime.utcnow()
        logger.info(f"[perf] call_qwen: {int((_t_qwen_end - _t_qwen_start).total_seconds() * 1000)}ms")
        
        # Capture LLM input/output for debugging
        llm_input_snapshot = [dict(m) for m in messages]  # Shallow copy of messages sent to LLM
        llm_output_snapshot = response  # Raw LLM response
        
        # Parse response
        assistant_message = response["choices"][0]["message"]
        response_text = assistant_message.get("content", "")
        tool_calls_data = assistant_message.get("tool_calls", [])

        confidence_percent = 100
        response_suppressed = False
        confidence_threshold_percent = int(settings.response_confidence_threshold * 100)

        # 仅在"本轮直接文本回复"时做置信度门控（有 tool_calls 的轮次跳过）
        if (settings.enable_confidence_guard 
            and response_text 
            and not tool_calls_data):
            latest_user_msg = user_message
            if is_tool_continue:
                for m in reversed(session.messages):
                    if m.role == MessageRole.USER:
                        latest_user_msg = m.content
                        break

            # 构建工具调用摘要：从 session.messages 中提取本次交互的工具调用和结果
            tool_calls_summary_lines = []
            for m in session.messages:
                if m.role == MessageRole.ASSISTANT and m.tool_calls:
                    for tc in m.tool_calls:
                        args_str = json.dumps(tc.args, ensure_ascii=False) if tc.args else "{}"
                        result_str = ""
                        if tc.result is not None:
                            result_str = json.dumps(tc.result, ensure_ascii=False, default=str)
                            if len(result_str) > 300:
                                result_str = result_str[:300] + "..."
                        tool_calls_summary_lines.append(
                            f"- 调用工具 {tc.name}({args_str}) → {result_str}"
                        )
            tool_calls_summary = "\n".join(tool_calls_summary_lines) if tool_calls_summary_lines else ""

            confidence_percent = _estimate_response_confidence_percent(
                latest_user_msg, response_text, tool_calls_summary
            )
            logger.info(
                f"Confidence guard: score={confidence_percent}%, "
                f"threshold={confidence_threshold_percent}%, "
                f"user_msg={latest_user_msg[:80]!r}, "
                f"response={response_text[:80]!r}"
            )
            if confidence_percent < confidence_threshold_percent:
                response_suppressed = True
                logger.warning(
                    f"【置信度抑制】Low-confidence response suppressed: confidence={confidence_percent}%, "
                    f"threshold={confidence_threshold_percent}%, "
                    f"original_response={response_text[:200]!r}"
                )
                # 不清空 response_text，保留原始回复用于日志和调试
                # 通过 metadata.response_suppressed 标记，由上层 executor 决定是否替换为兜底回复

        # Create assistant message
        assistant_msg = Message(
            role=MessageRole.ASSISTANT,
            content=response_text,
            timestamp=datetime.utcnow(),
            metadata={
                "confidence_percent": confidence_percent,
                "response_suppressed": response_suppressed,
                "confidence_threshold_percent": confidence_threshold_percent
            }
        )
        
        tool_call_objects = []
        
        # Execute tool calls if any
        if tool_calls_data:
            _t_tools_start = datetime.utcnow()
            for tc in tool_calls_data:
                tool_name = tc["function"]["name"]
                tool_call_id = tc["id"]
                tool_call = None  # Initialize to None
                
                try:
                    # Parse arguments
                    args = json.loads(tc["function"]["arguments"])
                    
                    # Log tool call
                    log_tool_call(session.session_id, tool_name, tool_call_id, args)
                    
                    # Create tool call object
                    tool_call = ToolCall(
                        id=tool_call_id,
                        name=tool_name,
                        args=args,
                        status=ToolCallStatus.EXECUTING,
                        started_at=datetime.utcnow()
                    )
                    
                    # Execute tool
                    tool_start = datetime.utcnow()
                    result = tools_registry.execute_tool(tool_name, args)
                    tool_end = datetime.utcnow()
                    
                    # Update tool call
                    tool_call.result = result
                    tool_call.status = ToolCallStatus.SUCCESS
                    tool_call.completed_at = tool_end
                    tool_call.duration_ms = int((tool_end - tool_start).total_seconds() * 1000)
                    
                    tool_call_objects.append(tool_call)
                    
                    # Log tool result
                    log_tool_result(
                        session.session_id,
                        tool_name,
                        tool_call_id,
                        success=True,
                        duration_ms=tool_call.duration_ms
                    )
                    
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
                    logger.error(f"Tool execution failed: {e}", exc_info=True)
                    
                    # Only update tool_call if it was created
                    if tool_call is not None:
                        tool_call.status = ToolCallStatus.ERROR
                        tool_call.error = str(e)
                        tool_call.completed_at = datetime.utcnow()
                        tool_call_objects.append(tool_call)
                    else:
                        # Create error tool call if tool_call wasn't created yet
                        tool_call = ToolCall(
                            id=tool_call_id,
                            name=tool_name,
                            args={},
                            status=ToolCallStatus.ERROR,
                            error=str(e),
                            started_at=datetime.utcnow(),
                            completed_at=datetime.utcnow()
                        )
                        tool_call_objects.append(tool_call)
                    
                    # IMPORTANT: Create tool response message even for errors
                    # This is required by Qwen API - every tool_call must have a response
                    error_result = {
                        "success": False,
                        "error": str(e)
                    }
                    tool_msg = Message(
                        role=MessageRole.TOOL,
                        content=json_serialize(error_result),
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        timestamp=datetime.utcnow()
                    )
                    new_messages.append(tool_msg)
                    
                    log_tool_result(
                        session.session_id,
                        tool_name,
                        tool_call_id,
                        success=False,
                        duration_ms=0
                    )
        
        # Add tool calls to assistant message
        if tool_call_objects:
            _t_tools_end = datetime.utcnow()
            logger.info(f"[perf] tool_execution_total ({len(tool_call_objects)} tools): {int((_t_tools_end - _t_tools_start).total_seconds() * 1000)}ms")
            assistant_msg.tool_calls = tool_call_objects
        
        # Insert assistant message at correct position
        if is_tool_continue:
            # For tool continuation: assistant should be first (no user message)
            new_messages.insert(0, assistant_msg)
        else:
            # For normal turn: assistant comes after user message
            new_messages.insert(1, assistant_msg)
        
        # Calculate duration
        end_time = datetime.utcnow()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        
        log_turn_end(session.session_id, turn_counter, duration_ms, success=True)
        
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
                "turn_counter": turn_counter,
                "confidence_percent": confidence_percent,
                "response_suppressed": response_suppressed,
            },
            llm_input=llm_input_snapshot,
            llm_output=llm_output_snapshot
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


def _build_message_history(
    session: Session,
    new_user_message: Message,
    system_prompt: str
) -> List[Dict[str, Any]]:
    """
    Build message history for Qwen API.
    
    Args:
        session: Current session
        new_user_message: New user message
        system_prompt: System prompt
        
    Returns:
        List of messages in Qwen format
    """
    messages = [
        {"role": "system", "content": system_prompt}
    ]
    
    logger.debug(f"Building message history from {len(session.messages)} session messages")
    
    # Add historical messages
    for idx, msg in enumerate(session.messages):
        logger.debug(f"Processing session message {idx}: role={msg.role}, has_tool_calls={hasattr(msg, 'tool_calls') and msg.tool_calls is not None}, tool_call_id={getattr(msg, 'tool_call_id', None)}")
        
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
    
    # Add new user message
    logger.debug(f"Adding new user message: {new_user_message.content[:50]}")
    messages.append({"role": "user", "content": new_user_message.content})
    
    return messages


# ============================================================
# System Prompt Loading (DB-first, fallback to code)
# With in-memory caching to avoid hitting MySQL on every turn.
# ============================================================

# Cached PromptStore instance (lazy init)
_prompt_store_instance: PromptStore = None

# System prompt cache: (rendered_prompt, cached_at_timestamp)
import time as _time
_system_prompt_cache: tuple = (None, 0.0)
_SYSTEM_PROMPT_CACHE_TTL = 300  # 5 minutes – prompt changes are rare


def _get_prompt_store() -> PromptStore:
    """Get or create PromptStore singleton."""
    global _prompt_store_instance
    if _prompt_store_instance is None:
        _prompt_store_instance = PromptStore(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_database
        )
    return _prompt_store_instance


def _load_system_prompt() -> str:
    """
    Load system prompt: try database first, fallback to code.
    Results are cached in-memory for up to _SYSTEM_PROMPT_CACHE_TTL seconds
    to avoid a MySQL round-trip on every turn.
    
    1. Check in-memory cache (TTL-based)
    2. Try loading active 'rental_system' prompt from DB
    3. If found, render template variables (dates)
    4. If not found or DB error, use code default
    
    Returns:
        Rendered system prompt string
    """
    global _system_prompt_cache
    
    cached_prompt, cached_at = _system_prompt_cache
    now = _time.monotonic()
    
    if cached_prompt is not None and (now - cached_at) < _SYSTEM_PROMPT_CACHE_TTL:
        logger.debug("Using cached system prompt (%.1fs old)", now - cached_at)
        return cached_prompt
    
    rendered = None
    try:
        store = _get_prompt_store()
        prompt = store.get_active("rental_system")
        if prompt and prompt.content:
            logger.info("Loaded system prompt from database (rental_system)")
            rendered = render_system_prompt(prompt.content)
    except Exception as e:
        logger.warning(f"Failed to load system prompt from DB, using code default: {e}")
    
    if rendered is None:
        # Fallback to code default
        logger.info("Using code-default system prompt")
        rendered = get_rental_system_prompt()
    
    _system_prompt_cache = (rendered, now)
    return rendered
