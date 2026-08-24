"""Fixed SaaS Core role-to-capability mappings.

Tenant and platform identities deliberately use separate role types and
authorization functions.  A platform administrator is never a tenant role.
"""

from enum import Enum
from typing import FrozenSet, Union


class TenantRole(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"


class PlatformRole(str, Enum):
    PLATFORM_ADMIN = "platform_admin"


class Capability(str, Enum):
    SESSION_LOGOUT = "session.logout"
    SESSION_SELF_READ = "session.self.read"
    SESSION_SELF_REVOKE = "session.self.revoke"
    FACTOR_SELF_MANAGE = "factor.self.manage"
    PHONE_SELF_CHANGE = "phone.self.change"
    TENANT_EXPIRED_STATUS_READ = "tenant.expired_status.read"
    TENANT_SUSPENSION_STATUS_READ = "tenant.suspension_status.read"
    TENANT_SUMMARY_READ = "tenant.summary.read"
    INVENTORY_READ = "inventory.read"
    INVENTORY_WRITE = "inventory.write"
    RENTAL_READ = "rental.read"
    RENTAL_WRITE = "rental.write"
    RENTAL_SHIP = "rental.ship"
    WAREHOUSE_READ = "warehouse.read"
    WAREHOUSE_WRITE = "warehouse.write"
    WAREHOUSE_SETUP = "warehouse.setup"
    WAREHOUSE_DEVICE_MOVE = "warehouse.device.move"
    PRINT_SUBMIT = "print.submit"
    XIANYU_SYNC = "xianyu.sync"
    RELAY_WRITE = "relay.write"
    INSPECTION_WRITE = "inspection.write"
    CUSTOMER_PII_READ = "customer.pii.read"
    TENANT_MEMBERS_READ = "tenant.members.read"
    TENANT_MEMBERS_MANAGE = "tenant.members.manage"
    TENANT_INTEGRATIONS_READ = "tenant.integrations.read"
    TENANT_INTEGRATIONS_MANAGE = "tenant.integrations.manage"
    TENANT_SUBSCRIPTION_REDEEM = "tenant.subscription.redeem"
    TENANT_BRANDING_MANAGE = "tenant.branding.manage"
    TENANT_DELETE_REQUEST = "tenant.delete.request"
    PLATFORM_REDEMPTION_CODES_MANAGE = "platform.redemption_codes.manage"
    PLATFORM_TENANTS_READ = "platform.tenants.read"
    PLATFORM_JOBS_READ = "platform.jobs.read"
    PLATFORM_SCHEMAS_READ = "platform.schemas.read"
    PLATFORM_TENANT_BUSINESS_READ = "platform.tenant_business.read"
    PLATFORM_MEMBERS_INTEGRATIONS_READ = "platform.members_integrations.read"
    PLATFORM_SUBSCRIPTION_ADJUST = "platform.subscription.adjust"
    PLATFORM_TENANT_SUSPEND = "platform.tenant.suspend"
    PLATFORM_RECOVERY_RELEASE = "platform.recovery.release"


_OPERATOR_CAPABILITIES = frozenset(
    {
        Capability.SESSION_LOGOUT,
        Capability.SESSION_SELF_READ,
        Capability.SESSION_SELF_REVOKE,
        Capability.PHONE_SELF_CHANGE,
        Capability.TENANT_SUMMARY_READ,
        Capability.INVENTORY_READ,
        Capability.INVENTORY_WRITE,
        Capability.RENTAL_READ,
        Capability.RENTAL_WRITE,
        Capability.RENTAL_SHIP,
        Capability.WAREHOUSE_READ,
        Capability.WAREHOUSE_WRITE,
        Capability.WAREHOUSE_DEVICE_MOVE,
        Capability.PRINT_SUBMIT,
        Capability.XIANYU_SYNC,
        Capability.RELAY_WRITE,
        Capability.INSPECTION_WRITE,
        Capability.CUSTOMER_PII_READ,
    }
)

_TENANT_CAPABILITIES = {
    TenantRole.OPERATOR: _OPERATOR_CAPABILITIES,
    TenantRole.ADMIN: _OPERATOR_CAPABILITIES
    | frozenset(
        {
            Capability.TENANT_MEMBERS_READ,
            Capability.TENANT_MEMBERS_MANAGE,
            Capability.TENANT_INTEGRATIONS_READ,
            Capability.TENANT_INTEGRATIONS_MANAGE,
            Capability.TENANT_SUBSCRIPTION_REDEEM,
            Capability.TENANT_BRANDING_MANAGE,
            Capability.TENANT_DELETE_REQUEST,
            Capability.WAREHOUSE_SETUP,
        }
    ),
}

_PLATFORM_CAPABILITIES = {
    PlatformRole.PLATFORM_ADMIN: frozenset(
        {
            Capability.SESSION_LOGOUT,
            Capability.SESSION_SELF_READ,
            Capability.SESSION_SELF_REVOKE,
            Capability.FACTOR_SELF_MANAGE,
            Capability.PLATFORM_REDEMPTION_CODES_MANAGE,
            Capability.PLATFORM_TENANTS_READ,
            Capability.PLATFORM_JOBS_READ,
            Capability.PLATFORM_SCHEMAS_READ,
            Capability.PLATFORM_TENANT_BUSINESS_READ,
            Capability.PLATFORM_MEMBERS_INTEGRATIONS_READ,
            Capability.PLATFORM_SUBSCRIPTION_ADJUST,
            Capability.PLATFORM_TENANT_SUSPEND,
            Capability.PLATFORM_RECOVERY_RELEASE,
            Capability.CUSTOMER_PII_READ,
        }
    )
}


def tenant_capabilities(role: TenantRole) -> FrozenSet[Capability]:
    return _TENANT_CAPABILITIES[role]


def platform_capabilities(role: PlatformRole) -> FrozenSet[Capability]:
    return _PLATFORM_CAPABILITIES[role]


def has_tenant_capability(role: TenantRole, capability: Capability) -> bool:
    return capability in tenant_capabilities(role)


def has_platform_capability(role: PlatformRole, capability: Capability) -> bool:
    return capability in platform_capabilities(role)


def capabilities_for(
    role: Union[TenantRole, PlatformRole],
) -> FrozenSet[Capability]:
    """Return capabilities while preserving the identity-domain boundary."""

    if isinstance(role, TenantRole):
        return tenant_capabilities(role)
    if isinstance(role, PlatformRole):
        return platform_capabilities(role)
    raise TypeError("unsupported role type")
