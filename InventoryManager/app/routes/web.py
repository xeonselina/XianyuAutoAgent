"""前端页面路由、内部 API 与租户请求边界。"""

from datetime import datetime

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import and_, select

from app import db
from app.control.models import AuthSession, Tenant, TenantMember
from app.crypto import hash_token
from app.routes.web_pages import bp as web_pages_bp
from app.routes.gantt_api import bp as gantt_api_bp
from app.routes.device_api import bp as device_api_bp
from app.routes.rental_api import bp as rental_api_bp
from app.routes.inventory_api import bp as inventory_api_bp
from app.routes.ocr_api import bp as ocr_api_bp
from app.routes.customer_api import bp as customer_api_bp
from app.routes.xianyu_order_alert_api import bp as xianyu_order_alert_api_bp
from app.routes.relay_case_api import bp as relay_case_api_bp
from app.tenant_context import bind_tenant, reset_tenant
from app.utils.response import error

# 创建主蓝图
bp = Blueprint('web', __name__)

# 注册所有子模块蓝图
bp.register_blueprint(web_pages_bp)
bp.register_blueprint(gantt_api_bp)
bp.register_blueprint(device_api_bp)
bp.register_blueprint(rental_api_bp)
bp.register_blueprint(inventory_api_bp)
bp.register_blueprint(ocr_api_bp)
bp.register_blueprint(customer_api_bp)
bp.register_blueprint(xianyu_order_alert_api_bp)
bp.register_blueprint(relay_case_api_bp)


_PUBLIC_EXTERNAL_PATHS = {
    '/external-api/health',
    '/external-api/docs',
}
_TENANT_PATH_ROOTS = {'/api', '/web', '/external-api'}


def _requires_tenant_session(path):
    if path in _PUBLIC_EXTERNAL_PATHS:
        return False
    return (
        path in _TENANT_PATH_ROOTS
        or path.startswith(('/api/', '/web/', '/external-api/'))
    )


def _tenant_error(code, message, status_code):
    return error(
        message,
        status_code=status_code,
        code=code,
    ).to_flask_response()


def bind_request_tenant():
    """Authenticate and bind tenant business routes before dispatch."""
    if not _requires_tenant_session(request.path):
        return None
    if current_app.extensions.get('tenant_auth_bypass_enabled', False):
        return None

    raw_token = request.cookies.get('tenant_session')
    if not raw_token:
        return _tenant_error(
            'AUTH_REQUIRED',
            '需要租户登录',
            401,
        )

    control_store = current_app.extensions.get('control_store')
    if control_store is None:
        current_app.logger.error('租户控制数据库未配置')
        return _tenant_error(
            'CONFIG_INCOMPLETE',
            '租户认证服务未配置',
            500,
        )

    now = datetime.utcnow()
    with control_store.session() as session:
        row = session.execute(
            select(AuthSession, TenantMember, Tenant)
            .select_from(AuthSession)
            .join(
                TenantMember,
                and_(
                    TenantMember.id == AuthSession.subject_id,
                    TenantMember.tenant_id == AuthSession.tenant_id,
                ),
            )
            .join(Tenant, Tenant.id == AuthSession.tenant_id)
            .where(
                AuthSession.kind == 'tenant',
                AuthSession.token_hash == hash_token(raw_token),
                AuthSession.expires_at > now,
            )
        ).one_or_none()

    if row is None:
        return _tenant_error(
            'AUTH_REQUIRED',
            '租户会话无效或已过期',
            401,
        )

    auth_session, member, tenant = row
    if member.status != 'active':
        return _tenant_error(
            'AUTH_REQUIRED',
            '租户成员已停用',
            401,
        )
    if tenant.provisioning_status != 'active':
        return _tenant_error(
            'PROVISIONING_FAILED',
            '租户数据库尚未就绪',
            503,
        )
    if tenant.status != 'active':
        return _tenant_error(
            'TENANT_SUSPENDED',
            '租户已暂停',
            403,
        )
    if tenant.expires_at <= now:
        return _tenant_error(
            'TENANT_EXPIRED',
            '租户已到期',
            403,
        )

    registry = current_app.extensions['tenant_engine_registry']
    tenant_engine = registry.get(tenant)
    g.tenant = tenant
    g.member = member
    g.auth_session = auth_session
    g.tenant_context_token = bind_tenant(tenant.id, tenant_engine)
    return None


def reset_request_tenant(_exception):
    """Release the tenant session before restoring the prior context."""
    token = getattr(g, 'tenant_context_token', None)
    if token is None:
        return
    try:
        db.session.remove()
    finally:
        reset_tenant(token)


@bp.route('/health')
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'healthy',
        'timestamp': '2024-01-01T00:00:00Z',
        'service': 'Inventory Manager Web API'
    })
