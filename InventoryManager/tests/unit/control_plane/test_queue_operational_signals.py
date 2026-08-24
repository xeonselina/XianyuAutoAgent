from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from inventory_control import ControlBase, Tenant
from inventory_control.jobs import ControlJobService
from inventory_control.models.jobs import BackgroundJob
from inventory_control.models.operations import PlatformOperationalSignal
from inventory_control.operations import (
    OperationalEnvironment,
    OperationalInputError,
    OperationalObservationConflictError,
    OperationalObservationStatus,
    OperationalPolicyRegistry,
    OperationalSignalKey,
    OperationalSignalPolicy,
    OperationalSignalService,
    OperationalResultClass,
    QueueOperationalPolicy,
    QueueOperationalSignalAdapter,
)
from tests.support.test_database import (
    clear_guarded_mysql_test_rows,
    guarded_mysql_control_database,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def database_schema():
    with guarded_mysql_control_database(ControlBase.metadata) as database:
        yield database


@pytest.fixture
def database(database_schema):
    clear_guarded_mysql_test_rows(database_schema.engine, ControlBase.metadata)
    return database_schema


def _signals():
    return OperationalSignalService(
        environment=OperationalEnvironment.TEST,
        policies=OperationalPolicyRegistry(
            OperationalSignalPolicy(
                signal_key=key,
                version=1,
                failure_threshold=1,
                recovery_threshold=1,
                freshness_window=timedelta(minutes=5),
                repeat_interval=timedelta(minutes=10),
            )
            for key in OperationalSignalKey
        ),
    )


def _adapter(*, now=NOW):
    return QueueOperationalSignalAdapter(
        signals=_signals(),
        policy=QueueOperationalPolicy(
            oldest_wait_threshold=timedelta(minutes=5),
            terminal_failure_lookback=timedelta(hours=1),
            terminal_failure_threshold=2,
        ),
        database_clock=lambda _session: now,
    )


def _seed_job(database, *, status, available_at, updated_at=NOW):
    with database.transaction() as session:
        tenant = session.query(Tenant).first()
        if tenant is None:
            tenant = Tenant(status="active")
            session.add(tenant)
            session.flush()
        job = BackgroundJob(
            tenant_id=tenant.id,
            tenant_access_version=tenant.access_version,
            job_type="monitor-test",
            resource_key=f"resource-{status}-{available_at.timestamp()}",
            payload={},
            idempotency_key=f"key-{status}-{available_at.timestamp()}",
            requested_by_type="scheduler",
            status=status,
            available_at=available_at,
            updated_at=updated_at,
        )
        session.add(job)
        session.flush()
        return job.id


def test_empty_queue_records_two_independent_healthy_aggregates(database):
    with database.transaction() as session:
        snapshot = _adapter().record_current(session)

    assert snapshot.oldest_due_wait_seconds == 0
    assert snapshot.terminal_failures_in_window == 0
    assert snapshot.oldest_wait_update.signal.effective_status.value == "healthy"
    assert (
        snapshot.consecutive_failures_update.signal.effective_status.value
        == "healthy"
    )


def test_due_wait_and_terminal_failure_thresholds_use_database_time(database):
    _seed_job(
        database,
        status="pending",
        available_at=NOW - timedelta(minutes=7, seconds=3),
    )
    _seed_job(
        database,
        status="pending",
        available_at=NOW + timedelta(minutes=30),
    )
    _seed_job(database, status="dead_letter", available_at=NOW)
    _seed_job(database, status="needs_review", available_at=NOW)
    _seed_job(
        database,
        status="failed",
        available_at=NOW,
        updated_at=NOW - timedelta(hours=2),
    )

    with database.transaction() as session:
        snapshot = _adapter().record_current(session)

    assert snapshot.oldest_due_wait_seconds == 423
    assert snapshot.terminal_failures_in_window == 2
    assert snapshot.oldest_wait_update.signal.effective_status.value == "unhealthy"
    assert snapshot.oldest_wait_update.signal.result_class.value == (
        "threshold_exceeded"
    )
    assert (
        snapshot.consecutive_failures_update.signal.effective_status.value
        == "unhealthy"
    )
    assert snapshot.consecutive_failures_update.signal.result_class.value == (
        "persistent_failure"
    )


def test_second_signal_failure_rolls_back_both_current_rows(database):
    signals = _signals()
    adapter = QueueOperationalSignalAdapter(
        signals=signals,
        policy=QueueOperationalPolicy(
            oldest_wait_threshold=timedelta(minutes=5),
            terminal_failure_lookback=timedelta(hours=1),
            terminal_failure_threshold=2,
        ),
        database_clock=lambda _session: NOW,
    )
    with database.transaction() as session:
        signals.record_observation(
            session,
            signal_key=OperationalSignalKey.QUEUE_CONSECUTIVE_FAILURES,
            observed_status=OperationalObservationStatus.OK,
            result_class=OperationalResultClass.OK,
            observed_at=NOW + timedelta(seconds=1),
        )

    with pytest.raises(OperationalObservationConflictError):
        with database.transaction() as session:
            adapter.record_current(session)

    with database.new_session() as session:
        assert session.get(
            PlatformOperationalSignal,
            OperationalSignalKey.QUEUE_OLDEST_WAIT.value,
        ) is None


@pytest.mark.parametrize(
    "policy",
    [
        QueueOperationalPolicy,
        lambda: QueueOperationalPolicy(
            oldest_wait_threshold=timedelta(0),
            terminal_failure_lookback=timedelta(hours=1),
            terminal_failure_threshold=1,
        ),
        lambda: QueueOperationalPolicy(
            oldest_wait_threshold=timedelta(minutes=1),
            terminal_failure_lookback=timedelta(hours=1),
            terminal_failure_threshold=0,
        ),
    ],
)
def test_queue_policy_has_no_implicit_or_unbounded_thresholds(policy):
    with pytest.raises((TypeError, OperationalInputError)):
        policy()
