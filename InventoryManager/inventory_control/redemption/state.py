"""Pure fail-closed redemption-code lifecycle rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID


class RedemptionCodeStatus(str, Enum):
    ACTIVE = "active"
    RESERVED = "reserved"
    REDEEMED = "redeemed"
    REVOKED = "revoked"
    EXPIRED = "expired"
    RECOVERY_REVOKED = "recovery_revoked"


class RedemptionCodeStateError(RuntimeError):
    """A stable non-enumerating state error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class RedemptionCodeState:
    code_uuid: UUID
    status: RedemptionCodeStatus
    redeem_before: datetime
    created_under_recovery_run_uuid: UUID
    reserved_user_uuid: Optional[UUID] = None
    reserved_registration_attempt_uuid: Optional[UUID] = None
    redeemed_tenant_uuid: Optional[UUID] = None
    redeemed_registration_attempt_uuid: Optional[UUID] = None
    registration_commit_uuid: Optional[UUID] = None

    def __post_init__(self) -> None:
        if not isinstance(self.code_uuid, UUID):
            raise TypeError("code_uuid must be a UUID")
        if not isinstance(self.status, RedemptionCodeStatus):
            raise TypeError("status must be a RedemptionCodeStatus")
        if not isinstance(self.created_under_recovery_run_uuid, UUID):
            raise TypeError("created recovery run must be a UUID")
        if not isinstance(self.redeem_before, datetime):
            raise TypeError("redeem_before must be a datetime")

        reservation_fields = (
            self.reserved_user_uuid,
            self.reserved_registration_attempt_uuid,
        )
        if any(value is not None for value in reservation_fields) and not all(
            isinstance(value, UUID) for value in reservation_fields
        ):
            raise ValueError("reservation identity must be complete")
        if self.status is RedemptionCodeStatus.ACTIVE and any(
            value is not None
            for value in (
                *reservation_fields,
                self.redeemed_tenant_uuid,
                self.redeemed_registration_attempt_uuid,
                self.registration_commit_uuid,
            )
        ):
            raise ValueError("active code cannot have ownership bindings")
        if self.status is RedemptionCodeStatus.RESERVED and not all(
            isinstance(value, UUID) for value in reservation_fields
        ):
            raise ValueError("reserved code requires immutable attempt binding")
        if self.status is RedemptionCodeStatus.REDEEMED and not isinstance(
            self.redeemed_tenant_uuid, UUID
        ):
            raise ValueError("redeemed code requires a tenant binding")


def expire_if_due(
    state: RedemptionCodeState,
    *,
    database_now: datetime,
) -> RedemptionCodeState:
    """Expire only an unreserved active bearer at its deadline."""

    _require_compatible_time(state, database_now)
    if (
        state.status is RedemptionCodeStatus.ACTIVE
        and state.redeem_before <= database_now
    ):
        return replace(state, status=RedemptionCodeStatus.EXPIRED)
    return state


def reserve_for_registration(
    state: RedemptionCodeState,
    *,
    user_uuid: UUID,
    registration_attempt_uuid: UUID,
    current_recovery_run_uuid: UUID,
    recovery_run_completed: bool,
    database_now: datetime,
) -> RedemptionCodeState:
    """Atomically bind one active code to one user and attempt."""

    current = _require_current_redeemable(
        state,
        current_recovery_run_uuid=current_recovery_run_uuid,
        recovery_run_completed=recovery_run_completed,
        database_now=database_now,
    )
    if not isinstance(user_uuid, UUID) or not isinstance(
        registration_attempt_uuid, UUID
    ):
        raise TypeError("registration identity must use UUIDs")
    return replace(
        current,
        status=RedemptionCodeStatus.RESERVED,
        reserved_user_uuid=user_uuid,
        reserved_registration_attempt_uuid=registration_attempt_uuid,
    )


def redeem_for_renewal(
    state: RedemptionCodeState,
    *,
    tenant_uuid: UUID,
    current_recovery_run_uuid: UUID,
    recovery_run_completed: bool,
    database_now: datetime,
) -> RedemptionCodeState:
    """Consume an unreserved bearer for an existing tenant renewal."""

    current = _require_current_redeemable(
        state,
        current_recovery_run_uuid=current_recovery_run_uuid,
        recovery_run_completed=recovery_run_completed,
        database_now=database_now,
    )
    if not isinstance(tenant_uuid, UUID):
        raise TypeError("tenant_uuid must be a UUID")
    return replace(
        current,
        status=RedemptionCodeStatus.REDEEMED,
        redeemed_tenant_uuid=tenant_uuid,
    )


def redeem_reserved_registration(
    state: RedemptionCodeState,
    *,
    user_uuid: UUID,
    registration_attempt_uuid: UUID,
    tenant_uuid: UUID,
    registration_commit_uuid: UUID,
    current_recovery_run_uuid: UUID,
    recovery_run_completed: bool,
) -> RedemptionCodeState:
    """Finalize only the registration attempt that owns the reservation."""

    if not recovery_run_completed:
        raise RedemptionCodeStateError("RECOVERY_NOT_COMPLETED")
    if (
        not isinstance(current_recovery_run_uuid, UUID)
        or state.created_under_recovery_run_uuid != current_recovery_run_uuid
    ):
        raise RedemptionCodeStateError("CODE_NOT_REDEEMABLE")
    if state.status is not RedemptionCodeStatus.RESERVED:
        raise RedemptionCodeStateError("CODE_NOT_REDEEMABLE")
    if (
        state.reserved_user_uuid != user_uuid
        or state.reserved_registration_attempt_uuid != registration_attempt_uuid
    ):
        raise RedemptionCodeStateError("CODE_RESERVATION_MISMATCH")
    if not isinstance(tenant_uuid, UUID) or not isinstance(
        registration_commit_uuid, UUID
    ):
        raise TypeError("registration result must use UUIDs")
    return replace(
        state,
        status=RedemptionCodeStatus.REDEEMED,
        redeemed_tenant_uuid=tenant_uuid,
        redeemed_registration_attempt_uuid=registration_attempt_uuid,
        registration_commit_uuid=registration_commit_uuid,
    )


def revoke_after_host_restore(state: RedemptionCodeState) -> RedemptionCodeState:
    """Irreversibly fence snapshot active/reserved bearers after restore."""

    if state.status in {
        RedemptionCodeStatus.ACTIVE,
        RedemptionCodeStatus.RESERVED,
    }:
        return replace(state, status=RedemptionCodeStatus.RECOVERY_REVOKED)
    return state


def _require_current_redeemable(
    state: RedemptionCodeState,
    *,
    current_recovery_run_uuid: UUID,
    recovery_run_completed: bool,
    database_now: datetime,
) -> RedemptionCodeState:
    if not isinstance(state, RedemptionCodeState):
        raise TypeError("state must be a RedemptionCodeState")
    if not recovery_run_completed:
        raise RedemptionCodeStateError("RECOVERY_NOT_COMPLETED")
    if (
        not isinstance(current_recovery_run_uuid, UUID)
        or state.created_under_recovery_run_uuid != current_recovery_run_uuid
    ):
        raise RedemptionCodeStateError("CODE_NOT_REDEEMABLE")
    current = expire_if_due(state, database_now=database_now)
    if current.status is not RedemptionCodeStatus.ACTIVE:
        raise RedemptionCodeStateError("CODE_NOT_REDEEMABLE")
    return current


def _require_compatible_time(
    state: RedemptionCodeState,
    database_now: datetime,
) -> None:
    if not isinstance(database_now, datetime):
        raise TypeError("database_now must be a datetime")
    if state.redeem_before.tzinfo != database_now.tzinfo:
        raise ValueError("code and database times must use one timezone form")
