"""Typed contracts for tenant membership mutation boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from inventory_control.domain import TenantRole


class MembershipMutationError(RuntimeError):
    pass


class MembershipMutationInputError(MembershipMutationError):
    pass


class MembershipMutationAuthorityError(MembershipMutationError):
    pass


class MembershipMutationConflictError(MembershipMutationError):
    pass


class LastActiveAdminError(MembershipMutationConflictError):
    pass


class MemberSeatLimitError(MembershipMutationConflictError):
    pass


class MembershipMutationAction(str, Enum):
    ENABLE = "enable"
    DISABLE = "disable"
    RELEASE = "release"
    CHANGE_ROLE = "change_role"


@dataclass(frozen=True, slots=True)
class MembershipMutationPlan:
    role_after: TenantRole
    status_after: str
    changes_admin_authority: bool
    admin_sms_purpose: str | None


def plan_membership_mutation(
    *,
    current_role: TenantRole,
    current_status: str,
    action: MembershipMutationAction,
    target_role: TenantRole | None,
) -> MembershipMutationPlan:
    """Return the shared semantic plan used by D48 issue and final mutation."""

    try:
        before_role = TenantRole(current_role)
        selected_action = MembershipMutationAction(action)
        selected_role = (
            None if target_role is None else TenantRole(target_role)
        )
    except (TypeError, ValueError):
        raise MembershipMutationInputError() from None
    if current_status not in {"active", "disabled"}:
        raise MembershipMutationConflictError()
    if (selected_action is MembershipMutationAction.CHANGE_ROLE) != (
        selected_role is not None
    ):
        raise MembershipMutationInputError()

    role_after = selected_role or before_role
    if selected_action is MembershipMutationAction.ENABLE:
        status_after = "active"
    elif selected_action is MembershipMutationAction.DISABLE:
        status_after = "disabled"
    elif selected_action is MembershipMutationAction.RELEASE:
        status_after = "released"
    else:
        status_after = current_status

    effective_before = (
        before_role is TenantRole.ADMIN and current_status == "active"
    )
    effective_after = (
        role_after is TenantRole.ADMIN and status_after == "active"
    )
    changes_admin = bool(
        effective_before != effective_after
        or (
            before_role is not role_after
            and TenantRole.ADMIN in {before_role, role_after}
        )
        or (
            before_role is TenantRole.ADMIN
            and status_after in {"disabled", "released"}
        )
    )
    purpose = None
    if changes_admin:
        purpose = (
            "grant_admin"
            if (
                effective_after
                or (
                    before_role is not TenantRole.ADMIN
                    and role_after is TenantRole.ADMIN
                )
            )
            else "revoke_admin"
        )
    return MembershipMutationPlan(
        role_after=role_after,
        status_after=status_after,
        changes_admin_authority=changes_admin,
        admin_sms_purpose=purpose,
    )


@dataclass(frozen=True, slots=True)
class AdminPermissionChangeProof:
    """D48 result passed by the action-intent boundary, never by HTTP input."""

    tenant_uuid: UUID
    actor_user_uuid: UUID
    actor_session_uuid: UUID
    target_membership_uuid: UUID
    expected_target_revision: int
    action: MembershipMutationAction
    target_role: TenantRole | None

    def __post_init__(self) -> None:
        identifiers = (
            self.tenant_uuid,
            self.actor_user_uuid,
            self.actor_session_uuid,
            self.target_membership_uuid,
        )
        if any(not isinstance(value, UUID) for value in identifiers):
            raise TypeError("Admin proof identifiers must be UUIDs")
        if (
            isinstance(self.expected_target_revision, bool)
            or not isinstance(self.expected_target_revision, int)
            or self.expected_target_revision < 1
        ):
            raise ValueError("Admin proof revision is invalid")
        object.__setattr__(self, "action", MembershipMutationAction(self.action))
        if self.target_role is not None:
            object.__setattr__(self, "target_role", TenantRole(self.target_role))


@dataclass(frozen=True, slots=True)
class MembershipMutationResult:
    membership_uuid: UUID
    user_uuid: UUID
    role: TenantRole
    status: str
    row_version: int
    sessions_revoked: int
    idempotent: bool


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
    "plan_membership_mutation",
]
