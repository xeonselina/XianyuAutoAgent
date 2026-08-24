"""Caller-transaction persistence for verified full-backup facts.

This adapter performs control-database operations only.  It never contacts a
tenant database, provider, SSH endpoint, NAS, dump process, or filesystem.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from inventory_control.database import read_database_utc_value
from inventory_control.models.backups import (
    BackupAttemptRecord,
    CompletedBackupArtifactRecord,
    PlatformBackupLease,
)
from inventory_control.transactions import require_caller_transaction

from .domain import (
    BackupAttempt,
    BackupCompletionResult,
    BackupDomainError,
    BackupLease,
    BackupLeaseStatus,
    BackupManifest,
    BackupObservation,
    CompletedBackupArtifact,
    RetentionPlan,
    RetentionPolicy,
    acquire_backup_lease,
    begin_backup_attempt,
    complete_backup as _complete_backup,
    plan_successful_point_retention,
    renew_backup_lease,
)
from .filesystem import decode_manifest_json, encode_manifest_json


FLEET_FULL_BACKUP_LEASE_KEY = "fleet_full_backup"


class BackupPersistenceError(BackupDomainError):
    """Stable, non-sensitive persistence failure."""

    def __init__(self, code: str = "BACKUP_PERSISTENCE_FAILED") -> None:
        super().__init__(code)


class BackupPersistenceTransactionError(BackupPersistenceError):
    """The caller did not provide a clean explicit outer transaction."""

    def __init__(self) -> None:
        super().__init__("BACKUP_PERSISTENCE_TRANSACTION_INVALID")


class BackupPersistenceIntegrityError(BackupPersistenceError):
    """Persisted backup facts were missing, malformed, or contradictory."""

    def __init__(self, code: str = "BACKUP_PERSISTED_FACTS_INVALID") -> None:
        super().__init__(code)


DatabaseClock = Callable[[Session], datetime]


class BackupPersistenceService:
    """Persist lease, attempt, and immutable completion facts atomically."""

    __slots__ = ("_database_clock", "_session")

    def __init__(
        self,
        *,
        session: Session,
        database_clock: DatabaseClock | None = None,
    ) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session")
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._session = session
        self._database_clock = database_clock or _read_database_utc_now

    def acquire_lease(
        self,
        *,
        acquisition_id: UUID,
        holder_id: str,
        lease_duration: timedelta,
    ) -> BackupLease:
        """Acquire or exactly replay the singleton fleet backup lease."""

        self._prepare(mutation=True)
        current = self._lock_lease()
        selected = acquire_backup_lease(
            current,
            acquisition_id=acquisition_id,
            holder_id=holder_id,
            database_now_utc=self._now(),
            lease_duration=lease_duration,
        )
        if selected != current:
            self._write_lease(selected)
            self._flush_or_fail()
        return selected

    def renew_lease(
        self,
        *,
        acquisition_id: UUID,
        lease_generation: int,
        fencing_token: int,
        lease_duration: timedelta,
    ) -> BackupLease:
        """Renew only the exact current acquisition, generation, and fence."""

        self._prepare(mutation=True)
        selected = renew_backup_lease(
            self._lock_lease(),
            acquisition_id=acquisition_id,
            lease_generation=lease_generation,
            fencing_token=fencing_token,
            database_now_utc=self._now(),
            lease_duration=lease_duration,
        )
        self._write_lease(selected)
        self._flush_or_fail()
        return selected

    def begin_attempt(
        self,
        *,
        attempt_id: UUID,
        partial_name: str,
        acquisition_id: UUID,
        lease_generation: int,
        fencing_token: int,
    ) -> BackupAttempt:
        """Persist an immutable attempt only under the caller's exact fence."""

        self._prepare(mutation=True)
        current = self._lock_lease()
        _require_expected_fence(
            current,
            acquisition_id=acquisition_id,
            lease_generation=lease_generation,
            fencing_token=fencing_token,
        )
        selected = begin_backup_attempt(
            current,
            attempt_id=attempt_id,
            partial_name=partial_name,
            database_now_utc=self._now(),
        )
        conflicts = self._attempt_conflicts(
            attempt_id=selected.attempt_id,
            partial_name=selected.partial_name,
        )
        if conflicts:
            exact = tuple(
                item for item in conflicts if item.attempt_id == selected.attempt_id
            )
            if (
                len(exact) == 1
                and _same_attempt_identity(exact[0], selected)
                and len(conflicts) == 1
            ):
                return exact[0]
            raise BackupPersistenceIntegrityError("BACKUP_ATTEMPT_IDENTITY_CONFLICT")

        row = BackupAttemptRecord(
            attempt_id=str(selected.attempt_id),
            acquisition_id=str(selected.acquisition_id),
            lease_generation=selected.lease_generation,
            fencing_token=selected.fencing_token,
            partial_name=selected.partial_name,
            started_at=selected.started_at_utc,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError:
            self._session.expire_all()
            conflicts = self._attempt_conflicts(
                attempt_id=selected.attempt_id,
                partial_name=selected.partial_name,
            )
            if len(conflicts) == 1 and _same_attempt_identity(conflicts[0], selected):
                return conflicts[0]
            raise BackupPersistenceIntegrityError(
                "BACKUP_ATTEMPT_IDENTITY_CONFLICT"
            ) from None
        return selected

    def complete_attempt(
        self,
        *,
        manifest: BackupManifest,
        observation: BackupObservation,
    ) -> BackupCompletionResult:
        """Persist one verified completion and release its exact lease.

        Exact replay returns the already sealed artifact without changing the
        current lease.  This remains true if a newer acquisition is now held.
        """

        self._prepare(mutation=True)
        if not isinstance(manifest, BackupManifest):
            raise BackupDomainError("INVALID_BACKUP_MANIFEST")
        if not isinstance(observation, BackupObservation):
            raise BackupDomainError("INVALID_BACKUP_OBSERVATION")

        lease = self._lock_lease()
        attempt = self._lock_attempt(manifest.attempt_id)
        # Lease validity must be evaluated with database time observed after
        # both authoritative rows are locked.  Reading time before a lock wait
        # could let an expired worker publish with a stale timestamp.
        now = self._now()
        existing = self._conflicting_artifacts(
            artifact_id=manifest.artifact_id,
            attempt_id=manifest.attempt_id,
            published_name=manifest.published_name,
            database_now_utc=now,
        )
        completed = _complete_backup(
            lease=lease,
            attempt=attempt,
            manifest=manifest,
            observation=observation,
            existing_artifacts=existing,
            database_now_utc=now,
        )
        if completed.idempotent_replay:
            return completed

        encoded_manifest = encode_manifest_json(manifest)
        try:
            decoded_manifest = decode_manifest_json(
                encoded_manifest,
                expected_manifest_sha256=completed.artifact.manifest_sha256,
            )
        except ValueError:
            raise BackupPersistenceIntegrityError(
                "BACKUP_CANONICAL_MANIFEST_INVALID"
            ) from None
        if decoded_manifest != manifest:
            raise BackupPersistenceIntegrityError("BACKUP_CANONICAL_MANIFEST_INVALID")

        artifact_row = _artifact_row(
            completed.artifact,
            canonical_manifest_bytes=encoded_manifest,
        )
        try:
            with self._session.begin_nested():
                self._session.add(artifact_row)
                self._write_lease(completed.lease)
                self._session.flush()
        except IntegrityError:
            self._session.expire_all()
            current_lease = self._lock_lease()
            raced = self._conflicting_artifacts(
                artifact_id=manifest.artifact_id,
                attempt_id=manifest.attempt_id,
                published_name=manifest.published_name,
                database_now_utc=now,
            )
            replay = _complete_backup(
                lease=current_lease,
                attempt=attempt,
                manifest=manifest,
                observation=observation,
                existing_artifacts=raced,
                database_now_utc=now,
            )
            if replay.idempotent_replay:
                return replay
            raise BackupPersistenceIntegrityError(
                "BACKUP_COMPLETION_IDENTITY_CONFLICT"
            ) from None
        return completed

    def load_completed_artifact(
        self,
        *,
        artifact_id: UUID,
    ) -> CompletedBackupArtifact | None:
        """Load one immutable artifact through the canonical decoder."""

        self._prepare(mutation=False)
        if not isinstance(artifact_id, UUID):
            raise BackupDomainError("INVALID_ARTIFACT_ID")
        try:
            row = self._session.scalar(
                sa.select(CompletedBackupArtifactRecord)
                .where(CompletedBackupArtifactRecord.artifact_id == str(artifact_id))
                .execution_options(autoflush=False, populate_existing=True)
            )
        except SQLAlchemyError:
            raise BackupPersistenceError() from None
        if row is None:
            return None
        return _artifact_from_row(row, database_now_utc=self._now())

    def plan_retention(
        self,
        *,
        newly_verified_artifact_id: UUID,
        policy: RetentionPolicy,
    ) -> RetentionPlan:
        """Validate the completed catalog and calculate a read-only D23 plan.

        The returned cleanup identifiers are only candidates.  This method
        never deletes artifact rows, touches the filesystem, or acknowledges
        NAS/cloud retention.  A malformed catalog row fails the entire plan
        closed so callers cannot delete around unverified backup history.
        """

        self._prepare(mutation=False)
        if not isinstance(newly_verified_artifact_id, UUID):
            raise BackupDomainError("INVALID_ARTIFACT_ID")
        if not isinstance(policy, RetentionPolicy):
            raise BackupDomainError("INVALID_RETENTION_POLICY")
        try:
            rows = tuple(
                self._session.scalars(
                    sa.select(CompletedBackupArtifactRecord)
                    .order_by(
                        CompletedBackupArtifactRecord.snapshot_at,
                        CompletedBackupArtifactRecord.completed_at,
                        CompletedBackupArtifactRecord.artifact_id,
                    )
                    .execution_options(
                        autoflush=False,
                        populate_existing=True,
                    )
                )
            )
        except SQLAlchemyError:
            raise BackupPersistenceError() from None
        now = self._now()
        artifacts = tuple(_artifact_from_row(row, database_now_utc=now) for row in rows)
        return plan_successful_point_retention(
            artifacts,
            newly_verified_artifact_id=newly_verified_artifact_id,
            policy=policy,
            database_now_utc=now,
        )

    def _prepare(self, *, mutation: bool) -> None:
        require_caller_transaction(
            self._session,
            BackupPersistenceTransactionError,
            clean=True,
        )

    def _now(self) -> datetime:
        return _as_utc(self._database_clock(self._session))

    def _lock_lease(self) -> BackupLease:
        try:
            row = self._session.scalar(
                sa.select(PlatformBackupLease)
                .where(PlatformBackupLease.lease_key == FLEET_FULL_BACKUP_LEASE_KEY)
                .with_for_update()
                .execution_options(autoflush=False, populate_existing=True)
            )
        except SQLAlchemyError:
            raise BackupPersistenceError() from None
        if row is None:
            raise BackupPersistenceIntegrityError("BACKUP_LEASE_ROW_MISSING")
        return _lease_from_row(row)

    def _write_lease(self, lease: BackupLease) -> None:
        try:
            row = self._session.get(PlatformBackupLease, FLEET_FULL_BACKUP_LEASE_KEY)
        except SQLAlchemyError:
            raise BackupPersistenceError() from None
        if row is None:
            raise BackupPersistenceIntegrityError("BACKUP_LEASE_ROW_MISSING")
        row.status = lease.status.value
        row.generation = lease.generation
        row.fencing_token = lease.fencing_token
        row.observed_at = lease.observed_at_utc
        row.holder_id = lease.holder_id
        row.acquisition_id = _optional_uuid_text(lease.acquisition_id)
        row.acquired_at = lease.acquired_at_utc
        row.expires_at = lease.expires_at_utc
        row.last_acquisition_id = _optional_uuid_text(lease.last_acquisition_id)

    def _lock_attempt(self, attempt_id: UUID) -> BackupAttempt:
        try:
            row = self._session.scalar(
                sa.select(BackupAttemptRecord)
                .where(BackupAttemptRecord.attempt_id == str(attempt_id))
                .with_for_update()
                .execution_options(autoflush=False, populate_existing=True)
            )
        except SQLAlchemyError:
            raise BackupPersistenceError() from None
        if row is None:
            raise BackupPersistenceIntegrityError("BACKUP_ATTEMPT_ROW_MISSING")
        return _attempt_from_row(row)

    def _attempt_conflicts(
        self,
        *,
        attempt_id: UUID,
        partial_name: str,
    ) -> tuple[BackupAttempt, ...]:
        try:
            rows = tuple(
                self._session.scalars(
                    sa.select(BackupAttemptRecord)
                    .where(
                        sa.or_(
                            BackupAttemptRecord.attempt_id == str(attempt_id),
                            BackupAttemptRecord.partial_name == partial_name,
                        )
                    )
                    .with_for_update()
                    .execution_options(
                        autoflush=False,
                        populate_existing=True,
                    )
                )
            )
        except SQLAlchemyError:
            raise BackupPersistenceError() from None
        return tuple(_attempt_from_row(row) for row in rows)

    def _conflicting_artifacts(
        self,
        *,
        artifact_id: UUID,
        attempt_id: UUID,
        published_name: str,
        database_now_utc: datetime,
    ) -> tuple[CompletedBackupArtifact, ...]:
        try:
            rows = tuple(
                self._session.scalars(
                    sa.select(CompletedBackupArtifactRecord)
                    .where(
                        sa.or_(
                            CompletedBackupArtifactRecord.artifact_id
                            == str(artifact_id),
                            CompletedBackupArtifactRecord.attempt_id == str(attempt_id),
                            CompletedBackupArtifactRecord.published_name
                            == published_name,
                        )
                    )
                    .execution_options(
                        autoflush=False,
                        populate_existing=True,
                    )
                )
            )
        except SQLAlchemyError:
            raise BackupPersistenceError() from None
        return tuple(
            _artifact_from_row(row, database_now_utc=database_now_utc) for row in rows
        )

    def _flush_or_fail(self) -> None:
        try:
            self._session.flush()
        except SQLAlchemyError:
            raise BackupPersistenceError() from None


def _lease_from_row(row: PlatformBackupLease) -> BackupLease:
    try:
        return BackupLease(
            status=BackupLeaseStatus(row.status),
            generation=row.generation,
            fencing_token=row.fencing_token,
            observed_at_utc=_as_utc(row.observed_at),
            holder_id=row.holder_id,
            acquisition_id=_optional_uuid(row.acquisition_id),
            acquired_at_utc=_optional_utc(row.acquired_at),
            expires_at_utc=_optional_utc(row.expires_at),
            last_acquisition_id=_optional_uuid(row.last_acquisition_id),
        )
    except (BackupDomainError, TypeError, ValueError):
        raise BackupPersistenceIntegrityError() from None


def _attempt_from_row(row: BackupAttemptRecord) -> BackupAttempt:
    try:
        return BackupAttempt(
            attempt_id=_uuid(row.attempt_id),
            acquisition_id=_uuid(row.acquisition_id),
            lease_generation=row.lease_generation,
            fencing_token=row.fencing_token,
            partial_name=row.partial_name,
            started_at_utc=_as_utc(row.started_at),
        )
    except (BackupDomainError, TypeError, ValueError):
        raise BackupPersistenceIntegrityError() from None


def _artifact_from_row(
    row: CompletedBackupArtifactRecord,
    *,
    database_now_utc: datetime,
) -> CompletedBackupArtifact:
    try:
        canonical = bytes(row.canonical_manifest_bytes)
        manifest_digest = bytes(row.manifest_sha256)
        manifest = decode_manifest_json(
            canonical,
            expected_manifest_sha256=manifest_digest,
        )
        snapshot_at = _as_utc(row.snapshot_at)
        completed_at = _as_utc(row.completed_at)
        if (
            str(manifest.artifact_id) != row.artifact_id
            or str(manifest.attempt_id) != row.attempt_id
            or manifest.published_name != row.published_name
            or manifest.snapshot_at_utc != snapshot_at
            or manifest.completed_at_utc != completed_at
            or manifest.artifact_sha256 != bytes(row.artifact_sha256)
            or manifest.size_bytes != row.size_bytes
            or str(manifest.recovery_marker.installation_id) != row.installation_id
            or str(manifest.recovery_marker.recovery_run_id) != row.recovery_run_id
            or manifest.recovery_marker.marker_generation != row.marker_generation
            or manifest.recovery_marker.marker_sha256 != bytes(row.marker_sha256)
        ):
            raise BackupPersistenceIntegrityError()
        artifact = CompletedBackupArtifact(
            artifact_id=manifest.artifact_id,
            attempt_id=manifest.attempt_id,
            published_name=manifest.published_name,
            snapshot_at_utc=manifest.snapshot_at_utc,
            completed_at_utc=manifest.completed_at_utc,
            artifact_sha256=manifest.artifact_sha256,
            manifest_sha256=manifest.manifest_sha256,
            size_bytes=manifest.size_bytes,
            databases=manifest.databases,
            root_key_versions=manifest.root_key_versions,
            recovery_marker=manifest.recovery_marker,
            record_sha256=bytes(row.record_sha256),
        )
        artifact.verify_integrity(database_now_utc=database_now_utc)
        if encode_manifest_json(manifest) != canonical:
            raise BackupPersistenceIntegrityError()
        return artifact
    except BackupPersistenceIntegrityError:
        raise
    except (BackupDomainError, TypeError, ValueError):
        raise BackupPersistenceIntegrityError() from None


def _artifact_row(
    artifact: CompletedBackupArtifact,
    *,
    canonical_manifest_bytes: bytes,
) -> CompletedBackupArtifactRecord:
    marker = artifact.recovery_marker
    return CompletedBackupArtifactRecord(
        artifact_id=str(artifact.artifact_id),
        attempt_id=str(artifact.attempt_id),
        published_name=artifact.published_name,
        canonical_manifest_bytes=canonical_manifest_bytes,
        artifact_sha256=artifact.artifact_sha256,
        manifest_sha256=artifact.manifest_sha256,
        record_sha256=artifact.record_sha256,
        size_bytes=artifact.size_bytes,
        snapshot_at=artifact.snapshot_at_utc,
        completed_at=artifact.completed_at_utc,
        installation_id=str(marker.installation_id),
        recovery_run_id=str(marker.recovery_run_id),
        marker_generation=marker.marker_generation,
        marker_sha256=marker.marker_sha256,
    )


def _same_attempt_identity(left: BackupAttempt, right: BackupAttempt) -> bool:
    return (
        left.attempt_id == right.attempt_id
        and left.acquisition_id == right.acquisition_id
        and left.lease_generation == right.lease_generation
        and left.fencing_token == right.fencing_token
        and left.partial_name == right.partial_name
    )


def _require_expected_fence(
    lease: BackupLease,
    *,
    acquisition_id: UUID,
    lease_generation: int,
    fencing_token: int,
) -> None:
    if not isinstance(acquisition_id, UUID):
        raise BackupDomainError("INVALID_ACQUISITION_ID")
    if (
        not isinstance(lease_generation, int)
        or isinstance(lease_generation, bool)
        or lease_generation <= 0
    ):
        raise BackupDomainError("INVALID_BACKUP_LEASE_GENERATION")
    if (
        not isinstance(fencing_token, int)
        or isinstance(fencing_token, bool)
        or fencing_token <= 0
    ):
        raise BackupDomainError("INVALID_BACKUP_FENCING_TOKEN")
    if (
        lease.acquisition_id != acquisition_id
        or lease.generation != lease_generation
        or lease.fencing_token != fencing_token
    ):
        raise BackupDomainError("STALE_BACKUP_LEASE_FENCE")


def _read_database_utc_now(session: Session) -> datetime:
    return _as_utc(read_database_utc_value(session))


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise BackupPersistenceIntegrityError()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _optional_utc(value: object | None) -> datetime | None:
    return None if value is None else _as_utc(value)


def _uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise ValueError("invalid technical identity")
    selected = UUID(value)
    if str(selected) != value:
        raise ValueError("invalid technical identity")
    return selected


def _optional_uuid(value: object | None) -> UUID | None:
    return None if value is None else _uuid(value)


def _optional_uuid_text(value: UUID | None) -> str | None:
    return None if value is None else str(value)


__all__ = [
    "BackupPersistenceError",
    "BackupPersistenceIntegrityError",
    "BackupPersistenceService",
    "BackupPersistenceTransactionError",
    "FLEET_FULL_BACKUP_LEASE_KEY",
]
