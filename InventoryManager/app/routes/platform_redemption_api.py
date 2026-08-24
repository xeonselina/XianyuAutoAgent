"""Platform redemption-code management routes."""

from flask import Blueprint, jsonify, request

from app.routes.platform_api_helpers import (
    platform_failure,
    platform_runtime_unavailable,
    strict_json_object,
)
from app.services.platform_redemption import (
    PlatformRedemptionHttpInvalid,
    PlatformRedemptionRuntimeUnavailable,
    require_platform_redemption_http_runtime,
)
from inventory_control.platform_http import PlatformHttpError


bp = Blueprint(
    "platform_redemption_api",
    __name__,
    url_prefix="/platform/api",
)

_LIST_KEYS = frozenset({"page", "page_size", "status"})
_GENERATE_KEYS = frozenset(
    {
        "generation_request_id",
        "name",
        "quantity",
        "service_duration_days",
        "redeem_before",
        "channel",
        "internal_note",
    }
)
_GENERATE_REQUIRED_KEYS = _GENERATE_KEYS - {"channel", "internal_note"}
_REVOKE_KEYS = frozenset({"expected_row_version", "reason_code"})


@bp.after_request
def protect_redemption_responses(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@bp.get("/redemption-codes")
def list_redemption_codes():
    if any(key not in _LIST_KEYS for key in request.args) or any(
        len(request.args.getlist(key)) != 1 for key in request.args
    ):
        return platform_failure(PlatformRedemptionHttpInvalid())
    try:
        result = require_platform_redemption_http_runtime().list_codes(
            flask_request=request,
            page=_query_integer("page", default=1),
            page_size=_query_integer("page_size", default=20),
            status=request.args.get("status"),
        )
        return jsonify({"success": True, "data": result}), 200
    except PlatformHttpError as exc:
        return platform_failure(exc)
    except PlatformRedemptionRuntimeUnavailable:
        return platform_runtime_unavailable("平台兑换码服务尚未就绪")


@bp.post("/redemption-code-batches")
def generate_redemption_code_batch():
    payload = strict_json_object(allowed_keys=_GENERATE_KEYS)
    if payload is None or not _GENERATE_REQUIRED_KEYS.issubset(payload):
        return platform_failure(PlatformRedemptionHttpInvalid())
    try:
        result = require_platform_redemption_http_runtime().generate_batch(
            flask_request=request,
            generation_request_id=payload["generation_request_id"],
            name=payload["name"],
            quantity=payload["quantity"],
            service_duration_days=payload["service_duration_days"],
            redeem_before=payload["redeem_before"],
            channel=payload.get("channel"),
            internal_note=payload.get("internal_note"),
        )
        return jsonify({"success": True, "data": result}), 201
    except PlatformHttpError as exc:
        return platform_failure(exc)
    except PlatformRedemptionRuntimeUnavailable:
        return platform_runtime_unavailable("平台兑换码服务尚未就绪")


@bp.post("/redemption-codes/<code_id>/reveal")
def reveal_redemption_code(code_id: str):
    payload = strict_json_object(allowed_keys=frozenset())
    if payload != {}:
        return platform_failure(PlatformRedemptionHttpInvalid())
    try:
        result = require_platform_redemption_http_runtime().reveal_code(
            flask_request=request,
            code_id=code_id,
        )
        return jsonify({"success": True, "data": result}), 200
    except PlatformHttpError as exc:
        return platform_failure(exc)
    except PlatformRedemptionRuntimeUnavailable:
        return platform_runtime_unavailable("平台兑换码服务尚未就绪")


@bp.post("/redemption-codes/<code_id>/revoke")
def revoke_redemption_code(code_id: str):
    payload = strict_json_object(allowed_keys=_REVOKE_KEYS)
    if payload is None or set(payload) != _REVOKE_KEYS:
        return platform_failure(PlatformRedemptionHttpInvalid())
    try:
        result = require_platform_redemption_http_runtime().revoke_code(
            flask_request=request,
            code_id=code_id,
            expected_row_version=payload["expected_row_version"],
            reason_code=payload["reason_code"],
        )
        return jsonify({"success": True, "data": result}), 200
    except PlatformHttpError as exc:
        return platform_failure(exc)
    except PlatformRedemptionRuntimeUnavailable:
        return platform_runtime_unavailable("平台兑换码服务尚未就绪")


def _query_integer(name: str, *, default: int) -> int | object:
    value = request.args.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


__all__ = ["bp"]
