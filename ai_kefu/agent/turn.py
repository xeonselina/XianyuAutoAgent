"""
Single turn execution logic.
T042 - Execute one turn of agent conversation.
"""

import json
from datetime import datetime, date
from typing import List, Dict, Any
from ai_kefu.agent.types import TurnResult
from ai_kefu.models.session import Session, Message, ToolCall
from ai_kefu.config.constants import MessageRole, ToolCallStatus
from ai_kefu.llm.qwen_client import call_qwen
from ai_kefu.tools.tool_registry import ToolRegistry
from ai_kefu.utils.logging import logger, log_turn_start, log_turn_end, log_tool_call, log_tool_result
from ai_kefu.prompts.rental_system_prompt import RENTAL_CUSTOMER_SERVICE_PROMPT as CUSTOMER_SERVICE_SYSTEM_PROMPT


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


def validate_message_sequence(messages: List[Dict[str, Any]]) -> tuple[bool, str]:
    """
    Validate that message sequence follows Qwen API requirements.
    
    An assistant message with tool_calls must be followed by tool messages
    for each tool_call_id.
    
    Returns:
        (is_valid, error_message)
    """
    pending_tool_call_ids = set()
    
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
                logger.warning(f"Message[{i}] (tool): unexpected tool_call_id={tool_call_id}")
        
        elif role == "user":
            # A new user message means any pending tool calls should have been resolved
            if pending_tool_call_ids:
                error_msg = f"Message[{i}] (user): found user message but {len(pending_tool_call_ids)} tool_call_ids are still pending: {pending_tool_call_ids}"
                logger.error(error_msg)
                return False, error_msg
    
    # At the end, all tool calls should be resolved
    if pending_tool_call_ids:
        error_msg = f"End of messages: {len(pending_tool_call_ids)} tool_call_ids still pending: {pending_tool_call_ids}"
        logger.error(error_msg)
        return False, error_msg
    
    return True, ""


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
        
        # Validate message sequence
        is_valid, error_msg = validate_message_sequence(messages)
        if not is_valid:
            logger.error(f"Invalid message sequence: {error_msg}")
            logger.error(f"Full message history: {json.dumps([{'role': m.get('role'), 'has_tool_calls': 'tool_calls' in m, 'tool_call_id': m.get('tool_call_id')} for m in messages], indent=2)}")
            raise ValueError(f"Invalid message sequence: {error_msg}")
        
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
