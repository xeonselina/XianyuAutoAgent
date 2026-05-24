"""
设备型号API路由
重构后的精简版本，只包含路由定义
"""

from flask import Blueprint
from app.handlers.device_model_handlers import DeviceModelHandlers
from app.utils.response import handle_response

bp = Blueprint('device_model_api', __name__)


@bp.route('/api/device-models', methods=['GET'])
@handle_response
def get_device_models():
    """获取所有激活的设备型号及其附件"""
    return DeviceModelHandlers.handle_get_device_models()


@bp.route('/api/device-models/<int:model_id>/accessories', methods=['GET'])
@handle_response
def get_model_accessories(model_id):
    """获取指定型号的附件"""
    return DeviceModelHandlers.handle_get_model_accessories(model_id)
