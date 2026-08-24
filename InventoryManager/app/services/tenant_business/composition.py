"""Explicit construction and publication of the shared tenant HTTP runtime."""

from __future__ import annotations

import os

from flask import Flask

from app.services.tenant_business.http_runtime import (
    TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyTenantBusinessHttpRuntime,
)
from inventory_control.database import ControlDatabase
from inventory_control.identity import SessionService
from inventory_control.recovery import RecoveryAuthorityService
from inventory_control.routing import (
    DatabaseInstanceRegistry,
    SqlAlchemyTenantRouterScope,
    TenantEnginePoolSettings,
)
from inventory_control.tenant_http import TenantHttpBoundary


def build_tenant_business_http_runtime(
    *,
    control_database: ControlDatabase,
    root_key_directory: str | os.PathLike[str],
    database_instances: DatabaseInstanceRegistry,
    engine_pool_settings: TenantEnginePoolSettings,
    max_cache_entries: int,
) -> SqlAlchemyTenantBusinessHttpRuntime:
    """Build the complete graph without publishing or opening a database."""

    if not isinstance(control_database, ControlDatabase):
        raise TypeError("control_database must be a ControlDatabase")
    recovery_authority = RecoveryAuthorityService()
    tenant_http_boundary = TenantHttpBoundary(
        SessionService(gate_current_read=recovery_authority)
    )
    router_scope = SqlAlchemyTenantRouterScope(
        root_key_directory=root_key_directory,
        database_instances=database_instances,
        engine_pool_settings=engine_pool_settings,
        max_cache_entries=max_cache_entries,
    )
    return SqlAlchemyTenantBusinessHttpRuntime(
        control_database=control_database,
        tenant_http_boundary=tenant_http_boundary,
        tenant_router_factory=router_scope,
    )


def install_tenant_business_http_runtime(
    app: Flask,
    *,
    control_database: ControlDatabase,
    root_key_directory: str | os.PathLike[str],
    database_instances: DatabaseInstanceRegistry,
    engine_pool_settings: TenantEnginePoolSettings,
    max_cache_entries: int,
) -> SqlAlchemyTenantBusinessHttpRuntime:
    """Install once; invalid construction cannot publish a partial runtime."""

    if not isinstance(app, Flask):
        raise TypeError("app must be a Flask application")
    if TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION in app.extensions:
        raise RuntimeError("tenant business HTTP runtime is already installed")
    runtime = build_tenant_business_http_runtime(
        control_database=control_database,
        root_key_directory=root_key_directory,
        database_instances=database_instances,
        engine_pool_settings=engine_pool_settings,
        max_cache_entries=max_cache_entries,
    )
    app.extensions[TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION] = runtime
    return runtime


__all__ = [
    "build_tenant_business_http_runtime",
    "install_tenant_business_http_runtime",
]
