"""
租赁相关API路由
重构后的精简版本，只包含路由定义
"""

from flask import Blueprint, current_app, jsonify, request
from app.handlers.rental_handlers import RentalHandlers
from app.services.rental.http_runtime import (
    RentalAvailabilityInvalid,
    RentalIdInvalid,
    RentalQueryInvalid,
    RentalSaasHttpRuntimeUnavailable,
    require_rental_saas_http_runtime,
)
from app.services.rental.mutation_service import RentalMutationError
from app.utils.response import (
    bad_request,
    created,
    error,
    handle_response,
    not_found,
    success,
)
from inventory_control.tenant_http import TenantHttpError

bp = Blueprint('rental_api', __name__)
_MIGRATED_RUNTIME_ENDPOINTS = frozenset({
    "booking_availability",
    "booking_bootstrap",
    "create_rental",
    "delete_rental",
    "get_rental",
    "get_rentals",
    "get_due_today_rentals",
    "get_edit_context",
    "get_pending_returns",
    "search_rentals",
    "update_rental",
    "update_rental_status",
    "web_get_rental",
    "web_delete_rental",
    "web_update_rental",
})


def _legacy_test_runtime_enabled() -> bool:
    return (
        current_app.testing is True
        and current_app.config.get(
            "ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API"
        )
        is True
    )


@bp.before_request
def require_tenant_rental_runtime():
    """Block every legacy global-session rental handler outside tests.

    The handlers below still use Flask-SQLAlchemy's process-global bind and
    therefore cannot derive a tenant database from the authenticated control
    session.  Until an endpoint is migrated onto the explicit tenant-business
    runtime, production must stop here before any handler, ORM query, provider
    call, or mutation can run.  The exception is deliberately limited to an
    explicit testing-only compatibility flag; setting the flag in a real
    process cannot enable the legacy path.
    """

    if _legacy_test_runtime_enabled():
        return None
    endpoint_name = (request.endpoint or "").rsplit(".", 1)[-1]
    if endpoint_name in _MIGRATED_RUNTIME_ENDPOINTS:
        return None

    response = jsonify({
        "success": False,
        "message": "租户租赁服务尚未就绪",
    })
    response.status_code = 503
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@bp.after_request
def protect_rental_responses(response):
    """Tenant rental payloads and fixed failures must never be cached."""

    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


def _get_rental_from_current_runtime(rental_id):
    if _legacy_test_runtime_enabled():
        return RentalHandlers.handle_get_rental(rental_id)
    try:
        runtime = require_rental_saas_http_runtime()
        rental = runtime.get_rental(
            flask_request=request,
            rental_id=rental_id,
        )
        if rental is None:
            return not_found("租赁记录不存在")
        return success(data=rental)
    except RentalIdInvalid as exc:
        return bad_request(str(exc))
    except TenantHttpError as exc:
        return error(
            exc.public_message,
            status_code=exc.status_code,
            data={"code": exc.code},
        )
    except RentalSaasHttpRuntimeUnavailable:
        return error("租户租赁服务尚未就绪", status_code=503)


def _get_edit_context_from_current_runtime(rental_id):
    try:
        runtime = require_rental_saas_http_runtime()
        context = runtime.get_edit_context(
            flask_request=request,
            rental_id=rental_id,
        )
        if context is None:
            return not_found("租赁记录不存在")
        return success(data=context)
    except RentalIdInvalid as exc:
        return bad_request(str(exc))
    except TenantHttpError as exc:
        return error(
            exc.public_message,
            status_code=exc.status_code,
            data={"code": exc.code},
        )
    except RentalSaasHttpRuntimeUnavailable:
        return error("租户租赁服务尚未就绪", status_code=503)


def _list_rentals_from_current_runtime(filters):
    if _legacy_test_runtime_enabled():
        return None
    try:
        runtime = require_rental_saas_http_runtime()
        return success(data=runtime.list_rentals(
            flask_request=request,
            filters=filters,
        ))
    except RentalQueryInvalid as exc:
        return bad_request(str(exc))
    except TenantHttpError as exc:
        return error(
            exc.public_message,
            status_code=exc.status_code,
            data={"code": exc.code},
        )
    except RentalSaasHttpRuntimeUnavailable:
        return error("租户租赁服务尚未就绪", status_code=503)


def _list_pending_returns_from_current_runtime():
    if _legacy_test_runtime_enabled():
        return None
    try:
        runtime = require_rental_saas_http_runtime()
        return success(data=runtime.list_pending_returns(
            flask_request=request,
            pagination=request.args.to_dict(flat=True),
        ))
    except RentalQueryInvalid as exc:
        return bad_request(str(exc))
    except TenantHttpError as exc:
        return error(
            exc.public_message,
            status_code=exc.status_code,
            data={"code": exc.code},
        )
    except RentalSaasHttpRuntimeUnavailable:
        return error("租户租赁服务尚未就绪", status_code=503)


def _booking_bootstrap_from_current_runtime():
    try:
        runtime = require_rental_saas_http_runtime()
        return success(data=runtime.booking_bootstrap(flask_request=request))
    except TenantHttpError as exc:
        return error(
            exc.public_message,
            status_code=exc.status_code,
            data={"code": exc.code},
        )
    except RentalSaasHttpRuntimeUnavailable:
        return error("租户租赁服务尚未就绪", status_code=503)


def _booking_availability_from_current_runtime():
    try:
        runtime = require_rental_saas_http_runtime()
        return success(data=runtime.booking_availability(
            flask_request=request,
            payload=request.get_json(silent=True),
        ))
    except RentalAvailabilityInvalid as exc:
        return bad_request(str(exc))
    except TenantHttpError as exc:
        return error(
            exc.public_message,
            status_code=exc.status_code,
            data={"code": exc.code},
        )
    except RentalSaasHttpRuntimeUnavailable:
        return error("租户租赁服务尚未就绪", status_code=503)


def _create_rental_from_current_runtime():
    try:
        runtime = require_rental_saas_http_runtime()
        result = runtime.create_rental(
            flask_request=request,
            payload=request.get_json(silent=True),
        )
        return created(data=result, message="租赁记录创建成功")
    except RentalMutationError as exc:
        return error(
            exc.public_message,
            status_code=exc.status_code,
            data={"code": exc.code, **exc.data},
        )
    except TenantHttpError as exc:
        return error(
            exc.public_message,
            status_code=exc.status_code,
            data={"code": exc.code},
        )
    except RentalSaasHttpRuntimeUnavailable:
        return error("租户租赁服务尚未就绪", status_code=503)


def _update_rental_from_current_runtime(rental_id):
    try:
        runtime = require_rental_saas_http_runtime()
        result = runtime.update_rental(
            flask_request=request,
            rental_id=rental_id,
            payload=request.get_json(silent=True),
        )
        return success(data=result, message="租赁记录更新成功")
    except RentalIdInvalid as exc:
        return bad_request(str(exc))
    except RentalMutationError as exc:
        return error(
            exc.public_message,
            status_code=exc.status_code,
            data={"code": exc.code, **exc.data},
        )
    except TenantHttpError as exc:
        return error(
            exc.public_message,
            status_code=exc.status_code,
            data={"code": exc.code},
        )
    except RentalSaasHttpRuntimeUnavailable:
        return error("租户租赁服务尚未就绪", status_code=503)


def _update_rental_status_from_current_runtime(rental_id):
    try:
        runtime = require_rental_saas_http_runtime()
        result = runtime.update_rental_status(
            flask_request=request,
            rental_id=rental_id,
            payload=request.get_json(silent=True),
        )
        return success(data=result, message="状态更新成功")
    except RentalIdInvalid as exc:
        return bad_request(str(exc))
    except RentalMutationError as exc:
        return error(
            exc.public_message,
            status_code=exc.status_code,
            data={"code": exc.code, **exc.data},
        )
    except TenantHttpError as exc:
        return error(
            exc.public_message,
            status_code=exc.status_code,
            data={"code": exc.code},
        )
    except RentalSaasHttpRuntimeUnavailable:
        return error("租户租赁服务尚未就绪", status_code=503)


def _delete_rental_from_current_runtime(rental_id):
    try:
        runtime = require_rental_saas_http_runtime()
        result = runtime.delete_rental(
            flask_request=request,
            rental_id=rental_id,
        )
        return success(data=result, message="租赁记录删除成功")
    except RentalIdInvalid as exc:
        return bad_request(str(exc))
    except RentalMutationError as exc:
        return error(
            exc.public_message,
            status_code=exc.status_code,
            data={"code": exc.code, **exc.data},
        )
    except TenantHttpError as exc:
        return error(
            exc.public_message,
            status_code=exc.status_code,
            data={"code": exc.code},
        )
    except RentalSaasHttpRuntimeUnavailable:
        return error("租户租赁服务尚未就绪", status_code=503)


# ===================== 基础租赁API =====================

@bp.route('/api/rental-booking/bootstrap')
@handle_response
def booking_bootstrap():
    """一次返回预约表单所需的非库存元数据。"""
    return _booking_bootstrap_from_current_runtime()


@bp.route('/api/rental-booking/availability', methods=['POST'])
@handle_response
def booking_availability():
    """批量返回实时主设备、物流与逻辑附件可用性。"""
    return _booking_availability_from_current_runtime()

@bp.route('/api/rentals/estimate-logistics')
@handle_response
def estimate_logistics():
    """根据目的地预估顺丰标快物流时效"""
    return RentalHandlers.handle_estimate_logistics()

@bp.route('/api/rentals')
@handle_response
def get_rentals():
    """获取租赁记录列表"""
    runtime_response = _list_rentals_from_current_runtime(
        request.args.to_dict(flat=True)
    )
    if runtime_response is not None:
        return runtime_response
    return RentalHandlers.handle_get_rentals()


@bp.route('/api/rentals/pending-returns')
@handle_response
def get_pending_returns():
    """获取今天及以前应归还的租赁记录"""
    runtime_response = _list_pending_returns_from_current_runtime()
    if runtime_response is not None:
        return runtime_response
    return RentalHandlers.handle_get_pending_returns()


@bp.route('/api/rentals/due-today')
@handle_response
def get_due_today_rentals():
    """待归还租赁记录的兼容接口"""
    runtime_response = _list_pending_returns_from_current_runtime()
    if runtime_response is not None:
        return runtime_response
    return RentalHandlers.handle_get_pending_returns()


@bp.route('/api/rentals/<rental_id>')
@handle_response
def get_rental(rental_id):
    """获取单个租赁记录"""
    return _get_rental_from_current_runtime(rental_id)


@bp.route('/api/rentals/<rental_id>/edit-context')
@handle_response
def get_edit_context(rental_id):
    """一次返回权威租赁编辑 DTO 与表单元数据。"""
    return _get_edit_context_from_current_runtime(rental_id)


@bp.route('/api/rentals', methods=['POST'])
@handle_response
def create_rental():
    """创建租赁记录"""
    if not _legacy_test_runtime_enabled():
        return _create_rental_from_current_runtime()
    return RentalHandlers.handle_create_rental()


@bp.route('/api/rentals/<rental_id>', methods=['PUT'])
@handle_response
def update_rental(rental_id):
    """更新租赁记录"""
    if not _legacy_test_runtime_enabled():
        return _update_rental_from_current_runtime(rental_id)
    return RentalHandlers.handle_web_update_rental(rental_id)


@bp.route('/api/rentals/<rental_id>', methods=['DELETE'])
@handle_response
def delete_rental(rental_id):
    """删除租赁记录"""
    if not _legacy_test_runtime_enabled():
        return _delete_rental_from_current_runtime(rental_id)
    return RentalHandlers.handle_delete_rental(rental_id)


@bp.route('/api/rentals/<rental_id>/status', methods=['PUT'])
@handle_response
def update_rental_status(rental_id):
    """更新租赁状态"""
    if not _legacy_test_runtime_enabled():
        return _update_rental_status_from_current_runtime(rental_id)
    return RentalHandlers.handle_update_rental_status(rental_id)


@bp.route('/api/rentals/<rental_id>/ship-to-xianyu', methods=['POST'])
@handle_response
def ship_rental_to_xianyu(rental_id):
    """单个租赁发货到闲鱼"""
    return RentalHandlers.handle_ship_rental_to_xianyu(rental_id)


# ===================== 租赁检查API =====================

@bp.route('/api/rentals/check-conflict', methods=['POST'])
@handle_response
def check_rental_conflict():
    """检查租赁冲突"""
    return RentalHandlers.handle_check_rental_conflict()


@bp.route('/api/rentals/check-duplicate', methods=['POST'])
@handle_response
def check_duplicate_rental():
    """检查重复租赁"""
    return RentalHandlers.handle_check_duplicate_rental()


# ===================== Web界面API =====================

@bp.route('/web/rentals/<rental_id>', methods=['GET'])
@handle_response
def web_get_rental(rental_id):
    """Web界面获取租赁记录"""
    return _get_rental_from_current_runtime(rental_id)


@bp.route('/web/rentals/<rental_id>', methods=['PUT'])
@handle_response
def web_update_rental(rental_id):
    """Web界面更新租赁记录"""
    if not _legacy_test_runtime_enabled():
        return _update_rental_from_current_runtime(rental_id)
    return RentalHandlers.handle_web_update_rental(rental_id)


@bp.route('/web/rentals/<rental_id>', methods=['DELETE'])
@handle_response
def web_delete_rental(rental_id):
    """Web界面删除租赁记录"""
    if not _legacy_test_runtime_enabled():
        return _delete_rental_from_current_runtime(rental_id)
    return RentalHandlers.handle_delete_rental(rental_id)


# ===================== 闲鱼订单API =====================

@bp.route('/api/rentals/fetch-xianyu-order', methods=['POST'])
@handle_response
def fetch_xianyu_order():
    """获取闲鱼订单详情"""
    return RentalHandlers.handle_fetch_xianyu_order()




# ===================== 搜索API =====================

@bp.route('/api/rentals/search', methods=['POST'])
@handle_response
def search_rentals():
    """搜索租赁记录 - 支持多字段搜索"""
    runtime_response = _list_rentals_from_current_runtime(
        request.get_json(silent=True)
    )
    if runtime_response is not None:
        return runtime_response
    return RentalHandlers.handle_search_rentals()

# ===================== 批量打印API =====================

@bp.route('/api/rentals/by-ship-date', methods=['GET'])
@handle_response
def get_rentals_by_ship_date():
    """根据发货日期范围查询租赁记录（用于批量打印）"""
    return RentalHandlers.handle_get_rentals_by_ship_date()
