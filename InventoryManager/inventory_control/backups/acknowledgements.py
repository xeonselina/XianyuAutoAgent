"""Pure rules for independent NAS backup and cloud-sync acknowledgements.

The module has no database, filesystem, SSH, NAS, cloud-drive, or provider
dependency.  It accepts only privacy-minimized technical facts and produces
immutable acknowledgement and freshness results.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Iterable
from uuid import UUID


_SHA256_BYTES = 32
_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_REQUEST_DIGEST_DOMAIN = b"inventory-control/backup-ack-request/v1\0"


class BackupAcknowledgementError(ValueError):
    """Stable, non-sensitive acknowledgement-domain failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class BackupAcknowledgementConflict(BackupAcknowledgementError):
    """An idempotency slot was reused with different request facts."""

    def __init__(self) -> None:
        super().__init__("BACKUP_ACK_IDEMPOTENCY_CONFLICT")


class AcknowledgementKind(str, Enum):
    BACKUP_STATUS = "backup-status-ack"
    SYNC_STATUS = "sync-status-ack"


class AcknowledgementSafeResult(str, Enum):
    VERIFIED = "verified"
    SYNCED = "synced"


class FreshnessState(str, Enum):
    MISSING = "missing"
    FRESH = "fresh"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class CompletedArtifactBinding:
    """Authoritative non-secret projection of one completed backup artifact."""

    artifact_id: UUID
    manifest_sha256: bytes
    artifact_sha256: bytes
    completed_at_utc: datetime

    def __post_init__(self) -> None:
        _uuid("INVALID_ACK_ARTIFACT_ID", self.artifact_id)
        _digest("INVALID_ACK_MANIFEST_DIGEST", self.manifest_sha256)
        _digest("INVALID_ACK_ARTIFACT_DIGEST", self.artifact_sha256)
        object.__setattr__(
            self,
            "completed_at_utc",
            _utc("INVALID_ACK_ARTIFACT_COMPLETION_TIME", self.completed_at_utc),
        )


@dataclass(frozen=True, slots=True)
class AcknowledgementSubmission:
    """Canonical request received from the restricted NAS command boundary."""

    kind: AcknowledgementKind
    artifact_id: UUID
    manifest_sha256: bytes
    artifact_sha256: bytes
    source_generation: int
    idempotency_key: str
    request_digest: bytes
    safe_result: AcknowledgementSafeResult
    reported_at_utc: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.kind, AcknowledgementKind):
            _fail("INVALID_ACK_KIND")
        _uuid("INVALID_ACK_ARTIFACT_ID", self.artifact_id)
        _digest("INVALID_ACK_MANIFEST_DIGEST", self.manifest_sha256)
        _digest("INVALID_ACK_ARTIFACT_DIGEST", self.artifact_sha256)
        if (
            not isinstance(self.source_generation, int)
            or isinstance(self.source_generation, bool)
            or self.source_generation <= 0
        ):
            _fail("INVALID_ACK_SOURCE_GENERATION")
        _idempotency_key(self.idempotency_key)
        _digest("INVALID_ACK_REQUEST_DIGEST", self.request_digest)
        if not isinstance(self.safe_result, AcknowledgementSafeResult):
            _fail("INVALID_ACK_SAFE_RESULT")
        _require_result_for_kind(self.kind, self.safe_result)
        reported_at = _utc("INVALID_ACK_REPORTED_TIME", self.reported_at_utc)
        object.__setattr__(self, "reported_at_utc", reported_at)
        expected = acknowledgement_request_digest(
            kind=self.kind,
            artifact_id=self.artifact_id,
            manifest_sha256=self.manifest_sha256,
            artifact_sha256=self.artifact_sha256,
            source_generation=self.source_generation,
            idempotency_key=self.idempotency_key,
            safe_result=self.safe_result,
            reported_at_utc=reported_at,
        )
        if not hmac.compare_digest(self.request_digest, expected):
            _fail("ACK_REQUEST_DIGEST_MISMATCH")


@dataclass(frozen=True, slots=True)
class BackupArtifactAcknowledgement:
    """Immutable accepted acknowledgement plus its completed-artifact time."""

    kind: AcknowledgementKind
    artifact_id: UUID
    manifest_sha256: bytes
    artifact_sha256: bytes
    artifact_completed_at_utc: datetime
    source_generation: int
    idempotency_key: str
    request_digest: bytes
    safe_result: AcknowledgementSafeResult
    reported_at_utc: datetime
    received_at_utc: datetime
    row_version: int = 1

    def __post_init__(self) -> None:
        submission = AcknowledgementSubmission(
            kind=self.kind,
            artifact_id=self.artifact_id,
            manifest_sha256=self.manifest_sha256,
            artifact_sha256=self.artifact_sha256,
            source_generation=self.source_generation,
            idempotency_key=self.idempotency_key,
            request_digest=self.request_digest,
            safe_result=self.safe_result,
            reported_at_utc=self.reported_at_utc,
        )
        object.__setattr__(self, "reported_at_utc", submission.reported_at_utc)
        object.__setattr__(
            self,
            "artifact_completed_at_utc",
            _utc(
                "INVALID_ACK_ARTIFACT_COMPLETION_TIME",
                self.artifact_completed_at_utc,
            ),
        )
        object.__setattr__(
            self,
            "received_at_utc",
            _utc("INVALID_ACK_RECEIVED_TIME", self.received_at_utc),
        )
        if self.row_version != 1:
            _fail("INVALID_ACK_ROW_VERSION")


@dataclass(frozen=True, slots=True)
class AcknowledgementWriteResult:
    acknowledgement: BackupArtifactAcknowledgement
    idempotent_replay: bool

    def __post_init__(self) -> None:
        if not isinstance(self.acknowledgement, BackupArtifactAcknowledgement):
            _fail("INVALID_ACK_WRITE_RESULT")
        if not isinstance(self.idempotent_replay, bool):
            _fail("INVALID_ACK_WRITE_RESULT")


@dataclass(frozen=True, slots=True)
class AcknowledgementFreshness:
    kind: AcknowledgementKind
    state: FreshnessState
    evaluated_at_utc: datetime
    maximum_age: timedelta
    latest_artifact_id: UUID | None = None
    latest_restore_point_at_utc: datetime | None = None
    latest_reported_at_utc: datetime | None = None
    latest_received_at_utc: datetime | None = None
    latest_source_generation: int | None = None
    age: timedelta | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, AcknowledgementKind):
            _fail("INVALID_ACK_FRESHNESS")
        if not isinstance(self.state, FreshnessState):
            _fail("INVALID_ACK_FRESHNESS")
        object.__setattr__(
            self,
            "evaluated_at_utc",
            _utc("INVALID_ACK_FRESHNESS_TIME", self.evaluated_at_utc),
        )
        _maximum_age(self.maximum_age)
        details = (
            self.latest_artifact_id,
            self.latest_restore_point_at_utc,
            self.latest_reported_at_utc,
            self.latest_received_at_utc,
            self.latest_source_generation,
            self.age,
        )
        if self.state is FreshnessState.MISSING:
            if any(value is not None for value in details):
                _fail("INVALID_ACK_FRESHNESS")
            return
        if any(value is None for value in details):
            _fail("INVALID_ACK_FRESHNESS")
        _uuid("INVALID_ACK_ARTIFACT_ID", self.latest_artifact_id)
        restore_point = _utc(
            "INVALID_ACK_ARTIFACT_COMPLETION_TIME",
            self.latest_restore_point_at_utc,
        )
        reported_at = _utc(
            "INVALID_ACK_REPORTED_TIME",
            self.latest_reported_at_utc,
        )
        received_at = _utc(
            "INVALID_ACK_RECEIVED_TIME",
            self.latest_received_at_utc,
        )
        if (
            not isinstance(self.latest_source_generation, int)
            or isinstance(self.latest_source_generation, bool)
            or self.latest_source_generation <= 0
        ):
            _fail("INVALID_ACK_FRESHNESS")
        if not isinstance(self.age, timedelta) or self.age < timedelta(0):
            _fail("INVALID_ACK_FRESHNESS")
        expected_state = (
            FreshnessState.STALE
            if self.age > self.maximum_age
            else FreshnessState.FRESH
        )
        if self.state is not expected_state:
            _fail("INVALID_ACK_FRESHNESS")
        object.__setattr__(self, "latest_restore_point_at_utc", restore_point)
        object.__setattr__(self, "latest_reported_at_utc", reported_at)
        object.__setattr__(self, "latest_received_at_utc", received_at)


@dataclass(frozen=True, slots=True)
class BackupFreshnessSnapshot:
    latest_verified_backup: AcknowledgementFreshness
    latest_cloud_sync: AcknowledgementFreshness

    def __post_init__(self) -> None:
        if (
            not isinstance(self.latest_verified_backup, AcknowledgementFreshness)
            or self.latest_verified_backup.kind
            is not AcknowledgementKind.BACKUP_STATUS
            or not isinstance(self.latest_cloud_sync, AcknowledgementFreshness)
            or self.latest_cloud_sync.kind is not AcknowledgementKind.SYNC_STATUS
        ):
            _fail("INVALID_ACK_FRESHNESS_SNAPSHOT")


def acknowledgement_request_digest(
    *,
    kind: AcknowledgementKind,
    artifact_id: UUID,
    manifest_sha256: bytes,
    artifact_sha256: bytes,
    source_generation: int,
    idempotency_key: str,
    safe_result: AcknowledgementSafeResult,
    reported_at_utc: datetime,
) -> bytes:
    """Return the stable, purpose-separated digest for one ack request."""

    if not isinstance(kind, AcknowledgementKind):
        _fail("INVALID_ACK_KIND")
    _uuid("INVALID_ACK_ARTIFACT_ID", artifact_id)
    _digest("INVALID_ACK_MANIFEST_DIGEST", manifest_sha256)
    _digest("INVALID_ACK_ARTIFACT_DIGEST", artifact_sha256)
    if (
        not isinstance(source_generation, int)
        or isinstance(source_generation, bool)
        or source_generation <= 0
    ):
        _fail("INVALID_ACK_SOURCE_GENERATION")
    _idempotency_key(idempotency_key)
    if not isinstance(safe_result, AcknowledgementSafeResult):
        _fail("INVALID_ACK_SAFE_RESULT")
    _require_result_for_kind(kind, safe_result)
    reported_at = _utc("INVALID_ACK_REPORTED_TIME", reported_at_utc)
    payload = {
        "artifact_id": str(artifact_id),
        "artifact_sha256": artifact_sha256.hex(),
        "idempotency_key": idempotency_key,
        "kind": kind.value,
        "manifest_sha256": manifest_sha256.hex(),
        "reported_at_utc": _format_utc(reported_at),
        "safe_result": safe_result.value,
        "source_generation": source_generation,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(_REQUEST_DIGEST_DOMAIN + encoded).digest()


def accept_acknowledgement(
    *,
    artifact: CompletedArtifactBinding,
    submission: AcknowledgementSubmission,
    existing_acknowledgements: Iterable[BackupArtifactAcknowledgement],
    database_now_utc: datetime,
) -> AcknowledgementWriteResult:
    """Accept, exactly replay, or reject one independently scoped ack."""

    if not isinstance(artifact, CompletedArtifactBinding):
        _fail("INVALID_COMPLETED_ARTIFACT_BINDING")
    if not isinstance(submission, AcknowledgementSubmission):
        _fail("INVALID_ACK_SUBMISSION")
    now = _utc("INVALID_ACK_RECEIVED_TIME", database_now_utc)
    if artifact.completed_at_utc > now:
        _fail("ACK_ARTIFACT_COMPLETION_IN_FUTURE")
    if (
        submission.artifact_id != artifact.artifact_id
        or not hmac.compare_digest(
            submission.manifest_sha256, artifact.manifest_sha256
        )
        or not hmac.compare_digest(
            submission.artifact_sha256, artifact.artifact_sha256
        )
    ):
        _fail("ACK_COMPLETED_ARTIFACT_MISMATCH")

    existing = tuple(existing_acknowledgements)
    if any(not isinstance(item, BackupArtifactAcknowledgement) for item in existing):
        _fail("INVALID_EXISTING_ACKNOWLEDGEMENT")
    same_slot = tuple(
        item
        for item in existing
        if item.kind is submission.kind
        and item.artifact_id == submission.artifact_id
    )
    same_key = tuple(
        item
        for item in existing
        if item.kind is submission.kind
        and item.idempotency_key == submission.idempotency_key
    )
    if len(same_slot) > 1 or len(same_key) > 1:
        _fail("ACK_PERSISTED_FACTS_INVALID")
    if same_slot or same_key:
        if (
            len(same_slot) == 1
            and len(same_key) == 1
            and same_slot[0] is same_key[0]
            and _matches_submission(same_slot[0], submission, artifact)
        ):
            return AcknowledgementWriteResult(
                acknowledgement=same_slot[0],
                idempotent_replay=True,
            )
        raise BackupAcknowledgementConflict()

    accepted = BackupArtifactAcknowledgement(
        kind=submission.kind,
        artifact_id=submission.artifact_id,
        manifest_sha256=submission.manifest_sha256,
        artifact_sha256=submission.artifact_sha256,
        artifact_completed_at_utc=artifact.completed_at_utc,
        source_generation=submission.source_generation,
        idempotency_key=submission.idempotency_key,
        request_digest=submission.request_digest,
        safe_result=submission.safe_result,
        reported_at_utc=submission.reported_at_utc,
        received_at_utc=now,
        row_version=1,
    )
    return AcknowledgementWriteResult(
        acknowledgement=accepted,
        idempotent_replay=False,
    )


def evaluate_acknowledgement_freshness(
    acknowledgements: Iterable[BackupArtifactAcknowledgement],
    *,
    database_now_utc: datetime,
    backup_maximum_age: timedelta,
    sync_maximum_age: timedelta,
) -> BackupFreshnessSnapshot:
    """Evaluate backup and cloud-sync restore-point ages independently."""

    now = _utc("INVALID_ACK_FRESHNESS_TIME", database_now_utc)
    _maximum_age(backup_maximum_age)
    _maximum_age(sync_maximum_age)
    materialized = tuple(acknowledgements)
    if any(
        not isinstance(item, BackupArtifactAcknowledgement)
        for item in materialized
    ):
        _fail("INVALID_EXISTING_ACKNOWLEDGEMENT")
    return BackupFreshnessSnapshot(
        latest_verified_backup=_evaluate_kind(
            materialized,
            kind=AcknowledgementKind.BACKUP_STATUS,
            now=now,
            maximum_age=backup_maximum_age,
        ),
        latest_cloud_sync=_evaluate_kind(
            materialized,
            kind=AcknowledgementKind.SYNC_STATUS,
            now=now,
            maximum_age=sync_maximum_age,
        ),
    )


def _evaluate_kind(
    acknowledgements: tuple[BackupArtifactAcknowledgement, ...],
    *,
    kind: AcknowledgementKind,
    now: datetime,
    maximum_age: timedelta,
) -> AcknowledgementFreshness:
    selected = tuple(item for item in acknowledgements if item.kind is kind)
    if not selected:
        return AcknowledgementFreshness(
            kind=kind,
            state=FreshnessState.MISSING,
            evaluated_at_utc=now,
            maximum_age=maximum_age,
        )
    latest = max(
        selected,
        key=lambda item: (
            item.artifact_completed_at_utc,
            item.reported_at_utc,
            item.received_at_utc,
            item.source_generation,
            str(item.artifact_id),
        ),
    )
    if latest.artifact_completed_at_utc > now:
        _fail("ACK_ARTIFACT_COMPLETION_IN_FUTURE")
    age = now - latest.artifact_completed_at_utc
    state = (
        FreshnessState.STALE if age > maximum_age else FreshnessState.FRESH
    )
    return AcknowledgementFreshness(
        kind=kind,
        state=state,
        evaluated_at_utc=now,
        maximum_age=maximum_age,
        latest_artifact_id=latest.artifact_id,
        latest_restore_point_at_utc=latest.artifact_completed_at_utc,
        latest_reported_at_utc=latest.reported_at_utc,
        latest_received_at_utc=latest.received_at_utc,
        latest_source_generation=latest.source_generation,
        age=age,
    )


def _matches_submission(
    acknowledgement: BackupArtifactAcknowledgement,
    submission: AcknowledgementSubmission,
    artifact: CompletedArtifactBinding,
) -> bool:
    return (
        acknowledgement.kind is submission.kind
        and acknowledgement.artifact_id == submission.artifact_id
        and acknowledgement.artifact_completed_at_utc
        == artifact.completed_at_utc
        and hmac.compare_digest(
            acknowledgement.manifest_sha256, submission.manifest_sha256
        )
        and hmac.compare_digest(
            acknowledgement.artifact_sha256, submission.artifact_sha256
        )
        and acknowledgement.source_generation == submission.source_generation
        and acknowledgement.idempotency_key == submission.idempotency_key
        and hmac.compare_digest(
            acknowledgement.request_digest, submission.request_digest
        )
        and acknowledgement.safe_result is submission.safe_result
        and acknowledgement.reported_at_utc == submission.reported_at_utc
    )


def _require_result_for_kind(
    kind: AcknowledgementKind,
    result: AcknowledgementSafeResult,
) -> None:
    expected = {
        AcknowledgementKind.BACKUP_STATUS: AcknowledgementSafeResult.VERIFIED,
        AcknowledgementKind.SYNC_STATUS: AcknowledgementSafeResult.SYNCED,
    }[kind]
    if result is not expected:
        _fail("ACK_SAFE_RESULT_KIND_MISMATCH")


def _idempotency_key(value: object) -> None:
    if not isinstance(value, str) or _IDEMPOTENCY_KEY.fullmatch(value) is None:
        _fail("INVALID_ACK_IDEMPOTENCY_KEY")


def _digest(code: str, value: object) -> None:
    if not isinstance(value, bytes) or len(value) != _SHA256_BYTES:
        _fail(code)


def _uuid(code: str, value: object) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        _fail(code)


def _utc(code: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        _fail(code)
    selected = value.astimezone(timezone.utc)
    if selected.utcoffset() != timedelta(0):
        _fail(code)
    return selected


def _maximum_age(value: object) -> None:
    if not isinstance(value, timedelta) or value <= timedelta(0):
        _fail("INVALID_ACK_MAXIMUM_AGE")


def _format_utc(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _fail(code: str) -> None:
    raise BackupAcknowledgementError(code)


__all__ = [
    "AcknowledgementFreshness",
    "AcknowledgementKind",
    "AcknowledgementSafeResult",
    "AcknowledgementSubmission",
    "AcknowledgementWriteResult",
    "BackupAcknowledgementConflict",
    "BackupAcknowledgementError",
    "BackupArtifactAcknowledgement",
    "BackupFreshnessSnapshot",
    "CompletedArtifactBinding",
    "FreshnessState",
    "accept_acknowledgement",
    "acknowledgement_request_digest",
    "evaluate_acknowledgement_freshness",
]
