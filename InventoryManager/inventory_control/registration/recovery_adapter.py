"""Bridge D58 recovery authority into registration persistence facts.

The adapter performs only control-database reads/writes inside the caller's
existing transaction.  It never commits and never performs provider or tenant
database I/O.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.models.foundation import Tenant
from inventory_control.models.recovery import TenantRecoveryHold
from inventory_control.recovery import (
    CurrentRecoveryAuthority,
    RecoveryAuthorityError,
    RecoveryAuthorityService,
)

from .persistence import RegistrationAuthorityFacts


class RecoveryRegistrationAuthorityAdapter:
    """Provide registration's current-run read and baseline-hold writer."""

    def __init__(
        self,
        *,
        recovery_authority: RecoveryAuthorityService,
        expected_deployment_marker_fingerprint: str,
    ) -> None:
        if not isinstance(recovery_authority, RecoveryAuthorityService):
            raise TypeError("recovery_authority must be a RecoveryAuthorityService")
        if (
            not isinstance(expected_deployment_marker_fingerprint, str)
            or len(expected_deployment_marker_fingerprint) != 64
        ):
            raise ValueError(
                "expected_deployment_marker_fingerprint must be 64 characters"
            )
        self._recovery_authority = recovery_authority
        self._expected_marker = expected_deployment_marker_fingerprint

    def __call__(
        self,
        session: Session,
        *,
        tenant_uuid: UUID,
        expected_recovery_run_uuid: UUID,
        database_now: datetime,
    ) -> RegistrationAuthorityFacts:
        del database_now
        current = self._recovery_authority.read_current_completed(session)
        hold = session.scalar(
            sa.select(TenantRecoveryHold)
            .where(
                TenantRecoveryHold.recovery_run_id
                == current.recovery_run_uuid,
                TenantRecoveryHold.tenant_id == str(tenant_uuid),
            )
            .with_for_update()
        )
        return self._facts(
            current,
            hold=hold,
            expected_recovery_run_uuid=expected_recovery_run_uuid,
        )

    def create_released_baseline(
        self,
        session: Session,
        *,
        tenant: Tenant,
        database_uuid: UUID,
        registration_commit_uuid: UUID,
        expected_recovery_run_uuid: UUID,
        expected_dml_login_state_version: int,
        database_now: datetime,
    ) -> RegistrationAuthorityFacts:
        del database_now
        current = self._recovery_authority.read_current_completed(session)
        if (
            current.recovery_run_uuid != str(expected_recovery_run_uuid)
            or current.deployment_marker_fingerprint != self._expected_marker
        ):
            raise RecoveryAuthorityError("REGISTRATION_RECOVERY_FENCE_LOST")
        released = self._recovery_authority.create_released_baseline_hold(
            session,
            tenant=tenant,
            database_uuid=database_uuid,
            expected_dml_login_state_version=(
                expected_dml_login_state_version
            ),
            dml_convergence_status="active",
            registration_commit_uuid=registration_commit_uuid,
        )
        hold = session.scalar(
            sa.select(TenantRecoveryHold)
            .where(TenantRecoveryHold.id == released.hold_uuid)
            .with_for_update()
        )
        if hold is None:  # pragma: no cover - flush/read invariant
            raise RecoveryAuthorityError("RECOVERY_HOLD_ANCHOR_MISSING")
        return self._facts(
            current,
            hold=hold,
            expected_recovery_run_uuid=expected_recovery_run_uuid,
        )

    def _facts(
        self,
        current: CurrentRecoveryAuthority,
        *,
        hold: TenantRecoveryHold | None,
        expected_recovery_run_uuid: UUID,
    ) -> RegistrationAuthorityFacts:
        marker_matches = bool(
            current.deployment_marker_fingerprint == self._expected_marker
        )
        current_uuid = UUID(current.recovery_run_uuid)
        run_matches = current_uuid == expected_recovery_run_uuid
        hold_ready = bool(
            run_matches
            and marker_matches
            and hold is not None
            and hold.recovery_run_id == current.recovery_run_uuid
            and hold.state == "released"
        )
        return RegistrationAuthorityFacts(
            current_recovery_run_uuid=current_uuid,
            recovery_run_completed=current.status == "completed",
            external_marker_matches=marker_matches,
            marker_generation=current.row_version,
            released_hold_uuid=UUID(hold.id) if hold is not None else None,
            released_hold_revision=(
                hold.hold_revision if hold is not None else None
            ),
            released_hold_ready=hold_ready,
        )


__all__ = ["RecoveryRegistrationAuthorityAdapter"]
