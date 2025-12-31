"""
动态报价工具 - 根据租赁时间、客户类型等计算租金
T_RENTAL_003 - calculate_price tool
"""

from typing import Dict, Any, Optional
from datetime import datetime
from ai_kefu.utils.logging import logger


def calculate_price(
    start_date: str,
    end_date: str,
    device_model: str,
    base_price: float,
    customer_type: str = "new",
    is_peak_season: Optional[bool] = None
) -> Dict[str, Any]:
    """
    根据租赁时间、设备型号、客户类型等计算租金报价。
    
    注意: 详细的定价规则存储在知识库中,建议先使用 knowledge_search 
    查询 "租赁定价规则" 获取最新的价格策略。
    
    Args:
        start_date: 租赁开始日期 (YYYY-MM-DD)
        end_date: 租赁结束日期 (YYYY-MM-DD)
        device_model: 设备型号名称
        base_price: 设备基础日租金
        customer_type: 客户类型 ("new" 新客户 / "old" 老客户)
        is_peak_season: 是否旺季 (可选, None 则自动判断)
        
    Returns:
        Dict with pricing calculation:
        {
            "success": bool,
            "total_price": float,
            "daily_price": float,
            "rental_days": int,
            "discount_info": dict,
            "message": str,
            "error": str (if failed)
        }
    """
    try:
        logger.info(f"Calculating price: {start_date} to {end_date}, model={device_model}, customer={customer_type}")
        
        # 验证日期格式
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as e:
            return {
                "success": False,
                "total_price": 0,
                "error": f"日期格式错误，请使用 YYYY-MM-DD 格式: {str(e)}"
            }
        
        # 验证日期逻辑
        if end_dt <= start_dt:
            return {
                "success": False,
                "total_price": 0,
                "error": "结束日期必须晚于开始日期"
            }
        
        # 计算租赁天数
        rental_days = (end_dt - start_dt).days
        
        # 判断是否旺季 (如果未指定)
        if is_peak_season is None:
            is_peak_season = _is_peak_season(start_dt, end_dt)
        
        # 计算价格
        pricing_result = _calculate_rental_price(
            rental_days=rental_days,
            base_price=base_price,
            customer_type=customer_type,
            is_peak_season=is_peak_season
        )
        
        # 构建返回消息
        discount_info = pricing_result["discount_info"]
        discount_desc = []
        if discount_info.get("customer_discount", 0) > 0:
            discount_desc.append(f"老客户优惠 {discount_info['customer_discount']*100:.0f}%")
        if discount_info.get("duration_discount", 0) > 0:
            discount_desc.append(f"租期优惠 {discount_info['duration_discount']*100:.0f}%")
        if discount_info.get("season_markup", 0) > 0:
            discount_desc.append(f"旺季加价 {discount_info['season_markup']*100:.0f}%")
        
        discount_str = "，".join(discount_desc) if discount_desc else "无优惠"
        
        message = (
            f"{device_model} 租赁 {rental_days} 天\n"
            f"日租金: ¥{pricing_result['daily_price']:.2f}\n"
            f"总价: ¥{pricing_result['total_price']:.2f}\n"
            f"优惠情况: {discount_str}"
        )
        
        logger.info(f"Price calculated: {pricing_result['total_price']:.2f} CNY for {rental_days} days")
        
        return {
            "success": True,
            "total_price": pricing_result["total_price"],
            "daily_price": pricing_result["daily_price"],
            "rental_days": rental_days,
            "device_model": device_model,
            "customer_type": customer_type,
            "is_peak_season": is_peak_season,
            "discount_info": discount_info,
            "message": message
        }
        
    except Exception as e:
        error_msg = f"价格计算失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "success": False,
            "total_price": 0,
            "error": error_msg
        }


def _is_peak_season(start_dt: datetime, end_dt: datetime) -> bool:
    """
    判断租赁时间是否在旺季。
    
    旺季定义:
    - 春节前后 (1月15日 - 2月28日)
    - 五一劳动节 (4月28日 - 5月5日)
    - 国庆节 (9月28日 - 10月7日)
    
    Args:
        start_dt: 开始日期
        end_dt: 结束日期
        
    Returns:
        是否旺季
    """
    # 定义旺季时间段 (月-日)
    peak_periods = [
        ((1, 15), (2, 28)),   # 春节
        ((4, 28), (5, 5)),    # 五一
        ((9, 28), (10, 7)),   # 国庆
    ]
    
    # 检查租赁期间是否与任何旺季重叠
    for (start_month, start_day), (end_month, end_day) in peak_periods:
        # 构建当年的旺季日期范围
        year = start_dt.year
        peak_start = datetime(year, start_month, start_day)
        peak_end = datetime(year, end_month, end_day)
        
        # 检查是否有重叠
        if not (end_dt < peak_start or start_dt > peak_end):
            return True
    
    return False


def _calculate_rental_price(
    rental_days: int,
    base_price: float,
    customer_type: str,
    is_peak_season: bool
) -> Dict[str, Any]:
    """
    根据规则计算租金。
    
    注意: 这里是默认规则,实际规则应该存储在知识库中。
    建议使用 knowledge_search 查询最新规则。
    
    定价规则 (示例):
    1. 老客户折扣: 95折 (0.05 off)
    2. 租期折扣:
       - 7天以上: 95折
       - 15天以上: 9折
       - 30天以上: 85折
    3. 旺季加价: 15% (1.15倍)
    
    Args:
        rental_days: 租赁天数
        base_price: 基础日租金
        customer_type: 客户类型
        is_peak_season: 是否旺季
        
    Returns:
        定价详情
    """
    # 基础总价
    base_total = base_price * rental_days
    
    discount_info = {
        "customer_discount": 0.0,
        "duration_discount": 0.0,
        "season_markup": 0.0
    }
    
    # 1. 客户类型折扣
    customer_discount = 0.0
    if customer_type == "old":
        customer_discount = 0.05  # 老客户95折
        discount_info["customer_discount"] = customer_discount
    
    # 2. 租期折扣
    duration_discount = 0.0
    if rental_days >= 30:
        duration_discount = 0.15  # 30天以上85折
    elif rental_days >= 15:
        duration_discount = 0.10  # 15天以上9折
    elif rental_days >= 7:
        duration_discount = 0.05  # 7天以上95折
    
    discount_info["duration_discount"] = duration_discount
    
    # 3. 旺季加价
    season_markup = 0.0
    if is_peak_season:
        season_markup = 0.15  # 旺季加价15%
        discount_info["season_markup"] = season_markup
    
    # 计算最终价格
    # 折扣按累加方式计算,旺季加价后应用
    total_discount = customer_discount + duration_discount
    discounted_price = base_total * (1 - total_discount)
    
    # 应用旺季加价
    final_price = discounted_price * (1 + season_markup)
    
    # 计算实际日租金
    actual_daily_price = final_price / rental_days
    
    return {
        "total_price": round(final_price, 2),
        "daily_price": round(actual_daily_price, 2),
        "base_total": base_total,
        "discount_info": discount_info
    }


def get_tool_definition() -> Dict[str, Any]:
    """
    获取动态报价工具定义（用于 Qwen Function Calling）
    
    Returns:
        工具定义字典
    """
    return {
        "name": "calculate_price",
        "description": """根据租赁时间、设备型号、客户类型等计算租金报价。

使用场景：
- 确认档期可用后,需要给用户报价时
- 用户询问租金价格时
- 在给出最终报价前使用

工作流程：
1. 先使用 knowledge_search 查询 "租赁定价规则" 了解最新价格策略
2. 使用 check_availability 获取可用设备和基础价格
3. 调用此工具计算最终报价

定价因素：
- 租赁天数: 影响租期折扣
- 客户类型: 老客户有优惠
- 旺季淡季: 旺季会有加价
- 设备型号: 不同设备基础价格不同

注意：
- 需要从 check_availability 的返回结果中获取 base_price
- 详细的定价规则存储在知识库中
- 旺季包括: 春节、五一、国庆
""",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "租赁开始日期 (格式: YYYY-MM-DD)"
                },
                "end_date": {
                    "type": "string",
                    "description": "租赁结束日期 (格式: YYYY-MM-DD)"
                },
                "device_model": {
                    "type": "string",
                    "description": "设备型号名称,从 check_availability 返回结果中获取"
                },
                "base_price": {
                    "type": "number",
                    "description": "设备基础日租金,从 check_availability 返回结果中获取"
                },
                "customer_type": {
                    "type": "string",
                    "enum": ["new", "old"],
                    "description": "客户类型: 'new' 新客户 / 'old' 老客户",
                    "default": "new"
                },
                "is_peak_season": {
                    "type": "boolean",
                    "description": "是否旺季 (可选,不指定则自动判断)"
                }
            },
            "required": ["start_date", "end_date", "device_model", "base_price"]
        }
    }
