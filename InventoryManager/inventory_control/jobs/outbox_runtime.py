"""Reusable ordinary-outbox worker with one committed provider boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Mapping, Protocol

from sqlalchemy.orm import Session

from inventory_control.database import ControlDatabase, read_database_utc_value

from .outbox_service import (
    ControlOutboxService,
    OutboxAuthorityVerifier,
    OutboxDispatchPermit,
    OutboxFailureCertainty,
    OutboxLease,
)


class OutboxResultDisposition(str, Enum):
    COMPLETE = "complete"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True, repr=False)
class PreparedOutboxDispatch:
    value: Any = field(default=None, repr=False)

    def __repr__(self) -> str:
        return "PreparedOutboxDispatch(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class OutboxHandlerResult:
    disposition: OutboxResultDisposition
    safe_code: str
    safe_facts_digest: bytes = field(repr=False)
    value: Any = field(default=None, repr=False)
    reason_code: str | None = None

    def __post_init__(self) -> None:
        selected = OutboxResultDisposition(self.disposition)
        object.__setattr__(self, "disposition", selected)
        if (
            not isinstance(self.safe_code, str)
            or not self.safe_code
            or not isinstance(self.safe_facts_digest, bytes)
            or len(self.safe_facts_digest) != 32
        ):
            raise ValueError("outbox handler safe result is invalid")
        if selected is OutboxResultDisposition.COMPLETE:
            if self.reason_code is not None:
                raise ValueError("complete result cannot contain a reason")
        elif not isinstance(self.reason_code, str) or not self.reason_code:
            raise ValueError("unknown result requires a reason")

    def __repr__(self) -> str:
        return (
            "OutboxHandlerResult("
            f"disposition={self.disposition.value!r}, "
            f"safe_code={self.safe_code!r}, <redacted>)"
        )


class OrdinaryOutboxHandler(Protocol):
    def prepare_dispatch(
        self,
        session: Session,
        *,
        lease: OutboxLease,
        permit: OutboxDispatchPermit,
    ) -> PreparedOutboxDispatch: ...

    def execute(
        self,
        *,
        permit: OutboxDispatchPermit,
        prepared: PreparedOutboxDispatch,
    ) -> OutboxHandlerResult: ...

    def persist_result(
        self,
        session: Session,
        *,
        permit: OutboxDispatchPermit,
        result: OutboxHandlerResult,
        completed_at: datetime,
    ) -> None: ...

    def persist_unknown(
        self,
        session: Session,
        *,
        permit: OutboxDispatchPermit,
        result: OutboxHandlerResult | None,
        reason_code: str,
        completed_at: datetime,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class OutboxWorkerRunResult:
    state: str
    event_id: str | None = None
    reason_code: str | None = None


class DurableOrdinaryOutboxWorker:
    """Claim and dispatch one ordinary event without provider I/O in a DB txn."""

    def __init__(
        self,
        *,
        database: ControlDatabase,
        authority: OutboxAuthorityVerifier,
        handlers: Mapping[str, OrdinaryOutboxHandler],
        heartbeat_recorder: Callable[[Session, datetime], object] | None,
        worker_id: str,
        result_mac_key: bytes,
        lease_duration: timedelta = timedelta(minutes=2),
        clock: Callable[[], datetime] | None = None,
        allow_sqlite_claim_for_tests: bool = False,
        service: ControlOutboxService | None = None,
    ) -> None:
        if not isinstance(database, ControlDatabase):
            raise TypeError("database must be a ControlDatabase")
        if not isinstance(worker_id, str) or not worker_id or len(worker_id) > 128:
            raise ValueError("worker_id is invalid")
        if not isinstance(result_mac_key, bytes) or len(result_mac_key) < 32:
            raise ValueError("result_mac_key must contain at least 32 bytes")
        if not isinstance(lease_duration, timedelta) or lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        if heartbeat_recorder is not None and not callable(heartbeat_recorder):
            raise TypeError("heartbeat_recorder must be callable")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._database = database
        self._authority = authority
        self._handlers = dict(handlers)
        self._heartbeat_recorder = heartbeat_recorder
        self._worker_id = worker_id
        self._result_mac_key = bytes(result_mac_key)
        self._lease_duration = lease_duration
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._allow_sqlite_claim_for_tests = allow_sqlite_claim_for_tests
        self._service = service or ControlOutboxService()

    def run_once(self) -> OutboxWorkerRunResult:
        result = self._run_once()
        if self._heartbeat_recorder is not None:
            with self._database.transaction() as session:
                self._heartbeat_recorder(
                    session,
                    observed_at=_database_now(session),
                )
        return result

    def _run_once(self) -> OutboxWorkerRunResult:
        lease = self._claim()
        if lease is None:
            return OutboxWorkerRunResult("idle")
        handler = self._handlers.get(lease.event_type)
        if handler is None:
            with self._database.transaction() as session:
                event = self._service.cancel_leased_ordinary_before_side_effect(
                    session,
                    event_id=lease.event_id,
                    worker_id=self._worker_id,
                    lease_token=lease.lease_token,
                    execution_generation=lease.execution_generation,
                    authority=self._authority,
                    reason_code="handler_not_registered",
                )
            return OutboxWorkerRunResult(
                event.state,
                lease.event_id,
                "handler_not_registered",
            )

        permit: OutboxDispatchPermit | None = None
        try:
            with self._database.transaction() as session:
                permit = self._service.authorize_side_effect(
                    session,
                    event_id=lease.event_id,
                    worker_id=self._worker_id,
                    lease_token=lease.lease_token,
                    execution_generation=lease.execution_generation,
                    authority=self._authority,
                )
                if permit is None:
                    return OutboxWorkerRunResult(
                        "recovery_quarantined",
                        lease.event_id,
                        "authority_rejected",
                    )
                prepared = handler.prepare_dispatch(
                    session,
                    lease=lease,
                    permit=permit,
                )
                if not isinstance(prepared, PreparedOutboxDispatch):
                    raise TypeError("handler returned an invalid prepared dispatch")
        except Exception:
            with self._database.transaction() as session:
                failed = self._service.record_safe_failure(
                    session,
                    event_id=lease.event_id,
                    worker_id=self._worker_id,
                    lease_token=lease.lease_token,
                    execution_generation=lease.execution_generation,
                    certainty=OutboxFailureCertainty.BEFORE_SIDE_EFFECT,
                    error_code="handler_prepare_failed",
                    authority=self._authority,
                )
            return OutboxWorkerRunResult(
                failed.state,
                lease.event_id,
                "handler_prepare_failed",
            )

        try:
            result = handler.execute(permit=permit, prepared=prepared)
            if not isinstance(result, OutboxHandlerResult):
                raise TypeError("handler returned an invalid result")
        except Exception:
            return self._persist_unknown(
                lease=lease,
                handler=handler,
                permit=permit,
                result=None,
                reason_code="provider_result_unknown",
            )

        if result.disposition is OutboxResultDisposition.UNKNOWN:
            return self._persist_unknown(
                lease=lease,
                handler=handler,
                permit=permit,
                result=result,
                reason_code=result.reason_code or "provider_result_unknown",
            )

        evidence = self._service.make_safe_result_evidence(
            permit,
            safe_code=result.safe_code,
            safe_facts_digest=result.safe_facts_digest,
            result_mac_key=self._result_mac_key,
        )
        try:
            with self._database.transaction() as session:
                completed = self._service.complete_success(
                    session,
                    event_id=lease.event_id,
                    worker_id=self._worker_id,
                    lease_token=lease.lease_token,
                    execution_generation=lease.execution_generation,
                    evidence=evidence,
                    result_mac_key=self._result_mac_key,
                    authority=self._authority,
                )
                if completed.state == "succeeded":
                    handler.persist_result(
                        session,
                        permit=permit,
                        result=result,
                        completed_at=_database_now(session),
                    )
                else:
                    handler.persist_unknown(
                        session,
                        permit=permit,
                        result=result,
                        reason_code="authority_changed_after_result",
                        completed_at=_database_now(session),
                    )
            return OutboxWorkerRunResult(completed.state, lease.event_id)
        except Exception:
            return self._persist_unknown(
                lease=lease,
                handler=handler,
                permit=permit,
                result=result,
                reason_code="result_persistence_failed",
            )

    def _persist_unknown(
        self,
        *,
        lease: OutboxLease,
        handler: OrdinaryOutboxHandler,
        permit: OutboxDispatchPermit,
        result: OutboxHandlerResult | None,
        reason_code: str,
    ) -> OutboxWorkerRunResult:
        try:
            with self._database.transaction() as session:
                handler.persist_unknown(
                    session,
                    permit=permit,
                    result=result,
                    reason_code=reason_code,
                    completed_at=_database_now(session),
                )
                event = self._service.record_unknown_outcome(
                    session,
                    event_id=lease.event_id,
                    worker_id=self._worker_id,
                    lease_token=lease.lease_token,
                    execution_generation=lease.execution_generation,
                    reason_code=reason_code,
                )
        except Exception:
            with self._database.transaction() as session:
                event = self._service.record_unknown_outcome(
                    session,
                    event_id=lease.event_id,
                    worker_id=self._worker_id,
                    lease_token=lease.lease_token,
                    execution_generation=lease.execution_generation,
                    reason_code=reason_code,
                )
        return OutboxWorkerRunResult(event.state, lease.event_id, reason_code)

    def _claim(self) -> OutboxLease | None:
        with self._database.transaction() as session:
            dialect = session.bind.dialect.name if session.bind is not None else None
            kwargs = {
                "worker_id": self._worker_id,
                "lease_duration": self._lease_duration,
                "authority": self._authority,
                "now": self._clock(),
            }
            if dialect == "mysql":
                return self._service.claim_ordinary_mysql_skip_locked(
                    session,
                    **kwargs,
                )
            if dialect == "sqlite" and self._allow_sqlite_claim_for_tests:
                return self._service.claim_ordinary_sqlite_for_test(
                    session,
                    **kwargs,
                )
            raise RuntimeError("ordinary outbox worker requires MySQL")


def _database_now(session: Session) -> datetime:
    value = read_database_utc_value(session)
    if not isinstance(value, datetime):
        raise RuntimeError("control database time is unavailable")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "DurableOrdinaryOutboxWorker",
    "OrdinaryOutboxHandler",
    "OutboxHandlerResult",
    "OutboxResultDisposition",
    "OutboxWorkerRunResult",
    "PreparedOutboxDispatch",
]
