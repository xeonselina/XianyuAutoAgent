"""Tenant browser-session status and logout endpoints."""

from flask import Blueprint, jsonify, request

from app.services.tenant_identity import (
    TenantIdentityRuntimeUnavailable,
    TenantSmsRateLimited,
    require_tenant_identity_http_runtime,
)
from inventory_control.tenant_http import (
    TenantHttpError,
    clear_tenant_session_cookie,
    set_tenant_session_cookie,
)


bp = Blueprint("tenant_identity_api", __name__, url_prefix="/api/auth")


@bp.after_request
def protect_identity_responses(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@bp.get("/session")
def session_status():
    try:
        result = require_tenant_identity_http_runtime().session_status(
            flask_request=request
        )
        return jsonify({"success": True, "data": result}), 200
    except TenantHttpError as exc:
        return _tenant_failure(exc)
    except TenantIdentityRuntimeUnavailable:
        return _unavailable()


@bp.post("/login/challenges")
def request_login_code():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    try:
        result = require_tenant_identity_http_runtime().request_login_code(
            flask_request=request,
            raw_phone=payload.get("phone"),
        )
        return jsonify({
            "success": True,
            "message": "如该号码可登录，验证码将由平台短信发送。",
            "data": result,
        }), 202
    except TenantSmsRateLimited as exc:
        response, status = _tenant_failure(exc)
        response.headers["Retry-After"] = str(exc.retry_after_seconds)
        return response, status
    except TenantHttpError as exc:
        return _tenant_failure(exc)
    except TenantIdentityRuntimeUnavailable:
        return _unavailable()


@bp.post("/login/verify")
def verify_login_code():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    try:
        issued = require_tenant_identity_http_runtime().complete_login(
            flask_request=request,
            raw_phone=payload.get("phone"),
            challenge_id=payload.get("challenge_id"),
            plaintext_code=payload.get("code"),
            device_name=payload.get("device_name"),
        )
        response = jsonify({
            "success": True,
            "data": {
                "csrf_token": issued.csrf_token,
                "session_id": issued.auth.session_id,
                "tenant_id": issued.auth.tenant_id,
                "role": issued.auth.role.value,
                "effective_gate": issued.auth.effective_gate.value,
                "tenant_timezone": issued.auth.tenant_timezone,
            },
        })
        return set_tenant_session_cookie(
            response,
            issued.session_token,
        ), 200
    except TenantHttpError as exc:
        return _tenant_failure(exc)
    except TenantIdentityRuntimeUnavailable:
        return _unavailable()


@bp.post("/logout")
def logout():
    try:
        result = require_tenant_identity_http_runtime().logout(
            flask_request=request
        )
        response = jsonify({"success": True, "data": result})
        return clear_tenant_session_cookie(response), 200
    except TenantHttpError as exc:
        return _tenant_failure(exc)
    except TenantIdentityRuntimeUnavailable:
        return _unavailable()


@bp.get("/sessions")
def list_sessions():
    try:
        result = require_tenant_identity_http_runtime().list_sessions(
            flask_request=request
        )
        return jsonify({"success": True, "data": result}), 200
    except TenantHttpError as exc:
        return _tenant_failure(exc)
    except TenantIdentityRuntimeUnavailable:
        return _unavailable()


@bp.post("/sessions/<session_id>/revoke")
def revoke_session(session_id: str):
    try:
        result = require_tenant_identity_http_runtime().revoke_session(
            flask_request=request,
            target_session_id=session_id,
        )
        response = jsonify({"success": True, "data": result})
        if result.get("current_session_revoked") is True:
            response = clear_tenant_session_cookie(response)
        return response, 200
    except TenantHttpError as exc:
        return _tenant_failure(exc)
    except TenantIdentityRuntimeUnavailable:
        return _unavailable()


@bp.post("/sessions/revoke-all")
def revoke_all_sessions():
    try:
        result = require_tenant_identity_http_runtime().revoke_all_sessions(
            flask_request=request
        )
        response = jsonify({"success": True, "data": result})
        return clear_tenant_session_cookie(response), 200
    except TenantHttpError as exc:
        return _tenant_failure(exc)
    except TenantIdentityRuntimeUnavailable:
        return _unavailable()


@bp.post("/phone-change/challenges")
def request_phone_change_challenges():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    try:
        result = (
            require_tenant_identity_http_runtime()
            .request_phone_change_challenges(
                flask_request=request,
                raw_new_phone=payload.get("new_phone"),
                action_id=payload.get("action_id"),
            )
        )
        return jsonify({"success": True, "data": result}), 202
    except TenantSmsRateLimited as exc:
        response, status = _tenant_failure(exc)
        response.headers["Retry-After"] = str(exc.retry_after_seconds)
        return response, status
    except TenantHttpError as exc:
        return _tenant_failure(exc)
    except TenantIdentityRuntimeUnavailable:
        return _unavailable()


@bp.post("/phone-change/confirm")
def confirm_phone_change():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    try:
        result = require_tenant_identity_http_runtime().confirm_phone_change(
            flask_request=request,
            raw_new_phone=payload.get("new_phone"),
            action_id=payload.get("action_id"),
            old_challenge_id=payload.get("old_challenge_id"),
            old_plaintext_code=payload.get("old_code"),
            new_challenge_id=payload.get("new_challenge_id"),
            new_plaintext_code=payload.get("new_code"),
        )
        response = jsonify({"success": True, "data": result})
        return clear_tenant_session_cookie(response), 200
    except TenantHttpError as exc:
        return _tenant_failure(exc)
    except TenantIdentityRuntimeUnavailable:
        return _unavailable()


def _tenant_failure(exc: TenantHttpError):
    return jsonify({
        "success": False,
        "message": exc.public_message,
        "data": {"code": exc.code},
    }), exc.status_code


def _unavailable():
    return jsonify({
        "success": False,
        "message": "租户会话服务尚未就绪",
    }), 503


__all__ = ["bp"]
