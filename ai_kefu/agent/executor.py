"""
Agent executor - Main orchestrator for Plan-Action-Check loop.
T043 - AgentExecutor with run() and stream() methods.
"""

import uuid
from datetime import datetime
from typing import Optional, AsyncGenerator
from ai_kefu.agent.types import AgentConfig
from ai_kefu.agent.turn import execute_turn
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
    SessionNotFoundError
)


class AgentExecutor:
    """
    Main agent executor implementing Plan-Action-Check loop.
    """
    
    def __init__(
        self,
        session_store: SessionStore,
        config: Optional[AgentConfig] = None
    ):
        """
        Initialize agent executor.
        
        Args:
            session_store: Session storage
            config: Agent configuration
        """
        self.session_store = session_store
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
            collect_rental_info
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
        user_id: Optional[str] = None
    ) -> dict:
        """
        Run agent synchronously (complete conversation).
        
        Args:
            query: User query
            session_id: Existing session ID (optional)
            user_id: User ID (optional)
            
        Returns:
            Dict with response
        """
        start_time = datetime.utcnow()
        
        # Load or create session
        session = self._get_or_create_session(session_id, user_id)
        
        # Create agent state for loop detection
        agent_state = AgentState(session_id=session.session_id)
        
        # Execute turns until completion
        response_text = ""
        
        try:
            while True:
                # Check max turns
                if session.turn_counter >= self.config.max_turns:
                    raise MaxTurnsExceededError(session.session_id, self.config.max_turns)
                
                # Execute turn
                turn_result = execute_turn(
                    session=session,
                    user_message=query,
                    tools_registry=self.tools_registry
                )
                
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
                
                # Store intermediate response
                response_text = turn_result.response_text
                
                # For synchronous mode, we stop after first turn
                # (Multi-turn would need user input for next turn)
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
                    "duration_ms": duration_ms
                }
            }
            
        except Exception as e:
            logger.error(f"Agent execution failed: {e}", exc_info=True)
            session.status = SessionStatus.ERROR
            session.terminate_reason = TerminateReason.ERROR
            self.session_store.set(session)
            
            return {
                "session_id": session.session_id,
                "status": session.status,
                "error": str(e)
            }
    
    async def stream(
        self,
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        Run agent with streaming (for real-time responses).
        
        Args:
            query: User query
            session_id: Existing session ID (optional)
            user_id: User ID (optional)
            
        Yields:
            Response chunks
        """
        # For now, just yield the sync result
        # Full streaming would require streaming from Qwen API
        result = self.run(query, session_id, user_id)
        
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
        user_id: Optional[str]
    ) -> Session:
        """
        Get existing session or create new one.
        
        Args:
            session_id: Existing session ID (optional)
            user_id: User ID (optional)
            
        Returns:
            Session object
        """
        if session_id:
            # Try to load existing session
            session = self.session_store.get(session_id)
            if session:
                logger.info(f"Loaded existing session: {session_id}")
                return session
            else:
                logger.warning(f"Session not found: {session_id}, creating new")
        
        # Create new session
        new_session = Session(
            session_id=str(uuid.uuid4()),
            user_id=user_id,
            status=SessionStatus.ACTIVE
        )
        
        logger.info(f"Created new session: {new_session.session_id}")
        return new_session
