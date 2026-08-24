"""Independent platform-administrator login and session endpoints."""

from flask import Blueprint, jsonify, request

from app.services.platform_identity import (
    PlatformIdentityRuntimeUnavailable,
    PlatformLoginHttpRejected,
    PlatformStepUpHttpRejected,
    require_platform_identity_http_runtime,
)
from app.services.platform_tenant_read import (
    PlatformTenantReadRuntimeUnavailable,
    require_platform_tenant_read_http_runtime,
)
from inventory_control.platform_http import (
    PlatformHttpError,
    clear_platform_session_cookie,
    set_platform_device_cookie,
    set_platform_session_cookie,
)


bp = Blueprint(
    "platform_identity_api",
    __name__,
    url_prefix="/platform/api",
)


@bp.after_request
def protect_platform_identity_responses(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@bp.post("/login")
def login():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    try:
        result = require_platform_identity_http_runtime().login(
            flask_request=request,
            username=payload.get("username"),
            password=payload.get("password"),
            factor_method=payload.get("factor_method"),
            factor_value=payload.get("factor"),
            device_name=payload.get("device_name"),
        )
        response = jsonify(
            {
                "success": True,
                "data": {
                    "csrf_token": result.issued.csrf_token,
                    "session_id": result.issued.auth.session_id,
                    "role": "platform_admin",
                    "mfa_method": result.issued.auth.mfa_method,
                },
            }
        )
        response = set_platform_session_cookie(
            response, result.issued.session_token
        )
        if result.set_device_cookie:
            response = set_platform_device_cookie(
                response,
                result.device_id,
                max_age_seconds=result.device_cookie_max_age_seconds,
            )
        return response, 200
    except PlatformLoginHttpRejected as exc:
        response, status = _platform_failure(exc)
        if exc.set_device_cookie:
            response = set_platform_device_cookie(
                response,
                exc.device_id,
                max_age_seconds=exc.device_cookie_max_age_seconds,
            )
        return response, status
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformIdentityRuntimeUnavailable:
        return _unavailable()


@bp.post("/setup/consume")
def consume_setup_token():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    try:
        result = require_platform_identity_http_runtime().consume_setup_token(
            flask_request=request,
            setup_token=payload.get("setup_token"),
        )
        return jsonify({"success": True, "data": result}), 200
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformIdentityRuntimeUnavailable:
        return _unavailable()


@bp.post("/setup/password")
def set_setup_password():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    try:
        result = require_platform_identity_http_runtime().set_setup_password(
            flask_request=request,
            password=payload.get("password"),
        )
        return jsonify({"success": True, "data": result}), 200
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformIdentityRuntimeUnavailable:
        return _unavailable()


@bp.post("/setup/totp")
def begin_setup_totp():
    try:
        result = require_platform_identity_http_runtime().begin_setup_totp(
            flask_request=request
        )
        return jsonify({"success": True, "data": result}), 200
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformIdentityRuntimeUnavailable:
        return _unavailable()


@bp.post("/setup/complete")
def complete_setup():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    try:
        result = require_platform_identity_http_runtime().complete_setup(
            flask_request=request,
            credential_id=payload.get("credential_id"),
            totp_code=payload.get("totp_code"),
        )
        return jsonify({"success": True, "data": result}), 200
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformIdentityRuntimeUnavailable:
        return _unavailable()


@bp.post("/step-up")
def step_up():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    try:
        result = require_platform_identity_http_runtime().step_up(
            flask_request=request,
            factor_method=payload.get("factor_method"),
            factor_value=payload.get("factor"),
        )
        response = jsonify(
            {
                "success": True,
                "data": {
                    "csrf_token": result.issued.csrf_token,
                    "session_id": result.issued.auth.session_id,
                    "role": "platform_admin",
                    "mfa_method": result.issued.auth.mfa_method,
                    "mfa_verified_at": result.issued.auth.mfa_verified_at,
                },
            }
        )
        response = set_platform_session_cookie(
            response, result.issued.session_token
        )
        if result.set_device_cookie:
            response = set_platform_device_cookie(
                response,
                result.device_id,
                max_age_seconds=result.device_cookie_max_age_seconds,
            )
        return response, 200
    except PlatformStepUpHttpRejected as exc:
        return _factor_failure(exc)
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformIdentityRuntimeUnavailable:
        return _unavailable()


@bp.post("/factors/totp/replacement")
def begin_totp_replacement():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    try:
        result = (
            require_platform_identity_http_runtime()
            .begin_totp_replacement(
                flask_request=request,
                factor_method=payload.get("factor_method"),
                factor_value=payload.get("factor"),
            )
        )
        return _credential_success(result)
    except PlatformStepUpHttpRejected as exc:
        return _factor_failure(exc)
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformIdentityRuntimeUnavailable:
        return _unavailable()


@bp.post("/factors/totp/replacement/complete")
def complete_totp_replacement():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    try:
        result = (
            require_platform_identity_http_runtime()
            .complete_totp_replacement(
                flask_request=request,
                credential_id=payload.get("credential_id"),
                totp_code=payload.get("totp_code"),
            )
        )
        return _credential_success(result)
    except PlatformStepUpHttpRejected as exc:
        return _factor_failure(exc)
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformIdentityRuntimeUnavailable:
        return _unavailable()


@bp.post("/factors/recovery-codes/regenerate")
def regenerate_recovery_codes():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    try:
        result = (
            require_platform_identity_http_runtime()
            .regenerate_recovery_codes(
                flask_request=request,
                factor_method=payload.get("factor_method"),
                factor_value=payload.get("factor"),
            )
        )
        return _credential_success(result)
    except PlatformStepUpHttpRejected as exc:
        return _factor_failure(exc)
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformIdentityRuntimeUnavailable:
        return _unavailable()


@bp.get("/session")
def session_status():
    try:
        result = require_platform_identity_http_runtime().session_status(
            flask_request=request
        )
        return jsonify({"success": True, "data": result}), 200
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformIdentityRuntimeUnavailable:
        return _unavailable()


@bp.get("/sessions")
def list_sessions():
    try:
        result = require_platform_identity_http_runtime().list_sessions(
            flask_request=request
        )
        return jsonify({"success": True, "data": result}), 200
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformIdentityRuntimeUnavailable:
        return _unavailable()


@bp.get("/tenants")
def list_tenants():
    try:
        result = require_platform_identity_http_runtime().list_tenants(
            flask_request=request,
            query_arguments=request.args,
        )
        return jsonify({"success": True, "data": result}), 200
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformIdentityRuntimeUnavailable:
        return _unavailable()


@bp.get("/tenants/<tenant_id>")
def get_tenant(tenant_id: str):
    try:
        result = require_platform_identity_http_runtime().get_tenant(
            flask_request=request,
            tenant_id=tenant_id,
        )
        return jsonify({"success": True, "data": result}), 200
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformIdentityRuntimeUnavailable:
        return _unavailable()


@bp.get("/tenants/<tenant_id>/read/rentals")
def list_tenant_rentals(tenant_id: str):
    try:
        result = require_platform_tenant_read_http_runtime().list_rentals(
            flask_request=request,
            tenant_id=tenant_id,
            query_arguments=request.args,
        )
        return jsonify({"success": True, "data": result}), 200
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformTenantReadRuntimeUnavailable:
        return _unavailable()


@bp.get("/tenants/<tenant_id>/read/devices")
def list_tenant_devices(tenant_id: str):
    try:
        result = require_platform_tenant_read_http_runtime().list_devices(
            flask_request=request,
            tenant_id=tenant_id,
            query_arguments=request.args,
        )
        return jsonify({"success": True, "data": result}), 200
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformTenantReadRuntimeUnavailable:
        return _unavailable()


@bp.get("/tenants/<tenant_id>/read/warehouses")
def list_tenant_warehouses(tenant_id: str):
    try:
        result = require_platform_tenant_read_http_runtime().list_warehouses(
            flask_request=request,
            tenant_id=tenant_id,
            query_arguments=request.args,
        )
        return jsonify({"success": True, "data": result}), 200
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformTenantReadRuntimeUnavailable:
        return _unavailable()


@bp.get(
    "/tenants/<tenant_id>/read/rentals/<rental_id>/customer-pii"
)
def get_tenant_rental_customer_pii(tenant_id: str, rental_id: str):
    try:
        result = (
            require_platform_tenant_read_http_runtime()
            .get_rental_customer_pii(
                flask_request=request,
                tenant_id=tenant_id,
                rental_id=rental_id,
                query_arguments=request.args,
            )
        )
        return jsonify({"success": True, "data": result}), 200
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformTenantReadRuntimeUnavailable:
        return _unavailable()


@bp.post("/sessions/<session_id>/revoke")
def revoke_session(session_id: str):
    try:
        result = require_platform_identity_http_runtime().revoke_session(
            flask_request=request,
            target_session_id=session_id,
        )
        response = jsonify({"success": True, "data": result})
        if result.get("current_session_revoked") is True:
            response = clear_platform_session_cookie(response)
        return response, 200
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformIdentityRuntimeUnavailable:
        return _unavailable()


@bp.post("/sessions/revoke-all")
def revoke_all_sessions():
    try:
        result = require_platform_identity_http_runtime().revoke_all_sessions(
            flask_request=request
        )
        response = jsonify({"success": True, "data": result})
        return clear_platform_session_cookie(response), 200
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformIdentityRuntimeUnavailable:
        return _unavailable()


@bp.post("/logout")
def logout():
    try:
        result = require_platform_identity_http_runtime().logout(
            flask_request=request
        )
        response = jsonify({"success": True, "data": result})
        return clear_platform_session_cookie(response), 200
    except PlatformHttpError as exc:
        return _platform_failure(exc)
    except PlatformIdentityRuntimeUnavailable:
        return _unavailable()


def _platform_failure(exc: PlatformHttpError):
    return jsonify(
        {
            "success": False,
            "message": exc.public_message,
            "data": {"code": exc.code},
        }
    ), exc.status_code


def _factor_failure(exc: PlatformStepUpHttpRejected):
    response, status = _platform_failure(exc)
    if exc.set_device_cookie:
        response = set_platform_device_cookie(
            response,
            exc.device_id,
            max_age_seconds=exc.device_cookie_max_age_seconds,
        )
    return response, status


def _credential_success(result):
    response = jsonify({"success": True, "data": result.data})
    if result.clear_session_cookie:
        response = clear_platform_session_cookie(response)
    if result.set_device_cookie:
        response = set_platform_device_cookie(
            response,
            result.device_id,
            max_age_seconds=result.device_cookie_max_age_seconds,
        )
    return response, 200


def _unavailable():
    return jsonify(
        {
            "success": False,
            "message": "平台身份服务尚未就绪",
        }
    ), 503


__all__ = ["bp"]
