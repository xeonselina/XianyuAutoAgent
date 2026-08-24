"""Authoritative effective-tenant-state reduction.

The reducer contains no route allowlist.  Callers first reduce current control
facts, then choose the small state-specific surface they support.  Only ACTIVE
may open a normal tenant business database route.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class TenantStatus(str, Enum):
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDING = "suspending"
    SUSPENDED = "suspended"
    RESUMING = "resuming"
    DELETION_COOLING_OFF = "deletion_cooling_off"
    DELETION_COMMITTING = "deletion_committing"
    DELETED = "deleted"


class EffectiveTenantGate(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    RECOVERY_HOLD = "recovery_hold"
    DELETION_COOLING_OFF = "deletion_cooling_off"
    DELETED = "deleted"
    PROVISIONING = "provisioning"
    STALE_ACCESS = "stale_access"
    INVALID_STATE = "invalid_state"


_SUSPENSION_STATUSES = {
    TenantStatus.SUSPENDING,
    TenantStatus.SUSPENDED,
    TenantStatus.RESUMING,
}


@dataclass(frozen=True)
class TenantGateFacts:
    tenant_status: TenantStatus
    current_access_version: int
    presented_access_version: Optional[int]
    recovery_hold_released: bool
    unresolved_suspension: bool
    subscription_expires_at: Optional[datetime]
    evaluated_at: datetime

    def __post_init__(self) -> None:
        if self.current_access_version < 1:
            raise ValueError("current_access_version must be positive")
        if (
            self.presented_access_version is not None
            and self.presented_access_version < 1
        ):
            raise ValueError("presented_access_version must be positive")
        if self.evaluated_at.tzinfo != (
            self.subscription_expires_at.tzinfo
            if self.subscription_expires_at is not None
            else self.evaluated_at.tzinfo
        ):
            raise ValueError("subscription and evaluation times must use one timezone form")


@dataclass(frozen=True)
class TenantGateDecision:
    gate: EffectiveTenantGate
    error_code: Optional[str]

    @property
    def allows_business_route(self) -> bool:
        return self.gate is EffectiveTenantGate.ACTIVE


def reduce_tenant_gate(facts: TenantGateFacts) -> TenantGateDecision:
    """Reduce current authoritative facts using the approved fixed priority."""

    if (
        facts.presented_access_version is not None
        and facts.presented_access_version != facts.current_access_version
    ):
        return TenantGateDecision(
            EffectiveTenantGate.STALE_ACCESS,
            "STALE_TENANT_ACCESS_VERSION",
        )

    if facts.tenant_status in {
        TenantStatus.DELETION_COMMITTING,
        TenantStatus.DELETED,
    }:
        return TenantGateDecision(
            EffectiveTenantGate.DELETED,
            "TENANT_DELETED",
        )

    if facts.tenant_status is TenantStatus.DELETION_COOLING_OFF:
        return TenantGateDecision(
            EffectiveTenantGate.DELETION_COOLING_OFF,
            "TENANT_DELETION_COOLING_OFF",
        )

    if not facts.recovery_hold_released:
        return TenantGateDecision(
            EffectiveTenantGate.RECOVERY_HOLD,
            "TENANT_RECOVERY_IN_PROGRESS",
        )

    if facts.unresolved_suspension or facts.tenant_status in _SUSPENSION_STATUSES:
        return TenantGateDecision(
            EffectiveTenantGate.SUSPENDED,
            "TENANT_SUSPENDED",
        )

    if facts.tenant_status is TenantStatus.PROVISIONING:
        return TenantGateDecision(
            EffectiveTenantGate.PROVISIONING,
            "TENANT_PROVISIONING",
        )

    if facts.tenant_status is TenantStatus.EXPIRED or (
        facts.subscription_expires_at is not None
        and facts.subscription_expires_at <= facts.evaluated_at
    ):
        return TenantGateDecision(
            EffectiveTenantGate.EXPIRED,
            "TENANT_EXPIRED",
        )

    if (
        facts.tenant_status is TenantStatus.ACTIVE
        and facts.subscription_expires_at is not None
        and facts.subscription_expires_at > facts.evaluated_at
    ):
        return TenantGateDecision(EffectiveTenantGate.ACTIVE, None)

    return TenantGateDecision(
        EffectiveTenantGate.INVALID_STATE,
        "TENANT_STATE_INVALID",
    )
