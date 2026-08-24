"""
批量发货 API 路由模块
重构后的精简版本，只包含路由定义
"""

from flask import Blueprint, current_app, jsonify, request
from app.handlers.shipping_batch_handlers import ShippingBatchHandlers
from app.services.shipping.batch_http_runtime import (
    SfBatchShippingHttpError,
    require_sf_batch_shipping_http_runtime,
)
from app.utils.response import error, handle_response, success
from inventory_control.tenant_http import TenantHttpError

bp = Blueprint('shipping_batch', __name__, url_prefix='/api/shipping-batch')
_MIGRATED_RUNTIME_ENDPOINTS = frozenset({"schedule_shipment"})


def _legacy_test_runtime_enabled() -> bool:
    return (
        current_app.testing is True
        and current_app.config.get(
            "ENABLE_LEGACY_SINGLE_TENANT_SHIPPING_BATCH_API"
        )
        is True
    )


@bp.before_request
def require_tenant_shipping_runtime():
    """Keep global-session/provider handlers unreachable outside tests."""

    if _legacy_test_runtime_enabled():
        return None
    endpoint_name = (request.endpoint or "").rsplit(".", 1)[-1]
    if endpoint_name in _MIGRATED_RUNTIME_ENDPOINTS:
        return None
    response = jsonify({
        "success": False,
        "message": "租户发货服务尚未就绪",
    })
    response.status_code = 503
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@bp.after_request
def protect_shipping_responses(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@bp.route('/schedule', methods=['POST'])
@handle_response
def schedule_shipment():
    """预约发货"""
    if _legacy_test_runtime_enabled():
        return ShippingBatchHandlers.handle_schedule_shipment()
    try:
        result = require_sf_batch_shipping_http_runtime().schedule_shipments(
            flask_request=request,
            payload=request.get_json(silent=True),
        )
        return success(data=result, message="发货任务已受理", status_code=202)
    except TenantHttpError as exc:
        return error(
            exc.public_message,
            status_code=exc.status_code,
            data={"code": exc.code},
        )
    except SfBatchShippingHttpError as exc:
        return error(
            exc.public_message,
            status_code=exc.status_code,
            data={"code": exc.code},
        )


@bp.route('/status', methods=['GET'])
@handle_response
def get_status():
    """获取批量发货状态摘要"""
    return ShippingBatchHandlers.handle_get_status()


@bp.route('/express-type', methods=['PATCH'])
@handle_response
def update_express_type():
    """更新租赁订单的快递类型"""
    return ShippingBatchHandlers.handle_update_express_type()


@bp.route('/printers', methods=['GET'])
@handle_response
def get_printers():
    """获取打印机配置信息"""
    return ShippingBatchHandlers.handle_get_printers()


@bp.route('/print-waybills', methods=['POST'])
@handle_response
def print_waybills():
    """批量打印快递面单"""
    return ShippingBatchHandlers.handle_print_waybills()


@bp.route('/ship-to-xianyu/<int:rental_id>', methods=['POST'])
@handle_response
def ship_to_xianyu(rental_id):
    """发货到闲鱼"""
    return ShippingBatchHandlers.handle_ship_to_xianyu(rental_id)
