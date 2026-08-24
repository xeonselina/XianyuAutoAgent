"""Shared fail-closed runtime primitives for tenant business HTTP APIs."""

from .http_runtime import (
    TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyTenantBusinessHttpRuntime,
    TenantBusinessHttpRuntime,
    TenantBusinessRequestScope,
    TenantBusinessRuntimeUnavailable,
    TenantSetupRequired,
    require_tenant_business_http_runtime,
)
from .composition import (
    build_tenant_business_http_runtime,
    install_tenant_business_http_runtime,
)

__all__ = [
    "TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION",
    "SqlAlchemyTenantBusinessHttpRuntime",
    "TenantBusinessHttpRuntime",
    "TenantBusinessRequestScope",
    "TenantBusinessRuntimeUnavailable",
    "TenantSetupRequired",
    "require_tenant_business_http_runtime",
    "build_tenant_business_http_runtime",
    "install_tenant_business_http_runtime",
]
