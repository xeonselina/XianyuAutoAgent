"""Shared current-control-fact gate for schedulers and durable workers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.database import read_database_utc_datetime
from inventory_control.domain import TenantGateFacts, TenantStatus, reduce_tenant_gate
from inventory_control.models.foundation import Tenant, TenantDatabase
from inventory_control.models.jobs import BackgroundJob
from inventory_control.models.deletion import TenantDeletionRequest
from inventory_control.models.suspensions import TenantSuspension
from inventory_control.models.subscriptions import Subscription

from .contracts import AuthorityVerdict
from .scheduler import ScheduleGateVerdict


class RecoveryHoldProbe(Protocol):
    def __call__(
        self,
        session: Session,
        *,
        tenant_id: str,
        now: datetime,
    ) -> bool:
        """Return true only when the current recovery hold is released."""


class SuspensionProbe(Protocol):
    def __call__(
        self,
        session: Session,
        *,
        tenant_id: str,
        now: datetime,
    ) -> bool:
        """Return true when an unresolved suspension aggregate exists."""


class DeletionProbe(Protocol):
    def __call__(
        self,
        session: Session,
        *,
        tenant_id: str,
        now: datetime,
    ) -> bool:
        """Return true when a deletion phase blocks normal work."""


class ControlLifecycleGateProbes:
    """Lock current deletion and suspension aggregates for normal jobs."""

    def unresolved_deletion(
        self,
        session: Session,
        *,
        tenant_id: str,
        now: datetime,
    ) -> bool:
        _require_probe_inputs(session, tenant_id=tenant_id, now=now)
        rows = tuple(
            session.scalars(
                sa.select(TenantDeletionRequest)
                .where(TenantDeletionRequest.active_tenant_id == tenant_id)
                .limit(2)
                .execution_options(autoflush=False, populate_existing=True)
                .with_for_update()
            )
        )
        if len(rows) > 1:
            raise RuntimeError("tenant deletion authority is inconsistent")
        if not rows:
            return False
        status = rows[0].status
        if status == "pending_review":
            return False
        if status in {
            "cooling_off",
            "committing",
            "awaiting_offsite_ack",
            "releasing_claims",
            "dropping",
            "failed",
        }:
            return True
        raise RuntimeError("tenant deletion authority is inconsistent")

    def unresolved_suspension(
        self,
        session: Session,
        *,
        tenant_id: str,
        now: datetime,
    ) -> bool:
        _require_probe_inputs(session, tenant_id=tenant_id, now=now)
        rows = tuple(
            session.scalars(
                sa.select(TenantSuspension)
                .where(TenantSuspension.active_tenant_id == tenant_id)
                .limit(2)
                .execution_options(autoflush=False, populate_existing=True)
                .with_for_update()
            )
        )
        if len(rows) > 1:
            raise RuntimeError("tenant suspension authority is inconsistent")
        return bool(rows)


@dataclass(frozen=True, slots=True)
class CurrentTenantAuthority:
    tenant: Tenant | None
    allowed: bool
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class LockedTenantAuthority:
    """Current tenant facts whose source rows remain locked by ``session``."""

    tenant: Tenant | None
    presented_access_version: int | None
    recovery_released: bool | None
    deletion_open: bool | None
    suspension_open: bool | None
    subscription: Subscription | None
    route: TenantDatabase | None
    failure_reason_code: str | None = None


DatabaseClock = Callable[[Session], datetime]


class ControlTenantGateReader:
    """Lock and reduce the current authority without entering a tenant schema.

    Recovery and suspension probes are mandatory because silently treating
    missing lifecycle tables as released would create a fail-open deployment.
    Each probe is responsible for locking its own current aggregate in the
    documented tenant-first order.
    """

    def __init__(
        self,
        *,
        recovery_hold_released: RecoveryHoldProbe,
        unresolved_deletion: DeletionProbe,
        unresolved_suspension: SuspensionProbe,
        database_clock: DatabaseClock | None = None,
    ) -> None:
        if not callable(recovery_hold_released):
            raise TypeError("recovery_hold_released probe is required")
        if not callable(unresolved_deletion):
            raise TypeError("unresolved_deletion probe is required")
        if not callable(unresolved_suspension):
            raise TypeError("unresolved_suspension probe is required")
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._recovery_hold_released = recovery_hold_released
        self._unresolved_deletion = unresolved_deletion
        self._unresolved_suspension = unresolved_suspension
        self._database_clock = database_clock or read_database_utc_datetime

    def read(
        self,
        session: Session,
        *,
        tenant_id: str,
        presented_access_version: int | None,
        now: datetime,
        tenant_already_locked: Tenant | None = None,
    ) -> CurrentTenantAuthority:
        _as_utc(now)
        locked = self.lock_current(
            session,
            tenant_id=tenant_id,
            presented_access_version=presented_access_version,
            tenant_already_locked=tenant_already_locked,
        )
        evaluated_at = self.database_now(session)
        return self.evaluate_locked(locked, now=evaluated_at)

    def lock_current(
        self,
        session: Session,
        *,
        tenant_id: str,
        presented_access_version: int | None,
        tenant_already_locked: Tenant | None = None,
    ) -> LockedTenantAuthority:
        """Acquire the complete authority prefix without deciding by time.

        The caller may safely lock a job/outbox row after this returns.  The
        final database time must be read only after that last row lock and
        supplied to :meth:`evaluate_locked`.
        """

        tenant = tenant_already_locked
        if tenant is None:
            tenant = session.scalar(
                sa.select(Tenant).where(Tenant.id == tenant_id).with_for_update()
            )
        elif tenant.id != tenant_id:
            raise ValueError("locked tenant does not match requested tenant")
        if tenant is None:
            return LockedTenantAuthority(
                tenant=None,
                presented_access_version=presented_access_version,
                recovery_released=None,
                deletion_open=None,
                suspension_open=None,
                subscription=None,
                route=None,
                failure_reason_code="tenant_not_found",
            )

        try:
            # Probes currently need a timestamp while acquiring their own
            # current rows.  It is not the final authorization time; the final
            # reducer runs only after every authority row and the job/event row
            # are locked.
            probe_time = self.database_now(session)
            recovery_released = self._recovery_hold_released(
                session,
                tenant_id=tenant.id,
                now=probe_time,
            )
            deletion_open = self._unresolved_deletion(
                session,
                tenant_id=tenant.id,
                now=probe_time,
            )
            suspension_open = self._unresolved_suspension(
                session,
                tenant_id=tenant.id,
                now=probe_time,
            )
        except Exception:
            return LockedTenantAuthority(
                tenant=tenant,
                presented_access_version=presented_access_version,
                recovery_released=None,
                deletion_open=None,
                suspension_open=None,
                subscription=None,
                route=None,
                failure_reason_code="tenant_authority_unavailable",
            )
        if (
            not isinstance(recovery_released, bool)
            or not isinstance(deletion_open, bool)
            or not isinstance(suspension_open, bool)
        ):
            return LockedTenantAuthority(
                tenant=tenant,
                presented_access_version=presented_access_version,
                recovery_released=None,
                deletion_open=None,
                suspension_open=None,
                subscription=None,
                route=None,
                failure_reason_code="tenant_authority_unavailable",
            )
        subscription = session.scalar(
            sa.select(Subscription)
            .where(Subscription.tenant_id == tenant.id)
            .with_for_update()
        )
        route = session.scalar(
            sa.select(TenantDatabase)
            .where(TenantDatabase.tenant_id == tenant.id)
            .with_for_update()
        )
        return LockedTenantAuthority(
            tenant=tenant,
            presented_access_version=presented_access_version,
            recovery_released=recovery_released,
            deletion_open=deletion_open,
            suspension_open=suspension_open,
            subscription=subscription,
            route=route,
        )

    def evaluate_locked(
        self,
        locked: LockedTenantAuthority,
        *,
        now: datetime,
    ) -> CurrentTenantAuthority:
        evaluated_at = _as_utc(now)
        tenant = locked.tenant
        if tenant is None:
            return CurrentTenantAuthority(None, False, "tenant_not_found")
        if locked.failure_reason_code is not None:
            return CurrentTenantAuthority(tenant, False, locked.failure_reason_code)
        if (
            locked.recovery_released is None
            or locked.deletion_open is None
            or locked.suspension_open is None
        ):
            return CurrentTenantAuthority(tenant, False, "tenant_authority_unavailable")
        if locked.deletion_open:
            return CurrentTenantAuthority(tenant, False, "TENANT_DELETION_IN_PROGRESS")
        try:
            tenant_status = TenantStatus(tenant.status)
        except (TypeError, ValueError):
            return CurrentTenantAuthority(tenant, False, "tenant_state_invalid")
        decision = reduce_tenant_gate(
            TenantGateFacts(
                tenant_status=tenant_status,
                current_access_version=tenant.access_version,
                presented_access_version=locked.presented_access_version,
                recovery_hold_released=locked.recovery_released,
                unresolved_suspension=locked.suspension_open,
                subscription_expires_at=(
                    _as_utc(locked.subscription.expires_at)
                    if locked.subscription is not None
                    else None
                ),
                evaluated_at=evaluated_at,
            )
        )
        if not decision.allows_business_route:
            return CurrentTenantAuthority(
                tenant=tenant,
                allowed=False,
                reason_code=decision.error_code,
            )

        if locked.route is None or locked.route.status != "ready":
            return CurrentTenantAuthority(tenant, False, "tenant_route_not_ready")
        return CurrentTenantAuthority(
            tenant=tenant,
            allowed=True,
            reason_code=None,
        )

    def database_now(self, session: Session) -> datetime:
        return _as_utc(self._database_clock(session))


class DurableWorkerAuthority:
    def __init__(self, reader: ControlTenantGateReader) -> None:
        self._reader = reader

    def evaluate(
        self,
        session: Session,
        *,
        job: BackgroundJob,
        phase: str,
        now: datetime,
    ) -> AuthorityVerdict:
        locked = self.lock_current_job_authority(
            session,
            job=job,
            phase=phase,
        )
        return self.evaluate_locked_job_authority(
            session,
            locked_authority=locked,
            job=job,
            phase=phase,
            now=self._reader.database_now(session),
        )

    def lock_current_job_authority(
        self,
        session: Session,
        *,
        job: BackgroundJob,
        phase: str,
    ) -> LockedTenantAuthority:
        if phase not in {
            "claim",
            "after_claim",
            "before_tenant_context",
            "heartbeat",
            "before_provider_boundary",
            "before_provider_call",
        }:
            raise ValueError("worker phase is invalid")
        return self._reader.lock_current(
            session,
            tenant_id=job.tenant_id,
            presented_access_version=job.tenant_access_version,
        )

    def evaluate_locked_job_authority(
        self,
        session: Session,
        *,
        locked_authority: LockedTenantAuthority,
        job: BackgroundJob,
        phase: str,
        now: datetime,
    ) -> AuthorityVerdict:
        del session
        if phase not in {
            "claim",
            "after_claim",
            "before_tenant_context",
            "heartbeat",
            "before_provider_boundary",
            "before_provider_call",
        }:
            return AuthorityVerdict(False, "worker_phase_invalid")
        if (
            locked_authority.tenant is not None
            and locked_authority.tenant.id != job.tenant_id
        ):
            return AuthorityVerdict(False, "tenant_authority_unavailable")
        current = self._reader.evaluate_locked(locked_authority, now=now)
        if current.allowed:
            return AuthorityVerdict(True)
        return AuthorityVerdict(
            False,
            current.reason_code or "tenant_gate_denied",
            recovery_review=current.reason_code == "TENANT_RECOVERY_IN_PROGRESS",
        )


class DurableScheduleGate:
    def __init__(self, reader: ControlTenantGateReader) -> None:
        self._reader = reader

    def evaluate(
        self,
        session: Session,
        *,
        tenant: Tenant,
        now: datetime,
    ) -> ScheduleGateVerdict:
        current = self._reader.read(
            session,
            tenant_id=tenant.id,
            presented_access_version=tenant.access_version,
            now=now,
            tenant_already_locked=tenant,
        )
        if current.allowed:
            return ScheduleGateVerdict(True)
        return ScheduleGateVerdict(
            False,
            current.reason_code or "tenant_gate_denied",
        )


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("time must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _require_probe_inputs(
    session: Session,
    *,
    tenant_id: str,
    now: datetime,
) -> None:
    if (
        not isinstance(session, Session)
        or not session.in_transaction()
        or not isinstance(tenant_id, str)
        or not tenant_id
        or not isinstance(now, datetime)
    ):
        raise TypeError("lifecycle probe inputs are invalid")
