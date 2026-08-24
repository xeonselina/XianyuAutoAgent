"""Opt-in real-MySQL contention proof for Gantt execution snapshots.

The normal suite only collects and skips this module.  It can run only after
all three explicit gates below are present, and the shared test-database guard
has accepted the exact ``inventory_management_test`` schema, account grants,
schema preflight, and advisory-locked metadata lifecycle.

No database URL or credential is defined here.  The test holds one underlying
Rental or Device row in a separate transaction, proves Gantt execution waits
at its locking read, then commits the concurrent change.  Execution must see
that new row state and reject the stale preview without applying its pinned
device assignment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import os
from threading import Event, Lock, Thread
from typing import Callable, Literal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app import create_app, db
from app.models.audit_log import AuditLog
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental
from app.services.gantt.reorder_service import (
    GanttReorderService,
    StalePreviewError,
)
from tests.support.test_database import (
    build_mysql_test_config,
    guarded_mysql_test_metadata,
)


_REAL_CONTENTION_ENABLED = (
    os.environ.get("RUN_REAL_MYSQL_CONTENTION_TESTS", "").lower() == "true"
    and os.environ.get("ALLOW_REAL_TEST_DATABASE", "").lower() == "true"
    and bool(os.environ.get("TEST_DATABASE_URL"))
)
pytestmark = pytest.mark.skipif(
    not _REAL_CONTENTION_ENABLED,
    reason=(
        "real MySQL Gantt contention requires "
        "RUN_REAL_MYSQL_CONTENTION_TESTS=true, "
        "ALLOW_REAL_TEST_DATABASE=true, and TEST_DATABASE_URL"
    ),
)

_LOCK_WAIT_TIMEOUT_SECONDS = 12
_WORKER_TIMEOUT_SECONDS = 30


@pytest.fixture(scope="module")
def mysql_application():
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
class _SeededReorder:
    rental_ids: tuple[int, int]
    device_ids: tuple[int, int]
    original_device_by_rental: dict[int, int]


@dataclass(frozen=True, slots=True)
class _ConcurrentOutcome:
    state: str
    error: BaseException | None = None


def _factory() -> Callable[[], Session]:
    return sessionmaker(bind=db.engine, expire_on_commit=False)


def _seed_reorder_case(session_factory) -> _SeededReorder:
    suffix = uuid4().hex[:12]
    base = date.today() + timedelta(days=20)

    with session_factory.begin() as session:
        model = DeviceModel(
            name=f"mysql-gantt-{suffix}",
            display_name="MySQL Gantt 并发测试",
            is_active=True,
        )
        session.add(model)
        session.flush()

        first_device = Device(
            name=f"mysql-gantt-a-{suffix}",
            serial_number=f"mysql-gantt-a-{suffix}",
            model=model.name,
            model_id=model.id,
            is_accessory=False,
            lifecycle_status="active",
        )
        second_device = Device(
            name=f"mysql-gantt-b-{suffix}",
            serial_number=f"mysql-gantt-b-{suffix}",
            model=model.name,
            model_id=model.id,
            is_accessory=False,
            lifecycle_status="active",
        )
        session.add_all((first_device, second_device))
        session.flush()

        # Touching windows on two same-model devices give the solver one
        # deterministic compaction opportunity and therefore a real pinned
        # assignment whose accidental commit would be observable.
        first_rental = Rental(
            device_id=first_device.id,
            start_date=base + timedelta(days=1),
            end_date=base + timedelta(days=2),
            logistics_days=0,
            planned_ship_out_date=base,
            planned_return_date=base + timedelta(days=3),
            ship_out_time=datetime.combine(base, time(19)),
            ship_in_time=datetime.combine(base + timedelta(days=3), time(12)),
            customer_name="MySQL Gantt 并发客户甲",
            customer_phone="13800138000",
            destination="并发测试地址甲",
            status="not_shipped",
        )
        second_rental = Rental(
            device_id=second_device.id,
            start_date=base + timedelta(days=4),
            end_date=base + timedelta(days=7),
            logistics_days=0,
            planned_ship_out_date=base + timedelta(days=3),
            planned_return_date=base + timedelta(days=8),
            ship_out_time=datetime.combine(base + timedelta(days=3), time(19)),
            ship_in_time=datetime.combine(base + timedelta(days=8), time(12)),
            customer_name="MySQL Gantt 并发客户乙",
            customer_phone="13800138001",
            destination="并发测试地址乙",
            status="not_shipped",
        )
        session.add_all((first_rental, second_rental))
        session.flush()

        rental_ids = (first_rental.id, second_rental.id)
        device_ids = (first_device.id, second_device.id)
        return _SeededReorder(
            rental_ids=rental_ids,
            device_ids=device_ids,
            original_device_by_rental={
                first_rental.id: first_device.id,
                second_rental.id: second_device.id,
            },
        )


def _preview_token(session_factory, seeded: _SeededReorder) -> str:
    with session_factory() as session:
        preview = GanttReorderService.preview([], tenant_session=session)

    changed_seeded_rentals = {
        change["rental_id"]
        for change in preview["changes"]
        if change["rental_id"] in seeded.rental_ids
    }
    assert changed_seeded_rentals, (
        "seed must produce a pinned Gantt device change before contention"
    )
    return preview["token"]


def _run_blocked_execute(
    *,
    application,
    session_factory,
    token: str,
    seeded: _SeededReorder,
    mutation_target: Literal["rental", "device"],
    monkeypatch,
) -> tuple[_ConcurrentOutcome, _ConcurrentOutcome, str]:
    row_locked = Event()
    release_mutation = Event()
    execute_reached_lock = Event()
    execute_finished = Event()
    outcomes_lock = Lock()
    outcomes: dict[str, _ConcurrentOutcome] = {}
    concurrent_value = f"committed-contention-{uuid4().hex[:12]}"

    locked_entity = Rental if mutation_target == "rental" else Device
    original_lock_query = GanttReorderService._query_with_optional_lock

    def signal_target_lock(query, lock):
        if lock and any(
            description.get("entity") is locked_entity
            for description in query.column_descriptions
        ):
            execute_reached_lock.set()
        return original_lock_query(query, lock)

    monkeypatch.setattr(
        GanttReorderService,
        "_query_with_optional_lock",
        staticmethod(signal_target_lock),
    )

    session_id_lock = Lock()
    concurrent_session_ids: dict[str, int] = {}

    def mutate() -> None:
        session: Session = session_factory()
        with session_id_lock:
            concurrent_session_ids["mutation"] = id(session)
        try:
            session.execute(
                text(
                    "SET SESSION innodb_lock_wait_timeout = "
                    f"{_LOCK_WAIT_TIMEOUT_SECONDS}"
                )
            )
            with session.begin_nested():
                if mutation_target == "rental":
                    row = session.execute(
                        select(Rental)
                        .where(Rental.id == seeded.rental_ids[0])
                        .with_for_update()
                    ).scalar_one()
                    row.destination = concurrent_value
                else:
                    row = session.execute(
                        select(Device)
                        .where(Device.id == seeded.device_ids[0])
                        .with_for_update()
                    ).scalar_one()
                    row.lifecycle_status = "sold"
                    row.lifecycle_reason = concurrent_value
                session.flush()
                row_locked.set()
                if not release_mutation.wait(_WORKER_TIMEOUT_SECONDS):
                    raise TimeoutError("mutation release was not signalled")
            session.commit()
            outcome = _ConcurrentOutcome("committed")
        except BaseException as exc:  # retained for main-thread assertions
            session.rollback()
            outcome = _ConcurrentOutcome("failed", exc)
        finally:
            session.close()
        with outcomes_lock:
            outcomes["mutation"] = outcome

    def execute() -> None:
        if not row_locked.wait(_WORKER_TIMEOUT_SECONDS):
            with outcomes_lock:
                outcomes["execute"] = _ConcurrentOutcome(
                    "failed",
                    TimeoutError("mutation row was not locked"),
                )
            execute_finished.set()
            return
        with application.app_context():
            session: Session = db.session()
            with session_id_lock:
                concurrent_session_ids["execute"] = id(session)
            try:
                session.execute(
                    text(
                        "SET SESSION innodb_lock_wait_timeout = "
                        f"{_LOCK_WAIT_TIMEOUT_SECONDS}"
                    )
                )
                GanttReorderService.execute(token)
                outcome = _ConcurrentOutcome("committed")
            except BaseException as exc:  # retained for main-thread assertions
                db.session.rollback()
                outcome = _ConcurrentOutcome("failed", exc)
            finally:
                db.session.remove()
        with outcomes_lock:
            outcomes["execute"] = outcome
        execute_finished.set()

    mutation_worker = Thread(
        target=mutate,
        name=f"gantt-{mutation_target}-mutation",
        daemon=True,
    )
    execute_worker = Thread(
        target=execute,
        name=f"gantt-{mutation_target}-execute",
        daemon=True,
    )

    mutation_worker.start()
    execute_worker_started = False
    try:
        assert row_locked.wait(_WORKER_TIMEOUT_SECONDS), (
            "concurrent mutation did not acquire its row lock"
        )
        execute_worker.start()
        execute_worker_started = True
        assert execute_reached_lock.wait(_WORKER_TIMEOUT_SECONDS), (
            "Gantt execute did not reach the target locking read"
        )
        assert not execute_finished.wait(0.25), (
            "Gantt execute did not wait for the concurrent row lock"
        )
    finally:
        release_mutation.set()
        mutation_worker.join(timeout=_WORKER_TIMEOUT_SECONDS)
        if execute_worker_started:
            execute_worker.join(timeout=_WORKER_TIMEOUT_SECONDS)

    assert not mutation_worker.is_alive(), "mutation worker exceeded timeout"
    assert not execute_worker.is_alive(), "execute worker exceeded timeout"
    assert set(concurrent_session_ids) == {"mutation", "execute"}
    assert len(set(concurrent_session_ids.values())) == 2
    assert set(outcomes) == {"mutation", "execute"}
    return outcomes["mutation"], outcomes["execute"], concurrent_value


def _assert_no_silent_assignment(
    session_factory,
    seeded: _SeededReorder,
    *,
    mutation_target: Literal["rental", "device"],
    concurrent_value: str,
) -> None:
    with session_factory() as session:
        actual_device_by_rental = dict(
            session.execute(
                select(Rental.id, Rental.device_id).where(
                    Rental.id.in_(seeded.rental_ids)
                )
            ).all()
        )
        audit_count = session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "gantt_schedule_reordered",
                AuditLog.rental_id.in_(seeded.rental_ids),
            )
        )
        assert actual_device_by_rental == seeded.original_device_by_rental
        assert int(audit_count) == 0

        if mutation_target == "rental":
            assert session.get(Rental, seeded.rental_ids[0]).destination == (
                concurrent_value
            )
        else:
            device = session.get(Device, seeded.device_ids[0])
            assert device.lifecycle_status == "sold"
            assert device.lifecycle_reason == concurrent_value


@pytest.mark.parametrize("mutation_target", ("rental", "device"))
def test_execute_waits_then_rejects_concurrent_snapshot_change(
    mysql_application,
    monkeypatch,
    mutation_target,
):
    session_factory = _factory()
    seeded = _seed_reorder_case(session_factory)
    token = _preview_token(session_factory, seeded)

    mutation, execution, concurrent_value = _run_blocked_execute(
        application=mysql_application,
        session_factory=session_factory,
        token=token,
        seeded=seeded,
        mutation_target=mutation_target,
        monkeypatch=monkeypatch,
    )

    assert mutation == _ConcurrentOutcome("committed")
    assert execution.state == "failed"
    assert isinstance(execution.error, StalePreviewError)
    assert "重新预览" in str(execution.error)
    _assert_no_silent_assignment(
        session_factory,
        seeded,
        mutation_target=mutation_target,
        concurrent_value=concurrent_value,
    )
