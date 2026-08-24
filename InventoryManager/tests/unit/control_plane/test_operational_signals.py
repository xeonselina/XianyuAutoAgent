from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from inventory_control.models import (
    PlatformAlertLifecycleEvent,
    PlatformOperationalSignal,
)
from inventory_control.operations import (
    AlertLifecycleKind,
    OperationalEffectiveStatus,
    OperationalEnvironment,
    OperationalInputError,
    OperationalObservationConflictError,
    OperationalObservationStatus,
    OperationalPolicyConflictError,
    OperationalPolicyError,
    OperationalPolicyRegistry,
    OperationalResultClass,
    OperationalSignalKey,
    OperationalSignalPolicy,
    OperationalSignalService,
    OperationalTransactionRequiredError,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _policies(
    *,
    version=1,
    failure_threshold=2,
    recovery_threshold=2,
    freshness_seconds=30,
    repeat_seconds=60,
):
    return OperationalPolicyRegistry(
        OperationalSignalPolicy(
            signal_key=key,
            version=version,
            failure_threshold=failure_threshold,
            recovery_threshold=recovery_threshold,
            freshness_window=timedelta(seconds=freshness_seconds),
            repeat_interval=timedelta(seconds=repeat_seconds),
        )
        for key in OperationalSignalKey
    )


def _service(**policy_overrides):
    return OperationalSignalService(
        environment=OperationalEnvironment.TEST,
        policies=_policies(**policy_overrides),
    )


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


def _failure(
    database,
    service,
    *,
    at,
    key=OperationalSignalKey.CONTROL_DB_CONNECTION_CAPACITY,
    result=OperationalResultClass.CAPACITY_HIGH,
    suppressed_until=None,
):
    with database.transaction() as session:
        return service.record_observation(
            session,
            signal_key=key,
            observed_status=OperationalObservationStatus.FAILURE,
            result_class=result,
            observed_at=at,
            notifications_suppressed_until=suppressed_until,
        )


def _success(
    database,
    service,
    *,
    at,
    key=OperationalSignalKey.CONTROL_DB_CONNECTION_CAPACITY,
):
    with database.transaction() as session:
        return service.record_observation(
            session,
            signal_key=key,
            observed_status=OperationalObservationStatus.OK,
            result_class=OperationalResultClass.OK,
            observed_at=at,
        )


def test_policy_registry_requires_every_fixed_signal_and_valid_values():
    policies = [
        OperationalSignalPolicy(
            signal_key=key,
            version=1,
            failure_threshold=1,
            recovery_threshold=1,
            freshness_window=timedelta(seconds=30),
            repeat_interval=timedelta(minutes=5),
        )
        for key in OperationalSignalKey
    ]
    with pytest.raises(OperationalPolicyError):
        OperationalPolicyRegistry(policies[:-1])
    with pytest.raises(OperationalPolicyError):
        OperationalSignalPolicy(
            signal_key=OperationalSignalKey.WORKER_HEARTBEAT,
            version=1,
            failure_threshold=0,
            recovery_threshold=1,
            freshness_window=timedelta(seconds=30),
            repeat_interval=timedelta(minutes=5),
        )
    with pytest.raises(OperationalPolicyError):
        OperationalSignalPolicy(
            signal_key=OperationalSignalKey.WORKER_HEARTBEAT,
            version=1,
            failure_threshold=1,
            recovery_threshold=1,
            freshness_window=timedelta(milliseconds=1),
            repeat_interval=timedelta(minutes=5),
        )


def test_requires_explicit_caller_owned_transaction(control_database):
    service = _service()
    with control_database.new_session() as session:
        with pytest.raises(OperationalTransactionRequiredError):
            service.record_worker_heartbeat(session, observed_at=NOW)


def test_worker_and_evaluator_heartbeats_are_independent_fixed_signals(
    control_database,
):
    service = _service()
    with control_database.transaction() as session:
        worker = service.record_worker_heartbeat(session, observed_at=NOW)
        evaluator = service.record_evaluator_heartbeat(
            session, observed_at=NOW + timedelta(seconds=10)
        )

    assert worker.signal.signal_key is OperationalSignalKey.WORKER_HEARTBEAT
    assert evaluator.signal.signal_key is OperationalSignalKey.EVALUATOR_HEARTBEAT
    assert worker.signal.source == "worker"
    assert evaluator.signal.source == "evaluator"
    assert worker.signal.effective_status is OperationalEffectiveStatus.HEALTHY
    assert evaluator.signal.effective_status is OperationalEffectiveStatus.HEALTHY

    with control_database.transaction() as session:
        stale_worker = service.evaluate_freshness(
            session,
            signal_key=OperationalSignalKey.WORKER_HEARTBEAT,
            evaluated_at=NOW + timedelta(seconds=30),
        )
    assert stale_worker.signal.effective_status is OperationalEffectiveStatus.UNKNOWN
    assert stale_worker.lifecycle_event.event_type is AlertLifecycleKind.TRIGGER

    with control_database.new_session() as session:
        evaluator_row = session.get(
            PlatformOperationalSignal,
            OperationalSignalKey.EVALUATOR_HEARTBEAT.value,
        )
        assert evaluator_row.effective_status == "healthy"


def test_consecutive_failure_trigger_repeat_and_recovery_are_hysteretic(
    control_database,
):
    service = _service(repeat_seconds=10)
    first = _failure(control_database, service, at=NOW)
    assert first.signal.effective_status is OperationalEffectiveStatus.DEGRADED
    assert first.lifecycle_event is None

    triggered = _failure(
        control_database,
        service,
        at=NOW + timedelta(seconds=1),
    )
    assert triggered.signal.effective_status is OperationalEffectiveStatus.UNHEALTHY
    assert triggered.lifecycle_event.event_type is AlertLifecycleKind.TRIGGER
    fingerprint = triggered.lifecycle_event.alert_fingerprint
    assert len(fingerprint) == 64

    with control_database.transaction() as session:
        repeated = service.evaluate_freshness(
            session,
            signal_key=OperationalSignalKey.CONTROL_DB_CONNECTION_CAPACITY,
            evaluated_at=NOW + timedelta(seconds=11),
        )
    assert repeated.lifecycle_event.event_type is AlertLifecycleKind.REPEAT
    assert repeated.lifecycle_event.alert_fingerprint == fingerprint

    recovering = _success(
        control_database,
        service,
        at=NOW + timedelta(seconds=12),
    )
    assert recovering.signal.effective_status is OperationalEffectiveStatus.UNHEALTHY
    assert recovering.lifecycle_event is None
    replayed_recovery_observation = _success(
        control_database,
        service,
        at=NOW + timedelta(seconds=12),
    )
    assert replayed_recovery_observation.signal.idempotent_replay is True
    assert replayed_recovery_observation.lifecycle_event is None

    recovered = _success(
        control_database,
        service,
        at=NOW + timedelta(seconds=13),
    )
    assert recovered.signal.effective_status is OperationalEffectiveStatus.HEALTHY
    assert recovered.signal.active_alert_fingerprint is None
    assert recovered.lifecycle_event.event_type is AlertLifecycleKind.RECOVERY
    assert recovered.lifecycle_event.alert_fingerprint == fingerprint

    _failure(control_database, service, at=NOW + timedelta(seconds=14))
    second_episode = _failure(
        control_database,
        service,
        at=NOW + timedelta(seconds=15),
    )
    assert second_episode.lifecycle_event.alert_fingerprint == fingerprint
    assert second_episode.lifecycle_event.alert_generation == 2

    with control_database.new_session() as session:
        events = session.scalars(
            sa.select(PlatformAlertLifecycleEvent).order_by(
                PlatformAlertLifecycleEvent.occurred_at
            )
        ).all()
        assert [event.event_type for event in events] == [
            "trigger",
            "repeat",
            "recovery",
            "trigger",
        ]
        assert len(
            {
                (
                    event.alert_fingerprint,
                    event.alert_generation,
                    event.lifecycle_sequence,
                )
                for event in events
            }
        ) == len(events)


def test_freshness_expiry_becomes_unknown_and_never_reuses_last_green(
    control_database,
):
    service = _service(freshness_seconds=20)
    with control_database.transaction() as session:
        service.record_worker_heartbeat(session, observed_at=NOW)
    with control_database.transaction() as session:
        update = service.evaluate_freshness(
            session,
            signal_key=OperationalSignalKey.WORKER_HEARTBEAT,
            evaluated_at=NOW + timedelta(seconds=20),
        )
    assert update.signal.effective_status is OperationalEffectiveStatus.UNKNOWN
    assert update.signal.result_class is OperationalResultClass.STALE
    assert update.lifecycle_event.event_type is AlertLifecycleKind.TRIGGER

    with control_database.new_session() as session:
        persisted = session.get(
            PlatformOperationalSignal,
            OperationalSignalKey.WORKER_HEARTBEAT.value,
        )
        assert persisted.observed_status == "ok"
        assert persisted.effective_status == "unknown"

    with control_database.transaction() as session:
        first_heartbeat = service.record_worker_heartbeat(
            session, observed_at=NOW + timedelta(seconds=21)
        )
    assert first_heartbeat.signal.effective_status is OperationalEffectiveStatus.UNKNOWN
    with control_database.transaction() as session:
        second_heartbeat = service.record_worker_heartbeat(
            session, observed_at=NOW + timedelta(seconds=22)
        )
    assert (
        second_heartbeat.signal.effective_status is OperationalEffectiveStatus.HEALTHY
    )
    assert second_heartbeat.lifecycle_event.event_type is AlertLifecycleKind.RECOVERY


def test_suppressed_alert_is_recorded_then_triggers_after_window(
    control_database,
):
    service = _service(failure_threshold=1, repeat_seconds=10)
    suppression_end = NOW + timedelta(seconds=40)
    suppressed = _failure(
        control_database,
        service,
        at=NOW,
        suppressed_until=suppression_end,
    )
    assert suppressed.lifecycle_event.event_type is AlertLifecycleKind.SUPPRESSED
    assert suppressed.lifecycle_event.suppressed_until == suppression_end
    fingerprint = suppressed.lifecycle_event.alert_fingerprint

    with control_database.transaction() as session:
        not_due = service.evaluate_freshness(
            session,
            signal_key=OperationalSignalKey.CONTROL_DB_CONNECTION_CAPACITY,
            evaluated_at=NOW + timedelta(seconds=20),
            notifications_suppressed_until=suppression_end,
        )
    assert not_due.lifecycle_event is None

    with control_database.transaction() as session:
        due = service.evaluate_freshness(
            session,
            signal_key=OperationalSignalKey.CONTROL_DB_CONNECTION_CAPACITY,
            evaluated_at=suppression_end,
        )
    assert due.lifecycle_event.event_type is AlertLifecycleKind.TRIGGER
    assert due.lifecycle_event.alert_fingerprint == fingerprint


def test_duplicate_observation_is_idempotent_and_conflicts_are_rejected(
    control_database,
):
    service = _service()
    with control_database.transaction() as session:
        service.record_worker_heartbeat(session, observed_at=NOW)
    with control_database.transaction() as session:
        replay = service.record_worker_heartbeat(session, observed_at=NOW)
        assert replay.signal.idempotent_replay is True
        assert replay.lifecycle_event is None
    with control_database.transaction() as session:
        with pytest.raises(OperationalObservationConflictError):
            service.record_observation(
                session,
                signal_key=OperationalSignalKey.WORKER_HEARTBEAT,
                observed_status=OperationalObservationStatus.FAILURE,
                result_class=OperationalResultClass.UNAVAILABLE,
                observed_at=NOW,
            )
    with control_database.transaction() as session:
        with pytest.raises(OperationalObservationConflictError):
            service.record_worker_heartbeat(
                session, observed_at=NOW - timedelta(seconds=1)
            )


def test_same_policy_version_cannot_silently_change_thresholds(control_database):
    service = _service(failure_threshold=2)
    with control_database.transaction() as session:
        service.record_worker_heartbeat(session, observed_at=NOW)
    conflicting = _service(failure_threshold=3)
    with control_database.transaction() as session:
        with pytest.raises(OperationalPolicyConflictError):
            conflicting.record_worker_heartbeat(
                session, observed_at=NOW + timedelta(seconds=1)
            )


def test_inputs_and_persistence_have_no_freeform_payload_surface(control_database):
    service = _service()
    with control_database.transaction() as session:
        with pytest.raises(OperationalInputError) as error:
            service.record_observation(
                session,
                signal_key="tenant-secret-signal",
                observed_status=OperationalObservationStatus.FAILURE,
                result_class=OperationalResultClass.PROVIDER_ERROR,
                observed_at=NOW,
            )
    assert "tenant-secret-signal" not in str(error.value)

    signal_columns = {
        column.name for column in PlatformOperationalSignal.__table__.columns
    }
    event_columns = {
        column.name for column in PlatformAlertLifecycleEvent.__table__.columns
    }
    forbidden = {
        "tenant_id",
        "user_id",
        "customer_id",
        "provider_request_id",
        "payload",
        "message",
        "details",
        "secret",
    }
    assert forbidden.isdisjoint(signal_columns)
    assert forbidden.isdisjoint(event_columns)
