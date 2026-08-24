"""Explicit tenant member and warehouse settings operations."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth import normalize_china_phone
from app.control.models import TenantMember
from app.models.warehouse import (
    Warehouse,
    WarehouseKuaimaiConfig,
    WarehouseSFConfig,
)


SF_CHECKWORD_PURPOSE = "warehouse-sf-checkword"
SF_MONTHLY_CARD_PURPOSE = "warehouse-sf-monthly-card"
KUAIMAI_SECRET_PURPOSE = "warehouse-kuaimai-app-secret"


class SettingsValidationError(ValueError):
    pass


class SettingsNotFoundError(LookupError):
    pass


class MemberPhoneConflictError(RuntimeError):
    pass


class LastActiveAdminError(RuntimeError):
    pass


def member_to_dict(member):
    return {
        "id": member.id,
        "phone": member.phone,
        "role": member.role,
        "status": member.status,
    }


def _required_text(value, field, maximum):
    if not isinstance(value, str) or not value.strip():
        raise SettingsValidationError(f"{field} 不能为空")
    value = value.strip()
    if len(value) > maximum:
        raise SettingsValidationError(f"{field} 过长")
    return value


def _optional_text(value, field, maximum):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise SettingsValidationError(f"{field} 必须是字符串")
    value = value.strip()
    if not value:
        return None
    if len(value) > maximum:
        raise SettingsValidationError(f"{field} 过长")
    return value


class SettingsService:
    def __init__(self, business_session, control_store, tenant_id):
        self.business_session = business_session
        self.control_store = control_store
        self.tenant_id = tenant_id
        self.secret_box = control_store.secret_box

    def list_members(self):
        with self.control_store.session() as session:
            members = session.scalars(
                select(TenantMember)
                .where(TenantMember.tenant_id == self.tenant_id)
                .order_by(TenantMember.id)
            ).all()
            return [member_to_dict(member) for member in members]

    def create_member(self, phone, role="operator"):
        try:
            normalized_phone = normalize_china_phone(phone)
        except ValueError as exc:
            raise SettingsValidationError("请输入有效的大陆手机号") from exc
        if not isinstance(role, str) or role not in {"admin", "operator"}:
            raise SettingsValidationError("role 必须是 admin 或 operator")
        try:
            with self.control_store.tenant_members_locked_session(
                self.tenant_id
            ) as (session, _members):
                member = TenantMember(
                    tenant_id=self.tenant_id,
                    phone=normalized_phone,
                    role=role,
                    status="active",
                )
                session.add(member)
                session.flush()
                result = member_to_dict(member)
            return result
        except IntegrityError as exc:
            raise MemberPhoneConflictError from exc

    def update_member(self, member_id, payload):
        role = payload.get("role")
        status = payload.get("status")
        if role is not None and (
            not isinstance(role, str)
            or role not in {"admin", "operator"}
        ):
            raise SettingsValidationError("role 必须是 admin 或 operator")
        if status is not None and (
            not isinstance(status, str)
            or status not in {"active", "disabled"}
        ):
            raise SettingsValidationError(
                "status 必须是 active 或 disabled"
            )

        with self.control_store.tenant_members_locked_session(
            self.tenant_id
        ) as (_session, members):
            member = next(
                (
                    candidate
                    for candidate in members
                    if candidate.id == member_id
                ),
                None,
            )
            if member is None:
                raise SettingsNotFoundError("成员不存在")
            next_role = role if role is not None else member.role
            next_status = status if status is not None else member.status
            removes_active_admin = (
                member.role == "admin"
                and member.status == "active"
                and (
                    next_role != "admin"
                    or next_status != "active"
                )
            )
            if removes_active_admin:
                active_admin_count = sum(
                    candidate.role == "admin"
                    and candidate.status == "active"
                    for candidate in members
                )
                if active_admin_count <= 1:
                    raise LastActiveAdminError
            member.role = next_role
            member.status = next_status
            return member_to_dict(member)

    def list_warehouses(self):
        warehouses = self.business_session.scalars(
            select(Warehouse).order_by(Warehouse.id)
        ).all()
        return [warehouse.to_settings_dict() for warehouse in warehouses]

    def create_warehouse(self, province, city, name=None):
        province = _required_text(province, "province", 64)
        city = _required_text(city, "city", 64)
        if name is None or (isinstance(name, str) and not name.strip()):
            name = f"{province}{city}仓库"
        else:
            name = _required_text(name, "name", 100)
        warehouse = Warehouse(province=province, city=city, name=name)
        self.business_session.add(warehouse)
        self.business_session.flush()
        return warehouse

    def update_warehouse(self, warehouse_id, payload):
        warehouse = self.business_session.get(Warehouse, warehouse_id)
        if warehouse is None:
            raise SettingsNotFoundError("仓库不存在")
        old_default_name = (
            f"{warehouse.province}{warehouse.city}仓库"
        )
        province = (
            _required_text(payload["province"], "province", 64)
            if "province" in payload
            else warehouse.province
        )
        city = (
            _required_text(payload["city"], "city", 64)
            if "city" in payload
            else warehouse.city
        )
        if "name" in payload:
            raw_name = payload["name"]
            if raw_name is None or (
                isinstance(raw_name, str) and not raw_name.strip()
            ):
                name = f"{province}{city}仓库"
            else:
                name = _required_text(raw_name, "name", 100)
        elif warehouse.name == old_default_name:
            name = f"{province}{city}仓库"
        else:
            name = warehouse.name
        warehouse.province = province
        warehouse.city = city
        warehouse.name = name
        self.business_session.flush()
        return warehouse

    def upsert_sf_config(self, warehouse_id, payload, secret_box=None):
        warehouse = self.business_session.get(Warehouse, warehouse_id)
        if warehouse is None:
            raise SettingsNotFoundError("仓库不存在")
        config = self.business_session.get(
            WarehouseSFConfig, warehouse_id
        )
        if config is None:
            config = WarehouseSFConfig(warehouse_id=warehouse_id)
            self.business_session.add(config)
        for field, maximum in (
            ("partner_id", 100),
            ("sender_name", 100),
            ("sender_phone", 30),
            ("sender_address", 500),
        ):
            if field in payload:
                setattr(
                    config,
                    field,
                    _optional_text(payload[field], field, maximum),
                )
        if "test_mode" in payload:
            if not isinstance(payload["test_mode"], bool):
                raise SettingsValidationError("test_mode 必须是布尔值")
            config.test_mode = payload["test_mode"]
        box = secret_box or self.secret_box
        for request_field, model_field, purpose in (
            ("checkword", "checkword_ciphertext", SF_CHECKWORD_PURPOSE),
            (
                "monthly_card",
                "monthly_card_ciphertext",
                SF_MONTHLY_CARD_PURPOSE,
            ),
        ):
            value = payload.get(request_field)
            if value not in (None, ""):
                if not isinstance(value, str):
                    raise SettingsValidationError(
                        f"{request_field} 必须是字符串"
                    )
                setattr(
                    config,
                    model_field,
                    box.encrypt(value, purpose=purpose),
                )
        self.business_session.flush()
        return config

    def upsert_kuaimai_config(
        self, warehouse_id, payload, secret_box=None
    ):
        warehouse = self.business_session.get(Warehouse, warehouse_id)
        if warehouse is None:
            raise SettingsNotFoundError("仓库不存在")
        config = self.business_session.get(
            WarehouseKuaimaiConfig, warehouse_id
        )
        if config is None:
            config = WarehouseKuaimaiConfig(warehouse_id=warehouse_id)
            self.business_session.add(config)
        for field, maximum in (("app_id", 100), ("printer_sn", 100)):
            if field in payload:
                setattr(
                    config,
                    field,
                    _optional_text(payload[field], field, maximum),
                )
        secret = payload.get("app_secret")
        if secret not in (None, ""):
            if not isinstance(secret, str):
                raise SettingsValidationError(
                    "app_secret 必须是字符串"
                )
            box = secret_box or self.secret_box
            config.app_secret_ciphertext = box.encrypt(
                secret,
                purpose=KUAIMAI_SECRET_PURPOSE,
            )
        self.business_session.flush()
        return config
