"""
租赁信息收集工具 - 管理租赁咨询的信息收集状态
T_RENTAL_004 - collect_rental_info tool
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
from ai_kefu.utils.logging import logger


# 租赁信息收集状态
class RentalInfoStatus:
    INCOMPLETE = "incomplete"  # 信息不完整
    COMPLETE = "complete"      # 信息完整
    READY_FOR_QUOTE = "ready_for_quote"  # 可以报价


def collect_rental_info(
    receive_date: Optional[str] = None,
    return_date: Optional[str] = None,
    destination: Optional[str] = None,
    device_preference: Optional[str] = None,
    customer_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    收集和验证租赁所需的关键信息。
    
    关键信息:
    1. receive_date: 收货日期 (用户希望什么时候收到设备)
    2. return_date: 归还日期 (用户什么时候寄回设备)
    3. destination: 收货地址 (至少需要省份/城市)
    4. device_preference: 设备偏好 (可选)
    5. customer_type: 客户类型 (可选, 新客户/老客户)
    
    Args:
        receive_date: 收货日期 (YYYY-MM-DD)
        return_date: 归还日期 (YYYY-MM-DD)
        destination: 收货地址
        device_preference: 设备型号偏好 (可选)
        customer_type: 客户类型 "new"/"old" (可选)
        
    Returns:
        Dict with collection status:
        {
            "success": bool,
            "status": str,  # incomplete/complete/ready_for_quote
            "collected_info": dict,
            "missing_fields": list,
            "message": str,
            "next_steps": list,
            "error": str (if failed)
        }
    """
    try:
        logger.info("Collecting rental information")
        
        collected_info = {}
        missing_fields = []
        validation_errors = []
        
        # 1. 验证收货日期
        if receive_date:
            try:
                receive_dt = datetime.strptime(receive_date, "%Y-%m-%d")
                # 检查日期是否在未来
                if receive_dt.date() < datetime.now().date():
                    validation_errors.append("收货日期不能早于今天")
                else:
                    collected_info["receive_date"] = receive_date
                    # Store datetime internally for calculation, don't include in return
            except ValueError:
                validation_errors.append("收货日期格式错误,请使用 YYYY-MM-DD 格式")
        else:
            missing_fields.append("receive_date")
        
        # 2. 验证归还日期
        if return_date:
            try:
                return_dt = datetime.strptime(return_date, "%Y-%m-%d")
                collected_info["return_date"] = return_date
                
                # 如果收货日期也有,验证逻辑关系
                if receive_date and "receive_date" in collected_info:
                    receive_dt = datetime.strptime(receive_date, "%Y-%m-%d")
                    if return_dt <= receive_dt:
                        validation_errors.append("归还日期必须晚于收货日期")
                    else:
                        # 计算预计使用天数
                        usage_days = (return_dt - receive_dt).days - 2  # 减去物流时间
                        collected_info["estimated_usage_days"] = max(1, usage_days)
            except ValueError:
                validation_errors.append("归还日期格式错误,请使用 YYYY-MM-DD 格式")
        else:
            missing_fields.append("return_date")
        
        # 3. 验证收货地址
        if destination and destination.strip():
            collected_info["destination"] = destination.strip()
        else:
            missing_fields.append("destination")
        
        # 4. 收集设备偏好 (可选)
        if device_preference:
            collected_info["device_preference"] = device_preference
        
        # 5. 收集客户类型 (可选,默认新客户)
        collected_info["customer_type"] = customer_type if customer_type in ["new", "old"] else "new"
        
        # 判断状态
        if validation_errors:
            status = RentalInfoStatus.INCOMPLETE
            message = "信息验证失败: " + "; ".join(validation_errors)
            next_steps = ["请提供正确的信息"]
        elif missing_fields:
            status = RentalInfoStatus.INCOMPLETE
            missing_str = ", ".join([
                "收货日期" if f == "receive_date" else
                "归还日期" if f == "return_date" else
                "收货地址" if f == "destination" else f
                for f in missing_fields
            ])
            message = f"还需要以下信息: {missing_str}"
            next_steps = [f"询问用户{missing_str}"]
        else:
            status = RentalInfoStatus.READY_FOR_QUOTE
            message = "信息收集完成,可以开始查询档期和报价"
            next_steps = [
                "1. 使用 calculate_logistics 计算物流时间",
                "2. 使用 check_availability 查询档期",
                "3. 使用 calculate_price 计算报价"
            ]
        
        logger.info(f"Rental info collection status: {status}, missing: {missing_fields}")
        
        return {
            "success": True,
            "status": status,
            "collected_info": collected_info,
            "missing_fields": missing_fields,
            "validation_errors": validation_errors,
            "message": message,
            "next_steps": next_steps
        }
        
    except Exception as e:
        error_msg = f"信息收集失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "success": False,
            "status": RentalInfoStatus.INCOMPLETE,
            "collected_info": {},
            "missing_fields": [],
            "error": error_msg
        }


def get_tool_definition() -> Dict[str, Any]:
    """
    获取租赁信息收集工具定义（用于 Qwen Function Calling）
    
    Returns:
        工具定义字典
    """
    return {
        "name": "collect_rental_info",
        "description": """收集和验证手机租赁所需的关键信息,管理信息收集状态。

使用场景：
- 用户开始咨询租赁时,收集必要信息
- 每次收到用户提供的新信息时,更新收集状态
- 在查询档期和报价前,确认信息完整性

必需信息:
1. receive_date: 收货日期 (用户希望什么时候收到设备)
2. return_date: 归还日期 (用户什么时候寄回设备)
3. destination: 收货地址 (至少需要省份/城市)

可选信息:
4. device_preference: 设备型号偏好
5. customer_type: 客户类型 (new/old)

工作流程：
1. 与用户对话时,逐步收集上述信息
2. 每次获得新信息时调用此工具验证
3. 当 status 为 "ready_for_quote" 时,按 next_steps 执行后续步骤

注意：
- 收货日期不能早于今天
- 归还日期必须晚于收货日期
- 实际租赁时间 = 收货日期+1天 到 归还日期-1天 (扣除物流时间)
""",
        "parameters": {
            "type": "object",
            "properties": {
                "receive_date": {
                    "type": "string",
                    "description": "收货日期,格式: YYYY-MM-DD。用户希望什么时候收到设备"
                },
                "return_date": {
                    "type": "string",
                    "description": "归还日期,格式: YYYY-MM-DD。用户什么时候寄回设备"
                },
                "destination": {
                    "type": "string",
                    "description": "收货地址,至少包含省份或城市名称"
                },
                "device_preference": {
                    "type": "string",
                    "description": "设备型号偏好 (可选),例如: 'iPhone 15 Pro Max'"
                },
                "customer_type": {
                    "type": "string",
                    "enum": ["new", "old"],
                    "description": "客户类型 (可选): 'new' 新客户 / 'old' 老客户"
                }
            },
            "required": []
        }
    }
