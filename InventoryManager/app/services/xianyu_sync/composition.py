"""Explicit, environment-free composition for the Xianyu durable worker."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from typing import Callable

from inventory_control import ControlDatabase
from inventory_control.jobs import (
    DurableJobCapability,
    DurableJobWorker,
    DurableProviderCallAuthorizer,
    RetryBackoffPolicy,
    WorkerHeartbeatRecorder,
    XIAN_YU_MANUAL_JOB_TYPE,
    XIAN_YU_SCHEDULED_JOB_TYPE,
    xianyu_periodic_job_definition,
)
from inventory_control.jobs.contracts import JobAuthority
from inventory_control.routing import (
    DatabaseInstanceRegistry,
    SqlAlchemyTenantRouterScope,
    TenantEnginePoolSettings,
)

from .provider import XianyuProviderAdapter, XianyuProviderSettings
from .requests_adapter import RequestsXianyuProviderAdapter
from .worker import (
    SqlAlchemyRoutedTenantTransactionProvider,
    SqlAlchemyXianyuCredentialRequestSource,
    SqlAlchemyXianyuTenantSyncStore,
    XianyuSyncJobHandler,
)


WorkerClock = Callable[[], datetime]


def build_xianyu_sync_durable_worker(
    *,
    control_database: ControlDatabase,
    authority: JobAuthority,
    heartbeat_recorder: WorkerHeartbeatRecorder,
    retry_backoff_policy: RetryBackoffPolicy,
    worker_id: str,
    root_key_directory: str | os.PathLike[str],
    database_instances: DatabaseInstanceRegistry,
    engine_pool_settings: TenantEnginePoolSettings,
    max_cache_entries: int,
    provider_settings: XianyuProviderSettings,
    provider_adapter: XianyuProviderAdapter | None = None,
    lease_duration: timedelta = timedelta(minutes=2),
    clock: WorkerClock | None = None,
) -> DurableJobWorker:
    """Build both Xianyu job types without reading process configuration.

    Construction performs no control/tenant query and no provider call. The
    process launcher remains responsible for parsing deployment configuration,
    supplying the shared authority/heartbeat policy, and driving ``run_once``.
    """

    selected_clock = clock or _utc_now
    capability = build_xianyu_sync_capability(
        control_database=control_database,
        authority=authority,
        root_key_directory=root_key_directory,
        database_instances=database_instances,
        engine_pool_settings=engine_pool_settings,
        max_cache_entries=max_cache_entries,
        provider_settings=provider_settings,
        provider_adapter=provider_adapter,
        lease_duration=lease_duration,
        clock=selected_clock,
    )
    return DurableJobWorker(
        database=control_database,
        authority=authority,
        handlers=capability.handlers,
        heartbeat_recorder=heartbeat_recorder,
        retry_backoff_policy=retry_backoff_policy,
        worker_id=worker_id,
        lease_duration=lease_duration,
        clock=selected_clock,
        claim_job_types=capability.handlers.keys(),
    )


def build_xianyu_sync_capability(
    *,
    control_database: ControlDatabase,
    authority: JobAuthority,
    root_key_directory: str | os.PathLike[str],
    database_instances: DatabaseInstanceRegistry,
    engine_pool_settings: TenantEnginePoolSettings,
    max_cache_entries: int,
    provider_settings: XianyuProviderSettings,
    provider_adapter: XianyuProviderAdapter | None = None,
    lease_duration: timedelta = timedelta(minutes=2),
    clock: WorkerClock | None = None,
) -> DurableJobCapability:
    """Build reusable Xianyu registrations for the one shared job process."""

    if not isinstance(control_database, ControlDatabase):
        raise TypeError("control_database must be a ControlDatabase")
    if not _is_job_authority(authority):
        raise TypeError("authority must implement JobAuthority")
    selected_clock = clock or _utc_now
    if not callable(selected_clock):
        raise TypeError("worker clock must be callable")

    router_scope = SqlAlchemyTenantRouterScope(
        root_key_directory=root_key_directory,
        database_instances=database_instances,
        engine_pool_settings=engine_pool_settings,
        max_cache_entries=max_cache_entries,
    )
    transaction_provider = SqlAlchemyRoutedTenantTransactionProvider(
        database=control_database,
        router_scope=router_scope,
    )
    handler = XianyuSyncJobHandler(
        tenant_store=SqlAlchemyXianyuTenantSyncStore(transaction_provider),
        credential_source=SqlAlchemyXianyuCredentialRequestSource(
            database=control_database,
            root_key_directory=root_key_directory,
        ),
        provider_adapter=(
            provider_adapter
            if provider_adapter is not None
            else RequestsXianyuProviderAdapter()
        ),
        provider_settings=provider_settings,
        call_authorizer=DurableProviderCallAuthorizer(
            database=control_database,
            authority=authority,
            lease_duration=lease_duration,
            clock=selected_clock,
        ),
        clock=selected_clock,
    )
    return DurableJobCapability(
        handlers={
            XIAN_YU_SCHEDULED_JOB_TYPE: handler,
            XIAN_YU_MANUAL_JOB_TYPE: handler,
        },
        schedules=(xianyu_periodic_job_definition(),),
        authority=authority,
    )


def _is_job_authority(value: object) -> bool:
    return callable(getattr(value, "lock_current_job_authority", None)) and callable(
        getattr(value, "evaluate_locked_job_authority", None)
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "build_xianyu_sync_capability",
    "build_xianyu_sync_durable_worker",
]
