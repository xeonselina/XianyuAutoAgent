from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
import sqlalchemy as sa
from sqlalchemy import event

from inventory_control.backups.ack_persistence import (
    BackupAckPersistenceIntegrityError,
    BackupAckPersistenceTransactionError,
    BackupAcknowledgementPersistenceService,
)
from inventory_control.backups.acknowledgements import (
    AcknowledgementKind,
    AcknowledgementSafeResult,
    BackupAcknowledgementConflict,
    BackupAcknowledgementError,
    FreshnessState,
    acknowledgement_request_digest,
)
from inventory_control.backups.domain import (
    BackupLeaseStatus,
    BackupManifest,
    BackupObservation,
    BackupStage,
    DatabaseKind,
    DatabaseSnapshot,
    RecoveryMarkerSnapshot,
)
from inventory_control.backups.persistence import (
    BackupPersistenceService,
    FLEET_FULL_BACKUP_LEASE_KEY,
)
from inventory_control.database import ControlDatabase
from inventory_control.models import ControlBase
from inventory_control.models.backups import (
    BackupArtifactAcknowledgementRecord,
    PlatformBackupLease,
)


UTC = timezone.utc
BASE = datetime(2026, 8, 22, 8, 0, 0, 123456, tzinfo=UTC)
ALL_STAGES = frozenset(BackupStage)


def _id(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"inventory-manager-backup-ack-db/{label}")


def _digest(label: str) -> bytes:
    return hashlib.sha256(label.encode("ascii")).digest()


@pytest.fixture
def control_database(mysql_control_database):
    with mysql_control_database.transaction() as session:
        session.add(
            PlatformBackupLease(
                lease_key=FLEET_FULL_BACKUP_LEASE_KEY,
                status=BackupLeaseStatus.AVAILABLE.value,
                generation=0,
                fencing_token=0,
                observed_at=BASE - timedelta(days=1),
            )
        )
    return mysql_control_database


def _backup_service(session, now: datetime) -> BackupPersistenceService:
    return BackupPersistenceService(
        session=session,
        database_clock=lambda _session: now,
    )


def _ack_service(
    session,
    now: datetime,
) -> BackupAcknowledgementPersistenceService:
    return BackupAcknowledgementPersistenceService(
        session=session,
        database_clock=lambda _session: now,
    )


def _complete_artifact(
    control_database,
    label: str,
    *,
    snapshot_at: datetime,
):
    acquisition_id = _id(f"acquisition/{label}")
    attempt_id = _id(f"attempt/{label}")
    artifact_id = _id(f"artifact/{label}")
    published_name = f"backup-{artifact_id}.sql.gz"
    databases = (
        DatabaseSnapshot(
            database_id=_id("control"),
            kind=DatabaseKind.CONTROL,
            schema_generation=23,
            schema_sha256=_digest("control-schema"),
            required_root_key_versions=(1,),
        ),
        DatabaseSnapshot(
            database_id=_id("tenant"),
            kind=DatabaseKind.TENANT,
            schema_generation=12,
            schema_sha256=_digest("tenant-schema"),
            required_root_key_versions=(1,),
        ),
    )
    marker = RecoveryMarkerSnapshot(
        installation_id=_id("installation"),
        recovery_run_id=_id("recovery-run"),
        marker_generation=2,
        marker_sha256=_digest("marker"),
    )
    manifest = BackupManifest(
        artifact_id=artifact_id,
        attempt_id=attempt_id,
        published_name=published_name,
        snapshot_at_utc=snapshot_at,
        completed_at_utc=snapshot_at + timedelta(minutes=1),
        artifact_sha256=_digest(f"artifact-content/{label}"),
        size_bytes=4096,
        databases=databases,
        root_key_versions=(1,),
        recovery_marker=marker,
    )
    observation = BackupObservation(
        artifact_id=artifact_id,
        attempt_id=attempt_id,
        partial_name=f"{published_name}.partial",
        published_name=published_name,
        successful_stages=ALL_STAGES,
        atomic_publish_succeeded=True,
        observed_artifact_sha256=manifest.artifact_sha256,
        observed_manifest_sha256=manifest.manifest_sha256,
        observed_size_bytes=manifest.size_bytes,
        observed_databases=databases,
        observed_root_key_versions=(1,),
        observed_recovery_marker=marker,
    )
    with control_database.transaction() as session:
        lease = _backup_service(
            session, snapshot_at - timedelta(minutes=2)
        ).acquire_lease(
            acquisition_id=acquisition_id,
            holder_id=f"backup-worker-{label}",
            lease_duration=timedelta(minutes=30),
        )
    with control_database.transaction() as session:
        _backup_service(
            session, snapshot_at - timedelta(minutes=1)
        ).begin_attempt(
            attempt_id=attempt_id,
            partial_name=f"{published_name}.partial",
            acquisition_id=acquisition_id,
            lease_generation=lease.generation,
            fencing_token=lease.fencing_token,
        )
    with control_database.transaction() as session:
        return _backup_service(
            session, snapshot_at + timedelta(minutes=2)
        ).complete_attempt(
            manifest=manifest,
            observation=observation,
        ).artifact


def _ack_arguments(
    artifact,
    *,
    kind: AcknowledgementKind,
    generation: int,
    key: str,
    reported_at: datetime,
):
    safe_result = (
        AcknowledgementSafeResult.VERIFIED
        if kind is AcknowledgementKind.BACKUP_STATUS
        else AcknowledgementSafeResult.SYNCED
    )
    return {
        "artifact_id": artifact.artifact_id,
        "manifest_sha256": artifact.manifest_sha256,
        "artifact_sha256": artifact.artifact_sha256,
        "source_generation": generation,
        "idempotency_key": key,
        "request_digest": acknowledgement_request_digest(
            kind=kind,
            artifact_id=artifact.artifact_id,
            manifest_sha256=artifact.manifest_sha256,
            artifact_sha256=artifact.artifact_sha256,
            source_generation=generation,
            idempotency_key=key,
            safe_result=safe_result,
            reported_at_utc=reported_at,
        ),
        "reported_at_utc": reported_at,
    }


def test_sync_ack_needs_completed_artifact_but_not_backup_ack(control_database):
    artifact = _complete_artifact(
        control_database,
        "sync-first",
        snapshot_at=BASE,
    )
    arguments = _ack_arguments(
        artifact,
        kind=AcknowledgementKind.SYNC_STATUS,
        generation=1,
        key="sync-status-sync-first",
        reported_at=BASE + timedelta(minutes=4),
    )
    with control_database.transaction() as session:
        result = _ack_service(
            session, BASE + timedelta(minutes=5)
        ).record_sync_status_ack(**arguments)
        rows = tuple(
            session.scalars(sa.select(BackupArtifactAcknowledgementRecord))
        )

    assert result.idempotent_replay is False
    assert result.acknowledgement.kind is AcknowledgementKind.SYNC_STATUS
    assert len(rows) == 1
    assert rows[0].ack_kind == AcknowledgementKind.SYNC_STATUS.value
    assert rows[0].safe_result == AcknowledgementSafeResult.SYNCED.value


def test_missing_or_mismatched_completed_artifact_is_rejected(control_database):
    missing_id = _id("artifact/missing")
    reported_at = BASE + timedelta(minutes=1)
    request_digest = acknowledgement_request_digest(
        kind=AcknowledgementKind.SYNC_STATUS,
        artifact_id=missing_id,
        manifest_sha256=_digest("missing-manifest"),
        artifact_sha256=_digest("missing-artifact"),
        source_generation=1,
        idempotency_key="sync-status-missing",
        safe_result=AcknowledgementSafeResult.SYNCED,
        reported_at_utc=reported_at,
    )
    with control_database.transaction() as session:
        with pytest.raises(BackupAckPersistenceIntegrityError) as caught:
            _ack_service(session, BASE + timedelta(minutes=2)).record_sync_status_ack(
                artifact_id=missing_id,
                manifest_sha256=_digest("missing-manifest"),
                artifact_sha256=_digest("missing-artifact"),
                source_generation=1,
                idempotency_key="sync-status-missing",
                request_digest=request_digest,
                reported_at_utc=reported_at,
            )
    assert caught.value.code == "ACK_COMPLETED_ARTIFACT_NOT_FOUND"

    artifact = _complete_artifact(
        control_database,
        "mismatch",
        snapshot_at=BASE + timedelta(hours=1),
    )
    arguments = _ack_arguments(
        artifact,
        kind=AcknowledgementKind.BACKUP_STATUS,
        generation=2,
        key="backup-status-mismatch",
        reported_at=BASE + timedelta(hours=1, minutes=4),
    )
    arguments["artifact_sha256"] = _digest("wrong-artifact")
    arguments["request_digest"] = acknowledgement_request_digest(
        kind=AcknowledgementKind.BACKUP_STATUS,
        artifact_id=artifact.artifact_id,
        manifest_sha256=artifact.manifest_sha256,
        artifact_sha256=arguments["artifact_sha256"],
        source_generation=arguments["source_generation"],
        idempotency_key=arguments["idempotency_key"],
        safe_result=AcknowledgementSafeResult.VERIFIED,
        reported_at_utc=arguments["reported_at_utc"],
    )
    with control_database.transaction() as session:
        with pytest.raises(BackupAcknowledgementError) as caught:
            _ack_service(
                session, BASE + timedelta(hours=1, minutes=5)
            ).record_backup_status_ack(**arguments)
    assert getattr(caught.value, "code", None) == "ACK_COMPLETED_ARTIFACT_MISMATCH"


def test_exact_replay_keeps_first_receive_time_and_changed_request_conflicts(
    control_database,
):
    artifact = _complete_artifact(
        control_database,
        "replay",
        snapshot_at=BASE,
    )
    first_arguments = _ack_arguments(
        artifact,
        kind=AcknowledgementKind.BACKUP_STATUS,
        generation=9,
        key="backup-status-replay",
        reported_at=BASE + timedelta(minutes=4),
    )
    with control_database.transaction() as session:
        first = _ack_service(
            session, BASE + timedelta(minutes=5, microseconds=111111)
        ).record_backup_status_ack(**first_arguments)
    with control_database.transaction() as session:
        replay = _ack_service(
            session, BASE + timedelta(minutes=7, microseconds=222222)
        ).record_backup_status_ack(**first_arguments)
        assert (
            session.scalar(
                sa.select(sa.func.count()).select_from(
                    BackupArtifactAcknowledgementRecord
                )
            )
            == 1
        )
    assert replay.idempotent_replay is True
    assert replay.acknowledgement == first.acknowledgement
    assert (
        replay.acknowledgement.received_at_utc
        == BASE + timedelta(minutes=5, microseconds=111111)
    )

    changed = _ack_arguments(
        artifact,
        kind=AcknowledgementKind.BACKUP_STATUS,
        generation=10,
        key="backup-status-replay-changed",
        reported_at=BASE + timedelta(minutes=8),
    )
    with control_database.transaction() as session:
        with pytest.raises(BackupAcknowledgementConflict):
            _ack_service(
                session, BASE + timedelta(minutes=9)
            ).record_backup_status_ack(**changed)


def test_backup_and_sync_freshness_remain_independent(control_database):
    old = _complete_artifact(control_database, "old", snapshot_at=BASE)
    backup_arguments = _ack_arguments(
        old,
        kind=AcknowledgementKind.BACKUP_STATUS,
        generation=1,
        key="backup-status-old",
        reported_at=BASE + timedelta(hours=3),
    )
    with control_database.transaction() as session:
        _ack_service(
            session, BASE + timedelta(hours=3, minutes=1)
        ).record_backup_status_ack(**backup_arguments)

    with control_database.transaction() as session:
        snapshot = _ack_service(
            session, BASE + timedelta(hours=3, minutes=2)
        ).evaluate_freshness(
            backup_maximum_age=timedelta(minutes=90),
            sync_maximum_age=timedelta(hours=6),
        )
    assert snapshot.latest_verified_backup.state is FreshnessState.STALE
    assert snapshot.latest_cloud_sync.state is FreshnessState.MISSING

    recent = _complete_artifact(
        control_database,
        "recent",
        snapshot_at=BASE + timedelta(hours=3),
    )
    sync_arguments = _ack_arguments(
        recent,
        kind=AcknowledgementKind.SYNC_STATUS,
        generation=2,
        key="sync-status-recent",
        reported_at=BASE + timedelta(hours=3, minutes=4),
    )
    with control_database.transaction() as session:
        _ack_service(
            session, BASE + timedelta(hours=3, minutes=5)
        ).record_sync_status_ack(**sync_arguments)
    with control_database.transaction() as session:
        snapshot = _ack_service(
            session, BASE + timedelta(hours=3, minutes=6)
        ).evaluate_freshness(
            backup_maximum_age=timedelta(minutes=90),
            sync_maximum_age=timedelta(minutes=30),
        )
    assert snapshot.latest_verified_backup.state is FreshnessState.STALE
    assert snapshot.latest_cloud_sync.state is FreshnessState.FRESH
    assert snapshot.latest_cloud_sync.latest_artifact_id == recent.artifact_id


def test_database_time_is_read_after_artifact_and_ack_locks(control_database):
    artifact = _complete_artifact(
        control_database,
        "lock-clock",
        snapshot_at=BASE,
    )
    arguments = _ack_arguments(
        artifact,
        kind=AcknowledgementKind.BACKUP_STATUS,
        generation=1,
        key="backup-status-lock-clock",
        reported_at=BASE + timedelta(minutes=4),
    )
    sequence: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        lowered = statement.lower()
        if lowered.lstrip().startswith("select"):
            if "completed_backup_artifacts" in lowered:
                sequence.append("artifact")
            elif "backup_artifact_acknowledgements" in lowered:
                sequence.append("ack")

    def database_clock(_session):
        sequence.append("clock")
        return BASE + timedelta(minutes=5)

    event.listen(control_database.engine, "before_cursor_execute", capture)
    try:
        with control_database.transaction() as session:
            BackupAcknowledgementPersistenceService(
                session=session,
                database_clock=database_clock,
            ).record_backup_status_ack(**arguments)
    finally:
        event.remove(control_database.engine, "before_cursor_execute", capture)

    assert sequence[:3] == ["artifact", "ack", "clock"]


def test_service_requires_clean_explicit_caller_transaction(control_database):
    artifact = _complete_artifact(
        control_database,
        "transaction",
        snapshot_at=BASE,
    )
    arguments = _ack_arguments(
        artifact,
        kind=AcknowledgementKind.BACKUP_STATUS,
        generation=1,
        key="backup-status-transaction",
        reported_at=BASE + timedelta(minutes=4),
    )
    session = control_database.new_session()
    try:
        with pytest.raises(BackupAckPersistenceTransactionError):
            _ack_service(
                session, BASE + timedelta(minutes=5)
            ).record_backup_status_ack(**arguments)
    finally:
        session.close()

    with control_database.transaction() as session:
        session.add(
            BackupArtifactAcknowledgementRecord(
                artifact_id=str(artifact.artifact_id),
                ack_kind=AcknowledgementKind.BACKUP_STATUS.value,
                manifest_sha256=artifact.manifest_sha256,
                artifact_sha256=artifact.artifact_sha256,
                source_generation=1,
                idempotency_key="dirty-session",
                request_digest=_digest("not-a-valid-request-digest"),
                safe_result=AcknowledgementSafeResult.VERIFIED.value,
                reported_at=BASE,
                received_at=BASE,
                row_version=1,
            )
        )
        with pytest.raises(BackupAckPersistenceTransactionError):
            _ack_service(
                session, BASE + timedelta(minutes=5)
            ).record_backup_status_ack(**arguments)
