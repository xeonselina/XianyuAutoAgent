"""Tenant-first current-read repository for D53 preview and commit fences."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.models import (
    DisasterRecoveryRun,
    Subscription,
    Tenant,
    TenantDeletionRequest,
    TenantRecoveryHold,
    TenantSuspension,
    TenantSuspensionAction,
)
from inventory_control.proofs import SubscriptionAdjustmentFences

from .adjustment_service import (
    SubscriptionAdjustmentConflictError,
    SubscriptionAdjustmentGate,
    SubscriptionAdjustmentGateError,
)


@dataclass(frozen=True, slots=True)
class SubscriptionAdjustmentSnapshot:
    fences: SubscriptionAdjustmentFences
    gate: SubscriptionAdjustmentGate
    tenant_status: str
    subscription_status: str
    subscription_expires_at: datetime


class SqlAlchemySubscriptionAdjustmentGate:
    """Re-read and lock every preview fence after the service locks tenant."""

    def __init__(self, *, expected_fences: SubscriptionAdjustmentFences) -> None:
        if not isinstance(expected_fences, SubscriptionAdjustmentFences):
            raise TypeError("expected_fences must be SubscriptionAdjustmentFences")
        self._expected = expected_fences

    def __call__(
        self,
        session: Session,
        tenant: Tenant,
        database_now: datetime,
    ) -> SubscriptionAdjustmentGate:
        if (
            not isinstance(session, Session)
            or not session.in_transaction()
            or not isinstance(tenant, Tenant)
            or not isinstance(database_now, datetime)
        ):
            raise TypeError("subscription adjustment gate inputs are invalid")
        expected = self._expected
        if (
            tenant.id != str(expected.tenant_uuid)
            or tenant.row_version != expected.tenant_row_version
            or tenant.access_version != expected.tenant_access_version
        ):
            raise SubscriptionAdjustmentConflictError(
                "tenant lifecycle revision changed"
            )
        state = _read_lifecycle_state(
            session,
            tenant=tenant,
            locking=True,
        )
        current = _fences(tenant=tenant, state=state)
        if current != expected:
            raise SubscriptionAdjustmentConflictError(
                "tenant lifecycle revision changed"
            )
        return _gate(tenant=tenant, state=state)


def read_subscription_adjustment_snapshot(
    session: Session,
    *,
    tenant_uuid: str | UUID,
) -> SubscriptionAdjustmentSnapshot:
    """Read one no-side-effect preview snapshot in canonical lock order."""

    if not isinstance(session, Session) or not session.in_transaction():
        raise TypeError("an explicit control transaction is required")
    tenant_id = str(_uuid(tenant_uuid))
    tenant = session.scalar(sa.select(Tenant).where(Tenant.id == tenant_id))
    if tenant is None:
        raise SubscriptionAdjustmentGateError("tenant is unavailable")
    state = _read_lifecycle_state(session, tenant=tenant, locking=False)
    gate = _gate(tenant=tenant, state=state)
    fences = _fences(tenant=tenant, state=state)
    subscription = state.subscription
    return SubscriptionAdjustmentSnapshot(
        fences=fences,
        gate=gate,
        tenant_status=tenant.status,
        subscription_status=subscription.status,
        subscription_expires_at=_utc(subscription.expires_at),
    )


@dataclass(frozen=True, slots=True)
class _LifecycleState:
    run: DisasterRecoveryRun
    hold: TenantRecoveryHold
    deletion: TenantDeletionRequest | None
    suspension: TenantSuspension | None
    suspension_action: TenantSuspensionAction | None
    subscription: Subscription


def _read_lifecycle_state(
    session: Session,
    *,
    tenant: Tenant,
    locking: bool,
) -> _LifecycleState:
    runs = tuple(
        session.scalars(
            _maybe_lock(
                sa.select(DisasterRecoveryRun)
                .where(DisasterRecoveryRun.current_run_marker == "current")
                .order_by(DisasterRecoveryRun.id)
                .limit(2),
                locking,
            )
        )
    )
    if len(runs) != 1:
        raise SubscriptionAdjustmentGateError(
            "current recovery run is unavailable"
        )
    run = runs[0]
    hold = session.scalar(
        _maybe_lock(
            sa.select(TenantRecoveryHold).where(
                TenantRecoveryHold.recovery_run_id == run.id,
                TenantRecoveryHold.tenant_id == tenant.id,
            ),
            locking,
        )
    )
    if hold is None:
        raise SubscriptionAdjustmentGateError(
            "current tenant recovery hold is unavailable"
        )
    deletion = session.scalar(
        _maybe_lock(
            sa.select(TenantDeletionRequest).where(
                TenantDeletionRequest.active_tenant_id == tenant.id
            ),
            locking,
        )
    )
    suspension = session.scalar(
        _maybe_lock(
            sa.select(TenantSuspension).where(
                TenantSuspension.active_tenant_id == tenant.id
            ),
            locking,
        )
    )
    suspension_action = None
    if suspension is not None:
        actions = tuple(
            session.scalars(
                _maybe_lock(
                    sa.select(TenantSuspensionAction)
                    .where(
                        TenantSuspensionAction.suspension_id == suspension.id
                    )
                    .order_by(
                        TenantSuspensionAction.generation.desc(),
                        TenantSuspensionAction.id,
                    )
                    .limit(2),
                    locking,
                )
            )
        )
        if not actions:
            raise SubscriptionAdjustmentGateError(
                "current suspension action is unavailable"
            )
        if len(actions) > 1 and actions[0].generation == actions[1].generation:
            raise SubscriptionAdjustmentGateError(
                "current suspension action is ambiguous"
            )
        suspension_action = actions[0]
    subscription = session.scalar(
        _maybe_lock(
            sa.select(Subscription).where(Subscription.tenant_id == tenant.id),
            locking,
        )
    )
    if subscription is None:
        raise SubscriptionAdjustmentGateError(
            "tenant subscription is unavailable"
        )
    return _LifecycleState(
        run=run,
        hold=hold,
        deletion=deletion,
        suspension=suspension,
        suspension_action=suspension_action,
        subscription=subscription,
    )


def _fences(
    *,
    tenant: Tenant,
    state: _LifecycleState,
) -> SubscriptionAdjustmentFences:
    deletion = state.deletion
    suspension = state.suspension
    action = state.suspension_action
    return SubscriptionAdjustmentFences(
        tenant_uuid=UUID(tenant.id),
        tenant_row_version=tenant.row_version,
        tenant_access_version=tenant.access_version,
        subscription_uuid=UUID(state.subscription.id),
        subscription_row_version=state.subscription.row_version,
        recovery_run_uuid=UUID(state.run.id),
        recovery_run_row_version=state.run.row_version,
        recovery_hold_uuid=UUID(state.hold.id),
        recovery_hold_revision=state.hold.hold_revision,
        recovery_hold_row_version=state.hold.row_version,
        deletion_request_uuid=UUID(deletion.id) if deletion is not None else None,
        deletion_request_revision=(
            deletion.request_revision if deletion is not None else None
        ),
        deletion_row_version=(
            deletion.row_version if deletion is not None else None
        ),
        suspension_uuid=UUID(suspension.id) if suspension is not None else None,
        suspension_row_version=(
            suspension.row_version if suspension is not None else None
        ),
        suspension_generation=(
            suspension.barrier_generation if suspension is not None else None
        ),
        suspension_action_uuid=UUID(action.id) if action is not None else None,
        suspension_action_row_version=(
            action.row_version if action is not None else None
        ),
    )


def _gate(
    *,
    tenant: Tenant,
    state: _LifecycleState,
) -> SubscriptionAdjustmentGate:
    suspension = state.suspension
    action = state.suspension_action
    barrier_complete = bool(
        suspension is not None
        and suspension.state == "active"
        and action is not None
        and action.direction == "freeze"
        and action.state == "succeeded"
        and action.generation == suspension.barrier_generation
    )
    return SubscriptionAdjustmentGate(
        recovery_run_completed=state.run.status == "completed",
        tenant_hold_released=state.hold.state == "released",
        no_unresolved_deletion=state.deletion is None,
        suspension_state=(suspension.state if suspension is not None else None),
        suspension_barrier_complete=barrier_complete,
    )


def _maybe_lock(statement, locking: bool):
    return statement.with_for_update() if locking else statement


def _uuid(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            pass
    raise ValueError("tenant_uuid is invalid")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "SqlAlchemySubscriptionAdjustmentGate",
    "SubscriptionAdjustmentSnapshot",
    "read_subscription_adjustment_snapshot",
]
