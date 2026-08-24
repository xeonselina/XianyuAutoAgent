"""Caller-owned control persistence for independent NAS backup acknowledgements.

This module performs control-database operations only.  It never contacts a
NAS, SSH endpoint, cloud drive, provider, filesystem, or tenant database, and
it never commits or rolls back the caller's outer transaction.
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
    BackupArtifactAcknowledgementRecord,
    CompletedBackupArtifactRecord,
)
from inventory_control.transactions import require_caller_transaction

from .acknowledgements import (
    AcknowledgementKind,
    AcknowledgementSafeResult,
    AcknowledgementSubmission,
    AcknowledgementWriteResult,
    BackupAcknowledgementConflict,
    BackupAcknowledgementError,
    BackupArtifactAcknowledgement,
    BackupFreshnessSnapshot,
    CompletedArtifactBinding,
    accept_acknowledgement,
    evaluate_acknowledgement_freshness,
)
from .persistence import BackupPersistenceError, _artifact_from_row


class BackupAckPersistenceError(BackupAcknowledgementError):
    """Stable, non-sensitive acknowledgement persistence failure."""

    def __init__(self, code: str = "BACKUP_ACK_PERSISTENCE_FAILED") -> None:
        super().__init__(code)


class BackupAckPersistenceTransactionError(BackupAckPersistenceError):
    def __init__(self) -> None:
        super().__init__("BACKUP_ACK_PERSISTENCE_TRANSACTION_INVALID")


class BackupAckPersistenceIntegrityError(BackupAckPersistenceError):
    def __init__(self, code: str = "BACKUP_ACK_PERSISTED_FACTS_INVALID") -> None:
        super().__init__(code)


DatabaseClock = Callable[[Session], datetime]


class BackupAcknowledgementPersistenceService:
    """Persist and evaluate privacy-minimized NAS acknowledgements."""

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

    def record_backup_status_ack(
        self,
        *,
        artifact_id: UUID,
        manifest_sha256: bytes,
        artifact_sha256: bytes,
        source_generation: int,
        idempotency_key: str,
        request_digest: bytes,
        reported_at_utc: datetime,
    ) -> AcknowledgementWriteResult:
        """Record NAS completion of local artifact/manifest/checksum checks."""

        return self._record(
            AcknowledgementSubmission(
                kind=AcknowledgementKind.BACKUP_STATUS,
                artifact_id=artifact_id,
                manifest_sha256=manifest_sha256,
                artifact_sha256=artifact_sha256,
                source_generation=source_generation,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                safe_result=AcknowledgementSafeResult.VERIFIED,
                reported_at_utc=reported_at_utc,
            )
        )

    def record_sync_status_ack(
        self,
        *,
        artifact_id: UUID,
        manifest_sha256: bytes,
        artifact_sha256: bytes,
        source_generation: int,
        idempotency_key: str,
        request_digest: bytes,
        reported_at_utc: datetime,
    ) -> AcknowledgementWriteResult:
        """Record cloud sync independently of the backup-status ack slot."""

        return self._record(
            AcknowledgementSubmission(
                kind=AcknowledgementKind.SYNC_STATUS,
                artifact_id=artifact_id,
                manifest_sha256=manifest_sha256,
                artifact_sha256=artifact_sha256,
                source_generation=source_generation,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                safe_result=AcknowledgementSafeResult.SYNCED,
                reported_at_utc=reported_at_utc,
            )
        )

    def evaluate_freshness(
        self,
        *,
        backup_maximum_age: timedelta,
        sync_maximum_age: timedelta,
    ) -> BackupFreshnessSnapshot:
        """Read and evaluate both acknowledgement streams independently."""

        self._prepare(mutation=False)
        try:
            rows = tuple(
                self._session.execute(
                    sa.select(
                        BackupArtifactAcknowledgementRecord,
                        CompletedBackupArtifactRecord,
                    )
                    .join(
                        CompletedBackupArtifactRecord,
                        CompletedBackupArtifactRecord.artifact_id
                        == BackupArtifactAcknowledgementRecord.artifact_id,
                    )
                    .execution_options(
                        autoflush=False,
                        populate_existing=True,
                    )
                ).all()
            )
        except SQLAlchemyError:
            raise BackupAckPersistenceError() from None
        # Read database time only after the acknowledgement/artifact snapshot;
        # an old clock read must not make a row fresh after a blocked query.
        now = self._now()
        acknowledgements = tuple(
            self._ack_from_rows(ack_row, artifact_row, database_now_utc=now)
            for ack_row, artifact_row in rows
        )
        return evaluate_acknowledgement_freshness(
            acknowledgements,
            database_now_utc=now,
            backup_maximum_age=backup_maximum_age,
            sync_maximum_age=sync_maximum_age,
        )

    def _record(
        self,
        submission: AcknowledgementSubmission,
    ) -> AcknowledgementWriteResult:
        self._prepare(mutation=True)
        artifact_row = self._lock_completed_artifact(submission.artifact_id)
        existing_rows = self._lock_conflicts(submission)
        # Both authoritative scopes are locked before the acceptance timestamp
        # is read.  A lock wait therefore cannot preserve a stale DB time.
        now = self._now()
        artifact = self._artifact_binding(
            artifact_row,
            database_now_utc=now,
        )
        existing = self._existing_for_submission(
            existing_rows,
            submission=submission,
            artifact=artifact,
        )
        reduced = accept_acknowledgement(
            artifact=artifact,
            submission=submission,
            existing_acknowledgements=existing,
            database_now_utc=now,
        )
        if reduced.idempotent_replay:
            return reduced

        try:
            with self._session.begin_nested():
                self._session.add(_ack_row(reduced.acknowledgement))
                self._session.flush()
        except IntegrityError:
            self._session.expire_all()
            artifact_row = self._lock_completed_artifact(submission.artifact_id)
            existing_rows = self._lock_conflicts(submission)
            raced_now = self._now()
            artifact = self._artifact_binding(
                artifact_row,
                database_now_utc=raced_now,
            )
            existing = self._existing_for_submission(
                existing_rows,
                submission=submission,
                artifact=artifact,
            )
            raced = accept_acknowledgement(
                artifact=artifact,
                submission=submission,
                existing_acknowledgements=existing,
                database_now_utc=raced_now,
            )
            if raced.idempotent_replay:
                return raced
            raise BackupAckPersistenceIntegrityError(
                "BACKUP_ACK_CONCURRENT_INSERT_INVALID"
            ) from None
        except SQLAlchemyError:
            raise BackupAckPersistenceError() from None
        return reduced

    def _prepare(self, *, mutation: bool) -> None:
        require_caller_transaction(
            self._session,
            BackupAckPersistenceTransactionError,
            clean=True,
        )

    def _now(self) -> datetime:
        try:
            return _as_utc(self._database_clock(self._session))
        except BackupAckPersistenceError:
            raise
        except (SQLAlchemyError, TypeError, ValueError):
            raise BackupAckPersistenceError() from None

    def _lock_completed_artifact(
        self,
        artifact_id: UUID,
    ) -> CompletedBackupArtifactRecord:
        if not isinstance(artifact_id, UUID):
            raise BackupAcknowledgementError("INVALID_ACK_ARTIFACT_ID")
        try:
            row = self._session.scalar(
                sa.select(CompletedBackupArtifactRecord)
                .where(CompletedBackupArtifactRecord.artifact_id == str(artifact_id))
                .with_for_update()
                .execution_options(autoflush=False, populate_existing=True)
            )
        except SQLAlchemyError:
            raise BackupAckPersistenceError() from None
        if row is None:
            raise BackupAckPersistenceIntegrityError("ACK_COMPLETED_ARTIFACT_NOT_FOUND")
        return row

    def _lock_conflicts(
        self,
        submission: AcknowledgementSubmission,
    ) -> tuple[BackupArtifactAcknowledgementRecord, ...]:
        try:
            return tuple(
                self._session.scalars(
                    sa.select(BackupArtifactAcknowledgementRecord)
                    .where(
                        BackupArtifactAcknowledgementRecord.ack_kind
                        == submission.kind.value,
                        sa.or_(
                            BackupArtifactAcknowledgementRecord.artifact_id
                            == str(submission.artifact_id),
                            BackupArtifactAcknowledgementRecord.idempotency_key
                            == submission.idempotency_key,
                        ),
                    )
                    .order_by(
                        BackupArtifactAcknowledgementRecord.artifact_id,
                        BackupArtifactAcknowledgementRecord.ack_kind,
                    )
                    .with_for_update()
                    .execution_options(
                        autoflush=False,
                        populate_existing=True,
                    )
                )
            )
        except SQLAlchemyError:
            raise BackupAckPersistenceError() from None

    def _existing_for_submission(
        self,
        rows: tuple[BackupArtifactAcknowledgementRecord, ...],
        *,
        submission: AcknowledgementSubmission,
        artifact: CompletedArtifactBinding,
    ) -> tuple[BackupArtifactAcknowledgement, ...]:
        # A same-kind idempotency key on another artifact is a conflict.  Do
        # not lock that second completed-artifact row after locking the first;
        # avoiding cross-artifact lock inversion keeps this boundary bounded.
        if any(row.artifact_id != str(submission.artifact_id) for row in rows):
            raise BackupAcknowledgementConflict()
        return tuple(_ack_from_row(row, artifact=artifact) for row in rows)

    def _artifact_binding(
        self,
        row: CompletedBackupArtifactRecord,
        *,
        database_now_utc: datetime,
    ) -> CompletedArtifactBinding:
        try:
            artifact = _artifact_from_row(
                row,
                database_now_utc=database_now_utc,
            )
            return CompletedArtifactBinding(
                artifact_id=artifact.artifact_id,
                manifest_sha256=artifact.manifest_sha256,
                artifact_sha256=artifact.artifact_sha256,
                completed_at_utc=artifact.completed_at_utc,
            )
        except BackupPersistenceError:
            raise BackupAckPersistenceIntegrityError() from None
        except (BackupAcknowledgementError, TypeError, ValueError):
            raise BackupAckPersistenceIntegrityError() from None

    def _ack_from_rows(
        self,
        ack_row: BackupArtifactAcknowledgementRecord,
        artifact_row: CompletedBackupArtifactRecord,
        *,
        database_now_utc: datetime,
    ) -> BackupArtifactAcknowledgement:
        artifact = self._artifact_binding(
            artifact_row,
            database_now_utc=database_now_utc,
        )
        return _ack_from_row(ack_row, artifact=artifact)


def _ack_from_row(
    row: BackupArtifactAcknowledgementRecord,
    *,
    artifact: CompletedArtifactBinding,
) -> BackupArtifactAcknowledgement:
    try:
        if row.artifact_id != str(artifact.artifact_id):
            raise BackupAckPersistenceIntegrityError()
        acknowledgement = BackupArtifactAcknowledgement(
            kind=AcknowledgementKind(row.ack_kind),
            artifact_id=_uuid(row.artifact_id),
            manifest_sha256=bytes(row.manifest_sha256),
            artifact_sha256=bytes(row.artifact_sha256),
            artifact_completed_at_utc=artifact.completed_at_utc,
            source_generation=row.source_generation,
            idempotency_key=row.idempotency_key,
            request_digest=bytes(row.request_digest),
            safe_result=AcknowledgementSafeResult(row.safe_result),
            reported_at_utc=_as_utc(row.reported_at),
            received_at_utc=_as_utc(row.received_at),
            row_version=row.row_version,
        )
        if (
            acknowledgement.manifest_sha256 != artifact.manifest_sha256
            or acknowledgement.artifact_sha256 != artifact.artifact_sha256
        ):
            raise BackupAckPersistenceIntegrityError()
        return acknowledgement
    except BackupAckPersistenceIntegrityError:
        raise
    except (BackupAcknowledgementError, TypeError, ValueError):
        raise BackupAckPersistenceIntegrityError() from None


def _ack_row(
    acknowledgement: BackupArtifactAcknowledgement,
) -> BackupArtifactAcknowledgementRecord:
    return BackupArtifactAcknowledgementRecord(
        artifact_id=str(acknowledgement.artifact_id),
        ack_kind=acknowledgement.kind.value,
        manifest_sha256=acknowledgement.manifest_sha256,
        artifact_sha256=acknowledgement.artifact_sha256,
        source_generation=acknowledgement.source_generation,
        idempotency_key=acknowledgement.idempotency_key,
        request_digest=acknowledgement.request_digest,
        safe_result=acknowledgement.safe_result.value,
        reported_at=acknowledgement.reported_at_utc,
        received_at=acknowledgement.received_at_utc,
        row_version=acknowledgement.row_version,
    )


def _read_database_utc_now(session: Session) -> datetime:
    return _as_utc(read_database_utc_value(session))


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise BackupAckPersistenceIntegrityError()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise ValueError("invalid technical identity")
    selected = UUID(value)
    if str(selected) != value or selected.int == 0:
        raise ValueError("invalid technical identity")
    return selected


__all__ = [
    "BackupAckPersistenceError",
    "BackupAckPersistenceIntegrityError",
    "BackupAckPersistenceTransactionError",
    "BackupAcknowledgementPersistenceService",
]
