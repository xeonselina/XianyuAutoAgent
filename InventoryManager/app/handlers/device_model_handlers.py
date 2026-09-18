"""
设备型号API处理器
包含设备型号相关的请求处理逻辑
"""

from flask import request, current_app
from app.utils.response import (
    ApiResponse,
    created,
    error,
    not_found,
    success,
    bad_request,
    server_error
)
from app.services.device.device_model_service import (
    DeviceModelConflict,
    DeviceModelNotFound,
    DeviceModelService,
)


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

    @staticmethod
    def handle_get_library() -> ApiResponse:
        try:
            return success(data=DeviceModelService.get_library())
        except Exception as exc:
            current_app.logger.exception("获取型号库失败: %s", exc)
            return server_error("获取型号库失败")

    @staticmethod
    def handle_create() -> ApiResponse:
        try:
            return created(
                data=DeviceModelService.create(request.get_json(silent=True)),
                message="型号创建成功",
            )
        except DeviceModelConflict as exc:
            return error(str(exc), status_code=409, code="MODEL_CONFLICT")
        except ValueError as exc:
            return bad_request(str(exc))
        except Exception as exc:
            current_app.logger.exception("创建设备型号失败: %s", exc)
            return server_error("创建设备型号失败")

    @staticmethod
    def handle_update(model_id: int) -> ApiResponse:
        try:
            return success(
                data=DeviceModelService.update(
                    model_id, request.get_json(silent=True)
                ),
                message="型号更新成功",
            )
        except DeviceModelNotFound as exc:
            return not_found(str(exc))
        except DeviceModelConflict as exc:
            return error(str(exc), status_code=409, code="MODEL_CONFLICT")
        except ValueError as exc:
            return bad_request(str(exc))
        except Exception as exc:
            current_app.logger.exception("更新设备型号失败: %s", exc)
            return server_error("更新设备型号失败")

    @staticmethod
    def handle_delete(model_id: int) -> ApiResponse:
        try:
            DeviceModelService.delete(model_id)
            return success(message="型号已删除")
        except DeviceModelNotFound as exc:
            return not_found(str(exc))
        except DeviceModelConflict as exc:
            return error(str(exc), status_code=409, code="MODEL_IN_USE")
        except Exception as exc:
            current_app.logger.exception("删除设备型号失败: %s", exc)
            return server_error("删除设备型号失败")

    @staticmethod
    def handle_assign_legacy() -> ApiResponse:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return bad_request("请求体必须是 JSON 对象")
        try:
            return success(
                data=DeviceModelService.assign_legacy_group(
                    data.get("legacy_model"), data.get("model_id")
                ),
                message="历史型号归类成功",
            )
        except DeviceModelNotFound as exc:
            return not_found(str(exc))
        except DeviceModelConflict as exc:
            return error(str(exc), status_code=409, code="MODEL_CONFLICT")
        except ValueError as exc:
            return bad_request(str(exc))
        except Exception as exc:
            current_app.logger.exception("历史型号归类失败: %s", exc)
            return server_error("历史型号归类失败")
