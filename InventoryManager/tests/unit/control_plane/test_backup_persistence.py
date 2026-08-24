from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
import sqlalchemy as sa
from sqlalchemy import event

import inventory_control.backups.persistence as backup_persistence
from inventory_control import (
    BackupAttemptRecord,
    CompletedBackupArtifactRecord,
    ControlBase,
    ControlDatabase,
    PlatformBackupLease,
)
from inventory_control.backups.domain import (
    BackupDomainError,
    BackupLeaseStatus,
    BackupManifest,
    BackupObservation,
    BackupStage,
    DatabaseKind,
    DatabaseSnapshot,
    RecoveryMarkerSnapshot,
    RetentionPolicy,
)
from inventory_control.backups.filesystem import decode_manifest_json
from inventory_control.backups.persistence import (
    BackupPersistenceIntegrityError,
    BackupPersistenceService,
    BackupPersistenceTransactionError,
    FLEET_FULL_BACKUP_LEASE_KEY,
)


UTC = timezone.utc
BASE = datetime(2026, 8, 22, 4, 0, tzinfo=UTC)
ALL_STAGES = frozenset(BackupStage)


def _id(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"inventory-manager-backup-persistence/{label}")


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
                observed_at=BASE,
            )
        )
    return mysql_control_database


def _service(session, now: datetime) -> BackupPersistenceService:
    return BackupPersistenceService(
        session=session,
        database_clock=lambda _session: now,
    )


def _manifest_and_observation(label: str, attempt_id: UUID):
    artifact_id = _id(f"artifact/{label}")
    published_name = f"backup-{artifact_id}.sql.gz"
    databases = (
        DatabaseSnapshot(
            database_id=_id("control"),
            kind=DatabaseKind.CONTROL,
            schema_generation=17,
            schema_sha256=_digest("control-schema"),
            required_root_key_versions=(1, 2),
        ),
        DatabaseSnapshot(
            database_id=_id("tenant"),
            kind=DatabaseKind.TENANT,
            schema_generation=9,
            schema_sha256=_digest("tenant-schema"),
            required_root_key_versions=(2,),
        ),
    )
    marker = RecoveryMarkerSnapshot(
        installation_id=_id("installation"),
        recovery_run_id=_id("recovery-run"),
        marker_generation=4,
        marker_sha256=_digest("marker"),
    )
    manifest = BackupManifest(
        artifact_id=artifact_id,
        attempt_id=attempt_id,
        published_name=published_name,
        snapshot_at_utc=BASE + timedelta(minutes=2),
        completed_at_utc=BASE + timedelta(minutes=3),
        artifact_sha256=_digest(f"artifact/{label}"),
        size_bytes=8192,
        databases=databases,
        root_key_versions=(2, 1),
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
        observed_databases=tuple(reversed(databases)),
        observed_root_key_versions=(2, 1),
        observed_recovery_marker=marker,
    )
    return manifest, observation


def _start_attempt(control_database, label: str = "success"):
    acquisition_id = _id(f"acquisition/{label}")
    attempt_id = _id(f"attempt/{label}")
    manifest, observation = _manifest_and_observation(label, attempt_id)
    with control_database.transaction() as session:
        lease = _service(session, BASE).acquire_lease(
            acquisition_id=acquisition_id,
            holder_id=f"nas-worker-{label}",
            lease_duration=timedelta(minutes=30),
        )
    with control_database.transaction() as session:
        attempt = _service(
            session, BASE + timedelta(minutes=1)
        ).begin_attempt(
            attempt_id=attempt_id,
            partial_name=f"{manifest.published_name}.partial",
            acquisition_id=acquisition_id,
            lease_generation=lease.generation,
            fencing_token=lease.fencing_token,
        )
    return lease, attempt, manifest, observation


def _complete_at(control_database, *, label: str, snapshot_at: datetime):
    acquisition_id = _id(f"acquisition/{label}")
    attempt_id = _id(f"attempt/{label}")
    manifest, observation = _manifest_and_observation(label, attempt_id)
    manifest = replace(
        manifest,
        snapshot_at_utc=snapshot_at,
        completed_at_utc=snapshot_at + timedelta(minutes=1),
    )
    observation = replace(
        observation,
        observed_manifest_sha256=manifest.manifest_sha256,
    )
    with control_database.transaction() as session:
        lease = _service(
            session, snapshot_at - timedelta(minutes=2)
        ).acquire_lease(
            acquisition_id=acquisition_id,
            holder_id=f"nas-worker-{label}",
            lease_duration=timedelta(minutes=30),
        )
    with control_database.transaction() as session:
        _service(
            session, snapshot_at - timedelta(minutes=1)
        ).begin_attempt(
            attempt_id=attempt_id,
            partial_name=f"{manifest.published_name}.partial",
            acquisition_id=acquisition_id,
            lease_generation=lease.generation,
            fencing_token=lease.fencing_token,
        )
    with control_database.transaction() as session:
        return _service(
            session, snapshot_at + timedelta(minutes=2)
        ).complete_attempt(
            manifest=manifest,
            observation=observation,
        ).artifact


def test_lease_acquire_and_renew_are_control_db_only(
    control_database,
    monkeypatch,
):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("filesystem manifest codec must not be called")

    monkeypatch.setattr(backup_persistence, "encode_manifest_json", forbidden)
    monkeypatch.setattr(backup_persistence, "decode_manifest_json", forbidden)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())

    event.listen(control_database.engine, "before_cursor_execute", capture)
    acquisition_id = _id("acquisition/lease-only")
    try:
        with control_database.transaction() as session:
            lease = _service(session, BASE).acquire_lease(
                acquisition_id=acquisition_id,
                holder_id="nas-worker-1",
                lease_duration=timedelta(minutes=10),
            )
        with control_database.transaction() as session:
            renewed = _service(
                session, BASE + timedelta(minutes=1)
            ).renew_lease(
                acquisition_id=acquisition_id,
                lease_generation=lease.generation,
                fencing_token=lease.fencing_token,
                lease_duration=timedelta(minutes=15),
            )
    finally:
        event.remove(control_database.engine, "before_cursor_execute", capture)

    assert renewed.generation == 1
    assert renewed.fencing_token == 1
    assert renewed.expires_at_utc == BASE + timedelta(minutes=16)
    joined = " ".join(statements)
    assert "platform_backup_leases" in joined
    for forbidden_table in (
        "tenants",
        "provider_account",
        "completed_backup_artifacts",
        "backup_attempts",
    ):
        assert forbidden_table not in joined


def test_attempt_requires_exact_live_fence_and_replays_exactly(control_database):
    acquisition_id = _id("acquisition/fence")
    attempt_id = _id("attempt/fence")
    manifest, _observation = _manifest_and_observation("fence", attempt_id)
    with control_database.transaction() as session:
        lease = _service(session, BASE).acquire_lease(
            acquisition_id=acquisition_id,
            holder_id="nas-worker-fence",
            lease_duration=timedelta(minutes=30),
        )

    with control_database.transaction() as session:
        service = _service(session, BASE + timedelta(minutes=1))
        with pytest.raises(BackupDomainError) as caught:
            service.begin_attempt(
                attempt_id=attempt_id,
                partial_name=f"{manifest.published_name}.partial",
                acquisition_id=acquisition_id,
                lease_generation=lease.generation,
                fencing_token=lease.fencing_token + 1,
            )
    assert caught.value.code == "STALE_BACKUP_LEASE_FENCE"

    with control_database.transaction() as session:
        first = _service(session, BASE + timedelta(minutes=1)).begin_attempt(
            attempt_id=attempt_id,
            partial_name=f"{manifest.published_name}.partial",
            acquisition_id=acquisition_id,
            lease_generation=lease.generation,
            fencing_token=lease.fencing_token,
        )
    with control_database.transaction() as session:
        replay = _service(session, BASE + timedelta(minutes=2)).begin_attempt(
            attempt_id=attempt_id,
            partial_name=f"{manifest.published_name}.partial",
            acquisition_id=acquisition_id,
            lease_generation=lease.generation,
            fencing_token=lease.fencing_token,
        )
        assert (
            session.scalar(
                sa.select(sa.func.count()).select_from(BackupAttemptRecord)
            )
            == 1
        )
    assert replay == first


def test_completion_persists_canonical_manifest_and_releases_same_lease(
    control_database,
):
    lease, attempt, manifest, observation = _start_attempt(control_database)

    with control_database.transaction() as session:
        completed = _service(
            session, BASE + timedelta(minutes=4)
        ).complete_attempt(manifest=manifest, observation=observation)

    assert completed.idempotent_replay is False
    assert completed.lease.status is BackupLeaseStatus.AVAILABLE
    assert completed.lease.generation == lease.generation
    assert completed.lease.last_acquisition_id == attempt.acquisition_id

    with control_database.transaction() as session:
        row = session.get(
            CompletedBackupArtifactRecord, str(manifest.artifact_id)
        )
        assert row is not None
        decoded = decode_manifest_json(
            row.canonical_manifest_bytes,
            expected_manifest_sha256=row.manifest_sha256,
        )
        assert decoded == manifest
        canonical_payload = json.loads(row.canonical_manifest_bytes)
        canonical_text = json.dumps(canonical_payload, sort_keys=True).lower()
        for forbidden in ("password", "key_material", "path", "dsn", "secret"):
            assert forbidden not in canonical_text
        assert row.artifact_sha256 == manifest.artifact_sha256
        assert row.record_sha256 == completed.artifact.record_sha256
        assert row.marker_sha256 == manifest.recovery_marker.marker_sha256
        loaded = _service(
            session, BASE + timedelta(minutes=5)
        ).load_completed_artifact(artifact_id=manifest.artifact_id)
        assert loaded == completed.artifact
        lease_row = session.get(
            PlatformBackupLease, FLEET_FULL_BACKUP_LEASE_KEY
        )
        assert lease_row.status == BackupLeaseStatus.AVAILABLE.value


def test_completion_reads_database_time_after_lease_and_attempt_locks(
    control_database,
):
    _lease, _attempt, manifest, observation = _start_attempt(
        control_database, "clock-after-locks"
    )
    sequence: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        lowered = statement.lower()
        if lowered.lstrip().startswith("select"):
            if "platform_backup_leases" in lowered:
                sequence.append("lease")
            elif "backup_attempts" in lowered:
                sequence.append("attempt")

    def database_clock(_session):
        sequence.append("clock")
        return BASE + timedelta(minutes=4)

    event.listen(control_database.engine, "before_cursor_execute", capture)
    try:
        with control_database.transaction() as session:
            BackupPersistenceService(
                session=session,
                database_clock=database_clock,
            ).complete_attempt(
                manifest=manifest,
                observation=observation,
            )
    finally:
        event.remove(control_database.engine, "before_cursor_execute", capture)

    assert sequence[:3] == ["lease", "attempt", "clock"]


def test_microsecond_backup_facts_round_trip_and_exactly_replay(
    control_database,
):
    label = "microsecond-roundtrip"
    acquisition_id = _id(f"acquisition/{label}")
    attempt_id = _id(f"attempt/{label}")
    manifest, observation = _manifest_and_observation(label, attempt_id)
    snapshot_at = BASE + timedelta(minutes=5, microseconds=123456)
    completed_at = snapshot_at + timedelta(seconds=7, microseconds=111111)
    manifest = replace(
        manifest,
        snapshot_at_utc=snapshot_at,
        completed_at_utc=completed_at,
    )
    observation = replace(
        observation,
        observed_manifest_sha256=manifest.manifest_sha256,
    )
    acquired_at = BASE + timedelta(minutes=1, microseconds=222222)
    with control_database.transaction() as session:
        lease = _service(session, acquired_at).acquire_lease(
            acquisition_id=acquisition_id,
            holder_id="nas-worker-microsecond",
            lease_duration=timedelta(minutes=30, microseconds=333333),
        )
    with control_database.transaction() as session:
        attempt = _service(
            session, BASE + timedelta(minutes=2, microseconds=444444)
        ).begin_attempt(
            attempt_id=attempt_id,
            partial_name=f"{manifest.published_name}.partial",
            acquisition_id=acquisition_id,
            lease_generation=lease.generation,
            fencing_token=lease.fencing_token,
        )
    with control_database.transaction() as session:
        first = _service(
            session, completed_at + timedelta(seconds=1)
        ).complete_attempt(manifest=manifest, observation=observation)
    with control_database.transaction() as session:
        replay = _service(
            session, completed_at + timedelta(seconds=2)
        ).complete_attempt(manifest=manifest, observation=observation)
        loaded = _service(
            session, completed_at + timedelta(seconds=2)
        ).load_completed_artifact(artifact_id=manifest.artifact_id)

    assert attempt.started_at_utc.microsecond == 444444
    assert lease.acquired_at_utc.microsecond == 222222
    assert lease.expires_at_utc.microsecond == 555555
    assert first.artifact.snapshot_at_utc.microsecond == 123456
    assert first.artifact.completed_at_utc.microsecond == 234567
    assert replay.idempotent_replay is True
    assert replay.artifact == first.artifact == loaded


def test_completion_leaves_atomic_commit_or_rollback_to_caller(control_database):
    _lease, _attempt, manifest, observation = _start_attempt(
        control_database, "caller-rollback"
    )
    with control_database.new_session() as session:
        transaction = session.begin()
        result = _service(
            session, BASE + timedelta(minutes=4)
        ).complete_attempt(manifest=manifest, observation=observation)
        assert result.lease.status is BackupLeaseStatus.AVAILABLE
        transaction.rollback()

    with control_database.transaction() as session:
        assert session.get(
            CompletedBackupArtifactRecord, str(manifest.artifact_id)
        ) is None
        row = session.get(PlatformBackupLease, FLEET_FULL_BACKUP_LEASE_KEY)
        assert row.status == BackupLeaseStatus.HELD.value


def test_exact_completion_replay_does_not_release_or_overwrite_newer_lease(
    control_database,
):
    _lease, _attempt, manifest, observation = _start_attempt(
        control_database, "response-loss"
    )
    with control_database.transaction() as session:
        first = _service(
            session, BASE + timedelta(minutes=4)
        ).complete_attempt(manifest=manifest, observation=observation)

    newer_acquisition = _id("acquisition/newer")
    with control_database.transaction() as session:
        newer = _service(
            session, BASE + timedelta(minutes=5)
        ).acquire_lease(
            acquisition_id=newer_acquisition,
            holder_id="nas-worker-newer",
            lease_duration=timedelta(minutes=30),
        )

    with control_database.transaction() as session:
        replay = _service(
            session, BASE + timedelta(minutes=6)
        ).complete_attempt(manifest=manifest, observation=observation)

    assert replay.idempotent_replay is True
    assert replay.artifact == first.artifact
    assert replay.lease.status is BackupLeaseStatus.HELD
    assert replay.lease.acquisition_id == newer_acquisition
    assert replay.lease.generation == newer.generation
    with control_database.transaction() as session:
        row = session.get(PlatformBackupLease, FLEET_FULL_BACKUP_LEASE_KEY)
        assert row.status == BackupLeaseStatus.HELD.value
        assert row.acquisition_id == str(newer_acquisition)
        assert row.generation == newer.generation
        assert session.scalar(
            sa.select(sa.func.count()).select_from(CompletedBackupArtifactRecord)
        ) == 1


def test_changed_completion_replay_fails_closed_and_keeps_newer_lease(
    control_database,
):
    _lease, _attempt, manifest, observation = _start_attempt(
        control_database, "changed-replay"
    )
    with control_database.transaction() as session:
        _service(session, BASE + timedelta(minutes=4)).complete_attempt(
            manifest=manifest,
            observation=observation,
        )
    newer_acquisition = _id("acquisition/newer-changed")
    with control_database.transaction() as session:
        newer = _service(
            session, BASE + timedelta(minutes=5)
        ).acquire_lease(
            acquisition_id=newer_acquisition,
            holder_id="nas-worker-newer-changed",
            lease_duration=timedelta(minutes=30),
        )

    changed_manifest = replace(manifest, size_bytes=manifest.size_bytes + 1)
    changed_observation = replace(
        observation,
        observed_size_bytes=changed_manifest.size_bytes,
        observed_manifest_sha256=changed_manifest.manifest_sha256,
    )
    with control_database.transaction() as session:
        with pytest.raises(BackupDomainError) as caught:
            _service(
                session, BASE + timedelta(minutes=6)
            ).complete_attempt(
                manifest=changed_manifest,
                observation=changed_observation,
            )
    assert caught.value.code == "DUPLICATE_ARTIFACT_IDENTITY"
    with control_database.transaction() as session:
        row = session.get(PlatformBackupLease, FLEET_FULL_BACKUP_LEASE_KEY)
        assert row.acquisition_id == str(newer_acquisition)
        assert row.generation == newer.generation


def test_load_revalidates_canonical_manifest_and_record(control_database):
    _lease, _attempt, manifest, observation = _start_attempt(
        control_database, "tamper"
    )
    with control_database.transaction() as session:
        _service(session, BASE + timedelta(minutes=4)).complete_attempt(
            manifest=manifest,
            observation=observation,
        )
    with control_database.transaction() as session:
        session.execute(
            sa.update(CompletedBackupArtifactRecord)
            .where(
                CompletedBackupArtifactRecord.artifact_id
                == str(manifest.artifact_id)
            )
            .values(canonical_manifest_bytes=b"{}")
        )
    with control_database.transaction() as session:
        with pytest.raises(BackupPersistenceIntegrityError):
            _service(
                session, BASE + timedelta(minutes=5)
            ).load_completed_artifact(artifact_id=manifest.artifact_id)


def test_retention_plan_validates_full_catalog_without_writes(control_database):
    first_snapshot = BASE + timedelta(minutes=2)
    artifacts = tuple(
        _complete_at(
            control_database,
            label=f"retention-{offset:02d}",
            snapshot_at=first_snapshot + timedelta(hours=offset),
        )
        for offset in range(50)
    )
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower().strip())

    event.listen(control_database.engine, "before_cursor_execute", capture)
    try:
        with control_database.transaction() as session:
            plan = _service(session, BASE + timedelta(hours=51)).plan_retention(
                newly_verified_artifact_id=artifacts[-1].artifact_id,
                policy=RetentionPolicy("Asia/Shanghai"),
            )
            assert session.scalar(
                sa.select(sa.func.count()).select_from(
                    CompletedBackupArtifactRecord
                )
            ) == len(artifacts)
    finally:
        event.remove(control_database.engine, "before_cursor_execute", capture)

    assert plan.triggered_by_artifact_id == artifacts[-1].artifact_id
    assert plan.cleanup_candidate_ids == tuple(
        artifact.artifact_id for artifact in artifacts[:2]
    )
    assert len(plan.hourly_artifact_ids) == 48
    assert set(plan.retained_artifact_ids).isdisjoint(
        plan.cleanup_candidate_ids
    )
    assert not any(
        statement.startswith(("insert", "update", "delete"))
        for statement in statements
    )


def test_retention_plan_fails_closed_on_unrelated_tampered_history(
    control_database,
):
    old = _complete_at(
        control_database,
        label="retention-tampered-old",
        snapshot_at=BASE + timedelta(hours=1),
    )
    latest = _complete_at(
        control_database,
        label="retention-tampered-latest",
        snapshot_at=BASE + timedelta(hours=2),
    )
    with control_database.transaction() as session:
        session.execute(
            sa.update(CompletedBackupArtifactRecord)
            .where(
                CompletedBackupArtifactRecord.artifact_id
                == str(old.artifact_id)
            )
            .values(canonical_manifest_bytes=b"{}")
        )

    with control_database.transaction() as session:
        with pytest.raises(BackupPersistenceIntegrityError):
            _service(session, BASE + timedelta(hours=3)).plan_retention(
                newly_verified_artifact_id=latest.artifact_id,
                policy=RetentionPolicy("UTC"),
            )


def test_requires_clean_explicit_caller_transaction(control_database):
    acquisition_id = _id("acquisition/transaction")
    with control_database.new_session() as session:
        with pytest.raises(BackupPersistenceTransactionError):
            _service(session, BASE).acquire_lease(
                acquisition_id=acquisition_id,
                holder_id="nas-worker-transaction",
                lease_duration=timedelta(minutes=10),
            )

    with control_database.new_session() as session:
        session.scalar(sa.select(sa.literal(1)))
        with pytest.raises(BackupPersistenceTransactionError):
            _service(session, BASE).acquire_lease(
                acquisition_id=acquisition_id,
                holder_id="nas-worker-transaction",
                lease_duration=timedelta(minutes=10),
            )

    with control_database.new_session() as session:
        transaction = session.begin()
        row = session.get(PlatformBackupLease, FLEET_FULL_BACKUP_LEASE_KEY)
        row.observed_at = BASE + timedelta(seconds=1)
        with pytest.raises(BackupPersistenceTransactionError):
            _service(session, BASE).acquire_lease(
                acquisition_id=acquisition_id,
                holder_id="nas-worker-transaction",
                lease_duration=timedelta(minutes=10),
            )
        transaction.rollback()


def test_persisted_schema_has_no_secret_path_or_free_form_json_columns():
    columns = {
        table.name: set(table.c.keys())
        for table in (
            PlatformBackupLease.__table__,
            BackupAttemptRecord.__table__,
            CompletedBackupArtifactRecord.__table__,
        )
    }
    joined = " ".join(
        column for table_columns in columns.values() for column in table_columns
    ).lower()
    for forbidden in ("password", "secret", "material", "path", "dsn", "json"):
        assert forbidden not in joined
    assert "canonical_manifest_bytes" in columns["completed_backup_artifacts"]
    assert "partial_name" in columns["backup_attempts"]
