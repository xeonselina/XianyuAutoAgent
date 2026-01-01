"""
档期查询工具 - 调用档期管理 API 查询可租赁设备
T_RENTAL_001 - check_availability tool
"""

import requests
from typing import Dict, Any, Optional
from datetime import datetime
from ai_kefu.utils.logging import logger
from ai_kefu.config.settings import settings


def check_availability(
    start_date: str,
    end_date: str,
    logistics_days: int = 2,
    model: Optional[str] = None,
    is_accessory: bool = False
) -> Dict[str, Any]:
    """
    查询指定时间段内可租赁的设备档期。
    
    Args:
        start_date: 租赁开始日期 (YYYY-MM-DD 格式, 用户实际使用开始日期)
        end_date: 租赁结束日期 (YYYY-MM-DD 格式, 用户实际使用结束日期)
        logistics_days: 物流所需天数 (默认2天)
        model: 设备型号 ID (可选, 不指定则查询所有型号)
        is_accessory: 是否为配件 (默认 False)
        
    Returns:
        Dict with availability results:
        {
            "success": bool,
            "available_slots": [...],  # API 返回的可用档期
            "message": str,
            "error": str (if failed)
        }
    """
    try:
        logger.info(f"Checking availability: {start_date} to {end_date}, logistics={logistics_days}d, model={model}")
        
        # 验证日期格式
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as e:
            return {
                "success": False,
                "available_slots": [],
                "error": f"日期格式错误，请使用 YYYY-MM-DD 格式: {str(e)}"
            }
        
        # 验证日期逻辑
        if end_dt <= start_dt:
            return {
                "success": False,
                "available_slots": [],
                "error": "结束日期必须晚于开始日期"
            }
        
        # 计算租赁天数
        rental_days = (end_dt - start_dt).days
        
        # 构建请求数据
        payload = {
            "start_date": start_date,
            "end_date": end_date,
            "logistics_days": logistics_days,
            "is_accessory": is_accessory
        }
        
        # 如果指定了型号，添加到请求中
        if model:
            payload["model"] = model
        
        # 从配置获取 API 地址
        api_url = f"{settings.rental_api_base_url}{settings.rental_find_slot_endpoint}"
        
        # 调用档期查询 API
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "content-type": "application/json"
        }
        
        logger.info(f"Calling rental API: {api_url}")
        logger.debug(f"Request payload: {payload}")
        
        response = requests.post(
            api_url,
            json=payload,
            headers=headers,
            timeout=10  # 10秒超时
        )
        
        # 检查响应状态
        if response.status_code != 200:
            error_msg = f"API 请求失败 (状态码: {response.status_code}): {response.text}"
            logger.error(error_msg)
            return {
                "success": False,
                "available_slots": [],
                "error": error_msg
            }
        
        # 解析响应
        api_response = response.json()
        logger.debug(f"API response: {api_response}")
        
        # 根据 API 返回结果构建响应
        # 注意: 需要根据实际 API 响应格式调整
        available_slots = api_response.get("data", []) if isinstance(api_response.get("data"), list) else []
        
        if not available_slots:
            message = f"抱歉，{start_date} 至 {end_date} 期间暂无可租设备"
        else:
            message = f"找到 {len(available_slots)} 个可用档期"
        
        logger.info(f"Availability check completed: {len(available_slots)} slots found")
        
        return {
            "success": True,
            "available_slots": available_slots,
            "rental_days": rental_days,
            "start_date": start_date,
            "end_date": end_date,
            "logistics_days": logistics_days,
            "message": message,
            "api_response": api_response  # 保留完整 API 响应供参考
        }
        
    except requests.exceptions.Timeout:
        error_msg = "档期查询超时，请稍后重试"
        logger.error(error_msg)
        return {
            "success": False,
            "available_slots": [],
            "error": error_msg
        }
    except requests.exceptions.RequestException as e:
        error_msg = f"档期查询网络错误: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "success": False,
            "available_slots": [],
            "error": error_msg
        }
    except Exception as e:
        error_msg = f"档期查询失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "success": False,
            "available_slots": [],
            "error": error_msg
        }


def get_tool_definition() -> Dict[str, Any]:
    """
    获取档期查询工具定义（用于 Qwen Function Calling）
    
    Returns:
        工具定义字典
    """
    return {
        "name": "check_availability",
        "description": """查询手机租赁档期，检查指定时间段内是否有可租设备。

使用场景：
- 用户提供了租赁开始和结束日期时
- 需要确认是否有空闲设备可租时
- 在给出报价前，必须先确认档期

工作流程：
1. 用户提供收货日期和归还日期
2. 使用 calculate_logistics 计算物流天数
3. 调用此工具查询档期 (start_date = 收货日期 + 1天, end_date = 归还日期 - 1天)

注意：
- 日期格式必须为 YYYY-MM-DD
- start_date 是用户收到设备后开始使用的日期
- end_date 是用户归还设备前最后使用的日期
- logistics_days 由 calculate_logistics 工具计算得出
""",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "租赁开始日期 (格式: YYYY-MM-DD)。用户收到设备后的第一天使用日期"
                },
                "end_date": {
                    "type": "string",
                    "description": "租赁结束日期 (格式: YYYY-MM-DD)。用户归还设备前的最后一天使用日期"
                },
                "logistics_days": {
                    "type": "integer",
                    "description": "物流所需天数，由 calculate_logistics 工具计算得出",
                    "default": 2
                },
                "model": {
                    "type": "string",
                    "description": "设备型号 ID (可选)。如果不指定则查询所有可用型号"
                },
                "is_accessory": {
                    "type": "boolean",
                    "description": "是否为配件 (默认 false)",
                    "default": False
                }
            },
            "required": ["start_date", "end_date"]
        }
    }
