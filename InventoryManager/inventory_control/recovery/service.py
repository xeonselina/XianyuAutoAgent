"""Locking current reads for D58 recovery authority and tenant holds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.database import read_database_utc_value
from inventory_control.domain.tenant_gate import (
    EffectiveTenantGate,
    TenantGateDecision,
    TenantGateFacts,
    TenantStatus,
    reduce_tenant_gate,
)
from inventory_control.models.foundation import Tenant
from inventory_control.models.deletion import TenantDeletionRequest
from inventory_control.models.recovery import (
    DisasterRecoveryRun,
    TenantRecoveryHold,
)
from inventory_control.models.subscriptions import Subscription
from inventory_control.models.suspensions import TenantSuspension


DatabaseClock = Callable[[Session], datetime]


class RecoveryAuthorityError(RuntimeError):
    """A stable fail-closed recovery authority rejection."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RecoveryAuthorityTransactionError(RecoveryAuthorityError):
    pass


@dataclass(frozen=True, slots=True)
class CurrentRecoveryAuthority:
    recovery_run_uuid: str
    kind: str
    status: str
    row_version: int
    host_installation_fingerprint: str
    deployment_marker_fingerprint: str


@dataclass(frozen=True, slots=True)
class ReleasedRecoveryHold:
    hold_uuid: str
    recovery_run_uuid: str
    tenant_uuid: str
    database_uuid: str
    hold_revision: int
    idempotent: bool


class RecoveryAuthorityService:
    """Read the single current recovery epoch in tenant-first lock order.

    Callers lock ``Tenant`` first.  This service then locks the current run,
    the exact run/tenant hold, and finally the subscription.  The same callable
    can be supplied directly to :class:`SessionService`.
    """

    def __init__(self, *, database_clock: DatabaseClock | None = None) -> None:
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._database_clock = database_clock or _read_database_utc_now

    def __call__(
        self,
        session: Session,
        tenant: Tenant,
        _request_now: datetime,
    ) -> TenantGateDecision:
        return self.read_tenant_gate(session, tenant=tenant)

    def read_current_completed(
        self,
        session: Session,
    ) -> CurrentRecoveryAuthority:
        """Lock and return the current completed run, or reject closed."""

        _require_transaction(session)
        run = self._lock_current_run(session)
        if run is None or run.status != "completed":
            raise RecoveryAuthorityError("RECOVERY_RUN_NOT_COMPLETED")
        return _authority(run)

    def is_current_hold_released(
        self,
        session: Session,
        *,
        tenant_id: str,
        now: datetime,
    ) -> bool:
        """Probe the current run/hold in the shared tenant-first lock order.

        ``now`` is accepted for the worker/scheduler probe protocol; recovery
        authority itself is version/state based and never trusts that value.
        """

        _require_transaction(session)
        _uuid(tenant_id, "tenant_id")
        if not isinstance(now, datetime):
            raise TypeError("now must be a datetime")
        run = self._lock_current_run(session)
        if run is None or run.status != "completed":
            return False
        hold = session.scalar(
            sa.select(TenantRecoveryHold)
            .where(
                TenantRecoveryHold.recovery_run_id == run.id,
                TenantRecoveryHold.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        return bool(hold is not None and hold.state == "released")

    def read_tenant_gate(
        self,
        session: Session,
        *,
        tenant: Tenant,
        presented_access_version: int | None = None,
    ) -> TenantGateDecision:
        """Reduce current run, hold, lifecycle, and subscription facts."""

        _require_transaction(session)
        if not isinstance(tenant, Tenant):
            raise TypeError("tenant must be a locked Tenant")

        run = self._lock_current_run(session)
        hold = (
            session.scalar(
                sa.select(TenantRecoveryHold)
                .where(
                    TenantRecoveryHold.recovery_run_id == run.id,
                    TenantRecoveryHold.tenant_id == tenant.id,
                )
                .with_for_update()
            )
            if run is not None
            else None
        )
        deletion_rows = tuple(
            session.scalars(
                sa.select(TenantDeletionRequest)
                .where(
                    TenantDeletionRequest.active_tenant_id == tenant.id
                )
                .limit(2)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
        )
        suspension_rows = tuple(
            session.scalars(
                sa.select(TenantSuspension)
                .where(TenantSuspension.active_tenant_id == tenant.id)
                .limit(2)
                .execution_options(populate_existing=True)
                .with_for_update()
            )
        )
        subscription = session.scalar(
            sa.select(Subscription)
            .where(Subscription.tenant_id == tenant.id)
            .with_for_update()
        )
        evaluated_at = _as_utc(self._database_clock(session))

        try:
            tenant_status = _effective_tenant_status(
                tenant.status,
                deletion_rows,
            )
        except (TypeError, ValueError):
            return TenantGateDecision(
                EffectiveTenantGate.INVALID_STATE,
                "TENANT_STATE_INVALID",
            )

        hold_released = bool(
            run is not None
            and run.status == "completed"
            and hold is not None
            and hold.state == "released"
        )
        unresolved_suspension = bool(suspension_rows) or tenant_status in {
            TenantStatus.SUSPENDING,
            TenantStatus.SUSPENDED,
            TenantStatus.RESUMING,
        }
        return reduce_tenant_gate(
            TenantGateFacts(
                tenant_status=tenant_status,
                current_access_version=tenant.access_version,
                presented_access_version=presented_access_version,
                recovery_hold_released=hold_released,
                unresolved_suspension=unresolved_suspension,
                subscription_expires_at=(
                    _as_utc(subscription.expires_at)
                    if subscription is not None
                    else None
                ),
                evaluated_at=evaluated_at,
            )
        )
    def create_released_baseline_hold(
        self,
        session: Session,
        *,
        tenant: Tenant,
        database_uuid: str | UUID,
        expected_dml_login_state_version: int,
        dml_convergence_status: str,
        registration_commit_uuid: str | UUID | None = None,
    ) -> ReleasedRecoveryHold:
        """Create the released hold anchor used by a new tenant final commit.

        This method does not increment ``Tenant.access_version``: the hold is
        born released and no prior tenant session or route can exist.  A later
        host-restore hold installation and release are separate transitions.
        """

        _require_transaction(session)
        if not isinstance(tenant, Tenant):
            raise TypeError("tenant must be a locked Tenant")
        database_id = str(_uuid(database_uuid, "database_uuid"))
        commit_id = (
            str(_uuid(registration_commit_uuid, "registration_commit_uuid"))
            if registration_commit_uuid is not None
            else None
        )
        if (
            isinstance(expected_dml_login_state_version, bool)
            or not isinstance(expected_dml_login_state_version, int)
            or expected_dml_login_state_version < 1
        ):
            raise ValueError("expected_dml_login_state_version must be positive")
        if dml_convergence_status not in {"active", "locked"}:
            raise ValueError("baseline DML convergence must be active or locked")

        run = self._lock_current_run(session)
        if run is None or run.status != "completed":
            raise RecoveryAuthorityError("RECOVERY_RUN_NOT_COMPLETED")
        existing = session.scalar(
            sa.select(TenantRecoveryHold)
            .where(
                TenantRecoveryHold.recovery_run_id == run.id,
                TenantRecoveryHold.tenant_id == tenant.id,
            )
            .with_for_update()
        )
        if existing is not None:
            expected_anchor_revision = 1 if commit_id is not None else None
            if (
                existing.state != "released"
                or existing.database_uuid != database_id
                or existing.created_from_registration_commit_uuid != commit_id
                or existing.initial_hold_revision != expected_anchor_revision
            ):
                raise RecoveryAuthorityError("RECOVERY_HOLD_ANCHOR_CONFLICT")
            return _released(existing, idempotent=True)

        now = _as_utc(self._database_clock(session))
        hold = TenantRecoveryHold(
            recovery_run_id=run.id,
            tenant_id=tenant.id,
            database_uuid=database_id,
            created_from_registration_commit_uuid=commit_id,
            initial_hold_revision=1 if commit_id is not None else None,
            state="released",
            hold_revision=1,
            snapshot_underlying_status=tenant.status,
            snapshot_access_version=tenant.access_version,
            expected_dml_login_state_version=expected_dml_login_state_version,
            dml_convergence_status=dml_convergence_status,
            held_at=now,
            released_at=now,
            row_version=1,
            created_at=now,
            updated_at=now,
        )
        session.add(hold)
        session.flush()
        return _released(hold, idempotent=False)

    def _lock_current_run(
        self,
        session: Session,
    ) -> DisasterRecoveryRun | None:
        return session.scalar(
            sa.select(DisasterRecoveryRun)
            .where(DisasterRecoveryRun.current_run_marker == "current")
            .with_for_update()
        )


def _effective_tenant_status(
    projected_status: object,
    deletion_rows: tuple[TenantDeletionRequest, ...],
) -> TenantStatus:
    if len(deletion_rows) > 1:
        raise ValueError("multiple active deletion requests")
    projected = TenantStatus(projected_status)
    if not deletion_rows:
        return projected
    deletion_status = deletion_rows[0].status
    if deletion_status == "pending_review":
        return projected
    if deletion_status == "cooling_off":
        return TenantStatus.DELETION_COOLING_OFF
    if deletion_status in {
        "committing",
        "awaiting_offsite_ack",
        "releasing_claims",
        "dropping",
        "failed",
    }:
        return TenantStatus.DELETION_COMMITTING
    raise ValueError("active deletion request has invalid status")


def _authority(run: DisasterRecoveryRun) -> CurrentRecoveryAuthority:
    return CurrentRecoveryAuthority(
        recovery_run_uuid=run.id,
        kind=run.kind,
        status=run.status,
        row_version=run.row_version,
        host_installation_fingerprint=run.host_installation_fingerprint,
        deployment_marker_fingerprint=run.deployment_marker_fingerprint,
    )


def _released(
    hold: TenantRecoveryHold,
    *,
    idempotent: bool,
) -> ReleasedRecoveryHold:
    return ReleasedRecoveryHold(
        hold_uuid=hold.id,
        recovery_run_uuid=hold.recovery_run_id,
        tenant_uuid=hold.tenant_id,
        database_uuid=hold.database_uuid,
        hold_revision=hold.hold_revision,
        idempotent=idempotent,
    )


def _read_database_utc_now(session: Session) -> datetime:
    return _as_utc(read_database_utc_value(session))


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise RecoveryAuthorityTransactionError("DATABASE_CLOCK_INVALID")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _uuid(value: object, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            pass
    raise ValueError(f"{field_name} must be a UUID")


def _require_transaction(session: Session) -> None:
    if not isinstance(session, Session) or not session.in_transaction():
        raise RecoveryAuthorityTransactionError(
            "CALLER_TRANSACTION_REQUIRED"
        )
