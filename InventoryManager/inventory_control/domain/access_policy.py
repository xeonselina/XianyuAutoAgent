"""State-aware tenant capability reduction.

RBAC describes what a role could do in an active tenant.  This module applies
the higher-priority effective tenant gate before a route or object lookup.
"""

from __future__ import annotations

from typing import FrozenSet

from .rbac import Capability, TenantRole, tenant_capabilities
from .tenant_gate import EffectiveTenantGate


_EXPIRED_BASE = frozenset(
    {
        Capability.TENANT_EXPIRED_STATUS_READ,
        Capability.SESSION_LOGOUT,
    }
)
_SUSPENDED_BASE = frozenset(
    {
        Capability.TENANT_SUSPENSION_STATUS_READ,
        Capability.SESSION_LOGOUT,
    }
)
_ADMIN_SUSPENDED_SELF_SECURITY = frozenset(
    {
        Capability.SESSION_SELF_READ,
        Capability.SESSION_SELF_REVOKE,
        Capability.PHONE_SELF_CHANGE,
    }
)


def tenant_capabilities_for_gate(
    *,
    role: TenantRole,
    gate: EffectiveTenantGate,
) -> FrozenSet[Capability]:
    """Return the complete backend allowlist for one effective gate."""

    if not isinstance(role, TenantRole):
        raise TypeError("role must be a tenant role")
    if not isinstance(gate, EffectiveTenantGate):
        raise TypeError("gate must be an effective tenant gate")

    if gate is EffectiveTenantGate.ACTIVE:
        return tenant_capabilities(role)
    if gate is EffectiveTenantGate.EXPIRED:
        if role is TenantRole.ADMIN:
            return _EXPIRED_BASE | frozenset(
                {Capability.TENANT_SUBSCRIPTION_REDEEM}
            )
        return _EXPIRED_BASE
    if gate is EffectiveTenantGate.SUSPENDED:
        if role is TenantRole.ADMIN:
            return _SUSPENDED_BASE | _ADMIN_SUSPENDED_SELF_SECURITY
        return _SUSPENDED_BASE

    # Provisioning, recovery, deletion, stale access, and invalid state never
    # enter a normal tenant session/capability surface.
    return frozenset()


def has_tenant_capability_for_gate(
    *,
    role: TenantRole,
    gate: EffectiveTenantGate,
    capability: Capability,
) -> bool:
    if not isinstance(capability, Capability):
        raise TypeError("capability must be a Capability")
    return capability in tenant_capabilities_for_gate(role=role, gate=gate)
