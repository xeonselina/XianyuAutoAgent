"""
Agent executor - Main orchestrator for Plan-Action-Check loop.
T043 - AgentExecutor with run() and stream() methods.
"""

import uuid
import threading
from datetime import datetime
from typing import Optional, AsyncGenerator
from ai_kefu.agent.types import AgentConfig
from ai_kefu.agent.turn import execute_turn
from ai_kefu.agent.context_summarizer import should_summarize, summarize_context, apply_summary_to_session
from ai_kefu.agent.skill_selector import detect_skills, get_active_tool_names
from ai_kefu.models.session import Session, AgentState
from ai_kefu.storage.session_store import SessionStore
from ai_kefu.tools.tool_registry import ToolRegistry
from ai_kefu.tools import knowledge_search, complete_task
from ai_kefu.services.loop_detection import check_tool_loop
from ai_kefu.config.constants import SessionStatus, TerminateReason, TOOL_COMPLETE_TASK, MessageRole
from ai_kefu.config.settings import settings
from ai_kefu.utils.logging import logger, log_agent_complete
from ai_kefu.utils.errors import (
    MaxTurnsExceededError,
    LoopDetectedError,
    SessionNotFoundError,
    TurnTimeoutError
)


class AgentExecutor:
    """
    Main agent executor implementing Plan-Action-Check loop.
    """
    
    def __init__(
        self,
        session_store: SessionStore,
        config: Optional[AgentConfig] = None,
        conversation_store=None
    ):
        """
        Initialize agent executor.
        
        Args:
            session_store: Session storage
            config: Agent configuration
            conversation_store: ConversationStore for persisting turn data (optional)
        """
        self.session_store = session_store
        self.conversation_store = conversation_store
        self.config = config or AgentConfig(
            max_turns=settings.max_turns,
            turn_timeout_seconds=settings.turn_timeout_seconds,
            loop_detection_threshold=settings.loop_detection_threshold
        )
        
        # Initialize tool registry
        self.tools_registry = ToolRegistry()
        self._register_tools()
    
    def _register_tools(self):
        """Register all available tools."""
        # Register knowledge_search
        self.tools_registry.register_tool(
            "knowledge_search",
            knowledge_search.knowledge_search,
            knowledge_search.get_tool_definition()
        )
        
        # Register complete_task
        self.tools_registry.register_tool(
            "complete_task",
            complete_task.complete_task,
            complete_task.get_tool_definition()
        )
        
        # Register ask_human_agent
        from ai_kefu.tools import ask_human_agent
        self.tools_registry.register_tool(
            "ask_human_agent",
            ask_human_agent.ask_human_agent,
            ask_human_agent.get_tool_definition()
        )
        
        # Register rental tools
        from ai_kefu.tools import (
            check_availability,
            calculate_logistics,
            calculate_price,
            collect_rental_info,
            parse_date,
            get_return_address,
            get_order_status
        )

        self.tools_registry.register_tool(
            "parse_date",
            parse_date.parse_date,
            parse_date.get_tool_definition()
        )

        self.tools_registry.register_tool(
            "check_availability",
            check_availability.check_availability,
            check_availability.get_tool_definition()
        )

        self.tools_registry.register_tool(
            "calculate_logistics",
            calculate_logistics.calculate_logistics,
            calculate_logistics.get_tool_definition()
        )

        self.tools_registry.register_tool(
            "calculate_price",
            calculate_price.calculate_price,
            calculate_price.get_tool_definition()
        )

        self.tools_registry.register_tool(
            "collect_rental_info",
            collect_rental_info.collect_rental_info,
            collect_rental_info.get_tool_definition()
        )

        self.tools_registry.register_tool(
            "get_return_address",
            get_return_address.get_return_address,
            get_return_address.get_tool_definition()
        )

        self.tools_registry.register_tool(
            "get_order_status",
            get_order_status.get_order_status,
            get_order_status.get_tool_definition()
        )

        # Register Xianyu tools
        from ai_kefu.tools.xianyu import (
            get_item_info,
            get_item_info_definition,
            get_order_detail,
            get_order_detail_definition,
            get_buyer_info,
            get_buyer_info_definition,
            send_xianyu_message,
            send_message_definition,
            upload_media,
            upload_media_definition,
            list_conversations,
            list_conversations_definition,
        )

        self.tools_registry.register_tool(
            "get_item_info",
            get_item_info,
            get_item_info_definition()
        )

        self.tools_registry.register_tool(
            "get_order_detail",
            get_order_detail,
            get_order_detail_definition()
        )

        self.tools_registry.register_tool(
            "get_buyer_info",
            get_buyer_info,
            get_buyer_info_definition()
        )

        self.tools_registry.register_tool(
            "send_xianyu_message",
            send_xianyu_message,
            send_message_definition()
        )

        self.tools_registry.register_tool(
            "upload_media",
            upload_media,
            upload_media_definition()
        )

        self.tools_registry.register_tool(
            "list_conversations",
            list_conversations,
            list_conversations_definition()
        )

        logger.info(f"Registered {len(self.tools_registry.get_all_tools())} tools")
    
    def run(
        self,
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        context: Optional[dict] = None
    ) -> dict:
        """
        Run agent synchronously (complete conversation).
        
        Args:
            query: User query
            session_id: Existing session ID (optional)
            user_id: User ID (optional)
            context: Additional context (may contain conversation_id/chat_id for history loading)
            
        Returns:
            Dict with response
        """
        start_time = datetime.utcnow()
        
        # Load or create session
        chat_id = (context or {}).get("conversation_id")
        user_nickname = (context or {}).get("user_nickname")
        item_id = (context or {}).get("item_id")
        item_title = (context or {}).get("item_title")
        item_price = (context or {}).get("item_price")
        session = self._get_or_create_session(
            session_id, user_id, chat_id=chat_id, item_id=item_id,
            item_title=item_title, item_price=item_price,
        )
        
        # Check if context summarization is needed before processing
        if self.config.enable_context_summary and should_summarize(
            session, 
            max_message_tokens=self.config.context_summary_token_threshold
        ):
            logger.info(
                f"Session {session.session_id}: triggering context summarization "
                f"({len(session.messages)} messages)"
            )
            summary = summarize_context(
                session, 
                keep_recent_count=self.config.context_summary_keep_recent
            )
            if summary:
                apply_summary_to_session(
                    session, 
                    summary, 
                    keep_recent_count=self.config.context_summary_keep_recent
                )
                # Save session immediately after summarization
                self.session_store.set(session)
                logger.info(
                    f"Session {session.session_id}: context summarized, "
                    f"now {len(session.messages)} messages with summary"
                )
        
        # Create agent state for loop detection
        agent_state = AgentState(session_id=session.session_id)
        
        # ============================================================
        # 动态注入上下文信息到 ask_human_agent 工具
        # LLM function calling 不会传 chat_id/user_nickname/context_summary，
        # 所以通过 functools.partial 预绑定这些参数。
        # ============================================================
        from functools import partial
        from ai_kefu.tools import ask_human_agent as _ask_human_mod
        _original_ask_human = _ask_human_mod.ask_human_agent
        _bound_ask_human = partial(
            _original_ask_human,
            chat_id=chat_id,
            user_nickname=user_nickname,
            context_summary=session.context.get("context_summary"),
        )
        self.tools_registry._tools["ask_human_agent"] = _bound_ask_human

        # ============================================================
        # 动态注入 chat_id / buyer_id 到 send_xianyu_message 工具
        # LLM function calling 只传 text，chat_id 和 buyer_id 由运行时上下文提供。
        # buyer_id 对应闲鱼的买家用户 ID，通过 context.user_id 传入。
        # ============================================================
        _buyer_id = (context or {}).get("user_id", "")
        from ai_kefu.tools.xianyu import send_xianyu_message as _send_xianyu_msg_fn
        _original_send_xianyu = _send_xianyu_msg_fn
        if chat_id and _buyer_id:
            _bound_send_xianyu = partial(
                _original_send_xianyu,
                chat_id=chat_id,
                buyer_id=_buyer_id,
            )
            self.tools_registry._tools["send_xianyu_message"] = _bound_send_xianyu

        # Execute turns until completion
        response_text = ""
        is_first_turn = True
        last_turn_metadata = {}

        # Generate a unique interaction_id for this user-message processing
        # All turns within this run() belong to the same interaction
        interaction_id = str(uuid.uuid4())
        local_turn_counter = 0

        # ============================================================
        # 动态技能选择：根据用户消息检测本次 run() 需要的工具子集
        # 以减少每次传给 LLM 的 tool definitions 数量（节省 token）。
        # active_skills 在整个 run() 中保持不变（包括 tool-continuation 轮次）。
        # ============================================================
        active_skills = detect_skills(query, session_context=session.context)
        active_skill_tools = get_active_tool_names(active_skills)
        logger.info(
            f"[skill_selector] active_skills={active_skills}, "
            f"active_tool_count={len(active_skill_tools)}"
        )
        
        # 超时保护: 确保整个 agent 执行不超过 turn_timeout_seconds
        # 这是最后一道防线，防止 Qwen API 慢响应 + 重试导致无限等待
        timeout_seconds = self.config.turn_timeout_seconds
        _timed_out = threading.Event()
        
        def _timeout_handler():
            _timed_out.set()
            logger.warning(
                f"Session {session.session_id}: agent execution timeout "
                f"({timeout_seconds}s), will terminate on next check"
            )
        
        timeout_timer = threading.Timer(timeout_seconds, _timeout_handler)
        timeout_timer.daemon = True
        timeout_timer.start()
        
        try:
            while True:
                # 检查超时标志
                if _timed_out.is_set():
                    raise TurnTimeoutError(session.session_id, timeout_seconds)
                
                # Check max turns
                if session.turn_counter >= self.config.max_turns:
                    raise MaxTurnsExceededError(session.session_id, self.config.max_turns)
                
                # Execute turn
                # First turn: add user message
                # Subsequent turns: continue with tool results
                turn_result = execute_turn(
                    session=session,
                    user_message=query,
                    tools_registry=self.tools_registry,
                    is_tool_continue=not is_first_turn,
                    active_skill_tools=active_skill_tools,
                )
                
                is_first_turn = False
                
                if not turn_result.success:
                    session.status = SessionStatus.ERROR
                    session.terminate_reason = TerminateReason.ERROR
                    self.session_store.set(session)
                    return {
                        "session_id": session.session_id,
                        "status": session.status,
                        "error": turn_result.error_message
                    }
                
                # Update session with new messages
                session.messages.extend(turn_result.new_messages)
                session.turn_counter += 1
                local_turn_counter += 1
                session.updated_at = datetime.utcnow()
                
                # Persist turn data for debugging
                if self.conversation_store:
                    try:
                        tool_results = None
                        if turn_result.tool_calls:
                            tool_results = [
                                {
                                    "id": tc.get("id"),
                                    "name": tc.get("name"),
                                    "result": tc.get("result")
                                }
                                for tc in turn_result.tool_calls
                            ]
                        self.conversation_store.save_turn(
                            session_id=session.session_id,
                            turn_number=session.turn_counter,
                            user_query=query,
                            llm_input=turn_result.llm_input,
                            llm_output=turn_result.llm_output,
                            response_text=turn_result.response_text,
                            tool_calls=turn_result.tool_calls if turn_result.tool_calls else None,
                            tool_results=tool_results,
                            duration_ms=turn_result.metadata.get("duration_ms"),
                            success=turn_result.success,
                            error_message=turn_result.error_message,
                            interaction_id=interaction_id,
                            local_turn_number=local_turn_counter,
                            confidence_percent=turn_result.metadata.get("confidence_percent"),
                            response_suppressed=turn_result.metadata.get("response_suppressed", False)
                        )
                    except Exception as e:
                        logger.warning(f"Failed to persist turn data (non-fatal): {e}")
                
                # Extract rental info from tool results and persist into session.context
                # so it gets saved to DB context column on the next AI reply.
                if turn_result.tool_calls:
                    for tc_dict in turn_result.tool_calls:
                        tool_name = tc_dict.get("name", "")
                        result = tc_dict.get("result") or {}
                        if isinstance(result, str):
                            try:
                                import json as _json
                                result = _json.loads(result)
                            except Exception:
                                result = {}
                        if tool_name == "collect_rental_info" and result.get("success"):
                            collected = result.get("collected_info", {})
                            if collected.get("receive_date"):
                                session.context["receive_date"] = collected["receive_date"]
                            if collected.get("return_date"):
                                session.context["return_date"] = collected["return_date"]
                            if collected.get("destination"):
                                session.context["destination"] = collected["destination"]
                        elif tool_name == "calculate_logistics" and result.get("success"):
                            if result.get("destination"):
                                session.context["destination"] = result["destination"]

                # Check for loop in tool calls
                if self.config.enable_loop_detection and turn_result.tool_calls:
                    for tc_dict in turn_result.tool_calls:
                        # Create ToolCall object for loop detection
                        from ai_kefu.models.session import ToolCall
                        tc = ToolCall(
                            id=tc_dict["id"],
                            name=tc_dict["name"],
                            args=tc_dict["args"]
                        )
                        if check_tool_loop(agent_state, tc):
                            raise LoopDetectedError(session.session_id, tc.name)
                
                # Check if task completed
                task_completed = any(
                    tc_dict["name"] == TOOL_COMPLETE_TASK
                    for tc_dict in turn_result.tool_calls
                )
                
                if task_completed:
                    session.status = SessionStatus.COMPLETED
                    session.terminate_reason = TerminateReason.GOAL
                    response_text = turn_result.response_text
                    break
                
                # Update response text
                response_text = turn_result.response_text
                
                # If there were tool calls, continue to next turn to get LLM's response to tool results
                if turn_result.tool_calls:
                    logger.info(f"Turn {session.turn_counter} had {len(turn_result.tool_calls)} tool calls, continuing to next turn")
                    continue
                
                # If no tool calls and we have response text, we're done
                if response_text:
                    last_turn_metadata = turn_result.metadata
                    # 检查是否被置信度门控抑制
                    if turn_result.metadata.get("response_suppressed"):
                        confidence = turn_result.metadata.get("confidence_percent", "?")
                        threshold = turn_result.metadata.get("confidence_threshold_percent", "?")
                        logger.warning(
                            f"Turn {session.turn_counter}: 【置信度抑制】confidence={confidence}%, "
                            f"original_response={response_text[:200]!r}, using fallback response"
                        )
                        # 保留原始回复到 metadata，供下游（如数据库记录）使用
                        last_turn_metadata["original_response"] = response_text
                        # 置信度抑制时不给用户发送任何消息（静默处理），
                        # 通过 metadata.response_suppressed=True 标记，
                        # 让下游（message_handler）只做数据库记录、不发送到闲鱼。
                        # response_text 保持原始内容不动，用于数据库记录。

                        # 发送钉钉通知
                        try:
                            from ai_kefu.services.dingtalk_notify import notify_confidence_suppression

                            # 获取上下文总结：优先使用已有摘要，否则从最近消息中构建
                            _ctx_summary = session.context.get("context_summary")
                            if not _ctx_summary and session.messages:
                                # 没有正式摘要时，从最近消息构建简要上下文
                                _recent_lines = []
                                for _m in session.messages[-8:]:  # 最多取最近 8 条
                                    if _m.role == MessageRole.USER:
                                        _recent_lines.append(f"用户: {_m.content[:100]}")
                                    elif _m.role == MessageRole.ASSISTANT and _m.content:
                                        _recent_lines.append(f"客服: {_m.content[:100]}")
                                if _recent_lines:
                                    _ctx_summary = "\n".join(_recent_lines)

                            notify_confidence_suppression(
                                chat_id=chat_id or session.session_id,
                                user_message=query,
                                original_response=last_turn_metadata["original_response"],
                                confidence_percent=confidence if isinstance(confidence, int) else 0,
                                threshold_percent=threshold if isinstance(threshold, int) else 80,
                                fallback_response="",
                                user_nickname=user_nickname,
                                context_summary=_ctx_summary,
                            )
                        except Exception as notify_err:
                            logger.warning(f"置信度抑制钉钉通知失败（不影响主流程）: {notify_err}")
                    else:
                        logger.info(f"Turn {session.turn_counter} completed with response, ending agent execution")
                    break
                
                # If no tool calls and no response text, something is wrong
                last_turn_metadata = turn_result.metadata
                logger.warning(f"Turn {session.turn_counter} had no tool calls and no response text")
                break
            
            # Save session
            self.session_store.set(session)
            
            # Log completion
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            log_agent_complete(
                session.session_id,
                session.status,
                session.turn_counter,
                duration_ms
            )
            
            return {
                "session_id": session.session_id,
                "response": response_text,
                "status": session.status,
                "turn_counter": session.turn_counter,
                "metadata": {
                    "duration_ms": duration_ms,
                    "confidence_percent": last_turn_metadata.get("confidence_percent"),
                    "response_suppressed": last_turn_metadata.get("response_suppressed", False),
                    "original_response": last_turn_metadata.get("original_response"),
                    "context_summary": session.context.get("context_summary"),
                    "is_returning_customer": session.context.get("is_returning_customer"),
                    "receive_date": session.context.get("receive_date"),
                    "return_date": session.context.get("return_date"),
                    "destination": session.context.get("destination"),
                }
            }
            
        except TurnTimeoutError as e:
            logger.error(f"Agent execution timed out: {e}")
            session.status = SessionStatus.ERROR
            session.terminate_reason = TerminateReason.TIMEOUT
            self.session_store.set(session)
            
            return {
                "session_id": session.session_id,
                "response": "抱歉，系统响应超时，请稍后再试~",
                "status": session.status,
                "error": str(e)
            }
            
        except Exception as e:
            logger.error(f"Agent execution failed: {e}", exc_info=True)
            session.status = SessionStatus.ERROR
            session.terminate_reason = TerminateReason.ERROR
            self.session_store.set(session)
            
            # Provide a user-friendly fallback response for transient errors
            # so the caller can still show something to the end user
            error_str = str(e)
            fallback_response = ""
            
            # Common transient errors from Qwen/DashScope API
            transient_keywords = [
                "RequestFailure", "ServiceUnavailable", "Throttling",
                "rate limit", "timeout", "timed out", "Connection",
                "InternalError", "ServerError"
            ]
            is_transient = any(kw.lower() in error_str.lower() for kw in transient_keywords)
            
            if is_transient:
                fallback_response = "抱歉，系统暂时繁忙，请稍后再试~"
                logger.warning(f"Transient error detected, returning fallback response: {error_str}")
            
            return {
                "session_id": session.session_id,
                "response": fallback_response,
                "status": session.status,
                "error": error_str
            }
        
        finally:
            # 确保超时定时器被取消（无论成功还是异常）
            timeout_timer.cancel()
            # 恢复 ask_human_agent 原始函数（避免 partial 闭包泄漏到其他 session）
            self.tools_registry._tools["ask_human_agent"] = _original_ask_human
            # 恢复 send_xianyu_message 原始函数
            self.tools_registry._tools["send_xianyu_message"] = _original_send_xianyu
    
    async def stream(
        self,
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        context: Optional[dict] = None
    ) -> AsyncGenerator[str, None]:
        """
        Run agent with streaming (for real-time responses).
        
        Args:
            query: User query
            session_id: Existing session ID (optional)
            user_id: User ID (optional)
            context: Additional context (optional)
            
        Yields:
            Response chunks
        """
        # For now, just yield the sync result
        # Full streaming would require streaming from Qwen API
        result = self.run(query, session_id, user_id, context=context)
        
        if "response" in result:
            # Simulate streaming by yielding words
            words = result["response"].split()
            for word in words:
                yield word + " "
        elif "error" in result:
            yield f"Error: {result['error']}"
    
    def _get_or_create_session(
        self,
        session_id: Optional[str],
        user_id: Optional[str],
        chat_id: Optional[str] = None,
        item_id: Optional[str] = None,
        item_title: Optional[str] = None,
        item_price: Optional[str] = None,
    ) -> Session:
        """
        Get existing session or create new one.
        When creating a new session, load conversation history from MySQL
        and generate a context summary so the LLM knows the conversation background.
        Also prefetch item info (title, price, model) and store as a fixed context slot.

        Args:
            session_id: Existing session ID (optional)
            user_id: User ID (optional)
            chat_id: Xianyu chat ID (for loading history from MySQL on new sessions)
            item_id: Xianyu item/listing ID (for prefetching item info on new sessions)
            
        Returns:
            Session object
        """
        if session_id:
            # Try to load existing session
            session = self.session_store.get(session_id)
            if session:
                logger.info(f"Loaded existing session: {session_id}")
                # If existing session has few messages and no context_summary,
                # load history from MySQL to provide conversation background.
                # This covers: Redis session data was preserved but context was lost,
                # or session was recently recreated with minimal history.
                if len(session.messages) <= 2 and not session.context.get("context_summary") and chat_id:
                    logger.info(
                        f"Existing session {session_id} has {len(session.messages)} messages "
                        f"and no context_summary, loading from MySQL"
                    )
                    self._load_history_as_context(session, chat_id)
                    # Also load cross-conversation user history
                    self._load_user_history_as_context(session, user_id)
                    if session.context.get("context_summary"):
                        self.session_store.set(session)  # Persist the updated context
                # Prefetch item info if not already cached in session
                if item_id and not session.context.get("item_info"):
                    self._load_item_info_context(session, item_id, item_title=item_title, item_price=item_price)
                    self.session_store.set(session)
                return session
            else:
                # Create new session with the provided session_id
                logger.info(f"Session not found in store, creating new session with provided ID: {session_id}")
                new_session = Session(
                    session_id=session_id,  # Use the provided session_id
                    user_id=user_id,
                    status=SessionStatus.ACTIVE
                )
                # Load conversation history from MySQL for context
                self._load_history_as_context(new_session, chat_id)
                # Load cross-conversation user history (all chats for this buyer)
                self._load_user_history_as_context(new_session, user_id)
                # Prefetch item info for the fixed context slot
                self._load_item_info_context(new_session, item_id, item_title=item_title, item_price=item_price)
                return new_session

        # Create new session with generated ID
        new_session = Session(
            session_id=str(uuid.uuid4()),
            user_id=user_id,
            status=SessionStatus.ACTIVE
        )
        # Load conversation history from MySQL for context
        self._load_history_as_context(new_session, chat_id)
        # Load cross-conversation user history (all chats for this buyer)
        self._load_user_history_as_context(new_session, user_id)
        # Prefetch item info for the fixed context slot
        self._load_item_info_context(new_session, item_id, item_title=item_title, item_price=item_price)

        logger.info(f"Created new session: {new_session.session_id}")
        return new_session

    def _load_item_info_context(
        self,
        session: Session,
        item_id: Optional[str],
        item_title: Optional[str] = None,
        item_price: Optional[str] = None,
    ):
        """
        Fetch Xianyu item/listing info once at session start and store it as a
        fixed context slot (session.context["item_info"]).

        This lets the LLM know the exact product title, price, and description
        for the listing the buyer is enquiring about — without having to ask
        the buyer which variant they want.

        If the Xianyu API call fails (e.g. XIANYU_COOKIE not configured), falls
        back to the title/price forwarded by the interceptor in the request context.

        Args:
            session:    The session to populate
            item_id:    Xianyu item ID (from context["item_id"])
            item_title: Item title forwarded by interceptor (fallback when API unavailable)
            item_price: Item price forwarded by interceptor (fallback when API unavailable)
        """
        if not item_id:
            return

        import re as _re
        # Each tuple: (regex_pattern, canonical_name)
        # 3 canonical models: X300U, X200U, X300P
        # Ultra/Pro variants and space-separated writes all normalize to the canonical name.
        _model_patterns = [
            (r"X300\s*Ultra",          "X300U"),
            (r"X300\s*U(?![a-zA-Z])",  "X300U"),
            (r"X200\s*Ultra",          "X200U"),
            (r"X200\s*U(?![a-zA-Z])",  "X200U"),
            (r"X300\s*Pro",            "X300P"),
            (r"X300\s*P(?![a-zA-Z])",  "X300P"),
        ]

        def _extract_and_store(title: str, price: str, source: str):
            """Helper: store item_info slot and detect model from title."""
            session.context["item_info"] = {
                "success": True,
                "item_id": item_id,
                "title": title,
                "price": price,
                "desc": "",
                "item_status": 0,
                "seller_id": "",
                "location": "",
            }
            for _pat, _canonical in _model_patterns:
                if _re.search(_pat, title, _re.IGNORECASE):
                    session.context["item_model"] = _canonical
                    logger.info(
                        f"[item_info] Detected item_model={_canonical!r} from title={title!r} (source={source})"
                    )
                    break
            else:
                logger.debug(
                    f"[item_info] No known model pattern found in title={title!r} (source={source})"
                )
            logger.info(
                f"[item_info] item_info context set for item_id={item_id}: "
                f"title={title!r}, price={price!r}, source={source}"
            )

        try:
            from ai_kefu.tools.xianyu import get_item_info
            result = get_item_info(item_id)
            if result.get("success"):
                session.context["item_info"] = result
                _title = result.get("title", "")
                for _pat, _canonical in _model_patterns:
                    if _re.search(_pat, _title, _re.IGNORECASE):
                        session.context["item_model"] = _canonical
                        logger.info(
                            f"[item_info] Detected item_model={_canonical!r} from title={_title!r} (source=api)"
                        )
                        break
                else:
                    logger.debug(
                        f"[item_info] No known model pattern found in title={_title!r} (source=api)"
                    )
                logger.info(
                    f"[item_info] Prefetched item info for item_id={item_id}: "
                    f"title={_title!r}, price={result.get('price', '')!r}"
                )
            else:
                logger.warning(
                    f"[item_info] API call failed for item_id={item_id}: "
                    f"{result.get('error')} — trying interceptor-forwarded title fallback"
                )
                if item_title:
                    _extract_and_store(item_title, item_price or "", "interceptor")
                else:
                    logger.warning(
                        f"[item_info] No fallback title available for item_id={item_id}, "
                        "item_info context slot will be empty"
                    )
        except Exception as e:
            logger.warning(
                f"[item_info] Exception while fetching item info for item_id={item_id}: {e} "
                "— trying interceptor-forwarded title fallback",
                exc_inc=True,
            )
            if item_title:
                _extract_and_store(item_title, item_price or "", "interceptor")

    def _get_summary_cache_key(self, chat_id: str) -> str:
        """Generate Redis key for cached history summary."""
        return f"history_summary:{chat_id}"

    def _get_cached_summary(self, chat_id: str) -> Optional[dict]:
        """
        Try to load cached history summary from Redis.
        
        Returns:
            Dict with 'summary', 'is_returning_customer', 'fingerprint' if cache hit,
            None if cache miss.
        """
        try:
            import json
            cache_key = self._get_summary_cache_key(chat_id)
            data = self.session_store.client.get(cache_key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.debug(f"Failed to read summary cache for chat_id={chat_id}: {e}")
        return None

    def _set_cached_summary(
        self,
        chat_id: str,
        summary: str,
        is_returning_customer: bool,
        fingerprint: dict,
        ttl: int = 3600,
    ):
        """
        Cache history summary in Redis.

        Args:
            chat_id: Xianyu chat ID
            summary: Generated summary text
            is_returning_customer: Whether user is a returning customer
            fingerprint: Dict identifying the data version (varies by source)
            ttl: Redis key TTL in seconds (default 3600 / 1 hour).
                 Use a shorter value (e.g. 1800) for API-sourced summaries
                 whose message count can change more frequently.
        """
        try:
            import json
            cache_key = self._get_summary_cache_key(chat_id)
            cache_data = json.dumps({
                "summary": summary,
                "is_returning_customer": is_returning_customer,
                "fingerprint": fingerprint
            }, ensure_ascii=False)
            self.session_store.client.setex(cache_key, ttl, cache_data)
            logger.debug(f"Cached history summary for chat_id={chat_id} (ttl={ttl}s)")
        except Exception as e:
            logger.debug(f"Failed to cache summary for chat_id={chat_id}: {e}")

    # ------------------------------------------------------------------
    # User-level (cross-conversation) summary cache helpers
    # ------------------------------------------------------------------

    def _get_user_summary_cache_key(self, user_id: str) -> str:
        """Generate Redis key for cached cross-conversation user summary."""
        return f"user_history_summary:{user_id}"

    def _get_cached_user_summary(self, user_id: str) -> Optional[dict]:
        """
        Try to load a cached cross-conversation summary from Redis.

        Returns:
            Dict with 'summary', 'is_returning_customer', 'fingerprint' if cache hit,
            None on cache miss.
        """
        try:
            import json
            cache_key = self._get_user_summary_cache_key(user_id)
            data = self.session_store.client.get(cache_key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.debug(f"Failed to read user summary cache for user_id={user_id}: {e}")
        return None

    def _set_cached_user_summary(
        self,
        user_id: str,
        summary: str,
        is_returning_customer: bool,
        fingerprint: dict,
        ttl: int = 3600,
    ):
        """
        Cache a cross-conversation history summary in Redis.

        Args:
            user_id: Buyer's Xianyu user ID
            summary: Generated summary text
            is_returning_customer: Whether user is a returning customer
            fingerprint: Dict identifying the data version
            ttl: Redis key TTL in seconds (default 3600 / 1 hour)
        """
        try:
            import json
            cache_key = self._get_user_summary_cache_key(user_id)
            cache_data = json.dumps({
                "summary": summary,
                "is_returning_customer": is_returning_customer,
                "fingerprint": fingerprint,
            }, ensure_ascii=False)
            self.session_store.client.setex(cache_key, ttl, cache_data)
            logger.debug(f"Cached user history summary for user_id={user_id} (ttl={ttl}s)")
        except Exception as e:
            logger.debug(f"Failed to cache user summary for user_id={user_id}: {e}")

    def _load_history_as_context(self, session: Session, chat_id: Optional[str]):
        """
        Load conversation history and inject as context summary into the session.

        Strategy (in priority order):
        1. Try Xianyu WebSocket API — covers *all* messages including pre-AI ones.
           Applies time-proximity compression (verbatim recent, LLM-summarized older).
        2. Fall back to MySQL-based loader if the API returns nothing or fails.

        Args:
            session: The newly created session
            chat_id: Xianyu chat ID to query history for
        """
        if not chat_id:
            return

        try:
            api_messages = self._fetch_xianyu_api_history(chat_id)
        except Exception as e:
            logger.warning(f"[api_history] Unexpected error, falling back to MySQL: {e}", exc_info=True)
            api_messages = []

        if api_messages:
            try:
                api_fingerprint = {"source": "xianyu_api", "message_count": len(api_messages)}

                # Check Redis cache — avoid re-summarizing if message count unchanged
                cached = self._get_cached_summary(chat_id)
                if cached and cached.get("fingerprint") == api_fingerprint:
                    session.context["context_summary"] = cached["summary"]
                    session.context["is_returning_customer"] = cached.get("is_returning_customer", False)
                    logger.info(
                        f"[cache_hit] API history summary for chat_id={chat_id}: "
                        f"{len(cached['summary'])} chars"
                    )
                    return

                # Detect returning customer from API messages
                is_returning_customer = any(
                    "我已付款" in (m.get("message", {}).get("reminderContent") or "")
                    for m in api_messages
                )

                # Apply time-proximity compression
                summary_body = self._compress_by_time_proximity(api_messages)
                if not summary_body:
                    logger.debug(
                        f"[api_history] No extractable text from {len(api_messages)} messages "
                        f"for chat_id={chat_id}, falling back to MySQL"
                    )
                else:
                    tag = (
                        "【老客户】该用户之前有过付款记录。"
                        if is_returning_customer
                        else "【新客户】该用户暂无历史付款记录。"
                    )
                    summary = f"{tag}\n\n{summary_body}"

                    session.context["context_summary"] = summary
                    session.context["is_returning_customer"] = is_returning_customer
                    # Use shorter TTL for API summaries — message count changes more often
                    self._set_cached_summary(
                        chat_id, summary, is_returning_customer, api_fingerprint, ttl=1800
                    )
                    logger.info(
                        f"[api_history] Loaded {len(api_messages)} msgs for chat_id={chat_id}, "
                        f"summary={len(summary)} chars, returning_customer={is_returning_customer}"
                    )
                    return
            except Exception as e:
                logger.warning(
                    f"[api_history] Error processing API history for chat_id={chat_id}: {e}, "
                    "falling back to MySQL",
                    exc_info=True,
                )

        # Fall back to MySQL-based history (original behaviour, unchanged)
        self._load_history_as_context_from_mysql(session, chat_id)

    def _compress_mysql_messages_by_time_proximity(self, messages: list) -> str:
        """
        Apply tiered time-proximity compression to a list of ConversationMessage objects
        (as returned by ConversationStore.get_conversation_history_by_user_id).

        Tiers (same thresholds as the Xianyu API variant):
        - Last 20 messages  → verbatim   (highest signal)
        - Messages 20–60    → LLM-summarized as 【近期对话摘要】
        - Messages 60+      → LLM-summarized as 【早期对话摘要】

        Returns:
            Formatted multi-section string, or "" if no usable text.
        """
        RECENT_WINDOW = 20
        MIDTERM_WINDOW = 40

        def _extract_line(msg) -> Optional[str]:
            content = (msg.message_content or "").strip()
            if not content:
                return None
            # Strip debug prefix for readability
            if content.startswith("【调试】"):
                content = content[4:]
            msg_type = msg.message_type
            type_str = msg_type.value if hasattr(msg_type, 'value') else str(msg_type)
            if type_str == "user":
                return f"用户: {content}"
            elif type_str == "seller":
                return f"客服: {content}"
            return None

        lines = [t for m in messages if (t := _extract_line(m))]

        if not lines:
            return ""

        recent = lines[-RECENT_WINDOW:]
        midterm = lines[-(RECENT_WINDOW + MIDTERM_WINDOW):-RECENT_WINDOW]
        early = lines[:-(RECENT_WINDOW + MIDTERM_WINDOW)]

        parts = []

        if early:
            early_text = "\n".join(early)
            early_summary = (
                self._summarize_history(early_text)
                or f"（早期对话 {len(early)} 条，已省略）"
            )
            parts.append(f"【早期对话摘要】\n{early_summary}")

        if midterm:
            mid_text = "\n".join(midterm)
            mid_summary = (
                self._summarize_history(mid_text)
                or f"（中期对话 {len(midterm)} 条，已省略）"
            )
            parts.append(f"【近期对话摘要】\n{mid_summary}")

        parts.append(f"【最新对话记录（{len(recent)} 条）】\n" + "\n".join(recent))

        return "\n\n".join(parts)

    def _load_user_history_as_context(self, session: Session, user_id: Optional[str]):
        """
        Load ALL conversation history for a buyer (across every chat_id) and inject
        a time-proximity-compressed summary into the session context.

        This supplements the per-chat context already loaded by
        _load_history_as_context, giving the LLM visibility into the buyer's full
        interaction history — not just the current conversation thread.

        Strategy:
        1. Lightweight fingerprint check → Redis cache lookup
        2. On cache miss: fetch up to 100 messages by user_id from MySQL,
           apply tiered compression, cache result
        3. Merge with any existing context_summary already in the session

        Args:
            session:  The newly created (or reloaded) session
            user_id:  Buyer's Xianyu user ID
        """
        if not user_id or not self.conversation_store:
            return

        try:
            # Step 1: lightweight fingerprint
            fingerprint = self.conversation_store.get_user_fingerprint(user_id)
            if not fingerprint:
                logger.debug(f"No cross-conversation history found for user_id={user_id}")
                return

            # Step 2: Redis cache check
            cached = self._get_cached_user_summary(user_id)
            if cached and cached.get("fingerprint") == fingerprint:
                user_summary = cached["summary"]
                is_returning_customer = cached.get("is_returning_customer", False)
                logger.info(
                    f"[user_cache_hit] Cross-conversation summary for user_id={user_id}: "
                    f"{len(user_summary)} chars, returning_customer={is_returning_customer}"
                )
            else:
                # Step 3: Cache miss — load & compress
                logger.info(
                    f"[user_cache_miss] Generating cross-conversation summary for user_id={user_id} "
                    f"(count={fingerprint['message_count']}, last={fingerprint['last_message_at']})"
                )
                history = self.conversation_store.get_conversation_history_by_user_id(
                    user_id=user_id,
                    limit=100,
                )
                if not history:
                    return

                # Detect returning customer
                is_returning_customer = any(
                    "我已付款，等待你发货" in (msg.message_content or "")
                    for msg in history
                )

                summary_body = self._compress_mysql_messages_by_time_proximity(history)
                if not summary_body:
                    logger.debug(
                        f"[user_history] No extractable text from {len(history)} messages "
                        f"for user_id={user_id}"
                    )
                    return

                returning_tag = (
                    "【老客户】该用户之前有过付款记录。"
                    if is_returning_customer
                    else "【新客户】该用户暂无历史付款记录。"
                )
                user_summary = f"{returning_tag}\n\n{summary_body}"

                # Cache for subsequent sessions
                self._set_cached_user_summary(
                    user_id, user_summary, is_returning_customer, fingerprint
                )
                logger.info(
                    f"[user_history] Loaded {len(history)} msgs for user_id={user_id}, "
                    f"summary={len(user_summary)} chars, returning_customer={is_returning_customer}"
                )

            # Step 4: Merge into session context
            # If a per-chat summary already exists (from _load_history_as_context),
            # prepend the cross-conversation view as a separate section so the LLM
            # gets the broadest picture first.
            existing = session.context.get("context_summary", "")
            if existing:
                session.context["context_summary"] = (
                    f"## 用户历史对话摘要（跨会话）\n{user_summary}"
                    f"\n\n## 当前会话上下文\n{existing}"
                )
            else:
                session.context["context_summary"] = user_summary

            # Returning-customer flag: a returning customer in ANY chat counts
            if is_returning_customer:
                session.context["is_returning_customer"] = True

        except Exception as e:
            logger.warning(
                f"Failed to load cross-conversation history for user_id={user_id}: {e}",
                exc_info=True,
            )

    def _load_history_as_context_from_mysql(self, session: Session, chat_id: Optional[str]):
        """
        Load conversation history from MySQL and inject as context summary.

        Uses Redis cache to avoid repeated LLM summarization calls.
        Cache is invalidated when message count or last message timestamp changes.

        This ensures that when a Redis session expires and a new one is created,
        the LLM still has context about previous conversations with this user.

        Args:
            session: The newly created session
            chat_id: Xianyu chat ID to query history for
        """
        if not chat_id or not self.conversation_store:
            return
        
        try:
            # Step 1: Get lightweight fingerprint (COUNT + MAX timestamp)
            fingerprint = self.conversation_store.get_conversation_fingerprint(chat_id)
            if not fingerprint:
                logger.debug(f"No conversation history found for chat_id={chat_id}")
                return
            
            # Step 2: Check Redis cache
            cached = self._get_cached_summary(chat_id)
            if cached and cached.get("fingerprint") == fingerprint:
                # Cache hit! Reuse cached summary
                summary = cached["summary"]
                is_returning_customer = cached["is_returning_customer"]
                session.context["context_summary"] = summary
                session.context["is_returning_customer"] = is_returning_customer
                logger.info(
                    f"[cache_hit] Loaded cached history summary for chat_id={chat_id}: "
                    f"{len(summary)} chars, returning_customer={is_returning_customer}"
                )
                return
            
            # Step 3: Cache miss - load full history and generate summary
            logger.info(f"[cache_miss] Generating history summary for chat_id={chat_id} "
                        f"(fingerprint: count={fingerprint['message_count']}, last={fingerprint['last_message_at']})")
            
            # Load recent conversation history from MySQL
            history = self.conversation_store.get_conversation_history(
                chat_id=chat_id,
                limit=50  # Get last 50 messages for summarization
            )
            
            if not history:
                logger.debug(f"No conversation history found for chat_id={chat_id}")
                return
            
            # Build a readable conversation text from MySQL records
            conversation_lines = []
            # 检测是否老客户：历史对话中是否出现过 "[我已付款，等待你发货]"
            is_returning_customer = False
            for msg in history:
                msg_type = msg.message_type
                content = msg.message_content or ""
                
                # Skip empty messages
                if not content.strip():
                    continue
                
                # 检测付款记录（闲鱼系统消息或用户消息中包含付款标记）
                if "我已付款，等待你发货" in content:
                    is_returning_customer = True
                
                # Clean up debug markers for readability
                if content.startswith("【调试】"):
                    content = content[4:]
                
                if isinstance(msg_type, str):
                    type_str = msg_type
                else:
                    type_str = msg_type.value if hasattr(msg_type, 'value') else str(msg_type)
                
                if type_str == "user":
                    conversation_lines.append(f"用户: {content}")
                elif type_str == "seller":
                    conversation_lines.append(f"客服: {content}")
            
            if not conversation_lines:
                return
            
            # 将老客户标记存入 session context
            session.context["is_returning_customer"] = is_returning_customer
            if is_returning_customer:
                logger.info(f"chat_id={chat_id}: 检测到老客户（历史对话中有付款记录）")
            
            # Build context summary directly (for short histories) 
            # or call LLM to summarize (for long histories)
            conversation_text = "\n".join(conversation_lines)
            
            # 在摘要前附加老客户标记
            returning_customer_tag = "【老客户】该用户之前有过付款记录。" if is_returning_customer else "【新客户】该用户暂无历史付款记录。"
            
            if len(conversation_lines) <= 10:
                # Short history: use as-is
                summary = f"{returning_customer_tag}\n\n以下是与该用户之前的对话记录：\n{conversation_text}"
            else:
                # Longer history: call LLM to summarize
                summary = self._summarize_history(conversation_text, is_returning_customer=is_returning_customer)
                if not summary:
                    # Fallback: use last few messages as context
                    recent_lines = conversation_lines[-10:]
                    summary = f"{returning_customer_tag}\n\n以下是与该用户最近的对话记录：\n" + "\n".join(recent_lines)
                else:
                    # 确保摘要中包含老客户标记
                    if returning_customer_tag not in summary:
                        summary = f"{returning_customer_tag}\n\n{summary}"
            
            # Inject into session context
            session.context["context_summary"] = summary
            logger.info(
                f"Loaded conversation history for chat_id={chat_id}: "
                f"{len(history)} records, summary {len(summary)} chars, "
                f"returning_customer={is_returning_customer}"
            )
            
            # Step 4: Cache the result for future requests
            self._set_cached_summary(chat_id, summary, is_returning_customer, fingerprint)
            
        except Exception as e:
            logger.warning(
                f"Failed to load conversation history for chat_id={chat_id}: {e}",
                exc_info=True
            )
    
    def _fetch_xianyu_api_history(self, chat_id: str) -> list:
        """
        Synchronously fetch all messages from the Xianyu WebSocket API.

        Uses a ThreadPoolExecutor to call asyncio.run() safely even when called
        from within a FastAPI async context (avoids "event loop already running" errors).

        Returns:
            List of {send_user_id, send_user_name, message} dicts in chronological order.
            Empty list if the provider is unavailable or an error occurs.
        """
        import asyncio
        import concurrent.futures
        from ai_kefu.xianyu_provider import get_provider

        try:
            provider = get_provider()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, provider.list_all_conversations(chat_id))
                messages = future.result(timeout=30)
            logger.info(
                f"[api_history] Fetched {len(messages)} msgs from Xianyu API for chat_id={chat_id}"
            )
            return messages
        except Exception as e:
            logger.warning(
                f"[api_history] Failed to fetch Xianyu API history for chat_id={chat_id}: {e}"
            )
            return []

    def _compress_by_time_proximity(self, messages: list) -> str:
        """
        Apply tiered time-proximity compression to a raw Xianyu API message list.

        Tiers:
        - Last 20 messages  → verbatim   (most recent context, highest signal)
        - Messages 20–60    → LLM-summarize as 【近期对话摘要】
        - Messages 60+      → LLM-summarize as 【早期对话摘要】

        Returns:
            A formatted multi-section string ready to inject into
            session.context["context_summary"], or "" if no text could be extracted.
        """
        RECENT_WINDOW = 20
        MIDTERM_WINDOW = 40  # messages 20–60 from the end

        def _extract_text(m: dict):
            reminder = m.get("message", {}).get("reminderContent")
            if reminder and isinstance(reminder, str) and reminder.strip():
                name = m.get("send_user_name") or m.get("send_user_id") or "用户"
                return f"{name}: {reminder.strip()}"
            return None

        lines = [t for m in messages if (t := _extract_text(m))]

        if not lines:
            return ""

        recent = lines[-RECENT_WINDOW:]
        midterm = lines[-(RECENT_WINDOW + MIDTERM_WINDOW):-RECENT_WINDOW]
        early = lines[:-(RECENT_WINDOW + MIDTERM_WINDOW)]

        parts = []

        if early:
            early_text = "\n".join(early)
            early_summary = (
                self._summarize_history(early_text)
                or f"（早期对话 {len(early)} 条，已省略）"
            )
            parts.append(f"【早期对话摘要】\n{early_summary}")

        if midterm:
            mid_text = "\n".join(midterm)
            mid_summary = (
                self._summarize_history(mid_text)
                or f"（中期对话 {len(midterm)} 条，已省略）"
            )
            parts.append(f"【近期对话摘要】\n{mid_summary}")

        parts.append(f"【最新对话记录（{len(recent)} 条）】\n" + "\n".join(recent))

        return "\n\n".join(parts)

    def _summarize_history(self, conversation_text: str, is_returning_customer: bool = False) -> Optional[str]:
        """
        Use LLM to summarize conversation history into a compact context.
        
        Args:
            conversation_text: Formatted conversation text
            is_returning_customer: Whether this user has payment history (returning customer)
            
        Returns:
            Summary string, or None if failed
        """
        from ai_kefu.llm.qwen_client import call_qwen_fast
        
        returning_tag = "【老客户】该用户之前有过付款记录。" if is_returning_customer else "【新客户】该用户暂无历史付款记录。"
        
        prompt = f"""请将以下客服对话历史压缩成一段简洁的上下文摘要。

要求：
1. 摘要开头必须标注客户类型：{returning_tag}
2. 保留关键信息：用户的核心需求、已确认的订单/租赁信息、价格、日期等
3. 保留对话状态：当前进展到哪一步、还有哪些待确认的事项
4. 保留用户偏好和情绪倾向
5. 去掉冗余的寒暄、重复的信息
6. 使用第三人称描述（"用户"、"客服"）
7. 控制在 200 字以内

对话历史：
{conversation_text}

请输出压缩后的上下文摘要："""
        
        try:
            response = call_qwen_fast(
                messages=[
                    {"role": "system", "content": "你是一个专业的对话摘要助手。"},
                    {"role": "user", "content": prompt}
                ],
                tools=None,
                max_tokens=300,
                temperature=0.3,
                model=settings.model_name_light,  # 摘要任务，使用 flash 模型降低成本
            )
            
            summary = response["choices"][0]["message"].get("content", "")
            if summary:
                summary = summary.strip()
                logger.info(f"Generated history summary: {len(summary)} chars")
                return summary
            return None
            
        except Exception as e:
            logger.warning(f"Failed to summarize history: {e}")
            return None
