from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app.services.gantt.composition import install_gantt_saas_http_runtime
from app.services.gantt.http_runtime import (
    GANTT_SAAS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyGanttSaasHttpRuntime,
)
from app.services.tenant_business.http_runtime import (
    TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyTenantBusinessHttpRuntime,
)
from inventory_control import ControlDatabase
from inventory_control.routing import (
    DatabaseInstanceConfig,
    DatabaseInstanceRegistry,
    TenantEnginePoolSettings,
)


def _disconnected_control_database() -> ControlDatabase:
    return ControlDatabase(
        engine=SimpleNamespace(dispose=lambda: None),
        session_factory=object(),
    )


def _registry() -> DatabaseInstanceRegistry:
    return DatabaseInstanceRegistry(
        [
            DatabaseInstanceConfig(
                key="primary",
                host="mysql.internal",
            )
        ]
    )


def _pool() -> TenantEnginePoolSettings:
    return TenantEnginePoolSettings(
        pool_size=1,
        max_overflow=0,
        pool_timeout_seconds=2,
        pool_recycle_seconds=30,
    )


def test_explicit_composition_installs_complete_runtime_without_connecting(
    tmp_path: Path,
) -> None:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "legacy-value-must-be-irrelevant"
    control_database = _disconnected_control_database()
    try:
        runtime = install_gantt_saas_http_runtime(
            app,
            control_database=control_database,
            root_key_directory=tmp_path,
            database_instances=_registry(),
            engine_pool_settings=_pool(),
            max_cache_entries=8,
        )
    finally:
        control_database.dispose()

    assert isinstance(runtime, SqlAlchemyGanttSaasHttpRuntime)
    assert app.extensions[GANTT_SAAS_HTTP_RUNTIME_EXTENSION] is runtime
    assert isinstance(
        app.extensions[TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION],
        SqlAlchemyTenantBusinessHttpRuntime,
    )
    assert (
        app.extensions[TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION]
        is runtime.tenant_business_runtime
    )
    assert "legacy-value" not in repr(runtime)


@pytest.mark.parametrize(
    ("override", "expected_exception"),
    [
        ({"control_database": object()}, TypeError),
        ({"root_key_directory": Path("relative/keys")}, ValueError),
        ({"database_instances": object()}, TypeError),
        ({"engine_pool_settings": object()}, TypeError),
        ({"max_cache_entries": 0}, ValueError),
    ],
)
def test_invalid_composition_fails_before_extension_publication(
    tmp_path: Path,
    override,
    expected_exception,
) -> None:
    app = Flask(__name__)
    control_database = _disconnected_control_database()
    arguments = {
        "control_database": control_database,
        "root_key_directory": tmp_path,
        "database_instances": _registry(),
        "engine_pool_settings": _pool(),
        "max_cache_entries": 8,
    }
    arguments.update(override)
    try:
        with pytest.raises(expected_exception):
            install_gantt_saas_http_runtime(app, **arguments)
    finally:
        control_database.dispose()

    assert GANTT_SAAS_HTTP_RUNTIME_EXTENSION not in app.extensions
    assert TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION not in app.extensions


def test_composition_cannot_replace_an_installed_runtime(tmp_path: Path) -> None:
    app = Flask(__name__)
    control_database = _disconnected_control_database()
    try:
        first = install_gantt_saas_http_runtime(
            app,
            control_database=control_database,
            root_key_directory=tmp_path,
            database_instances=_registry(),
            engine_pool_settings=_pool(),
            max_cache_entries=8,
        )
        with pytest.raises(RuntimeError, match="already installed"):
            install_gantt_saas_http_runtime(
                app,
                control_database=control_database,
                root_key_directory=tmp_path,
                database_instances=_registry(),
                engine_pool_settings=_pool(),
                max_cache_entries=8,
            )
    finally:
        control_database.dispose()

    assert app.extensions[GANTT_SAAS_HTTP_RUNTIME_EXTENSION] is first
    assert (
        app.extensions[TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION]
        is first.tenant_business_runtime
    )
