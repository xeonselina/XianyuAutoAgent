"""Low-cardinality operational aggregation for the durable job queue."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import sqlalchemy as sa
from sqlalchemy.orm import Session, SessionTransactionOrigin

from inventory_control.database import read_database_utc_value
from inventory_control.models.jobs import BackgroundJob

from .service import (
    OperationalInputError,
    OperationalObservationStatus,
    OperationalResultClass,
    OperationalSignalKey,
    OperationalSignalService,
    OperationalSignalUpdate,
    OperationalTransactionRequiredError,
)


QUEUE_TERMINAL_FAILURE_STATES = (
    "failed",
    "dead_letter",
    "needs_review",
    "recovery_review",
)
DatabaseClock = Callable[[Session], datetime]


@dataclass(frozen=True, slots=True)
class QueueOperationalPolicy:
    oldest_wait_threshold: timedelta
    terminal_failure_lookback: timedelta
    terminal_failure_threshold: int

    def __post_init__(self) -> None:
        _duration(self.oldest_wait_threshold)
        _duration(self.terminal_failure_lookback)
        if (
            isinstance(self.terminal_failure_threshold, bool)
            or not isinstance(self.terminal_failure_threshold, int)
            or self.terminal_failure_threshold < 1
        ):
            raise OperationalInputError()


@dataclass(frozen=True, slots=True)
class QueueOperationalSnapshot:
    observed_at: datetime
    oldest_due_wait_seconds: int
    terminal_failures_in_window: int
    oldest_wait_update: OperationalSignalUpdate
    consecutive_failures_update: OperationalSignalUpdate


class QueueOperationalSignalAdapter:
    """Reduce queue state into two fixed aggregate operational signals."""

    def __init__(
        self,
        *,
        signals: OperationalSignalService,
        policy: QueueOperationalPolicy,
        database_clock: DatabaseClock | None = None,
    ) -> None:
        if not isinstance(signals, OperationalSignalService):
            raise OperationalInputError()
        if not isinstance(policy, QueueOperationalPolicy):
            raise OperationalInputError()
        if database_clock is not None and not callable(database_clock):
            raise OperationalInputError()
        self._signals = signals
        self._policy = policy
        self._database_clock = database_clock or _read_database_utc_now

    def record_current(self, session: Session) -> QueueOperationalSnapshot:
        _materialize_sqlite_outer_transaction(session)
        observed_at = _as_utc(self._database_clock(session))
        oldest_available_at = session.scalar(
            sa.select(sa.func.min(BackgroundJob.available_at)).where(
                BackgroundJob.status == "pending",
                BackgroundJob.available_at <= observed_at,
            )
        )
        oldest_wait_seconds = (
            0
            if oldest_available_at is None
            else max(
                0,
                int(
                    (
                        observed_at - _as_utc(oldest_available_at)
                    ).total_seconds()
                ),
            )
        )
        failure_count = int(
            session.scalar(
                sa.select(sa.func.count(BackgroundJob.id)).where(
                    BackgroundJob.status.in_(QUEUE_TERMINAL_FAILURE_STATES),
                    BackgroundJob.updated_at
                    >= observed_at - self._policy.terminal_failure_lookback,
                )
            )
            or 0
        )

        oldest_failed = (
            oldest_wait_seconds
            >= int(self._policy.oldest_wait_threshold.total_seconds())
        )
        failures_failed = (
            failure_count >= self._policy.terminal_failure_threshold
        )
        # Stable order prevents the two current-signal rows from deadlocking
        # against another evaluator transaction.
        oldest_update = self._signals.record_observation(
            session,
            signal_key=OperationalSignalKey.QUEUE_OLDEST_WAIT,
            observed_status=(
                OperationalObservationStatus.FAILURE
                if oldest_failed
                else OperationalObservationStatus.OK
            ),
            result_class=(
                OperationalResultClass.THRESHOLD_EXCEEDED
                if oldest_failed
                else OperationalResultClass.OK
            ),
            observed_at=observed_at,
        )
        failure_update = self._signals.record_observation(
            session,
            signal_key=OperationalSignalKey.QUEUE_CONSECUTIVE_FAILURES,
            observed_status=(
                OperationalObservationStatus.FAILURE
                if failures_failed
                else OperationalObservationStatus.OK
            ),
            result_class=(
                OperationalResultClass.PERSISTENT_FAILURE
                if failures_failed
                else OperationalResultClass.OK
            ),
            observed_at=observed_at,
        )
        return QueueOperationalSnapshot(
            observed_at=observed_at,
            oldest_due_wait_seconds=oldest_wait_seconds,
            terminal_failures_in_window=failure_count,
            oldest_wait_update=oldest_update,
            consecutive_failures_update=failure_update,
        )


def _duration(value: object) -> None:
    if (
        not isinstance(value, timedelta)
        or value < timedelta(seconds=1)
        or value > timedelta(days=365)
    ):
        raise OperationalInputError()


def _materialize_sqlite_outer_transaction(session: Session) -> None:
    """Keep signal-service savepoints inside the caller transaction in tests."""

    if not isinstance(session, Session):
        raise OperationalInputError()
    transaction = session.get_transaction()
    if (
        transaction is None
        or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
    ):
        raise OperationalTransactionRequiredError()
    connection = session.connection()
    if connection.dialect.name != "sqlite":
        return
    driver_connection = getattr(connection.connection, "driver_connection", None)
    if driver_connection is not None and not driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")


def _read_database_utc_now(session: Session) -> datetime:
    return _as_utc(read_database_utc_value(session))


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise OperationalInputError()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "QUEUE_TERMINAL_FAILURE_STATES",
    "QueueOperationalPolicy",
    "QueueOperationalSignalAdapter",
    "QueueOperationalSnapshot",
]
