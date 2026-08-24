from dataclasses import asdict
from datetime import datetime, timedelta
from inspect import signature

import pytest
from sqlalchemy.exc import IntegrityError

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
from app.models.rental import Rental
from app.models.rental_relay_case import RentalRelayCase
from app.models.shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
    WaybillPrintJob,
)
from app.models.warehouse import Warehouse
from app.services.accessory_inventory_service import (
    AccessoryCapacityReductionUnavailableError,
    AccessoryFulfillmentFrozenError,
    AccessoryInspectionChainRecalculationRequiredError,
    AccessoryInventoryRepository,
    AccessoryInventoryService,
    AccessoryPersistenceError,
    AccessoryRelayHandoffConflictError,
    AccessoryTransactionRequiredError,
    AccessoryUnitUnavailableError,
)


WINDOW_START = datetime(2026, 9, 1, 8)
WINDOW_END = datetime(2026, 9, 6, 8)
INTEGRATION_UUID = "11111111-1111-4111-8111-111111111111"
ACCOUNT_UUID = "22222222-2222-4222-8222-222222222222"
INTEGRATION_REVISION_UUID = "33333333-3333-4333-8333-333333333333"
ACCOUNT_REVISION_UUID = "44444444-4444-4444-8444-444444444444"
OPERATOR_UUID = "55555555-5555-4555-8555-555555555555"


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


def _warehouse(*, name="默认仓库"):
    return Warehouse(
        name=name,
        status="active",
        setup_state="ready",
        is_default=name == "默认仓库",
        default_slot=1 if name == "默认仓库" else None,
        contact_name="负责人",
        contact_phone="13800138000",
        province="广东省",
        city="深圳市",
        district="南山区",
        address_detail="测试地址 1 号",
    )


def _seed_base(*, unit_ids=()):
    warehouse = _warehouse()
    accessory_type = AccessoryType(
        name="tripod",
        display_name="三脚架",
        tracking_mode="logical_unit",
    )
    device = Device(name="主设备", warehouse=warehouse)
    db.session.add_all((warehouse, accessory_type, device))
    db.session.flush()
    db.session.add(
        DeviceAccessoryConfig(
            device_id=device.id,
            accessory_type_id=accessory_type.id,
            enabled=True,
        )
    )
    rentals = []
    for index in range(4):
        rental = Rental(
            device=device,
            start_date=datetime(2026, 9, 1 + index).date(),
            end_date=datetime(2026, 9, 3 + index).date(),
            customer_name=f"测试客户 {index}",
        )
        db.session.add(rental)
        rentals.append(rental)
    units = [
        AccessoryUnit(
            id=unit_id,
            accessory_type=accessory_type,
            warehouse=warehouse,
        )
        for unit_id in unit_ids
    ]
    db.session.add_all(units)
    db.session.commit()
    return warehouse, accessory_type, device, rentals, units


class RecordingRepository(AccessoryInventoryRepository):
    def __init__(self, session):
        super().__init__(session)
        self.locked_unit_ids = ()

    def lock_reservation_units(self, **kwargs):
        units = super().lock_reservation_units(**kwargs)
        self.locked_unit_ids = tuple(unit.id for unit in units)
        return units


class FailingFlushRepository(AccessoryInventoryRepository):
    def flush(self):
        raise IntegrityError("simulated statement", {}, RuntimeError("simulated"))


class FailingReadRepository(AccessoryInventoryRepository):
    def get_accessory_type(self, accessory_type_id):
        raise IntegrityError(
            "select where unit_id = :unit_id",
            {"unit_id": "private-unit-uuid"},
            RuntimeError("simulated"),
        )


def _reserve(
    service,
    *,
    rental_id,
    accessory_type_id,
    operation_key="booking-1",
    start_at=WINDOW_START,
    end_at=WINDOW_END,
):
    return service.reserve_for_rental(
        rental_id=rental_id,
        accessory_type_id=accessory_type_id,
        reservation_start_at=start_at,
        reservation_end_at=end_at,
        actor_type="user",
        actor_id="user-1",
        operation_key=operation_key,
    )


def _seed_shipping_execution(
    *,
    rental,
    warehouse,
    attempt_status=None,
    print_status=None,
    shipment_status=None,
    cancellation_proven=False,
):
    if shipment_status is None:
        shipment_status = {
            "provider_submitting": "provider_submitting",
            "succeeded": "submitted",
            "unknown": "needs_review",
            "needs_review": "needs_review",
            "definitive_failure": "failed",
        }.get(attempt_status, "submitted" if print_status is not None else "prepared")
    shipment = OutboundShipment(
        rental_id=rental.id,
        origin_warehouse_id=warehouse.id,
        origin_warehouse_uuid=warehouse.warehouse_uuid,
        integration_uuid=INTEGRATION_UUID,
        provider_account_uuid=ACCOUNT_UUID,
        integration_secret_revision_uuid=INTEGRATION_REVISION_UUID,
        provider_account_secret_revision_uuid=ACCOUNT_REVISION_UUID,
        binding_revision=1,
        account_masked_hint="****1234",
        sender_snapshot={"contact": "仓库"},
        receiver_snapshot={"contact": "客户"},
        cargo_snapshot={
            "items": [{"name": "租赁设备", "count": 1}]
        },
        tracking_check_phone_last4="9000",
        express_type_id=1,
        scheduled_dispatch_at=datetime(2026, 8, 23, 9),
        provider_order_id=f"sf-{rental.id}-{attempt_status}-{print_status}",
        request_hash="a" * 64,
        waybill_no=(f"SF{rental.id:010d}" if print_status is not None else None),
        status=shipment_status,
    )
    db.session.add(shipment)
    db.session.flush()
    if attempt_status is not None:
        db.session.add(
            ProviderOperationAttempt(
                shipment_id=shipment.id,
                operation="create_waybill",
                idempotency_key=f"attempt-{rental.id}-{attempt_status}",
                attempt_no=1,
                integration_secret_revision_uuid=INTEGRATION_REVISION_UUID,
                provider_account_secret_revision_uuid=ACCOUNT_REVISION_UUID,
                binding_revision=1,
                status=attempt_status,
            )
        )
    if cancellation_proven:
        db.session.add(
            ProviderOperationAttempt(
                shipment_id=shipment.id,
                operation="cancel_waybill",
                idempotency_key=f"cancel-{rental.id}-{attempt_status}-{print_status}",
                attempt_no=1,
                integration_secret_revision_uuid=INTEGRATION_REVISION_UUID,
                provider_account_secret_revision_uuid=ACCOUNT_REVISION_UUID,
                binding_revision=1,
                status="succeeded",
            )
        )
    if print_status is not None:
        db.session.add(
            WaybillPrintJob(
                shipment_id=shipment.id,
                rental_id=rental.id,
                waybill_no_snapshot=shipment.waybill_no,
                first_label_warehouse_uuid=warehouse.warehouse_uuid,
                integration_uuid=INTEGRATION_UUID,
                provider_account_uuid=ACCOUNT_UUID,
                integration_secret_revision_uuid=INTEGRATION_REVISION_UUID,
                provider_account_secret_revision_uuid=ACCOUNT_REVISION_UUID,
                binding_revision=1,
                return_warehouse_id=warehouse.id,
                return_warehouse_uuid=warehouse.warehouse_uuid,
                return_contact_snapshot={"contact": "仓库"},
                printer_sn_snapshot="printer-1",
                operator_user_uuid=OPERATOR_UUID,
                idempotency_key=f"print-{rental.id}-{print_status}",
                status=print_status,
            )
        )
    db.session.commit()
    return shipment


def test_public_service_methods_accept_no_tenant_database_or_unit_selector():
    forbidden = {
        "tenant",
        "tenant_id",
        "database",
        "database_url",
        "unit_id",
        "link_id",
    }
    for method_name in (
        "availability",
        "reserve_for_rental",
        "dispatch_for_rental",
        "handoff_for_relay",
        "release_reservation",
        "inspect_return_for_rental",
        "add_capacity",
        "reduce_capacity",
    ):
        parameter_names = set(
            signature(getattr(AccessoryInventoryService, method_name)).parameters
        )
        assert parameter_names.isdisjoint(forbidden)


def test_availability_is_realtime_and_returns_only_type_and_counts(application):
    unit_ids = (
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000003",
        "00000000-0000-0000-0000-000000000004",
        "00000000-0000-0000-0000-000000000005",
    )
    warehouse, accessory_type, _, rentals, units = _seed_base(unit_ids=unit_ids)
    units[2].current_holder_rental_id = rentals[2].id
    units[3].condition_status = "maintenance"
    units[4].condition_status = "retired"
    db.session.add(
        RentalAccessoryUnitLink(
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            accessory_unit_id=units[1].id,
            reservation_start_at=WINDOW_START,
            reservation_end_at=WINDOW_END,
        )
    )
    db.session.commit()

    service = AccessoryInventoryService(db.session())
    result = service.availability(
        accessory_type_id=accessory_type.id,
        warehouse_id=warehouse.id,
        reservation_start_at=WINDOW_START,
        reservation_end_at=WINDOW_END,
    )

    assert asdict(result) == {
        "type_code": "tripod",
        "display_name": "三脚架",
        "total": 3,
        "reserved": 2,
        "available": 1,
    }
    assert all(unit_id not in repr(result) for unit_id in unit_ids)


def test_database_errors_do_not_expose_internal_query_parameters(application):
    session = db.session()
    service = AccessoryInventoryService(
        session,
        repository=FailingReadRepository(session),
    )

    with pytest.raises(AccessoryPersistenceError) as caught:
        service.availability(
            accessory_type_id=1,
            warehouse_id=1,
            reservation_start_at=WINDOW_START,
            reservation_end_at=WINDOW_END,
        )

    assert caught.value.code == "ACCESSORY_PERSISTENCE_FAILED"
    assert "private-unit-uuid" not in str(caught.value)


def test_reservation_uses_fixed_unit_order_excludes_overlap_and_is_idempotent(
    application,
):
    unit_ids = (
        "00000000-0000-0000-0000-000000000003",
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    )
    warehouse, accessory_type, _, rentals, units = _seed_base(unit_ids=unit_ids)
    db.session.add(
        RentalAccessoryUnitLink(
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            accessory_unit_id=units[1].id,
            reservation_start_at=WINDOW_START,
            reservation_end_at=WINDOW_END,
        )
    )
    db.session.commit()
    session = db.session()
    repository = RecordingRepository(session)
    service = AccessoryInventoryService(session, repository=repository)

    with session.begin():
        result = _reserve(
            service,
            rental_id=rentals[1].id,
            accessory_type_id=accessory_type.id,
        )

    assert repository.row_locking_supported is False
    assert repository.locked_unit_ids == tuple(sorted(unit_ids))
    link = RentalAccessoryUnitLink.query.filter_by(
        rental_id=rentals[1].id,
        accessory_type_id=accessory_type.id,
    ).one()
    assert link.accessory_unit_id == unit_ids[2]
    assert (result.total, result.reserved, result.available) == (3, 2, 1)
    assert RentalAccessoryRequest.query.filter_by(rental_id=rentals[1].id).count() == 1
    assert AccessoryUnitEvent.query.filter_by(event_type="linked").count() == 1

    db.session.commit()
    with session.begin():
        retry = _reserve(
            service,
            rental_id=rentals[1].id,
            accessory_type_id=accessory_type.id,
        )

    assert retry == result
    assert AccessoryUnitEvent.query.filter_by(event_type="linked").count() == 1


def test_unavailable_reservation_leaves_no_request_link_or_event(application):
    unit_id = "10000000-0000-0000-0000-000000000001"
    _, accessory_type, _, rentals, units = _seed_base(unit_ids=(unit_id,))
    db.session.add(
        RentalAccessoryUnitLink(
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            accessory_unit_id=units[0].id,
            reservation_start_at=WINDOW_START,
            reservation_end_at=WINDOW_END,
        )
    )
    db.session.commit()
    session = db.session()
    service = AccessoryInventoryService(session)

    with pytest.raises(AccessoryUnitUnavailableError) as caught:
        with session.begin():
            _reserve(
                service,
                rental_id=rentals[1].id,
                accessory_type_id=accessory_type.id,
            )

    assert caught.value.code == "ACCESSORY_UNIT_UNAVAILABLE"
    assert unit_id not in str(caught.value)
    assert RentalAccessoryRequest.query.filter_by(rental_id=rentals[1].id).count() == 0
    assert RentalAccessoryUnitLink.query.filter_by(rental_id=rentals[1].id).count() == 0
    assert AccessoryUnitEvent.query.count() == 0


def test_caller_transaction_rolls_back_pending_facts_after_flush_failure(application):
    _, accessory_type, _, rentals, _ = _seed_base(
        unit_ids=("15000000-0000-0000-0000-000000000001",)
    )
    session = db.session()
    service = AccessoryInventoryService(
        session,
        repository=FailingFlushRepository(session),
    )

    with pytest.raises(AccessoryUnitUnavailableError):
        with session.begin():
            _reserve(
                service,
                rental_id=rentals[0].id,
                accessory_type_id=accessory_type.id,
                operation_key="flush-failure",
            )

    assert RentalAccessoryRequest.query.count() == 0
    assert RentalAccessoryUnitLink.query.count() == 0
    assert AccessoryUnitEvent.query.count() == 0


def test_dispatch_requires_empty_holder_updates_version_and_is_idempotent(application):
    warehouse, accessory_type, _, rentals, units = _seed_base(
        unit_ids=("20000000-0000-0000-0000-000000000001",)
    )
    session = db.session()
    service = AccessoryInventoryService(session)
    with session.begin():
        _reserve(
            service,
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
        )

    with session.begin():
        result = service.dispatch_for_rental(
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            actor_type="user",
            actor_id="user-1",
            operation_key="ship-1",
        )

    assert result.type_code == "tripod"
    assert units[0].current_holder_rental_id == rentals[0].id
    assert units[0].row_version == 2
    assert AccessoryUnitEvent.query.filter_by(event_type="dispatched").count() == 1
    db.session.commit()
    _seed_shipping_execution(
        rental=rentals[0],
        warehouse=warehouse,
        attempt_status="provider_submitting",
    )

    with session.begin():
        retry = service.dispatch_for_rental(
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            actor_type="user",
            actor_id="user-1",
            operation_key="ship-1",
        )

    assert retry == result
    assert units[0].row_version == 2
    assert AccessoryUnitEvent.query.filter_by(event_type="dispatched").count() == 1


def test_dispatch_rejects_a_unit_held_by_another_rental(application):
    _, accessory_type, _, rentals, units = _seed_base(
        unit_ids=("30000000-0000-0000-0000-000000000001",)
    )
    units[0].current_holder_rental_id = rentals[1].id
    db.session.add_all(
        (
            RentalAccessoryRequest(
                rental_id=rentals[0].id,
                accessory_type_id=accessory_type.id,
                name_snapshot="三脚架",
            ),
            RentalAccessoryUnitLink(
                rental_id=rentals[0].id,
                accessory_type_id=accessory_type.id,
                accessory_unit_id=units[0].id,
                reservation_start_at=WINDOW_START,
                reservation_end_at=WINDOW_END,
            ),
        )
    )
    db.session.commit()
    session = db.session()
    service = AccessoryInventoryService(session)

    with pytest.raises(AccessoryUnitUnavailableError):
        with session.begin():
            service.dispatch_for_rental(
                rental_id=rentals[0].id,
                accessory_type_id=accessory_type.id,
                actor_type="user",
                actor_id="user-1",
                operation_key="ship-held",
            )

    assert units[0].current_holder_rental_id == rentals[1].id
    assert units[0].row_version == 1
    assert AccessoryUnitEvent.query.filter_by(event_type="dispatched").count() == 0


@pytest.mark.parametrize(
    ("outcome", "expected_condition", "holder_is_cleared"),
    (
        ("received_normal", "active", True),
        ("received_damaged", "maintenance", True),
        ("missing", "lost", False),
    ),
)
def test_inspection_records_custody_condition_and_idempotent_events(
    application,
    outcome,
    expected_condition,
    holder_is_cleared,
):
    warehouse, accessory_type, _, rentals, units = _seed_base(
        unit_ids=("30500000-0000-0000-0000-000000000001",)
    )
    target = _warehouse(name="验货仓")
    db.session.add(target)
    db.session.commit()
    session = db.session()
    service = AccessoryInventoryService(session)
    with session.begin():
        _reserve(
            service,
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
        )
    with session.begin():
        service.dispatch_for_rental(
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            actor_type="user",
            actor_id="user-1",
            operation_key="inspection-dispatch",
        )

    with session.begin():
        result = service.inspect_return_for_rental(
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            warehouse_id=target.id,
            outcome=outcome,
            occurred_at=WINDOW_END + timedelta(days=2),
            actor_type="user",
            actor_id="user-1",
            operation_key=f"inspection-{outcome}",
        )

    assert result.type_code == "tripod"
    assert units[0].condition_status == expected_condition
    assert (units[0].current_holder_rental_id is None) is holder_is_cleared
    if holder_is_cleared:
        assert units[0].warehouse_id == target.id
        assert AccessoryUnitEvent.query.filter_by(event_type="inspected").count() == 1
        assert AccessoryUnitEvent.query.filter_by(event_type="warehouse_moved").count() == 1
    else:
        assert units[0].warehouse_id == warehouse.id
        assert units[0].current_holder_rental_id == rentals[0].id
        assert AccessoryUnitEvent.query.filter_by(event_type="lost").count() == 1

    event_count = AccessoryUnitEvent.query.count()
    db.session.commit()
    with session.begin():
        replay = service.inspect_return_for_rental(
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            warehouse_id=target.id,
            outcome=outcome,
            occurred_at=WINDOW_END + timedelta(days=2),
            actor_type="user",
            actor_id="user-1",
            operation_key=f"inspection-{outcome}",
        )

    assert replay == result
    assert AccessoryUnitEvent.query.count() == event_count


def test_inspection_fails_closed_when_future_links_need_recalculation(application):
    warehouse, accessory_type, _, rentals, units = _seed_base(
        unit_ids=("30600000-0000-0000-0000-000000000001",)
    )
    target = _warehouse(name="验货仓")
    units[0].current_holder_rental_id = rentals[0].id
    db.session.add_all(
        (
            target,
            RentalAccessoryRequest(
                rental_id=rentals[0].id,
                accessory_type_id=accessory_type.id,
                name_snapshot="三脚架",
            ),
            RentalAccessoryUnitLink(
                rental_id=rentals[0].id,
                accessory_type_id=accessory_type.id,
                accessory_unit_id=units[0].id,
                reservation_start_at=WINDOW_START,
                reservation_end_at=WINDOW_END,
            ),
            RentalAccessoryUnitLink(
                rental_id=rentals[1].id,
                accessory_type_id=accessory_type.id,
                accessory_unit_id=units[0].id,
                reservation_start_at=WINDOW_END + timedelta(days=1),
                reservation_end_at=WINDOW_END + timedelta(days=4),
            ),
        )
    )
    db.session.commit()
    session = db.session()
    service = AccessoryInventoryService(session)

    with pytest.raises(AccessoryInspectionChainRecalculationRequiredError):
        with session.begin():
            service.inspect_return_for_rental(
                rental_id=rentals[0].id,
                accessory_type_id=accessory_type.id,
                warehouse_id=target.id,
                outcome="received_normal",
                occurred_at=WINDOW_END + timedelta(hours=1),
                actor_type="user",
                actor_id="user-1",
                operation_key="inspection-needs-chain",
            )

    assert units[0].current_holder_rental_id == rentals[0].id
    assert units[0].warehouse_id == warehouse.id
    assert units[0].condition_status == "active"
    assert AccessoryUnitEvent.query.count() == 0


def test_provider_effect_boundary_blocks_dispatch_holder_mutation(application):
    warehouse, accessory_type, _, rentals, units = _seed_base(
        unit_ids=("31000000-0000-0000-0000-000000000001",)
    )
    session = db.session()
    service = AccessoryInventoryService(session)
    with session.begin():
        _reserve(
            service,
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
        )
    _seed_shipping_execution(
        rental=rentals[0],
        warehouse=warehouse,
        attempt_status="provider_submitting",
    )

    with pytest.raises(AccessoryFulfillmentFrozenError):
        with session.begin():
            service.dispatch_for_rental(
                rental_id=rentals[0].id,
                accessory_type_id=accessory_type.id,
                actor_type="user",
                actor_id="user-1",
                operation_key="dispatch-after-provider",
            )

    assert units[0].current_holder_rental_id is None
    assert units[0].row_version == 1
    assert AccessoryUnitEvent.query.filter_by(event_type="dispatched").count() == 0


def _seed_relay_links(*, holder_index=0, source_case=True):
    warehouse, accessory_type, device, rentals, units = _seed_base(
        unit_ids=("35000000-0000-0000-0000-000000000001",)
    )
    relay_case = RentalRelayCase(
        predecessor_rental_id=rentals[0].id,
        successor_rental_id=rentals[1].id,
        status="agreed",
    )
    db.session.add(relay_case)
    db.session.flush()
    units[0].current_holder_rental_id = rentals[holder_index].id
    db.session.add_all(
        (
            RentalAccessoryRequest(
                rental_id=rentals[0].id,
                accessory_type_id=accessory_type.id,
                name_snapshot="三脚架",
            ),
            RentalAccessoryUnitLink(
                rental_id=rentals[0].id,
                accessory_type_id=accessory_type.id,
                accessory_unit_id=units[0].id,
                reservation_start_at=WINDOW_START,
                reservation_end_at=WINDOW_END,
            ),
            RentalAccessoryUnitLink(
                rental_id=rentals[1].id,
                accessory_type_id=accessory_type.id,
                accessory_unit_id=units[0].id,
                reservation_start_at=WINDOW_START + timedelta(days=1),
                reservation_end_at=WINDOW_END + timedelta(days=1),
                source_relay_case_id=(relay_case.id if source_case else None),
            ),
        )
    )
    db.session.commit()
    return warehouse, accessory_type, device, rentals, units[0], relay_case


def test_relay_handoff_advances_exact_holder_without_creating_demand(
    application,
):
    warehouse, accessory_type, device, rentals, unit, relay_case = (
        _seed_relay_links()
    )
    session = db.session()
    service = AccessoryInventoryService(session)

    with session.begin():
        result = service.handoff_for_relay(
            relay_case_id=relay_case.id,
            accessory_type_id=accessory_type.id,
            actor_type="user",
            actor_id="operator-1",
            operation_key="relay-ship-1",
        )

    assert result.type_code == "tripod"
    assert unit.current_holder_rental_id == rentals[1].id
    assert unit.row_version == 2
    assert RentalAccessoryRequest.query.filter_by(
        rental_id=rentals[1].id,
        accessory_type_id=accessory_type.id,
    ).count() == 0
    event = AccessoryUnitEvent.query.filter_by(
        event_type="relay_handoff"
    ).one()
    assert event.main_device_id == device.id
    assert event.rental_id == rentals[1].id
    assert event.relay_case_id == relay_case.id
    assert event.from_holder_rental_id == rentals[0].id
    assert event.to_holder_rental_id == rentals[1].id

    relay_case.status = "shipped"
    db.session.commit()
    _seed_shipping_execution(
        rental=rentals[1],
        warehouse=warehouse,
        attempt_status="provider_submitting",
    )
    with session.begin():
        replay = service.handoff_for_relay(
            relay_case_id=relay_case.id,
            accessory_type_id=accessory_type.id,
            actor_type="user",
            actor_id="operator-1",
            operation_key="relay-ship-1",
        )

    assert replay == result
    assert unit.row_version == 2
    assert AccessoryUnitEvent.query.filter_by(
        event_type="relay_handoff"
    ).count() == 1


def test_relay_handoff_rejects_out_of_order_holder_and_wrong_chain_source(
    application,
):
    _, accessory_type, _, rentals, unit, relay_case = _seed_relay_links(
        holder_index=2
    )
    session = db.session()
    service = AccessoryInventoryService(session)

    with pytest.raises(AccessoryRelayHandoffConflictError):
        with session.begin():
            service.handoff_for_relay(
                relay_case_id=relay_case.id,
                accessory_type_id=accessory_type.id,
                actor_type="user",
                actor_id="operator-1",
                operation_key="relay-out-of-order",
            )

    assert unit.current_holder_rental_id == rentals[2].id
    assert unit.row_version == 1
    assert AccessoryUnitEvent.query.filter_by(
        event_type="relay_handoff"
    ).count() == 0

    unit.current_holder_rental_id = rentals[0].id
    successor_link = RentalAccessoryUnitLink.query.filter_by(
        rental_id=rentals[1].id,
        accessory_type_id=accessory_type.id,
    ).one()
    successor_link.source_relay_case_id = None
    db.session.commit()
    with pytest.raises(AccessoryRelayHandoffConflictError):
        with session.begin():
            service.handoff_for_relay(
                relay_case_id=relay_case.id,
                accessory_type_id=accessory_type.id,
                actor_type="user",
                actor_id="operator-1",
                operation_key="relay-wrong-source",
            )

    assert unit.current_holder_rental_id == rentals[0].id
    assert unit.row_version == 1


def test_print_effect_boundary_on_either_relay_rental_blocks_handoff(application):
    warehouse, accessory_type, _, rentals, unit, relay_case = _seed_relay_links()
    _seed_shipping_execution(
        rental=rentals[1],
        warehouse=warehouse,
        print_status="provider_submitting",
    )
    session = db.session()
    service = AccessoryInventoryService(session)

    with pytest.raises(AccessoryFulfillmentFrozenError):
        with session.begin():
            service.handoff_for_relay(
                relay_case_id=relay_case.id,
                accessory_type_id=accessory_type.id,
                actor_type="user",
                actor_id="operator-1",
                operation_key="handoff-after-print",
            )

    assert unit.current_holder_rental_id == rentals[0].id
    assert unit.row_version == 1
    assert AccessoryUnitEvent.query.filter_by(
        event_type="relay_handoff"
    ).count() == 0


def test_release_removes_only_link_keeps_request_and_is_idempotent(application):
    warehouse, accessory_type, _, rentals, _ = _seed_base(
        unit_ids=("40000000-0000-0000-0000-000000000001",)
    )
    session = db.session()
    service = AccessoryInventoryService(session)
    with session.begin():
        _reserve(
            service,
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
        )

    with session.begin():
        result = service.release_reservation(
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            reservation_start_at=WINDOW_START,
            reservation_end_at=WINDOW_END,
            actor_type="user",
            actor_id="user-1",
            operation_key="release-1",
        )

    assert (result.total, result.reserved, result.available) == (1, 0, 1)
    assert RentalAccessoryRequest.query.filter_by(rental_id=rentals[0].id).count() == 1
    assert RentalAccessoryUnitLink.query.filter_by(rental_id=rentals[0].id).count() == 0
    assert AccessoryUnitEvent.query.filter_by(event_type="unlinked").count() == 1
    db.session.commit()
    _seed_shipping_execution(
        rental=rentals[0],
        warehouse=warehouse,
        attempt_status="provider_submitting",
    )

    with session.begin():
        retry = service.release_reservation(
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            reservation_start_at=WINDOW_START,
            reservation_end_at=WINDOW_END,
            actor_type="user",
            actor_id="user-1",
            operation_key="release-1",
        )

    assert retry == result
    assert AccessoryUnitEvent.query.filter_by(event_type="unlinked").count() == 1


@pytest.mark.parametrize(
    "attempt_status",
    ("provider_submitting", "succeeded", "unknown", "needs_review"),
)
def test_provider_effect_boundary_blocks_release_without_partial_write(
    application,
    attempt_status,
):
    warehouse, accessory_type, _, rentals, _ = _seed_base(
        unit_ids=("41000000-0000-0000-0000-000000000001",)
    )
    session = db.session()
    service = AccessoryInventoryService(session)
    with session.begin():
        _reserve(
            service,
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
        )
    _seed_shipping_execution(
        rental=rentals[0],
        warehouse=warehouse,
        attempt_status=attempt_status,
    )

    with pytest.raises(AccessoryFulfillmentFrozenError) as caught:
        with session.begin():
            service.release_reservation(
                rental_id=rentals[0].id,
                accessory_type_id=accessory_type.id,
                reservation_start_at=WINDOW_START,
                reservation_end_at=WINDOW_END,
                actor_type="user",
                actor_id="user-1",
                operation_key=f"release-after-{attempt_status}",
            )

    assert caught.value.code == "ACCESSORY_FULFILLMENT_FROZEN"
    assert RentalAccessoryRequest.query.filter_by(
        rental_id=rentals[0].id
    ).count() == 1
    assert RentalAccessoryUnitLink.query.filter_by(
        rental_id=rentals[0].id
    ).count() == 1
    assert AccessoryUnitEvent.query.filter_by(event_type="unlinked").count() == 0


@pytest.mark.parametrize("attempt_status", ("prepared", "definitive_failure"))
def test_provider_pre_boundary_or_no_effect_allows_release(
    application,
    attempt_status,
):
    warehouse, accessory_type, _, rentals, _ = _seed_base(
        unit_ids=("42000000-0000-0000-0000-000000000001",)
    )
    session = db.session()
    service = AccessoryInventoryService(session)
    with session.begin():
        _reserve(
            service,
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
        )
    _seed_shipping_execution(
        rental=rentals[0],
        warehouse=warehouse,
        attempt_status=attempt_status,
    )

    with session.begin():
        service.release_reservation(
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            reservation_start_at=WINDOW_START,
            reservation_end_at=WINDOW_END,
            actor_type="user",
            actor_id="user-1",
            operation_key=f"release-before-{attempt_status}",
        )

    assert RentalAccessoryUnitLink.query.filter_by(
        rental_id=rentals[0].id
    ).count() == 0


@pytest.mark.parametrize(
    "print_status",
    ("provider_submitting", "printed", "unknown", "needs_review"),
)
def test_print_effect_boundary_blocks_new_request_without_partial_write(
    application,
    print_status,
):
    warehouse, accessory_type, _, rentals, _ = _seed_base(
        unit_ids=("43000000-0000-0000-0000-000000000001",)
    )
    _seed_shipping_execution(
        rental=rentals[0],
        warehouse=warehouse,
        print_status=print_status,
    )
    session = db.session()
    service = AccessoryInventoryService(session)

    with pytest.raises(AccessoryFulfillmentFrozenError) as caught:
        with session.begin():
            _reserve(
                service,
                rental_id=rentals[0].id,
                accessory_type_id=accessory_type.id,
                operation_key=f"reserve-after-print-{print_status}",
            )

    assert caught.value.code == "ACCESSORY_FULFILLMENT_FROZEN"
    assert RentalAccessoryRequest.query.filter_by(
        rental_id=rentals[0].id
    ).count() == 0
    assert RentalAccessoryUnitLink.query.filter_by(
        rental_id=rentals[0].id
    ).count() == 0
    assert AccessoryUnitEvent.query.count() == 0


@pytest.mark.parametrize("print_status", ("prepared", "failed", "cancelled"))
def test_submitted_shipment_remains_frozen_regardless_of_print_job_state(
    application,
    print_status,
):
    warehouse, accessory_type, _, rentals, _ = _seed_base(
        unit_ids=("44000000-0000-0000-0000-000000000001",)
    )
    _seed_shipping_execution(
        rental=rentals[0],
        warehouse=warehouse,
        print_status=print_status,
    )
    session = db.session()
    service = AccessoryInventoryService(session)

    with pytest.raises(AccessoryFulfillmentFrozenError):
        with session.begin():
            _reserve(
                service,
                rental_id=rentals[0].id,
                accessory_type_id=accessory_type.id,
                operation_key=f"reserve-submitted-{print_status}",
            )

    assert RentalAccessoryRequest.query.filter_by(
        rental_id=rentals[0].id
    ).count() == 0
    assert RentalAccessoryUnitLink.query.filter_by(
        rental_id=rentals[0].id
    ).count() == 0


def test_proven_cancelled_shipment_unfreezes_historical_waybill_and_print(
    application,
):
    warehouse, accessory_type, _, rentals, _ = _seed_base(
        unit_ids=("45000000-0000-0000-0000-000000000001",)
    )
    session = db.session()
    service = AccessoryInventoryService(session)
    with session.begin():
        _reserve(
            service,
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
        )
    _seed_shipping_execution(
        rental=rentals[0],
        warehouse=warehouse,
        attempt_status="succeeded",
        print_status="printed",
        shipment_status="cancelled",
        cancellation_proven=True,
    )

    with session.begin():
        service.release_reservation(
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            reservation_start_at=WINDOW_START,
            reservation_end_at=WINDOW_END,
            actor_type="user",
            actor_id="user-1",
            operation_key="release-after-proven-cancel",
        )

    assert RentalAccessoryUnitLink.query.filter_by(
        rental_id=rentals[0].id
    ).count() == 0


def test_cancelled_shipment_without_successful_cancel_attempt_fails_closed(
    application,
):
    warehouse, accessory_type, _, rentals, _ = _seed_base(
        unit_ids=("45500000-0000-0000-0000-000000000001",)
    )
    _seed_shipping_execution(
        rental=rentals[0],
        warehouse=warehouse,
        attempt_status="succeeded",
        shipment_status="cancelled",
    )
    session = db.session()
    service = AccessoryInventoryService(session)

    with pytest.raises(AccessoryFulfillmentFrozenError):
        with session.begin():
            _reserve(
                service,
                rental_id=rentals[0].id,
                accessory_type_id=accessory_type.id,
                operation_key="reserve-unproven-cancel",
            )


@pytest.mark.parametrize("historical_effect", ("provider", "print"))
def test_failed_shipment_with_historical_effect_fails_closed(
    application,
    historical_effect,
):
    warehouse, accessory_type, _, rentals, _ = _seed_base(
        unit_ids=("46000000-0000-0000-0000-000000000001",)
    )
    _seed_shipping_execution(
        rental=rentals[0],
        warehouse=warehouse,
        attempt_status=("succeeded" if historical_effect == "provider" else None),
        print_status=("printed" if historical_effect == "print" else None),
        shipment_status="failed",
    )
    session = db.session()
    service = AccessoryInventoryService(session)

    with pytest.raises(AccessoryFulfillmentFrozenError):
        with session.begin():
            _reserve(
                service,
                rental_id=rentals[0].id,
                accessory_type_id=accessory_type.id,
                operation_key=f"reserve-inconsistent-{historical_effect}",
            )

    assert RentalAccessoryRequest.query.filter_by(
        rental_id=rentals[0].id
    ).count() == 0


def test_exact_reservation_replay_survives_boundary_but_new_facts_freeze(
    application,
):
    warehouse, accessory_type, _, rentals, _ = _seed_base(
        unit_ids=("47000000-0000-0000-0000-000000000001",)
    )
    session = db.session()
    service = AccessoryInventoryService(session)
    with session.begin():
        original = _reserve(
            service,
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            operation_key="reserve-before-boundary",
        )
    _seed_shipping_execution(
        rental=rentals[0],
        warehouse=warehouse,
        attempt_status="provider_submitting",
    )

    with session.begin():
        replay = _reserve(
            service,
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            operation_key="reserve-before-boundary",
        )
    assert replay == original
    db.session.commit()

    with pytest.raises(AccessoryFulfillmentFrozenError):
        with session.begin():
            _reserve(
                service,
                rental_id=rentals[0].id,
                accessory_type_id=accessory_type.id,
                operation_key="different-operation",
            )

    with pytest.raises(AccessoryFulfillmentFrozenError):
        with session.begin():
            _reserve(
                service,
                rental_id=rentals[0].id,
                accessory_type_id=accessory_type.id,
                operation_key="reserve-before-boundary",
                end_at=WINDOW_END + timedelta(hours=1),
            )

    assert AccessoryUnitEvent.query.filter_by(event_type="linked").count() == 1


def test_exact_release_replay_survives_boundary_but_changed_window_freezes(
    application,
):
    warehouse, accessory_type, _, rentals, _ = _seed_base(
        unit_ids=("48000000-0000-0000-0000-000000000001",)
    )
    session = db.session()
    service = AccessoryInventoryService(session)
    with session.begin():
        _reserve(
            service,
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
        )
    with session.begin():
        original = service.release_reservation(
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            reservation_start_at=WINDOW_START,
            reservation_end_at=WINDOW_END,
            actor_type="user",
            actor_id="user-1",
            operation_key="release-before-boundary",
        )
    _seed_shipping_execution(
        rental=rentals[0],
        warehouse=warehouse,
        attempt_status="provider_submitting",
    )

    with session.begin():
        replay = service.release_reservation(
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            reservation_start_at=WINDOW_START,
            reservation_end_at=WINDOW_END,
            actor_type="user",
            actor_id="user-1",
            operation_key="release-before-boundary",
        )
    assert replay == original
    db.session.commit()

    with pytest.raises(AccessoryFulfillmentFrozenError):
        with session.begin():
            service.release_reservation(
                rental_id=rentals[0].id,
                accessory_type_id=accessory_type.id,
                reservation_start_at=WINDOW_START,
                reservation_end_at=WINDOW_END + timedelta(hours=1),
                actor_type="user",
                actor_id="user-1",
                operation_key="release-before-boundary",
            )

    assert AccessoryUnitEvent.query.filter_by(event_type="unlinked").count() == 1


def test_add_capacity_creates_one_unit_and_event_per_quantity(application):
    warehouse, accessory_type, _, _, _ = _seed_base()
    session = db.session()
    service = AccessoryInventoryService(session)

    with session.begin():
        result = service.add_capacity(
            accessory_type_id=accessory_type.id,
            warehouse_id=warehouse.id,
            quantity=2,
            evaluation_start_at=WINDOW_START,
            evaluation_end_at=WINDOW_END,
            actor_type="user",
            actor_id="admin-1",
            operation_key="capacity-add-1",
        )

    assert (result.total, result.reserved, result.available) == (2, 0, 2)
    assert AccessoryUnit.query.count() == 2
    assert AccessoryUnitEvent.query.filter_by(event_type="created").count() == 2
    db.session.commit()

    with session.begin():
        retry = service.add_capacity(
            accessory_type_id=accessory_type.id,
            warehouse_id=warehouse.id,
            quantity=2,
            evaluation_start_at=WINDOW_START,
            evaluation_end_at=WINDOW_END,
            actor_type="user",
            actor_id="admin-1",
            operation_key="capacity-add-1",
        )

    assert retry == result
    assert AccessoryUnit.query.count() == 2
    assert AccessoryUnitEvent.query.filter_by(event_type="created").count() == 2


def test_reduce_capacity_only_retires_active_unheld_units_without_future_links(
    application,
):
    unit_ids = (
        "50000000-0000-0000-0000-000000000001",
        "50000000-0000-0000-0000-000000000002",
        "50000000-0000-0000-0000-000000000003",
        "50000000-0000-0000-0000-000000000004",
    )
    warehouse, accessory_type, _, rentals, units = _seed_base(unit_ids=unit_ids)
    units[1].current_holder_rental_id = rentals[1].id
    units[3].condition_status = "maintenance"
    db.session.add(
        RentalAccessoryUnitLink(
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            accessory_unit_id=units[2].id,
            reservation_start_at=WINDOW_START,
            reservation_end_at=WINDOW_END,
        )
    )
    db.session.add(
        RentalAccessoryUnitLink(
            rental_id=rentals[3].id,
            accessory_type_id=accessory_type.id,
            accessory_unit_id=units[0].id,
            reservation_start_at=WINDOW_START - timedelta(days=10),
            reservation_end_at=WINDOW_START - timedelta(days=2),
        )
    )
    db.session.commit()
    session = db.session()
    service = AccessoryInventoryService(session)

    with pytest.raises(AccessoryCapacityReductionUnavailableError):
        with session.begin():
            service.reduce_capacity(
                accessory_type_id=accessory_type.id,
                warehouse_id=warehouse.id,
                quantity=2,
                effective_at=WINDOW_START - timedelta(days=1),
                evaluation_start_at=WINDOW_START,
                evaluation_end_at=WINDOW_END,
                actor_type="user",
                actor_id="admin-1",
                operation_key="capacity-reduce-too-many",
            )

    assert all(unit.condition_status != "retired" for unit in units)
    assert AccessoryUnitEvent.query.filter_by(event_type="retired").count() == 0
    db.session.commit()

    with session.begin():
        result = service.reduce_capacity(
            accessory_type_id=accessory_type.id,
            warehouse_id=warehouse.id,
            quantity=1,
            effective_at=WINDOW_START - timedelta(days=1),
            evaluation_start_at=WINDOW_START,
            evaluation_end_at=WINDOW_END,
            actor_type="user",
            actor_id="admin-1",
            operation_key="capacity-reduce-1",
        )

    assert units[0].condition_status == "retired"
    assert units[0].row_version == 2
    assert units[1].condition_status == "active"
    assert units[2].condition_status == "active"
    assert units[3].condition_status == "maintenance"
    assert (result.total, result.reserved, result.available) == (2, 2, 0)
    assert AccessoryUnitEvent.query.filter_by(event_type="retired").count() == 1
    db.session.commit()

    with session.begin():
        retry = service.reduce_capacity(
            accessory_type_id=accessory_type.id,
            warehouse_id=warehouse.id,
            quantity=1,
            effective_at=WINDOW_START - timedelta(days=1),
            evaluation_start_at=WINDOW_START,
            evaluation_end_at=WINDOW_END,
            actor_type="user",
            actor_id="admin-1",
            operation_key="capacity-reduce-1",
        )

    assert retry == result
    assert AccessoryUnitEvent.query.filter_by(event_type="retired").count() == 1


def test_write_api_rejects_implicit_autobegin_transaction(application):
    warehouse, accessory_type, _, _, _ = _seed_base()
    session = db.session()
    service = AccessoryInventoryService(session)

    with pytest.raises(AccessoryTransactionRequiredError):
        service.add_capacity(
            accessory_type_id=accessory_type.id,
            warehouse_id=warehouse.id,
            quantity=1,
            evaluation_start_at=WINDOW_START,
            evaluation_end_at=WINDOW_END,
            actor_type="user",
            actor_id="admin-1",
            operation_key="missing-transaction",
        )

    assert AccessoryUnit.query.count() == 0
