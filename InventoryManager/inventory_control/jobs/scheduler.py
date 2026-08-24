"""Deterministic tenant fan-out for the independent background process."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.database import ControlDatabase
from inventory_control.models.foundation import Tenant

from .service import ControlJobService


@dataclass(frozen=True, slots=True)
class ScheduleCycle:
    bucket_started_at: datetime
    trigger_at: datetime
    not_after: datetime
    bucket_key: str


@dataclass(frozen=True, slots=True)
class PeriodicJobDefinition:
    job_type: str
    interval: timedelta
    not_after_window: timedelta
    resource_key: str
    payload_builder: Callable[[Session, Tenant, ScheduleCycle], dict[str, Any]]
    priority: int = 0
    max_attempts: int = 3
    idempotency_scope_builder: Callable[
        [Session, Tenant, ScheduleCycle, dict[str, Any]], str
    ] | None = None

    def __post_init__(self) -> None:
        if not self.job_type or len(self.job_type) > 96:
            raise ValueError("job_type is invalid")
        if not self.resource_key or len(self.resource_key) > 255:
            raise ValueError("resource_key is invalid")
        if self.interval < timedelta(seconds=1):
            raise ValueError("interval must be at least one second")
        if self.not_after_window <= timedelta(0):
            raise ValueError("not_after_window must be positive")
        if self.not_after_window > self.interval:
            raise ValueError("not_after_window cannot exceed interval")
        if self.priority < 0:
            raise ValueError("priority must be nonnegative")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if not callable(self.payload_builder):
            raise TypeError("payload_builder must be callable")
        if self.idempotency_scope_builder is not None and not callable(
            self.idempotency_scope_builder
        ):
            raise TypeError("idempotency_scope_builder must be callable")


@dataclass(frozen=True, slots=True)
class ScheduleGateVerdict:
    allowed: bool
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.allowed and self.reason_code is not None:
            raise ValueError("allowed verdict cannot contain a reason")
        if not self.allowed and not self.reason_code:
            raise ValueError("denied verdict requires a reason")


class TenantScheduleGate(Protocol):
    """Evaluate all current recovery, lifecycle, route, and subscription facts."""

    def evaluate(
        self,
        session: Session,
        *,
        tenant: Tenant,
        now: datetime,
    ) -> ScheduleGateVerdict: ...


@dataclass(frozen=True, slots=True)
class FanOutResult:
    evaluated_tenants: int
    enqueued_jobs: int
    reused_jobs: int
    skipped_not_due: int
    skipped_gate: int


class PeriodicTenantScheduler:
    """Create one durable job per eligible tenant and current time bucket.

    Candidate IDs are read once, then every tenant is locked and handled in a
    separate short transaction.  A restart evaluates only the current bucket;
    it never walks historical buckets to replay missed work.
    """

    def __init__(
        self,
        *,
        database: ControlDatabase,
        gate: TenantScheduleGate,
        service: ControlJobService | None = None,
    ) -> None:
        self._database = database
        self._gate = gate
        self._service = service or ControlJobService()

    def fan_out(
        self,
        definition: PeriodicJobDefinition,
        *,
        now: datetime,
    ) -> FanOutResult:
        now = _as_utc(now)
        with self._database.new_session() as session:
            tenant_ids = list(
                session.scalars(
                    sa.select(Tenant.id)
                    .where(Tenant.status == "active")
                    .order_by(Tenant.id.asc())
                )
            )

        enqueued = reused = not_due = denied = 0
        for tenant_id in tenant_ids:
            with self._database.transaction() as session:
                tenant = session.scalar(
                    sa.select(Tenant)
                    .where(Tenant.id == tenant_id)
                    .with_for_update()
                )
                if tenant is None or tenant.status != "active":
                    denied += 1
                    continue
                cycle = _current_cycle(
                    tenant_id=tenant.id,
                    job_type=definition.job_type,
                    interval=definition.interval,
                    not_after_window=definition.not_after_window,
                    now=now,
                )
                if now < cycle.trigger_at or now >= cycle.not_after:
                    not_due += 1
                    continue
                verdict = self._gate.evaluate(session, tenant=tenant, now=now)
                if not verdict.allowed:
                    denied += 1
                    continue
                payload = definition.payload_builder(session, tenant, cycle)
                if not isinstance(payload, dict):
                    raise TypeError("payload_builder must return a dict")
                scope = cycle.bucket_key
                if definition.idempotency_scope_builder is not None:
                    scope = definition.idempotency_scope_builder(
                        session,
                        tenant,
                        cycle,
                        payload,
                    )
                if (
                    not isinstance(scope, str)
                    or not scope
                    or len(scope) > 160
                    or any(ord(character) < 33 for character in scope)
                ):
                    raise ValueError("periodic idempotency scope is invalid")
                idempotency_key = f"scheduler:{definition.job_type}:{scope}"
                if len(idempotency_key) > 255:
                    raise ValueError("periodic idempotency key is too long")
                existing = session.scalar(
                    sa.select(BackgroundJobId.id).where(
                        BackgroundJobId.tenant_id == tenant.id,
                        BackgroundJobId.job_type == definition.job_type,
                        BackgroundJobId.resource_key == definition.resource_key,
                        BackgroundJobId.idempotency_key == idempotency_key,
                    )
                )
                self._service.enqueue_job(
                    session,
                    tenant_id=tenant.id,
                    tenant_access_version=tenant.access_version,
                    job_type=definition.job_type,
                    resource_key=definition.resource_key,
                    payload=payload,
                    idempotency_key=idempotency_key,
                    requested_by_type="scheduler",
                    priority=definition.priority,
                    max_attempts=definition.max_attempts,
                    available_at=cycle.trigger_at,
                    not_after=cycle.not_after,
                )
                if existing is None:
                    enqueued += 1
                else:
                    reused += 1

        return FanOutResult(
            evaluated_tenants=len(tenant_ids),
            enqueued_jobs=enqueued,
            reused_jobs=reused,
            skipped_not_due=not_due,
            skipped_gate=denied,
        )


# A narrow projection avoids loading job payloads merely to test idempotency.
from inventory_control.models.jobs import BackgroundJob as BackgroundJobId


def _current_cycle(
    *,
    tenant_id: str,
    job_type: str,
    interval: timedelta,
    not_after_window: timedelta,
    now: datetime,
) -> ScheduleCycle:
    interval_seconds = int(interval.total_seconds())
    bucket_epoch = int(now.timestamp()) // interval_seconds * interval_seconds
    bucket_started_at = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc)
    digest = hashlib.sha256(f"{job_type}\0{tenant_id}".encode("utf-8")).digest()
    offset_seconds = int.from_bytes(digest[:8], "big") % interval_seconds
    trigger_at = bucket_started_at + timedelta(seconds=offset_seconds)
    return ScheduleCycle(
        bucket_started_at=bucket_started_at,
        trigger_at=trigger_at,
        not_after=trigger_at + not_after_window,
        bucket_key=str(bucket_epoch),
    )


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("now must be a datetime")
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(timezone.utc)
