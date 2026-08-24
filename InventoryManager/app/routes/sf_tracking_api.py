"""Tenant-routed, fail-closed SF shipment tracking endpoints."""

from flask import Blueprint, jsonify, request

from app.services.shipping import (
    SfTrackingHttpRuntimeUnavailable,
    SfTrackingProviderUnavailable,
    SfTrackingQueryRejected,
    SfTrackingRequestInvalid,
    require_sf_tracking_http_runtime,
)
from inventory_control.tenant_http import TenantHttpError


bp = Blueprint("sf_tracking", __name__, url_prefix="/api/sf-tracking")


@bp.after_request
def protect_tracking_responses(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@bp.get("/list")
def list_shipments():
    try:
        result = require_sf_tracking_http_runtime().list_shipments(
            flask_request=request,
            page_size=request.args.get("page_size"),
            after_cursor=request.args.get("after_cursor"),
        )
        return jsonify({"success": True, "data": result}), 200
    except _PUBLIC_ERRORS as exc:
        return _failure(exc)


@bp.post("/query")
def query_shipment():
    try:
        result = require_sf_tracking_http_runtime().query_shipment(
            flask_request=request,
            payload=request.get_json(silent=True),
        )
        return jsonify({"success": True, "data": result}), 200
    except _PUBLIC_ERRORS as exc:
        return _failure(exc)


@bp.post("/batch-query")
def query_shipments():
    try:
        result = require_sf_tracking_http_runtime().query_shipments(
            flask_request=request,
            payload=request.get_json(silent=True),
        )
        return jsonify({"success": True, "data": result}), 200
    except _PUBLIC_ERRORS as exc:
        return _failure(exc)


_PUBLIC_ERRORS = (
    TenantHttpError,
    SfTrackingHttpRuntimeUnavailable,
    SfTrackingProviderUnavailable,
    SfTrackingQueryRejected,
    SfTrackingRequestInvalid,
)


def _failure(exc):
    return jsonify(
        {
            "success": False,
            "message": exc.public_message,
            "data": {"code": exc.code},
        }
    ), exc.status_code


__all__ = ["bp"]
