"""Independent, bounded freshness evaluation for current operational signals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from sqlalchemy.orm import Session

from inventory_control.database import ControlDatabase, read_database_utc_value

from .service import (
    OperationalEffectiveStatus,
    OperationalSignalKey,
    OperationalSignalNotFoundError,
    OperationalSignalService,
)


DatabaseClock = Callable[[Session], datetime]


@dataclass(frozen=True, slots=True)
class OperationalFreshnessResult:
    configured_signals: int
    evaluated_signals: int
    missing_signals: tuple[OperationalSignalKey, ...]
    healthy_signals: int
    degraded_signals: int
    unhealthy_signals: int
    unknown_signals: int
    lifecycle_events: int


class OperationalFreshnessEvaluator:
    """Advance explicitly configured signal freshness in short transactions.

    Notification delivery is an event-driven latch and is therefore rejected
    from this periodic evaluator.  An idle healthy notification channel must
    not become stale merely because there was no event to deliver.
    """

    def __init__(
        self,
        *,
        database: ControlDatabase,
        signals: OperationalSignalService,
        signal_keys: Iterable[OperationalSignalKey],
        database_clock: DatabaseClock | None = None,
    ) -> None:
        if not isinstance(database, ControlDatabase):
            raise TypeError("control database is required")
        if not isinstance(signals, OperationalSignalService):
            raise TypeError("operational signal service is required")
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        try:
            keys = tuple(signal_keys)
        except TypeError:
            raise TypeError("signal_keys must be iterable") from None
        if (
            not keys
            or any(not isinstance(key, OperationalSignalKey) for key in keys)
            or len(keys) != len(set(keys))
            or OperationalSignalKey.NOTIFICATION_DELIVERY in keys
        ):
            raise ValueError("freshness signal keys are invalid")
        self._database = database
        self._signals = signals
        self._signal_keys = keys
        self._database_clock = database_clock or _read_database_utc_now

    def run_once(self) -> OperationalFreshnessResult:
        missing: list[OperationalSignalKey] = []
        counts = {status: 0 for status in OperationalEffectiveStatus}
        events = 0
        evaluated = 0
        for key in self._signal_keys:
            try:
                with self._database.transaction() as session:
                    evaluated_at = _as_utc(self._database_clock(session))
                    update = self._signals.evaluate_freshness(
                        session,
                        signal_key=key,
                        evaluated_at=evaluated_at,
                    )
            except OperationalSignalNotFoundError:
                missing.append(key)
                continue
            evaluated += 1
            counts[update.signal.effective_status] += 1
            events += int(update.lifecycle_event is not None)

        return OperationalFreshnessResult(
            configured_signals=len(self._signal_keys),
            evaluated_signals=evaluated,
            missing_signals=tuple(missing),
            healthy_signals=counts[OperationalEffectiveStatus.HEALTHY],
            degraded_signals=counts[OperationalEffectiveStatus.DEGRADED],
            unhealthy_signals=counts[OperationalEffectiveStatus.UNHEALTHY],
            unknown_signals=counts[OperationalEffectiveStatus.UNKNOWN],
            lifecycle_events=events,
        )


def _read_database_utc_now(session: Session) -> datetime:
    return _as_utc(read_database_utc_value(session))


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError("control database did not return a timestamp")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "OperationalFreshnessEvaluator",
    "OperationalFreshnessResult",
]
