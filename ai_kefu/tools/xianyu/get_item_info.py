"""
Tool: get_item_info
查询闲鱼商品详情。底层调用由 xianyu_provider 层统一管理。
"""

import asyncio
from typing import Dict, Any

from ai_kefu.xianyu_provider import get_provider
from ai_kefu.utils.logging import logger


def get_item_info(item_id: str) -> Dict[str, Any]:
    """
    Fetch Xianyu item details by item ID.

    Args:
        item_id: The Xianyu item/product ID (商品ID).

    Returns:
        {
            "success": bool,
            "item_id": str,
            "title": str,
            "price": str,          # e.g. "99.00"
            "desc": str,
            "category": str,
            "image_url": str,
            "item_status": int,    # 0=在售, 1=已售, 2=下架
            "seller_id": str,
            "location": str,
            "error": str           # only when success=False
        }
    """
    try:
        logger.info(f"[get_item_info] Fetching item: {item_id}")
        provider = get_provider()
        result = asyncio.run(provider.get_item_info(str(item_id)))

        if result["success"]:
            logger.info(
                f"[get_item_info] OK: item_id={item_id}, title={result.get('title')!r}"
            )
        else:
            logger.warning(
                f"[get_item_info] FAILED: item_id={item_id}, error={result.get('error')}"
            )
        return result

    except ValueError as e:
        msg = str(e)
        logger.error(f"[get_item_info] Config error: {msg}")
        return {"success": False, "error": msg}

    except Exception as e:
        msg = f"get_item_info failed: {e}"
        logger.error(msg, exc_info=True)
        return {"success": False, "error": msg}


def get_tool_definition() -> Dict[str, Any]:
    """Return the Qwen function-calling tool definition."""
    return {
        "name": "get_item_info",
        "description": (
            "查询闲鱼商品详情。\n\n"
            "使用场景：\n"
            "- 买家询问商品的价格、描述、库存、规格等信息时\n"
            "- 需要确认商品是否仍在售时\n"
            "- 需要获取商品标题用于回答买家问题时\n\n"
            "注意：item_id 通常由系统上下文（context.item_id）提供，无需向买家询问。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "string",
                    "description": "闲鱼商品ID（通常从对话上下文中获取）",
                }
            },
            "required": ["item_id"],
        },
    }
