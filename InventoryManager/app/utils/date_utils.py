"""
日期工具模块 - 提供日期相关的公共函数
"""

from datetime import datetime, date, time
from typing import Tuple, Optional, Union
from flask import jsonify


def parse_date_strings(start_date_str: str, end_date_str: str) -> Tuple[date, date]:
    """
    解析日期字符串为date对象
    
    Args:
        start_date_str: 开始日期字符串 (YYYY-MM-DD)
        end_date_str: 结束日期字符串 (YYYY-MM-DD)
        
    Returns:
        Tuple[date, date]: (开始日期, 结束日期)
        
    Raises:
        ValueError: 日期格式错误
    """
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        return start_date, end_date
    except ValueError:
        raise ValueError('日期格式错误，请使用YYYY-MM-DD格式')


def validate_date_range(start_date: date, end_date: date, allow_same_date: bool = False) -> Optional[str]:
    """
    验证日期范围
    
    Args:
        start_date: 开始日期
        end_date: 结束日期
        allow_same_date: 是否允许开始和结束日期相同
        
    Returns:
        Optional[str]: 错误信息，如果验证通过则返回None
    """
    if not allow_same_date and start_date > end_date:
        return '开始日期必须早于结束日期'
    
    return None


def convert_dates_to_datetime(start_date: date, end_date: date, 
                            ship_out_hour: str = "19:00:00", 
                            ship_in_hour: str = "12:00:00") -> Tuple[datetime, datetime]:
    """
    将日期转换为寄出和收回的datetime对象
    
    Args:
        start_date: 开始日期
        end_date: 结束日期
        ship_out_hour: 寄出时间 (HH:MM:SS)
        ship_in_hour: 收回时间 (HH:MM:SS)
        
    Returns:
        Tuple[datetime, datetime]: (寄出时间, 收回时间)
    """
    ship_out_time = datetime.combine(start_date, time.fromisoformat(ship_out_hour))
    ship_in_time = datetime.combine(end_date, time.fromisoformat(ship_in_hour))
    return ship_out_time, ship_in_time


def create_error_response(error_msg: str, status_code: int = 400) -> dict:
    """
    创建标准错误响应

    Args:
        error_msg: 错误信息
        status_code: HTTP状态码

    Returns:
        dict: 错误响应
    """
    return {
        'success': False,
        'error': error_msg
    }


def create_success_response(data: dict, **kwargs) -> dict:
    """
    创建标准成功响应

    Args:
        data: 响应数据
        **kwargs: 其他响应字段

    Returns:
        dict: 成功响应
    """
    response = {
        'success': True,
        'data': data,
        'timestamp': datetime.utcnow().isoformat()
    }
    response.update(kwargs)
    return response
