"""Explicit, environment-free SF create-waybill job composition."""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID

from app.services.relay.result_signal import (
    RelayCommittedShipmentResultEnqueuer,
)
from app.tenancy import TenantContext, TenantContextSource
from app.tenancy.routed_transaction import (
    SqlAlchemyTenantTransactionProvider,
)
from inventory_control import ControlDatabase
from inventory_control.jobs import (
    DurableJobCapability,
    DurableProviderCallAuthorizer,
)
from inventory_control.jobs.contracts import JobAuthority
from inventory_control.routing import (
    DatabaseInstanceRegistry,
    SqlAlchemyTenantRouterScope,
    TenantEnginePoolSettings,
)

from .sf_waybill_provider import (
    SfWaybillProviderAdapter,
    SfWaybillProviderDispatcher,
    SfWaybillProviderSettings,
    SfWaybillQueryDispatcher,
)
from .sf_waybill_intent import (
    SF_WAYBILL_INTENT_JOB_TYPE,
    SfWaybillIntentJobHandler,
    SqlAlchemySfWaybillIntentEnqueuer,
    SqlAlchemySfWaybillIntentStore,
    sf_waybill_intent_job_definition,
)
from .sf_waybill_reconciliation import (
    SF_WAYBILL_RECONCILIATION_JOB_TYPE,
    SfWaybillReconciliationJobHandler,
    SqlAlchemySfWaybillQueryCredentialSource,
    SqlAlchemySfWaybillReconciliationStore,
    sf_waybill_reconciliation_job_definition,
)
from .sf_waybill_worker import (
    SF_CREATE_WAYBILL_JOB_TYPE,
    PreparedSfWaybillJob,
    SfCreateWaybillJobHandler,
    SqlAlchemySfWaybillCredentialSource,
    SqlAlchemySfWaybillTenantStore,
)


WorkerClock = Callable[[], datetime]


class _SfWaybillTenantTransactionProvider:
    def __init__(self, delegate: SqlAlchemyTenantTransactionProvider) -> None:
        if not callable(delegate):
            raise TypeError("tenant transaction provider is invalid")
        self._delegate = delegate

    @contextmanager
    def __call__(self, prepared: PreparedSfWaybillJob):
        if not isinstance(prepared, PreparedSfWaybillJob):
            raise TypeError("prepared SF waybill job is invalid")
        context = TenantContext(
            tenant_id=UUID(prepared.tenant_uuid),
            access_version=prepared.tenant_access_version,
            source=TenantContextSource.WORKER_JOB,
            principal_ref="sf-waybill-worker",
            source_ref=prepared.job_uuid,
            request_id=prepared.request_id,
        )
        with self._delegate(context) as tenant_session:
            yield tenant_session


def build_sf_waybill_capability(
    *,
    control_database: ControlDatabase,
    authority: JobAuthority,
    root_key_directory: str | os.PathLike[str],
    database_instances: DatabaseInstanceRegistry,
    engine_pool_settings: TenantEnginePoolSettings,
    max_cache_entries: int,
    provider_adapter: SfWaybillProviderAdapter,
    provider_settings: SfWaybillProviderSettings,
    lease_duration: timedelta = timedelta(minutes=2),
    clock: WorkerClock | None = None,
) -> DurableJobCapability:
    """Build the SF handler without reading config or opening a connection."""

    if not isinstance(control_database, ControlDatabase) or not (
        callable(getattr(authority, "lock_current_job_authority", None))
        and callable(
            getattr(authority, "evaluate_locked_job_authority", None)
        )
    ):
        raise TypeError("SF waybill capability composition is invalid")
    if not all(
        callable(getattr(provider_adapter, method, None))
        for method in ("create_waybill", "query_waybill")
    ):
        raise TypeError("SF waybill provider adapter is invalid")
    if not isinstance(provider_settings, SfWaybillProviderSettings):
        raise TypeError("SF waybill provider settings are invalid")
    if not isinstance(lease_duration, timedelta) or lease_duration <= timedelta(0):
        raise ValueError("lease duration must be positive")
    selected_clock = clock or _utc_now
    if not callable(selected_clock):
        raise TypeError("worker clock is invalid")

    router_scope = SqlAlchemyTenantRouterScope(
        root_key_directory=root_key_directory,
        database_instances=database_instances,
        engine_pool_settings=engine_pool_settings,
        max_cache_entries=max_cache_entries,
    )
    tenant_transactions = SqlAlchemyTenantTransactionProvider(
        database=control_database,
        router_scope=router_scope,
    )
    create_transactions = _SfWaybillTenantTransactionProvider(
        tenant_transactions
    )
    call_authorizer = DurableProviderCallAuthorizer(
        database=control_database,
        authority=authority,
        lease_duration=lease_duration,
        clock=selected_clock,
    )
    relay_enqueuer = RelayCommittedShipmentResultEnqueuer(
        control_database=control_database,
    )
    create_handler = SfCreateWaybillJobHandler(
        tenant_store=SqlAlchemySfWaybillTenantStore(create_transactions),
        credential_source=SqlAlchemySfWaybillCredentialSource(
            control_database=control_database,
            root_key_directory=root_key_directory,
        ),
        provider_dispatcher=SfWaybillProviderDispatcher(
            adapter=provider_adapter,
            settings=provider_settings,
        ),
        call_authorizer=call_authorizer,
        relay_enqueuer=relay_enqueuer,
        clock=selected_clock,
    )
    intent_handler = SfWaybillIntentJobHandler(
        store=SqlAlchemySfWaybillIntentStore(tenant_transactions),
        enqueuer=SqlAlchemySfWaybillIntentEnqueuer(
            control_database=control_database,
        ),
        clock=selected_clock,
    )
    reconciliation_handler = SfWaybillReconciliationJobHandler(
        store=SqlAlchemySfWaybillReconciliationStore(tenant_transactions),
        credential_source=SqlAlchemySfWaybillQueryCredentialSource(
            control_database=control_database,
            root_key_directory=root_key_directory,
        ),
        provider_dispatcher=SfWaybillQueryDispatcher(
            adapter=provider_adapter,
            settings=provider_settings,
        ),
        call_authorizer=call_authorizer,
        relay_enqueuer=relay_enqueuer,
        clock=selected_clock,
    )
    return DurableJobCapability(
        handlers={
            SF_CREATE_WAYBILL_JOB_TYPE: create_handler,
            SF_WAYBILL_INTENT_JOB_TYPE: intent_handler,
            SF_WAYBILL_RECONCILIATION_JOB_TYPE: reconciliation_handler,
        },
        schedules=(
            sf_waybill_intent_job_definition(),
            sf_waybill_reconciliation_job_definition(),
        ),
        authority=authority,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["build_sf_waybill_capability"]
