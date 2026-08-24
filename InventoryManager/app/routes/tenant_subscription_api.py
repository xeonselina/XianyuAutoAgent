"""Closed tenant subscription status and redemption endpoints."""

from flask import Blueprint, jsonify, request

from app.services.tenant_subscription import (
    TenantSubscriptionRuntimeUnavailable,
    require_tenant_subscription_http_runtime,
)
from inventory_control.tenant_http import TenantHttpError


bp = Blueprint(
    "tenant_subscription_api",
    __name__,
    url_prefix="/api/subscription",
)


@bp.after_request
def protect_subscription_responses(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@bp.get("/status")
def subscription_status():
    try:
        result = require_tenant_subscription_http_runtime().status(
            flask_request=request
        )
        return jsonify({"success": True, "data": result}), 200
    except TenantHttpError as exc:
        return _tenant_failure(exc)
    except TenantSubscriptionRuntimeUnavailable:
        return _unavailable()


@bp.post("/redeem")
def redeem_subscription():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    try:
        result = require_tenant_subscription_http_runtime().redeem(
            flask_request=request,
            raw_code=payload.get("code"),
            idempotency_key=payload.get("idempotency_key"),
            expected_subscription_row_version=payload.get(
                "expected_subscription_row_version"
            ),
        )
        return jsonify({"success": True, "data": result}), 200
    except TenantHttpError as exc:
        return _tenant_failure(exc)
    except TenantSubscriptionRuntimeUnavailable:
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
        "message": "租户订阅服务尚未就绪",
    }), 503


__all__ = ["bp"]
