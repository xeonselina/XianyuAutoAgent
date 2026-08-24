"""SQLAlchemy current-read adapter for tenant subscription renewal."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.models import (
    DisasterRecoveryRun,
    Tenant,
    TenantDeletionRequest,
    TenantRecoveryHold,
    TenantSuspension,
)

from .renewal_service import SubscriptionRenewalGate


class SqlAlchemySubscriptionRenewalGate:
    """Read the complete renewal gate in the shared tenant-first suffix.

    ``SubscriptionRenewalService`` owns the tenant lock.  This adapter then
    locks current run, hold, deletion and suspension rows in that order.
    """

    def __call__(
        self,
        session: Session,
        tenant: Tenant,
        current_recovery_run_uuid: UUID,
        database_now: datetime,
    ) -> SubscriptionRenewalGate:
        if (
            not isinstance(session, Session)
            or not session.in_transaction()
            or not isinstance(tenant, Tenant)
            or not isinstance(current_recovery_run_uuid, UUID)
            or not isinstance(database_now, datetime)
        ):
            raise TypeError("subscription renewal gate inputs are invalid")

        runs = tuple(
            session.scalars(
                sa.select(DisasterRecoveryRun)
                .where(
                    DisasterRecoveryRun.current_run_marker == "current"
                )
                .order_by(DisasterRecoveryRun.id)
                .limit(2)
                .with_for_update()
            )
        )
        run = runs[0] if len(runs) == 1 else None
        run_matches = bool(
            run is not None
            and run.id == str(current_recovery_run_uuid)
            and run.status == "completed"
        )
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
        deletion = session.scalar(
            sa.select(TenantDeletionRequest)
            .where(TenantDeletionRequest.active_tenant_id == tenant.id)
            .with_for_update()
        )
        suspension = session.scalar(
            sa.select(TenantSuspension)
            .where(TenantSuspension.active_tenant_id == tenant.id)
            .with_for_update()
        )
        return SubscriptionRenewalGate(
            recovery_run_completed=run_matches,
            tenant_hold_released=bool(
                run_matches and hold is not None and hold.state == "released"
            ),
            no_unresolved_deletion=deletion is None,
            no_unresolved_suspension=suspension is None,
        )


__all__ = ["SqlAlchemySubscriptionRenewalGate"]
