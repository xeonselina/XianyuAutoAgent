"""Explicit composition for the tenant inspection HTTP runtime."""

from __future__ import annotations

from flask import Flask

from app.services.inspection.http_runtime import (
    INSPECTION_SAAS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyInspectionSaasHttpRuntime,
)
from app.services.tenant_business import (
    TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION,
    TenantBusinessHttpRuntime,
)


def install_inspection_saas_http_runtime(
    app: Flask,
) -> SqlAlchemyInspectionSaasHttpRuntime:
    if not isinstance(app, Flask):
        raise TypeError("app must be a Flask application")
    if INSPECTION_SAAS_HTTP_RUNTIME_EXTENSION in app.extensions:
        raise RuntimeError("inspection SaaS HTTP runtime is already installed")
    tenant_runtime = app.extensions.get(TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION)
    if not isinstance(tenant_runtime, TenantBusinessHttpRuntime):
        raise RuntimeError("tenant business HTTP runtime is not installed")
    runtime = SqlAlchemyInspectionSaasHttpRuntime(
        tenant_business_runtime=tenant_runtime
    )
    app.extensions[INSPECTION_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
    return runtime


__all__ = ["install_inspection_saas_http_runtime"]
