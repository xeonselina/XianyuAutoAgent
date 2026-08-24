from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
import sqlalchemy as sa

from inventory_control.backups.acknowledgements import (
    AcknowledgementKind,
    AcknowledgementSafeResult,
    AcknowledgementSubmission,
    BackupFreshnessSnapshot,
    CompletedArtifactBinding,
    accept_acknowledgement,
    acknowledgement_request_digest,
    evaluate_acknowledgement_freshness,
)
from inventory_control.models.operations import (
    PlatformAlertLifecycleEvent,
    PlatformOperationalSignal,
)
from inventory_control.operations.backup_signals import (
    BackupFreshnessSignalAdapter,
)
from inventory_control.operations.service import (
    OperationalEffectiveStatus,
    OperationalEnvironment,
    OperationalObservationConflictError,
    OperationalObservationStatus,
    OperationalPolicyRegistry,
    OperationalResultClass,
    OperationalSignalKey,
    OperationalSignalPolicy,
    OperationalSignalService,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 22, 12, 0, 0, 654321, tzinfo=UTC)


def _id(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"inventory-manager-backup-signals/{label}")


def _digest(label: str) -> bytes:
    return hashlib.sha256(label.encode("ascii")).digest()


def _policies() -> OperationalPolicyRegistry:
    return OperationalPolicyRegistry(
        OperationalSignalPolicy(
            signal_key=key,
            version=1,
            failure_threshold=1,
            recovery_threshold=1,
            freshness_window=timedelta(minutes=10),
            repeat_interval=timedelta(minutes=5),
        )
        for key in OperationalSignalKey
    )


def _adapter() -> BackupFreshnessSignalAdapter:
    return BackupFreshnessSignalAdapter(
        signals=OperationalSignalService(
            environment=OperationalEnvironment.TEST,
            policies=_policies(),
        )
    )


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


def _accepted_ack(
    *,
    kind: AcknowledgementKind,
    restore_point_age: timedelta,
):
    label = f"{kind.value}/{int(restore_point_age.total_seconds())}"
    completed_at = NOW - restore_point_age
    artifact = CompletedArtifactBinding(
        artifact_id=_id(label),
        manifest_sha256=_digest(f"manifest/{label}"),
        artifact_sha256=_digest(f"artifact/{label}"),
        completed_at_utc=completed_at,
    )
    safe_result = (
        AcknowledgementSafeResult.VERIFIED
        if kind is AcknowledgementKind.BACKUP_STATUS
        else AcknowledgementSafeResult.SYNCED
    )
    reported_at = completed_at + timedelta(seconds=10)
    key = f"ack-{kind.name.lower()}-{int(restore_point_age.total_seconds())}"
    digest = acknowledgement_request_digest(
        kind=kind,
        artifact_id=artifact.artifact_id,
        manifest_sha256=artifact.manifest_sha256,
        artifact_sha256=artifact.artifact_sha256,
        source_generation=1,
        idempotency_key=key,
        safe_result=safe_result,
        reported_at_utc=reported_at,
    )
    submission = AcknowledgementSubmission(
        kind=kind,
        artifact_id=artifact.artifact_id,
        manifest_sha256=artifact.manifest_sha256,
        artifact_sha256=artifact.artifact_sha256,
        source_generation=1,
        idempotency_key=key,
        request_digest=digest,
        safe_result=safe_result,
        reported_at_utc=reported_at,
    )
    return accept_acknowledgement(
        artifact=artifact,
        submission=submission,
        existing_acknowledgements=(),
        database_now_utc=reported_at + timedelta(seconds=1),
    ).acknowledgement


def _freshness(
    *,
    backup_age_minutes: int | None,
    sync_age_minutes: int | None,
) -> BackupFreshnessSnapshot:
    acknowledgements = []
    if backup_age_minutes is not None:
        acknowledgements.append(
            _accepted_ack(
                kind=AcknowledgementKind.BACKUP_STATUS,
                restore_point_age=timedelta(minutes=backup_age_minutes),
            )
        )
    if sync_age_minutes is not None:
        acknowledgements.append(
            _accepted_ack(
                kind=AcknowledgementKind.SYNC_STATUS,
                restore_point_age=timedelta(minutes=sync_age_minutes),
            )
        )
    return evaluate_acknowledgement_freshness(
        acknowledgements,
        database_now_utc=NOW,
        backup_maximum_age=timedelta(minutes=90),
        sync_maximum_age=timedelta(minutes=90),
    )


@pytest.mark.parametrize(
    (
        "backup_age",
        "sync_age",
        "backup_status",
        "backup_result",
        "sync_status",
        "sync_result",
    ),
    (
        (
            5,
            5,
            OperationalObservationStatus.OK,
            OperationalResultClass.VERIFIED,
            OperationalObservationStatus.OK,
            OperationalResultClass.VERIFIED,
        ),
        (
            5,
            120,
            OperationalObservationStatus.OK,
            OperationalResultClass.VERIFIED,
            OperationalObservationStatus.FAILURE,
            OperationalResultClass.THRESHOLD_EXCEEDED,
        ),
        (
            120,
            5,
            OperationalObservationStatus.FAILURE,
            OperationalResultClass.THRESHOLD_EXCEEDED,
            OperationalObservationStatus.OK,
            OperationalResultClass.VERIFIED,
        ),
        (
            None,
            None,
            OperationalObservationStatus.FAILURE,
            OperationalResultClass.UNAVAILABLE,
            OperationalObservationStatus.FAILURE,
            OperationalResultClass.UNAVAILABLE,
        ),
    ),
)
def test_adapter_records_backup_and_cloud_freshness_independently(
    control_database,
    backup_age,
    sync_age,
    backup_status,
    backup_result,
    sync_status,
    sync_result,
):
    freshness = _freshness(
        backup_age_minutes=backup_age,
        sync_age_minutes=sync_age,
    )
    with control_database.transaction() as session:
        updates = _adapter().record_snapshot(session, freshness=freshness)

    backup = updates.backup_verified_freshness.signal
    sync = updates.cloud_sync_freshness.signal
    assert backup.signal_key is OperationalSignalKey.BACKUP_VERIFIED_FRESHNESS
    assert sync.signal_key is OperationalSignalKey.CLOUD_SYNC_FRESHNESS
    assert backup.severity == "p1"
    assert sync.severity == "p2"
    assert backup.observed_status is backup_status
    assert backup.observed_result_class is backup_result
    assert sync.observed_status is sync_status
    assert sync.observed_result_class is sync_result
    assert backup.observed_at == freshness.latest_verified_backup.evaluated_at_utc
    assert sync.observed_at == freshness.latest_cloud_sync.evaluated_at_utc
    assert backup.effective_status is (
        OperationalEffectiveStatus.HEALTHY
        if backup_status is OperationalObservationStatus.OK
        else OperationalEffectiveStatus.UNHEALTHY
    )
    assert sync.effective_status is (
        OperationalEffectiveStatus.HEALTHY
        if sync_status is OperationalObservationStatus.OK
        else OperationalEffectiveStatus.UNHEALTHY
    )


def test_exact_snapshot_replay_is_idempotent_for_both_fixed_signals(
    control_database,
):
    freshness = _freshness(backup_age_minutes=None, sync_age_minutes=None)
    adapter = _adapter()
    with control_database.transaction() as session:
        first = adapter.record_snapshot(session, freshness=freshness)
    assert first.backup_verified_freshness.lifecycle_event is not None
    assert first.cloud_sync_freshness.lifecycle_event is not None

    with control_database.transaction() as session:
        replay = adapter.record_snapshot(session, freshness=freshness)
        signal_count = session.scalar(
            sa.select(sa.func.count()).select_from(PlatformOperationalSignal)
        )
        event_count = session.scalar(
            sa.select(sa.func.count()).select_from(PlatformAlertLifecycleEvent)
        )
    assert replay.backup_verified_freshness.signal.idempotent_replay is True
    assert replay.cloud_sync_freshness.signal.idempotent_replay is True
    assert replay.backup_verified_freshness.lifecycle_event is None
    assert replay.cloud_sync_freshness.lifecycle_event is None
    assert signal_count == 2
    assert event_count == 2


def test_adapter_does_not_commit_and_outer_rollback_removes_both_signals(
    control_database,
):
    class RollbackProbe(RuntimeError):
        pass

    freshness = _freshness(backup_age_minutes=5, sync_age_minutes=120)
    session = control_database.new_session()
    try:
        with pytest.raises(RollbackProbe):
            with session.begin():
                _adapter().record_snapshot(session, freshness=freshness)
                raise RollbackProbe()
    finally:
        session.close()

    with control_database.new_session() as session:
        assert (
            session.scalar(
                sa.select(sa.func.count()).select_from(PlatformOperationalSignal)
            )
            == 0
        )
        assert (
            session.scalar(
                sa.select(sa.func.count()).select_from(PlatformAlertLifecycleEvent)
            )
            == 0
        )


def test_second_signal_conflict_rolls_back_first_signal_in_outer_transaction(
    control_database,
):
    adapter = _adapter()
    initial = _freshness(backup_age_minutes=None, sync_age_minutes=5)
    with control_database.transaction() as session:
        adapter.record_snapshot(session, freshness=initial)

    conflicting = _freshness(backup_age_minutes=5, sync_age_minutes=120)
    conflicting = BackupFreshnessSnapshot(
        latest_verified_backup=replace(
            conflicting.latest_verified_backup,
            evaluated_at_utc=NOW + timedelta(seconds=1),
        ),
        latest_cloud_sync=conflicting.latest_cloud_sync,
    )
    with pytest.raises(OperationalObservationConflictError):
        with control_database.transaction() as session:
            adapter.record_snapshot(session, freshness=conflicting)

    with control_database.new_session() as session:
        backup = session.get(
            PlatformOperationalSignal,
            OperationalSignalKey.BACKUP_VERIFIED_FRESHNESS.value,
        )
        sync = session.get(
            PlatformOperationalSignal,
            OperationalSignalKey.CLOUD_SYNC_FRESHNESS.value,
        )
        assert backup is not None
        assert backup.observed_status == "failure"
        assert backup.observed_result_class == "unavailable"
        assert sync.observed_status == "ok"
        assert sync.observed_result_class == "verified"
