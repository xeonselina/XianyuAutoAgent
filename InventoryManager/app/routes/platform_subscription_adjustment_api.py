"""Platform service-period preview and fresh-factor commit routes."""

from flask import Blueprint, jsonify, request

from app.routes.platform_api_helpers import (
    platform_failure,
    platform_runtime_unavailable,
    strict_json_object,
)
from app.services.platform_subscription_adjustment import (
    PlatformSubscriptionAdjustmentHttpInvalid,
    PlatformSubscriptionAdjustmentRuntimeUnavailable,
    require_platform_subscription_adjustment_http_runtime,
)
from inventory_control.platform_http import PlatformHttpError


bp = Blueprint(
    "platform_subscription_adjustment_api",
    __name__,
    url_prefix="/platform/api",
)

_PREVIEW_KEYS = frozenset(
    {
        "operation",
        "days",
        "reason_code",
        "note",
        "offline_reference",
        "idempotency_key",
    }
)
_COMMIT_KEYS = _PREVIEW_KEYS | frozenset(
    {
        "action_id",
        "expected_subscription_row_version",
        "confirmation_token",
        "factor_method",
        "factor",
    }
)


@bp.after_request
def protect_adjustment_responses(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@bp.post("/tenants/<tenant_id>/subscription-adjustments/preview")
def preview_subscription_adjustment(tenant_id: str):
    payload = strict_json_object(allowed_keys=_PREVIEW_KEYS)
    if payload is None:
        return platform_failure(PlatformSubscriptionAdjustmentHttpInvalid())
    try:
        result = require_platform_subscription_adjustment_http_runtime().preview(
            flask_request=request,
            tenant_id=tenant_id,
            operation=payload.get("operation"),
            days=payload.get("days"),
            reason_code=payload.get("reason_code"),
            note=payload.get("note"),
            offline_reference=payload.get("offline_reference"),
            idempotency_key=payload.get("idempotency_key"),
        )
        return jsonify({"success": True, "data": result}), 200
    except PlatformHttpError as exc:
        return platform_failure(exc)
    except PlatformSubscriptionAdjustmentRuntimeUnavailable:
        return platform_runtime_unavailable(
            "平台服务期调整服务尚未就绪"
        )


@bp.post("/tenants/<tenant_id>/subscription-adjustments")
def commit_subscription_adjustment(tenant_id: str):
    payload = strict_json_object(allowed_keys=_COMMIT_KEYS)
    if payload is None:
        return platform_failure(PlatformSubscriptionAdjustmentHttpInvalid())
    try:
        result = require_platform_subscription_adjustment_http_runtime().commit(
            flask_request=request,
            tenant_id=tenant_id,
            operation=payload.get("operation"),
            days=payload.get("days"),
            reason_code=payload.get("reason_code"),
            note=payload.get("note"),
            offline_reference=payload.get("offline_reference"),
            idempotency_key=payload.get("idempotency_key"),
            action_id=payload.get("action_id"),
            expected_subscription_row_version=payload.get(
                "expected_subscription_row_version"
            ),
            confirmation_token=payload.get("confirmation_token"),
            factor_method=payload.get("factor_method"),
            factor_value=payload.get("factor"),
        )
        return jsonify({"success": True, "data": result}), 200
    except PlatformHttpError as exc:
        return platform_failure(exc)
    except PlatformSubscriptionAdjustmentRuntimeUnavailable:
        return platform_runtime_unavailable(
            "平台服务期调整服务尚未就绪"
        )


__all__ = ["bp"]
