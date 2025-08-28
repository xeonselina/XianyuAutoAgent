"""
统一时区处理工具

核心原则：
1. 数据库存储UTC时间
2. API接口使用ISO 8601格式传输
3. 所有日期比较和计算使用中国时区(Asia/Shanghai)
4. 前端显示使用用户本地时区
"""

from datetime import datetime, date, time, timezone
from typing import Union, Optional
import pytz
from flask import current_app

# 系统统一时区 - 中国时区
SYSTEM_TIMEZONE = pytz.timezone('Asia/Shanghai')
UTC_TIMEZONE = pytz.UTC


def get_current_datetime() -> datetime:
    """获取当前日期时间(中国时区)"""
    return datetime.now(SYSTEM_TIMEZONE)


def get_current_date() -> date:
    """获取当前日期(中国时区)"""
    return get_current_datetime().date()


def to_system_timezone(dt: Union[datetime, str]) -> datetime:
    """将任意时间转换为中国时区"""
    if isinstance(dt, str):
        # 如果是字符串，先解析
        dt = parse_datetime(dt)
    
    if dt.tzinfo is None:
        # 如果没有时区信息，假设是UTC时间
        dt = UTC_TIMEZONE.localize(dt)
    
    return dt.astimezone(SYSTEM_TIMEZONE)


def to_utc_timezone(dt: Union[datetime, str]) -> datetime:
    """将任意时间转换为UTC时区"""
    if isinstance(dt, str):
        dt = parse_datetime(dt)
    
    if dt.tzinfo is None:
        # 如果没有时区信息，假设是系统时区
        dt = SYSTEM_TIMEZONE.localize(dt)
    
    return dt.astimezone(UTC_TIMEZONE)


def parse_datetime(dt_str: str) -> datetime:
    """解析日期时间字符串"""
    # 常见格式
    formats = [
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M:%S.%f',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%S.%f%z'
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    
    raise ValueError(f"无法解析日期时间字符串: {dt_str}")


def parse_date(date_str: str) -> date:
    """解析日期字符串"""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        raise ValueError(f"无法解析日期字符串: {date_str}")


def format_system_date(dt: Union[datetime, date], fmt: str = '%Y-%m-%d') -> str:
    """格式化日期(中国时区)"""
    if isinstance(dt, datetime):
        dt = to_system_timezone(dt)
        return dt.strftime(fmt)
    else:
        return dt.strftime(fmt)


def format_system_datetime(dt: Union[datetime, str], fmt: str = '%Y-%m-%d %H:%M:%S') -> str:
    """格式化日期时间(中国时区)"""
    if isinstance(dt, str):
        dt = parse_datetime(dt)
    
    dt = to_system_timezone(dt)
    return dt.strftime(fmt)


def to_api_format(dt: Union[datetime, str]) -> str:
    """转换为API格式(ISO 8601)"""
    if isinstance(dt, str):
        dt = parse_datetime(dt)
    
    # 转换为UTC后输出ISO格式
    utc_dt = to_utc_timezone(dt)
    return utc_dt.isoformat()


def from_api_format(iso_str: str) -> datetime:
    """从API格式解析时间"""
    return parse_datetime(iso_str)


def is_same_date_system(dt1: Union[datetime, date, str], dt2: Union[datetime, date, str]) -> bool:
    """检查两个日期是否在同一天(中国时区)"""
    date1 = get_system_date(dt1)
    date2 = get_system_date(dt2)
    return date1 == date2


def get_system_date(dt: Union[datetime, date, str]) -> date:
    """获取系统时区的日期部分"""
    if isinstance(dt, str):
        dt = parse_datetime(dt)
    
    if isinstance(dt, datetime):
        dt = to_system_timezone(dt)
        return dt.date()
    
    return dt


def create_system_datetime(year: int, month: int, day: int, 
                         hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    """创建中国时区的日期时间对象"""
    dt = datetime(year, month, day, hour, minute, second)
    return SYSTEM_TIMEZONE.localize(dt)


def combine_date_time_system(date_obj: date, time_obj: time = None) -> datetime:
    """将日期和时间合并为中国时区的datetime对象"""
    if time_obj is None:
        time_obj = time.min
    
    dt = datetime.combine(date_obj, time_obj)
    return SYSTEM_TIMEZONE.localize(dt)


def get_date_range_start_end(date_obj: date) -> tuple[datetime, datetime]:
    """获取某一天的开始和结束时间(中国时区)"""
    start = combine_date_time_system(date_obj, time.min)
    end = combine_date_time_system(date_obj, time.max)
    return start, end


def log_timezone_debug(dt: Union[datetime, str], context: str = ""):
    """调试时区信息"""
    if current_app:
        if isinstance(dt, str):
            current_app.logger.debug(f"[时区调试] {context}: {dt} (字符串)")
        else:
            system_dt = to_system_timezone(dt)
            utc_dt = to_utc_timezone(dt)
            current_app.logger.debug(
                f"[时区调试] {context}: "
                f"原始={dt} -> 中国时区={system_dt} -> UTC={utc_dt}"
            )


class DateTimeUtils:
    """日期时间工具类"""
    
    @staticmethod
    def get_today_range() -> tuple[datetime, datetime]:
        """获取今天的时间范围(中国时区)"""
        today = get_current_date()
        return get_date_range_start_end(today)
    
    @staticmethod
    def get_date_range(start_date: Union[date, str], end_date: Union[date, str]) -> tuple[datetime, datetime]:
        """获取日期范围的时间戳"""
        if isinstance(start_date, str):
            start_date = parse_date(start_date)
        if isinstance(end_date, str):
            end_date = parse_date(end_date)
        
        start_dt = combine_date_time_system(start_date, time.min)
        end_dt = combine_date_time_system(end_date, time.max)
        
        return start_dt, end_dt
    
    @staticmethod
    def is_date_in_range(check_date: Union[date, datetime, str], 
                        start_date: Union[date, str], 
                        end_date: Union[date, str]) -> bool:
        """检查日期是否在范围内"""
        if isinstance(check_date, str):
            check_date = parse_date(check_date)
        elif isinstance(check_date, datetime):
            check_date = get_system_date(check_date)
        
        if isinstance(start_date, str):
            start_date = parse_date(start_date)
        if isinstance(end_date, str):
            end_date = parse_date(end_date)
        
        return start_date <= check_date <= end_date