"""Tenant login, password change, and session routes."""

from datetime import datetime

from flask import Blueprint, current_app, make_response, request

from app.auth import (
    PasswordPolicyError,
    SmsRateLimitExceeded,
    csrf_matches,
    normalize_china_phone,
    refresh_csrf_token,
    resolve_tenant_session,
    revoke_auth_session,
    session_cookie_options,
    should_secure_session_cookie,
)
from app.utils.response import error, success


bp = Blueprint("auth_api", __name__, url_prefix="/auth")
_GENERIC_SMS_MESSAGE = "如果该手机号可登录，验证码将发送至手机"
_GENERIC_PASSWORD_MESSAGE = "手机号或密码无效"


def _auth_method_disabled():
    return error(
        "当前未启用此认证方式",
        status_code=409,
        code="AUTH_METHOD_DISABLED",
    ).to_flask_response()


def _method_is(method):
    return current_app.config["TENANT_AUTH_MODE"] == method


def _auth_error(message="租户会话无效或已过期"):
    return error(
        message,
        status_code=401,
        code="AUTH_REQUIRED",
    ).to_flask_response()


def _tenant_access_status(tenant, now=None):
    now = now or datetime.utcnow()
    if tenant.status != "active":
        return "suspended"
    if tenant.expires_at <= now:
        return "expired"
    if tenant.provisioning_status != "active":
        return tenant.provisioning_status
    return "active"


def _login_data(member, tenant, csrf_token):
    return {
        "csrf_token": csrf_token,
        "member": {
            "id": member.id,
            "phone": member.phone,
            "role": member.role,
            "status": member.status,
        },
        "tenant": {
            "id": tenant.id,
            "name": tenant.name,
            "status": tenant.status,
            "provisioning_status": tenant.provisioning_status,
            "expires_at": tenant.expires_at.isoformat() + "Z",
            "access_status": _tenant_access_status(tenant),
        },
    }


def _identity_from_cookie():
    store = current_app.extensions.get("control_store")
    if store is None:
        return None
    return resolve_tenant_session(
        store,
        request.cookies.get("tenant_session"),
    )


def _login_response(login):
    payload, status_code = success(
        data=_login_data(
            login.member,
            login.tenant,
            login.credentials.csrf_token,
        )
    ).to_flask_response()
    response = make_response(payload, status_code)
    response.set_cookie(
        "tenant_session",
        login.credentials.raw_token,
        **session_cookie_options(
            "tenant",
            secure=should_secure_session_cookie(
                current_app.config.get("SESSION_COOKIE_SECURE", False),
                request.is_secure,
            ),
        ),
    )
    return response


@bp.get("/config")
def tenant_auth_config():
    return success(
        data={"method": current_app.config["TENANT_AUTH_MODE"]}
    ).to_flask_response()


@bp.post("/sms/request")
def request_sms_code():
    if not _method_is("sms"):
        return _auth_method_disabled()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return error(
            "请求体必须是 JSON 对象",
            status_code=400,
            code="INVALID_REQUEST",
        ).to_flask_response()
    raw_phone = body.get("phone")
    try:
        normalize_china_phone(raw_phone)
    except ValueError:
        return error(
            "请输入有效的大陆手机号",
            status_code=400,
            code="INVALID_REQUEST",
        ).to_flask_response()

    auth_service = current_app.extensions.get("auth_service")
    if auth_service is None:
        return error(
            "租户认证服务未配置",
            status_code=500,
            code="CONFIG_INCOMPLETE",
        ).to_flask_response()
    try:
        auth_service.request_code(raw_phone, request.remote_addr)
    except SmsRateLimitExceeded:
        return error(
            "验证码请求过于频繁",
            status_code=429,
            code="RATE_LIMITED",
        ).to_flask_response()
    return success(message=_GENERIC_SMS_MESSAGE).to_flask_response()


@bp.post("/sms/verify")
def verify_sms_code():
    if not _method_is("sms"):
        return _auth_method_disabled()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return error(
            "请求体必须是 JSON 对象",
            status_code=400,
            code="INVALID_REQUEST",
        ).to_flask_response()
    raw_phone = body.get("phone")
    code = body.get("code")
    if raw_phone is None or code is None:
        return error(
            "手机号和验证码不能为空",
            status_code=400,
            code="INVALID_REQUEST",
        ).to_flask_response()
    auth_service = current_app.extensions.get("auth_service")
    if auth_service is None:
        return error(
            "租户认证服务未配置",
            status_code=500,
            code="CONFIG_INCOMPLETE",
        ).to_flask_response()

    login = auth_service.verify_code(raw_phone, code)
    if login is None:
        return error(
            "手机号或验证码无效",
            status_code=401,
            code="AUTH_INVALID",
        ).to_flask_response()

    return _login_response(login)


@bp.post("/password/login")
def login_with_password():
    if not _method_is("password"):
        return _auth_method_disabled()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return error(
            "请求体必须是 JSON 对象",
            status_code=400,
            code="INVALID_REQUEST",
        ).to_flask_response()
    if "phone" not in body or "password" not in body:
        return error(
            "手机号和密码不能为空",
            status_code=400,
            code="INVALID_REQUEST",
        ).to_flask_response()
    auth_service = current_app.extensions.get("auth_service")
    if auth_service is None:
        return error(
            "租户认证服务未配置",
            status_code=500,
            code="CONFIG_INCOMPLETE",
        ).to_flask_response()
    login = auth_service.login_password(
        body.get("phone"),
        body.get("password"),
    )
    if login is None:
        return error(
            _GENERIC_PASSWORD_MESSAGE,
            status_code=401,
            code="AUTH_INVALID",
        ).to_flask_response()
    return _login_response(login)


@bp.post("/password/change")
def change_password():
    if not _method_is("password"):
        return _auth_method_disabled()
    identity = _identity_from_cookie()
    if identity is None:
        return _auth_error()
    if not csrf_matches(
        identity.auth_session,
        request.headers.get("X-CSRF-Token"),
    ):
        return error(
            "CSRF token 无效",
            status_code=403,
            code="CSRF_INVALID",
        ).to_flask_response()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return error(
            "请求体必须是 JSON 对象",
            status_code=400,
            code="INVALID_REQUEST",
        ).to_flask_response()
    if "current_password" not in body or "new_password" not in body:
        return error(
            "当前密码和新密码不能为空",
            status_code=400,
            code="INVALID_REQUEST",
        ).to_flask_response()
    auth_service = current_app.extensions.get("auth_service")
    if auth_service is None:
        return error(
            "租户认证服务未配置",
            status_code=500,
            code="CONFIG_INCOMPLETE",
        ).to_flask_response()
    try:
        changed = auth_service.change_password(
            identity.member.id,
            identity.auth_session.id,
            body.get("current_password"),
            body.get("new_password"),
        )
    except PasswordPolicyError:
        return error(
            "新密码必须为 8 至 128 个字符",
            status_code=400,
            code="PASSWORD_POLICY",
        ).to_flask_response()
    if not changed:
        return error(
            "当前密码无效",
            status_code=401,
            code="AUTH_INVALID",
        ).to_flask_response()
    return success(message="密码已更新").to_flask_response()


@bp.get("/me")
def current_tenant_member():
    identity = _identity_from_cookie()
    if identity is None:
        return _auth_error()
    csrf_token = refresh_csrf_token(
        current_app.extensions["control_store"],
        identity.auth_session.id,
        request.cookies.get("tenant_session"),
    )
    if csrf_token is None:
        return _auth_error()
    return success(
        data=_login_data(
            identity.member,
            identity.tenant,
            csrf_token,
        )
    ).to_flask_response()


@bp.post("/logout")
def logout_tenant_member():
    identity = _identity_from_cookie()
    if identity is None:
        return _auth_error()
    if not csrf_matches(
        identity.auth_session,
        request.headers.get("X-CSRF-Token"),
    ):
        return error(
            "CSRF token 无效",
            status_code=403,
            code="CSRF_INVALID",
        ).to_flask_response()

    revoke_auth_session(
        current_app.extensions["control_store"],
        identity.auth_session.id,
    )
    payload, status_code = success(message="已退出登录").to_flask_response()
    response = make_response(payload, status_code)
    response.delete_cookie(
        "tenant_session",
        path="/",
        secure=should_secure_session_cookie(
            current_app.config.get("SESSION_COOKIE_SECURE", False),
            request.is_secure,
        ),
        httponly=True,
        samesite="Lax",
    )
    return response
