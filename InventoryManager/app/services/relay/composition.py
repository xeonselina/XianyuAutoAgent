"""Explicit composition for relay HTTP and provider-free worker runtimes."""

import os

from flask import Flask

from app.tenancy.routed_transaction import SqlAlchemyTenantTransactionProvider
from app.services.tenant_business import (
    TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION,
    TenantBusinessHttpRuntime,
)
from inventory_control import ControlDatabase
from inventory_control.jobs import DurableJobCapability
from inventory_control.jobs.contracts import JobAuthority
from inventory_control.routing import (
    DatabaseInstanceRegistry,
    SqlAlchemyTenantRouterScope,
    TenantEnginePoolSettings,
)

from .external_projection import (
    RELAY_EXTERNAL_PROJECTION_JOB_TYPE,
    RelayExternalProjectionJobHandler,
    SqlAlchemyRelayExternalProjectionStore,
)
from .reconciliation import (
    RELAY_EXTERNAL_RECONCILIATION_JOB_TYPE,
    RelayExternalReconciliationJobHandler,
    SqlAlchemyRelayExternalReconciliationStore,
    relay_external_reconciliation_job_definition,
)
from .http_runtime import (
    RELAY_SAAS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyRelaySaasHttpRuntime,
)


def install_relay_saas_http_runtime(app: Flask) -> SqlAlchemyRelaySaasHttpRuntime:
    if not isinstance(app, Flask):
        raise TypeError("app must be a Flask application")
    if RELAY_SAAS_HTTP_RUNTIME_EXTENSION in app.extensions:
        raise RuntimeError("relay SaaS HTTP runtime is already installed")
    tenant_runtime = app.extensions.get(TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION)
    if not isinstance(tenant_runtime, TenantBusinessHttpRuntime):
        raise RuntimeError("tenant business HTTP runtime is not installed")
    runtime = SqlAlchemyRelaySaasHttpRuntime(
        tenant_business_runtime=tenant_runtime
    )
    app.extensions[RELAY_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
    return runtime


def build_relay_external_projection_capability(
    *,
    control_database: ControlDatabase,
    authority: JobAuthority,
    root_key_directory: str | os.PathLike[str],
    database_instances: DatabaseInstanceRegistry,
    engine_pool_settings: TenantEnginePoolSettings,
    max_cache_entries: int,
) -> DurableJobCapability:
    """Register the relay sink in the shared durable worker without I/O."""

    if not isinstance(control_database, ControlDatabase) or not (
        callable(getattr(authority, "lock_current_job_authority", None))
        and callable(
            getattr(authority, "evaluate_locked_job_authority", None)
        )
    ):
        raise TypeError("relay projection capability composition is invalid")
    router_scope = SqlAlchemyTenantRouterScope(
        root_key_directory=root_key_directory,
        database_instances=database_instances,
        engine_pool_settings=engine_pool_settings,
        max_cache_entries=max_cache_entries,
    )
    transactions = SqlAlchemyTenantTransactionProvider(
        database=control_database,
        router_scope=router_scope,
    )
    projection_handler = RelayExternalProjectionJobHandler(
        store=SqlAlchemyRelayExternalProjectionStore(transactions)
    )
    reconciliation_handler = RelayExternalReconciliationJobHandler(
        store=SqlAlchemyRelayExternalReconciliationStore(transactions)
    )
    return DurableJobCapability(
        handlers={
            RELAY_EXTERNAL_PROJECTION_JOB_TYPE: projection_handler,
            RELAY_EXTERNAL_RECONCILIATION_JOB_TYPE: (
                reconciliation_handler
            ),
        },
        schedules=(relay_external_reconciliation_job_definition(),),
        authority=authority,
    )


__all__ = [
    "build_relay_external_projection_capability",
    "install_relay_saas_http_runtime",
]
