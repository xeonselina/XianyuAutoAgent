"""
设备型号API处理器
包含设备型号相关的请求处理逻辑
"""

from flask import request, current_app
from app.utils.response import (
    ApiResponse,
    success,
    bad_request,
    server_error
)
from app.services.device.device_model_service import DeviceModelService


class DeviceModelHandlers:
    """设备型号处理器类"""

    @staticmethod
    def handle_get_device_models() -> ApiResponse:
        """处理获取设备型号列表请求"""
        try:
            # 调用服务层获取所有激活的设备型号
            models = DeviceModelService.get_active_models_with_accessories()
            return success(data=models)

        except Exception as e:
            current_app.logger.error(f"获取设备型号失败: {e}")
            return server_error('获取设备型号失败')

    @staticmethod
    def handle_get_model_accessories(model_id: int) -> ApiResponse:
        """处理获取设备附件请求"""
        try:
            # 验证 model_id
            if not isinstance(model_id, int) or model_id <= 0:
                return bad_request('无效的设备型号ID')

            # 调用服务层获取附件
            accessories = DeviceModelService.get_accessories_for_model(model_id)
            return success(data=accessories)

        except Exception as e:
            current_app.logger.error(f"获取设备附件失败: {e}")
            return server_error('获取设备附件失败')
