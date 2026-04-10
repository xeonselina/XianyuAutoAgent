"""
Tool: get_buyer_info
查询闲鱼买家信息，包括购买历史统计和地区信息。底层调用由 xianyu_provider 层统一管理。
"""

import asyncio
from typing import Dict, Any

from ai_kefu.xianyu_provider import get_provider
from ai_kefu.utils.logging import logger


def get_buyer_info(buyer_id: str) -> Dict[str, Any]:
    """
    Fetch Xianyu buyer information including purchase history and location.

    Args:
        buyer_id: The Xianyu buyer/user ID (买家ID，通常不含 @goofish 后缀).

    Returns:
        {
            "success": bool,
            "buyer_id": str,
            "buyer_nick": str,              # 买家昵称
            "buy_count": int,               # 买家总购买次数
            "deal_count": int,              # 买家成交次数
            "trade_count": int,             # 交易总数
            "has_bought": bool,             # 是否从当前卖家购买过
            "user_type": int,               # 1=买家, 2=卖家
            "location": str,                # 用户地区信息
            "error": str,                   # only when success=False
            "_raw_api_response": dict       # 完整 API 响应（用于调试）
        }
    """
    try:
        logger.info(f"[get_buyer_info] Fetching buyer info: {buyer_id}")
        provider = get_provider()
        result = asyncio.run(provider.get_buyer_info(str(buyer_id)))

        if result["success"]:
            logger.info(
                f"[get_buyer_info] OK: buyer_id={buyer_id}, "
                f"nick={result.get('buyer_nick')!r}, "
                f"has_bought={result.get('has_bought')}, "
                f"buy_count={result.get('buy_count')}"
            )
        else:
            logger.warning(
                f"[get_buyer_info] FAILED: buyer_id={buyer_id}, error={result.get('error')}"
            )
        return result

    except ValueError as e:
        msg = str(e)
        logger.error(f"[get_buyer_info] Config error: {msg}")
        return {"success": False, "error": msg}

    except Exception as e:
        msg = f"get_buyer_info failed: {e}"
        logger.error(msg, exc_info=True)
        return {"success": False, "error": msg}


def get_tool_definition() -> Dict[str, Any]:
    """Return the Qwen function-calling tool definition."""
    return {
        "name": "get_buyer_info",
        "description": (
            "查询闲鱼买家信息和购买历史统计。\n\n"
            "使用场景：\n"
            "- 判断买家是否为重复客户（has_bought=true）\n"
            "- 查看买家的购买能力和信用度（buy_count, deal_count）\n"
            "- 获取买家地区用于物流和运费计算\n"
            "- 评估买家风险等级（基于购买历史）\n\n"
            "返回信息：\n"
            "- buyer_nick: 买家昵称\n"
            "- buy_count: 总购买次数\n"
            "- deal_count: 成交次数\n"
            "- has_bought: 是否从你购买过\n"
            "- location: 用户地区\n"
            "- user_type: 用户类型（1=买家, 2=卖家）"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "buyer_id": {
                    "type": "string",
                    "description": "闲鱼买家ID（通常从对话上下文或系统提供）",
                }
            },
            "required": ["buyer_id"],
        },
    }
