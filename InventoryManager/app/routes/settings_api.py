"""Admin-only member and warehouse settings routes."""

from flask import Blueprint, current_app, g, request
from sqlalchemy.exc import DataError, IntegrityError

from app import db
from app.auth import require_role
from app.services.settings_service import (
    LastActiveAdminError,
    MemberPhoneConflictError,
    SettingsNotFoundError,
    SettingsService,
    SettingsValidationError,
)
from app.utils.response import created, error, success


bp = Blueprint("settings_api", __name__, url_prefix="/api/settings")


def _invalid(message):
    return error(
        message,
        status_code=400,
        code="INVALID_REQUEST",
    ).to_flask_response()


def _json_body(allowed_fields, *, require_nonempty=False):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise SettingsValidationError("请求体必须是 JSON 对象")
    unexpected = set(body) - set(allowed_fields)
    if unexpected:
        raise SettingsValidationError("请求包含不支持的字段")
    if require_nonempty and not body:
        raise SettingsValidationError("请求至少包含一个可更新字段")
    return body


def _service():
    return SettingsService(
        db.session,
        current_app.extensions["control_store"],
        g.tenant.id,
    )


def _handle_settings_error(exc):
    if isinstance(exc, SettingsValidationError):
        return _invalid(str(exc))
    if isinstance(exc, SettingsNotFoundError):
        return error(
            str(exc), status_code=404, code="NOT_FOUND"
        ).to_flask_response()
    if isinstance(exc, MemberPhoneConflictError):
        return error(
            "手机号已属于其他成员",
            status_code=409,
            code="PHONE_CONFLICT",
        ).to_flask_response()
    if isinstance(exc, LastActiveAdminError):
        return error(
            "必须保留至少一个启用的管理员",
            status_code=409,
            code="INVALID_REQUEST",
        ).to_flask_response()
    raise exc


def _handle_business_database_error(exc):
    db.session.rollback()
    if isinstance(exc, DataError):
        return error(
            "设置内容超出允许范围",
            status_code=400,
            code="INVALID_REQUEST",
        ).to_flask_response()
    return error(
        "设置保存冲突，请重试",
        status_code=409,
        code="INVALID_REQUEST",
    ).to_flask_response()


@bp.get("/members")
@require_role("admin")
def list_members():
    return success(data=_service().list_members()).to_flask_response()


@bp.post("/members")
@require_role("admin")
def create_member():
    try:
        body = _json_body({"phone", "role"})
        if "phone" not in body:
            raise SettingsValidationError("phone 不能为空")
        member = _service().create_member(
            body["phone"], body.get("role", "operator")
        )
        return created(data=member).to_flask_response()
    except (
        SettingsValidationError,
        MemberPhoneConflictError,
    ) as exc:
        return _handle_settings_error(exc)


@bp.patch("/members/<int:member_id>")
@require_role("admin")
def update_member(member_id):
    try:
        body = _json_body({"role", "status"}, require_nonempty=True)
        member = _service().update_member(member_id, body)
        return success(data=member).to_flask_response()
    except (
        SettingsValidationError,
        SettingsNotFoundError,
        LastActiveAdminError,
    ) as exc:
        return _handle_settings_error(exc)


@bp.get("/warehouses")
@require_role("admin")
def list_warehouses():
    return success(data=_service().list_warehouses()).to_flask_response()


@bp.post("/warehouses")
@require_role("admin")
def create_warehouse():
    try:
        body = _json_body({"province", "city", "name"})
        warehouse = _service().create_warehouse(
            body.get("province"), body.get("city"), body.get("name")
        )
        db.session.commit()
        return created(data=warehouse.to_settings_dict()).to_flask_response()
    except (SettingsValidationError, SettingsNotFoundError) as exc:
        db.session.rollback()
        return _handle_settings_error(exc)
    except (DataError, IntegrityError) as exc:
        return _handle_business_database_error(exc)


@bp.patch("/warehouses/<int:warehouse_id>")
@require_role("admin")
def update_warehouse(warehouse_id):
    try:
        body = _json_body(
            {"province", "city", "name"}, require_nonempty=True
        )
        warehouse = _service().update_warehouse(warehouse_id, body)
        db.session.commit()
        return success(data=warehouse.to_settings_dict()).to_flask_response()
    except (SettingsValidationError, SettingsNotFoundError) as exc:
        db.session.rollback()
        return _handle_settings_error(exc)
    except (DataError, IntegrityError) as exc:
        return _handle_business_database_error(exc)


@bp.put("/warehouses/<int:warehouse_id>/sf")
@require_role("admin")
def upsert_sf_config(warehouse_id):
    try:
        body = _json_body(
            {
                "partner_id",
                "checkword",
                "monthly_card",
                "test_mode",
                "sender_name",
                "sender_phone",
                "sender_address",
            }
        )
        config = _service().upsert_sf_config(warehouse_id, body)
        db.session.commit()
        return success(data=config.to_dict()).to_flask_response()
    except (SettingsValidationError, SettingsNotFoundError) as exc:
        db.session.rollback()
        return _handle_settings_error(exc)
    except (DataError, IntegrityError) as exc:
        return _handle_business_database_error(exc)


@bp.put("/warehouses/<int:warehouse_id>/kuaimai")
@require_role("admin")
def upsert_kuaimai_config(warehouse_id):
    try:
        body = _json_body({"app_id", "app_secret", "printer_sn"})
        config = _service().upsert_kuaimai_config(warehouse_id, body)
        db.session.commit()
        return success(data=config.to_dict()).to_flask_response()
    except (SettingsValidationError, SettingsNotFoundError) as exc:
        db.session.rollback()
        return _handle_settings_error(exc)
    except (DataError, IntegrityError) as exc:
        return _handle_business_database_error(exc)


_XIANYU_FIELDS = {"name", "app_key", "app_secret", "is_active"}


@bp.get("/xianyu-shops")
@require_role("admin")
def list_xianyu_shops():
    return success(data=_service().list_xianyu_shops()).to_flask_response()


@bp.post("/xianyu-shops")
@require_role("admin")
def create_xianyu_shop():
    try:
        shop = _service().create_xianyu_shop(_json_body(_XIANYU_FIELDS))
        db.session.commit()
        return created(data=shop.to_dict()).to_flask_response()
    except (SettingsValidationError, SettingsNotFoundError) as exc:
        db.session.rollback()
        return _handle_settings_error(exc)
    except (DataError, IntegrityError) as exc:
        return _handle_business_database_error(exc)


@bp.patch("/xianyu-shops/<int:shop_id>")
@require_role("admin")
def update_xianyu_shop(shop_id):
    try:
        shop = _service().update_xianyu_shop(
            shop_id, _json_body(_XIANYU_FIELDS, require_nonempty=True)
        )
        db.session.commit()
        return success(data=shop.to_dict()).to_flask_response()
    except (SettingsValidationError, SettingsNotFoundError) as exc:
        db.session.rollback()
        return _handle_settings_error(exc)
    except (DataError, IntegrityError) as exc:
        return _handle_business_database_error(exc)


@bp.post("/xianyu-shops/<int:shop_id>/sync")
@require_role("admin")
def sync_xianyu_shop(shop_id):
    from app.services.xianyu_order_reconciliation_service import (
        XianyuOrderReconciliationService, XianyuShopConfigIncompleteError,
    )
    try:
        return success(data=XianyuOrderReconciliationService().reconcile_shop(shop_id)).to_flask_response()
    except XianyuShopConfigIncompleteError:
        return error("闲鱼店铺不存在或已停用", status_code=409,
                     code="CONFIG_INCOMPLETE").to_flask_response()
