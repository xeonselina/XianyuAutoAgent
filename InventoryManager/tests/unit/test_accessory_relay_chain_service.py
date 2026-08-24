from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone

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
from app.models.audit_log import AuditLog
from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding
from app.models.rental_relay_case import RentalRelayCase
from app.models.warehouse import Warehouse
from app.services.accessory_relay_chain_service import (
    AccessoryRelayChainConflictError,
    AccessoryRelayChainService,
    AccessoryRelayChainTransactionRequiredError,
)
from app.services.relay.relay_case_service import RelayCaseService
from app.services.relay.mutation_service import (
    RelayStatusMutationConflict,
    RelayStatusMutationPersistenceError,
    RelayStatusMutationService,
)
from sqlalchemy.exc import SQLAlchemyError


UNIT_A = "a0000000-0000-4000-8000-000000000001"
UNIT_B = "b0000000-0000-4000-8000-000000000002"


def _window(rental):
    return (
        datetime.combine(rental.planned_ship_out_date, time.min),
        datetime.combine(
            rental.planned_return_date + timedelta(days=1),
            time.min,
        ),
    )


def _seed_chain(*, a_to_b="agreed", b_to_c="agreed", second_unit=True):
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
    db.session.add_all((warehouse, accessory_type, device))
    db.session.flush()
    rentals = []
    for index, planned_ship_date in enumerate(
        (date(2026, 9, 1), date(2026, 9, 5), date(2026, 9, 9))
    ):
        rental = Rental(
            device=device,
            start_date=planned_ship_date + timedelta(days=2),
            end_date=planned_ship_date + timedelta(days=4),
            planned_ship_out_date=planned_ship_date,
            planned_return_date=planned_ship_date + timedelta(days=6),
            logistics_days=1,
            customer_name=f"客户 {index}",
        )
        db.session.add(rental)
        rentals.append(rental)
    db.session.flush()
    units = [
        AccessoryUnit(
            id=UNIT_A,
            accessory_type=accessory_type,
            warehouse=warehouse,
            current_holder_rental_id=rentals[0].id,
        )
    ]
    if second_unit:
        units.append(
            AccessoryUnit(
                id=UNIT_B,
                accessory_type=accessory_type,
                warehouse=warehouse,
            )
        )
    cases = [
        RentalRelayCase(
            predecessor_rental_id=rentals[0].id,
            successor_rental_id=rentals[1].id,
            status=a_to_b,
        ),
        RentalRelayCase(
            predecessor_rental_id=rentals[1].id,
            successor_rental_id=rentals[2].id,
            status=b_to_c,
        ),
    ]
    db.session.add_all((*units, *cases))
    db.session.flush()
    start_at, end_at = _window(rentals[0])
    db.session.add(
        RentalAccessoryUnitLink(
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            accessory_unit_id=UNIT_A,
            reservation_start_at=start_at,
            reservation_end_at=end_at,
        )
    )
    db.session.commit()
    return warehouse, accessory_type, device, rentals, units, cases


def _add_request(rental, accessory_type):
    db.session.add(
        RentalAccessoryRequest(
            rental_id=rental.id,
            accessory_type_id=accessory_type.id,
            name_snapshot=accessory_type.display_name,
        )
    )


def _add_link(rental, accessory_type, unit, *, source_case=None):
    start_at, end_at = _window(rental)
    db.session.add(
        RentalAccessoryUnitLink(
            rental_id=rental.id,
            accessory_type_id=accessory_type.id,
            accessory_unit_id=unit.id,
            reservation_start_at=start_at,
            reservation_end_at=end_at,
            source_relay_case_id=(source_case.id if source_case else None),
        )
    )


def _recompute(service, case, operation_key):
    return service.recompute_from_case(
        relay_case_id=case.id,
        actor_type="tenant_user",
        actor_id="operator-1",
        operation_key=operation_key,
    )


def _mutate_relay_status(
    session,
    predecessor,
    successor,
    status,
    operation_key,
):
    return RelayStatusMutationService.update(
        tenant_session=session,
        predecessor_id=predecessor.id,
        successor_id=successor.id,
        status=status,
        accessory_note_provided=False,
        accessory_note=None,
        database_now=datetime(2026, 8, 23, 8, tzinfo=timezone.utc),
        actor_id="operator-1",
        operation_key=operation_key,
        tenant_timezone="Asia/Shanghai",
    )


def _project_relay_status(
    session,
    predecessor,
    successor,
    status,
    operation_key,
    *,
    tracking_number=None,
):
    return RelayStatusMutationService.project_external_stage(
        tenant_session=session,
        predecessor_id=predecessor.id,
        successor_id=successor.id,
        status=status,
        sf_tracking_number=tracking_number,
        database_now=datetime(2026, 8, 23, 9, tzinfo=timezone.utc),
        actor_id="operator-1",
        operation_key=operation_key,
        tenant_timezone="Asia/Shanghai",
    )


def _ready_warehouse(name, *, is_default=False):
    return Warehouse(
        name=name,
        status="active",
        setup_state="ready",
        is_default=is_default,
        default_slot=1 if is_default else None,
        contact_name="负责人",
        contact_phone="13800138000",
        province="广东省",
        city="深圳市",
        district="南山区",
        address_detail=f"{name}测试地址",
    )


def _seed_inspection_reassignment(*, second_unit=True):
    source_warehouse = _ready_warehouse("原仓", is_default=True)
    inspection_warehouse = _ready_warehouse("验货仓")
    accessory_type = AccessoryType(
        name="tripod",
        display_name="三脚架",
        tracking_mode="logical_unit",
    )
    returned_device = Device(name="已归还主设备", warehouse=inspection_warehouse)
    future_device = Device(name="未来订单主设备", warehouse=source_warehouse)
    db.session.add_all(
        (
            source_warehouse,
            inspection_warehouse,
            accessory_type,
            returned_device,
            future_device,
        )
    )
    db.session.flush()
    returned_rental = Rental(
        device=returned_device,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 4),
        planned_ship_out_date=date(2026, 7, 31),
        planned_return_date=date(2026, 8, 5),
        logistics_days=1,
        customer_name="已归还客户",
        status="returned",
    )
    future_rental = Rental(
        device=future_device,
        start_date=date(2026, 9, 2),
        end_date=date(2026, 9, 5),
        planned_ship_out_date=date(2026, 9, 1),
        planned_return_date=date(2026, 9, 6),
        logistics_days=1,
        customer_name="未来客户",
    )
    db.session.add_all((returned_rental, future_rental))
    db.session.flush()
    inspected_unit = AccessoryUnit(
        id=UNIT_A,
        accessory_type=accessory_type,
        warehouse=source_warehouse,
        current_holder_rental_id=returned_rental.id,
    )
    units = [inspected_unit]
    if second_unit:
        units.append(
            AccessoryUnit(
                id=UNIT_B,
                accessory_type=accessory_type,
                warehouse=source_warehouse,
            )
        )
    db.session.add_all(units)
    db.session.flush()
    _add_link(returned_rental, accessory_type, inspected_unit)
    _add_request(future_rental, accessory_type)
    _add_link(future_rental, accessory_type, inspected_unit)
    db.session.commit()
    return (
        source_warehouse,
        inspection_warehouse,
        accessory_type,
        returned_rental,
        future_rental,
        units,
    )


def _inspect_and_reassign(
    service,
    *,
    rental,
    accessory_type,
    warehouse,
    outcome="received_normal",
    operation_key="inspection-1",
):
    return service.inspect_return_and_reassign(
        rental_id=rental.id,
        accessory_type_id=accessory_type.id,
        warehouse_id=warehouse.id,
        outcome=outcome,
        occurred_at=datetime(2026, 8, 10, 12),
        actor_type="tenant_user",
        actor_id="operator-1",
        operation_key=operation_key,
    )


def test_recompute_requires_explicit_transaction(application):
    _, _, _, _, _, cases = _seed_chain()
    service = AccessoryRelayChainService(db.session())

    with pytest.raises(AccessoryRelayChainTransactionRequiredError):
        _recompute(service, cases[0], "agreement-1")


def test_inspection_reassigns_cross_warehouse_future_request_atomically(
    application,
):
    (
        _,
        inspection_warehouse,
        accessory_type,
        returned_rental,
        future_rental,
        units,
    ) = _seed_inspection_reassignment()
    session = db.session()
    service = AccessoryRelayChainService(session)

    with session.begin():
        result = _inspect_and_reassign(
            service,
            rental=returned_rental,
            accessory_type=accessory_type,
            warehouse=inspection_warehouse,
        )

    assert asdict(result) == {
        "type_code": "tripod",
        "display_name": "三脚架",
        "outcome": "received_normal",
        "retained_relay_count": 0,
        "reassigned_count": 1,
        "shortage_count": 0,
        "affected_rental_ids": (future_rental.id,),
        "shortage_rental_ids": (),
    }
    assert UNIT_A not in repr(result)
    assert UNIT_B not in repr(result)
    assert units[0].current_holder_rental_id is None
    assert units[0].warehouse_id == inspection_warehouse.id
    assert units[0].condition_status == "active"
    future_link = RentalAccessoryUnitLink.query.filter_by(
        rental_id=future_rental.id,
        accessory_type_id=accessory_type.id,
    ).one()
    assert future_link.accessory_unit_id == UNIT_B
    assert future_link.source_relay_case_id is None
    assert AccessoryUnitEvent.query.filter_by(event_type="unlinked").count() == 1
    assert AccessoryUnitEvent.query.filter_by(event_type="linked").count() == 1


def test_inspection_keeps_request_as_shortage_when_no_local_candidate(
    application,
):
    (
        _,
        inspection_warehouse,
        accessory_type,
        returned_rental,
        future_rental,
        units,
    ) = _seed_inspection_reassignment(second_unit=False)
    session = db.session()
    service = AccessoryRelayChainService(session)

    with session.begin():
        result = _inspect_and_reassign(
            service,
            rental=returned_rental,
            accessory_type=accessory_type,
            warehouse=inspection_warehouse,
        )

    assert result.shortage_count == 1
    assert result.reassigned_count == 0
    assert result.affected_rental_ids == (future_rental.id,)
    assert result.shortage_rental_ids == (future_rental.id,)
    assert units[0].warehouse_id == inspection_warehouse.id
    assert (
        RentalAccessoryRequest.query.filter_by(
            rental_id=future_rental.id,
            accessory_type_id=accessory_type.id,
        ).count()
        == 1
    )
    assert (
        RentalAccessoryUnitLink.query.filter_by(
            rental_id=future_rental.id,
            accessory_type_id=accessory_type.id,
        ).count()
        == 0
    )


def test_inspection_rolls_back_when_future_fulfillment_is_frozen(application):
    (
        source_warehouse,
        inspection_warehouse,
        accessory_type,
        returned_rental,
        future_rental,
        units,
    ) = _seed_inspection_reassignment()

    class FrozenFulfillmentRepository:
        @staticmethod
        def fulfillment_execution_is_frozen(rental_ids):
            assert rental_ids == (future_rental.id,)
            return True

    session = db.session()
    service = AccessoryRelayChainService(
        session,
        inventory_repository=FrozenFulfillmentRepository(),
    )
    with pytest.raises(AccessoryRelayChainConflictError):
        with session.begin():
            _inspect_and_reassign(
                service,
                rental=returned_rental,
                accessory_type=accessory_type,
                warehouse=inspection_warehouse,
            )

    assert units[0].warehouse_id == source_warehouse.id
    assert units[0].current_holder_rental_id == returned_rental.id
    assert units[0].condition_status == "active"
    future_link = RentalAccessoryUnitLink.query.filter_by(
        rental_id=future_rental.id,
        accessory_type_id=accessory_type.id,
    ).one()
    assert future_link.accessory_unit_id == UNIT_A
    assert AccessoryUnitEvent.query.count() == 0


@pytest.mark.parametrize(
    ("outcome", "condition_status", "holder_is_cleared"),
    (
        ("received_damaged", "maintenance", True),
        ("missing", "lost", False),
    ),
)
def test_abnormal_inspection_reassigns_future_request_without_reusing_unit(
    application,
    outcome,
    condition_status,
    holder_is_cleared,
):
    (
        _,
        inspection_warehouse,
        accessory_type,
        returned_rental,
        future_rental,
        units,
    ) = _seed_inspection_reassignment()
    session = db.session()
    service = AccessoryRelayChainService(session)

    with session.begin():
        result = _inspect_and_reassign(
            service,
            rental=returned_rental,
            accessory_type=accessory_type,
            warehouse=inspection_warehouse,
            outcome=outcome,
            operation_key=f"inspection-{outcome}",
        )

    assert result.reassigned_count == 1
    assert result.shortage_count == 0
    assert result.affected_rental_ids == (future_rental.id,)
    assert result.shortage_rental_ids == ()
    assert units[0].condition_status == condition_status
    assert (units[0].current_holder_rental_id is None) is holder_is_cleared
    future_link = RentalAccessoryUnitLink.query.filter_by(
        rental_id=future_rental.id,
        accessory_type_id=accessory_type.id,
    ).one()
    assert future_link.accessory_unit_id == UNIT_B


def test_normal_inspection_retains_reachable_agreed_same_device_chain(
    application,
):
    warehouse, accessory_type, _, rentals, units, cases = _seed_chain()
    session = db.session()
    service = AccessoryRelayChainService(session)
    with session.begin():
        _recompute(service, cases[0], "prepare-inspection-chain")

    with session.begin():
        result = service.inspect_return_and_reassign(
            rental_id=rentals[0].id,
            accessory_type_id=accessory_type.id,
            warehouse_id=warehouse.id,
            outcome="received_normal",
            occurred_at=datetime(2026, 8, 31, 12),
            actor_type="tenant_user",
            actor_id="operator-1",
            operation_key="inspection-retain-chain",
        )

    assert result.retained_relay_count == 2
    assert result.reassigned_count == 0
    assert result.shortage_count == 0
    assert result.affected_rental_ids == ()
    assert result.shortage_rental_ids == ()
    future_links = RentalAccessoryUnitLink.query.filter(
        RentalAccessoryUnitLink.rental_id.in_((rentals[1].id, rentals[2].id))
    ).all()
    assert {link.accessory_unit_id for link in future_links} == {UNIT_A}
    assert {link.source_relay_case_id for link in future_links} == {
        cases[0].id,
        cases[1].id,
    }
    assert units[0].current_holder_rental_id is None


def test_agreed_chain_creates_neutral_links_through_requestless_rentals(
    application,
):
    _, accessory_type, _, rentals, _, cases = _seed_chain()
    session = db.session()
    service = AccessoryRelayChainService(session)

    with session.begin():
        result = _recompute(service, cases[0], "agreement-neutral-chain")

    assert asdict(result) == {
        "linked_count": 2,
        "unlinked_count": 0,
        "shortage_count": 0,
        "shortage_type_codes": (),
    }
    links = RentalAccessoryUnitLink.query.order_by(
        RentalAccessoryUnitLink.rental_id
    ).all()
    assert [link.rental_id for link in links] == [rental.id for rental in rentals]
    assert {link.accessory_unit_id for link in links} == {UNIT_A}
    assert links[1].source_relay_case_id == cases[0].id
    assert links[2].source_relay_case_id == cases[1].id
    assert RentalAccessoryRequest.query.count() == 0
    assert AccessoryUnitEvent.query.filter_by(event_type="linked").count() == 2

    db.session.commit()
    with session.begin():
        replay = _recompute(service, cases[0], "agreement-neutral-chain")
    assert replay.linked_count == 0
    assert replay.unlinked_count == 0
    assert AccessoryUnitEvent.query.filter_by(event_type="linked").count() == 2
    assert accessory_type.name not in repr(links[0].accessory_unit_id)


def test_late_upstream_agreement_replaces_entire_downstream_plan(application):
    _, accessory_type, _, rentals, units, cases = _seed_chain(a_to_b="pending")
    _add_request(rentals[1], accessory_type)
    _add_request(rentals[2], accessory_type)
    _add_link(rentals[1], accessory_type, units[1])
    _add_link(
        rentals[2],
        accessory_type,
        units[1],
        source_case=cases[1],
    )
    db.session.commit()
    session = db.session()
    service = AccessoryRelayChainService(session)

    with session.begin():
        cases[0].status = "agreed"
        result = _recompute(service, cases[0], "late-upstream-agreement")

    assert (result.linked_count, result.unlinked_count) == (2, 2)
    links = RentalAccessoryUnitLink.query.order_by(
        RentalAccessoryUnitLink.rental_id
    ).all()
    assert {link.accessory_unit_id for link in links} == {UNIT_A}
    assert links[1].source_relay_case_id == cases[0].id
    assert links[2].source_relay_case_id == cases[1].id
    assert AccessoryUnitEvent.query.filter_by(event_type="unlinked").count() == 2
    assert AccessoryUnitEvent.query.filter_by(event_type="linked").count() == 2


def test_revoked_upstream_agreement_replans_requests_and_downstream_edge(
    application,
):
    _, accessory_type, _, rentals, units, cases = _seed_chain()
    _add_request(rentals[1], accessory_type)
    _add_link(
        rentals[1],
        accessory_type,
        units[0],
        source_case=cases[0],
    )
    _add_link(
        rentals[2],
        accessory_type,
        units[0],
        source_case=cases[1],
    )
    db.session.commit()
    session = db.session()
    service = AccessoryRelayChainService(session)

    with session.begin():
        cases[0].status = "notified"
        result = _recompute(service, cases[0], "revoke-upstream")

    assert (result.linked_count, result.unlinked_count) == (2, 2)
    links = RentalAccessoryUnitLink.query.order_by(
        RentalAccessoryUnitLink.rental_id
    ).all()
    assert links[1].accessory_unit_id == UNIT_B
    assert links[1].source_relay_case_id is None
    assert links[2].accessory_unit_id == UNIT_B
    assert links[2].source_relay_case_id == cases[1].id
    assert units[0].current_holder_rental_id == rentals[0].id
    assert units[1].current_holder_rental_id is None


def test_shortage_keeps_request_without_link_and_does_not_block_relay(
    application,
):
    _, accessory_type, _, rentals, units, cases = _seed_chain(
        a_to_b="pending",
        b_to_c="pending",
        second_unit=False,
    )
    # The only unit is physically held but has no usable planned link in this
    # test's local-allocation path.
    anchor_link = RentalAccessoryUnitLink.query.filter_by(rental_id=rentals[0].id).one()
    db.session.delete(anchor_link)
    _add_request(rentals[1], accessory_type)
    db.session.commit()
    session = db.session()
    service = AccessoryRelayChainService(session)

    with session.begin():
        result = _recompute(service, cases[0], "shortage-warning")

    assert asdict(result) == {
        "linked_count": 0,
        "unlinked_count": 0,
        "shortage_count": 1,
        "shortage_type_codes": ("tripod",),
    }
    assert RentalAccessoryRequest.query.filter_by(rental_id=rentals[1].id).count() == 1
    assert RentalAccessoryUnitLink.query.count() == 0
    assert UNIT_A not in repr(result)
    assert units[0].current_holder_rental_id == rentals[0].id


def test_recompute_rejects_replacing_a_unit_already_dispatched_to_successor(
    application,
):
    _, accessory_type, _, rentals, units, cases = _seed_chain()
    _add_request(rentals[1], accessory_type)
    _add_link(rentals[1], accessory_type, units[1])
    units[1].current_holder_rental_id = rentals[1].id
    db.session.commit()
    session = db.session()
    service = AccessoryRelayChainService(session)

    with pytest.raises(AccessoryRelayChainConflictError) as caught:
        with session.begin():
            _recompute(service, cases[0], "held-unit-conflict")

    assert caught.value.code == "ACCESSORY_RELAY_CHAIN_REVIEW_REQUIRED"
    assert UNIT_A not in str(caught.value)
    assert UNIT_B not in str(caught.value)
    assert (
        RentalAccessoryUnitLink.query.filter_by(
            rental_id=rentals[1].id,
            accessory_unit_id=UNIT_B,
        ).count()
        == 1
    )
    assert AccessoryUnitEvent.query.count() == 0


def test_handoff_moves_all_carried_units_and_replays_idempotently(application):
    _, _, _, rentals, units, cases = _seed_chain()
    session = db.session()
    service = AccessoryRelayChainService(session)
    with session.begin():
        _recompute(service, cases[0], "prepare-handoff")

    with session.begin():
        result = service.handoff_case(
            relay_case_id=cases[0].id,
            actor_type="tenant_user",
            actor_id="operator-1",
            operation_key="ship-edge-a-b",
        )

    assert asdict(result) == {
        "handed_off_count": 1,
        "accessory_type_codes": ("tripod",),
    }
    assert units[0].current_holder_rental_id == rentals[1].id
    assert units[0].row_version == 2
    assert (
        AccessoryUnitEvent.query.filter_by(
            event_type="relay_handoff",
            relay_case_id=cases[0].id,
        ).count()
        == 1
    )

    db.session.commit()
    with session.begin():
        replay = service.handoff_case(
            relay_case_id=cases[0].id,
            actor_type="tenant_user",
            actor_id="operator-1",
            operation_key="ship-edge-a-b",
        )
    assert replay == result
    assert units[0].row_version == 2
    assert (
        AccessoryUnitEvent.query.filter_by(
            event_type="relay_handoff",
            relay_case_id=cases[0].id,
        ).count()
        == 1
    )


def test_recompute_refuses_to_downgrade_an_executed_handoff(application):
    _, _, _, _, _, cases = _seed_chain()
    session = db.session()
    service = AccessoryRelayChainService(session)
    with session.begin():
        _recompute(service, cases[0], "prepare-executed-edge")
    with session.begin():
        service.handoff_case(
            relay_case_id=cases[0].id,
            actor_type="tenant_user",
            actor_id="operator-1",
            operation_key="execute-edge",
        )

    with pytest.raises(AccessoryRelayChainConflictError):
        with session.begin():
            cases[0].status = "pending"
            _recompute(service, cases[0], "illegal-downgrade")

    assert cases[0].status == "agreed"


def test_relay_status_service_composes_agreement_and_handoff_atomically(
    application,
    monkeypatch,
):
    _, accessory_type, _, rentals, units, cases = _seed_chain(
        a_to_b="pending",
        b_to_c="pending",
    )
    _add_request(rentals[1], accessory_type)
    db.session.commit()
    shipped_rental_ids = []

    class FakeXianyuService:
        def ship_order(self, rental):
            shipped_rental_ids.append(rental.id)
            return {"success": True, "message": "ok"}

    from app.services import xianyu_order_service

    monkeypatch.setattr(
        xianyu_order_service,
        "get_xianyu_service",
        lambda: FakeXianyuService(),
    )

    agreed = RelayCaseService.update_case(
        rentals[0].id,
        rentals[1].id,
        "agreed",
        operation_key="http-agree-a-b",
    )
    successor_link = RentalAccessoryUnitLink.query.filter_by(
        rental_id=rentals[1].id,
        accessory_type_id=accessory_type.id,
    ).one()
    assert successor_link.accessory_unit_id == UNIT_A
    assert successor_link.source_relay_case_id == cases[0].id
    assert agreed.accessory_chain["linked_count"] == 1
    assert (
        RentalRelayBinding.query.filter_by(
            predecessor_rental_id=rentals[0].id,
            successor_rental_id=rentals[1].id,
        ).count()
        == 1
    )

    shipped = RelayCaseService.update_case(
        rentals[0].id,
        rentals[1].id,
        "shipped",
        sf_tracking_number="SF1234567890",
    )
    assert shipped.relay_case.status == "shipped"
    assert shipped.accessory_chain["handed_off_count"] == 1
    assert units[0].current_holder_rental_id == rentals[1].id
    assert rentals[1].status == "shipped"
    assert shipped_rental_ids == [rentals[1].id]
    assert (
        AccessoryUnitEvent.query.filter_by(
            event_type="relay_handoff",
            relay_case_id=cases[0].id,
        ).count()
        == 1
    )


def test_relay_status_service_rolls_back_shipping_when_holder_is_out_of_order(
    application,
    monkeypatch,
):
    _, _, _, rentals, units, cases = _seed_chain(
        a_to_b="pending",
        b_to_c="pending",
    )
    units[0].current_holder_rental_id = rentals[2].id
    db.session.commit()

    RelayCaseService.update_case(
        rentals[0].id,
        rentals[1].id,
        "agreed",
        operation_key="agree-before-holder-conflict",
    )
    provider_called = []
    from app.services import xianyu_order_service

    monkeypatch.setattr(
        xianyu_order_service,
        "get_xianyu_service",
        lambda: provider_called.append(True),
    )

    with pytest.raises(AccessoryRelayChainConflictError):
        RelayCaseService.update_case(
            rentals[0].id,
            rentals[1].id,
            "shipped",
            sf_tracking_number="SF2234567890",
            operation_key="ship-holder-conflict",
        )

    db.session.refresh(cases[0])
    db.session.refresh(rentals[1])
    assert cases[0].status == "agreed"
    assert rentals[1].status == "not_shipped"
    assert rentals[1].ship_out_tracking_no is None
    assert units[0].current_holder_rental_id == rentals[2].id
    assert AccessoryUnitEvent.query.filter_by(event_type="relay_handoff").count() == 0
    assert provider_called == []


def test_tenant_projection_executes_full_chain_in_order_and_replays_earlier_edge(
    application,
    monkeypatch,
):
    _, accessory_type, _, rentals, units, cases = _seed_chain(
        a_to_b="pending",
        b_to_c="pending",
        second_unit=False,
    )
    session = db.session()

    from app.services import xianyu_order_service

    monkeypatch.setattr(
        xianyu_order_service,
        "get_xianyu_service",
        lambda: pytest.fail("tenant projection must not resolve a provider"),
    )

    with session.begin():
        _mutate_relay_status(
            session,
            rentals[1],
            rentals[2],
            "agreed",
            "agree-b-c-first",
        )
    with session.begin():
        upstream = _mutate_relay_status(
            session,
            rentals[0],
            rentals[1],
            "agreed",
            "agree-a-b-second",
        )

    assert upstream.accessory_chain["linked_count"] == 2
    assert RentalAccessoryRequest.query.count() == 0
    assert {
        link.rental_id: link.accessory_unit_id
        for link in RentalAccessoryUnitLink.query.order_by(
            RentalAccessoryUnitLink.rental_id
        ).all()
    } == {
        rentals[0].id: UNIT_A,
        rentals[1].id: UNIT_A,
        rentals[2].id: UNIT_A,
    }
    session.rollback()

    with pytest.raises(RelayStatusMutationConflict):
        with session.begin():
            _project_relay_status(
                session,
                rentals[1],
                rentals[2],
                "shipped",
                "ship-b-c-too-early",
                tracking_number="SF-BC-1",
            )
    assert units[0].current_holder_rental_id == rentals[0].id
    assert cases[1].status == "agreed"
    session.rollback()

    with session.begin():
        first_handoff = _project_relay_status(
            session,
            rentals[0],
            rentals[1],
            "shipped",
            "ship-a-b",
            tracking_number="SF-AB-1",
        )
    assert first_handoff.accessory_chain["handed_off_count"] == 1
    assert units[0].current_holder_rental_id == rentals[1].id
    session.rollback()

    with session.begin():
        second_handoff = _project_relay_status(
            session,
            rentals[1],
            rentals[2],
            "shipped",
            "ship-b-c",
            tracking_number="SF-BC-1",
        )
    assert second_handoff.accessory_chain["handed_off_count"] == 1
    assert units[0].current_holder_rental_id == rentals[2].id
    session.rollback()

    # Replaying the earlier edge after custody has legitimately advanced to C
    # proves idempotency from its immutable event without rewinding holder.
    with session.begin():
        replay = _project_relay_status(
            session,
            rentals[0],
            rentals[1],
            "shipped",
            "ship-a-b",
            tracking_number="SF-AB-1",
        )
    assert replay.accessory_chain["handed_off_count"] == 1
    assert units[0].current_holder_rental_id == rentals[2].id
    assert AccessoryUnitEvent.query.filter_by(event_type="relay_handoff").count() == 2
    session.rollback()

    with session.begin():
        completed = _project_relay_status(
            session,
            rentals[1],
            rentals[2],
            "completed",
            "complete-b-c",
            tracking_number="SF-BC-1",
        )
    assert completed.relay_case.status == "completed"
    assert units[0].current_holder_rental_id == rentals[2].id
    assert AccessoryUnitEvent.query.filter_by(event_type="relay_handoff").count() == 2
    assert (
        AuditLog.query.filter(
            AuditLog.action == "relay_case_status_changed",
            AuditLog.details["external_projection"].as_boolean().is_(True),
        ).count()
        == 3
    )
    assert accessory_type.id is not None


def test_tenant_projection_rolls_back_handoff_when_audit_persistence_fails(
    application,
    monkeypatch,
):
    _, _, _, rentals, units, cases = _seed_chain(
        a_to_b="pending",
        b_to_c="pending",
        second_unit=False,
    )
    session = db.session()
    with session.begin():
        _mutate_relay_status(
            session,
            rentals[0],
            rentals[1],
            "agreed",
            "agree-before-audit-failure",
        )

    from app.services.relay import mutation_service

    monkeypatch.setattr(
        mutation_service,
        "AuditLog",
        lambda **_values: (_ for _ in ()).throw(
            SQLAlchemyError("injected audit failure")
        ),
    )
    with pytest.raises(RelayStatusMutationPersistenceError):
        with session.begin():
            _project_relay_status(
                session,
                rentals[0],
                rentals[1],
                "shipped",
                "ship-with-audit-failure",
                tracking_number="SF-ROLLBACK-1",
            )

    session.refresh(cases[0])
    session.refresh(rentals[1])
    session.refresh(units[0])
    assert cases[0].status == "agreed"
    assert cases[0].sf_tracking_number is None
    assert rentals[1].status == "not_shipped"
    assert rentals[1].ship_out_tracking_no is None
    assert units[0].current_holder_rental_id == rentals[0].id
    assert AccessoryUnitEvent.query.filter_by(event_type="relay_handoff").count() == 0
