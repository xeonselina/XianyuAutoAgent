"""Explicit composition for migrated Rental SaaS HTTP capabilities."""

from __future__ import annotations

from flask import Flask

from app.services.rental.http_runtime import (
    RENTAL_SAAS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyRentalSaasHttpRuntime,
)
from app.services.tenant_business import (
    TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION,
    TenantBusinessHttpRuntime,
)


def install_rental_saas_http_runtime(
    app: Flask,
) -> SqlAlchemyRentalSaasHttpRuntime:
    """Publish Rental only when the shared trusted runtime already exists."""

    if not isinstance(app, Flask):
        raise TypeError("app must be a Flask application")
    if RENTAL_SAAS_HTTP_RUNTIME_EXTENSION in app.extensions:
        raise RuntimeError("Rental SaaS HTTP runtime is already installed")
    tenant_business_runtime = app.extensions.get(
        TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION
    )
    if not isinstance(tenant_business_runtime, TenantBusinessHttpRuntime):
        raise RuntimeError("tenant business HTTP runtime is not installed")

    runtime = SqlAlchemyRentalSaasHttpRuntime(
        tenant_business_runtime=tenant_business_runtime
    )
    app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
    return runtime


__all__ = ["install_rental_saas_http_runtime"]
