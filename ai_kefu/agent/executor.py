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
from ai_kefu.models.session import Session, AgentState
from ai_kefu.storage.session_store import SessionStore
from ai_kefu.tools.tool_registry import ToolRegistry
from ai_kefu.tools import knowledge_search, complete_task
from ai_kefu.services.loop_detection import check_tool_loop
from ai_kefu.config.constants import SessionStatus, TerminateReason, TOOL_COMPLETE_TASK
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
        session = self._get_or_create_session(session_id, user_id, chat_id=chat_id)
        
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
        
        # Execute turns until completion
        response_text = ""
        is_first_turn = True
        last_turn_metadata = {}
        
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
                    is_tool_continue=not is_first_turn
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
                            error_message=turn_result.error_message
                        )
                    except Exception as e:
                        logger.warning(f"Failed to persist turn data (non-fatal): {e}")
                
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
                    logger.info(f"Turn {session.turn_counter} completed with response, ending agent execution")
                    last_turn_metadata = turn_result.metadata
                    break
                
                # If no tool calls and no response text, something is wrong
                # (could be confidence guard suppression — still capture metadata)
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
        chat_id: Optional[str] = None
    ) -> Session:
        """
        Get existing session or create new one.
        When creating a new session, load conversation history from MySQL
        and generate a context summary so the LLM knows the conversation background.
        
        Args:
            session_id: Existing session ID (optional)
            user_id: User ID (optional)
            chat_id: Xianyu chat ID (for loading history from MySQL on new sessions)
            
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
                    if session.context.get("context_summary"):
                        self.session_store.set(session)  # Persist the updated context
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
                return new_session
        
        # Create new session with generated ID
        new_session = Session(
            session_id=str(uuid.uuid4()),
            user_id=user_id,
            status=SessionStatus.ACTIVE
        )
        # Load conversation history from MySQL for context
        self._load_history_as_context(new_session, chat_id)
        
        logger.info(f"Created new session: {new_session.session_id}")
        return new_session

    def _load_history_as_context(self, session: Session, chat_id: Optional[str]):
        """
        Load conversation history from MySQL and inject as context summary.
        
        This ensures that when a Redis session expires and a new one is created,
        the LLM still has context about previous conversations with this user.
        
        Args:
            session: The newly created session
            chat_id: Xianyu chat ID to query history for
        """
        if not chat_id or not self.conversation_store:
            return
        
        try:
            # Load recent conversation history from MySQL
            # Get the last N messages for this chat_id
            history = self.conversation_store.get_conversation_history(
                chat_id=chat_id,
                limit=30  # Get last 30 messages for summarization
            )
            
            if not history:
                logger.debug(f"No conversation history found for chat_id={chat_id}")
                return
            
            # Build a readable conversation text from MySQL records
            conversation_lines = []
            for msg in history:
                msg_type = msg.message_type
                content = msg.message_content or ""
                
                # Skip empty messages
                if not content.strip():
                    continue
                
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
            
            # Build context summary directly (for short histories) 
            # or call LLM to summarize (for long histories)
            conversation_text = "\n".join(conversation_lines)
            
            if len(conversation_lines) <= 10:
                # Short history: use as-is
                summary = f"以下是与该用户之前的对话记录：\n{conversation_text}"
            else:
                # Longer history: call LLM to summarize
                summary = self._summarize_history(conversation_text)
                if not summary:
                    # Fallback: use last few messages as context
                    recent_lines = conversation_lines[-10:]
                    summary = f"以下是与该用户最近的对话记录：\n" + "\n".join(recent_lines)
            
            # Inject into session context
            session.context["context_summary"] = summary
            logger.info(
                f"Loaded conversation history for chat_id={chat_id}: "
                f"{len(history)} records, summary {len(summary)} chars"
            )
            
        except Exception as e:
            logger.warning(
                f"Failed to load conversation history for chat_id={chat_id}: {e}",
                exc_info=True
            )
    
    def _summarize_history(self, conversation_text: str) -> Optional[str]:
        """
        Use LLM to summarize conversation history into a compact context.
        
        Args:
            conversation_text: Formatted conversation text
            
        Returns:
            Summary string, or None if failed
        """
        from ai_kefu.llm.qwen_client import call_qwen
        
        prompt = f"""请将以下客服对话历史压缩成一段简洁的上下文摘要。

要求：
1. 保留关键信息：用户的核心需求、已确认的订单/租赁信息、价格、日期等
2. 保留对话状态：当前进展到哪一步、还有哪些待确认的事项
3. 保留用户偏好和情绪倾向
4. 去掉冗余的寒暄、重复的信息
5. 使用第三人称描述（"用户"、"客服"）
6. 控制在 300 字以内

对话历史：
{conversation_text}

请输出压缩后的上下文摘要："""
        
        try:
            response = call_qwen(
                messages=[
                    {"role": "system", "content": "你是一个专业的对话摘要助手。"},
                    {"role": "user", "content": prompt}
                ],
                tools=None,
                max_tokens=500,
                temperature=0.3,
                model=settings.model_name_light  # 摘要任务，使用 flash 模型降低成本
            )
            
            summary = response["choices"][0]["message"].get("content", "")
            if summary:
                summary = self._build_structured_history_summary(conversation_text, summary.strip())
                logger.info(f"Generated history summary: {len(summary)} chars")
                return summary
            return None
            
        except Exception as e:
            logger.warning(f"Failed to summarize history: {e}")
            return None
