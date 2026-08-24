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
    DeviceAccessoryConfig,
    RentalAccessoryRequest,
    RentalAccessoryUnitLink,
)
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.inspection_record import InspectionRecord
from app.models.rental import Rental
from app.models.warehouse import DeviceWarehouseMovement, Warehouse
from app.services.inspection.http_runtime import SqlAlchemyInspectionSaasHttpRuntime
from app.services.rental.http_runtime import SqlAlchemyRentalSaasHttpRuntime
from app.services.tenant_business import TenantBusinessRequestScope
from inventory_control.domain import EffectiveTenantGate, TenantRole
from inventory_control.domain.rbac import Capability
from inventory_control.tenant_http import AuthContext


def _auth_context() -> AuthContext:
    return AuthContext(
        session_id=str(uuid4()),
        user_id=str(uuid4()),
        membership_id=str(uuid4()),
        tenant_id=str(uuid4()),
        role=TenantRole.OPERATOR,
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
    ):
        self.calls.append(
            {
                "path": flask_request.path,
                "capability": capability,
                "additional_capabilities": additional_capabilities,
                "request_id_prefix": request_id_prefix,
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
                request_id=f"inspection-test:{len(self.calls)}",
                database_now=datetime(2026, 8, 22, 16, 30, tzinfo=timezone.utc),
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


def test_tenant_inspection_closes_ordinary_accessory_custody_atomically(
    mysql_application_engine,
):
    app = create_app("testing")
    engine = mysql_application_engine
    scope = _ExplicitTenantRuntime(engine)
    try:
        with app.app_context():
            with Session(engine, expire_on_commit=False) as session:
                source = _warehouse("发货仓", default=True)
                target = _warehouse("验货仓")
                model = DeviceModel(
                    name="inspection-model",
                    display_name="验货型号",
                    is_active=True,
                    is_accessory=False,
                )
                accessory_type = AccessoryType(
                    name="tripod",
                    display_name="三脚架",
                    tracking_mode="logical_unit",
                    is_active=True,
                )
                session.add_all((source, target, model, accessory_type))
                session.flush()
                device = Device(
                    name="inspection-device",
                    model_id=model.id,
                    model=model.name,
                    warehouse_id=source.id,
                    is_accessory=False,
                )
                future_device = Device(
                    name="future-device",
                    model_id=model.id,
                    model=model.name,
                    warehouse_id=source.id,
                    is_accessory=False,
                )
                session.add_all((device, future_device))
                session.flush()
                session.add(
                    DeviceAccessoryConfig(
                        device_id=device.id,
                        accessory_type_id=accessory_type.id,
                        enabled=True,
                    )
                )
                rental = Rental(
                    device_id=device.id,
                    start_date=date(2026, 8, 18),
                    end_date=date(2026, 8, 20),
                    customer_name="验货客户",
                    customer_phone="13800138001",
                    damage_note="客户反馈镜头松动",
                    status="returned",
                    actual_returned_at=datetime(2026, 8, 22, 15, 0),
                )
                future_rental = Rental(
                    device_id=future_device.id,
                    start_date=date(2026, 9, 2),
                    end_date=date(2026, 9, 5),
                    customer_name="未来客户",
                    status="not_shipped",
                )
                session.add_all((rental, future_rental))
                session.flush()
                unit = AccessoryUnit(
                    accessory_type_id=accessory_type.id,
                    warehouse_id=source.id,
                    current_holder_rental_id=rental.id,
                    condition_status="active",
                )
                replacement_unit = AccessoryUnit(
                    accessory_type_id=accessory_type.id,
                    warehouse_id=source.id,
                    condition_status="active",
                )
                session.add_all((unit, replacement_unit))
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
                            accessory_unit_id=unit.id,
                            reservation_start_at=datetime(2026, 8, 17),
                            reservation_end_at=datetime(2026, 8, 22, 16),
                        ),
                        RentalAccessoryRequest(
                            rental_id=future_rental.id,
                            accessory_type_id=accessory_type.id,
                            name_snapshot="三脚架",
                        ),
                        RentalAccessoryUnitLink(
                            rental_id=future_rental.id,
                            accessory_type_id=accessory_type.id,
                            accessory_unit_id=unit.id,
                            reservation_start_at=datetime(2026, 9, 1),
                            reservation_end_at=datetime(2026, 9, 7),
                        ),
                    )
                )
                session.commit()
                rental_id = rental.id
                device_id = device.id
                target_id = target.id
                accessory_type_id = accessory_type.id
                future_rental_id = future_rental.id
                inspected_unit_id = unit.id
                replacement_unit_id = replacement_unit.id

        runtime = SqlAlchemyInspectionSaasHttpRuntime(
            tenant_business_runtime=scope
        )
        with app.test_request_context(
            f"/api/inspections/rental/latest/{device_id}"
        ):
            context = runtime.latest_by_device_id(
                flask_request=request,
                device_id=device_id,
            )

        assert context is not None
        assert context["rental"]["id"] == rental_id
        assert context["rental"]["damage_note"] == "客户反馈镜头松动"
        assert context["accessory_receipts"] == [
            {
                "accessory_type_id": accessory_type_id,
                "type_code": "tripod",
                "display_name": "三脚架",
                "travels_with_device": False,
                "outcome": "received_normal",
            }
        ]
        assert "accessory_unit_id" not in repr(context)
        assert scope.calls[-1]["capability"] is Capability.INSPECTION_WRITE
        assert scope.calls[-1]["additional_capabilities"] == (
            Capability.RENTAL_READ,
            Capability.INVENTORY_READ,
            Capability.WAREHOUSE_READ,
            Capability.CUSTOMER_PII_READ,
        )

        payload = {
            "rental_id": rental_id,
            "device_id": device_id,
            "warehouse_id": target_id,
            "check_items": [
                {"name": "机身外观", "is_checked": True, "order": 1}
            ],
            "accessory_receipts": [
                {
                    "accessory_type_id": accessory_type_id,
                    "outcome": "received_normal",
                }
            ],
        }
        with app.test_request_context("/api/inspections", method="POST"):
            created = runtime.create_inspection(
                flask_request=request,
                payload=payload,
            )

        assert created["status"] == "normal"
        assert created["warehouse_id"] == target_id
        assert created["inspector_user_uuid"] == scope.auth_context.user_id
        assert created["accessory_reassignments"] == [
            {
                "type_code": "tripod",
                "display_name": "三脚架",
                "outcome": "received_normal",
                "retained_relay_count": 0,
                "reassigned_count": 1,
                "shortage_count": 0,
                "affected_rental_ids": (future_rental_id,),
                "shortage_rental_ids": (),
            }
        ]
        assert "accessory_unit_id" not in repr(created)
        assert scope.calls[-1]["request_id_prefix"] == "inspection-create"
        with Session(engine) as session:
            persisted_device = session.get(Device, device_id)
            persisted_unit = session.get(AccessoryUnit, inspected_unit_id)
            assert persisted_device.warehouse_id == target_id
            assert persisted_unit.warehouse_id == target_id
            assert persisted_unit.current_holder_rental_id is None
            assert persisted_unit.condition_status == "active"
            future_link = session.query(RentalAccessoryUnitLink).filter_by(
                rental_id=future_rental_id,
                accessory_type_id=accessory_type_id,
            ).one()
            assert future_link.accessory_unit_id == replacement_unit_id
            assert session.query(DeviceWarehouseMovement).count() == 1
            assert session.query(InspectionRecord).count() == 1
            assert session.query(AccessoryUnitEvent).filter_by(
                event_type="inspected"
            ).count() == 1
            assert session.query(AccessoryUnitEvent).filter_by(
                event_type="warehouse_moved"
            ).count() == 1
            assert session.query(AccessoryUnitEvent).filter_by(
                event_type="unlinked"
            ).count() == 1
            assert session.query(AccessoryUnitEvent).filter_by(
                event_type="linked"
            ).count() == 1

        rental_runtime = SqlAlchemyRentalSaasHttpRuntime(
            tenant_business_runtime=scope
        )
        with app.test_request_context(
            f"/api/rentals/{rental_id}/status", method="PUT"
        ):
            completed = rental_runtime.update_rental_status(
                flask_request=request,
                rental_id=rental_id,
                payload={"status": "completed"},
            )
        assert completed["status"] == "completed"

        inspection_id = created["id"]
        check_id = created["check_items"][0]["id"]
        with app.test_request_context(
            f"/api/inspections/{inspection_id}", method="PUT"
        ):
            updated = runtime.update_inspection(
                flask_request=request,
                inspection_id=inspection_id,
                payload={
                    "check_items": [{"id": check_id, "is_checked": False}]
                },
            )
        assert updated["status"] == "abnormal"

        with app.test_request_context("/api/inspections?status=abnormal"):
            listed = runtime.list_inspections(
                flask_request=request,
                filters={"status": "abnormal", "page": "1", "per_page": "20"},
            )
        assert listed["pagination"]["total"] == 1
        assert listed["records"][0]["id"] == inspection_id
        assert "accessory_unit_id" not in repr(listed)
    finally:
        with app.app_context():
            db.session.remove()
