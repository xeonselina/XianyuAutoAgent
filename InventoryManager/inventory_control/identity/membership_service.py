"""Transactional tenant membership mutations and last-Admin protection."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.domain import TenantRole
from inventory_control.models import (
    TenantAuthSecurityEvent,
    TenantMembership,
    TenantUserSession,
    User,
)
from inventory_control.transactions import require_caller_transaction
from .membership_contracts import (
    AdminPermissionChangeProof,
    LastActiveAdminError,
    MemberSeatLimitError,
    MembershipMutationAction,
    MembershipMutationAuthorityError,
    MembershipMutationConflictError,
    MembershipMutationError,
    MembershipMutationInputError,
    MembershipMutationPlan,
    MembershipMutationResult,
    plan_membership_mutation,
)
from .membership_locking import MembershipMutationLocking


class TenantMembershipService:
    """Apply one member change in the caller-owned control transaction.

    The service takes the tenant coordination row before recounting Admins and
    seats.  It never accepts an HTTP request or an OTP.  A later D48 boundary
    must construct ``AdminPermissionChangeProof`` from a successfully consumed,
    exact action intent in the same transaction.
    """

    def mutate(
        self,
        session: Session,
        *,
        tenant_uuid: UUID,
        actor_user_uuid: UUID,
        actor_membership_uuid: UUID,
        actor_session_uuid: UUID,
        target_membership_uuid: UUID,
        expected_target_revision: int,
        action: MembershipMutationAction,
        action_uuid: UUID,
        target_role: TenantRole | None = None,
        admin_proof: AdminPermissionChangeProof | None = None,
        database_now: datetime,
    ) -> MembershipMutationResult:
        self._prepare(session)
        tenant_id = _uuid_text(tenant_uuid, "tenant_uuid")
        actor_user_id = _uuid_text(actor_user_uuid, "actor_user_uuid")
        actor_membership_id = _uuid_text(actor_membership_uuid, "actor_membership_uuid")
        actor_session_id = _uuid_text(actor_session_uuid, "actor_session_uuid")
        target_membership_id = _uuid_text(
            target_membership_uuid, "target_membership_uuid"
        )
        selected_action = _action(action)
        selected_role = _optional_role(target_role)
        expected_revision = _positive(
            expected_target_revision, "expected_target_revision"
        )
        action_id = _uuid_text(action_uuid, "action_uuid")
        now = _as_utc(database_now)
        _require_action_shape(selected_action, selected_role)

        target_summary = session.execute(
            sa.select(TenantMembership.user_id, TenantMembership.tenant_id).where(
                TenantMembership.id == target_membership_id
            )
        ).one_or_none()
        if target_summary is None or target_summary.tenant_id != tenant_id:
            raise MembershipMutationConflictError()

        locked = MembershipMutationLocking.lock(
            session,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            target_user_id=target_summary.user_id,
        )
        target_user = next(
            row for row in locked.users if row.id == target_summary.user_id
        )
        actor_user = next(row for row in locked.users if row.id == actor_user_id)

        actor = next(
            (row for row in locked.memberships if row.id == actor_membership_id),
            None,
        )
        target = next(
            (row for row in locked.memberships if row.id == target_membership_id),
            None,
        )
        if (
            actor is None
            or actor.user_id != actor_user_id
            or actor.role_key != TenantRole.ADMIN.value
            or actor.status != "active"
            or actor_user.status != "active"
            or locked.tenant.status != "active"
        ):
            raise MembershipMutationAuthorityError()
        if target is None or target.status == "released":
            raise MembershipMutationConflictError()
        if target.row_version != expected_revision:
            raise MembershipMutationConflictError()

        plan = plan_membership_mutation(
            current_role=TenantRole(target.role_key),
            current_status=target.status,
            action=selected_action,
            target_role=selected_role,
        )
        role_after = plan.role_after.value
        status_after = plan.status_after
        if target.role_key == role_after and target.status == status_after:
            return _result(target, sessions_revoked=0, idempotent=True)

        if plan.changes_admin_authority:
            _require_admin_proof(
                admin_proof,
                tenant_uuid=tenant_uuid,
                actor_user_uuid=actor_user_uuid,
                actor_session_uuid=actor_session_uuid,
                target_membership_uuid=target_membership_uuid,
                expected_revision=expected_revision,
                action=selected_action,
                target_role=selected_role,
            )

        if _is_active_admin(target, user_status=target_user.status) and not (
            role_after == TenantRole.ADMIN.value and status_after == "active"
        ):
            remaining = int(
                session.scalar(
                    sa.select(sa.func.count(TenantMembership.id))
                    .join(User, User.id == TenantMembership.user_id)
                    .where(
                        TenantMembership.tenant_id == tenant_id,
                        TenantMembership.id != target.id,
                        TenantMembership.role_key == "admin",
                        TenantMembership.status == "active",
                        TenantMembership.released_at.is_(None),
                        User.status == "active",
                    )
                )
                or 0
            )
            if remaining < 1:
                raise LastActiveAdminError()

        if target.status != "active" and status_after == "active":
            if target_user.status != "active":
                raise MembershipMutationConflictError()
            occupied = MembershipMutationLocking.occupied_seats(
                session, tenant_id=tenant_id, database_now=now
            )
            if occupied >= 10:
                raise MemberSeatLimitError()

        target.role_key = role_after
        target.status = status_after
        target.released_at = now if status_after == "released" else None
        target.row_version += 1
        target.updated_at = now

        revoked = 0
        if status_after in {"disabled", "released"}:
            target_user.auth_version += 1
            target_user.updated_at = now
            revoked = _revoke_sessions(
                locked.target_sessions,
                now=now,
                actor_session_id=actor_session_id,
                reason="membership_security_invalidated",
            )
            if status_after == "released":
                MembershipMutationLocking.invalidate_open_challenges(
                    session,
                    user_id=target_user.id,
                    database_now=now,
                )

        session.add(
            TenantAuthSecurityEvent(
                tenant_id=tenant_id,
                user_id=target_user.id,
                actor_session_id=actor_session_id,
                target_session_id=None,
                event_type="security_invalidated",
                reason_code=_reason_code(
                    selected_action,
                    role_after=role_after,
                    status_after=status_after,
                ),
                request_id=f"member-action:{action_id}",
                created_at=now,
            )
        )
        session.flush()
        return _result(target, sessions_revoked=revoked, idempotent=False)

    @staticmethod
    def _prepare(session: Session) -> None:
        require_caller_transaction(
            session,
            MembershipMutationInputError,
            invalid_session_error=MembershipMutationInputError,
            clean=True,
        )


def _require_admin_proof(
    proof: AdminPermissionChangeProof | None,
    *,
    tenant_uuid: UUID,
    actor_user_uuid: UUID,
    actor_session_uuid: UUID,
    target_membership_uuid: UUID,
    expected_revision: int,
    action: MembershipMutationAction,
    target_role: TenantRole | None,
) -> None:
    if not isinstance(proof, AdminPermissionChangeProof) or proof != (
        AdminPermissionChangeProof(
            tenant_uuid=tenant_uuid,
            actor_user_uuid=actor_user_uuid,
            actor_session_uuid=actor_session_uuid,
            target_membership_uuid=target_membership_uuid,
            expected_target_revision=expected_revision,
            action=action,
            target_role=target_role,
        )
    ):
        raise MembershipMutationAuthorityError()


def _is_active_admin(row: TenantMembership, *, user_status: str) -> bool:
    return (
        row.role_key == "admin"
        and row.status == "active"
        and row.released_at is None
        and user_status == "active"
    )


def _revoke_sessions(
    rows: tuple[TenantUserSession, ...],
    *,
    now: datetime,
    actor_session_id: str,
    reason: str,
) -> int:
    changed = 0
    for row in rows:
        if row.revoked_at is None:
            row.revoked_at = now
            row.revoked_reason_code = reason
            row.revoked_by_session_id = actor_session_id
            row.updated_at = now
            changed += 1
    return changed


def _reason_code(
    action: MembershipMutationAction, *, role_after: str, status_after: str
) -> str:
    if action is MembershipMutationAction.CHANGE_ROLE:
        return f"membership_role_{role_after}"
    return f"membership_{status_after}"


def _result(
    target: TenantMembership, *, sessions_revoked: int, idempotent: bool
) -> MembershipMutationResult:
    return MembershipMutationResult(
        membership_uuid=UUID(target.id),
        user_uuid=UUID(target.user_id),
        role=TenantRole(target.role_key),
        status=target.status,
        row_version=target.row_version,
        sessions_revoked=sessions_revoked,
        idempotent=idempotent,
    )


def _require_action_shape(
    action: MembershipMutationAction, target_role: TenantRole | None
) -> None:
    if (action is MembershipMutationAction.CHANGE_ROLE) != (target_role is not None):
        raise MembershipMutationInputError()


def _uuid_text(value: object, field: str) -> str:
    if not isinstance(value, UUID):
        raise MembershipMutationInputError(f"{field} is invalid")
    return str(value)


def _positive(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MembershipMutationInputError(f"{field} is invalid")
    return value


def _action(value: object) -> MembershipMutationAction:
    try:
        return MembershipMutationAction(value)
    except (TypeError, ValueError):
        raise MembershipMutationInputError() from None


def _optional_role(value: object) -> TenantRole | None:
    if value is None:
        return None
    try:
        return TenantRole(value)
    except (TypeError, ValueError):
        raise MembershipMutationInputError() from None


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise MembershipMutationInputError()
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "AdminPermissionChangeProof",
    "LastActiveAdminError",
    "MemberSeatLimitError",
    "MembershipMutationAction",
    "MembershipMutationAuthorityError",
    "MembershipMutationConflictError",
    "MembershipMutationError",
    "MembershipMutationInputError",
    "MembershipMutationPlan",
    "MembershipMutationResult",
    "TenantMembershipService",
    "plan_membership_mutation",
]
