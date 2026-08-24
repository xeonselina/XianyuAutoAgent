from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from uuid import uuid4

from flask import request
from sqlalchemy.orm import Session

from app import create_app, db
from app.models.accessory_inventory import (
    AccessoryType,
    AccessoryUnit,
    AccessoryUnitEvent,
    RentalAccessoryRequest,
    RentalAccessoryUnitLink,
)
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental
from app.models.warehouse import DeviceWarehouseMovement, Warehouse
from app.services.tenant_business import TenantBusinessRequestScope
from app.services.warehouse.http_runtime import (
    SqlAlchemyWarehouseSaasHttpRuntime,
)
from inventory_control.domain import EffectiveTenantGate, TenantRole
from inventory_control.domain.rbac import Capability
from inventory_control.tenant_http import AuthContext


def _auth_context() -> AuthContext:
    return AuthContext(
        session_id=str(uuid4()),
        user_id=str(uuid4()),
        membership_id=str(uuid4()),
        tenant_id=str(uuid4()),
        role=TenantRole.ADMIN,
        user_auth_version=1,
        tenant_access_version=1,
        tenant_timezone="Asia/Shanghai",
        effective_gate=EffectiveTenantGate.ACTIVE,
    )


class _ExplicitTenantRuntime:
    def __init__(self, engine):
        self.engine = engine
        self.auth_context = _auth_context()
        self.calls: list[dict[str, object]] = []

    @contextmanager
    def tenant_session(
        self,
        *,
        flask_request,
        capability,
        additional_capabilities=(),
        request_id_prefix,
        after_authorize=None,
        passthrough_exceptions=(),
        allow_pending_warehouse_setup=False,
    ):
        self.calls.append(
            {
                "capability": capability,
                "additional_capabilities": additional_capabilities,
                "request_id_prefix": request_id_prefix,
                "allow_pending_warehouse_setup": (
                    allow_pending_warehouse_setup
                ),
            }
        )
        if after_authorize is not None:
            after_authorize(self.auth_context)
        with Session(
            self.engine,
            autoflush=False,
            expire_on_commit=False,
        ) as tenant_session:
            yield TenantBusinessRequestScope(
                auth_context=self.auth_context,
                request_id=f"warehouse-test:{len(self.calls)}",
                database_now=datetime(
                    2026,
                    8,
                    22,
                    16,
                    30,
                    tzinfo=timezone.utc,
                ),
                tenant_session=tenant_session,
            )


def _warehouse(name, *, default=False):
    return Warehouse(
        name=name,
        status="active",
        setup_state="ready",
        is_default=default,
        default_slot=1 if default else None,
        contact_name="负责人",
        contact_phone="13800138000",
        province="广东省",
        city="深圳市",
        district="南山区",
        address_detail=f"{name}测试地址",
    )


def test_tenant_warehouse_runtime_lists_creates_previews_and_moves_atomically(
    mysql_application_engine,
):
    app = create_app("testing")
    engine = mysql_application_engine
    scope = _ExplicitTenantRuntime(engine)
    source_unit_id = str(uuid4())
    target_unit_id = str(uuid4())
    try:
        with app.app_context():
            with Session(engine, expire_on_commit=False) as session:
                source = _warehouse("原仓", default=True)
                target = _warehouse("目标仓")
                accessory_type = AccessoryType(
                    name="tripod",
                    display_name="三脚架",
                    tracking_mode="logical_unit",
                )
                model = DeviceModel(
                    name="x300u",
                    display_name="VIVO X300 Ultra",
                    is_active=True,
                    is_accessory=False,
                )
                device = Device(name="主设备", warehouse=source)
                session.add_all(
                    (source, target, accessory_type, model, device)
                )
                session.flush()
                rental = Rental(
                    device=device,
                    start_date=date(2026, 9, 2),
                    end_date=date(2026, 9, 5),
                    planned_ship_out_date=date(2026, 9, 1),
                    planned_return_date=date(2026, 9, 6),
                    logistics_days=1,
                    customer_name="未来客户",
                    xianyu_order_no="ORDER-1",
                )
                source_unit = AccessoryUnit(
                    id=source_unit_id,
                    accessory_type=accessory_type,
                    warehouse=source,
                )
                target_unit = AccessoryUnit(
                    id=target_unit_id,
                    accessory_type=accessory_type,
                    warehouse=target,
                )
                session.add_all((rental, source_unit, target_unit))
                session.flush()
                session.add_all(
                    (
                        RentalAccessoryRequest(
                            rental_id=rental.id,
                            accessory_type_id=accessory_type.id,
                            name_snapshot="三脚架",
                        ),
                        RentalAccessoryUnitLink(
                            rental_id=rental.id,
                            accessory_type_id=accessory_type.id,
                            accessory_unit_id=source_unit.id,
                            reservation_start_at=datetime(2026, 9, 1),
                            reservation_end_at=datetime(2026, 9, 7),
                        ),
                    )
                )
                session.commit()
                source_id = source.id
                target_id = target.id
                device_id = device.id
                rental_id = rental.id
                model_id = model.id
                accessory_type_id = accessory_type.id

        runtime = SqlAlchemyWarehouseSaasHttpRuntime(
            tenant_business_runtime=scope
        )
        with app.test_request_context("/api/warehouses"):
            listed = runtime.list_warehouses(flask_request=request)
        assert [item["id"] for item in listed] == [source_id, target_id]
        assert scope.calls[-1]["capability"] is Capability.WAREHOUSE_READ

        with app.test_request_context("/api/warehouses/setup"):
            setup = runtime.get_default_setup(flask_request=request)
        assert setup["id"] == source_id
        assert scope.calls[-1]["capability"] is Capability.WAREHOUSE_SETUP
        assert scope.calls[-1]["allow_pending_warehouse_setup"] is True

        with app.test_request_context("/api/warehouses", method="POST"):
            created = runtime.create_warehouse(
                flask_request=request,
                payload={
                    "name": "新仓",
                    "contact_name": "新负责人",
                    "contact_phone": "13800138001",
                    "province": "浙江省",
                    "city": "杭州市",
                    "district": "余杭区",
                    "address_detail": "测试路 3 号",
                },
            )
        assert created["name"] == "新仓"
        assert created["is_default"] is False
        assert scope.calls[-1]["capability"] is Capability.WAREHOUSE_WRITE

        with app.test_request_context(
            f"/api/warehouses/{created['id']}", method="PUT"
        ):
            updated = runtime.update_warehouse(
                flask_request=request,
                warehouse_id=created["id"],
                payload={
                    "name": "新仓（已编辑）",
                    "contact_name": "新负责人",
                    "contact_phone": "13800138001",
                    "province": "浙江省",
                    "city": "杭州市",
                    "district": "余杭区",
                    "address_detail": "测试路 4 号",
                },
            )
        assert updated["name"] == "新仓（已编辑）"

        with app.test_request_context(
            "/api/warehouses/preferences/booking", method="PUT"
        ):
            preference = runtime.set_user_preference(
                flask_request=request,
                scene="booking",
                payload={"warehouse_id": created["id"]},
            )
        assert preference == {
            "scene": "booking",
            "warehouse_id": created["id"],
        }
        with app.test_request_context("/api/warehouses/preferences"):
            preferences = runtime.get_user_preferences(
                flask_request=request
            )
        assert preferences == {"booking": created["id"]}

        with app.test_request_context("/api/warehouses/devices"):
            devices = runtime.list_main_devices(flask_request=request)
        assert devices == (
            {
                "id": device_id,
                "name": "主设备",
                "serial_number": None,
                "model": "x200u",
                "model_id": None,
                "warehouse_id": source_id,
            },
        )
        assert scope.calls[-1]["capability"] is Capability.INVENTORY_READ
        assert scope.calls[-1]["additional_capabilities"] == (
            Capability.WAREHOUSE_READ,
        )

        with app.test_request_context("/api/warehouses/device-models"):
            models = runtime.list_main_device_models(flask_request=request)
        assert models == (
            {
                "id": model_id,
                "name": "x300u",
                "display_name": "VIVO X300 Ultra",
            },
        )

        with app.test_request_context(
            "/api/warehouses/devices", method="POST"
        ):
            created_device = runtime.create_main_device(
                flask_request=request,
                payload={
                    "name": "新主设备",
                    "serial_number": "SN-NEW-1",
                    "model_id": model_id,
                    "warehouse_id": target_id,
                },
            )
        assert created_device["warehouse_id"] == target_id
        assert created_device["model"] == "x300u"
        assert scope.calls[-1]["capability"] is Capability.INVENTORY_WRITE
        assert scope.calls[-1]["additional_capabilities"] == (
            Capability.WAREHOUSE_READ,
        )

        with app.test_request_context(
            "/api/warehouses/device-moves/preview",
            method="POST",
        ):
            preview = runtime.preview_device_move(
                flask_request=request,
                payload={
                    "device_id": device_id,
                    "target_warehouse_id": target_id,
                },
            )
        assert preview["affected_rental_ids"] == [rental_id]
        assert preview["affected_rentals"][0]["order_number"] == "ORDER-1"
        assert preview["preserves_logistics_facts"] is True
        assert source_unit_id not in repr(preview)
        assert target_unit_id not in repr(preview)
        assert scope.calls[-1]["additional_capabilities"] == (
            Capability.WAREHOUSE_READ,
            Capability.RENTAL_READ,
            Capability.INVENTORY_READ,
        )

        with app.test_request_context(
            "/api/warehouses/device-moves/confirm",
            method="POST",
        ):
            moved = runtime.confirm_device_move(
                flask_request=request,
                payload={
                    "device_id": device_id,
                    "target_warehouse_id": target_id,
                    "expected_current_warehouse_id": source_id,
                    "expected_preview_revision": preview["revision"],
                    "confirmed": True,
                    "note": "按实际位置调仓",
                },
            )
        assert moved["to_warehouse_id"] == target_id
        assert moved["affected_rental_ids"] == [rental_id]
        assert moved["accessory_fulfillment"] == [
            {
                "rental_id": rental_id,
                    "accessory_type_id": accessory_type_id,
                "accessory_name": "三脚架",
                "status": "fulfilled",
            }
        ]
        assert source_unit_id not in repr(moved)
        assert target_unit_id not in repr(moved)
        assert scope.calls[-1]["additional_capabilities"] == (
            Capability.WAREHOUSE_WRITE,
            Capability.INVENTORY_WRITE,
            Capability.RENTAL_READ,
        )

        with Session(engine) as session:
            assert session.get(Device, device_id).warehouse_id == target_id
            link = session.query(RentalAccessoryUnitLink).filter_by(
                rental_id=rental_id
            ).one()
            assert link.accessory_unit_id == target_unit_id
            assert session.query(DeviceWarehouseMovement).count() == 1
            assert session.query(AccessoryUnitEvent).filter_by(
                event_type="unlinked"
            ).count() == 1
            assert session.query(AccessoryUnitEvent).filter_by(
                event_type="linked"
            ).count() == 1
    finally:
        with app.app_context():
            db.session.remove()


def test_pending_default_setup_runtime_is_admin_scoped_and_marks_ready(
    mysql_application_engine,
):
    app = create_app("testing")
    engine = mysql_application_engine
    scope = _ExplicitTenantRuntime(engine)
    try:
        with app.app_context():
            with Session(engine) as session:
                pending = Warehouse.pending_default(
                    contact_phone="13800138000"
                )
                session.add(pending)
                session.commit()
                pending_id = pending.id

        runtime = SqlAlchemyWarehouseSaasHttpRuntime(
            tenant_business_runtime=scope
        )
        with app.test_request_context("/api/warehouses/setup"):
            before = runtime.get_default_setup(flask_request=request)
        assert before["id"] == pending_id
        assert before["setup_state"] == "pending"

        with app.test_request_context(
            "/api/warehouses/setup", method="PUT"
        ):
            after = runtime.setup_default_warehouse(
                flask_request=request,
                payload={
                    "name": "默认仓库",
                    "contact_name": "首位管理员",
                    "contact_phone": "13800138000",
                    "province": "广东省",
                    "city": "深圳市",
                    "district": "南山区",
                    "address_detail": "测试路 1 号",
                },
            )
        assert after["setup_state"] == "ready"
        assert scope.calls[-1]["capability"] is Capability.WAREHOUSE_SETUP
        assert scope.calls[-1]["allow_pending_warehouse_setup"] is True

        with Session(engine) as session:
            stored = session.get(Warehouse, pending_id)
            assert stored.setup_state == "ready"
            assert stored.is_default is True
    finally:
        with app.app_context():
            db.session.remove()


def test_warehouse_routes_fail_closed_without_explicit_runtime():
    app = create_app("testing")
    client = app.test_client()

    response = client.get("/api/warehouses")

    assert response.status_code == 503
    assert response.get_json() == {
        "success": False,
        "message": "租户仓库服务尚未就绪",
    }
    assert response.headers["Cache-Control"] == "private, no-store"
