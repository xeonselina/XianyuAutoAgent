from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from flask import request
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app import create_app, db
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.accessory_inventory import (
    AccessoryType,
    AccessoryUnit,
    DeviceAccessoryConfig,
    RentalAccessoryRequest,
    RentalAccessoryUnitLink,
)
from app.models.rental import Rental
from app.models.rental_relay_case import RentalRelayCase
from app.models.warehouse import (
    UserWarehousePreference,
    Warehouse,
    WarehouseProviderBinding,
)
from app.services.rental.http_runtime import (
    RentalIdInvalid,
    RentalQueryInvalid,
    SqlAlchemyRentalSaasHttpRuntime,
)
from app.services.rental.mutation_service import (
    RentalAccessoryChainRecalculationRequired,
    RentalAccessoryInspectionRequired,
    RentalOriginWarehouseChanged,
    RentalUsagePeriodConflict,
)
from app.services.tenant_business import TenantBusinessRequestScope
from inventory_control.domain import EffectiveTenantGate, TenantRole
from inventory_control.domain.rbac import Capability
from inventory_control.tenant_http import AuthContext
from tests.support.test_database import (
    build_mysql_test_config,
    clear_guarded_mysql_test_rows,
)


def _auth_context(**changes) -> AuthContext:
    values = dict(
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
    values.update(changes)
    return AuthContext(**values)


def _disconnected_test_engine():
    """Build a MySQL-shaped engine for validation paths that execute no SQL."""

    return create_engine(
        "mysql+pymysql://unused:unused@127.0.0.1:1/"
        "inventory_management_test",
        connect_args={"connect_timeout": 1},
    )


class _ExplicitTenantRuntime:
    def __init__(self, engine) -> None:
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
        self.calls.append({
            "path": flask_request.path,
            "capability": capability,
            "additional_capabilities": additional_capabilities,
            "request_id_prefix": request_id_prefix,
        })
        auth_context = self.auth_context
        if after_authorize is not None:
            after_authorize(auth_context)
        with Session(
            self.engine,
            autoflush=False,
            expire_on_commit=False,
        ) as tenant_session:
            yield TenantBusinessRequestScope(
                auth_context=auth_context,
                request_id=(
                    f"rental-runtime-test:request:{len(self.calls)}"
                ),
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


def _seed(engine, *, customer_name: str) -> None:
    with Session(engine) as session:
        device = Device(name=f"device-{customer_name}", is_accessory=False)
        accessory = Device(
            name="tripod-child",
            model="tripod",
            is_accessory=True,
        )
        session.add_all([device, accessory])
        session.flush()
        session.add(
            Rental(
                id=1,
                device_id=device.id,
                start_date=date(2026, 8, 22),
                end_date=date(2026, 8, 23),
                customer_name=customer_name,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        session.add(
            Rental(
                id=2,
                device_id=device.id,
                start_date=date(2026, 8, 19),
                end_date=date(2026, 8, 22),
                customer_name="pending-row",
                customer_phone="13800138000",
                destination="上海市测试路 1 号",
                status="shipped",
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        session.add(
            Rental(
                id=3,
                device_id=accessory.id,
                start_date=date(2026, 8, 22),
                end_date=date(2026, 8, 23),
                customer_name="child-row",
                parent_rental_id=1,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        session.commit()


@pytest.fixture
def mysql_tenant_database(mysql_application_engine):
    app = create_app(build_mysql_test_config())
    with app.app_context():
        try:
            yield app, mysql_application_engine
        finally:
            db.session.remove()


def test_detail_read_uses_only_supplied_tenant_session_for_same_local_id(
    mysql_application_engine,
) -> None:
    app = create_app("testing")
    engine = mysql_application_engine
    first_scope = _ExplicitTenantRuntime(engine)
    second_scope = _ExplicitTenantRuntime(engine)
    try:
        with app.app_context():
            _seed(engine, customer_name="tenant-a")

        with app.test_request_context("/api/rentals/1"):
            first = SqlAlchemyRentalSaasHttpRuntime(
                tenant_business_runtime=first_scope
            ).get_rental(flask_request=request, rental_id="1")
        with app.test_request_context(
            "/api/rentals/search",
            method="POST",
        ):
            first_list = SqlAlchemyRentalSaasHttpRuntime(
                tenant_business_runtime=first_scope
            ).list_rentals(
                flask_request=request,
                filters={"q": "tenant-a", "page": "1", "per_page": "10"},
            )
        with app.test_request_context("/api/rentals/pending-returns"):
            pending = SqlAlchemyRentalSaasHttpRuntime(
                tenant_business_runtime=first_scope
            ).list_pending_returns(
                flask_request=request,
                pagination={"page": "1", "per_page": "50"},
            )

        clear_guarded_mysql_test_rows(engine, db.metadata)
        with app.app_context():
            _seed(engine, customer_name="tenant-b")
        with app.test_request_context("/api/rentals/1"):
            second = SqlAlchemyRentalSaasHttpRuntime(
                tenant_business_runtime=second_scope
            ).get_rental(flask_request=request, rental_id="1")

        assert first is not None and first["customer_name"] == "tenant-a"
        assert second is not None and second["customer_name"] == "tenant-b"
        assert first["accessories"] == [{
            "id": first["child_rentals"][0]["device_id"],
            "name": "tripod-child",
            "model": "tripod",
            "is_accessory": True,
            "value": None,
        }]
        assert first["child_rentals"][0]["id"] == 3
        assert first_list["total"] == 1
        assert first_list["rentals"][0]["customer_name"] == "tenant-a"
        assert first_list["current_page"] == 1
        assert pending["as_of_date"] == "2026-08-23"
        assert pending["total"] == 1
        assert pending["rentals"] == [{
            "id": 2,
            "device_model": "x200u",
            "start_date": "2026-08-19",
            "end_date": "2026-08-22",
            "due_date": "2026-08-23",
            "overdue_days": 0,
            "destination": "上海市测试路 1 号",
            "customer_phone": "13800138000",
            "status": "shipped",
        }]
        for call in first_scope.calls + second_scope.calls:
            assert call["capability"] is Capability.RENTAL_READ
            assert call["additional_capabilities"] == (
                Capability.CUSTOMER_PII_READ,
            )
            assert call["request_id_prefix"] in {
                "rental-detail",
                "rental-list",
                "rental-pending-returns",
            }
    finally:
        with app.app_context():
            db.session.remove()


def test_booking_bootstrap_is_three_projected_reads_without_device_inventory(
    mysql_application_engine,
) -> None:
    app = create_app("testing")
    engine = mysql_application_engine
    runtime_scope = _ExplicitTenantRuntime(engine)
    capture_statement = None
    try:
        with app.app_context():
            with Session(engine, expire_on_commit=False) as session:
                default_warehouse = Warehouse(
                    name="华南仓",
                    status="active",
                    setup_state="ready",
                    is_default=True,
                    default_slot=1,
                    contact_name="默认联系人",
                    contact_phone="13800138000",
                    province="广东省",
                    city="深圳市",
                    district="南山区",
                    address_detail="测试路1号",
                )
                recent_warehouse = Warehouse(
                    name="华东仓",
                    status="active",
                    setup_state="ready",
                    is_default=False,
                    contact_name="最近联系人",
                    contact_phone="13800138001",
                    province="上海市",
                    city="上海市",
                    district="浦东新区",
                    address_detail="测试路2号",
                )
                session.add_all([default_warehouse, recent_warehouse])
                session.flush()
                accessory_type = AccessoryType(
                    name="tripod",
                    display_name="三脚架",
                    tracking_mode="logical_unit",
                    is_active=True,
                    display_order=2,
                )
                session.add_all([
                    UserWarehousePreference(
                        user_id=runtime_scope.auth_context.user_id,
                        scene="booking",
                        warehouse_id=recent_warehouse.id,
                    ),
                    DeviceModel(
                        name="bootstrap-model",
                        display_name="预约型号",
                        is_active=True,
                        is_accessory=False,
                    ),
                    accessory_type,
                ])
                session.commit()
                accessory_type_id = accessory_type.id

        statements: list[str] = []

        def capture_statement(
            _connection,
            _cursor,
            statement,
            *_args,
            **_kwargs,
        ):
            statements.append(statement)

        event.listen(
            engine,
            "before_cursor_execute",
            capture_statement,
        )
        runtime = SqlAlchemyRentalSaasHttpRuntime(
            tenant_business_runtime=runtime_scope
        )
        with app.test_request_context("/api/rental-booking/bootstrap"):
            payload = runtime.booking_bootstrap(flask_request=request)

        assert len(statements) == 3
        assert payload["recent_warehouse_id"] == recent_warehouse.id
        assert payload["default_warehouse_id"] == default_warehouse.id
        assert [row["name"] for row in payload["warehouses"]] == [
            "华南仓",
            "华东仓",
        ]
        assert payload["device_models"][0]["name"] == "bootstrap-model"
        assert payload["accessory_types"][0] == {
            "id": accessory_type_id,
            "name": "tripod",
            "display_name": "三脚架",
            "tracking_mode": "logical_unit",
            "display_order": 2,
        }
        assert payload["form_policy"]["minimum_logistics_days"] == 0
        assert runtime_scope.calls[-1]["capability"] is Capability.RENTAL_READ
        assert runtime_scope.calls[-1]["additional_capabilities"] == (
            Capability.INVENTORY_READ,
            Capability.WAREHOUSE_READ,
        )
    finally:
        if capture_statement is not None:
            event.remove(
                engine,
                "before_cursor_execute",
                capture_statement,
            )


def test_booking_availability_stays_at_five_sql_for_100_devices_and_31_days(
    mysql_tenant_database,
) -> None:
    app, engine = mysql_tenant_database
    runtime_scope = _ExplicitTenantRuntime(engine)
    target_start = date(2026, 9, 10)
    target_end = date(2026, 9, 12)
    capture_statement = None
    try:
        with app.app_context():
            with Session(engine, expire_on_commit=False) as session:
                model = DeviceModel(
                    name="availability-model",
                    display_name="可用性型号",
                    is_active=True,
                    is_accessory=False,
                )
                accessory_type = AccessoryType(
                    name="logical-tripod",
                    display_name="逻辑三脚架",
                    tracking_mode="logical_unit",
                    is_active=True,
                )
                south = Warehouse(
                    name="华南仓",
                    status="active",
                    setup_state="ready",
                    is_default=True,
                    default_slot=1,
                    contact_name="联系人A",
                    contact_phone="13800138000",
                    province="广东省",
                    city="深圳市",
                    district="南山区",
                    address_detail="测试路1号",
                )
                east = Warehouse(
                    name="华东仓",
                    status="active",
                    setup_state="ready",
                    is_default=False,
                    contact_name="联系人B",
                    contact_phone="13800138001",
                    province="上海市",
                    city="上海市",
                    district="浦东新区",
                    address_detail="测试路2号",
                )
                session.add_all([model, accessory_type, south, east])
                session.flush()
                session.add(
                    WarehouseProviderBinding(
                        warehouse_id=south.id,
                        provider="sf",
                        provider_account_uuid=str(uuid4()),
                        binding_revision=3,
                        status="active",
                        verified_at=datetime(2026, 8, 20),
                    )
                )
                devices = [
                    Device(
                        name=f"candidate-{index:03d}",
                        model="availability-model",
                        model_id=model.id,
                        is_accessory=False,
                        lifecycle_status="active",
                        warehouse_id=(south.id if index % 2 == 0 else east.id),
                    )
                    for index in range(100)
                ]
                session.add_all(devices)
                session.flush()
                session.add_all([
                    DeviceAccessoryConfig(
                        device_id=device.id,
                        accessory_type_id=accessory_type.id,
                        enabled=True,
                    )
                    for device in devices
                ])

                rentals = []
                for offset in range(31):
                    usage_date = date(2026, 9, 1) + timedelta(days=offset)
                    rental = Rental(
                        id=100 + offset,
                        device_id=devices[offset].id,
                        start_date=usage_date,
                        end_date=usage_date,
                        customer_name=f"schedule-{offset:02d}",
                        logistics_days=0,
                        planned_ship_out_date=usage_date - timedelta(days=1),
                        planned_return_date=usage_date + timedelta(days=1),
                        status="not_shipped",
                    )
                    rentals.append(rental)
                session.add_all(rentals)
                session.flush()
                relay_predecessor = Rental(
                    id=500,
                    device_id=devices[0].id,
                    start_date=date(2026, 9, 8),
                    end_date=date(2026, 9, 8),
                    customer_name="relay-predecessor",
                    logistics_days=2,
                    planned_ship_out_date=date(2026, 9, 5),
                    planned_return_date=date(2026, 9, 11),
                    status="not_shipped",
                )
                session.add(relay_predecessor)
                session.flush()

                units = []
                for warehouse in (south, east):
                    for _index in range(3):
                        units.append(
                            AccessoryUnit(
                                accessory_type_id=accessory_type.id,
                                warehouse_id=warehouse.id,
                                condition_status="active",
                            )
                        )
                session.add_all(units)
                session.flush()
                units[0].current_holder_rental_id = relay_predecessor.id
                session.add_all([
                    RentalAccessoryUnitLink(
                        rental_id=relay_predecessor.id,
                        accessory_type_id=accessory_type.id,
                        accessory_unit_id=units[0].id,
                        reservation_start_at=datetime(2026, 9, 5),
                        reservation_end_at=datetime(2026, 9, 12),
                    ),
                    RentalAccessoryUnitLink(
                        rental_id=rentals[1].id,
                        accessory_type_id=accessory_type.id,
                        accessory_unit_id=units[1].id,
                        reservation_start_at=datetime(2026, 9, 9),
                        reservation_end_at=datetime(2026, 9, 14),
                    ),
                ])
                session.commit()

        statements: list[str] = []
        def capture_statement(
            _connection,
            _cursor,
            statement,
            *_args,
            **_kwargs,
        ):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture_statement)
        runtime = SqlAlchemyRentalSaasHttpRuntime(
            tenant_business_runtime=runtime_scope
        )
        base_payload = {
            "start_date": target_start.isoformat(),
            "end_date": target_end.isoformat(),
            "model_id": model.id,
            "preferred_warehouse_id": east.id,
            "requested_accessory_type_ids": [accessory_type.id],
            "destination": {
                "province": "北京市",
                "city": "北京市",
                "district": "朝阳区",
                "address_detail": "测试收货路3号",
            },
        }
        with app.test_request_context(
            "/api/rental-booking/availability",
            method="POST",
        ):
            first = runtime.booking_availability(
                flask_request=request,
                payload=base_payload,
            )

        assert len(statements) == 5
        assert len(first["candidates"]) == 100
        assert first["candidates"][0]["warehouse"]["id"] == east.id
        assert first["estimate_by_warehouse"][str(south.id)][
            "safe_failure_reason"
        ] == "SF_ESTIMATOR_NOT_INSTALLED"
        assert first["estimate_by_warehouse"][str(east.id)][
            "safe_failure_reason"
        ] == "SF_BINDING_UNAVAILABLE"
        assert all(
            candidate["logistics_days"] is None
            for candidate in first["candidates"]
        )
        assert all(
            candidate["accessories"][0]["availability_status"]
            == "logistics_confirmation_required"
            for candidate in first["candidates"]
        )

        confirmations = {
            warehouse_id: {
                "days": 0,
                "context": estimate["confirmation_context"],
            }
            for warehouse_id, estimate in first[
                "estimate_by_warehouse"
            ].items()
        }
        statements.clear()
        with app.test_request_context(
            "/api/rental-booking/availability",
            method="POST",
        ):
            confirmed = runtime.booking_availability(
                flask_request=request,
                payload={
                    **base_payload,
                    "manual_logistics_by_warehouse": confirmations,
                },
            )

        assert len(statements) == 5
        by_id = {
            candidate["device"]["id"]: candidate
            for candidate in confirmed["candidates"]
        }
        assert by_id[devices[9].id]["available"] is False
        assert by_id[devices[9].id]["hard_conflicts"][0]["code"] == (
            "USAGE_PERIOD_CONFLICT"
        )
        south_candidate = by_id[devices[0].id]
        east_candidate = by_id[devices[1].id]
        assert south_candidate["accessories"][0] == {
            "accessory_type_id": accessory_type.id,
            "name": "logical-tripod",
            "display_name": "逻辑三脚架",
            "tracking_mode": "logical_unit",
            "requested": True,
            "total": 3,
            "reserved": 2,
            "available": 1,
            "availability_status": "evaluated",
            "travels_with_device": True,
            "fulfilled": False,
            "relay_confirmation_required": True,
            "shortage": False,
            "display_hint": "relay_confirmation_required",
        }
        assert east_candidate["accessories"][0]["available"] == 3
        assert all(
            estimate["status"] == "manual_confirmed"
            for estimate in confirmed["estimate_by_warehouse"].values()
        )

        statements.clear()
        with app.test_request_context(
            "/api/rental-booking/availability",
            method="POST",
        ):
            own_edit = runtime.booking_availability(
                flask_request=request,
                payload={
                    **base_payload,
                    "exclude_rental_id": relay_predecessor.id,
                    "manual_logistics_by_warehouse": confirmations,
                },
            )
        assert len(statements) == 5
        own_accessory = {
            candidate["device"]["id"]: candidate
            for candidate in own_edit["candidates"]
        }[devices[0].id]["accessories"][0]
        assert own_accessory["fulfilled"] is True
        assert own_accessory["relay_confirmation_required"] is False
        assert own_accessory["shortage"] is False
        assert own_accessory["display_hint"] == "already_fulfilled"

        statements.clear()
        create_payload = {
            **base_payload,
            "device_id": devices[1].id,
            "expected_origin_warehouse_id": east.id,
            "manual_logistics_by_warehouse": confirmations,
            "customer_name": "最终事务客户",
            "customer_phone": "13800138000",
            "xianyu_order_no": "XY-FINAL-1",
            "order_amount": "88.00",
            "includes_handle": True,
            "includes_lens_mount": False,
            "photo_transfer": True,
            "lens_combo": "lens_400mm",
        }
        with app.test_request_context(
            "/api/rentals",
            method="POST",
        ):
            created = runtime.create_rental(
                flask_request=request,
                payload=create_payload,
            )

        assert created["main_rental"]["device_id"] == devices[1].id
        assert created["main_rental"]["warehouse"]["id"] == east.id
        assert created["main_rental"][
            "requested_accessory_type_ids"
        ] == [accessory_type.id]
        assert created["accessory_rentals"] == []
        assert created["refresh_scope"] == "current_window"
        assert "accessory_unit_id" not in repr(created)
        with Session(engine) as session:
            persisted = session.get(
                Rental,
                created["main_rental"]["id"],
            )
            assert persisted is not None
            assert persisted.customer_province == "北京市"
            assert persisted.customer_city == "北京市"
            assert persisted.customer_district == "朝阳区"
            assert persisted.customer_address_detail == "测试收货路3号"
            assert persisted.logistics_estimate_origin_warehouse_id == east.id
            assert persisted.logistics_estimate_days == 0
            assert session.query(RentalAccessoryRequest).filter_by(
                rental_id=persisted.id,
                accessory_type_id=accessory_type.id,
            ).count() == 1
            assert session.query(RentalAccessoryUnitLink).filter_by(
                rental_id=persisted.id,
                accessory_type_id=accessory_type.id,
            ).count() == 1
        assert runtime_scope.calls[-1]["capability"] is Capability.RENTAL_WRITE
        assert runtime_scope.calls[-1]["additional_capabilities"] == (
            Capability.CUSTOMER_PII_READ,
            Capability.INVENTORY_READ,
            Capability.WAREHOUSE_READ,
        )

        update_payload = {
            **create_payload,
            "start_date": "2026-09-15",
            "end_date": "2026-09-16",
            "customer_name": "最终编辑客户",
            "damage_note": "镜头卡口松动",
        }
        with app.test_request_context(
            f"/api/rentals/{created['main_rental']['id']}",
            method="PUT",
        ):
            updated = runtime.update_rental(
                flask_request=request,
                rental_id=str(created["main_rental"]["id"]),
                payload=update_payload,
            )

        assert updated["rental"] == {
            "id": created["main_rental"]["id"],
            "device_id": devices[1].id,
            "start_date": "2026-09-15",
            "end_date": "2026-09-16",
            "status": "not_shipped",
            "customer_name": "最终编辑客户",
            "destination": "北京市北京市朝阳区测试收货路3号",
            "warehouse": {
                "id": east.id,
                "name": "华东仓",
                "province": "上海市",
                "city": "上海市",
                "district": "浦东新区",
            },
            "requested_accessory_type_ids": [accessory_type.id],
        }
        assert updated["refresh_scope"] == "current_window"
        assert "accessory_unit_id" not in repr(updated)
        assert runtime_scope.calls[-1]["capability"] is Capability.RENTAL_WRITE
        assert runtime_scope.calls[-1]["request_id_prefix"] == "rental-update"
        with Session(engine) as session:
            persisted = session.get(
                Rental,
                created["main_rental"]["id"],
            )
            assert persisted is not None
            assert persisted.customer_name == "最终编辑客户"
            assert persisted.damage_note == "镜头卡口松动"
            assert persisted.start_date == date(2026, 9, 15)
            assert persisted.end_date == date(2026, 9, 16)
            link = session.query(RentalAccessoryUnitLink).filter_by(
                rental_id=persisted.id,
                accessory_type_id=accessory_type.id,
            ).one()
            assert link.reservation_start_at == datetime(2026, 9, 14)
            assert link.reservation_end_at == datetime(2026, 9, 18)

        with app.test_request_context(
            f"/api/rentals/{created['main_rental']['id']}",
            method="PUT",
        ):
            with pytest.raises(RentalUsagePeriodConflict):
                runtime.update_rental(
                    flask_request=request,
                    rental_id=created["main_rental"]["id"],
                    payload={
                        **update_payload,
                        "device_id": devices[9].id,
                        "start_date": target_start.isoformat(),
                        "end_date": target_end.isoformat(),
                    },
                )
        with Session(engine) as session:
            persisted = session.get(
                Rental,
                created["main_rental"]["id"],
            )
            assert persisted is not None
            assert persisted.device_id == devices[1].id
            assert persisted.customer_name == "最终编辑客户"
            assert persisted.start_date == date(2026, 9, 15)

        with Session(engine) as session:
            relay_link = session.query(RentalAccessoryUnitLink).filter_by(
                rental_id=created["main_rental"]["id"],
                accessory_type_id=accessory_type.id,
            ).one()
            relay_case = RentalRelayCase(
                predecessor_rental_id=relay_predecessor.id,
                successor_rental_id=created["main_rental"]["id"],
                status="agreed",
            )
            session.add(relay_case)
            session.flush()
            relay_link.source_relay_case_id = relay_case.id
            relay_case_id = relay_case.id
            session.commit()
        with app.test_request_context(
            f"/api/rentals/{created['main_rental']['id']}",
            method="PUT",
        ):
            with pytest.raises(RentalAccessoryChainRecalculationRequired):
                runtime.update_rental(
                    flask_request=request,
                    rental_id=created["main_rental"]["id"],
                    payload={
                        **update_payload,
                        "start_date": "2026-09-16",
                        "end_date": "2026-09-17",
                    },
                )
        with Session(engine) as session:
            persisted = session.get(
                Rental,
                created["main_rental"]["id"],
            )
            assert persisted is not None
            assert persisted.start_date == date(2026, 9, 15)
            relay_link = session.query(RentalAccessoryUnitLink).filter_by(
                rental_id=persisted.id,
                accessory_type_id=accessory_type.id,
            ).one()
            relay_link.source_relay_case_id = None
            session.flush()
            session.delete(session.get(RentalRelayCase, relay_case_id))
            session.commit()

        with app.test_request_context(
            f"/api/rentals/{created['main_rental']['id']}/status",
            method="PUT",
        ):
            shipped = runtime.update_rental_status(
                flask_request=request,
                rental_id=created["main_rental"]["id"],
                payload={"status": "shipped"},
            )
        assert shipped["status"] == "shipped"
        assert shipped["actual_shipped_at"] == "2026-08-22T16:30:00"
        assert "accessory_unit_id" not in repr(shipped)
        assert runtime_scope.calls[-1]["capability"] is Capability.RENTAL_WRITE
        assert runtime_scope.calls[-1]["additional_capabilities"] == (
            Capability.INVENTORY_READ,
        )
        assert runtime_scope.calls[-1]["request_id_prefix"] == "rental-status"
        with Session(engine) as session:
            dispatched_link = session.query(
                RentalAccessoryUnitLink
            ).filter_by(
                rental_id=created["main_rental"]["id"],
                accessory_type_id=accessory_type.id,
            ).one()
            dispatched_unit = session.get(
                AccessoryUnit,
                dispatched_link.accessory_unit_id,
            )
            assert dispatched_unit is not None
            assert dispatched_unit.current_holder_rental_id == (
                created["main_rental"]["id"]
            )

        with app.test_request_context(
            f"/api/rentals/{created['main_rental']['id']}/status",
            method="PUT",
        ):
            returned = runtime.update_rental_status(
                flask_request=request,
                rental_id=created["main_rental"]["id"],
                payload={"status": "returned"},
            )
        assert returned["status"] == "returned"
        assert returned["actual_returned_at"] == "2026-08-22T16:30:00"
        with app.test_request_context(
            f"/api/rentals/{created['main_rental']['id']}/status",
            method="PUT",
        ):
            with pytest.raises(RentalAccessoryInspectionRequired):
                runtime.update_rental_status(
                    flask_request=request,
                    rental_id=created["main_rental"]["id"],
                    payload={"status": "completed"},
                )
        with Session(engine) as session:
            dispatched_unit = session.query(AccessoryUnit).filter_by(
                current_holder_rental_id=created["main_rental"]["id"],
            ).one()
            dispatched_unit.current_holder_rental_id = None
            session.commit()
        with app.test_request_context(
            f"/api/rentals/{created['main_rental']['id']}/status",
            method="PUT",
        ):
            completed = runtime.update_rental_status(
                flask_request=request,
                rental_id=created["main_rental"]["id"],
                payload={"status": "completed"},
            )
        assert completed["status"] == "completed"
        with app.test_request_context(
            f"/api/rentals/{created['main_rental']['id']}",
            method="DELETE",
        ):
            deleted = runtime.delete_rental(
                flask_request=request,
                rental_id=created["main_rental"]["id"],
            )
        assert deleted["deleted"] is True
        assert deleted["id"] == created["main_rental"]["id"]
        assert runtime_scope.calls[-1]["request_id_prefix"] == "rental-delete"
        with Session(engine) as session:
            assert session.get(
                Rental,
                created["main_rental"]["id"],
            ) is None
            assert session.query(RentalAccessoryRequest).filter_by(
                rental_id=created["main_rental"]["id"],
            ).count() == 0
            assert session.query(RentalAccessoryUnitLink).filter_by(
                rental_id=created["main_rental"]["id"],
            ).count() == 0

        with app.test_request_context(
            "/api/rentals",
            method="POST",
        ):
            with pytest.raises(RentalOriginWarehouseChanged) as changed:
                runtime.create_rental(
                    flask_request=request,
                    payload={
                        **create_payload,
                        "xianyu_order_no": "XY-WRONG-ORIGIN",
                        "expected_origin_warehouse_id": south.id,
                    },
                )
        assert changed.value.data["warehouse"]["id"] == east.id
        assert changed.value.data["estimate"][
            "safe_failure_reason"
        ] == "SF_BINDING_UNAVAILABLE"
        with app.test_request_context(
            "/api/rentals",
            method="POST",
        ):
            with pytest.raises(RentalUsagePeriodConflict):
                runtime.create_rental(
                    flask_request=request,
                    payload={
                        **create_payload,
                        "device_id": devices[9].id,
                        "xianyu_order_no": "XY-CONFLICT",
                    },
                )
        with Session(engine) as session:
            assert session.query(Rental).filter(
                Rental.xianyu_order_no.in_((
                    "XY-WRONG-ORIGIN",
                    "XY-CONFLICT",
                ))
            ).count() == 0
    finally:
        if capture_statement is not None:
            event.remove(
                engine,
                "before_cursor_execute",
                capture_statement,
            )
        db.session.remove()


@pytest.mark.parametrize("rental_id", ("0", "01", "-1", "abc", True, None))
def test_invalid_id_is_rejected_after_authority_callback(rental_id) -> None:
    app = create_app("testing")
    engine = _disconnected_test_engine()
    try:
        runtime_scope = _ExplicitTenantRuntime(engine)
        runtime = SqlAlchemyRentalSaasHttpRuntime(
            tenant_business_runtime=runtime_scope
        )
        with app.test_request_context("/api/rentals/invalid"):
            with pytest.raises(RentalIdInvalid):
                runtime.get_rental(
                    flask_request=request,
                    rental_id=rental_id,
                )
        assert len(runtime_scope.calls) == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "filters",
    (
        None,
        {"page": "0"},
        {"per_page": "101"},
        {"status": "unknown"},
        {"start_date": "2026-08-22"},
        {"start_date": "2026-08-23", "end_date": "2026-08-22"},
        {"q": "x" * 101},
    ),
)
def test_invalid_list_query_is_rejected_after_authority_callback(filters) -> None:
    app = create_app("testing")
    engine = _disconnected_test_engine()
    try:
        runtime_scope = _ExplicitTenantRuntime(engine)
        runtime = SqlAlchemyRentalSaasHttpRuntime(
            tenant_business_runtime=runtime_scope
        )
        with app.test_request_context("/api/rentals"):
            with pytest.raises(RentalQueryInvalid):
                runtime.list_rentals(
                    flask_request=request,
                    filters=filters,
                )
        assert len(runtime_scope.calls) == 1
    finally:
        engine.dispose()


def test_list_projection_uses_two_queries_for_one_hundred_rows(
    mysql_application_engine,
) -> None:
    app = create_app("testing")
    engine = mysql_application_engine
    statements: list[str] = []
    capture_statement = None
    try:
        with app.app_context():
            with Session(engine) as session:
                first_rental = None
                for ordinal in range(1, 106):
                    device = Device(
                        name=f"projection-device-{ordinal}",
                        serial_number=f"PROJECTION-{ordinal}",
                        is_accessory=False,
                    )
                    session.add(device)
                    session.flush()
                    rental = Rental(
                        device_id=device.id,
                        start_date=date(2026, 9, 1),
                        end_date=date(2026, 9, 2),
                        customer_name=f"projection-customer-{ordinal}",
                    )
                    session.add(rental)
                    if first_rental is None:
                        first_rental = rental
                session.commit()
                first_rental_id = first_rental.id

        def capture_statement(
            _connection,
            _cursor,
            statement,
            *_args,
        ):
            statements.append(statement)

        event.listen(
            engine,
            "before_cursor_execute",
            capture_statement,
        )
        runtime = SqlAlchemyRentalSaasHttpRuntime(
            tenant_business_runtime=_ExplicitTenantRuntime(engine)
        )
        with app.test_request_context("/api/rentals?per_page=100"):
            result = runtime.list_rentals(
                flask_request=request,
                filters={"page": "1", "per_page": "100"},
            )

        assert result["total"] == 105
        assert len(result["rentals"]) == 100
        assert len(statements) == 2

        statements.clear()
        with app.test_request_context(f"/api/rentals/{first_rental_id}"):
            detail = runtime.get_rental(
                flask_request=request,
                rental_id=str(first_rental_id),
            )
        assert detail is not None
        assert detail["customer_name"] == "projection-customer-1"
        assert len(statements) == 2

        statements.clear()
        with app.test_request_context(
            f"/api/rentals/{first_rental_id}/edit-context"
        ):
            edit_context = runtime.get_edit_context(
                flask_request=request,
                rental_id=str(first_rental_id),
            )
        assert edit_context is not None
        assert edit_context["rental"]["customer_name"] == (
            "projection-customer-1"
        )
        assert edit_context["warehouses"] == []
        assert len(edit_context["devices"]) == 105
        assert edit_context["legacy_device_bound_accessories"] == []
        assert edit_context["rental"][
            "requested_accessory_type_ids"
        ] == []
        assert edit_context["rental"]["accessory_requests"] == []
        assert len(statements) == 7
    finally:
        if capture_statement is not None:
            event.remove(
                engine,
                "before_cursor_execute",
                capture_statement,
            )
