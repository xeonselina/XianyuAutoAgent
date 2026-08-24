from __future__ import annotations

import json
from datetime import date, datetime

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app import create_app, db
from app.models.device import Device
from app.models.rental import Rental
from app.models.warehouse import Warehouse
from app.services.platform_tenant_read.query_service import (
    PlatformTenantBusinessQueryService,
    PlatformTenantRentalQueryInputError,
    PlatformTenantRentalQueryService,
)


@pytest.fixture
def application():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        try:
            yield app
        finally:
            db.session.remove()
            db.drop_all()


def _seed_rentals() -> None:
    main_device = Device(name="主设备 A", model="x300u")
    child_device = Device(
        name="附件 B",
        model="battery",
        is_accessory=True,
    )
    main = Rental(
        device=main_device,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 4),
        customer_name="张三丰",
        customer_phone="+86 139-1234-5678",
        customer_province="广东省",
        customer_city="深圳市",
        customer_district="南山区",
        customer_address_detail="科技园秘密地址 101 号",
        buyer_id="buyer-secret",
        ship_out_tracking_no="SF-SECRET-001",
        customer_note="不能返回的内部备注",
        order_amount="123.45",
        status="shipped",
        actual_shipped_at=datetime(2026, 8, 31, 8, 30),
    )
    child = Rental(
        device=child_device,
        parent_rental=main,
        start_date=main.start_date,
        end_date=main.end_date,
        customer_name="附件子记录客户",
        status="shipped",
    )
    db.session.add_all([main_device, child_device, main, child])
    db.session.commit()


def test_list_rentals_is_one_bounded_select_and_returns_masked_main_rows(
    application,
) -> None:
    _seed_rentals()
    executed: list[str] = []

    def capture(_connection, _cursor, statement, *_args):
        executed.append(statement)

    event.listen(db.engine, "before_cursor_execute", capture)
    try:
        with Session(db.engine) as session, session.begin():
            result = PlatformTenantRentalQueryService(
                maximum_execution_time_ms=2_000
            ).list_rentals(
                session,
                page=1,
                page_size=1,
                status="shipped",
            )
    finally:
        event.remove(db.engine, "before_cursor_execute", capture)

    assert len(executed) == 1
    assert executed[0].lstrip().upper().startswith("SELECT")
    assert result["page"] == 1
    assert result["page_size"] == 1
    assert result["status_filter"] == "shipped"
    assert result["has_more"] is False
    assert len(result["items"]) == 1
    row = result["items"][0]
    assert row["device"] == {
        "device_id": row["device"]["device_id"],
        "name": "主设备 A",
        "model": "x300u",
    }
    assert row["customer"] == {
        "name_masked": "张**",
        "phone_masked": "*******5678",
        "region_masked": "已设置",
    }
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "张三丰",
        "+86 139-1234-5678",
        "广东省",
        "深圳市",
        "南山区",
        "科技园秘密地址 101 号",
        "buyer-secret",
        "SF-SECRET-001",
        "不能返回的内部备注",
        "附件子记录客户",
    ):
        assert forbidden not in serialized


def test_list_rentals_paginates_deterministically(application) -> None:
    for index in range(3):
        device = Device(name=f"设备 {index}", model="x200u")
        db.session.add(
            Rental(
                device=device,
                start_date=date(2026, 9, index + 1),
                end_date=date(2026, 9, index + 2),
                customer_name=f"客户 {index}",
                status="not_shipped",
            )
        )
    db.session.commit()

    service = PlatformTenantRentalQueryService(
        maximum_execution_time_ms=1_000
    )
    with Session(db.engine) as session, session.begin():
        first = service.list_rentals(
            session,
            page=1,
            page_size=2,
        )
    with Session(db.engine) as session, session.begin():
        second = service.list_rentals(
            session,
            page=2,
            page_size=2,
        )

    assert first["has_more"] is True
    assert second["has_more"] is False
    assert [row["rental_id"] for row in first["items"]] == [3, 2]
    assert [row["rental_id"] for row in second["items"]] == [1]


def test_device_and_warehouse_lists_are_bounded_non_pii_projections(
    application,
) -> None:
    warehouse = Warehouse(
        name="深圳一仓",
        status="active",
        setup_state="ready",
        is_default=True,
        default_slot=1,
        contact_name="秘密联系人",
        contact_phone="13900001111",
        province="广东省",
        city="深圳市",
        district="南山区",
        address_detail="秘密仓库地址 8 号",
    )
    device = Device(
        name="排障设备",
        model="x300u",
        serial_number="SERIAL-SECRET",
        lifecycle_status="damaged",
        lifecycle_reason="不可返回的损坏备注",
        warehouse=warehouse,
    )
    db.session.add_all((warehouse, device))
    db.session.commit()
    executed: list[str] = []

    def capture(_connection, _cursor, statement, *_args):
        executed.append(statement)

    service = PlatformTenantBusinessQueryService(
        maximum_execution_time_ms=1_000
    )
    event.listen(db.engine, "before_cursor_execute", capture)
    try:
        with Session(db.engine) as session, session.begin():
            devices = service.list_devices(
                session,
                page=1,
                page_size=25,
                lifecycle_status="damaged",
            )
        with Session(db.engine) as session, session.begin():
            warehouses = service.list_warehouses(
                session,
                page=1,
                page_size=25,
                status="active",
                setup_state="ready",
            )
    finally:
        event.remove(db.engine, "before_cursor_execute", capture)

    assert len(executed) == 2
    assert all(value.lstrip().upper().startswith("SELECT") for value in executed)
    assert devices["items"] == [
        {
            "device_id": device.id,
            "name": "排障设备",
            "model": "x300u",
            "model_id": None,
            "is_accessory": False,
            "warehouse_id": warehouse.id,
            "lifecycle_status": "damaged",
            "lifecycle_date": None,
            "created_at": devices["items"][0]["created_at"],
            "updated_at": devices["items"][0]["updated_at"],
        }
    ]
    assert warehouses["items"] == [
        {
            "warehouse_id": warehouse.id,
            "warehouse_uuid": warehouse.warehouse_uuid,
            "name": "深圳一仓",
            "status": "active",
            "setup_state": "ready",
            "is_default": True,
            "created_at": warehouses["items"][0]["created_at"],
            "updated_at": warehouses["items"][0]["updated_at"],
        }
    ]
    serialized = json.dumps(
        {"devices": devices, "warehouses": warehouses},
        ensure_ascii=False,
    )
    for forbidden in (
        "SERIAL-SECRET",
        "不可返回的损坏备注",
        "秘密联系人",
        "13900001111",
        "广东省",
        "深圳市",
        "南山区",
        "秘密仓库地址 8 号",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        ("list_devices", {"lifecycle_status": "unknown"}),
        ("list_warehouses", {"status": "unknown"}),
        ("list_warehouses", {"setup_state": "unknown"}),
    ],
)
def test_business_lists_reject_unknown_filters(application, method, kwargs) -> None:
    service = PlatformTenantBusinessQueryService(
        maximum_execution_time_ms=1_000
    )
    with Session(db.engine) as session, session.begin():
        with pytest.raises(PlatformTenantRentalQueryInputError):
            getattr(service, method)(
                session,
                page=1,
                page_size=25,
                **kwargs,
            )


def test_get_customer_pii_is_one_exact_select_for_main_rental(
    application,
) -> None:
    _seed_rentals()
    main_id = db.session.scalar(
        db.select(Rental.id).where(Rental.parent_rental_id.is_(None))
    )
    executed: list[str] = []

    def capture(_connection, _cursor, statement, *_args):
        executed.append(statement)

    event.listen(db.engine, "before_cursor_execute", capture)
    try:
        with Session(db.engine) as session, session.begin():
            result = PlatformTenantRentalQueryService(
                maximum_execution_time_ms=2_000
            ).get_customer_pii(session, rental_id=main_id)
    finally:
        event.remove(db.engine, "before_cursor_execute", capture)

    assert len(executed) == 1
    assert executed[0].lstrip().upper().startswith("SELECT")
    assert result == {
        "rental_id": main_id,
        "customer": {
            "name": "张三丰",
            "phone": "+86 139-1234-5678",
            "address": {
                "province": "广东省",
                "city": "深圳市",
                "district": "南山区",
                "detail": "科技园秘密地址 101 号",
            },
        },
    }


def test_get_customer_pii_never_returns_child_rental(application) -> None:
    _seed_rentals()
    child_id = db.session.scalar(
        db.select(Rental.id).where(Rental.parent_rental_id.is_not(None))
    )

    with Session(db.engine) as session, session.begin():
        result = PlatformTenantRentalQueryService(
            maximum_execution_time_ms=1_000
        ).get_customer_pii(session, rental_id=child_id)

    assert result is None


@pytest.mark.parametrize("rental_id", ["01", "0", True, "not-a-number"])
def test_get_customer_pii_rejects_noncanonical_id(
    application,
    rental_id,
) -> None:
    with Session(db.engine) as session, session.begin():
        with pytest.raises(PlatformTenantRentalQueryInputError):
            PlatformTenantRentalQueryService(
                maximum_execution_time_ms=500
            ).get_customer_pii(session, rental_id=rental_id)


@pytest.mark.parametrize(
    ("page", "page_size", "status"),
    [
        ("01", "50", None),
        ("0", "50", None),
        ("1", "101", None),
        ("1", "50", "unknown"),
        (True, "50", None),
    ],
)
def test_list_rentals_rejects_noncanonical_or_unbounded_inputs(
    application,
    page,
    page_size,
    status,
) -> None:
    with Session(db.engine) as session, session.begin():
        with pytest.raises(PlatformTenantRentalQueryInputError):
            PlatformTenantRentalQueryService(
                maximum_execution_time_ms=500
            ).list_rentals(
                session,
                page=page,
                page_size=page_size,
                status=status,
            )


def test_query_service_requires_an_active_session(application) -> None:
    session = Session(db.engine)
    try:
        with pytest.raises(TypeError):
            PlatformTenantRentalQueryService(
                maximum_execution_time_ms=500
            ).list_rentals(session, page=1, page_size=1)
    finally:
        session.close()


@pytest.mark.parametrize("timeout", [99, 10_001, True, "1000"])
def test_query_service_rejects_invalid_timeouts(timeout) -> None:
    with pytest.raises(ValueError):
        PlatformTenantRentalQueryService(maximum_execution_time_ms=timeout)
