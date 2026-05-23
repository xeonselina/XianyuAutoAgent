"""
Loop detection service.
T040 - Detect and prevent agent loops.
"""

import json
from ai_kefu.models.session import AgentState, ToolCall
from ai_kefu.config.constants import LOOP_DETECTION_THRESHOLD
from ai_kefu.utils.logging import logger


def check_tool_loop(state: AgentState, tool_call: ToolCall) -> bool:
    """
    Check if tool call creates a loop.
    
    Args:
        state: Agent runtime state
        tool_call: Tool call to check
        
    Returns:
        True if loop detected, False otherwise
    """
    # Create signature for this tool call
    signature = f"{tool_call.name}:{json.dumps(tool_call.args, sort_keys=True)}"
    
    # Count occurrences in recent history
    count = state.recent_tool_calls.count(signature)
    
    # Check if threshold exceeded
    if count >= LOOP_DETECTION_THRESHOLD:
        logger.warning(
            f"Loop detected: tool '{tool_call.name}' called {count} times with same arguments"
        )
        state.loop_detected = True
        state.loop_count += 1
        return True
    
    # Add to history
    state.recent_tool_calls.append(signature)
    
    # Limit history size to last 10 calls
    if len(state.recent_tool_calls) > 10:
        state.recent_tool_calls.pop(0)
    
    return False


def reset_loop_state(state: AgentState) -> None:
    """
    Reset loop detection state.
    
    Args:
        state: Agent runtime state
    """
    state.loop_detected = False
    state.loop_count = 0
    state.recent_tool_calls.clear()
    logger.info("Loop detection state reset")


def get_loop_info(state: AgentState) -> dict:
    """
    Get current loop detection information.
    
    Args:
        state: Agent runtime state
        
    Returns:
        Dict with loop information
    """
    return {
        "loop_detected": state.loop_detected,
        "loop_count": state.loop_count,
        "recent_calls_count": len(state.recent_tool_calls),
        "threshold": LOOP_DETECTION_THRESHOLD
    }
