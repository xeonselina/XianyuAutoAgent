"""
Tool: create_chat
主动向买家发起新的闲鱼会话，关联指定商品。
底层调用由 xianyu_provider 层统一管理，需要已有的 WebSocket 连接。
"""

from typing import Dict, Any

from ai_kefu.utils.logging import logger


def create_chat(
    websocket: Any,
    buyer_id: str,
    item_id: str,
) -> Dict[str, Any]:
    """
    Proactively initiate a new Xianyu chat session with a buyer for a specific item.

    This is a low-level wrapper — the websocket object must already be connected.
    In practice, the main WebSocket event loop should call
    ``provider.create_chat(websocket, buyer_id, item_id)`` directly.

    Args:
        websocket: An active websockets connection object.
        buyer_id:  Buyer's Xianyu user ID（不含 @goofish 后缀）.
        item_id:   The Xianyu item ID to associate with the chat.

    Returns:
        {"success": bool, "message": str, "error": str (on failure)}
    """
    import asyncio
    from ai_kefu.xianyu_provider import get_provider

    try:
        logger.info(
            f"[create_chat] Initiating chat: buyer_id={buyer_id}, item_id={item_id}"
        )
        provider = get_provider()
        asyncio.run(provider.create_chat(websocket, buyer_id, item_id))
        logger.info(f"[create_chat] Chat initiated: buyer_id={buyer_id}")
        return {
            "success": True,
            "message": f"已向买家 {buyer_id} 发起商品 {item_id} 的对话",
        }
    except ValueError as e:
        msg = str(e)
        logger.error(f"[create_chat] Config error: {msg}")
        return {"success": False, "error": msg}
    except Exception as e:
        msg = f"create_chat failed: {e}"
        logger.error(msg, exc_info=True)
        return {"success": False, "error": msg}


def get_tool_definition() -> Dict[str, Any]:
    """Return the Qwen function-calling tool definition."""
    return {
        "name": "create_chat",
        "description": (
            "主动向闲鱼买家发起新会话，关联指定商品。\n\n"
            "使用场景：\n"
            "- 买家下单后主动发送确认或欢迎消息时\n"
            "- 需要就特定商品主动联系买家时\n\n"
            "注意：\n"
            "- 此操作需要活跃的 WebSocket 连接，通常由系统自动管理\n"
            "- buyer_id 和 item_id 从对话上下文或订单信息中获取"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "buyer_id": {
                    "type": "string",
                    "description": "买家闲鱼用户ID（不含 @goofish）",
                },
                "item_id": {
                    "type": "string",
                    "description": "关联商品的闲鱼商品ID",
                },
            },
            "required": ["buyer_id", "item_id"],
        },
    }
