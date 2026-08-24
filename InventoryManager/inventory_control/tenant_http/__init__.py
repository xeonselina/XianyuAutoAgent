"""Tenant-facing HTTP authentication and authorization boundary."""

from .boundary import (
    TENANT_CSRF_HEADER_NAME,
    TENANT_SESSION_COOKIE_NAME,
    AuthContext,
    TenantAuthenticationRequired,
    TenantCapabilityDenied,
    TenantCsrfDenied,
    TenantHttpBoundary,
    TenantHttpError,
    active_tenant_context,
    clear_tenant_session_cookie,
    mark_private_no_store,
    set_tenant_session_cookie,
    tenant_http_error_response,
)

__all__ = [
    "TENANT_CSRF_HEADER_NAME",
    "TENANT_SESSION_COOKIE_NAME",
    "AuthContext",
    "TenantAuthenticationRequired",
    "TenantCapabilityDenied",
    "TenantCsrfDenied",
    "TenantHttpBoundary",
    "TenantHttpError",
    "active_tenant_context",
    "clear_tenant_session_cookie",
    "mark_private_no_store",
    "set_tenant_session_cookie",
    "tenant_http_error_response",
]
