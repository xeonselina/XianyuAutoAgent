"""
Complete task tool implementation.
T037 - complete_task tool.
"""

from typing import Dict, Any
from ai_kefu.utils.logging import logger


def complete_task(summary: str, resolved: bool) -> Dict[str, Any]:
    """
    Mark customer service task as complete.
    
    Args:
        summary: Brief summary of the conversation
        resolved: Whether the user's issue was resolved
        
    Returns:
        Dict with completion status:
        {
            "success": bool,
            "status": "completed",
            "resolved": bool,
            "summary": str,
            "message": str
        }
    """
    logger.info(f"Task completion: resolved={resolved}, summary='{summary}'")
    
    if resolved:
        message = "任务已完成，用户问题已解决"
    else:
        message = "任务已完成，但问题可能需要进一步跟进"
    
    return {
        "success": True,
        "status": "completed",
        "resolved": resolved,
        "summary": summary,
        "message": message
    }


def get_tool_definition() -> Dict[str, Any]:
    """
    Get complete_task tool definition for Qwen Function Calling.
    
    Returns:
        Tool definition dict
    """
    return {
        "name": "complete_task",
        "description": """标记客服对话完成。

使用场景：
- 用户的问题已经完全解决
- 用户表示满意或感谢
- 对话已经达到预期目标

注意：
- 只有在确认用户问题解决后才调用
- 提供简要的对话总结
- 明确标记问题是否已解决
""",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "对话总结（简要概括用户问题和解决方案）"
                },
                "resolved": {
                    "type": "boolean",
                    "description": "问题是否已解决（true=已解决，false=未解决或需要进一步跟进）"
                }
            },
            "required": ["summary", "resolved"]
        }
    }
