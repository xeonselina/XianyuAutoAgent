"""Pure control-plane domain rules.

These modules intentionally have no Flask or database dependency so the same
decisions can be used by HTTP requests, workers, and provisioning commands.
"""

from .tenant_gate import (
    EffectiveTenantGate,
    TenantGateDecision,
    TenantGateFacts,
    TenantStatus,
    reduce_tenant_gate,
)
from .rbac import (
    Capability,
    PlatformRole,
    TenantRole,
    capabilities_for,
    has_platform_capability,
    has_tenant_capability,
)
from .access_policy import (
    has_tenant_capability_for_gate,
    tenant_capabilities_for_gate,
)

__all__ = [
    "has_tenant_capability_for_gate",
    "tenant_capabilities_for_gate",
    "EffectiveTenantGate",
    "TenantGateDecision",
    "TenantGateFacts",
    "TenantStatus",
    "reduce_tenant_gate",
    "Capability",
    "PlatformRole",
    "TenantRole",
    "capabilities_for",
    "has_platform_capability",
    "has_tenant_capability",
]
