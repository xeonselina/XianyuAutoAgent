"""Narrow adapter from backup acknowledgement freshness to D49 signals.

The adapter has no NAS, cloud-drive, provider, filesystem, or network boundary.
It records both fixed signals through the existing caller-owned operational
transaction and never lets either acknowledgement stream stand in for the
other.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from inventory_control.backups.acknowledgements import (
    AcknowledgementFreshness,
    BackupFreshnessSnapshot,
    FreshnessState,
)
from inventory_control.transactions import require_caller_transaction

from .service import (
    OperationalInputError,
    OperationalObservationStatus,
    OperationalResultClass,
    OperationalSignalKey,
    OperationalSignalService,
    OperationalSignalUpdate,
    OperationalTransactionRequiredError,
)


@dataclass(frozen=True, slots=True)
class BackupFreshnessSignalUpdates:
    """The two independently persisted D49 signal updates."""

    backup_verified_freshness: OperationalSignalUpdate
    cloud_sync_freshness: OperationalSignalUpdate

    def __post_init__(self) -> None:
        if (
            not isinstance(
                self.backup_verified_freshness,
                OperationalSignalUpdate,
            )
            or self.backup_verified_freshness.signal.signal_key
            is not OperationalSignalKey.BACKUP_VERIFIED_FRESHNESS
            or not isinstance(
                self.cloud_sync_freshness,
                OperationalSignalUpdate,
            )
            or self.cloud_sync_freshness.signal.signal_key
            is not OperationalSignalKey.CLOUD_SYNC_FRESHNESS
        ):
            raise OperationalInputError()


class BackupFreshnessSignalAdapter:
    """Map one acknowledgement snapshot into two fixed current signals."""

    __slots__ = ("_signals",)

    def __init__(self, *, signals: OperationalSignalService) -> None:
        if not isinstance(signals, OperationalSignalService):
            raise OperationalInputError()
        self._signals = signals

    def record_snapshot(
        self,
        session: Session,
        *,
        freshness: BackupFreshnessSnapshot,
    ) -> BackupFreshnessSignalUpdates:
        """Record both streams in the same caller-owned transaction.

        The method deliberately performs no commit or rollback.  The fixed
        backup-then-cloud lock order is shared by every call, and an exception
        from either write escapes so the caller's transaction rolls back both.
        """

        if not isinstance(freshness, BackupFreshnessSnapshot):
            raise OperationalInputError()
        require_caller_transaction(
            session,
            OperationalTransactionRequiredError,
            invalid_session_error=OperationalInputError,
        )
        backup_status, backup_result = _observation(freshness.latest_verified_backup)
        sync_status, sync_result = _observation(freshness.latest_cloud_sync)
        backup_update = self._signals.record_observation(
            session,
            signal_key=OperationalSignalKey.BACKUP_VERIFIED_FRESHNESS,
            observed_status=backup_status,
            result_class=backup_result,
            observed_at=freshness.latest_verified_backup.evaluated_at_utc,
        )
        sync_update = self._signals.record_observation(
            session,
            signal_key=OperationalSignalKey.CLOUD_SYNC_FRESHNESS,
            observed_status=sync_status,
            result_class=sync_result,
            observed_at=freshness.latest_cloud_sync.evaluated_at_utc,
        )
        return BackupFreshnessSignalUpdates(
            backup_verified_freshness=backup_update,
            cloud_sync_freshness=sync_update,
        )


def _observation(
    freshness: AcknowledgementFreshness,
) -> tuple[OperationalObservationStatus, OperationalResultClass]:
    if not isinstance(freshness, AcknowledgementFreshness):
        raise OperationalInputError()
    if freshness.state is FreshnessState.FRESH:
        return (
            OperationalObservationStatus.OK,
            OperationalResultClass.VERIFIED,
        )
    if freshness.state is FreshnessState.MISSING:
        return (
            OperationalObservationStatus.FAILURE,
            OperationalResultClass.UNAVAILABLE,
        )
    if freshness.state is FreshnessState.STALE:
        return (
            OperationalObservationStatus.FAILURE,
            OperationalResultClass.THRESHOLD_EXCEEDED,
        )
    raise OperationalInputError()


__all__ = [
    "BackupFreshnessSignalAdapter",
    "BackupFreshnessSignalUpdates",
]
