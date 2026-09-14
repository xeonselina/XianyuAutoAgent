"""
设备型号API路由
重构后的精简版本，只包含路由定义
"""

from flask import Blueprint, current_app, g
from app.handlers.device_model_handlers import DeviceModelHandlers
from app.utils.response import error, handle_response

bp = Blueprint('device_model_api', __name__)


def _require_tenant_admin():
    member = getattr(g, "member", None)
    if member is None:
        if current_app.extensions.get("tenant_auth_bypass_enabled", False):
            return None
        return error(
            "需要店铺管理员登录",
            status_code=403,
            code="ADMIN_REQUIRED",
        )
    if member.role != "admin":
        return error(
            "只有店铺管理员可以维护设备型号",
            status_code=403,
            code="ADMIN_REQUIRED",
        )
    return None


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


@bp.get('/api/device-models/library')
@handle_response
def get_device_model_library():
    """获取完整型号库、引用数和历史自由文本分组。"""
    return DeviceModelHandlers.handle_get_library()


@bp.post('/api/device-models')
@handle_response
def create_device_model():
    denied = _require_tenant_admin()
    return denied or DeviceModelHandlers.handle_create()


@bp.put('/api/device-models/<int:model_id>')
@handle_response
def update_device_model(model_id):
    denied = _require_tenant_admin()
    return denied or DeviceModelHandlers.handle_update(model_id)


@bp.delete('/api/device-models/<int:model_id>')
@handle_response
def delete_device_model(model_id):
    denied = _require_tenant_admin()
    return denied or DeviceModelHandlers.handle_delete(model_id)


@bp.post('/api/device-models/assign-legacy')
@handle_response
def assign_legacy_device_model():
    denied = _require_tenant_admin()
    return denied or DeviceModelHandlers.handle_assign_legacy()
