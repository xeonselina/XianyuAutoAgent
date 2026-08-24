"""Explicit composition for the warehouse SaaS HTTP runtime."""

from flask import Flask

from app.services.tenant_business import (
    TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION,
    TenantBusinessHttpRuntime,
)

from .http_runtime import (
    WAREHOUSE_SAAS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyWarehouseSaasHttpRuntime,
)


def install_warehouse_saas_http_runtime(
    app: Flask,
) -> SqlAlchemyWarehouseSaasHttpRuntime:
    if not isinstance(app, Flask):
        raise TypeError("app must be a Flask application")
    if WAREHOUSE_SAAS_HTTP_RUNTIME_EXTENSION in app.extensions:
        raise RuntimeError("warehouse SaaS HTTP runtime is already installed")
    tenant_runtime = app.extensions.get(TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION)
    if not isinstance(tenant_runtime, TenantBusinessHttpRuntime):
        raise RuntimeError("tenant business HTTP runtime is not installed")
    runtime = SqlAlchemyWarehouseSaasHttpRuntime(
        tenant_business_runtime=tenant_runtime
    )
    app.extensions[WAREHOUSE_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
    return runtime


__all__ = ["install_warehouse_saas_http_runtime"]
