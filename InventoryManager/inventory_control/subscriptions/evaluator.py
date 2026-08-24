"""Current-time subscription and tenant status projection evaluator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.database import read_database_utc_value
from inventory_control.models.foundation import Tenant
from inventory_control.models.deletion import TenantDeletionRequest
from inventory_control.models.recovery import (
    DisasterRecoveryRun,
    TenantRecoveryHold,
)
from inventory_control.models.subscriptions import Subscription
from inventory_control.models.suspensions import (
    TenantSuspension,
    TenantSuspensionAction,
)


class SubscriptionProjectionError(RuntimeError):
    pass


class SubscriptionProjectionTransactionError(SubscriptionProjectionError):
    pass


class SubscriptionProjectionConflictError(SubscriptionProjectionError):
    pass


class SubscriptionProjectionAuthorityError(SubscriptionProjectionError):
    pass


DatabaseClock = Callable[[Session], datetime]


@dataclass(frozen=True, slots=True)
class SubscriptionProjectionLifecycleLocks:
    recovery_run_uuid: str
    recovery_hold_uuid: str
    deletion_request_uuid: str | None
    suspension_uuid: str | None
    suspension_action_uuid: str | None


class SubscriptionProjectionLifecycleLocker(Protocol):
    """Lock the lifecycle rows between the tenant and subscription rows."""

    def __call__(
        self,
        session: Session,
        tenant: Tenant,
    ) -> SubscriptionProjectionLifecycleLocks: ...


class SqlAlchemySubscriptionProjectionLifecycleLocker:
    """Acquire the D59 lifecycle prefix for a subscription projection.

    The caller already owns the tenant lock.  Missing recovery authority or a
    corrupt suspension/action pair fails closed; an expiry reconciliation is
    never allowed to race around those higher-priority facts.
    """

    def __call__(
        self,
        session: Session,
        tenant: Tenant,
    ) -> SubscriptionProjectionLifecycleLocks:
        if (
            not isinstance(session, Session)
            or not session.in_transaction()
            or not isinstance(tenant, Tenant)
        ):
            raise TypeError("subscription projection lock inputs are invalid")
        run = session.scalar(
            sa.select(DisasterRecoveryRun)
            .where(DisasterRecoveryRun.current_run_marker == "current")
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if run is None:
            raise SubscriptionProjectionAuthorityError(
                "SUBSCRIPTION_PROJECTION_RECOVERY_RUN_UNAVAILABLE"
            )
        hold = session.scalar(
            sa.select(TenantRecoveryHold)
            .where(
                TenantRecoveryHold.recovery_run_id == run.id,
                TenantRecoveryHold.tenant_id == tenant.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if hold is None:
            raise SubscriptionProjectionAuthorityError(
                "SUBSCRIPTION_PROJECTION_RECOVERY_HOLD_UNAVAILABLE"
            )
        deletion = session.scalar(
            sa.select(TenantDeletionRequest)
            .where(
                TenantDeletionRequest.tenant_id == tenant.id,
                TenantDeletionRequest.active_tenant_id == tenant.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        suspension = session.scalar(
            sa.select(TenantSuspension)
            .where(TenantSuspension.active_tenant_id == tenant.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        action = None
        if suspension is not None:
            action = session.scalar(
                sa.select(TenantSuspensionAction)
                .where(
                    TenantSuspensionAction.suspension_id == suspension.id,
                    TenantSuspensionAction.generation
                    == suspension.barrier_generation,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if action is None:
                raise SubscriptionProjectionAuthorityError(
                    "SUBSCRIPTION_PROJECTION_SUSPENSION_ACTION_UNAVAILABLE"
                )
        return SubscriptionProjectionLifecycleLocks(
            recovery_run_uuid=run.id,
            recovery_hold_uuid=hold.id,
            deletion_request_uuid=(deletion.id if deletion is not None else None),
            suspension_uuid=(suspension.id if suspension is not None else None),
            suspension_action_uuid=(action.id if action is not None else None),
        )


@dataclass(frozen=True, slots=True)
class SubscriptionProjectionResult:
    tenant_uuid: str
    subscription_uuid: str
    evaluated_at: datetime
    effective_status: str
    tenant_status_before: str
    tenant_status_after: str
    subscription_status_before: str
    subscription_status_after: str
    tenant_changed: bool
    subscription_changed: bool
    tenant_access_version: int
    tenant_row_version_before: int
    tenant_row_version_after: int
    subscription_row_version_before: int
    subscription_row_version_after: int


class SubscriptionProjectionEvaluator:
    """Reconcile derived active/expired projections without changing authority.

    The evaluator deliberately leaves ``access_version`` and sessions intact:
    an already authenticated member must reach the restricted expiry page.
    Higher-priority provisioning, suspension, deletion, and recovery states are
    never overwritten.  Their underlying subscription projection is still
    current-read and reconciled for the later gate reduction.
    """

    def __init__(
        self,
        *,
        lifecycle_locker: SubscriptionProjectionLifecycleLocker,
        database_clock: DatabaseClock | None = None,
    ) -> None:
        if not callable(lifecycle_locker):
            raise TypeError("lifecycle_locker is required")
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._lifecycle_locker = lifecycle_locker
        self._database_clock = database_clock or _read_database_utc_now

    def evaluate(
        self,
        session: Session,
        *,
        tenant_uuid: str | UUID,
    ) -> SubscriptionProjectionResult:
        if not isinstance(session, Session) or not session.in_transaction():
            raise SubscriptionProjectionTransactionError(
                "an explicit caller-owned transaction is required"
            )
        _require_clean_unit_of_work(session)
        tenant_id = str(_uuid(tenant_uuid))

        # Every tenant-scoped control mutation starts with the tenant lock.
        tenant = session.scalar(
            sa.select(Tenant).where(Tenant.id == tenant_id).with_for_update()
        )
        if tenant is None:
            raise SubscriptionProjectionConflictError("tenant is unavailable")
        self._lifecycle_locker(session, tenant)
        subscription = session.scalar(
            sa.select(Subscription)
            .where(Subscription.tenant_id == tenant_id)
            .with_for_update()
        )
        if subscription is None:
            raise SubscriptionProjectionConflictError(
                "tenant subscription is unavailable"
            )
        evaluated_at = _as_database_utc(self._database_clock(session))
        expires_at = _as_database_utc(subscription.expires_at)
        effective_status = "active" if expires_at > evaluated_at else "expired"

        tenant_before = tenant.status
        subscription_before = subscription.status
        tenant_revision = tenant.row_version
        subscription_revision = subscription.row_version
        tenant_after = tenant_before
        subscription_after = effective_status
        tenant_changed = False
        subscription_changed = subscription_before != effective_status

        if subscription_changed:
            changed = session.execute(
                sa.update(Subscription)
                .where(
                    Subscription.id == subscription.id,
                    Subscription.tenant_id == tenant_id,
                    Subscription.row_version == subscription_revision,
                )
                .values(
                    status=effective_status,
                    row_version=subscription_revision + 1,
                    updated_at=evaluated_at,
                )
                .execution_options(synchronize_session=False)
            )
            if changed.rowcount != 1:
                raise SubscriptionProjectionConflictError(
                    "subscription projection changed concurrently"
                )

        if tenant_before in {"active", "expired"}:
            tenant_after = effective_status
            tenant_changed = tenant_before != effective_status
            if tenant_changed:
                changed = session.execute(
                    sa.update(Tenant)
                    .where(
                        Tenant.id == tenant_id,
                        Tenant.status == tenant_before,
                        Tenant.row_version == tenant_revision,
                    )
                    .values(
                        status=effective_status,
                        row_version=tenant_revision + 1,
                        updated_at=evaluated_at,
                    )
                    .execution_options(synchronize_session=False)
                )
                if changed.rowcount != 1:
                    raise SubscriptionProjectionConflictError(
                        "tenant projection changed concurrently"
                    )

        session.expire(tenant)
        session.expire(subscription)
        return SubscriptionProjectionResult(
            tenant_uuid=tenant_id,
            subscription_uuid=subscription.id,
            evaluated_at=evaluated_at,
            effective_status=effective_status,
            tenant_status_before=tenant_before,
            tenant_status_after=tenant_after,
            subscription_status_before=subscription_before,
            subscription_status_after=subscription_after,
            tenant_changed=tenant_changed,
            subscription_changed=subscription_changed,
            tenant_access_version=tenant.access_version,
            tenant_row_version_before=tenant_revision,
            tenant_row_version_after=tenant_revision + int(tenant_changed),
            subscription_row_version_before=subscription_revision,
            subscription_row_version_after=(
                subscription_revision + int(subscription_changed)
            ),
        )


def _read_database_utc_now(session: Session) -> datetime:
    return _as_database_utc(read_database_utc_value(session))


def _as_database_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise SubscriptionProjectionTransactionError(
            "database clock did not return a datetime"
        )
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            pass
    raise ValueError("tenant_uuid is invalid")


def _require_clean_unit_of_work(session: Session) -> None:
    dirty = any(
        session.is_modified(instance, include_collections=True)
        for instance in session.dirty
    )
    if session.new or session.deleted or dirty:
        raise SubscriptionProjectionTransactionError(
            "projection evaluation requires a clean caller unit of work"
        )
