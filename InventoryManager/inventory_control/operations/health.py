"""Read-only, fixed-response health endpoint evaluation.

The HTTP adapter is intentionally kept separate.  It may expose only the
status code, fixed body, and fixed headers returned here; marker loading,
connection budgets, and rate limiting remain deployment/request-boundary
responsibilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Callable, Mapping

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.database import read_database_utc_value
from inventory_control.models.operations import PlatformOperationalSignal
from inventory_control.models.recovery import DisasterRecoveryRun

from .service import OperationalEnvironment


_OK_BODY = b'{"status":"ok"}\n'
_UNAVAILABLE_BODY = b'{"status":"unavailable"}\n'
_FIXED_HEADERS: Mapping[str, str] = MappingProxyType(
    {
        "Cache-Control": "no-store",
        "Content-Type": "application/json",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
    }
)
_MONITOR_SIGNAL_KEYS = (
    "worker.heartbeat",
    "evaluator.heartbeat",
    "notification.delivery",
)


class HostRecoveryMarkerMode(str, Enum):
    NORMAL = "normal"
    HOST_RESTORE = "host_restore"


@dataclass(frozen=True, slots=True)
class HostRecoveryMarker:
    """Already loaded, server-trusted external deployment marker."""

    mode: HostRecoveryMarkerMode
    installation_fingerprint: str
    marker_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.mode, HostRecoveryMarkerMode):
            raise TypeError("mode must be a HostRecoveryMarkerMode")
        _fingerprint(self.installation_fingerprint)
        _fingerprint(self.marker_fingerprint)


@dataclass(frozen=True, slots=True)
class HealthEndpointResult:
    """The only information a public health adapter may serialize."""

    status_code: int
    body: bytes
    headers: Mapping[str, str] = _FIXED_HEADERS

    @property
    def available(self) -> bool:
        return self.status_code == 200


class HealthTransactionRequired(RuntimeError):
    """A caller-owned read transaction is required."""


DatabaseClock = Callable[[Session], datetime]


class HealthEndpointService:
    """Evaluate the serving and background planes without side effects."""

    def __init__(
        self,
        *,
        environment: OperationalEnvironment,
        database_clock: DatabaseClock | None = None,
    ) -> None:
        if not isinstance(environment, OperationalEnvironment):
            raise TypeError("environment must be an OperationalEnvironment")
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._environment = environment
        self._database_clock = database_clock or _read_database_utc_now

    def external(
        self,
        session: Session,
        *,
        marker: HostRecoveryMarker,
    ) -> HealthEndpointResult:
        """Evaluate Web/control-DB serving and active host-restore completion."""

        _require_transaction(session)
        if not isinstance(marker, HostRecoveryMarker):
            return _unavailable()
        try:
            # The bounded scalar is the endpoint's minimal connectivity read.
            if session.scalar(sa.select(sa.literal(1))) != 1:
                return _unavailable()
            if marker.mode is HostRecoveryMarkerMode.NORMAL:
                return _ok()

            runs = tuple(
                session.scalars(
                    sa.select(DisasterRecoveryRun)
                    .where(DisasterRecoveryRun.status != "superseded")
                    .limit(2)
                )
            )
            if len(runs) != 1:
                return _unavailable()
            run = runs[0]
            if (
                run.status != "completed"
                or run.host_installation_fingerprint
                != marker.installation_fingerprint
                or run.deployment_marker_fingerprint
                != marker.marker_fingerprint
            ):
                return _unavailable()
            return _ok()
        except Exception:
            return _unavailable()

    def monitor(self, session: Session) -> HealthEndpointResult:
        """Evaluate heartbeat freshness and the notification failure latch."""

        _require_transaction(session)
        try:
            evaluated_at = _as_utc(self._database_clock(session))
            rows = tuple(
                session.scalars(
                    sa.select(PlatformOperationalSignal).where(
                        PlatformOperationalSignal.signal_key.in_(
                            _MONITOR_SIGNAL_KEYS
                        ),
                        PlatformOperationalSignal.environment
                        == self._environment.value,
                    )
                )
            )
            by_key = {row.signal_key: row for row in rows}
            if len(rows) != len(by_key) or set(by_key) != set(
                _MONITOR_SIGNAL_KEYS
            ):
                return _unavailable()

            for key in ("worker.heartbeat", "evaluator.heartbeat"):
                row = by_key[key]
                if (
                    row.effective_status != "healthy"
                    or _as_utc(row.freshness_deadline_at) < evaluated_at
                ):
                    return _unavailable()

            # Notification delivery is a latch, not a periodic canary.  A
            # healthy row stays valid while idle and is deliberately not made
            # stale by its observation deadline.
            if by_key["notification.delivery"].effective_status != "healthy":
                return _unavailable()
            return _ok()
        except Exception:
            return _unavailable()


def _ok() -> HealthEndpointResult:
    return HealthEndpointResult(status_code=200, body=_OK_BODY)


def _unavailable() -> HealthEndpointResult:
    return HealthEndpointResult(status_code=503, body=_UNAVAILABLE_BODY)


def _fingerprint(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("fingerprint must be 64 lowercase hexadecimal characters")


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("database clock must return a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _read_database_utc_now(session: Session) -> datetime:
    value = read_database_utc_value(session)
    return _as_utc(value)


def _require_transaction(session: Session) -> None:
    if not isinstance(session, Session) or not session.in_transaction():
        raise HealthTransactionRequired(
            "an explicit caller-owned read transaction is required"
        )
