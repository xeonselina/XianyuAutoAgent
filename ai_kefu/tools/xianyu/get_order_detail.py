"""
Tool: get_order_detail
查询闲鱼订单详情。底层调用由 xianyu_provider 层统一管理。
"""

import asyncio
from typing import Dict, Any

from ai_kefu.xianyu_provider import get_provider
from ai_kefu.utils.logging import logger


def get_order_detail(order_id: str) -> Dict[str, Any]:
    """
    Fetch Xianyu order details by order ID.

    Args:
        order_id: The Xianyu order ID (订单号).

    Returns:
        {
            "success": bool,
            "order_id": str,
            "item_id": str,
            "item_title": str,
            "sku": str,            # e.g. "颜色: 红色；尺码: L"
            "quantity": str,       # quantity purchased
            "amount": str,         # total payment in 元, e.g. "199.00"
            "status": str,         # raw status code
            "status_label": str,   # human-readable status
            "buyer_id": str,
            "buyer_nickname": str,
            "create_time": str,
            "error": str           # only when success=False
        }
    """
    try:
        logger.info(f"[get_order_detail] Fetching order: {order_id}")
        provider = get_provider()
        result = asyncio.run(provider.get_order_detail(str(order_id)))

        if result["success"]:
            logger.info(
                f"[get_order_detail] OK: order_id={order_id}, "
                f"status={result.get('status_label')!r}, "
                f"amount={result.get('amount')!r}"
            )
        else:
            logger.warning(
                f"[get_order_detail] FAILED: order_id={order_id}, error={result.get('error')}"
            )
        return result

    except ValueError as e:
        msg = str(e)
        logger.error(f"[get_order_detail] Config error: {msg}")
        return {"success": False, "error": msg}

    except Exception as e:
        msg = f"get_order_detail failed: {e}"
        logger.error(msg, exc_info=True)
        return {"success": False, "error": msg}


def get_tool_definition() -> Dict[str, Any]:
    """Return the Qwen function-calling tool definition."""
    return {
        "name": "get_order_detail",
        "description": (
            "查询闲鱼订单详情。\n\n"
            "使用场景：\n"
            "- 买家询问订单状态（是否发货、金额、规格等）时\n"
            "- 需要确认买家付款状态时\n"
            "- 需要获取订单的SKU、数量信息时\n\n"
            "注意：order_id 通常出现在买家发来的消息中（如\"我已付款\"系统卡片）或由上下文提供。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "闲鱼订单ID（订单号）",
                }
            },
            "required": ["order_id"],
        },
    }
