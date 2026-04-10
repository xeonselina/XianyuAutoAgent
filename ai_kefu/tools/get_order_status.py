"""
订单状态查询工具
调用真实的 xianyu_provider.get_order_detail() API，不再使用占位 mock。
"""

from typing import Dict, Any, Optional

from ai_kefu.tools.xianyu.get_order_detail import get_order_detail as _get_order_detail


def get_order_status(order_id: Optional[str] = None) -> Dict[str, Any]:
    """
    查询订单状态。底层委托给 get_order_detail，返回精简的状态视图。

    Args:
        order_id: 订单号（可选）

    Returns:
        {
            "success": bool,
            "order_id": str | None,
            "status": str | None,          # human-readable 状态（status_label）
            "status_code": str | None,     # 原始状态码
            "tracking_no": str | None,     # 快递单号（目前接口不返回，预留）
            "item_title": str | None,      # 商品名
            "amount": str | None,          # 付款金额
            "buyer_nickname": str | None,  # 买家昵称
            "need_human_check": bool,      # 是否需要人工介入
            "message": str,               # 人类可读摘要
        }
    """
    if not order_id:
        return {
            "success": False,
            "order_id": None,
            "status": None,
            "status_code": None,
            "tracking_no": None,
            "item_title": None,
            "amount": None,
            "buyer_nickname": None,
            "need_human_check": True,
            "message": "请提供订单号，我帮你查订单状态。",
        }

    result = _get_order_detail(order_id)

    if not result.get("success"):
        err = result.get("error", "未知错误")
        return {
            "success": False,
            "order_id": order_id,
            "status": None,
            "status_code": None,
            "tracking_no": None,
            "item_title": None,
            "amount": None,
            "buyer_nickname": None,
            "need_human_check": True,
            "message": f"查询订单失败：{err}",
        }

    status_label = result.get("status_label") or result.get("status") or "未知状态"
    item_title = result.get("item_title", "")
    amount = result.get("amount", "")
    buyer = result.get("buyer_nickname", "")

    parts = [f"状态：{status_label}"]
    if item_title:
        parts.append(f"商品：{item_title}")
    if amount:
        parts.append(f"金额：¥{amount}")
    summary = "；".join(parts)

    return {
        "success": True,
        "order_id": order_id,
        "status": status_label,
        "status_code": result.get("status"),
        "tracking_no": None,          # 当前接口未返回快递单号，预留字段
        "item_title": item_title,
        "amount": amount,
        "buyer_nickname": buyer,
        "need_human_check": False,
        "message": summary,
    }


def get_tool_definition() -> Dict[str, Any]:
    """获取工具定义（用于 Function Calling）。"""
    return {
        "name": "get_order_status",
        "description": (
            "查询订单状态与基本信息。用户问发货、订单进度、付款状态时优先调用。\n\n"
            "返回状态、商品名、金额等关键信息。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "订单号（通常出现在买家消息或系统通知卡片中）"
                }
            },
            "required": []
        }
    }
