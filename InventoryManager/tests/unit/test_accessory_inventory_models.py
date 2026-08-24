from datetime import datetime, timedelta

import pytest

from app import db
from app.models.accessory_inventory import (
    AccessoryType,
    AccessoryUnit,
    AccessoryUnitEvent,
    RentalAccessoryRequest,
    RentalAccessoryUnitLink,
)
from app.models.device import Device
from app.models.rental import Rental
from app.models.warehouse import Warehouse
from tests.support.test_database import DATABASE_CONSTRAINT_ERRORS


def _facts():
    warehouse = Warehouse(
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
    accessory_type = AccessoryType(
        name="tripod",
        display_name="三脚架",
        tracking_mode="logical_unit",
    )
    device = Device(name="主设备", warehouse=warehouse)
    db.session.add_all([warehouse, accessory_type, device])
    db.session.flush()
    rental = Rental(
        device=device,
        start_date=datetime(2026, 9, 1).date(),
        end_date=datetime(2026, 9, 3).date(),
        customer_name="测试客户",
    )
    unit = AccessoryUnit(
        accessory_type=accessory_type,
        warehouse=warehouse,
    )
    db.session.add_all([rental, unit])
    db.session.flush()
    return warehouse, accessory_type, device, rental, unit


def test_request_link_and_event_capture_separate_facts(application):
    _, accessory_type, device, rental, unit = _facts()
    start_at = datetime(2026, 8, 31, 8)
    request = RentalAccessoryRequest(
        rental=rental,
        accessory_type=accessory_type,
        name_snapshot="三脚架",
    )
    link = RentalAccessoryUnitLink(
        rental=rental,
        accessory_type_id=accessory_type.id,
        accessory_unit_id=unit.id,
        reservation_start_at=start_at,
        reservation_end_at=start_at + timedelta(days=5),
    )
    event = AccessoryUnitEvent(
        unit=unit,
        event_type="linked",
        main_device=device,
        rental=rental,
        actor_type="user",
        actor_id="user-1",
        idempotency_key="link:rental-1:tripod",
    )
    db.session.add_all([request, link, event])
    db.session.commit()

    assert unit.current_holder_rental_id is None
    assert request.name_snapshot == "三脚架"
    assert link.source_relay_case_id is None
    assert not hasattr(unit, "to_dict")


def test_one_rental_cannot_link_two_units_of_same_type(application):
    warehouse, accessory_type, _, rental, first_unit = _facts()
    second_unit = AccessoryUnit(
        accessory_type=accessory_type,
        warehouse=warehouse,
    )
    db.session.add(second_unit)
    db.session.flush()
    start_at = datetime(2026, 8, 31, 8)
    db.session.add_all(
        [
            RentalAccessoryUnitLink(
                rental=rental,
                accessory_type_id=accessory_type.id,
                accessory_unit_id=first_unit.id,
                reservation_start_at=start_at,
                reservation_end_at=start_at + timedelta(days=5),
            ),
            RentalAccessoryUnitLink(
                rental=rental,
                accessory_type_id=accessory_type.id,
                accessory_unit_id=second_unit.id,
                reservation_start_at=start_at,
                reservation_end_at=start_at + timedelta(days=5),
            ),
        ]
    )

    with pytest.raises(DATABASE_CONSTRAINT_ERRORS):
        db.session.commit()
    db.session.rollback()


def test_event_idempotency_is_global_within_tenant_database(application):
    _, _, _, _, unit = _facts()
    db.session.add_all(
        [
            AccessoryUnitEvent(
                unit=unit,
                event_type="created",
                actor_type="system",
                idempotency_key="migration:legacy-1",
            ),
            AccessoryUnitEvent(
                unit=unit,
                event_type="created",
                actor_type="system",
                idempotency_key="migration:legacy-1",
            ),
        ]
    )

    with pytest.raises(DATABASE_CONSTRAINT_ERRORS):
        db.session.commit()
    db.session.rollback()


def test_invalid_unit_condition_is_rejected(application):
    warehouse, accessory_type, _, _, _ = _facts()
    db.session.add(
        AccessoryUnit(
            accessory_type=accessory_type,
            warehouse=warehouse,
            condition_status="available",
        )
    )

    with pytest.raises(DATABASE_CONSTRAINT_ERRORS):
        db.session.commit()
    db.session.rollback()
