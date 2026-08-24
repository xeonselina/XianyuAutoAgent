from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.exc import IntegrityError

from app import db
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
from app.models.rental_relay_case import RentalRelayCase
from app.models.shipping_execution import OutboundShipment
from app.models.warehouse import (
    DeviceWarehouseMovement,
    UserWarehousePreference,
    Warehouse,
)
from app.services.shipping_execution_service import (
    ShippingExecutionService,
    ShippingSnapshotMismatchError,
)
from app.services.warehouse_service import (
    AccessoryMoveReassignmentUnsupportedError,
    DefaultWarehouseProtectedError,
    DeviceSerialNumberConflictError,
    MoveConfirmationRequiredError,
    SameWarehouseMoveError,
    StaleDeviceWarehouseError,
    UnsupportedDeviceMoveError,
    WarehouseService,
    WarehousePersistenceError,
    WarehouseInventoryPresentError,
    WarehouseServiceError,
    WarehouseUnavailableError,
)


def ready_warehouse(name, *, is_default=False):
    warehouse = Warehouse(
        status="active",
        setup_state="pending",
        is_default=is_default,
        default_slot=1 if is_default else None,
    )
    warehouse.mark_ready(
        name=name,
        contact_name="负责人",
        contact_phone="13800138000",
        province="广东省",
        city="深圳市",
        district="南山区",
        address_detail=f"{name}测试地址",
    )
    return warehouse


def rental_for(device, *, status="not_shipped", days_from_today=2, parent=None):
    start_date = date.today() + timedelta(days=days_from_today)
    return Rental(
        device=device,
        parent_rental=parent,
        start_date=start_date,
        end_date=start_date + timedelta(days=2),
        customer_name="测试客户",
        customer_phone="13800138000",
        destination="北京市",
        ship_out_time=datetime.combine(start_date, datetime.min.time()),
        ship_in_time=datetime.combine(
            start_date + timedelta(days=2), datetime.min.time()
        ),
        scheduled_ship_time=datetime.combine(
            start_date - timedelta(days=1), datetime.min.time()
        ),
        ship_out_tracking_no="ORIGINAL-OUT",
        ship_in_tracking_no="ORIGINAL-IN",
        xianyu_order_no=f"ORDER-{days_from_today}",
        logistics_days=1,
        planned_ship_out_date=start_date - timedelta(days=1),
        planned_return_date=start_date + timedelta(days=3),
        logistics_estimate_origin_warehouse_id=device.warehouse_id,
        logistics_estimate_provider="rule",
        logistics_estimate_provider_version="provider-v1",
        logistics_estimate_rule_version="rule-v1",
        logistics_estimate_days=1,
        logistics_estimate_evaluated_at=datetime(2026, 8, 22, 1, 2, 3),
        logistics_estimate_address_digest="a" * 64,
        logistics_estimate_address_summary="北京市",
        status=status,
    )


def logical_type(name="battery", display_name="电池"):
    return AccessoryType(
        name=name,
        display_name=display_name,
        tracking_mode="logical_unit",
        is_active=True,
    )


def unit_for(accessory_type, warehouse, *, unit_id=None, holder=None):
    return AccessoryUnit(
        id=unit_id or str(uuid4()),
        accessory_type=accessory_type,
        warehouse=warehouse,
        current_holder_rental=holder,
        condition_status="active",
    )


def request_for(rental, accessory_type, *, name=None):
    return RentalAccessoryRequest(
        rental=rental,
        accessory_type=accessory_type,
        name_snapshot=name or accessory_type.display_name,
    )


def link_for(rental, accessory_type, unit):
    return RentalAccessoryUnitLink(
        rental=rental,
        accessory_type_id=accessory_type.id,
        accessory_unit=unit,
        reservation_start_at=datetime.combine(
            rental.planned_ship_out_date,
            datetime.min.time(),
        ),
        reservation_end_at=datetime.combine(
            rental.planned_return_date + timedelta(days=1),
            datetime.min.time(),
        ),
    )


def execute_previewed(device, target, *, actor_user_id="user-1", note=None):
    preview = WarehouseService.preview_device_move(
        device_id=device.id,
        target_warehouse_id=target.id,
    )
    return WarehouseService.execute_device_move(
        device_id=device.id,
        target_warehouse_id=target.id,
        expected_current_warehouse_id=preview.device.warehouse_id,
        expected_preview_revision=preview.revision,
        confirmation_token_confirmed=True,
        actor_user_id=actor_user_id,
        note=note,
    )


def submitted_shipment_for(rental, warehouse):
    return OutboundShipment(
        provider="sf",
        rental=rental,
        origin_warehouse=warehouse,
        origin_warehouse_uuid=warehouse.warehouse_uuid,
        integration_uuid=str(uuid4()),
        provider_account_uuid=str(uuid4()),
        integration_secret_revision_uuid=str(uuid4()),
        provider_account_secret_revision_uuid=str(uuid4()),
        binding_revision=1,
        account_masked_hint="****1234",
        sender_snapshot={"name": "sender"},
        receiver_snapshot={"name": "receiver"},
        cargo_snapshot={"items": [{"name": "租赁设备", "count": 1}]},
        tracking_check_phone_last4="8000",
        express_type_id=2,
        scheduled_dispatch_at=datetime(2026, 8, 22, 1),
        provider_order_id=f"ORDER-{uuid4()}",
        request_hash="b" * 64,
        waybill_no=f"SF{uuid4().hex[:16]}",
        status="submitted",
        submitted_at=datetime(2026, 8, 22, 2, 3, 4),
    )


def test_create_ready_non_default_warehouse_and_list_only_active(application):
    default = ready_warehouse("默认仓", is_default=True)
    inactive = ready_warehouse("停用仓")
    inactive.status = "inactive"
    pending = Warehouse.pending_default()
    pending.is_default = False
    pending.default_slot = None
    db.session.add_all([default, inactive, pending])
    db.session.commit()

    created = WarehouseService.create_ready_warehouse(
        name="二号仓",
        contact_name=" 二号负责人 ",
        contact_phone=" 13900139000 ",
        province=" 广东省 ",
        city=" 深圳市 ",
        district=" 福田区 ",
        address_detail=" 测试地址 2 号 ",
    )
    listed = WarehouseService.list_active_warehouses()

    assert created.status == "active"
    assert created.setup_state == "ready"
    assert created.is_default is False
    assert created.default_slot is None
    assert created.contact_name == "二号负责人"
    assert [warehouse.id for warehouse in listed] == [
        default.id,
        pending.id,
        created.id,
    ]
    assert inactive not in listed


def test_pending_default_setup_edit_and_management_listing(application):
    pending = Warehouse.pending_default(contact_phone="13800138000")
    inactive = ready_warehouse("历史仓")
    inactive.status = "inactive"
    db.session.add_all((pending, inactive))
    db.session.commit()

    configured = WarehouseService.setup_default_warehouse(
        name=" 默认仓库 ",
        contact_name=" 管理员 ",
        contact_phone=" 13800138001 ",
        province=" 广东省 ",
        city=" 深圳市 ",
        district=" 南山区 ",
        address_detail=" 测试路 1 号 ",
    )
    edited = WarehouseService.update_warehouse(
        warehouse_id=configured.id,
        name="默认仓（已确认）",
        contact_name="仓库负责人",
        contact_phone="13800138002",
        province="广东省",
        city="深圳市",
        district="福田区",
        address_detail="测试路 2 号",
    )

    assert configured.id == pending.id
    assert edited.setup_state == "ready"
    assert edited.contact_phone == "13800138002"
    assert WarehouseService.get_default_warehouse().id == pending.id
    assert [row.id for row in WarehouseService.list_warehouses()] == [
        pending.id,
        inactive.id,
    ]


def test_main_device_creation_defaults_or_explicitly_assigns_ready_warehouse(
    application,
):
    default = ready_warehouse("默认仓", is_default=True)
    second = ready_warehouse("二号仓")
    model = DeviceModel(
        name="x300u",
        display_name="VIVO X300 Ultra",
        is_active=True,
        is_accessory=False,
    )
    db.session.add_all((default, second, model))
    db.session.commit()

    default_device = WarehouseService.create_main_device(
        name=" X300-01 ",
        serial_number=" SN-001 ",
        model_id=model.id,
    )
    second_device = WarehouseService.create_main_device(
        name="X300-02",
        serial_number="SN-002",
        model_id=model.id,
        warehouse_id=second.id,
    )

    assert default_device.warehouse_id == default.id
    assert second_device.warehouse_id == second.id
    assert default_device.model == "x300u"
    assert default_device.is_accessory is False
    with pytest.raises(DeviceSerialNumberConflictError):
        WarehouseService.create_main_device(
            name="重复序列号",
            serial_number="SN-001",
            model_id=model.id,
        )


def test_default_transfer_and_deactivation_preserve_history(application):
    current = ready_warehouse("当前默认仓", is_default=True)
    replacement = ready_warehouse("新默认仓")
    historical = ready_warehouse("历史仓")
    retired_device = Device(
        name="已退役设备",
        warehouse=historical,
        lifecycle_status="retired",
    )
    db.session.add_all((current, replacement, historical, retired_device))
    db.session.commit()

    with pytest.raises(DefaultWarehouseProtectedError):
        WarehouseService.deactivate_warehouse(warehouse_id=current.id)

    selected = WarehouseService.set_default_warehouse(warehouse_id=replacement.id)
    deactivated_current = WarehouseService.deactivate_warehouse(warehouse_id=current.id)
    deactivated_historical = WarehouseService.deactivate_warehouse(
        warehouse_id=historical.id
    )

    assert selected.id == replacement.id
    assert selected.default_slot == 1
    assert deactivated_current.status == "inactive"
    assert deactivated_historical.status == "inactive"
    assert db.session.get(Device, retired_device.id).warehouse_id == historical.id


def test_deactivation_rejects_current_serviceable_inventory(application):
    default = ready_warehouse("默认仓", is_default=True)
    occupied = ready_warehouse("在用仓")
    device = Device(name="在用设备", warehouse=occupied)
    db.session.add_all((default, occupied, device))
    db.session.commit()

    with pytest.raises(WarehouseInventoryPresentError):
        WarehouseService.deactivate_warehouse(warehouse_id=occupied.id)

    assert db.session.get(Warehouse, occupied.id).status == "active"


def test_user_warehouse_preference_uses_ready_warehouse(application):
    default = ready_warehouse("默认仓", is_default=True)
    second = ready_warehouse("二号仓")
    db.session.add_all((default, second))
    db.session.commit()

    first = WarehouseService.set_user_warehouse_preference(
        user_id="user-1",
        scene="booking",
        warehouse_id=default.id,
    )
    second_result = WarehouseService.set_user_warehouse_preference(
        user_id="user-1",
        scene="booking",
        warehouse_id=second.id,
    )

    assert first.user_id == "user-1"
    assert second_result.warehouse_id == second.id
    assert UserWarehousePreference.query.count() == 1


def test_explicit_tenant_session_requires_caller_transaction(application):
    session = db.session()

    with pytest.raises(WarehouseServiceError):
        WarehouseService.create_ready_warehouse(
            name="二号仓",
            contact_name="负责人",
            contact_phone="13800138000",
            province="广东省",
            city="深圳市",
            district="南山区",
            address_detail="测试地址",
            tenant_session=session,
        )

    assert Warehouse.query.count() == 0


def test_explicit_tenant_session_never_commits_caller_transaction(application):
    session = db.session()

    with pytest.raises(RuntimeError):
        with session.begin():
            created = WarehouseService.create_ready_warehouse(
                name="二号仓",
                contact_name="负责人",
                contact_phone="13800138000",
                province="广东省",
                city="深圳市",
                district="南山区",
                address_detail="测试地址",
                tenant_session=session,
            )
            assert created.id is not None
            raise RuntimeError("outer transaction rollback")

    assert Warehouse.query.count() == 0


def test_preview_is_immutable_and_lists_only_future_incomplete_main_rentals(
    application,
):
    current = ready_warehouse("当前仓", is_default=True)
    target = ready_warehouse("目标仓")
    device = Device(name="主设备", warehouse=current, is_accessory=False)
    child_device = Device(
        name="历史附件设备",
        warehouse=current,
        is_accessory=True,
    )
    db.session.add_all([current, target, device, child_device])
    db.session.flush()

    affected = rental_for(device, status="not_shipped", days_from_today=2)
    returned = rental_for(device, status="returned", days_from_today=8)
    completed = rental_for(device, status="completed", days_from_today=3)
    past = rental_for(device, status="not_shipped", days_from_today=-10)
    past.end_date = date.today() - timedelta(days=1)
    child = rental_for(
        child_device,
        status="not_shipped",
        days_from_today=4,
        parent=affected,
    )
    accessory_type = logical_type()
    db.session.add_all([affected, returned, completed, past, child, accessory_type])
    db.session.flush()
    source_unit = unit_for(accessory_type, current)
    db.session.add_all(
        [
            source_unit,
            request_for(affected, accessory_type),
        ]
    )
    db.session.flush()
    source_link = link_for(affected, accessory_type, source_unit)
    db.session.add(source_link)
    db.session.commit()

    preview = WarehouseService.preview_device_move(
        device_id=device.id,
        target_warehouse_id=target.id,
    )

    assert preview.device.id == device.id
    assert preview.current_warehouse.id == current.id
    assert preview.target_warehouse.id == target.id
    assert preview.is_same_warehouse is False
    assert preview.affected_rental_ids == (affected.id,)
    assert len(preview.revision) == 64
    assert set(preview.revision) <= set("0123456789abcdef")
    assert source_unit.id not in repr(preview)
    assert preview.preserves_logistics_facts is True
    assert preview.affected_rentals[0].order_number == affected.xianyu_order_no
    assert preview.affected_rentals[0].customer_start_date == affected.start_date
    assert preview.affected_rentals[0].customer_end_date == affected.end_date
    assert preview.affected_rentals[0].logistics_days == 1
    assert (
        preview.affected_rentals[0].planned_ship_out_date
        == affected.planned_ship_out_date
    )
    assert (
        preview.affected_rentals[0].planned_return_date == affected.planned_return_date
    )
    assert len(preview.affected_rentals[0].affected_accessory_types) == 1
    assert (
        preview.affected_rentals[0].affected_accessory_types[0].accessory_type_id
        == accessory_type.id
    )
    assert preview.affected_rentals[0].affected_accessory_types[0].name == "电池"
    with pytest.raises(FrozenInstanceError):
        preview.is_same_warehouse = True


def test_execute_rejects_stale_expected_warehouse(application):
    current = ready_warehouse("当前仓", is_default=True)
    target = ready_warehouse("目标仓")
    device = Device(name="主设备", warehouse=current)
    db.session.add_all([current, target, device])
    db.session.commit()
    preview = WarehouseService.preview_device_move(
        device_id=device.id,
        target_warehouse_id=target.id,
    )

    with pytest.raises(StaleDeviceWarehouseError):
        WarehouseService.execute_device_move(
            device_id=device.id,
            target_warehouse_id=target.id,
            expected_current_warehouse_id=target.id,
            expected_preview_revision=preview.revision,
            confirmation_token_confirmed=True,
            actor_user_id="user-1",
        )

    assert db.session.get(Device, device.id).warehouse_id == current.id
    assert DeviceWarehouseMovement.query.count() == 0


@pytest.mark.parametrize(
    ("status", "setup_state"),
    [("inactive", "ready"), ("active", "pending")],
)
def test_execute_rejects_inactive_or_pending_target(application, status, setup_state):
    current = ready_warehouse("当前仓", is_default=True)
    target = ready_warehouse("目标仓")
    target.status = status
    target.setup_state = setup_state
    if setup_state == "pending":
        target.name = None
        target.contact_name = None
        target.contact_phone = None
        target.province = None
        target.city = None
        target.district = None
        target.address_detail = None
    device = Device(name="主设备", warehouse=current)
    db.session.add_all([current, target, device])
    db.session.commit()
    preview = WarehouseService.preview_device_move(
        device_id=device.id,
        target_warehouse_id=target.id,
    )

    with pytest.raises(WarehouseUnavailableError):
        WarehouseService.execute_device_move(
            device_id=device.id,
            target_warehouse_id=target.id,
            expected_current_warehouse_id=current.id,
            expected_preview_revision=preview.revision,
            confirmation_token_confirmed=True,
            actor_user_id="user-1",
        )

    assert db.session.get(Device, device.id).warehouse_id == current.id
    assert DeviceWarehouseMovement.query.count() == 0


def test_execute_requires_strict_boolean_confirmation(application):
    current = ready_warehouse("当前仓", is_default=True)
    target = ready_warehouse("目标仓")
    device = Device(name="主设备", warehouse=current)
    db.session.add_all([current, target, device])
    db.session.commit()
    preview = WarehouseService.preview_device_move(
        device_id=device.id,
        target_warehouse_id=target.id,
    )

    for confirmation in (False, None, 1, "true"):
        with pytest.raises(MoveConfirmationRequiredError):
            WarehouseService.execute_device_move(
                device_id=device.id,
                target_warehouse_id=target.id,
                expected_current_warehouse_id=current.id,
                expected_preview_revision=preview.revision,
                confirmation_token_confirmed=confirmation,
                actor_user_id="user-1",
            )

    assert db.session.get(Device, device.id).warehouse_id == current.id
    assert DeviceWarehouseMovement.query.count() == 0


def test_execute_rejects_same_warehouse(application):
    warehouse = ready_warehouse("当前仓", is_default=True)
    device = Device(name="主设备", warehouse=warehouse)
    db.session.add_all([warehouse, device])
    db.session.commit()

    preview = WarehouseService.preview_device_move(
        device_id=device.id,
        target_warehouse_id=warehouse.id,
    )
    assert preview.is_same_warehouse is True

    with pytest.raises(SameWarehouseMoveError):
        WarehouseService.execute_device_move(
            device_id=device.id,
            target_warehouse_id=warehouse.id,
            expected_current_warehouse_id=warehouse.id,
            expected_preview_revision=preview.revision,
            confirmation_token_confirmed=True,
            actor_user_id="user-1",
        )

    assert DeviceWarehouseMovement.query.count() == 0


def test_move_rejects_legacy_accessory_device_fail_closed(application):
    current = ready_warehouse("当前仓", is_default=True)
    target = ready_warehouse("目标仓")
    device = Device(
        name="旧序列化附件",
        warehouse=current,
        is_accessory=True,
    )
    db.session.add_all([current, target, device])
    db.session.commit()

    with pytest.raises(UnsupportedDeviceMoveError):
        WarehouseService.preview_device_move(
            device_id=device.id,
            target_warehouse_id=target.id,
        )
    db.session.rollback()
    with pytest.raises(UnsupportedDeviceMoveError):
        WarehouseService.execute_device_move(
            device_id=device.id,
            target_warehouse_id=target.id,
            expected_current_warehouse_id=current.id,
            expected_preview_revision="0" * 64,
            confirmation_token_confirmed=True,
            actor_user_id="user-1",
        )

    assert db.session.get(Device, device.id).warehouse_id == current.id
    assert DeviceWarehouseMovement.query.count() == 0


def test_execute_rolls_back_location_when_movement_insert_fails(application):
    current = ready_warehouse("当前仓", is_default=True)
    target = ready_warehouse("目标仓")
    device = Device(name="主设备", warehouse=current)
    db.session.add_all([current, target, device])
    db.session.commit()
    preview = WarehouseService.preview_device_move(
        device_id=device.id,
        target_warehouse_id=target.id,
    )

    def fail_movement_insert(_mapper, _connection, _target):
        raise RuntimeError("injected movement failure")

    event.listen(DeviceWarehouseMovement, "before_insert", fail_movement_insert)
    try:
        with pytest.raises(RuntimeError, match="injected movement failure"):
            WarehouseService.execute_device_move(
                device_id=device.id,
                target_warehouse_id=target.id,
                expected_current_warehouse_id=current.id,
                expected_preview_revision=preview.revision,
                confirmation_token_confirmed=True,
                actor_user_id="user-1",
            )
    finally:
        event.remove(DeviceWarehouseMovement, "before_insert", fail_movement_insert)

    db.session.expire_all()
    assert db.session.get(Device, device.id).warehouse_id == current.id
    assert DeviceWarehouseMovement.query.count() == 0


def test_execute_commits_location_history_and_coordination_ids_only(application):
    current = ready_warehouse("当前仓", is_default=True)
    target = ready_warehouse("目标仓")
    device = Device(name="主设备", warehouse=current)
    db.session.add_all([current, target, device])
    db.session.flush()
    rental = rental_for(device, status="not_shipped", days_from_today=5)
    db.session.add(rental)
    db.session.commit()
    original_logistics = {
        "start_date": rental.start_date,
        "end_date": rental.end_date,
        "ship_out_time": rental.ship_out_time,
        "ship_in_time": rental.ship_in_time,
        "scheduled_ship_time": rental.scheduled_ship_time,
        "ship_out_tracking_no": rental.ship_out_tracking_no,
        "ship_in_tracking_no": rental.ship_in_tracking_no,
        "preferred_warehouse_id": rental.preferred_warehouse_id,
        "logistics_days": rental.logistics_days,
        "planned_ship_out_date": rental.planned_ship_out_date,
        "planned_return_date": rental.planned_return_date,
        "actual_shipped_at": rental.actual_shipped_at,
        "actual_returned_at": rental.actual_returned_at,
        "logistics_estimate_origin_warehouse_id": (
            rental.logistics_estimate_origin_warehouse_id
        ),
        "logistics_estimate_provider": rental.logistics_estimate_provider,
        "logistics_estimate_provider_version": (
            rental.logistics_estimate_provider_version
        ),
        "logistics_estimate_rule_version": (rental.logistics_estimate_rule_version),
        "logistics_estimate_days": rental.logistics_estimate_days,
        "logistics_estimate_evaluated_at": (rental.logistics_estimate_evaluated_at),
        "logistics_estimate_address_digest": (rental.logistics_estimate_address_digest),
        "logistics_estimate_address_summary": (
            rental.logistics_estimate_address_summary
        ),
        "status": rental.status,
    }
    preview = WarehouseService.preview_device_move(
        device_id=device.id,
        target_warehouse_id=target.id,
    )

    result = WarehouseService.execute_device_move(
        device_id=device.id,
        target_warehouse_id=target.id,
        expected_current_warehouse_id=current.id,
        expected_preview_revision=preview.revision,
        confirmation_token_confirmed=True,
        actor_user_id=" user-1 ",
        note="人工盘点后调整",
    )

    db.session.expire_all()
    stored_device = db.session.get(Device, device.id)
    movement = db.session.get(DeviceWarehouseMovement, result.movement_id)
    stored_rental = db.session.get(Rental, rental.id)
    assert stored_device.warehouse_id == target.id
    assert movement.device_id == device.id
    assert movement.from_warehouse_id == current.id
    assert movement.to_warehouse_id == target.id
    assert movement.source == "manual_change"
    assert movement.actor_user_id == "user-1"
    assert movement.note == "人工盘点后调整"
    assert result.affected_rental_ids == (rental.id,)
    assert {
        "start_date": stored_rental.start_date,
        "end_date": stored_rental.end_date,
        "ship_out_time": stored_rental.ship_out_time,
        "ship_in_time": stored_rental.ship_in_time,
        "scheduled_ship_time": stored_rental.scheduled_ship_time,
        "ship_out_tracking_no": stored_rental.ship_out_tracking_no,
        "ship_in_tracking_no": stored_rental.ship_in_tracking_no,
        "preferred_warehouse_id": stored_rental.preferred_warehouse_id,
        "logistics_days": stored_rental.logistics_days,
        "planned_ship_out_date": stored_rental.planned_ship_out_date,
        "planned_return_date": stored_rental.planned_return_date,
        "actual_shipped_at": stored_rental.actual_shipped_at,
        "actual_returned_at": stored_rental.actual_returned_at,
        "logistics_estimate_origin_warehouse_id": (
            stored_rental.logistics_estimate_origin_warehouse_id
        ),
        "logistics_estimate_provider": stored_rental.logistics_estimate_provider,
        "logistics_estimate_provider_version": (
            stored_rental.logistics_estimate_provider_version
        ),
        "logistics_estimate_rule_version": (
            stored_rental.logistics_estimate_rule_version
        ),
        "logistics_estimate_days": stored_rental.logistics_estimate_days,
        "logistics_estimate_evaluated_at": (
            stored_rental.logistics_estimate_evaluated_at
        ),
        "logistics_estimate_address_digest": (
            stored_rental.logistics_estimate_address_digest
        ),
        "logistics_estimate_address_summary": (
            stored_rental.logistics_estimate_address_summary
        ),
        "status": stored_rental.status,
    } == original_logistics


def test_execute_reassigns_future_link_to_target_and_appends_events(application):
    current = ready_warehouse("当前仓", is_default=True)
    target = ready_warehouse("目标仓")
    device = Device(name="主设备", warehouse=current)
    accessory_type = logical_type()
    db.session.add_all([current, target, device, accessory_type])
    db.session.flush()
    rental = rental_for(device, days_from_today=5)
    source_unit = unit_for(
        accessory_type,
        current,
        unit_id="10000000-0000-0000-0000-000000000001",
    )
    target_unit = unit_for(
        accessory_type,
        target,
        unit_id="20000000-0000-0000-0000-000000000001",
    )
    db.session.add_all(
        [
            rental,
            source_unit,
            target_unit,
            request_for(rental, accessory_type),
        ]
    )
    db.session.flush()
    old_link = link_for(rental, accessory_type, source_unit)
    db.session.add(old_link)
    db.session.commit()
    old_link_id = old_link.id

    result = execute_previewed(device, target)

    db.session.expire_all()
    links = (
        db.session.execute(
            select(RentalAccessoryUnitLink).where(
                RentalAccessoryUnitLink.rental_id == rental.id
            )
        )
        .scalars()
        .all()
    )
    events = (
        db.session.execute(
            select(AccessoryUnitEvent)
            .where(AccessoryUnitEvent.rental_id == rental.id)
            .order_by(AccessoryUnitEvent.event_type.asc())
        )
        .scalars()
        .all()
    )
    assert db.session.get(Device, device.id).warehouse_id == target.id
    assert len(links) == 1
    assert links[0].id != old_link_id
    assert links[0].accessory_unit_id == target_unit.id
    assert (links[0].reservation_start_at, links[0].reservation_end_at) == (
        datetime.combine(rental.planned_ship_out_date, datetime.min.time()),
        datetime.combine(
            rental.planned_return_date + timedelta(days=1),
            datetime.min.time(),
        ),
    )
    assert [row.event_type for row in events] == ["linked", "unlinked"]
    assert {row.unit_id for row in events} == {source_unit.id, target_unit.id}
    assert all(row.reason == "device_warehouse_reassignment" for row in events)
    assert all(result.movement_id in row.idempotency_key for row in events)
    assert all(source_unit.id not in row.idempotency_key for row in events)
    assert all(target_unit.id not in row.idempotency_key for row in events)
    assert len(result.accessory_fulfillment) == 1
    assert result.accessory_fulfillment[0].rental_id == rental.id
    assert result.accessory_fulfillment[0].accessory_type_id == accessory_type.id
    assert result.accessory_fulfillment[0].status == "fulfilled"


def test_execute_shortage_keeps_request_without_link_and_moves_device(application):
    current = ready_warehouse("当前仓", is_default=True)
    target = ready_warehouse("目标仓")
    device = Device(name="主设备", warehouse=current)
    accessory_type = logical_type()
    db.session.add_all([current, target, device, accessory_type])
    db.session.flush()
    rental = rental_for(device, days_from_today=5)
    source_unit = unit_for(accessory_type, current)
    request = request_for(rental, accessory_type)
    db.session.add_all([rental, source_unit, request])
    db.session.flush()
    db.session.add(link_for(rental, accessory_type, source_unit))
    db.session.commit()

    result = execute_previewed(device, target)

    db.session.expire_all()
    assert db.session.get(Device, device.id).warehouse_id == target.id
    assert (
        db.session.get(
            RentalAccessoryRequest,
            (rental.id, accessory_type.id),
        )
        is not None
    )
    assert RentalAccessoryUnitLink.query.filter_by(rental_id=rental.id).count() == 0
    assert (
        AccessoryUnitEvent.query.filter_by(
            rental_id=rental.id,
            event_type="unlinked",
        ).count()
        == 1
    )
    assert result.accessory_fulfillment[0].status == "shortage"


def test_execute_chooses_candidate_units_in_stable_type_and_id_order(application):
    current = ready_warehouse("当前仓", is_default=True)
    target = ready_warehouse("目标仓")
    device = Device(name="主设备", warehouse=current)
    accessory_type = logical_type()
    db.session.add_all([current, target, device, accessory_type])
    db.session.flush()
    rental = rental_for(device, days_from_today=5)
    later = unit_for(
        accessory_type,
        target,
        unit_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
    )
    first = unit_for(
        accessory_type,
        target,
        unit_id="00000000-0000-0000-0000-000000000001",
    )
    db.session.add_all([rental, later, first, request_for(rental, accessory_type)])
    db.session.commit()

    execute_previewed(device, target)

    link = RentalAccessoryUnitLink.query.filter_by(rental_id=rental.id).one()
    assert link.accessory_unit_id == first.id


def test_execute_rolls_back_device_movement_links_and_events_together(application):
    current = ready_warehouse("当前仓", is_default=True)
    target = ready_warehouse("目标仓")
    device = Device(name="主设备", warehouse=current)
    accessory_type = logical_type()
    db.session.add_all([current, target, device, accessory_type])
    db.session.flush()
    rental = rental_for(device, days_from_today=5)
    source_unit = unit_for(accessory_type, current)
    target_unit = unit_for(accessory_type, target)
    db.session.add_all(
        [
            rental,
            source_unit,
            target_unit,
            request_for(rental, accessory_type),
        ]
    )
    db.session.flush()
    old_link = link_for(rental, accessory_type, source_unit)
    db.session.add(old_link)
    db.session.commit()
    old_link_id = old_link.id
    preview = WarehouseService.preview_device_move(
        device_id=device.id,
        target_warehouse_id=target.id,
    )

    def fail_event_insert(_mapper, _connection, _target):
        raise IntegrityError(
            "injected accessory event failure",
            {"unit_id": source_unit.id},
            RuntimeError("injected"),
        )

    event.listen(AccessoryUnitEvent, "before_insert", fail_event_insert)
    try:
        with pytest.raises(WarehousePersistenceError) as exc_info:
            WarehouseService.execute_device_move(
                device_id=device.id,
                target_warehouse_id=target.id,
                expected_current_warehouse_id=current.id,
                expected_preview_revision=preview.revision,
                confirmation_token_confirmed=True,
                actor_user_id="user-1",
            )
    finally:
        event.remove(AccessoryUnitEvent, "before_insert", fail_event_insert)

    assert exc_info.value.__cause__ is None
    assert source_unit.id not in str(exc_info.value)
    db.session.expire_all()
    assert db.session.get(Device, device.id).warehouse_id == current.id
    assert DeviceWarehouseMovement.query.count() == 0
    assert AccessoryUnitEvent.query.count() == 0
    stored_link = db.session.get(RentalAccessoryUnitLink, old_link_id)
    assert stored_link is not None
    assert stored_link.accessory_unit_id == source_unit.id


@pytest.mark.parametrize("rental_status", ["shipped", "returned"])
def test_execute_does_not_reassign_shipped_or_returned_rentals(
    application,
    rental_status,
):
    current = ready_warehouse("当前仓", is_default=True)
    target = ready_warehouse("目标仓")
    device = Device(name="主设备", warehouse=current)
    accessory_type = logical_type()
    db.session.add_all([current, target, device, accessory_type])
    db.session.flush()
    rental = rental_for(
        device,
        status=rental_status,
        days_from_today=5,
    )
    source_unit = unit_for(accessory_type, current, holder=rental)
    target_unit = unit_for(accessory_type, target)
    db.session.add_all(
        [
            rental,
            source_unit,
            target_unit,
            request_for(rental, accessory_type),
        ]
    )
    db.session.flush()
    old_link = link_for(rental, accessory_type, source_unit)
    db.session.add(old_link)
    db.session.commit()
    old_link_id = old_link.id

    result = execute_previewed(device, target)

    db.session.expire_all()
    assert result.affected_rental_ids == ()
    assert result.accessory_fulfillment == ()
    assert db.session.get(Device, device.id).warehouse_id == target.id
    assert db.session.get(RentalAccessoryUnitLink, old_link_id) is not None
    assert AccessoryUnitEvent.query.count() == 0


def test_execute_rejects_relay_link_and_rolls_back_entire_move(application):
    current = ready_warehouse("当前仓", is_default=True)
    target = ready_warehouse("目标仓")
    device = Device(name="主设备", warehouse=current)
    next_device = Device(name="下一台设备", warehouse=current)
    accessory_type = logical_type()
    db.session.add_all([current, target, device, next_device, accessory_type])
    db.session.flush()
    rental = rental_for(device, days_from_today=5)
    successor = rental_for(next_device, days_from_today=10)
    source_unit = unit_for(accessory_type, current)
    target_unit = unit_for(accessory_type, target)
    db.session.add_all(
        [
            rental,
            successor,
            source_unit,
            target_unit,
            request_for(rental, accessory_type),
        ]
    )
    db.session.flush()
    relay = RentalRelayCase(
        predecessor_rental_id=rental.id,
        successor_rental_id=successor.id,
        status="agreed",
    )
    db.session.add(relay)
    db.session.flush()
    old_link = link_for(rental, accessory_type, source_unit)
    old_link.source_relay_case = relay
    db.session.add(old_link)
    db.session.commit()
    old_link_id = old_link.id
    preview = WarehouseService.preview_device_move(
        device_id=device.id,
        target_warehouse_id=target.id,
    )

    with pytest.raises(AccessoryMoveReassignmentUnsupportedError):
        WarehouseService.execute_device_move(
            device_id=device.id,
            target_warehouse_id=target.id,
            expected_current_warehouse_id=current.id,
            expected_preview_revision=preview.revision,
            confirmation_token_confirmed=True,
            actor_user_id="user-1",
        )

    db.session.expire_all()
    assert db.session.get(Device, device.id).warehouse_id == current.id
    assert db.session.get(RentalAccessoryUnitLink, old_link_id) is not None
    assert DeviceWarehouseMovement.query.count() == 0
    assert AccessoryUnitEvent.query.count() == 0


@pytest.mark.parametrize(
    ("has_target_unit", "expected_status"),
    ((True, "fulfilled"), (False, "shortage")),
)
def test_execute_reuses_chain_solver_for_requestless_relay_successor(
    application,
    has_target_unit,
    expected_status,
):
    current = ready_warehouse("当前仓", is_default=True)
    target = ready_warehouse("目标仓")
    device = Device(name="接力主设备", warehouse=current)
    accessory_type = logical_type()
    db.session.add_all((current, target, device, accessory_type))
    db.session.flush()
    predecessor = rental_for(device, days_from_today=5)
    successor = rental_for(device, days_from_today=10)
    source_unit = unit_for(accessory_type, current)
    target_unit = unit_for(accessory_type, target) if has_target_unit else None
    seeded = [
        predecessor,
        successor,
        source_unit,
        request_for(predecessor, accessory_type),
    ]
    if target_unit is not None:
        seeded.append(target_unit)
    db.session.add_all(seeded)
    db.session.flush()
    relay = RentalRelayCase(
        predecessor_rental_id=predecessor.id,
        successor_rental_id=successor.id,
        status="agreed",
    )
    db.session.add(relay)
    db.session.flush()
    predecessor_link = link_for(predecessor, accessory_type, source_unit)
    successor_link = link_for(successor, accessory_type, source_unit)
    successor_link.source_relay_case = relay
    db.session.add_all((predecessor_link, successor_link))
    db.session.commit()

    result = execute_previewed(device, target)

    db.session.expire_all()
    links = tuple(
        db.session.execute(
            select(RentalAccessoryUnitLink)
            .where(
                RentalAccessoryUnitLink.rental_id.in_((predecessor.id, successor.id))
            )
            .order_by(RentalAccessoryUnitLink.rental_id.asc())
        ).scalars()
    )
    assert db.session.get(Device, device.id).warehouse_id == target.id
    assert result.affected_rental_ids == (predecessor.id, successor.id)
    assert [fact.status for fact in result.accessory_fulfillment] == [expected_status]
    if target_unit is None:
        assert links == ()
    else:
        assert len(links) == 2
        assert {link.accessory_unit_id for link in links} == {target_unit.id}
        assert links[0].source_relay_case_id is None
        assert links[1].source_relay_case_id == relay.id
        assert target_unit.id not in repr(result)
    assert source_unit.id not in repr(result)


def test_relay_status_change_invalidates_device_move_preview(application):
    current = ready_warehouse("当前仓", is_default=True)
    target = ready_warehouse("目标仓")
    device = Device(name="接力主设备", warehouse=current)
    predecessor = rental_for(device, days_from_today=5)
    successor = rental_for(device, days_from_today=10)
    db.session.add_all((current, target, device, predecessor, successor))
    db.session.flush()
    relay = RentalRelayCase(
        predecessor_rental_id=predecessor.id,
        successor_rental_id=successor.id,
        status="pending",
    )
    db.session.add(relay)
    db.session.commit()
    preview = WarehouseService.preview_device_move(
        device_id=device.id,
        target_warehouse_id=target.id,
    )
    relay.status = "notified"
    db.session.commit()

    with pytest.raises(StaleDeviceWarehouseError):
        WarehouseService.execute_device_move(
            device_id=device.id,
            target_warehouse_id=target.id,
            expected_current_warehouse_id=current.id,
            expected_preview_revision=preview.revision,
            confirmation_token_confirmed=True,
            actor_user_id="user-1",
        )

    db.session.expire_all()
    assert db.session.get(Device, device.id).warehouse_id == current.id
    assert DeviceWarehouseMovement.query.count() == 0


@pytest.mark.parametrize(
    "changed_fact",
    [
        "new_rental",
        "rental_date",
        "request",
        "link",
        "holder",
        "device_warehouse",
        "target_state",
    ],
)
def test_execute_rejects_every_material_preview_revision_change(
    application,
    changed_fact,
):
    current = ready_warehouse("当前仓", is_default=True)
    target = ready_warehouse("目标仓")
    other = ready_warehouse("第三仓")
    device = Device(name="主设备", warehouse=current)
    first_type = logical_type("battery", "电池")
    second_type = logical_type("tripod", "支架")
    third_type = logical_type("charger", "充电器")
    db.session.add_all(
        [current, target, other, device, first_type, second_type, third_type]
    )
    db.session.flush()
    rental = rental_for(device, days_from_today=5)
    first_unit = unit_for(first_type, current)
    second_unit = unit_for(second_type, current)
    db.session.add_all(
        [
            rental,
            first_unit,
            second_unit,
            request_for(rental, first_type),
            request_for(rental, second_type),
        ]
    )
    db.session.flush()
    db.session.add(link_for(rental, first_type, first_unit))
    db.session.commit()
    preview = WarehouseService.preview_device_move(
        device_id=device.id,
        target_warehouse_id=target.id,
    )

    if changed_fact == "new_rental":
        db.session.add(rental_for(device, days_from_today=9))
    elif changed_fact == "rental_date":
        rental.planned_return_date += timedelta(days=1)
    elif changed_fact == "request":
        db.session.add(request_for(rental, third_type))
    elif changed_fact == "link":
        db.session.add(link_for(rental, second_type, second_unit))
    elif changed_fact == "holder":
        first_unit.current_holder_rental = rental
    elif changed_fact == "device_warehouse":
        device.warehouse = other
    elif changed_fact == "target_state":
        target.status = "inactive"
    db.session.commit()
    warehouse_after_change = device.warehouse_id

    with pytest.raises(StaleDeviceWarehouseError):
        WarehouseService.execute_device_move(
            device_id=device.id,
            target_warehouse_id=target.id,
            expected_current_warehouse_id=preview.device.warehouse_id,
            expected_preview_revision=preview.revision,
            confirmation_token_confirmed=True,
            actor_user_id="user-1",
        )

    db.session.expire_all()
    assert db.session.get(Device, device.id).warehouse_id == warehouse_after_change
    assert DeviceWarehouseMovement.query.count() == 0


def test_execute_refreshes_cached_rows_before_revision_comparison(application):
    current = ready_warehouse("当前仓", is_default=True)
    target = ready_warehouse("目标仓")
    device = Device(name="主设备", warehouse=current)
    db.session.add_all([current, target, device])
    db.session.flush()
    rental = rental_for(device, days_from_today=5)
    db.session.add(rental)
    db.session.commit()
    preview = WarehouseService.preview_device_move(
        device_id=device.id,
        target_warehouse_id=target.id,
    )
    cached_return_date = rental.planned_return_date
    db.session.execute(
        update(Rental)
        .where(Rental.id == rental.id)
        .values(planned_return_date=cached_return_date + timedelta(days=1))
        .execution_options(synchronize_session=False)
    )
    assert rental.planned_return_date == cached_return_date

    with pytest.raises(StaleDeviceWarehouseError):
        WarehouseService.execute_device_move(
            device_id=device.id,
            target_warehouse_id=target.id,
            expected_current_warehouse_id=current.id,
            expected_preview_revision=preview.revision,
            confirmation_token_confirmed=True,
            actor_user_id="user-1",
        )

    assert DeviceWarehouseMovement.query.count() == 0


def test_submitted_shipment_does_not_block_move_but_old_snapshot_fails_closed(
    application,
):
    current = ready_warehouse("当前仓", is_default=True)
    target = ready_warehouse("目标仓")
    device = Device(name="主设备", warehouse=current)
    accessory_type = logical_type()
    db.session.add_all([current, target, device, accessory_type])
    db.session.flush()
    rental = rental_for(device, days_from_today=5)
    source_unit = unit_for(accessory_type, current)
    target_unit = unit_for(accessory_type, target)
    db.session.add_all(
        [
            rental,
            source_unit,
            target_unit,
            request_for(rental, accessory_type),
        ]
    )
    db.session.flush()
    db.session.add(link_for(rental, accessory_type, source_unit))
    shipment = submitted_shipment_for(rental, current)
    db.session.add(shipment)
    db.session.commit()
    original_origin = (
        shipment.origin_warehouse_id,
        shipment.origin_warehouse_uuid,
    )

    result = execute_previewed(device, target)

    db.session.expire_all()
    stored_shipment = db.session.get(OutboundShipment, shipment.id)
    assert db.session.get(Device, device.id).warehouse_id == target.id
    assert result.accessory_fulfillment[0].status == "fulfilled"
    assert (
        stored_shipment.origin_warehouse_id,
        stored_shipment.origin_warehouse_uuid,
    ) == original_origin
    shipment_id = shipment.id
    rental_id = rental.id
    current_id = current.id
    current_uuid = current.warehouse_uuid
    db.session.rollback()

    with pytest.raises(ShippingSnapshotMismatchError):
        with db.session.begin():
            ShippingExecutionService(db.session()).prepare_paired_print_jobs(
                shipment_id=shipment_id,
                rental_id=rental_id,
                first_label_warehouse_uuid=current_uuid,
                return_warehouse_id=current_id,
                return_warehouse_uuid=current_uuid,
                return_contact_snapshot={"name": "return"},
                operator_user_uuid=str(uuid4()),
                idempotency_key="warehouse-move-old-snapshot",
            )
