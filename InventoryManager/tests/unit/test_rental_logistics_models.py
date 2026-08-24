from datetime import date, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app import create_app, db
from app.models.device import Device
from app.models.rental import Rental
from app.models.rental_relay_case import RentalRelayCase
from app.models.warehouse import Warehouse


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


def _ready_default():
    return Warehouse(
        name="默认仓库",
        status="active",
        setup_state="ready",
        is_default=True,
        default_slot=1,
        contact_name="负责人",
        contact_phone="13800138000",
        province="广东省",
        city="深圳市",
        district="南山区",
        address_detail="测试地址 1 号",
    )


def _rental(device, *, start=date(2026, 9, 10), end=date(2026, 9, 12)):
    return Rental(
        device=device,
        start_date=start,
        end_date=end,
        customer_name="测试客户",
    )


def test_planned_and_actual_logistics_facts_are_independent(application):
    warehouse = _ready_default()
    device = Device(name="主设备", warehouse=warehouse)
    rental = _rental(device)
    rental.preferred_warehouse = warehouse
    rental.logistics_days = 0
    rental.planned_ship_out_date = date(2026, 9, 9)
    rental.planned_return_date = date(2026, 9, 13)
    rental.actual_shipped_at = datetime(2026, 9, 9, 8)
    rental.logistics_estimate_origin_warehouse = warehouse
    rental.logistics_estimate_provider = "manual"
    rental.logistics_estimate_rule_version = "core-v1"
    rental.logistics_estimate_days = 0
    db.session.add_all([warehouse, device, rental])
    db.session.commit()

    payload = rental.to_dict()
    assert payload["logistics_days"] == 0
    assert payload["planned_ship_out_date"] == "2026-09-09"
    assert payload["planned_return_date"] == "2026-09-13"
    assert payload["actual_shipped_at"] == "2026-09-09T08:00:00"
    assert payload["actual_returned_at"] is None
    assert rental.ship_out_time is None


@pytest.mark.parametrize("invalid_days", [-1, 8])
def test_logistics_days_database_constraint_rejects_invalid_values(
    application, invalid_days
):
    warehouse = _ready_default()
    device = Device(name="主设备", warehouse=warehouse)
    rental = _rental(device)
    rental.logistics_days = invalid_days
    db.session.add_all([warehouse, device, rental])

    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_partial_or_reversed_planned_window_is_rejected(application):
    warehouse = _ready_default()
    device = Device(name="主设备", warehouse=warehouse)
    rental = _rental(device)
    rental.planned_ship_out_date = date(2026, 9, 13)
    rental.planned_return_date = date(2026, 9, 9)
    db.session.add_all([warehouse, device, rental])

    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_relay_accessory_note_is_separate_from_customer_note(application):
    warehouse = _ready_default()
    device = Device(name="主设备", warehouse=warehouse)
    predecessor = _rental(device)
    successor = _rental(
        device,
        start=date(2026, 9, 15),
        end=date(2026, 9, 17),
    )
    predecessor.customer_note = "客户可见备注"
    relay = RentalRelayCase(
        predecessor=predecessor,
        successor=successor,
        accessory_note="内部线下补寄安排",
        accessory_note_updated_by="user-1",
    )
    db.session.add_all([warehouse, device, predecessor, successor, relay])
    db.session.commit()

    assert predecessor.customer_note == "客户可见备注"
    assert relay.accessory_note == "内部线下补寄安排"
