import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.device import Device
from app.models.warehouse import Warehouse, WarehousePrinter


def ready_default(name="默认仓库"):
    warehouse = Warehouse.pending_default(contact_phone="13800138000")
    warehouse.mark_ready(
        name=name,
        contact_name="负责人",
        contact_phone="13800138000",
        province="广东省",
        city="深圳市",
        district="南山区",
        address_detail="测试地址 1 号",
    )
    return warehouse


def test_pending_default_can_be_completed_and_assigned_to_device(application):
    warehouse = Warehouse.pending_default(contact_phone="13800138000")
    db.session.add(warehouse)
    db.session.flush()
    assert warehouse.setup_state == "pending"
    assert warehouse.name is None

    warehouse.mark_ready(
        name="默认仓库",
        contact_name="负责人",
        contact_phone="13800138000",
        province="广东省",
        city="深圳市",
        district="南山区",
        address_detail="测试地址 1 号",
    )
    device = Device(name="仓库设备", warehouse=warehouse)
    db.session.add(device)
    db.session.commit()

    assert warehouse.setup_state == "ready"
    assert device.warehouse_id == warehouse.id
    assert device.to_dict()["warehouse_id"] == warehouse.id


def test_only_one_default_warehouse_is_allowed(application):
    db.session.add(ready_default("默认仓库 A"))
    db.session.commit()
    db.session.add(ready_default("默认仓库 B"))

    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_one_printer_cannot_bind_multiple_warehouses(application):
    first = ready_default()
    second = Warehouse(
        name="二号仓",
        status="active",
        setup_state="ready",
        is_default=False,
        default_slot=None,
        contact_name="负责人",
        contact_phone="13800138000",
        province="广东省",
        city="深圳市",
        district="福田区",
        address_detail="测试地址 2 号",
    )
    db.session.add_all([first, second])
    db.session.flush()
    db.session.add(
        WarehousePrinter(
            warehouse=first,
            printer_sn="KM-TEST-001",
            display_name="一号打印机",
        )
    )
    db.session.commit()
    db.session.add(
        WarehousePrinter(
            warehouse=second,
            printer_sn="KM-TEST-001",
            display_name="重复打印机",
        )
    )

    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_ready_transition_rejects_blank_required_fields():
    warehouse = Warehouse.pending_default()

    with pytest.raises(ValueError, match="non-empty"):
        warehouse.mark_ready(
            name=" ",
            contact_name="负责人",
            contact_phone="13800138000",
            province="广东省",
            city="深圳市",
            district="南山区",
            address_detail="测试地址 1 号",
        )
