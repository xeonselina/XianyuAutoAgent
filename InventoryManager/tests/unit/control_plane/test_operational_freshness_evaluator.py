from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from inventory_control import ControlBase
from inventory_control.models.operations import PlatformOperationalSignal
from inventory_control.operations import (
    OperationalEffectiveStatus,
    OperationalEnvironment,
    OperationalFreshnessEvaluator,
    OperationalPolicyRegistry,
    OperationalSignalKey,
    OperationalSignalPolicy,
    OperationalSignalService,
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


def _signals(*, freshness=timedelta(seconds=30)):
    return OperationalSignalService(
        environment=OperationalEnvironment.TEST,
        policies=OperationalPolicyRegistry(
            OperationalSignalPolicy(
                signal_key=key,
                version=1,
                failure_threshold=1,
                recovery_threshold=1,
                freshness_window=freshness,
                repeat_interval=timedelta(minutes=5),
            )
            for key in OperationalSignalKey
        ),
    )


def test_stale_heartbeats_advance_independently_and_emit_lifecycle(database):
    signals = _signals()
    with database.transaction() as session:
        signals.record_worker_heartbeat(session, observed_at=NOW)
        signals.record_evaluator_heartbeat(session, observed_at=NOW)

    result = OperationalFreshnessEvaluator(
        database=database,
        signals=signals,
        signal_keys=(
            OperationalSignalKey.WORKER_HEARTBEAT,
            OperationalSignalKey.EVALUATOR_HEARTBEAT,
        ),
        database_clock=lambda _session: NOW + timedelta(seconds=30),
    ).run_once()

    assert result.configured_signals == 2
    assert result.evaluated_signals == 2
    assert result.missing_signals == ()
    assert result.unknown_signals == 2
    assert result.lifecycle_events == 2
    with database.new_session() as session:
        rows = [
            session.get(PlatformOperationalSignal, key.value)
            for key in (
                OperationalSignalKey.WORKER_HEARTBEAT,
                OperationalSignalKey.EVALUATOR_HEARTBEAT,
            )
        ]
        assert {row.effective_status for row in rows} == {
            OperationalEffectiveStatus.UNKNOWN.value
        }
        assert all(row.result_class == "stale" for row in rows)


def test_missing_signal_is_reported_without_blocking_initialized_signal(database):
    signals = _signals()
    with database.transaction() as session:
        update = signals.record_worker_heartbeat(session, observed_at=NOW)
        assert update.lifecycle_event is None

    result = OperationalFreshnessEvaluator(
        database=database,
        signals=signals,
        signal_keys=(
            OperationalSignalKey.WORKER_HEARTBEAT,
            OperationalSignalKey.BACKUP_VERIFIED_FRESHNESS,
        ),
        database_clock=lambda _session: NOW + timedelta(seconds=1),
    ).run_once()

    assert result.evaluated_signals == 1
    assert result.healthy_signals == 1
    assert result.missing_signals == (
        OperationalSignalKey.BACKUP_VERIFIED_FRESHNESS,
    )


def test_freshness_replay_at_same_database_time_is_idempotent(database):
    signals = _signals()
    with database.transaction() as session:
        signals.record_worker_heartbeat(session, observed_at=NOW)
    evaluator = OperationalFreshnessEvaluator(
        database=database,
        signals=signals,
        signal_keys=(OperationalSignalKey.WORKER_HEARTBEAT,),
        database_clock=lambda _session: NOW + timedelta(seconds=30),
    )

    first = evaluator.run_once()
    second = evaluator.run_once()

    assert first.lifecycle_events == 1
    assert second.lifecycle_events == 0
    assert second.unknown_signals == 1


@pytest.mark.parametrize(
    "keys",
    [
        (),
        (OperationalSignalKey.WORKER_HEARTBEAT,) * 2,
        (OperationalSignalKey.NOTIFICATION_DELIVERY,),
        ("worker.heartbeat",),
    ],
)
def test_configuration_rejects_missing_duplicate_latch_or_untyped_keys(
    database,
    keys,
):
    with pytest.raises(ValueError):
        OperationalFreshnessEvaluator(
            database=database,
            signals=_signals(),
            signal_keys=keys,
        )
