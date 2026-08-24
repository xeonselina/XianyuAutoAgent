"""Pure domain rules for completed backup artifacts and retention.

The module intentionally performs no filesystem, database, SSH, compression,
or NAS work.  Callers supply immutable observations from those boundaries and
receive immutable facts that are safe to persist or execute later.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Iterable, Sequence
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_SHA256_BYTES = 32
_ARTIFACT_NAME = re.compile(
    r"backup-(?P<identity>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})\.sql\.gz"
)
_REQUIRED_STAGES = frozenset(
    {
        "dump",
        "compression",
        "transfer",
        "checksum",
        "manifest",
    }
)


class BackupDomainError(ValueError):
    """Stable, non-sensitive backup-domain failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class BackupStage(str, Enum):
    DUMP = "dump"
    COMPRESSION = "compression"
    TRANSFER = "transfer"
    CHECKSUM = "checksum"
    MANIFEST = "manifest"


class DatabaseKind(str, Enum):
    CONTROL = "control"
    TENANT = "tenant"


class BackupLeaseStatus(str, Enum):
    AVAILABLE = "available"
    HELD = "held"


@dataclass(frozen=True, slots=True)
class DatabaseSnapshot:
    """Non-sensitive identity and restore metadata for one database."""

    database_id: UUID
    kind: DatabaseKind
    schema_generation: int
    schema_sha256: bytes
    required_root_key_versions: tuple[int, ...]

    def __post_init__(self) -> None:
        _require_uuid("INVALID_DATABASE_ID", self.database_id)
        if not isinstance(self.kind, DatabaseKind):
            _fail("INVALID_DATABASE_KIND")
        if self.schema_generation <= 0:
            _fail("INVALID_SCHEMA_GENERATION")
        _require_sha256("INVALID_SCHEMA_SHA256", self.schema_sha256)
        versions = _normalize_versions(self.required_root_key_versions)
        object.__setattr__(self, "required_root_key_versions", versions)


@dataclass(frozen=True, slots=True)
class RecoveryMarkerSnapshot:
    """Technical recovery marker metadata; never contains marker contents."""

    installation_id: UUID
    recovery_run_id: UUID
    marker_generation: int
    marker_sha256: bytes

    def __post_init__(self) -> None:
        _require_uuid("INVALID_INSTALLATION_ID", self.installation_id)
        _require_uuid("INVALID_RECOVERY_RUN_ID", self.recovery_run_id)
        if self.marker_generation <= 0:
            _fail("INVALID_MARKER_GENERATION")
        _require_sha256("INVALID_MARKER_SHA256", self.marker_sha256)


@dataclass(frozen=True, slots=True)
class BackupManifest:
    """Immutable, data-minimized declaration for a full backup artifact."""

    artifact_id: UUID
    attempt_id: UUID
    published_name: str
    snapshot_at_utc: datetime
    completed_at_utc: datetime
    artifact_sha256: bytes
    size_bytes: int
    databases: tuple[DatabaseSnapshot, ...]
    root_key_versions: tuple[int, ...]
    recovery_marker: RecoveryMarkerSnapshot

    def __post_init__(self) -> None:
        _require_uuid("INVALID_ARTIFACT_ID", self.artifact_id)
        _require_uuid("INVALID_ATTEMPT_ID", self.attempt_id)
        _require_published_name(self.published_name, self.artifact_id)
        snapshot_at = _utc("INVALID_SNAPSHOT_TIME", self.snapshot_at_utc)
        completed_at = _utc("INVALID_COMPLETION_TIME", self.completed_at_utc)
        if completed_at < snapshot_at:
            _fail("COMPLETION_PRECEDES_SNAPSHOT")
        object.__setattr__(self, "snapshot_at_utc", snapshot_at)
        object.__setattr__(self, "completed_at_utc", completed_at)
        _require_sha256("INVALID_ARTIFACT_SHA256", self.artifact_sha256)
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool):
            _fail("INVALID_ARTIFACT_SIZE")
        if self.size_bytes <= 0:
            _fail("INVALID_ARTIFACT_SIZE")
        databases = _normalize_databases(self.databases)
        object.__setattr__(self, "databases", databases)
        root_versions = _normalize_versions(self.root_key_versions)
        if root_versions != _required_root_versions(databases):
            _fail("ROOT_KEY_VERSION_SET_MISMATCH")
        object.__setattr__(self, "root_key_versions", root_versions)
        if not isinstance(self.recovery_marker, RecoveryMarkerSnapshot):
            _fail("INVALID_RECOVERY_MARKER")

    @property
    def manifest_sha256(self) -> bytes:
        return _sha256_json(_manifest_payload(self))


@dataclass(frozen=True, slots=True)
class BackupObservation:
    """Observed results after all external backup steps have returned."""

    artifact_id: UUID
    attempt_id: UUID
    partial_name: str
    published_name: str
    successful_stages: frozenset[BackupStage]
    atomic_publish_succeeded: bool
    observed_artifact_sha256: bytes
    observed_manifest_sha256: bytes
    observed_size_bytes: int
    observed_databases: tuple[DatabaseSnapshot, ...]
    observed_root_key_versions: tuple[int, ...]
    observed_recovery_marker: RecoveryMarkerSnapshot

    def __post_init__(self) -> None:
        _require_uuid("INVALID_ARTIFACT_ID", self.artifact_id)
        _require_uuid("INVALID_ATTEMPT_ID", self.attempt_id)
        _require_published_name(self.published_name, self.artifact_id)
        if self.partial_name != f"{self.published_name}.partial":
            _fail("INVALID_PARTIAL_ARTIFACT_NAME")
        stages: frozenset[BackupStage]
        try:
            stages = frozenset(BackupStage(stage) for stage in self.successful_stages)
        except (TypeError, ValueError):
            _fail("INVALID_BACKUP_STAGE")
        object.__setattr__(self, "successful_stages", stages)
        if not isinstance(self.atomic_publish_succeeded, bool):
            _fail("INVALID_ATOMIC_PUBLISH_RESULT")
        _require_sha256(
            "INVALID_OBSERVED_ARTIFACT_SHA256", self.observed_artifact_sha256
        )
        _require_sha256(
            "INVALID_OBSERVED_MANIFEST_SHA256", self.observed_manifest_sha256
        )
        if not isinstance(self.observed_size_bytes, int) or isinstance(
            self.observed_size_bytes, bool
        ):
            _fail("INVALID_OBSERVED_ARTIFACT_SIZE")
        if self.observed_size_bytes <= 0:
            _fail("INVALID_OBSERVED_ARTIFACT_SIZE")
        databases = _normalize_databases(self.observed_databases)
        object.__setattr__(self, "observed_databases", databases)
        root_versions = _normalize_versions(self.observed_root_key_versions)
        if root_versions != _required_root_versions(databases):
            _fail("OBSERVED_ROOT_KEY_VERSION_SET_MISMATCH")
        object.__setattr__(self, "observed_root_key_versions", root_versions)
        if not isinstance(self.observed_recovery_marker, RecoveryMarkerSnapshot):
            _fail("INVALID_OBSERVED_RECOVERY_MARKER")


@dataclass(frozen=True, slots=True)
class BackupLease:
    """Single-instance lease state with monotonic generation and fence."""

    status: BackupLeaseStatus
    generation: int
    fencing_token: int
    observed_at_utc: datetime
    holder_id: str | None = None
    acquisition_id: UUID | None = None
    acquired_at_utc: datetime | None = None
    expires_at_utc: datetime | None = None
    last_acquisition_id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, BackupLeaseStatus):
            _fail("INVALID_BACKUP_LEASE_STATUS")
        if self.generation < 0:
            _fail("INVALID_BACKUP_LEASE_GENERATION")
        if self.fencing_token < 0:
            _fail("INVALID_BACKUP_FENCING_TOKEN")
        observed = _utc("INVALID_LEASE_OBSERVED_TIME", self.observed_at_utc)
        object.__setattr__(self, "observed_at_utc", observed)
        if self.last_acquisition_id is not None:
            _require_uuid("INVALID_LAST_ACQUISITION_ID", self.last_acquisition_id)
        if self.status is BackupLeaseStatus.AVAILABLE:
            if any(
                value is not None
                for value in (
                    self.holder_id,
                    self.acquisition_id,
                    self.acquired_at_utc,
                    self.expires_at_utc,
                )
            ):
                _fail("INCONSISTENT_AVAILABLE_LEASE")
            return
        if self.generation <= 0 or self.fencing_token <= 0:
            _fail("INVALID_HELD_LEASE_FENCE")
        _require_text("INVALID_LEASE_HOLDER", self.holder_id, maximum=128)
        _require_uuid("INVALID_ACQUISITION_ID", self.acquisition_id)
        acquired = _utc("INVALID_LEASE_ACQUIRED_TIME", self.acquired_at_utc)
        expires = _utc("INVALID_LEASE_EXPIRY_TIME", self.expires_at_utc)
        if expires <= acquired or observed < acquired or observed >= expires:
            _fail("INVALID_HELD_LEASE_WINDOW")
        if self.last_acquisition_id != self.acquisition_id:
            _fail("INCONSISTENT_LEASE_ACQUISITION")
        object.__setattr__(self, "acquired_at_utc", acquired)
        object.__setattr__(self, "expires_at_utc", expires)

    @classmethod
    def available(cls, *, observed_at_utc: datetime) -> "BackupLease":
        return cls(
            status=BackupLeaseStatus.AVAILABLE,
            generation=0,
            fencing_token=0,
            observed_at_utc=observed_at_utc,
        )


@dataclass(frozen=True, slots=True)
class BackupAttempt:
    attempt_id: UUID
    acquisition_id: UUID
    lease_generation: int
    fencing_token: int
    partial_name: str
    started_at_utc: datetime

    def __post_init__(self) -> None:
        _require_uuid("INVALID_ATTEMPT_ID", self.attempt_id)
        _require_uuid("INVALID_ACQUISITION_ID", self.acquisition_id)
        if self.lease_generation <= 0:
            _fail("INVALID_BACKUP_LEASE_GENERATION")
        if self.fencing_token <= 0:
            _fail("INVALID_BACKUP_FENCING_TOKEN")
        if not isinstance(self.partial_name, str) or not self.partial_name.endswith(
            ".sql.gz.partial"
        ):
            _fail("INVALID_PARTIAL_ARTIFACT_NAME")
        _require_published_name(self.partial_name.removesuffix(".partial"), None)
        object.__setattr__(
            self,
            "started_at_utc",
            _utc("INVALID_ATTEMPT_START_TIME", self.started_at_utc),
        )


@dataclass(frozen=True, slots=True)
class CompletedBackupArtifact:
    """Immutable verified artifact.  ``record_sha256`` seals all metadata."""

    artifact_id: UUID
    attempt_id: UUID
    published_name: str
    snapshot_at_utc: datetime
    completed_at_utc: datetime
    artifact_sha256: bytes
    manifest_sha256: bytes
    size_bytes: int
    databases: tuple[DatabaseSnapshot, ...]
    root_key_versions: tuple[int, ...]
    recovery_marker: RecoveryMarkerSnapshot
    record_sha256: bytes

    def __post_init__(self) -> None:
        _require_uuid("INVALID_ARTIFACT_ID", self.artifact_id)
        _require_uuid("INVALID_ATTEMPT_ID", self.attempt_id)
        _require_published_name(self.published_name, self.artifact_id)
        snapshot_at = _utc("INVALID_SNAPSHOT_TIME", self.snapshot_at_utc)
        completed_at = _utc("INVALID_COMPLETION_TIME", self.completed_at_utc)
        if completed_at < snapshot_at:
            _fail("COMPLETION_PRECEDES_SNAPSHOT")
        object.__setattr__(self, "snapshot_at_utc", snapshot_at)
        object.__setattr__(self, "completed_at_utc", completed_at)
        _require_sha256("INVALID_ARTIFACT_SHA256", self.artifact_sha256)
        _require_sha256("INVALID_MANIFEST_SHA256", self.manifest_sha256)
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool):
            _fail("INVALID_ARTIFACT_SIZE")
        if self.size_bytes <= 0:
            _fail("INVALID_ARTIFACT_SIZE")
        databases = _normalize_databases(self.databases)
        object.__setattr__(self, "databases", databases)
        root_versions = _normalize_versions(self.root_key_versions)
        if root_versions != _required_root_versions(databases):
            _fail("ROOT_KEY_VERSION_SET_MISMATCH")
        object.__setattr__(self, "root_key_versions", root_versions)
        if not isinstance(self.recovery_marker, RecoveryMarkerSnapshot):
            _fail("INVALID_RECOVERY_MARKER")
        _require_sha256("INVALID_ARTIFACT_RECORD_SHA256", self.record_sha256)
        if self.record_sha256 != _completed_record_sha256(self):
            _fail("CORRUPT_COMPLETED_ARTIFACT_RECORD")

    def verify_integrity(self, *, database_now_utc: datetime) -> None:
        now = _utc("INVALID_DATABASE_TIME", database_now_utc)
        if self.snapshot_at_utc > now or self.completed_at_utc > now:
            _fail("ARTIFACT_TIME_IN_FUTURE")
        if self.record_sha256 != _completed_record_sha256(self):
            _fail("CORRUPT_COMPLETED_ARTIFACT_RECORD")


@dataclass(frozen=True, slots=True)
class BackupCompletionResult:
    artifact: CompletedBackupArtifact
    lease: BackupLease
    idempotent_replay: bool


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """The approved D23 successful-point policy in one explicit timezone."""

    timezone_name: str
    hourly_success_points: int = 48
    daily_success_points: int = 30
    monthly_success_points: int = 12

    def __post_init__(self) -> None:
        _require_text("INVALID_RETENTION_TIMEZONE", self.timezone_name, maximum=128)
        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            _fail("INVALID_RETENTION_TIMEZONE")
        if (
            self.hourly_success_points,
            self.daily_success_points,
            self.monthly_success_points,
        ) != (48, 30, 12):
            _fail("UNSUPPORTED_RETENTION_POLICY")

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)


@dataclass(frozen=True, slots=True)
class RetentionPlan:
    hourly_artifact_ids: tuple[UUID, ...]
    daily_artifact_ids: tuple[UUID, ...]
    monthly_artifact_ids: tuple[UUID, ...]
    retained_artifact_ids: tuple[UUID, ...]
    cleanup_candidate_ids: tuple[UUID, ...]
    triggered_by_artifact_id: UUID


def acquire_backup_lease(
    current: BackupLease,
    *,
    acquisition_id: UUID,
    holder_id: str,
    database_now_utc: datetime,
    lease_duration: timedelta,
) -> BackupLease:
    """Acquire or idempotently replay the single backup lease."""

    if not isinstance(current, BackupLease):
        _fail("INVALID_BACKUP_LEASE")
    _require_uuid("INVALID_ACQUISITION_ID", acquisition_id)
    _require_text("INVALID_LEASE_HOLDER", holder_id, maximum=128)
    now = _utc("INVALID_DATABASE_TIME", database_now_utc)
    if not isinstance(lease_duration, timedelta) or lease_duration <= timedelta(0):
        _fail("INVALID_LEASE_DURATION")
    if now < current.observed_at_utc:
        _fail("LEASE_CLOCK_MOVED_BACKWARDS")

    if current.status is BackupLeaseStatus.HELD and now < current.expires_at_utc:
        if current.acquisition_id == acquisition_id:
            if current.holder_id != holder_id:
                _fail("DUPLICATE_LEASE_ACQUISITION_IDENTITY")
            return current
        _fail("OVERLAPPING_BACKUP_LEASE")

    if current.last_acquisition_id == acquisition_id:
        _fail("LEASE_ACQUISITION_ALREADY_ENDED")

    return BackupLease(
        status=BackupLeaseStatus.HELD,
        generation=current.generation + 1,
        fencing_token=current.fencing_token + 1,
        observed_at_utc=now,
        holder_id=holder_id,
        acquisition_id=acquisition_id,
        acquired_at_utc=now,
        expires_at_utc=now + lease_duration,
        last_acquisition_id=acquisition_id,
    )


def renew_backup_lease(
    current: BackupLease,
    *,
    acquisition_id: UUID,
    lease_generation: int,
    fencing_token: int,
    database_now_utc: datetime,
    lease_duration: timedelta,
) -> BackupLease:
    """Renew only the exact live owner/fence; stale workers stay fenced."""

    now = _utc("INVALID_DATABASE_TIME", database_now_utc)
    _require_live_fence(
        current,
        acquisition_id=acquisition_id,
        lease_generation=lease_generation,
        fencing_token=fencing_token,
        now=now,
    )
    if not isinstance(lease_duration, timedelta) or lease_duration <= timedelta(0):
        _fail("INVALID_LEASE_DURATION")
    return replace(
        current,
        observed_at_utc=now,
        expires_at_utc=now + lease_duration,
    )


def begin_backup_attempt(
    lease: BackupLease,
    *,
    attempt_id: UUID,
    partial_name: str,
    database_now_utc: datetime,
) -> BackupAttempt:
    """Bind a new attempt to the exact current lease generation and fence."""

    now = _utc("INVALID_DATABASE_TIME", database_now_utc)
    if lease.acquisition_id is None:
        _fail("BACKUP_LEASE_NOT_HELD")
    _require_live_fence(
        lease,
        acquisition_id=lease.acquisition_id,
        lease_generation=lease.generation,
        fencing_token=lease.fencing_token,
        now=now,
    )
    return BackupAttempt(
        attempt_id=attempt_id,
        acquisition_id=lease.acquisition_id,
        lease_generation=lease.generation,
        fencing_token=lease.fencing_token,
        partial_name=partial_name,
        started_at_utc=now,
    )


def complete_backup(
    *,
    lease: BackupLease,
    attempt: BackupAttempt,
    manifest: BackupManifest,
    observation: BackupObservation,
    existing_artifacts: Sequence[CompletedBackupArtifact],
    database_now_utc: datetime,
) -> BackupCompletionResult:
    """Validate every completion fact and atomically describe publication.

    A caller may persist the returned artifact and released lease in one local
    transaction.  No artifact is returned for a partial or mismatched result.
    """

    now = _utc("INVALID_DATABASE_TIME", database_now_utc)
    candidate = _candidate_artifact(
        attempt=attempt,
        manifest=manifest,
        observation=observation,
        now=now,
    )
    by_id, by_name, by_attempt = _validated_artifact_indexes(
        existing_artifacts, now=now
    )
    existing = by_id.get(candidate.artifact_id)
    if existing is not None:
        if existing != candidate:
            _fail("DUPLICATE_ARTIFACT_IDENTITY")
        return BackupCompletionResult(
            artifact=existing,
            lease=lease,
            idempotent_replay=True,
        )
    if candidate.published_name in by_name:
        _fail("DUPLICATE_ARTIFACT_NAME")
    if candidate.attempt_id in by_attempt:
        _fail("DUPLICATE_ATTEMPT_IDENTITY")

    _require_live_fence(
        lease,
        acquisition_id=attempt.acquisition_id,
        lease_generation=attempt.lease_generation,
        fencing_token=attempt.fencing_token,
        now=now,
    )
    if attempt.started_at_utc > manifest.snapshot_at_utc:
        _fail("SNAPSHOT_PRECEDES_ATTEMPT")
    released = BackupLease(
        status=BackupLeaseStatus.AVAILABLE,
        generation=lease.generation,
        fencing_token=lease.fencing_token,
        observed_at_utc=now,
        last_acquisition_id=lease.acquisition_id,
    )
    return BackupCompletionResult(
        artifact=candidate,
        lease=released,
        idempotent_replay=False,
    )


def plan_successful_point_retention(
    artifacts: Sequence[CompletedBackupArtifact],
    *,
    newly_verified_artifact_id: UUID,
    policy: RetentionPolicy,
    database_now_utc: datetime,
) -> RetentionPlan:
    """Return D23 retention and cleanup sets after a new verified success.

    Buckets use the recovery point (``snapshot_at_utc``) converted to the
    policy timezone.  The latest recovery point within each bucket wins, and
    the hourly/daily/monthly selections are unioned.  Cleanup is never proposed
    unless the trigger identifies the newest verified completion.
    """

    _require_uuid("INVALID_ARTIFACT_ID", newly_verified_artifact_id)
    if not isinstance(policy, RetentionPolicy):
        _fail("INVALID_RETENTION_POLICY")
    now = _utc("INVALID_DATABASE_TIME", database_now_utc)
    by_id, _, _ = _validated_artifact_indexes(artifacts, now=now)
    trigger = by_id.get(newly_verified_artifact_id)
    if trigger is None:
        _fail("NEW_VERIFIED_ARTIFACT_MISSING")
    latest = max(
        by_id.values(),
        key=lambda item: (
            item.completed_at_utc,
            item.snapshot_at_utc,
            str(item.artifact_id),
        ),
    )
    if trigger.artifact_id != latest.artifact_id:
        _fail("RETENTION_TRIGGER_NOT_LATEST_SUCCESS")

    zone = policy.timezone
    hourly = _select_bucket_representatives(
        by_id.values(),
        zone=zone,
        bucket=lambda value: (value.year, value.month, value.day, value.hour),
        count=policy.hourly_success_points,
    )
    daily = _select_bucket_representatives(
        by_id.values(),
        zone=zone,
        bucket=lambda value: (value.year, value.month, value.day),
        count=policy.daily_success_points,
    )
    monthly = _select_bucket_representatives(
        by_id.values(),
        zone=zone,
        bucket=lambda value: (value.year, value.month),
        count=policy.monthly_success_points,
    )
    retained = set(hourly) | set(daily) | set(monthly)
    cleanup = set(by_id) - retained
    order = lambda identity: (
        by_id[identity].snapshot_at_utc,
        by_id[identity].completed_at_utc,
        str(identity),
    )
    return RetentionPlan(
        hourly_artifact_ids=tuple(sorted(hourly, key=order)),
        daily_artifact_ids=tuple(sorted(daily, key=order)),
        monthly_artifact_ids=tuple(sorted(monthly, key=order)),
        retained_artifact_ids=tuple(sorted(retained, key=order)),
        cleanup_candidate_ids=tuple(sorted(cleanup, key=order)),
        triggered_by_artifact_id=trigger.artifact_id,
    )


def _candidate_artifact(
    *,
    attempt: BackupAttempt,
    manifest: BackupManifest,
    observation: BackupObservation,
    now: datetime,
) -> CompletedBackupArtifact:
    if attempt.attempt_id != manifest.attempt_id:
        _fail("ATTEMPT_MANIFEST_IDENTITY_MISMATCH")
    if attempt.attempt_id != observation.attempt_id:
        _fail("ATTEMPT_OBSERVATION_IDENTITY_MISMATCH")
    if manifest.artifact_id != observation.artifact_id:
        _fail("ARTIFACT_IDENTITY_MISMATCH")
    if attempt.partial_name != observation.partial_name:
        _fail("PARTIAL_ARTIFACT_IDENTITY_MISMATCH")
    if attempt.partial_name.removesuffix(".partial") != manifest.published_name:
        _fail("PUBLISHED_ARTIFACT_IDENTITY_MISMATCH")
    if manifest.published_name != observation.published_name:
        _fail("PUBLISHED_ARTIFACT_IDENTITY_MISMATCH")
    if frozenset(stage.value for stage in observation.successful_stages) != _REQUIRED_STAGES:
        _fail("INCOMPLETE_BACKUP_STAGES")
    if not observation.atomic_publish_succeeded:
        _fail("ATOMIC_PUBLISH_NOT_PROVEN")
    if observation.observed_artifact_sha256 != manifest.artifact_sha256:
        _fail("ARTIFACT_SHA256_MISMATCH")
    if observation.observed_manifest_sha256 != manifest.manifest_sha256:
        _fail("MANIFEST_SHA256_MISMATCH")
    if observation.observed_size_bytes != manifest.size_bytes:
        _fail("ARTIFACT_SIZE_MISMATCH")
    if observation.observed_databases != manifest.databases:
        _fail("DATABASE_SET_MISMATCH")
    if observation.observed_root_key_versions != manifest.root_key_versions:
        _fail("ROOT_KEY_VERSION_SET_MISMATCH")
    if observation.observed_recovery_marker != manifest.recovery_marker:
        _fail("RECOVERY_MARKER_MISMATCH")
    if manifest.snapshot_at_utc > now or manifest.completed_at_utc > now:
        _fail("ARTIFACT_TIME_IN_FUTURE")

    values = dict(
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
    )
    provisional = object.__new__(CompletedBackupArtifact)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "record_sha256", bytes(_SHA256_BYTES))
    record_sha256 = _completed_record_sha256(provisional)
    return CompletedBackupArtifact(**values, record_sha256=record_sha256)


def _validated_artifact_indexes(
    artifacts: Sequence[CompletedBackupArtifact], *, now: datetime
) -> tuple[
    dict[UUID, CompletedBackupArtifact],
    dict[str, CompletedBackupArtifact],
    dict[UUID, CompletedBackupArtifact],
]:
    by_id: dict[UUID, CompletedBackupArtifact] = {}
    by_name: dict[str, CompletedBackupArtifact] = {}
    by_attempt: dict[UUID, CompletedBackupArtifact] = {}
    for artifact in artifacts:
        if not isinstance(artifact, CompletedBackupArtifact):
            _fail("UNVERIFIED_BACKUP_ARTIFACT")
        artifact.verify_integrity(database_now_utc=now)
        if artifact.artifact_id in by_id:
            _fail("DUPLICATE_ARTIFACT_IDENTITY")
        if artifact.published_name in by_name:
            _fail("DUPLICATE_ARTIFACT_NAME")
        if artifact.attempt_id in by_attempt:
            _fail("DUPLICATE_ATTEMPT_IDENTITY")
        by_id[artifact.artifact_id] = artifact
        by_name[artifact.published_name] = artifact
        by_attempt[artifact.attempt_id] = artifact
    return by_id, by_name, by_attempt


def _select_bucket_representatives(
    artifacts: Iterable[CompletedBackupArtifact],
    *,
    zone: ZoneInfo,
    bucket,
    count: int,
) -> set[UUID]:
    representatives: dict[tuple[int, ...], CompletedBackupArtifact] = {}
    for artifact in artifacts:
        local = artifact.snapshot_at_utc.astimezone(zone)
        key = bucket(local)
        current = representatives.get(key)
        if current is None or (
            artifact.snapshot_at_utc,
            artifact.completed_at_utc,
            str(artifact.artifact_id),
        ) > (
            current.snapshot_at_utc,
            current.completed_at_utc,
            str(current.artifact_id),
        ):
            representatives[key] = artifact
    selected_keys = sorted(representatives, reverse=True)[:count]
    return {representatives[key].artifact_id for key in selected_keys}


def _require_live_fence(
    lease: BackupLease,
    *,
    acquisition_id: UUID,
    lease_generation: int,
    fencing_token: int,
    now: datetime,
) -> None:
    if not isinstance(lease, BackupLease) or lease.status is not BackupLeaseStatus.HELD:
        _fail("BACKUP_LEASE_NOT_HELD")
    if now < lease.observed_at_utc:
        _fail("LEASE_CLOCK_MOVED_BACKWARDS")
    if now >= lease.expires_at_utc:
        _fail("BACKUP_LEASE_EXPIRED")
    if (
        lease.acquisition_id != acquisition_id
        or lease.generation != lease_generation
        or lease.fencing_token != fencing_token
    ):
        _fail("STALE_BACKUP_LEASE_FENCE")


def _manifest_payload(manifest: BackupManifest) -> dict[str, object]:
    return {
        "artifact_id": str(manifest.artifact_id),
        "attempt_id": str(manifest.attempt_id),
        "published_name": manifest.published_name,
        "snapshot_at_utc": manifest.snapshot_at_utc.isoformat(),
        "completed_at_utc": manifest.completed_at_utc.isoformat(),
        "artifact_sha256": manifest.artifact_sha256.hex(),
        "size_bytes": manifest.size_bytes,
        "databases": [_database_payload(item) for item in manifest.databases],
        "root_key_versions": list(manifest.root_key_versions),
        "recovery_marker": _marker_payload(manifest.recovery_marker),
    }


def _completed_record_sha256(artifact: CompletedBackupArtifact) -> bytes:
    return _sha256_json(
        {
            "artifact_id": str(artifact.artifact_id),
            "attempt_id": str(artifact.attempt_id),
            "published_name": artifact.published_name,
            "snapshot_at_utc": artifact.snapshot_at_utc.isoformat(),
            "completed_at_utc": artifact.completed_at_utc.isoformat(),
            "artifact_sha256": artifact.artifact_sha256.hex(),
            "manifest_sha256": artifact.manifest_sha256.hex(),
            "size_bytes": artifact.size_bytes,
            "databases": [_database_payload(item) for item in artifact.databases],
            "root_key_versions": list(artifact.root_key_versions),
            "recovery_marker": _marker_payload(artifact.recovery_marker),
        }
    )


def _database_payload(database: DatabaseSnapshot) -> dict[str, object]:
    return {
        "database_id": str(database.database_id),
        "kind": database.kind.value,
        "schema_generation": database.schema_generation,
        "schema_sha256": database.schema_sha256.hex(),
        "required_root_key_versions": list(database.required_root_key_versions),
    }


def _marker_payload(marker: RecoveryMarkerSnapshot) -> dict[str, object]:
    return {
        "installation_id": str(marker.installation_id),
        "recovery_run_id": str(marker.recovery_run_id),
        "marker_generation": marker.marker_generation,
        "marker_sha256": marker.marker_sha256.hex(),
    }


def _sha256_json(payload: dict[str, object]) -> bytes:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).digest()


def _normalize_databases(
    values: Iterable[DatabaseSnapshot],
) -> tuple[DatabaseSnapshot, ...]:
    try:
        databases = tuple(values)
    except TypeError:
        _fail("INVALID_DATABASE_SET")
    if not databases:
        _fail("MISSING_DATABASE_SET")
    if any(not isinstance(item, DatabaseSnapshot) for item in databases):
        _fail("INVALID_DATABASE_SET")
    identities = [item.database_id for item in databases]
    if len(identities) != len(set(identities)):
        _fail("DUPLICATE_DATABASE_IDENTITY")
    control_count = sum(item.kind is DatabaseKind.CONTROL for item in databases)
    tenant_count = sum(item.kind is DatabaseKind.TENANT for item in databases)
    if control_count != 1 or tenant_count < 1:
        _fail("INCOMPLETE_FULL_DATABASE_SET")
    return tuple(sorted(databases, key=lambda item: (item.kind.value, str(item.database_id))))


def _required_root_versions(
    databases: Iterable[DatabaseSnapshot],
) -> tuple[int, ...]:
    return tuple(
        sorted(
            {
                version
                for database in databases
                for version in database.required_root_key_versions
            }
        )
    )


def _normalize_versions(values: Iterable[int]) -> tuple[int, ...]:
    try:
        versions = tuple(values)
    except TypeError:
        _fail("INVALID_ROOT_KEY_VERSION_SET")
    if not versions:
        _fail("MISSING_ROOT_KEY_VERSION_SET")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in versions
    ):
        _fail("INVALID_ROOT_KEY_VERSION_SET")
    if len(versions) != len(set(versions)):
        _fail("DUPLICATE_ROOT_KEY_VERSION")
    return tuple(sorted(versions))


def _require_published_name(value: object, artifact_id: UUID | None) -> None:
    if not isinstance(value, str):
        _fail("INVALID_PUBLISHED_ARTIFACT_NAME")
    match = _ARTIFACT_NAME.fullmatch(value)
    if match is None:
        _fail("INVALID_PUBLISHED_ARTIFACT_NAME")
    if artifact_id is not None and match.group("identity") != str(artifact_id):
        _fail("PUBLISHED_ARTIFACT_IDENTITY_MISMATCH")


def _require_uuid(code: str, value: object) -> None:
    if not isinstance(value, UUID):
        _fail(code)


def _require_sha256(code: str, value: object) -> None:
    if not isinstance(value, bytes) or len(value) != _SHA256_BYTES:
        _fail(code)


def _require_text(code: str, value: object, *, maximum: int) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        _fail(code)
    if value != value.strip() or any(ord(character) < 32 for character in value):
        _fail(code)


def _utc(code: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        _fail(code)
    normalized = value.astimezone(timezone.utc)
    if normalized.utcoffset() != timedelta(0):
        _fail(code)
    return normalized


def _fail(code: str) -> None:
    raise BackupDomainError(code)
