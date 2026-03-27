"""
日期解析工具 - 智能解析用户输入的日期表达
T_RENTAL_006 - parse_date tool
"""

from typing import Dict, Any
from datetime import datetime, timedelta
import re
from ai_kefu.utils.logging import logger


def _resolve_date(today: datetime, month: int, day: int, only_day: bool = False) -> tuple:
    """
    根据当前日期解析月+日，返回 (datetime, interpretation_str)。

    核心规则（固化）:
      用户在租赁场景中提到的日期通常是**未来的日期**。
      如果解析出来的日期 < 今天，说明用户大概率在说下个月（而非过去）。

    参数:
      only_day: 用户是否只提到了日号（没有月份）。
                True  -> "20号" 这类，日号 < 今天日号 → 一定是下个月
                False -> "3月20号" 这类，带了月份，按月份判断
    """
    try:
        result_date = datetime(today.year, month, day)
        if result_date.date() < today.date():
            if only_day or month == today.month:
                # 情况 1: 用户只说了日号 (如 "20号")，或者说的就是当月 (如 "3月20号")
                # 日期已过 → 推断为下个月
                if today.month == 12:
                    result_date = datetime(today.year + 1, 1, day)
                else:
                    result_date = datetime(today.year, today.month + 1, day)
                interpretation = f"下月{day}号 ({result_date.strftime('%Y-%m-%d')})"
                logger.info(
                    f"日期推断: {month}月{day}号已过今天({today.strftime('%m-%d')})，"
                    f"推断为下月 → {result_date.strftime('%Y-%m-%d')}"
                )
            else:
                # 情况 2: 用户明确说了非当月月份 (如今天3月说 "1月15号")
                # 该月份整体已过 → 推到明年
                result_date = datetime(today.year + 1, month, day)
                interpretation = f"明年{month}月{day}号 ({result_date.strftime('%Y-%m-%d')})"
                logger.info(
                    f"日期推断: {month}月{day}号已过今天({today.strftime('%m-%d')})，"
                    f"明确指定了{month}月 → 推到明年 {result_date.strftime('%Y-%m-%d')}"
                )
        else:
            if month == today.month:
                interpretation = f"本月{day}号 ({result_date.strftime('%Y-%m-%d')})"
            else:
                interpretation = f"今年{month}月{day}号 ({result_date.strftime('%Y-%m-%d')})"
        return result_date, interpretation
    except ValueError:
        return None, f"日期无效: {month}月没有{day}号"


def parse_date(date_input: str) -> Dict[str, Any]:
    """
    智能解析用户输入的日期表达，转换为标准 YYYY-MM-DD 格式。
    
    支持的格式:
    - "14号" -> 当前月份14日（如果已过则下月）
    - "1月14号" -> 当前年份1月14日（如果已过则明年）
    - "4.15" / "4.15号" -> 4月15日（点号分隔）
    - "4.30-5.4" -> 日期范围（返回两个日期）
    - "明天" -> 明天的日期
    - "后天" -> 后天的日期
    - "大后天" -> 大后天的日期
    - "这周六" / "下周一" -> 相对星期
    - "2026-01-14" -> 直接使用
    - "2026年1月14日" -> 转换为标准格式
    - "4月30号-5月5号" -> 日期范围
    
    Args:
        date_input: 用户输入的日期字符串
        
    Returns:
        Dict with parsed date(s)
    """
    try:
        logger.info(f"Parsing date input: {date_input}")
        
        today = datetime.now()
        date_input = date_input.strip()
        
        # ===== 0a. 先匹配标准格式 YYYY-MM-DD（避免被范围匹配的 - 截断）=====
        if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', date_input):
            result_date = datetime.strptime(date_input, "%Y-%m-%d")
            interpretation = f"标准格式 ({result_date.strftime('%Y-%m-%d')})"
            
            logger.info(f"Date parsed successfully: {date_input} -> {result_date.strftime('%Y-%m-%d')}")
            return {
                "success": True,
                "date": result_date.strftime("%Y-%m-%d"),
                "original_input": date_input,
                "interpretation": interpretation
            }
        
        # ===== 0b. 中文格式 YYYY年M月D日 =====
        if re.match(r'^\d{4}年\d{1,2}月\d{1,2}[日号]?$', date_input):
            match = re.match(r'^(\d{4})年(\d{1,2})月(\d{1,2})[日号]?$', date_input)
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
            result_date = datetime(year, month, day)
            interpretation = f"中文格式 ({result_date.strftime('%Y-%m-%d')})"
            
            logger.info(f"Date parsed successfully: {date_input} -> {result_date.strftime('%Y-%m-%d')}")
            return {
                "success": True,
                "date": result_date.strftime("%Y-%m-%d"),
                "original_input": date_input,
                "interpretation": interpretation
            }
        
        # ===== 0c. 斜杠格式 YYYY/M/D =====
        if re.match(r'^\d{4}/\d{1,2}/\d{1,2}$', date_input):
            match = re.match(r'^(\d{4})/(\d{1,2})/(\d{1,2})$', date_input)
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
            result_date = datetime(year, month, day)
            interpretation = f"斜杠格式 ({result_date.strftime('%Y-%m-%d')})"
            
            logger.info(f"Date parsed successfully: {date_input} -> {result_date.strftime('%Y-%m-%d')}")
            return {
                "success": True,
                "date": result_date.strftime("%Y-%m-%d"),
                "original_input": date_input,
                "interpretation": interpretation
            }
        
        # ===== 0d. 处理日期范围（含 "-" 或 "到" 或 "~"） =====
        range_match = re.match(
            r'^(.+?)\s*[-~到至]\s*(.+)$', date_input
        )
        if range_match:
            start_str = range_match.group(1).strip()
            end_str = range_match.group(2).strip()
            
            start_result = parse_date(start_str)
            end_result = parse_date(end_str)
            
            if start_result.get("success") and end_result.get("success"):
                return {
                    "success": True,
                    "date": start_result["date"],
                    "end_date": end_result["date"],
                    "original_input": date_input,
                    "interpretation": f"{start_result['interpretation']} 到 {end_result['interpretation']}",
                    "is_range": True
                }
            else:
                errors = []
                if not start_result.get("success"):
                    errors.append(f"起始日期: {start_result.get('error', '解析失败')}")
                if not end_result.get("success"):
                    errors.append(f"结束日期: {end_result.get('error', '解析失败')}")
                return {
                    "success": False,
                    "original_input": date_input,
                    "error": "; ".join(errors)
                }
        
        # ===== 1. 相对日期 =====
        if date_input in ["今天", "今日"]:
            result_date = today
            interpretation = f"今天 ({result_date.strftime('%Y-%m-%d')})"
        
        elif date_input in ["明天", "明日"]:
            result_date = today + timedelta(days=1)
            interpretation = f"明天 ({result_date.strftime('%Y-%m-%d')})"
        
        elif date_input in ["后天"]:
            result_date = today + timedelta(days=2)
            interpretation = f"后天 ({result_date.strftime('%Y-%m-%d')})"
        
        elif date_input in ["大后天"]:
            result_date = today + timedelta(days=3)
            interpretation = f"大后天 ({result_date.strftime('%Y-%m-%d')})"
        
        # ===== 2. "这周X" / "下周X" / "周X" =====
        elif re.match(r'^(这|本|下)?(周|星期)([一二三四五六日天])$', date_input):
            match = re.match(r'^(这|本|下)?(周|星期)([一二三四五六日天])$', date_input)
            prefix = match.group(1) or "这"
            day_char = match.group(3)
            
            weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
            target_weekday = weekday_map[day_char]
            current_weekday = today.weekday()
            
            if prefix in ["这", "本"]:
                days_ahead = (target_weekday - current_weekday) % 7
                if days_ahead == 0 and current_weekday == target_weekday:
                    days_ahead = 0  # 今天就是
                result_date = today + timedelta(days=days_ahead)
                interpretation = f"这周{day_char} ({result_date.strftime('%Y-%m-%d')})"
            else:  # 下
                days_ahead = (target_weekday - current_weekday) % 7
                if days_ahead == 0:
                    days_ahead = 7
                days_ahead += 7  # 下周
                result_date = today + timedelta(days=days_ahead)
                interpretation = f"下周{day_char} ({result_date.strftime('%Y-%m-%d')})"
        
        # ===== 3. "这周末" =====
        elif date_input in ["这周末", "本周末", "周末"]:
            current_weekday = today.weekday()
            days_to_saturday = (5 - current_weekday) % 7
            if days_to_saturday == 0 and current_weekday > 5:
                days_to_saturday = 7
            result_date = today + timedelta(days=days_to_saturday)
            interpretation = f"这周六 ({result_date.strftime('%Y-%m-%d')})"
        
        # ===== 4. 点号分隔 "X.X" 格式（如 4.15、4.30） =====
        elif re.match(r'^(\d{1,2})\.(\d{1,2})号?日?$', date_input):
            match = re.match(r'^(\d{1,2})\.(\d{1,2})号?日?$', date_input)
            month = int(match.group(1))
            day = int(match.group(2))
            
            result_date, interpretation = _resolve_date(today, month, day)
            if result_date is None:
                return {
                    "success": False,
                    "original_input": date_input,
                    "error": interpretation  # error message
                }
        
        # ===== 5. "X号" 格式（只有日期，没有月份） =====
        # 规则: 用户只说了日号，如果日号 < 今天，推断为下个月
        elif re.match(r'^(\d{1,2})号?$', date_input):
            day = int(re.match(r'^(\d{1,2})号?$', date_input).group(1))
            
            result_date, interpretation = _resolve_date(today, today.month, day, only_day=True)
            if result_date is None:
                return {
                    "success": False,
                    "original_input": date_input,
                    "error": interpretation
                }
        
        # ===== 6. "X月X号" 格式 =====
        elif re.match(r'^(\d{1,2})月(\d{1,2})[号日]?$', date_input):
            match = re.match(r'^(\d{1,2})月(\d{1,2})[号日]?$', date_input)
            month = int(match.group(1))
            day = int(match.group(2))
            
            result_date, interpretation = _resolve_date(today, month, day)
            if result_date is None:
                return {
                    "success": False,
                    "original_input": date_input,
                    "error": interpretation
                }
        
        # ===== 7. 斜杠格式 "M/D" =====
        elif re.match(r'^(\d{1,2})/(\d{1,2})$', date_input):
            match = re.match(r'^(\d{1,2})/(\d{1,2})$', date_input)
            month = int(match.group(1))
            day = int(match.group(2))
            
            result_date, interpretation = _resolve_date(today, month, day)
            if result_date is None:
                return {
                    "success": False,
                    "original_input": date_input,
                    "error": interpretation
                }
        
        # ===== 10. "X号收" / "X号收到" / "X号寄回" 等带动作后缀（只有日号） =====
        # 规则: 用户只说了日号+动作，如果日号 < 今天，推断为下个月
        elif re.match(r'^(\d{1,2})[号日]?\s*(收到?|寄回?|到|还|归还|发)$', date_input):
            match = re.match(r'^(\d{1,2})[号日]?\s*(收到?|寄回?|到|还|归还|发)$', date_input)
            day = int(match.group(1))
            action = match.group(2)
            
            result_date, interpretation = _resolve_date(today, today.month, day, only_day=True)
            if result_date is None:
                return {
                    "success": False,
                    "original_input": date_input,
                    "error": interpretation
                }
            interpretation += f" ({action})"
        
        # ===== 11. "X月X号收" 等带动作后缀 =====
        elif re.match(r'^(\d{1,2})\.?月?(\d{1,2})[号日]?\s*(收到?|寄回?|到|还|归还|发)$', date_input):
            match = re.match(r'^(\d{1,2})\.?月?(\d{1,2})[号日]?\s*(收到?|寄回?|到|还|归还|发)$', date_input)
            month = int(match.group(1))
            day = int(match.group(2))
            action = match.group(3)
            
            result_date, interpretation = _resolve_date(today, month, day)
            if result_date is None:
                return {
                    "success": False,
                    "original_input": date_input,
                    "error": interpretation
                }
            interpretation += f" ({action})"
        
        # ===== 10. 无法识别的格式 =====
        else:
            return {
                "success": False,
                "original_input": date_input,
                "error": f"无法识别的日期格式: {date_input}。支持: 14号、4.15、1月14号、4.30-5.4、明天、后天、这周六、下周一"
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

支持的格式：
1. 相对日期：今天、明天、后天、大后天
2. 只有日期：14号（默认当月，已过则下月）
3. 月份+日期：1月14号（默认今年，已过则明年）
4. 点号分隔：4.15、4.30（即4月15日、4月30日）
5. 日期范围：4.30-5.4、4月30号-5月5号（返回 date + end_date）
6. 标准格式：2026-01-14
7. 中文格式：2026年1月14日
8. 相对星期：这周六、下周一
9. 带动作后缀：15号收、4.20寄回

日期推断规则（固化）：
- 用户说的日期通常指未来。如果只说了日号（如"20号"）且日号比今天小，自动推断为下个月。
- 如果说了月+日且是当月（如当月说"3月15号"但15号已过），也推到下个月。
- 如果说了非当月月份且已过（如3月说"1月15号"），推到明年。

用户说日期时先调用此工具解析。如果用户一次说了两个日期（如"14号收16号还"），分别调用两次。
日期范围格式（含 - ~ 到 至）会自动拆分，返回 date 和 end_date 两个字段。
""",
        "parameters": {
            "type": "object",
            "properties": {
                "date_input": {
                    "type": "string",
                    "description": "用户输入的日期字符串，例如：'14号'、'4.15'、'4.30-5.4'、'下周六'、'明天'"
                }
            },
            "required": ["date_input"]
        }
    }
