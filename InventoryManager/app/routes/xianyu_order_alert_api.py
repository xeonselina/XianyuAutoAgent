"""Tenant-routed Xianyu alert summary and durable refresh endpoints."""

from flask import Blueprint, current_app, jsonify, request

from app.services.xianyu_sync import (
    XianyuSyncHttpError,
    require_xianyu_sync_http_runtime,
)
from app.utils.response import handle_response
from inventory_control.tenant_http import TenantHttpError


bp = Blueprint("xianyu_order_alert_api", __name__)


def _legacy_test_runtime_enabled() -> bool:
    return (
        current_app.testing is True
        and current_app.config.get(
            "ENABLE_LEGACY_SINGLE_TENANT_XIANYU_ALERT_API"
        )
        is True
    )


@bp.after_request
def protect_xianyu_responses(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@bp.get("/api/xianyu-order-alerts")
@handle_response
def get_alerts():
    if _legacy_test_runtime_enabled():
        return _legacy_alert_handlers().get_alerts()
    try:
        result = require_xianyu_sync_http_runtime().get_alerts(
            flask_request=request
        )
        return jsonify({"success": True, "data": result}), 200
    except _PUBLIC_ERRORS as exc:
        return _failure(exc)


@bp.post("/api/xianyu-order-alerts/refresh")
@handle_response
def refresh_alerts():
    if _legacy_test_runtime_enabled():
        return _legacy_alert_handlers().refresh_alerts()
    try:
        result = require_xianyu_sync_http_runtime().refresh_alerts(
            flask_request=request
        )
        return jsonify({"success": True, "data": result}), 202
    except _PUBLIC_ERRORS as exc:
        return _failure(exc)


@bp.post("/api/xianyu-order-alerts/<order_no>/ignore")
@handle_response
def ignore_alert(order_no):
    if _legacy_test_runtime_enabled():
        return _legacy_alert_handlers().ignore_alert(order_no)
    try:
        result = require_xianyu_sync_http_runtime().ignore_alert(
            flask_request=request,
            order_no=order_no,
            payload=request.get_json(silent=True),
        )
        return jsonify(
            {
                "success": True,
                "message": "订单已永久忽略",
                "data": result,
            }
        ), 200
    except _PUBLIC_ERRORS as exc:
        return _failure(exc)


_PUBLIC_ERRORS = (TenantHttpError, XianyuSyncHttpError)


def _legacy_alert_handlers():
    """Import the environment-era test adapter only inside an opted-in test."""

    from app.handlers.xianyu_order_alert_handlers import (
        XianyuOrderAlertHandlers,
    )

    return XianyuOrderAlertHandlers


def _failure(exc):
    return jsonify(
        {
            "success": False,
            "message": exc.public_message,
            "data": {"code": exc.code},
        }
    ), exc.status_code


__all__ = ["bp"]
