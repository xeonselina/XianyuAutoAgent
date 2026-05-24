"""
设备相关请求处理器
"""

from flask import request, current_app
from app.services.device.device_service import DeviceService


class DeviceHandlers:
    """设备处理器类"""

    @staticmethod
    def handle_get_devices():
        """处理 GET /api/devices 请求（支持查询参数过滤）"""
        try:
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 20))
            name = request.args.get('name')
            model = request.args.get('model')
            status = request.args.get('status')
            lifecycle_status = request.args.get('lifecycle_status')
            is_accessory = request.args.get('is_accessory')
            serial_number = request.args.get('serial_number')
            
            # 转换布尔值
            if is_accessory is not None:
                is_accessory = is_accessory.lower() == 'true'
            
            return DeviceService.get_devices_with_filters(
                page=page,
                per_page=per_page,
                name=name,
                model=model,
                status=status,
                lifecycle_status=lifecycle_status,
                is_accessory=is_accessory,
                serial_number=serial_number
            )
        
        except ValueError as e:
            current_app.logger.error(f"参数解析错误: {e}")
            raise
        except Exception as e:
            current_app.logger.error(f"获取设备列表失败: {e}")
            raise

    @staticmethod
    def handle_search_devices():
        """处理 POST /api/devices/search 请求（支持JSON体搜索）"""
        try:
            data = request.get_json() or {}
            
            # 通用搜索字段 'q' 可以用于名称和序列号
            q = data.get('q')
            name = data.get('name') or (q if q else None)
            serial_number = data.get('serial_number') or (q if q else None)
            model = data.get('model')
            status = data.get('status')
            lifecycle_status = data.get('lifecycle_status')
            is_accessory = data.get('is_accessory')
            page = int(data.get('page', 1))
            per_page = int(data.get('per_page', 20))
            
            return DeviceService.get_devices_with_filters(
                page=page,
                per_page=per_page,
                name=name,
                model=model,
                status=status,
                lifecycle_status=lifecycle_status,
                is_accessory=is_accessory,
                serial_number=serial_number
            )
        
        except ValueError as e:
            current_app.logger.error(f"参数解析错误: {e}")
            raise
        except Exception as e:
            current_app.logger.error(f"搜索设备失败: {e}")
            raise
