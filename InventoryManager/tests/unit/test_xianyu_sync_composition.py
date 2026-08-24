from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.xianyu_sync import (
    RequestsXianyuProviderAdapter,
    XianyuProviderSettings,
    build_xianyu_sync_capability,
    build_xianyu_sync_durable_worker,
)
from inventory_control import ControlDatabase
from inventory_control.jobs import (
    AuthorityVerdict,
    DurableJobWorker,
    RetryBackoffPolicy,
    XIAN_YU_MANUAL_JOB_TYPE,
    XIAN_YU_SCHEDULED_JOB_TYPE,
)
from inventory_control.routing import (
    DatabaseInstanceConfig,
    DatabaseInstanceRegistry,
    TenantEnginePoolSettings,
)


class Authority:
    def lock_current_job_authority(self, _session, *, job, phase):
        return job.id, phase

    def evaluate_locked_job_authority(
        self, _session, *, locked_authority, job, phase, now
    ):
        return AuthorityVerdict(locked_authority == (job.id, phase))


class Provider:
    def fetch_alerts(self, *, request, settings):
        raise AssertionError("composition must not call the provider")


SETTINGS = XianyuProviderSettings(
    endpoint="https://open.goofish.pro",
    connect_timeout_seconds=3,
    read_timeout_seconds=15,
    rate_limit_retry_seconds=45,
    page_size=100,
    max_pages=20,
)


def _registry() -> DatabaseInstanceRegistry:
    return DatabaseInstanceRegistry(
        [DatabaseInstanceConfig(key="primary", host="mysql.internal")]
    )


def _pool() -> TenantEnginePoolSettings:
    return TenantEnginePoolSettings(
        pool_size=1,
        max_overflow=0,
        pool_timeout_seconds=2,
        pool_recycle_seconds=30,
    )


def _build(database: ControlDatabase, root: Path, **overrides):
    arguments = {
        "control_database": database,
        "authority": Authority(),
        "heartbeat_recorder": lambda _session, *, observed_at: None,
        "retry_backoff_policy": RetryBackoffPolicy(
            (timedelta(seconds=5), timedelta(seconds=30))
        ),
        "worker_id": "xianyu-worker-1",
        "root_key_directory": root,
        "database_instances": _registry(),
        "engine_pool_settings": _pool(),
        "max_cache_entries": 8,
        "provider_settings": SETTINGS,
        "provider_adapter": Provider(),
        "lease_duration": timedelta(minutes=3),
    }
    arguments.update(overrides)
    return build_xianyu_sync_durable_worker(**arguments)


def _disconnected_control_database() -> ControlDatabase:
    return ControlDatabase(
        engine=SimpleNamespace(dispose=lambda: None),
        session_factory=object(),
    )


def test_composition_builds_both_job_types_without_database_or_provider_io(
    tmp_path: Path,
) -> None:
    database = _disconnected_control_database()
    worker = _build(database, tmp_path)

    assert isinstance(worker, DurableJobWorker)
    assert set(worker._handlers) == {
        XIAN_YU_SCHEDULED_JOB_TYPE,
        XIAN_YU_MANUAL_JOB_TYPE,
    }
    assert worker._handlers[XIAN_YU_SCHEDULED_JOB_TYPE] is worker._handlers[
        XIAN_YU_MANUAL_JOB_TYPE
    ]
    assert worker._claim_job_types == {
        XIAN_YU_SCHEDULED_JOB_TYPE,
        XIAN_YU_MANUAL_JOB_TYPE,
    }


def test_composition_can_select_production_shaped_adapter(tmp_path: Path) -> None:
    database = _disconnected_control_database()
    worker = _build(database, tmp_path, provider_adapter=None)

    handler = worker._handlers[XIAN_YU_SCHEDULED_JOB_TYPE]
    assert isinstance(handler._provider_adapter, RequestsXianyuProviderAdapter)


def test_capability_registration_reuses_one_handler_and_periodic_definition(
    tmp_path: Path,
) -> None:
    database = _disconnected_control_database()
    capability = build_xianyu_sync_capability(
        control_database=database,
        authority=Authority(),
        root_key_directory=tmp_path,
        database_instances=_registry(),
        engine_pool_settings=_pool(),
        max_cache_entries=8,
        provider_settings=SETTINGS,
        provider_adapter=Provider(),
    )

    assert set(capability.handlers) == {
        XIAN_YU_SCHEDULED_JOB_TYPE,
        XIAN_YU_MANUAL_JOB_TYPE,
    }
    assert capability.handlers[XIAN_YU_SCHEDULED_JOB_TYPE] is capability.handlers[
        XIAN_YU_MANUAL_JOB_TYPE
    ]
    assert [definition.job_type for definition in capability.schedules] == [
        XIAN_YU_SCHEDULED_JOB_TYPE
    ]


@pytest.mark.parametrize(
    ("override", "expected"),
    (
        ({"control_database": object()}, TypeError),
        ({"authority": object()}, TypeError),
        ({"root_key_directory": Path("relative")}, ValueError),
        ({"database_instances": object()}, TypeError),
        ({"engine_pool_settings": object()}, TypeError),
        ({"max_cache_entries": 0}, ValueError),
        ({"provider_settings": object()}, TypeError),
        ({"provider_adapter": object()}, TypeError),
        ({"lease_duration": timedelta(0)}, ValueError),
        ({"clock": object()}, TypeError),
    ),
)
def test_invalid_composition_fails_before_any_runtime_is_returned(
    tmp_path: Path,
    override,
    expected,
) -> None:
    database = _disconnected_control_database()
    with pytest.raises(expected):
        _build(database, tmp_path, **override)
