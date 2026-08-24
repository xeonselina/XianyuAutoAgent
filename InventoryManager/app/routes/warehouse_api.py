"""Tenant-routed warehouse and explicit device-move endpoints."""

from flask import Blueprint, jsonify, request

from app.services.warehouse import (
    WarehouseMutationError,
    WarehouseRequestInvalid,
    WarehouseSaasHttpRuntimeUnavailable,
    require_warehouse_saas_http_runtime,
)
from inventory_control.tenant_http import TenantHttpError


bp = Blueprint("warehouse_api", __name__, url_prefix="/api/warehouses")


@bp.after_request
def protect_warehouse_responses(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@bp.route("", methods=["GET"])
def list_warehouses():
    try:
        result = require_warehouse_saas_http_runtime().list_warehouses(
            flask_request=request
        )
        return jsonify({"success": True, "data": list(result)}), 200
    except (
        TenantHttpError,
        WarehouseSaasHttpRuntimeUnavailable,
    ) as exc:
        return _failure(exc)


@bp.route("/setup", methods=["GET"])
def get_default_warehouse_setup():
    try:
        result = require_warehouse_saas_http_runtime().get_default_setup(
            flask_request=request
        )
        return jsonify({"success": True, "data": result}), 200
    except (
        TenantHttpError,
        WarehouseMutationError,
        WarehouseSaasHttpRuntimeUnavailable,
    ) as exc:
        return _failure(exc)


@bp.route("/setup", methods=["PUT"])
def setup_default_warehouse():
    try:
        result = (
            require_warehouse_saas_http_runtime().setup_default_warehouse(
                flask_request=request,
                payload=request.get_json(silent=True),
            )
        )
        return jsonify({"success": True, "data": result}), 200
    except (
        TenantHttpError,
        WarehouseMutationError,
        WarehouseRequestInvalid,
        WarehouseSaasHttpRuntimeUnavailable,
    ) as exc:
        return _failure(exc)


@bp.route("", methods=["POST"])
def create_warehouse():
    try:
        result = require_warehouse_saas_http_runtime().create_warehouse(
            flask_request=request,
            payload=request.get_json(silent=True),
        )
        return jsonify({"success": True, "data": result}), 201
    except (
        TenantHttpError,
        WarehouseMutationError,
        WarehouseRequestInvalid,
        WarehouseSaasHttpRuntimeUnavailable,
    ) as exc:
        return _failure(exc)


@bp.route("/<int:warehouse_id>", methods=["PUT"])
def update_warehouse(warehouse_id):
    try:
        result = require_warehouse_saas_http_runtime().update_warehouse(
            flask_request=request,
            warehouse_id=warehouse_id,
            payload=request.get_json(silent=True),
        )
        return jsonify({"success": True, "data": result}), 200
    except (
        TenantHttpError,
        WarehouseMutationError,
        WarehouseRequestInvalid,
        WarehouseSaasHttpRuntimeUnavailable,
    ) as exc:
        return _failure(exc)


@bp.route("/<int:warehouse_id>/default", methods=["POST"])
def set_default_warehouse(warehouse_id):
    try:
        result = require_warehouse_saas_http_runtime().set_default_warehouse(
            flask_request=request,
            warehouse_id=warehouse_id,
        )
        return jsonify({"success": True, "data": result}), 200
    except (
        TenantHttpError,
        WarehouseMutationError,
        WarehouseRequestInvalid,
        WarehouseSaasHttpRuntimeUnavailable,
    ) as exc:
        return _failure(exc)


@bp.route("/<int:warehouse_id>/deactivate", methods=["POST"])
def deactivate_warehouse(warehouse_id):
    try:
        result = require_warehouse_saas_http_runtime().deactivate_warehouse(
            flask_request=request,
            warehouse_id=warehouse_id,
        )
        return jsonify({"success": True, "data": result}), 200
    except (
        TenantHttpError,
        WarehouseMutationError,
        WarehouseRequestInvalid,
        WarehouseSaasHttpRuntimeUnavailable,
    ) as exc:
        return _failure(exc)


@bp.route("/preferences/<scene>", methods=["PUT"])
def set_user_warehouse_preference(scene):
    try:
        result = require_warehouse_saas_http_runtime().set_user_preference(
            flask_request=request,
            scene=scene,
            payload=request.get_json(silent=True),
        )
        return jsonify({"success": True, "data": result}), 200
    except (
        TenantHttpError,
        WarehouseMutationError,
        WarehouseRequestInvalid,
        WarehouseSaasHttpRuntimeUnavailable,
    ) as exc:
        return _failure(exc)


@bp.route("/preferences", methods=["GET"])
def get_user_warehouse_preferences():
    try:
        result = require_warehouse_saas_http_runtime().get_user_preferences(
            flask_request=request
        )
        return jsonify({"success": True, "data": result}), 200
    except (
        TenantHttpError,
        WarehouseMutationError,
        WarehouseSaasHttpRuntimeUnavailable,
    ) as exc:
        return _failure(exc)


@bp.route("/devices", methods=["GET"])
def list_main_devices():
    try:
        result = require_warehouse_saas_http_runtime().list_main_devices(
            flask_request=request
        )
        return jsonify({"success": True, "data": list(result)}), 200
    except (
        TenantHttpError,
        WarehouseSaasHttpRuntimeUnavailable,
    ) as exc:
        return _failure(exc)


@bp.route("/device-models", methods=["GET"])
def list_main_device_models():
    try:
        result = require_warehouse_saas_http_runtime().list_main_device_models(
            flask_request=request
        )
        return jsonify({"success": True, "data": list(result)}), 200
    except (
        TenantHttpError,
        WarehouseSaasHttpRuntimeUnavailable,
    ) as exc:
        return _failure(exc)


@bp.route("/devices", methods=["POST"])
def create_main_device():
    try:
        result = require_warehouse_saas_http_runtime().create_main_device(
            flask_request=request,
            payload=request.get_json(silent=True),
        )
        return jsonify({"success": True, "data": result}), 201
    except (
        TenantHttpError,
        WarehouseMutationError,
        WarehouseRequestInvalid,
        WarehouseSaasHttpRuntimeUnavailable,
    ) as exc:
        return _failure(exc)


@bp.route("/device-moves/preview", methods=["POST"])
def preview_device_move():
    try:
        result = require_warehouse_saas_http_runtime().preview_device_move(
            flask_request=request,
            payload=request.get_json(silent=True),
        )
        return jsonify({"success": True, "data": result}), 200
    except (
        TenantHttpError,
        WarehouseMutationError,
        WarehouseRequestInvalid,
        WarehouseSaasHttpRuntimeUnavailable,
    ) as exc:
        return _failure(exc)


@bp.route("/device-moves/confirm", methods=["POST"])
def confirm_device_move():
    try:
        result = require_warehouse_saas_http_runtime().confirm_device_move(
            flask_request=request,
            payload=request.get_json(silent=True),
        )
        return jsonify({"success": True, "data": result}), 200
    except (
        TenantHttpError,
        WarehouseMutationError,
        WarehouseRequestInvalid,
        WarehouseSaasHttpRuntimeUnavailable,
    ) as exc:
        return _failure(exc)


def _failure(exc):
    if isinstance(exc, WarehouseMutationError):
        return jsonify(
            {
                "success": False,
                "message": exc.public_message,
                "data": {"code": exc.code},
            }
        ), exc.status_code
    if isinstance(exc, WarehouseRequestInvalid):
        return jsonify(
            {
                "success": False,
                "message": exc.public_message,
                "data": {"code": exc.code},
            }
        ), exc.status_code
    if isinstance(exc, TenantHttpError):
        return jsonify(
            {
                "success": False,
                "message": exc.public_message,
                "data": {"code": exc.code},
            }
        ), exc.status_code
    return jsonify(
        {"success": False, "message": "租户仓库服务尚未就绪"}
    ), 503


__all__ = ["bp"]
