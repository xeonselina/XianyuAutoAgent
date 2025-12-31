"""
物流时间计算工具 - 根据目的地计算物流所需天数
发货地: 广东深圳
物流方式: 顺丰标快
T_RENTAL_002 - calculate_logistics tool
"""

from typing import Dict, Any
from ai_kefu.utils.logging import logger


# 物流时间映射表 (从广东深圳发顺丰标快)
LOGISTICS_DAYS_MAP = {
    # 广东省内 - 1天
    "广东": 1,
    "深圳": 1,
    "广州": 1,
    "东莞": 1,
    "佛山": 1,
    "珠海": 1,
    "中山": 1,
    "惠州": 1,
    "江门": 1,
    "肇庆": 1,
    "汕头": 1,
    "湛江": 1,
    "韶关": 1,
    "河源": 1,
    "梅州": 1,
    "清远": 1,
    "阳江": 1,
    "潮州": 1,
    "揭阳": 1,
    "云浮": 1,
    "汕尾": 1,
    
    # 华南、华东主要城市 - 2天
    "福建": 2,
    "福州": 2,
    "厦门": 2,
    "泉州": 2,
    "湖南": 2,
    "长沙": 2,
    "湖北": 2,
    "武汉": 2,
    "江西": 2,
    "南昌": 2,
    "浙江": 2,
    "杭州": 2,
    "宁波": 2,
    "温州": 2,
    "上海": 2,
    "江苏": 2,
    "南京": 2,
    "苏州": 2,
    "无锡": 2,
    "常州": 2,
    "广西": 2,
    "南宁": 2,
    "桂林": 2,
    "海南": 2,
    "海口": 2,
    "三亚": 2,
    
    # 华北、华中、西南主要城市 - 3天
    "北京": 3,
    "天津": 3,
    "河北": 3,
    "石家庄": 3,
    "山东": 3,
    "济南": 3,
    "青岛": 3,
    "河南": 3,
    "郑州": 3,
    "安徽": 3,
    "合肥": 3,
    "四川": 3,
    "成都": 3,
    "重庆": 3,
    "贵州": 3,
    "贵阳": 3,
    "云南": 3,
    "昆明": 3,
    "山西": 3,
    "太原": 3,
    "陕西": 3,
    "西安": 3,
    
    # 东北、西北地区 - 4天
    "辽宁": 4,
    "沈阳": 4,
    "大连": 4,
    "吉林": 4,
    "长春": 4,
    "黑龙江": 4,
    "哈尔滨": 4,
    "甘肃": 4,
    "兰州": 4,
    "青海": 4,
    "西宁": 4,
    "宁夏": 4,
    "银川": 4,
    "内蒙古": 4,
    "呼和浩特": 4,
    
    # 偏远地区 - 5-7天
    "新疆": 6,
    "乌鲁木齐": 6,
    "西藏": 7,
    "拉萨": 7,
}

# 默认物流天数 (未匹配到的地区)
DEFAULT_LOGISTICS_DAYS = 3


def calculate_logistics(destination: str) -> Dict[str, Any]:
    """
    根据目的地地址计算物流所需天数。
    发货地: 广东深圳
    物流方式: 顺丰标快
    
    Args:
        destination: 目的地地址 (省份/城市名称)
        
    Returns:
        Dict with logistics calculation:
        {
            "success": bool,
            "logistics_days": int,
            "destination": str,
            "message": str,
            "error": str (if failed)
        }
    """
    try:
        logger.info(f"Calculating logistics for destination: {destination}")
        
        if not destination or not destination.strip():
            return {
                "success": False,
                "logistics_days": DEFAULT_LOGISTICS_DAYS,
                "destination": destination,
                "error": "目的地地址不能为空"
            }
        
        destination = destination.strip()
        
        # 尝试匹配城市/省份名
        logistics_days = DEFAULT_LOGISTICS_DAYS
        matched_location = None
        
        # 优先匹配城市,再匹配省份(从长到短匹配,避免误匹配)
        sorted_locations = sorted(LOGISTICS_DAYS_MAP.keys(), key=len, reverse=True)
        
        for location in sorted_locations:
            if location in destination:
                logistics_days = LOGISTICS_DAYS_MAP[location]
                matched_location = location
                break
        
        # 构建返回消息
        if matched_location:
            message = f"从深圳寄往 {matched_location} 预计 {logistics_days} 天送达（顺丰标快）"
        else:
            message = f"未找到精确匹配地区，按默认 {logistics_days} 天计算（顺丰标快）"
        
        logger.info(f"Logistics calculated: {destination} -> {logistics_days} days (matched: {matched_location})")
        
        return {
            "success": True,
            "logistics_days": logistics_days,
            "destination": destination,
            "matched_location": matched_location,
            "shipping_method": "顺丰标快",
            "origin": "广东深圳",
            "message": message
        }
        
    except Exception as e:
        error_msg = f"物流时间计算失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "success": False,
            "logistics_days": DEFAULT_LOGISTICS_DAYS,
            "destination": destination,
            "error": error_msg
        }


def get_tool_definition() -> Dict[str, Any]:
    """
    获取物流时间计算工具定义（用于 Qwen Function Calling）
    
    Returns:
        工具定义字典
    """
    return {
        "name": "calculate_logistics",
        "description": """根据目的地地址计算物流所需天数。

发货地: 广东深圳
物流方式: 顺丰标快

使用场景：
- 用户提供了收货地址时
- 需要计算物流时间以便查询档期时
- 在调用 check_availability 之前必须先计算物流时间

物流时间规则（从深圳发货）：
- 广东省内：1天
- 华南、华东主要城市：2天
- 华北、华中、西南：3天
- 东北、西北：4天
- 新疆：6天
- 西藏：7天

注意：
- 会根据地址中的省份/城市名自动匹配物流时间
- 返回的 logistics_days 用于 check_availability 工具
- 物流时间包含发货和收货的时间
""",
        "parameters": {
            "type": "object",
            "properties": {
                "destination": {
                    "type": "string",
                    "description": "目的地地址，至少包含省份或城市名称。例如: '北京市朝阳区'、'上海'、'广东广州'、'浙江杭州'"
                }
            },
            "required": ["destination"]
        }
    }
