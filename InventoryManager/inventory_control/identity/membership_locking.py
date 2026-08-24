"""Reusable lock-order and realtime-seat reads for member mutations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.models import (
    MemberSeatGuard,
    SmsChallenge,
    Tenant,
    TenantInvitation,
    TenantMembership,
    TenantSensitiveActionIntent,
    TenantUserSession,
    User,
)

from .membership_contracts import MembershipMutationConflictError


@dataclass(frozen=True, slots=True)
class LockedMembershipScope:
    tenant: Tenant
    users: tuple[User, ...]
    memberships: tuple[TenantMembership, ...]
    sensitive_intent: TenantSensitiveActionIntent | None
    target_sessions: tuple[TenantUserSession, ...]


class MembershipMutationLocking:
    """Acquire the shared D47/D48 member-mutation lock order."""

    @staticmethod
    def lock(
        session: Session,
        *,
        tenant_id: str,
        actor_user_id: str,
        target_user_id: str,
        sensitive_intent_id: str | None = None,
        lock_auth_artifacts: bool = True,
    ) -> LockedMembershipScope:
        user_ids = tuple(sorted({actor_user_id, target_user_id}))
        users = tuple(
            session.scalars(
                sa.select(User)
                .where(User.id.in_(user_ids))
                .order_by(User.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if tuple(row.id for row in users) != user_ids:
            raise MembershipMutationConflictError()

        tuple(
            session.scalars(
                sa.select(TenantInvitation)
                .where(TenantInvitation.user_id.in_(user_ids))
                .order_by(TenantInvitation.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        tenant = session.scalar(
            sa.select(Tenant)
            .where(Tenant.id == tenant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        guard = session.scalar(
            sa.select(MemberSeatGuard)
            .where(
                MemberSeatGuard.tenant_id == tenant_id,
                MemberSeatGuard.quota_key == "member_seats",
            )
            .with_for_update()
        )
        if tenant is None or guard is None:
            raise MembershipMutationConflictError()
        memberships = tuple(
            session.scalars(
                sa.select(TenantMembership)
                .where(TenantMembership.tenant_id == tenant_id)
                .order_by(TenantMembership.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        sensitive_intent = None
        if sensitive_intent_id is not None:
            sensitive_intent = session.scalar(
                sa.select(TenantSensitiveActionIntent)
                .where(
                    TenantSensitiveActionIntent.id == sensitive_intent_id
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        target_sessions: tuple[TenantUserSession, ...] = ()
        if lock_auth_artifacts:
            tuple(
                session.scalars(
                    sa.select(SmsChallenge)
                    .where(
                        SmsChallenge.user_id.in_(user_ids),
                        SmsChallenge.verification_state.in_(
                            ("pending_delivery", "active")
                        ),
                    )
                    .order_by(SmsChallenge.id)
                    .with_for_update()
                )
            )
            target_sessions = tuple(
                session.scalars(
                    sa.select(TenantUserSession)
                    .where(TenantUserSession.user_id == target_user_id)
                    .order_by(TenantUserSession.id)
                    .with_for_update()
                )
            )
        return LockedMembershipScope(
            tenant=tenant,
            users=users,
            memberships=memberships,
            sensitive_intent=sensitive_intent,
            target_sessions=target_sessions,
        )

    @staticmethod
    def occupied_seats(
        session: Session, *, tenant_id: str, database_now: datetime
    ) -> int:
        active = session.scalar(
            sa.select(sa.func.count(TenantMembership.id))
            .join(User, User.id == TenantMembership.user_id)
            .where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.status == "active",
                TenantMembership.released_at.is_(None),
                User.status == "active",
            )
        )
        pending = session.scalar(
            sa.select(sa.func.count(TenantInvitation.id)).where(
                TenantInvitation.tenant_id == tenant_id,
                TenantInvitation.status == "pending",
                TenantInvitation.expires_at > database_now,
            )
        )
        return int(active or 0) + int(pending or 0)

    @staticmethod
    def invalidate_open_challenges(
        session: Session, *, user_id: str, database_now: datetime
    ) -> None:
        for row in session.scalars(
            sa.select(SmsChallenge)
            .where(
                SmsChallenge.user_id == user_id,
                SmsChallenge.verification_state.in_(
                    ("pending_delivery", "active")
                ),
            )
            .order_by(SmsChallenge.id)
            .with_for_update()
        ):
            row.verification_state = "invalidated"
            row.invalidated_at = database_now
            row.invalidated_reason_code = "membership_released"
            row.row_version += 1


__all__ = ["LockedMembershipScope", "MembershipMutationLocking"]
