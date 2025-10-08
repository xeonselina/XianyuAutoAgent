"""
API响应工具类
提供强类型的API响应封装
"""

from typing import Any, Optional
from dataclasses import dataclass
from functools import wraps


@dataclass
class ApiResponse:
    """API响应类"""
    success: bool
    status_code: int
    message: Optional[str] = None
    data: Optional[Any] = None

    def to_dict(self) -> dict:
        """转换为字典"""
        result = {'success': self.success}

        if self.message is not None:
            result['message'] = self.message

        if self.data is not None:
            result['data'] = self.data

        return result

    def to_flask_response(self) -> tuple[dict, int]:
        """转换为Flask响应格式 (dict, status_code)"""
        return self.to_dict(), self.status_code


def handle_response(func):
    """
    装饰器：自动处理ApiResponse对象
    如果handler返回ApiResponse，自动转换为Flask响应格式
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        if isinstance(result, ApiResponse):
            return result.to_flask_response()
        return result
    return wrapper


# 便捷函数
def success(data: Any = None, message: str = None, status_code: int = 200) -> ApiResponse:
    """返回成功响应"""
    return ApiResponse(success=True, status_code=status_code, message=message, data=data)


def error(message: str, status_code: int = 400, data: Any = None) -> ApiResponse:
    """返回错误响应"""
    return ApiResponse(success=False, status_code=status_code, message=message, data=data)


def created(data: Any = None, message: str = '创建成功') -> ApiResponse:
    """返回创建成功响应"""
    return ApiResponse(success=True, status_code=201, message=message, data=data)


def not_found(message: str = '资源不存在') -> ApiResponse:
    """返回资源不存在响应"""
    return ApiResponse(success=False, status_code=404, message=message)


def bad_request(message: str) -> ApiResponse:
    """返回错误请求响应"""
    return ApiResponse(success=False, status_code=400, message=message)


def server_error(message: str = '服务器内部错误') -> ApiResponse:
    """返回服务器错误响应"""
    return ApiResponse(success=False, status_code=500, message=message)
