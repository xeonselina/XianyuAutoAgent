from __future__ import annotations

import pytest

from inventory_control.domain.access_policy import (
    has_tenant_capability_for_gate,
    tenant_capabilities_for_gate,
)
from inventory_control.domain.rbac import Capability, PlatformRole, TenantRole
from inventory_control.domain.tenant_gate import EffectiveTenantGate


def test_active_tenant_uses_normal_role_matrix_and_self_security() -> None:
    admin = tenant_capabilities_for_gate(
        role=TenantRole.ADMIN,
        gate=EffectiveTenantGate.ACTIVE,
    )
    operator = tenant_capabilities_for_gate(
        role=TenantRole.OPERATOR,
        gate=EffectiveTenantGate.ACTIVE,
    )

    assert Capability.INVENTORY_WRITE in admin
    assert Capability.INVENTORY_WRITE in operator
    assert Capability.TENANT_MEMBERS_MANAGE in admin
    assert Capability.TENANT_MEMBERS_MANAGE not in operator
    assert Capability.SESSION_SELF_REVOKE in admin
    assert Capability.SESSION_SELF_REVOKE in operator


def test_expired_surface_is_one_closed_renewal_loop() -> None:
    admin = tenant_capabilities_for_gate(
        role=TenantRole.ADMIN,
        gate=EffectiveTenantGate.EXPIRED,
    )
    operator = tenant_capabilities_for_gate(
        role=TenantRole.OPERATOR,
        gate=EffectiveTenantGate.EXPIRED,
    )

    assert admin == {
        Capability.TENANT_EXPIRED_STATUS_READ,
        Capability.SESSION_LOGOUT,
        Capability.TENANT_SUBSCRIPTION_REDEEM,
    }
    assert operator == {
        Capability.TENANT_EXPIRED_STATUS_READ,
        Capability.SESSION_LOGOUT,
    }
    for denied in (
        Capability.INVENTORY_READ,
        Capability.SESSION_SELF_READ,
        Capability.PHONE_SELF_CHANGE,
        Capability.TENANT_INTEGRATIONS_READ,
    ):
        assert denied not in admin
        assert denied not in operator


def test_suspended_operator_and_admin_have_exact_surfaces() -> None:
    admin = tenant_capabilities_for_gate(
        role=TenantRole.ADMIN,
        gate=EffectiveTenantGate.SUSPENDED,
    )
    operator = tenant_capabilities_for_gate(
        role=TenantRole.OPERATOR,
        gate=EffectiveTenantGate.SUSPENDED,
    )

    assert operator == {
        Capability.TENANT_SUSPENSION_STATUS_READ,
        Capability.SESSION_LOGOUT,
    }
    assert admin == operator | {
        Capability.SESSION_SELF_READ,
        Capability.SESSION_SELF_REVOKE,
        Capability.PHONE_SELF_CHANGE,
    }
    assert Capability.TENANT_SUBSCRIPTION_REDEEM not in admin
    assert Capability.TENANT_INTEGRATIONS_MANAGE not in admin


@pytest.mark.parametrize(
    "gate",
    [
        EffectiveTenantGate.RECOVERY_HOLD,
        EffectiveTenantGate.DELETION_COOLING_OFF,
        EffectiveTenantGate.DELETED,
        EffectiveTenantGate.PROVISIONING,
        EffectiveTenantGate.STALE_ACCESS,
        EffectiveTenantGate.INVALID_STATE,
    ],
)
def test_closed_gates_expose_no_tenant_capability(gate) -> None:
    assert tenant_capabilities_for_gate(
        role=TenantRole.ADMIN,
        gate=gate,
    ) == frozenset()


def test_policy_keeps_platform_roles_out_of_tenant_domain() -> None:
    with pytest.raises(TypeError, match="tenant role"):
        tenant_capabilities_for_gate(
            role=PlatformRole.PLATFORM_ADMIN,
            gate=EffectiveTenantGate.ACTIVE,
        )


def test_helper_checks_typed_capabilities() -> None:
    assert has_tenant_capability_for_gate(
        role=TenantRole.ADMIN,
        gate=EffectiveTenantGate.EXPIRED,
        capability=Capability.TENANT_SUBSCRIPTION_REDEEM,
    )
    with pytest.raises(TypeError):
        has_tenant_capability_for_gate(
            role=TenantRole.ADMIN,
            gate=EffectiveTenantGate.ACTIVE,
            capability="inventory.read",
        )
