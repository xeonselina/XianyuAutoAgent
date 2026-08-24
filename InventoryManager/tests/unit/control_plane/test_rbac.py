import pytest

from inventory_control.domain.rbac import (
    Capability,
    PlatformRole,
    TenantRole,
    capabilities_for,
    has_platform_capability,
    has_tenant_capability,
)


@pytest.mark.parametrize(
    "capability",
    [
        Capability.INVENTORY_WRITE,
        Capability.RENTAL_SHIP,
        Capability.WAREHOUSE_DEVICE_MOVE,
        Capability.PRINT_SUBMIT,
        Capability.XIANYU_SYNC,
        Capability.RELAY_WRITE,
        Capability.INSPECTION_WRITE,
        Capability.CUSTOMER_PII_READ,
    ],
)
def test_admin_and_operator_share_daily_business_capabilities(capability):
    assert has_tenant_capability(TenantRole.ADMIN, capability)
    assert has_tenant_capability(TenantRole.OPERATOR, capability)


@pytest.mark.parametrize(
    "capability",
    [
        Capability.TENANT_MEMBERS_MANAGE,
        Capability.TENANT_INTEGRATIONS_MANAGE,
        Capability.TENANT_SUBSCRIPTION_REDEEM,
        Capability.TENANT_DELETE_REQUEST,
    ],
)
def test_only_admin_has_tenant_administration_capabilities(capability):
    assert has_tenant_capability(TenantRole.ADMIN, capability)
    assert not has_tenant_capability(TenantRole.OPERATOR, capability)


def test_platform_admin_is_read_only_for_tenant_business():
    capabilities = capabilities_for(PlatformRole.PLATFORM_ADMIN)

    assert Capability.PLATFORM_TENANT_BUSINESS_READ in capabilities
    assert Capability.PLATFORM_TENANTS_READ in capabilities
    assert Capability.INVENTORY_WRITE not in capabilities
    assert Capability.RENTAL_SHIP not in capabilities
    assert Capability.TENANT_MEMBERS_MANAGE not in capabilities
    assert Capability.TENANT_INTEGRATIONS_MANAGE not in capabilities


def test_platform_admin_has_no_tenant_identity_recovery_authority():
    capabilities = capabilities_for(PlatformRole.PLATFORM_ADMIN)

    assert Capability.PHONE_SELF_CHANGE not in capabilities
    assert Capability.TENANT_MEMBERS_MANAGE not in capabilities
    assert Capability.TENANT_DELETE_REQUEST not in capabilities


def test_tenant_admin_cannot_receive_platform_capabilities():
    capabilities = capabilities_for(TenantRole.ADMIN)

    assert Capability.PLATFORM_REDEMPTION_CODES_MANAGE not in capabilities
    assert Capability.PLATFORM_SUBSCRIPTION_ADJUST not in capabilities
    assert Capability.PLATFORM_TENANT_SUSPEND not in capabilities
    assert Capability.PLATFORM_RECOVERY_RELEASE not in capabilities


def test_no_api_key_capability_exists():
    assert all("api_key" not in capability.value for capability in Capability)


def test_unknown_role_type_is_rejected():
    with pytest.raises(TypeError, match="unsupported role"):
        capabilities_for("admin")
