"""Single-process composition for SF execution and relay projection."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Callable, Iterable

from app.services.relay.composition import (
    build_relay_external_projection_capability,
)
from inventory_control import ControlDatabase
from inventory_control.jobs import (
    DurableJobCapability,
    DurableJobProcess,
    RetryBackoffPolicy,
    WorkerHeartbeatRecorder,
    build_durable_job_process,
)
from inventory_control.jobs.contracts import JobAuthority
from inventory_control.jobs.scheduler import TenantScheduleGate
from inventory_control.routing import (
    DatabaseInstanceRegistry,
    TenantEnginePoolSettings,
)

from .sf_waybill_composition import build_sf_waybill_capability
from .sf_waybill_provider import (
    SfWaybillProviderAdapter,
    SfWaybillProviderSettings,
)


def build_sf_relay_job_process(
    *,
    control_database: ControlDatabase,
    authority: JobAuthority,
    heartbeat_recorder: WorkerHeartbeatRecorder,
    retry_backoff_policy: RetryBackoffPolicy,
    schedule_gate: TenantScheduleGate,
    worker_id: str,
    root_key_directory: str | os.PathLike[str],
    database_instances: DatabaseInstanceRegistry,
    engine_pool_settings: TenantEnginePoolSettings,
    max_cache_entries: int,
    provider_adapter: SfWaybillProviderAdapter,
    provider_settings: SfWaybillProviderSettings,
    additional_capabilities: Iterable[DurableJobCapability] = (),
    lease_duration: timedelta = timedelta(minutes=2),
    max_jobs_per_cycle: int = 100,
    idle_poll_interval: timedelta = timedelta(seconds=1),
    clock: Callable[[], datetime] | None = None,
    allow_sqlite_claim_for_tests: bool = False,
) -> DurableJobProcess:
    """Merge SF, relay and caller capabilities into one durable process."""

    selected_additional = tuple(additional_capabilities)
    if any(
        not isinstance(capability, DurableJobCapability)
        for capability in selected_additional
    ):
        raise TypeError("additional capabilities are invalid")
    sf = build_sf_waybill_capability(
        control_database=control_database,
        authority=authority,
        root_key_directory=root_key_directory,
        database_instances=database_instances,
        engine_pool_settings=engine_pool_settings,
        max_cache_entries=max_cache_entries,
        provider_adapter=provider_adapter,
        provider_settings=provider_settings,
        lease_duration=lease_duration,
        clock=clock,
    )
    relay = build_relay_external_projection_capability(
        control_database=control_database,
        authority=authority,
        root_key_directory=root_key_directory,
        database_instances=database_instances,
        engine_pool_settings=engine_pool_settings,
        max_cache_entries=max_cache_entries,
    )
    return build_durable_job_process(
        database=control_database,
        authority=authority,
        heartbeat_recorder=heartbeat_recorder,
        retry_backoff_policy=retry_backoff_policy,
        schedule_gate=schedule_gate,
        capabilities=(sf, relay, *selected_additional),
        worker_id=worker_id,
        lease_duration=lease_duration,
        max_jobs_per_cycle=max_jobs_per_cycle,
        idle_poll_interval=idle_poll_interval,
        clock=clock,
        allow_sqlite_claim_for_tests=allow_sqlite_claim_for_tests,
    )


__all__ = ["build_sf_relay_job_process"]
