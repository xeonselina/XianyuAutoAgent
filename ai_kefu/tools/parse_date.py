"""
日期解析工具 - 智能解析用户输入的日期表达
T_RENTAL_006 - parse_date tool
"""

from typing import Dict, Any
from datetime import datetime, timedelta
import re
from ai_kefu.utils.logging import logger


def parse_date(date_input: str) -> Dict[str, Any]:
    """
    智能解析用户输入的日期表达，转换为标准 YYYY-MM-DD 格式。
    
    支持的格式:
    - "14号" -> 当前月份14日（如果已过则下月）
    - "1月14号" -> 当前年份1月14日（如果已过则明年）
    - "明天" -> 明天的日期
    - "后天" -> 后天的日期
    - "2026-01-14" -> 直接使用
    - "2026年1月14日" -> 转换为标准格式
    
    Args:
        date_input: 用户输入的日期字符串
        
    Returns:
        Dict with parsed date:
        {
            "success": bool,
            "date": str (YYYY-MM-DD),
            "original_input": str,
            "interpretation": str,
            "error": str (if failed)
        }
    """
    try:
        logger.info(f"Parsing date input: {date_input}")
        
        today = datetime.now()
        date_input = date_input.strip()
        
        # 1. 处理相对日期
        if date_input in ["今天", "今日"]:
            result_date = today
            interpretation = f"今天 ({result_date.strftime('%Y-%m-%d')})"
        
        elif date_input in ["明天", "明日"]:
            result_date = today + timedelta(days=1)
            interpretation = f"明天 ({result_date.strftime('%Y-%m-%d')})"
        
        elif date_input in ["后天"]:
            result_date = today + timedelta(days=2)
            interpretation = f"后天 ({result_date.strftime('%Y-%m-%d')})"
        
        # 2. 处理 "X号" 格式（只有日期）
        elif re.match(r'^(\d{1,2})号?$', date_input):
            day = int(re.match(r'^(\d{1,2})号?$', date_input).group(1))
            
            # 尝试当前月份
            try:
                result_date = datetime(today.year, today.month, day)
                
                # 如果日期已经过去，使用下个月
                if result_date.date() < today.date():
                    if today.month == 12:
                        result_date = datetime(today.year + 1, 1, day)
                    else:
                        result_date = datetime(today.year, today.month + 1, day)
                    interpretation = f"下月{day}号 ({result_date.strftime('%Y-%m-%d')})"
                else:
                    interpretation = f"本月{day}号 ({result_date.strftime('%Y-%m-%d')})"
            
            except ValueError:
                return {
                    "success": False,
                    "original_input": date_input,
                    "error": f"日期无效: {today.month}月没有{day}号"
                }
        
        # 3. 处理 "X月X号" 格式
        elif re.match(r'^(\d{1,2})月(\d{1,2})号?$', date_input):
            match = re.match(r'^(\d{1,2})月(\d{1,2})号?$', date_input)
            month = int(match.group(1))
            day = int(match.group(2))
            
            # 尝试当前年份
            try:
                result_date = datetime(today.year, month, day)
                
                # 如果日期已经过去，使用明年
                if result_date.date() < today.date():
                    result_date = datetime(today.year + 1, month, day)
                    interpretation = f"明年{month}月{day}号 ({result_date.strftime('%Y-%m-%d')})"
                else:
                    interpretation = f"今年{month}月{day}号 ({result_date.strftime('%Y-%m-%d')})"
            
            except ValueError:
                return {
                    "success": False,
                    "original_input": date_input,
                    "error": f"日期无效: {month}月没有{day}号"
                }
        
        # 4. 处理标准格式 "YYYY-MM-DD"
        elif re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', date_input):
            result_date = datetime.strptime(date_input, "%Y-%m-%d")
            interpretation = f"标准格式 ({result_date.strftime('%Y-%m-%d')})"
        
        # 5. 处理中文格式 "YYYY年M月D日"
        elif re.match(r'^\d{4}年\d{1,2}月\d{1,2}[日号]?$', date_input):
            match = re.match(r'^(\d{4})年(\d{1,2})月(\d{1,2})[日号]?$', date_input)
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
            result_date = datetime(year, month, day)
            interpretation = f"中文格式 ({result_date.strftime('%Y-%m-%d')})"
        
        # 6. 无法识别的格式
        else:
            return {
                "success": False,
                "original_input": date_input,
                "error": f"无法识别的日期格式: {date_input}。支持的格式：14号、1月14号、2026-01-14、2026年1月14日、明天、后天"
            }
        
        # 返回成功结果
        logger.info(f"Date parsed successfully: {date_input} -> {result_date.strftime('%Y-%m-%d')}")
        
        return {
            "success": True,
            "date": result_date.strftime("%Y-%m-%d"),
            "original_input": date_input,
            "interpretation": interpretation
        }
        
    except Exception as e:
        error_msg = f"日期解析失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "success": False,
            "original_input": date_input,
            "error": error_msg
        }


def get_tool_definition() -> Dict[str, Any]:
    """
    获取日期解析工具定义（用于 Qwen Function Calling）
    
    Returns:
        工具定义字典
    """
    return {
        "name": "parse_date",
        "description": """智能解析用户输入的日期表达，转换为标准 YYYY-MM-DD 格式。

使用场景：
- 用户说"14号收"，需要知道具体日期
- 用户说"1月20号还"，需要转换为标准格式
- 用户说"明天收货"，需要计算具体日期

支持的格式：
1. 相对日期：今天、明天、后天
2. 只有日期：14号（默认当月，如果已过则下月）
3. 月份+日期：1月14号（默认今年，如果已过则明年）
4. 标准格式：2026-01-14
5. 中文格式：2026年1月14日

重要：
- 在调用 collect_rental_info 之前，先用此工具解析用户输入的日期
- 向用户确认解析结果，避免误解

示例工作流：
1. 用户："14号收，16号还"
2. 调用 parse_date("14号") -> 2026-01-14
3. 调用 parse_date("16号") -> 2026-01-16
4. 向用户确认："您是说1月14日收货，1月16日归还，对吗？"
5. 用户确认后，调用 collect_rental_info(receive_date="2026-01-14", return_date="2026-01-16")
""",
        "parameters": {
            "type": "object",
            "properties": {
                "date_input": {
                    "type": "string",
                    "description": "用户输入的日期字符串，例如：'14号'、'1月14号'、'2026-01-14'、'明天'"
                }
            },
            "required": ["date_input"]
        }
    }
