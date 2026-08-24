"""Tenant integration metadata and write-only credential endpoints."""

from flask import Blueprint, jsonify, request

from app.services.tenant_integrations import (
    TenantIntegrationRuntimeUnavailable,
    TenantIntegrationSmsRateLimited,
    TenantProviderAccountRuntimeUnavailable,
    TenantProviderAccountSmsRateLimited,
    require_tenant_integration_http_runtime,
    require_tenant_provider_account_http_runtime,
)
from inventory_control.tenant_http import TenantHttpError


bp = Blueprint(
    "tenant_integration_api",
    __name__,
    url_prefix="/api/integrations",
)


@bp.after_request
def protect_integration_responses(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@bp.get("")
def list_integrations():
    return _run(
        lambda runtime, _payload: runtime.list_integrations(
            flask_request=request
        )
    )


@bp.post("")
def create_integration():
    return _run(
        lambda runtime, payload: runtime.create_integration(
            flask_request=request,
            payload=payload,
        ),
        success_status=201,
    )


@bp.post("/<integration_id>/credential-challenges")
def request_credential_challenge(integration_id: str):
    return _run(
        lambda runtime, payload: runtime.request_credential_challenge(
            flask_request=request,
            integration_id=integration_id,
            payload=payload,
        ),
        success_status=202,
    )


@bp.post("/<integration_id>/credential-confirm")
def confirm_credential_change(integration_id: str):
    return _run(
        lambda runtime, payload: runtime.confirm_credential_change(
            flask_request=request,
            integration_id=integration_id,
            payload=payload,
        )
    )


@bp.post("/sf/provider-accounts/bind-challenges")
def request_sf_account_bind_challenge():
    return _run_provider_account(
        lambda runtime, payload: runtime.request_bind_challenge(
            flask_request=request,
            payload=payload,
        ),
        success_status=202,
    )


@bp.get("/sf/provider-accounts")
def list_sf_provider_accounts():
    return _run_provider_account(
        lambda runtime, _payload: runtime.list_accounts(
            flask_request=request,
        )
    )


@bp.post("/sf/provider-accounts/bind-confirm")
def confirm_sf_account_bind():
    return _run_provider_account(
        lambda runtime, payload: runtime.confirm_bind(
            flask_request=request,
            payload=payload,
        )
    )


@bp.post("/sf/provider-accounts/unbind-challenges")
def request_sf_account_unbind_challenge():
    return _run_provider_account(
        lambda runtime, payload: runtime.request_unbind_challenge(
            flask_request=request,
            payload=payload,
        ),
        success_status=202,
    )


@bp.post("/sf/provider-accounts/unbind-confirm")
def confirm_sf_account_unbind():
    return _run_provider_account(
        lambda runtime, payload: runtime.confirm_unbind(
            flask_request=request,
            payload=payload,
        )
    )


def _run(operation, *, success_status: int = 200):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    try:
        result = operation(require_tenant_integration_http_runtime(), payload)
        return jsonify({"success": True, "data": result}), success_status
    except TenantIntegrationSmsRateLimited as exc:
        response, status = _tenant_failure(exc)
        response.headers["Retry-After"] = str(exc.retry_after_seconds)
        return response, status
    except TenantHttpError as exc:
        return _tenant_failure(exc)
    except TenantIntegrationRuntimeUnavailable:
        return jsonify({
            "success": False,
            "message": "租户集成服务尚未就绪",
        }), 503


def _tenant_failure(exc: TenantHttpError):
    return jsonify({
        "success": False,
        "message": exc.public_message,
        "data": {"code": exc.code},
    }), exc.status_code


def _run_provider_account(operation, *, success_status: int = 200):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    try:
        result = operation(
            require_tenant_provider_account_http_runtime(),
            payload,
        )
        return jsonify({"success": True, "data": result}), success_status
    except TenantProviderAccountSmsRateLimited as exc:
        response, status = _tenant_failure(exc)
        response.headers["Retry-After"] = str(exc.retry_after_seconds)
        return response, status
    except TenantHttpError as exc:
        return _tenant_failure(exc)
    except TenantProviderAccountRuntimeUnavailable:
        return jsonify({
            "success": False,
            "message": "顺丰账号服务尚未就绪",
        }), 503


__all__ = ["bp"]
