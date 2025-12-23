"""
Single turn execution logic.
T042 - Execute one turn of agent conversation.
"""

import json
from datetime import datetime
from typing import List, Dict, Any
from ai_kefu.agent.types import TurnResult
from ai_kefu.models.session import Session, Message, ToolCall
from ai_kefu.config.constants import MessageRole, ToolCallStatus
from ai_kefu.llm.qwen_client import call_qwen
from ai_kefu.tools.tool_registry import ToolRegistry
from ai_kefu.utils.logging import logger, log_turn_start, log_turn_end, log_tool_call, log_tool_result
from ai_kefu.prompts.system_prompt import CUSTOMER_SERVICE_SYSTEM_PROMPT


def execute_turn(
    session: Session,
    user_message: str,
    tools_registry: ToolRegistry,
    system_prompt: str = CUSTOMER_SERVICE_SYSTEM_PROMPT
) -> TurnResult:
    """
    Execute one turn of conversation.
    
    Args:
        session: Current session
        user_message: User's message
        tools_registry: Tool registry
        system_prompt: System prompt
        
    Returns:
        TurnResult with turn execution results
    """
    start_time = datetime.utcnow()
    turn_counter = session.turn_counter + 1
    
    log_turn_start(session.session_id, turn_counter, user_message)
    
    try:
        # Add user message to session
        user_msg = Message(
            role=MessageRole.USER,
            content=user_message,
            timestamp=datetime.utcnow()
        )
        
        new_messages = [user_msg]
        
        # Build message history for Qwen
        messages = _build_message_history(session, user_msg, system_prompt)
        
        # Get tools in Qwen format
        tools = tools_registry.to_qwen_format()
        
        # Call Qwen API
        logger.info(f"Calling Qwen API for turn {turn_counter}")
        response = call_qwen(messages=messages, tools=tools if tools else None)
        
        # Parse response
        assistant_message = response["choices"][0]["message"]
        response_text = assistant_message.get("content", "")
        tool_calls_data = assistant_message.get("tool_calls", [])
        
        # Create assistant message
        assistant_msg = Message(
            role=MessageRole.ASSISTANT,
            content=response_text,
            timestamp=datetime.utcnow()
        )
        
        tool_call_objects = []
        
        # Execute tool calls if any
        if tool_calls_data:
            for tc in tool_calls_data:
                tool_name = tc["function"]["name"]
                tool_call_id = tc["id"]
                
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
                    
                    log_tool_result(
                        session.session_id,
                        tool_name,
                        tool_call_id,
                        success=False,
                        duration_ms=0
                    )
        
        # Add tool calls to assistant message
        if tool_call_objects:
            assistant_msg.tool_calls = tool_call_objects
        
        new_messages.insert(1, assistant_msg)  # Insert after user message
        
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
    
    # Add historical messages
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
    
    # Add new user message
    messages.append({"role": "user", "content": new_user_message.content})
    
    return messages
