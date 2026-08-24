"""Opt-in real-MySQL contention proof for opposite warehouse moves.

The normal test suite only collects and skips this module.  A run is allowed
only when the caller explicitly enables real contention tests and the shared
database guard has accepted the exact ``inventory_management_test`` schema.
No production schema, provider, NAS, or network service is addressed here.

Logical accessory unit identifiers remain internal throughout the assertions:
the proof observes only device, rental, warehouse, movement, request, link
window, and event facts.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import os
from threading import Barrier, Lock, Thread
from time import monotonic
from typing import Callable
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

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
from app.models.warehouse import DeviceWarehouseMovement, Warehouse
from app.services.warehouse_service import WarehouseService
from tests.support.test_database import (
    build_mysql_test_config,
    guarded_mysql_test_metadata,
)


_REAL_CONTENTION_ENABLED = (
    os.environ.get("RUN_REAL_MYSQL_CONTENTION_TESTS", "").lower() == "true"
)
pytestmark = pytest.mark.skipif(
    not _REAL_CONTENTION_ENABLED,
    reason=(
        "real MySQL contention requires "
        "RUN_REAL_MYSQL_CONTENTION_TESTS=true"
    ),
)

_BARRIER_TIMEOUT_SECONDS = 15
_LOCK_WAIT_TIMEOUT_SECONDS = 12
_WORKER_TIMEOUT_SECONDS = 30


@pytest.fixture(scope="module")
def mysql_application():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.fail("TEST_DATABASE_URL is required for real contention tests")
    if os.environ.get("TESTING", "").lower() != "true":
        pytest.fail("TESTING=true is required for real contention tests")

    application = create_app(build_mysql_test_config())
    with application.app_context():
        if db.engine.dialect.name != "mysql":
            pytest.fail("real contention tests require a MySQL-protocol engine")
        with guarded_mysql_test_metadata(db.engine, db.metadata):
            try:
                yield application
            finally:
                db.session.remove()


@dataclass(frozen=True, slots=True)
class _SeededOppositeMoves:
    warehouse_ids: tuple[int, int]
    device_ids: tuple[int, int]
    rental_ids: tuple[int, int]
    accessory_type_id: int
    reservation_window: tuple[datetime, datetime]
    rental_dates: tuple[date, date, date, date]


@dataclass(frozen=True, slots=True)
class _MoveInvocation:
    device_id: int
    target_warehouse_id: int
    expected_current_warehouse_id: int
    expected_preview_revision: str
    actor_user_id: str


@dataclass(frozen=True, slots=True)
class _MoveOutcome:
    state: str
    error_type: str | None
    device_id: int
    from_warehouse_id: int | None = None
    to_warehouse_id: int | None = None
    affected_rental_ids: tuple[int, ...] = ()
    fulfillment_states: tuple[str, ...] = ()


def _factory() -> Callable[[], Session]:
    return sessionmaker(bind=db.engine, expire_on_commit=False)


def _ready_warehouse(label: str, *, is_default: bool = False) -> Warehouse:
    warehouse = Warehouse(
        status="active",
        setup_state="pending",
        is_default=is_default,
        default_slot=1 if is_default else None,
    )
    warehouse.mark_ready(
        name=f"mysql-opposite-move-{label}",
        contact_name="测试负责人",
        contact_phone="13800138000",
        province="广东省",
        city="深圳市",
        district="南山区",
        address_detail=f"隔离测试库{label}仓地址",
    )
    return warehouse


def _future_rental(
    device: Device,
    *,
    suffix: str,
    start_on: date,
    end_on: date,
) -> Rental:
    return Rental(
        device=device,
        start_date=start_on,
        end_date=end_on,
        customer_name=f"并发调仓客户-{suffix}",
        customer_phone="13800138000",
        destination="隔离测试目的地",
        xianyu_order_no=f"MYSQL-MOVE-{suffix}",
        logistics_days=1,
        planned_ship_out_date=start_on - timedelta(days=1),
        planned_return_date=end_on + timedelta(days=1),
        status="not_shipped",
    )


def _seed_opposite_moves(session_factory) -> _SeededOppositeMoves:
    suffix = uuid4().hex[:12]
    customer_start = date.today() + timedelta(days=30)
    customer_end = customer_start + timedelta(days=2)
    planned_ship = customer_start - timedelta(days=1)
    planned_return = customer_end + timedelta(days=1)
    reservation_window = (
        datetime.combine(planned_ship, time.min),
        datetime.combine(planned_return + timedelta(days=1), time.min),
    )

    with session_factory.begin() as session:
        warehouse_a = _ready_warehouse(f"a-{suffix}", is_default=True)
        warehouse_b = _ready_warehouse(f"b-{suffix}")
        device_a = Device(
            name=f"mysql-opposite-device-a-{suffix}",
            serial_number=f"mysql-opposite-a-{suffix}",
            is_accessory=False,
            warehouse=warehouse_a,
        )
        device_b = Device(
            name=f"mysql-opposite-device-b-{suffix}",
            serial_number=f"mysql-opposite-b-{suffix}",
            is_accessory=False,
            warehouse=warehouse_b,
        )
        accessory_type = AccessoryType(
            name=f"mysql-tripod-{suffix}",
            display_name="并发调仓三脚架",
            tracking_mode="logical_unit",
            is_active=True,
        )
        session.add_all(
            (warehouse_a, warehouse_b, device_a, device_b, accessory_type)
        )
        session.flush()

        session.add_all(
            (
                DeviceAccessoryConfig(
                    device_id=device_a.id,
                    accessory_type_id=accessory_type.id,
                    enabled=True,
                ),
                DeviceAccessoryConfig(
                    device_id=device_b.id,
                    accessory_type_id=accessory_type.id,
                    enabled=True,
                ),
            )
        )
        rental_a = _future_rental(
            device_a,
            suffix=f"a-{suffix}",
            start_on=customer_start,
            end_on=customer_end,
        )
        rental_b = _future_rental(
            device_b,
            suffix=f"b-{suffix}",
            start_on=customer_start,
            end_on=customer_end,
        )
        session.add_all((rental_a, rental_b))
        session.flush()

        session.add_all(
            (
                RentalAccessoryRequest(
                    rental_id=rental_a.id,
                    accessory_type_id=accessory_type.id,
                    name_snapshot=accessory_type.display_name,
                ),
                RentalAccessoryRequest(
                    rental_id=rental_b.id,
                    accessory_type_id=accessory_type.id,
                    name_snapshot=accessory_type.display_name,
                ),
            )
        )

        # Each warehouse starts with one ordinarily linked source unit and one
        # unheld candidate.  The extra candidate lets either globally ordered
        # move commit first without turning the opposite move into a shortage.
        linked_unit_a = AccessoryUnit(
            accessory_type_id=accessory_type.id,
            warehouse_id=warehouse_a.id,
            condition_status="active",
        )
        candidate_unit_a = AccessoryUnit(
            accessory_type_id=accessory_type.id,
            warehouse_id=warehouse_a.id,
            condition_status="active",
        )
        linked_unit_b = AccessoryUnit(
            accessory_type_id=accessory_type.id,
            warehouse_id=warehouse_b.id,
            condition_status="active",
        )
        candidate_unit_b = AccessoryUnit(
            accessory_type_id=accessory_type.id,
            warehouse_id=warehouse_b.id,
            condition_status="active",
        )
        session.add_all(
            (
                linked_unit_a,
                candidate_unit_a,
                linked_unit_b,
                candidate_unit_b,
            )
        )
        session.flush()

        session.add_all(
            (
                RentalAccessoryUnitLink(
                    rental_id=rental_a.id,
                    accessory_type_id=accessory_type.id,
                    accessory_unit_id=linked_unit_a.id,
                    reservation_start_at=reservation_window[0],
                    reservation_end_at=reservation_window[1],
                ),
                RentalAccessoryUnitLink(
                    rental_id=rental_b.id,
                    accessory_type_id=accessory_type.id,
                    accessory_unit_id=linked_unit_b.id,
                    reservation_start_at=reservation_window[0],
                    reservation_end_at=reservation_window[1],
                ),
                AccessoryUnitEvent(
                    unit_id=linked_unit_a.id,
                    event_type="linked",
                    main_device_id=device_a.id,
                    rental_id=rental_a.id,
                    to_warehouse_id=warehouse_a.id,
                    actor_type="system",
                    actor_id="mysql-opposite-move-seed",
                    reason="test_seed",
                    idempotency_key=f"mysql-opposite-seed:a:{suffix}",
                ),
                AccessoryUnitEvent(
                    unit_id=linked_unit_b.id,
                    event_type="linked",
                    main_device_id=device_b.id,
                    rental_id=rental_b.id,
                    to_warehouse_id=warehouse_b.id,
                    actor_type="system",
                    actor_id="mysql-opposite-move-seed",
                    reason="test_seed",
                    idempotency_key=f"mysql-opposite-seed:b:{suffix}",
                ),
            )
        )
        return _SeededOppositeMoves(
            warehouse_ids=(warehouse_a.id, warehouse_b.id),
            device_ids=(device_a.id, device_b.id),
            rental_ids=(rental_a.id, rental_b.id),
            accessory_type_id=accessory_type.id,
            reservation_window=reservation_window,
            rental_dates=(
                customer_start,
                customer_end,
                planned_ship,
                planned_return,
            ),
        )


def _preview_invocations(
    seeded: _SeededOppositeMoves,
) -> tuple[_MoveInvocation, _MoveInvocation]:
    warehouse_a, warehouse_b = seeded.warehouse_ids
    device_a, device_b = seeded.device_ids
    preview_a = WarehouseService.preview_device_move(
        device_id=device_a,
        target_warehouse_id=warehouse_b,
    )
    preview_b = WarehouseService.preview_device_move(
        device_id=device_b,
        target_warehouse_id=warehouse_a,
    )
    invocations = (
        _MoveInvocation(
            device_id=device_a,
            target_warehouse_id=warehouse_b,
            expected_current_warehouse_id=warehouse_a,
            expected_preview_revision=preview_a.revision,
            actor_user_id="mysql-opposite-move-a",
        ),
        _MoveInvocation(
            device_id=device_b,
            target_warehouse_id=warehouse_a,
            expected_current_warehouse_id=warehouse_b,
            expected_preview_revision=preview_b.revision,
            actor_user_id="mysql-opposite-move-b",
        ),
    )
    db.session.remove()
    return invocations


def _run_opposite_moves(
    application,
    invocations: tuple[_MoveInvocation, _MoveInvocation],
) -> tuple[tuple[_MoveOutcome, _MoveOutcome], float]:
    start_gate = Barrier(3, timeout=_BARRIER_TIMEOUT_SECONDS)
    outcome_lock = Lock()
    outcomes: list[_MoveOutcome | None] = [None, None]

    def move(index: int) -> None:
        invocation = invocations[index]
        with application.app_context():
            try:
                # A bounded InnoDB lock wait prevents a failed lock-order
                # proof from leaving a worker alive into schema teardown.
                db.session.execute(
                    text(
                        "SET SESSION innodb_lock_wait_timeout = "
                        f"{_LOCK_WAIT_TIMEOUT_SECONDS}"
                    )
                )
                # Hold each move's first, distinct device row before releasing
                # the barrier.  This proves two live transactions reach the
                # shared A/B warehouse-lock phase; it cannot pass merely
                # because one worker happened to finish before the other ran.
                db.session.execute(
                    select(Device.id)
                    .where(Device.id == invocation.device_id)
                    .with_for_update()
                ).scalar_one()
                start_gate.wait()
                result = WarehouseService.execute_device_move(
                    device_id=invocation.device_id,
                    target_warehouse_id=invocation.target_warehouse_id,
                    expected_current_warehouse_id=(
                        invocation.expected_current_warehouse_id
                    ),
                    expected_preview_revision=(
                        invocation.expected_preview_revision
                    ),
                    confirmation_token_confirmed=True,
                    actor_user_id=invocation.actor_user_id,
                    note="opposite warehouse contention proof",
                )
                outcome = _MoveOutcome(
                    state="committed",
                    error_type=None,
                    device_id=result.device_id,
                    from_warehouse_id=result.from_warehouse_id,
                    to_warehouse_id=result.to_warehouse_id,
                    affected_rental_ids=result.affected_rental_ids,
                    fulfillment_states=tuple(
                        fact.status for fact in result.accessory_fulfillment
                    ),
                )
            except BaseException as exc:  # retained only as a safe type name
                db.session.rollback()
                outcome = _MoveOutcome(
                    state="failed",
                    error_type=type(exc).__name__,
                    device_id=invocation.device_id,
                )
            finally:
                db.session.remove()
        with outcome_lock:
            outcomes[index] = outcome

    workers = tuple(
        Thread(
            target=move,
            args=(index,),
            name=f"warehouse-opposite-contention-{index}",
            daemon=True,
        )
        for index in range(2)
    )
    for worker in workers:
        worker.start()

    start_gate.wait()
    released_at = monotonic()
    deadline = released_at + _WORKER_TIMEOUT_SECONDS
    for worker in workers:
        worker.join(timeout=max(0.0, deadline - monotonic()))
    elapsed = monotonic() - released_at

    assert not any(worker.is_alive() for worker in workers), (
        "opposite warehouse move worker exceeded the bounded timeout"
    )
    assert all(outcome is not None for outcome in outcomes)
    return (outcomes[0], outcomes[1]), elapsed


def _assert_committed_facts(
    session_factory,
    seeded: _SeededOppositeMoves,
    outcomes: tuple[_MoveOutcome, _MoveOutcome],
) -> None:
    warehouse_a, warehouse_b = seeded.warehouse_ids
    device_a, device_b = seeded.device_ids
    rental_a, rental_b = seeded.rental_ids

    assert tuple(outcome.state for outcome in outcomes) == (
        "committed",
        "committed",
    )
    assert tuple(outcome.error_type for outcome in outcomes) == (None, None)
    assert {
        (
            outcome.device_id,
            outcome.from_warehouse_id,
            outcome.to_warehouse_id,
            outcome.affected_rental_ids,
            outcome.fulfillment_states,
        )
        for outcome in outcomes
    } == {
        (device_a, warehouse_a, warehouse_b, (rental_a,), ("fulfilled",)),
        (device_b, warehouse_b, warehouse_a, (rental_b,), ("fulfilled",)),
    }

    with session_factory() as session:
        device_warehouses = set(
            session.execute(
                select(Device.id, Device.warehouse_id)
                .where(Device.id.in_(seeded.device_ids))
                .order_by(Device.id.asc())
            ).all()
        )
        assert device_warehouses == {
            (device_a, warehouse_b),
            (device_b, warehouse_a),
        }

        movements = set(
            session.execute(
                select(
                    DeviceWarehouseMovement.device_id,
                    DeviceWarehouseMovement.from_warehouse_id,
                    DeviceWarehouseMovement.to_warehouse_id,
                    DeviceWarehouseMovement.source,
                    DeviceWarehouseMovement.actor_user_id,
                    DeviceWarehouseMovement.note,
                ).where(
                    DeviceWarehouseMovement.device_id.in_(seeded.device_ids)
                )
            ).all()
        )
        assert movements == {
            (
                device_a,
                warehouse_a,
                warehouse_b,
                "manual_change",
                "mysql-opposite-move-a",
                "opposite warehouse contention proof",
            ),
            (
                device_b,
                warehouse_b,
                warehouse_a,
                "manual_change",
                "mysql-opposite-move-b",
                "opposite warehouse contention proof",
            ),
        }

        requests = set(
            session.execute(
                select(
                    RentalAccessoryRequest.rental_id,
                    RentalAccessoryRequest.accessory_type_id,
                    RentalAccessoryRequest.name_snapshot,
                ).where(
                    RentalAccessoryRequest.rental_id.in_(seeded.rental_ids)
                )
            ).all()
        )
        assert requests == {
            (rental_a, seeded.accessory_type_id, "并发调仓三脚架"),
            (rental_b, seeded.accessory_type_id, "并发调仓三脚架"),
        }

        # Join facts are deliberately projected without a logical unit ID.
        links = set(
            session.execute(
                select(
                    RentalAccessoryUnitLink.rental_id,
                    RentalAccessoryUnitLink.accessory_type_id,
                    AccessoryUnit.warehouse_id,
                    AccessoryUnit.condition_status,
                    AccessoryUnit.current_holder_rental_id,
                    RentalAccessoryUnitLink.reservation_start_at,
                    RentalAccessoryUnitLink.reservation_end_at,
                    RentalAccessoryUnitLink.source_relay_case_id,
                )
                .join(
                    AccessoryUnit,
                    AccessoryUnit.id
                    == RentalAccessoryUnitLink.accessory_unit_id,
                )
                .where(
                    RentalAccessoryUnitLink.rental_id.in_(seeded.rental_ids)
                )
            ).all()
        )
        assert links == {
            (
                rental_a,
                seeded.accessory_type_id,
                warehouse_b,
                "active",
                None,
                seeded.reservation_window[0],
                seeded.reservation_window[1],
                None,
            ),
            (
                rental_b,
                seeded.accessory_type_id,
                warehouse_a,
                "active",
                None,
                seeded.reservation_window[0],
                seeded.reservation_window[1],
                None,
            ),
        }

        move_events = Counter(
            session.execute(
                select(
                    AccessoryUnitEvent.rental_id,
                    AccessoryUnitEvent.event_type,
                    AccessoryUnitEvent.from_warehouse_id,
                    AccessoryUnitEvent.to_warehouse_id,
                    AccessoryUnitEvent.actor_id,
                ).where(
                    AccessoryUnitEvent.rental_id.in_(seeded.rental_ids),
                    AccessoryUnitEvent.reason
                    == "device_warehouse_reassignment",
                )
            ).all()
        )
        assert move_events == Counter(
            {
                (
                    rental_a,
                    "unlinked",
                    warehouse_a,
                    None,
                    "mysql-opposite-move-a",
                ): 1,
                (
                    rental_a,
                    "linked",
                    None,
                    warehouse_b,
                    "mysql-opposite-move-a",
                ): 1,
                (
                    rental_b,
                    "unlinked",
                    warehouse_b,
                    None,
                    "mysql-opposite-move-b",
                ): 1,
                (
                    rental_b,
                    "linked",
                    None,
                    warehouse_a,
                    "mysql-opposite-move-b",
                ): 1,
            }
        )

        customer_start, customer_end, planned_ship, planned_return = (
            seeded.rental_dates
        )
        rental_facts = set(
            session.execute(
                select(
                    Rental.id,
                    Rental.start_date,
                    Rental.end_date,
                    Rental.logistics_days,
                    Rental.planned_ship_out_date,
                    Rental.planned_return_date,
                    Rental.status,
                ).where(Rental.id.in_(seeded.rental_ids))
            ).all()
        )
        assert rental_facts == {
            (
                rental_a,
                customer_start,
                customer_end,
                1,
                planned_ship,
                planned_return,
                "not_shipped",
            ),
            (
                rental_b,
                customer_start,
                customer_end,
                1,
                planned_ship,
                planned_return,
                "not_shipped",
            ),
        }

        unit_counts_by_warehouse = dict(
            session.execute(
                select(AccessoryUnit.warehouse_id, func.count())
                .where(
                    AccessoryUnit.accessory_type_id
                    == seeded.accessory_type_id
                )
                .group_by(AccessoryUnit.warehouse_id)
            ).all()
        )
        assert unit_counts_by_warehouse == {warehouse_a: 2, warehouse_b: 2}


def test_opposite_moves_finish_without_deadlock_and_commit_consistent_facts(
    mysql_application,
):
    session_factory = _factory()
    seeded = _seed_opposite_moves(session_factory)
    invocations = _preview_invocations(seeded)

    outcomes, elapsed = _run_opposite_moves(mysql_application, invocations)

    assert elapsed < _WORKER_TIMEOUT_SECONDS
    _assert_committed_facts(session_factory, seeded, outcomes)
