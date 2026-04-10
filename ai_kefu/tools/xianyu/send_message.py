"""
Tool: send_xianyu_message
向闲鱼买家发送消息。底层调用由 xianyu_provider 层统一管理。
"""

import asyncio
from typing import Dict, Any

from ai_kefu.xianyu_provider import get_provider
from ai_kefu.utils.logging import logger


def send_xianyu_message(chat_id: str, buyer_id: str, text: str) -> Dict[str, Any]:
    """
    Send a text message to a Xianyu chat session.

    Args:
        chat_id:   Xianyu conversation/session ID (会话ID，不含 @goofish 后缀).
        buyer_id:  Buyer's Xianyu user ID (买家用户ID，不含 @goofish 后缀).
        text:      The message content to send.

    Returns:
        {
            "success": bool,
            "chat_id": str,
            "message": str,    # echoes the sent text
            "error": str       # only when success=False
        }
    """
    try:
        logger.info(f"[send_xianyu_message] chat_id={chat_id}, buyer_id={buyer_id}")
        provider = get_provider()
        return asyncio.run(provider.send_message_once(chat_id, buyer_id, text))

    except ValueError as e:
        msg = str(e)
        logger.error(f"[send_xianyu_message] Config error: {msg}")
        return {"success": False, "error": msg}

    except Exception as e:
        msg = f"send_xianyu_message failed: {e}"
        logger.error(msg, exc_info=True)
        return {"success": False, "error": msg}


def get_tool_definition() -> Dict[str, Any]:
    """Return the Qwen function-calling tool definition."""
    return {
        "name": "send_xianyu_message",
        "description": (
            "向闲鱼买家发送消息。\n\n"
            "使用场景：\n"
            "- 需要主动向买家发送通知（如发货通知、价格变动等）时\n"
            "- 需要回复买家消息时（通常由外部消息监听器自动触发，此工具用于AI主动发送）\n\n"
            "注意：\n"
            "- chat_id 和 buyer_id 由系统上下文提供，无需向买家询问\n"
            "- 发送前请确认消息内容完整、礼貌"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "闲鱼会话ID（从对话上下文获取，不含 @goofish）",
                },
                "buyer_id": {
                    "type": "string",
                    "description": "买家的闲鱼用户ID（从对话上下文获取）",
                },
                "text": {
                    "type": "string",
                    "description": "要发送的消息文本内容",
                },
            },
            "required": ["chat_id", "buyer_id", "text"],
        },
    }
