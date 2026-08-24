from datetime import date

import pytest
from sqlalchemy import event

from app import create_app, db
from app.models.device import Device
from app.models.inspection_record import InspectionRecord
from app.models.rental import Rental
from app.models.warehouse import DeviceWarehouseMovement, Warehouse
from app.services.inspection_service import InspectionService


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


def _rental(device):
    return Rental(
        device=device,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        customer_name="测试客户",
    )


CHECKS = [{"name": "机身外观", "is_checked": True, "order": 1}]


def test_single_ready_warehouse_is_selected_and_move_is_atomic(application):
    warehouse = _warehouse("默认仓", default=True)
    device = Device(name="主设备")
    rental = _rental(device)
    db.session.add_all([warehouse, device, rental])
    db.session.commit()

    record = InspectionService.create_inspection_record_in_warehouse(
        rental_id=rental.id,
        device_id=device.id,
        check_items=CHECKS,
        inspector_user_uuid="user-1",
    )

    db.session.expire_all()
    assert db.session.get(Device, device.id).warehouse_id == warehouse.id
    assert record.warehouse_id == warehouse.id
    movement = DeviceWarehouseMovement.query.one()
    assert movement.source == "inspection"
    assert movement.related_resource_id == str(record.id)


def test_multiple_warehouses_require_explicit_selection(application):
    first = _warehouse("默认仓", default=True)
    second = _warehouse("二号仓")
    device = Device(name="主设备", warehouse=first)
    rental = _rental(device)
    db.session.add_all([first, second, device, rental])
    db.session.commit()

    with pytest.raises(ValueError, match="warehouse_id is required"):
        InspectionService.create_inspection_record_in_warehouse(
            rental_id=rental.id,
            device_id=device.id,
            check_items=CHECKS,
            inspector_user_uuid="user-1",
        )

    assert InspectionRecord.query.count() == 0
    assert db.session.get(Device, device.id).warehouse_id == first.id


def test_editing_an_inspection_does_not_move_device_again(application):
    first = _warehouse("默认仓", default=True)
    second = _warehouse("二号仓")
    device = Device(name="主设备", warehouse=first)
    rental = _rental(device)
    db.session.add_all([first, second, device, rental])
    db.session.commit()
    record = InspectionService.create_inspection_record_in_warehouse(
        rental_id=rental.id,
        device_id=device.id,
        warehouse_id=second.id,
        check_items=CHECKS,
        inspector_user_uuid="user-1",
    )
    check = record.check_items.one()

    device.warehouse_id = first.id
    db.session.commit()
    InspectionService.update_inspection_record(
        record.id,
        [{"id": check.id, "is_checked": False}],
    )

    assert db.session.get(Device, device.id).warehouse_id == first.id
    assert DeviceWarehouseMovement.query.count() == 1


def test_movement_failure_rolls_back_record_items_and_location(application):
    first = _warehouse("默认仓", default=True)
    second = _warehouse("二号仓")
    device = Device(name="主设备", warehouse=first)
    rental = _rental(device)
    db.session.add_all([first, second, device, rental])
    db.session.commit()

    def fail_insert(_mapper, _connection, _target):
        raise RuntimeError("injected movement failure")

    event.listen(DeviceWarehouseMovement, "before_insert", fail_insert)
    try:
        with pytest.raises(RuntimeError, match="injected movement failure"):
            InspectionService.create_inspection_record_in_warehouse(
                rental_id=rental.id,
                device_id=device.id,
                warehouse_id=second.id,
                check_items=CHECKS,
                inspector_user_uuid="user-1",
            )
    finally:
        event.remove(DeviceWarehouseMovement, "before_insert", fail_insert)

    db.session.expire_all()
    assert db.session.get(Device, device.id).warehouse_id == first.id
    assert InspectionRecord.query.count() == 0
    assert DeviceWarehouseMovement.query.count() == 0
