"""Explicit Flask composition for the SaaS Gantt HTTP runtime.

This module deliberately has no environment/configuration parser.  A process
bootstrap must provide already validated control, root-key, database-instance,
and engine-pool objects.  If it does not call this helper, the public reorder
routes retain their fixed 503 behavior.
"""

from __future__ import annotations

import os

from flask import Flask

from app.services.gantt.http_runtime import (
    GANTT_SAAS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyGanttSaasHttpRuntime,
)
from app.services.tenant_business.http_runtime import (
    TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION,
)
from app.services.tenant_business.composition import (
    build_tenant_business_http_runtime,
)
from inventory_control.database import ControlDatabase
from inventory_control.proofs import (
    GanttPreviewProofAdapter,
    SqlAlchemyGanttPreviewAuthorityReader,
)
from inventory_control.routing import (
    DatabaseInstanceRegistry,
    TenantEnginePoolSettings,
)


def install_gantt_saas_http_runtime(
    app: Flask,
    *,
    control_database: ControlDatabase,
    root_key_directory: str | os.PathLike[str],
    database_instances: DatabaseInstanceRegistry,
    engine_pool_settings: TenantEnginePoolSettings,
    max_cache_entries: int,
) -> SqlAlchemyGanttSaasHttpRuntime:
    """Install one fully explicit, fail-closed production composition.

    Construction performs no database connection and reads neither Flask
    ``SECRET_KEY`` nor any environment variable.  Invalid or partial object
    graphs raise before the runtime extension is published.
    """

    if not isinstance(app, Flask):
        raise TypeError("app must be a Flask application")
    if GANTT_SAAS_HTTP_RUNTIME_EXTENSION in app.extensions:
        raise RuntimeError("Gantt SaaS HTTP runtime is already installed")
    if TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION in app.extensions:
        raise RuntimeError("tenant business HTTP runtime is already installed")
    if not isinstance(control_database, ControlDatabase):
        raise TypeError("control_database must be a ControlDatabase")

    # Build the complete graph first.  Publishing the extension is the sole
    # mutation and therefore cannot expose a partially configured runtime.
    tenant_business_runtime = build_tenant_business_http_runtime(
        control_database=control_database,
        root_key_directory=root_key_directory,
        database_instances=database_instances,
        engine_pool_settings=engine_pool_settings,
        max_cache_entries=max_cache_entries,
    )
    authority_reader = SqlAlchemyGanttPreviewAuthorityReader(
        control_database=control_database,
        root_key_directory=root_key_directory,
    )
    proof_adapter = GanttPreviewProofAdapter(
        authority_reader=authority_reader
    )
    runtime = SqlAlchemyGanttSaasHttpRuntime(
        proof_adapter=proof_adapter,
        tenant_business_runtime=tenant_business_runtime,
    )
    app.extensions[TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION] = (
        runtime.tenant_business_runtime
    )
    app.extensions[GANTT_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
    return runtime


__all__ = ["install_gantt_saas_http_runtime"]
