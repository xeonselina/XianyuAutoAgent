"""Tenant-routed inspection HTTP endpoints."""

from flask import Blueprint, current_app, jsonify, request

from app.models.device import Device
from app.services.inspection.http_runtime import (
    InspectionIdInvalid,
    InspectionQueryInvalid,
    InspectionSaasHttpRuntimeUnavailable,
    require_inspection_saas_http_runtime,
)
from app.services.inspection.mutation_service import InspectionMutationError
from app.services.inspection_service import InspectionService
from inventory_control.tenant_http import TenantHttpError


inspection_bp = Blueprint("inspection", __name__, url_prefix="/api/inspections")


def _legacy_test_runtime_enabled() -> bool:
    return (
        current_app.testing is True
        and current_app.config.get(
            "ENABLE_LEGACY_SINGLE_TENANT_INSPECTION_API"
        )
        is True
    )


@inspection_bp.after_request
def protect_inspection_responses(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


def _runtime_failure(exc):
    if isinstance(exc, InspectionMutationError):
        return jsonify(
            {
                "success": False,
                "message": exc.public_message,
                "data": {"code": exc.code, **exc.data},
            }
        ), exc.status_code
    if isinstance(exc, (InspectionIdInvalid, InspectionQueryInvalid)):
        return jsonify({"success": False, "message": str(exc)}), 400
    if isinstance(exc, TenantHttpError):
        return jsonify(
            {
                "success": False,
                "message": exc.public_message,
                "data": {"code": exc.code},
            }
        ), exc.status_code
    return jsonify({"success": False, "message": "租户验货服务尚未就绪"}), 503


@inspection_bp.route("/rental/latest/<int:device_id>", methods=["GET"])
def get_latest_rental_by_device(device_id):
    if _legacy_test_runtime_enabled():
        return _legacy_latest_by_device_id(device_id)
    try:
        result = require_inspection_saas_http_runtime().latest_by_device_id(
            flask_request=request,
            device_id=device_id,
        )
        if result is None:
            return jsonify(
                {"success": False, "message": "未找到可验货的已寄回租赁记录"}
            ), 404
        return jsonify({"success": True, "data": result}), 200
    except (
        InspectionIdInvalid,
        TenantHttpError,
        InspectionSaasHttpRuntimeUnavailable,
    ) as exc:
        return _runtime_failure(exc)


@inspection_bp.route("/rental/latest/by-name/<device_name>", methods=["GET"])
def get_latest_rental_by_device_name(device_name):
    if _legacy_test_runtime_enabled():
        return _legacy_latest_by_device_name(device_name)
    try:
        result = require_inspection_saas_http_runtime().latest_by_device_name(
            flask_request=request,
            device_name=device_name,
        )
        if result is None:
            return jsonify(
                {"success": False, "message": "未找到可验货的已寄回租赁记录"}
            ), 404
        return jsonify({"success": True, "data": result}), 200
    except (
        InspectionQueryInvalid,
        TenantHttpError,
        InspectionSaasHttpRuntimeUnavailable,
    ) as exc:
        return _runtime_failure(exc)


@inspection_bp.route("", methods=["POST"])
def create_inspection():
    if _legacy_test_runtime_enabled():
        return _legacy_create()
    try:
        result = require_inspection_saas_http_runtime().create_inspection(
            flask_request=request,
            payload=request.get_json(silent=True),
        )
        return jsonify({"success": True, "data": result}), 201
    except (
        InspectionMutationError,
        TenantHttpError,
        InspectionSaasHttpRuntimeUnavailable,
    ) as exc:
        return _runtime_failure(exc)


@inspection_bp.route("/<int:inspection_id>", methods=["GET"])
def get_inspection(inspection_id):
    if _legacy_test_runtime_enabled():
        return _legacy_get(inspection_id)
    try:
        result = require_inspection_saas_http_runtime().get_inspection(
            flask_request=request,
            inspection_id=inspection_id,
        )
        if result is None:
            return jsonify({"success": False, "message": "验货记录不存在"}), 404
        return jsonify({"success": True, "data": result}), 200
    except (
        InspectionIdInvalid,
        TenantHttpError,
        InspectionSaasHttpRuntimeUnavailable,
    ) as exc:
        return _runtime_failure(exc)


@inspection_bp.route("/<int:inspection_id>", methods=["PUT"])
def update_inspection(inspection_id):
    if _legacy_test_runtime_enabled():
        return _legacy_update(inspection_id)
    try:
        result = require_inspection_saas_http_runtime().update_inspection(
            flask_request=request,
            inspection_id=inspection_id,
            payload=request.get_json(silent=True),
        )
        return jsonify({"success": True, "data": result}), 200
    except (
        InspectionIdInvalid,
        InspectionMutationError,
        TenantHttpError,
        InspectionSaasHttpRuntimeUnavailable,
    ) as exc:
        return _runtime_failure(exc)


@inspection_bp.route("", methods=["GET"])
def list_inspections():
    if _legacy_test_runtime_enabled():
        return _legacy_list()
    try:
        result = require_inspection_saas_http_runtime().list_inspections(
            flask_request=request,
            filters=request.args.to_dict(flat=True),
        )
        return jsonify({"success": True, "data": result}), 200
    except (
        InspectionQueryInvalid,
        TenantHttpError,
        InspectionSaasHttpRuntimeUnavailable,
    ) as exc:
        return _runtime_failure(exc)


def _legacy_latest_by_device_id(device_id):
    try:
        device = Device.query.get(device_id)
        if not device:
            return jsonify(
                {
                    "success": False,
                    "error": "Device not found",
                    "message": f"设备ID {device_id} 不存在",
                }
            ), 404
        rental = InspectionService.find_latest_rental_by_device_id(device_id)
        if not rental:
            return jsonify(
                {
                    "success": False,
                    "error": "No rental found",
                    "message": f"设备 {device.name} 未找到今天之前的租赁记录",
                }
            ), 404
        return jsonify(
            {
                "success": True,
                "data": {
                    "rental": rental.to_dict(),
                    "checklist": InspectionService.generate_checklist_for_rental(
                        rental.id
                    ),
                },
            }
        ), 200
    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
                "message": "获取租赁记录失败",
            }
        ), 500


def _legacy_latest_by_device_name(device_name):
    try:
        device = Device.query.filter_by(name=device_name).first()
        if not device:
            return jsonify(
                {
                    "success": False,
                    "error": "Device not found",
                    "message": f"设备名称 {device_name} 不存在",
                }
            ), 404
        return _legacy_latest_by_device_id(device.id)
    except Exception as exc:
        return jsonify(
            {
                "success": False,
                "error": str(exc),
                "message": "获取租赁记录失败",
            }
        ), 500


def _legacy_create():
    try:
        data = request.get_json()
        if not data or any(
            field not in data for field in ("rental_id", "device_id", "check_items")
        ):
            return jsonify(
                {
                    "success": False,
                    "error": "Missing required fields",
                    "message": "缺少必需字段：rental_id, device_id, check_items",
                }
            ), 400
        record = InspectionService.create_inspection_record(
            rental_id=data["rental_id"],
            device_id=data["device_id"],
            check_items=data["check_items"],
        )
        return jsonify({"success": True, "data": record.to_dict()}), 201
    except ValueError as exc:
        return jsonify(
            {"success": False, "error": str(exc), "message": "创建验货记录失败"}
        ), 400
    except Exception as exc:
        return jsonify(
            {"success": False, "error": str(exc), "message": "创建验货记录失败"}
        ), 500


def _legacy_get(inspection_id):
    try:
        record = InspectionService.get_inspection_record(inspection_id)
        if not record:
            return jsonify(
                {
                    "success": False,
                    "error": "Inspection record not found",
                    "message": f"验货记录 {inspection_id} 不存在",
                }
            ), 404
        return jsonify({"success": True, "data": record.to_dict()}), 200
    except Exception as exc:
        return jsonify(
            {"success": False, "error": str(exc), "message": "获取验货记录失败"}
        ), 500


def _legacy_update(inspection_id):
    try:
        data = request.get_json()
        if not data or "check_items" not in data:
            return jsonify(
                {
                    "success": False,
                    "error": "Missing required fields",
                    "message": "缺少必需字段：check_items",
                }
            ), 400
        record = InspectionService.update_inspection_record(
            inspection_id=inspection_id,
            check_items=data["check_items"],
        )
        return jsonify({"success": True, "data": record.to_dict()}), 200
    except ValueError as exc:
        return jsonify(
            {"success": False, "error": str(exc), "message": "更新验货记录失败"}
        ), 400
    except Exception as exc:
        return jsonify(
            {"success": False, "error": str(exc), "message": "更新验货记录失败"}
        ), 500


def _legacy_list():
    try:
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        if page < 1:
            page = 1
        if per_page < 1 or per_page > 100:
            per_page = 20
        result = InspectionService.get_inspection_records(
            device_name=request.args.get("device_name"),
            status=request.args.get("status"),
            page=page,
            per_page=per_page,
        )
        return jsonify({"success": True, "data": result}), 200
    except Exception as exc:
        return jsonify(
            {"success": False, "error": str(exc), "message": "获取验货记录列表失败"}
        ), 500
