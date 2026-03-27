"""
归还地址查询工具
用于提供标准归还地址，避免客服回复中编造地址。
"""

from typing import Dict, Any, Optional


DEFAULT_RETURN_ADDRESS = {
    "receiver_name": "租赁客服",
    "receiver_phone": "请联系客服获取最新电话",
    "province": "广东省",
    "city": "深圳市",
    "district": "南山区",
    "detail": "西丽街道松坪村竹苑9栋4单元415",
    "full_address": "广东省深圳市南山区西丽街道松坪村竹苑9栋4单元415",
    "courier_suggestion": "建议顺丰寄回",
}


def get_return_address(order_id: Optional[str] = None) -> Dict[str, Any]:
    """
    查询归还地址。

    Args:
        order_id: 订单号（可选，当前用于透传记录，后续可接真实订单系统）

    Returns:
        归还地址信息
    """
    message = "请按以下地址归还设备，寄出后把快递单号发我。"
    if order_id:
        message = f"订单 {order_id} 的归还地址如下，寄出后把快递单号发我。"

    return {
        "success": True,
        "order_id": order_id,
        "address": DEFAULT_RETURN_ADDRESS,
        "message": message,
    }


def get_tool_definition() -> Dict[str, Any]:
    """获取工具定义（用于 Function Calling）。"""
    return {
        "name": "get_return_address",
        "description": "查询设备归还地址。用户询问归还地址/寄回地址时必须调用，避免编造地址。",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "订单号（可选）"
                }
            },
            "required": []
        }
    }
