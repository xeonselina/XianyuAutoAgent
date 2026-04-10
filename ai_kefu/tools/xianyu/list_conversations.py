"""
Tool: list_conversations
拉取指定会话的历史消息列表，用于了解买家历史咨询内容。
底层调用由 xianyu_provider 层统一管理。
"""

import asyncio
from typing import Dict, Any, List

from ai_kefu.xianyu_provider import get_provider
from ai_kefu.utils.logging import logger


def list_conversations(chat_id: str) -> Dict[str, Any]:
    """
    Fetch the full history of messages in a Xianyu chat session.

    Args:
        chat_id: Xianyu conversation/session ID（会话ID，不含 @goofish 后缀）.

    Returns:
        {
            "success": bool,
            "chat_id": str,
            "count": int,
            "messages": [
                {
                    "send_user_id": str,
                    "send_user_name": str,
                    "message": dict     # decoded message payload
                },
                ...
            ],
            "error": str    # only when success=False
        }
    """
    try:
        logger.info(f"[list_conversations] Fetching history for chat_id={chat_id}")
        provider = get_provider()
        messages: List[Dict[str, Any]] = asyncio.run(
            provider.list_all_conversations(chat_id)
        )
        logger.info(
            f"[list_conversations] OK: chat_id={chat_id}, count={len(messages)}"
        )
        return {
            "success": True,
            "chat_id": chat_id,
            "count": len(messages),
            "messages": messages,
        }

    except ValueError as e:
        msg = str(e)
        logger.error(f"[list_conversations] Config error: {msg}")
        return {"success": False, "chat_id": chat_id, "count": 0, "messages": [], "error": msg}

    except Exception as e:
        msg = f"list_conversations failed: {e}"
        logger.error(msg, exc_info=True)
        return {"success": False, "chat_id": chat_id, "count": 0, "messages": [], "error": msg}


def get_tool_definition() -> Dict[str, Any]:
    """Return the Qwen function-calling tool definition."""
    return {
        "name": "list_conversations",
        "description": (
            "查询指定闲鱼会话的历史消息记录。\n\n"
            "使用场景：\n"
            "- 需要回顾买家历史咨询内容以提供更准确回复时\n"
            "- 需要了解买家之前提到的需求或问题时\n\n"
            "注意：chat_id 由系统上下文提供，通常与当前对话的 cid 相同。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "闲鱼会话ID（不含 @goofish 后缀，从上下文获取）",
                }
            },
            "required": ["chat_id"],
        },
    }
