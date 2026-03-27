"""
订单状态查询工具
用于查询订单阶段和物流信息（当前为安全占位实现，可后续接入真实 OMS）。
"""

from typing import Dict, Any, Optional


MOCK_ORDER_STATUS = {
    "paid": "已付款",
    "pending_ship": "待发货",
    "shipped": "已发货",
    "in_transit": "运输中",
    "delivered": "已签收",
    "returned": "已归还",
}


def get_order_status(order_id: Optional[str] = None) -> Dict[str, Any]:
    """
    查询订单状态。

    Args:
        order_id: 订单号（可选）

    Returns:
        状态信息。当前未接真实订单系统时返回“需人工核验”的安全结果。
    """
    if not order_id:
        return {
            "success": False,
            "order_id": None,
            "status": None,
            "tracking_no": None,
            "need_human_check": True,
            "message": "请提供订单号，我帮你查订单状态。",
        }

    return {
        "success": True,
        "order_id": order_id,
        "status": MOCK_ORDER_STATUS["pending_ship"],
        "tracking_no": None,
        "need_human_check": True,
        "message": "当前状态为待发货，物流单号生成后我会同步你。",
    }


def get_tool_definition() -> Dict[str, Any]:
    """获取工具定义（用于 Function Calling）。"""
    return {
        "name": "get_order_status",
        "description": "查询订单状态与物流信息。用户问发货/单号/订单进度时应优先调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "订单号"
                }
            },
            "required": []
        }
    }
