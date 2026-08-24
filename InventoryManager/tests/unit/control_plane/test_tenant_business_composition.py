from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app.services.rental.composition import install_rental_saas_http_runtime
from app.services.rental.http_runtime import (
    RENTAL_SAAS_HTTP_RUNTIME_EXTENSION,
)
from app.services.tenant_business import (
    TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyTenantBusinessHttpRuntime,
    install_tenant_business_http_runtime,
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
    return DatabaseInstanceRegistry([
        DatabaseInstanceConfig(key="primary", host="mysql.internal")
    ])


def _pool() -> TenantEnginePoolSettings:
    return TenantEnginePoolSettings(
        pool_size=1,
        max_overflow=0,
        pool_timeout_seconds=2,
        pool_recycle_seconds=30,
    )


def test_standalone_shared_composition_can_then_install_rental(
    tmp_path: Path,
) -> None:
    app = Flask(__name__)
    control_database = _disconnected_control_database()
    try:
        shared = install_tenant_business_http_runtime(
            app,
            control_database=control_database,
            root_key_directory=tmp_path,
            database_instances=_registry(),
            engine_pool_settings=_pool(),
            max_cache_entries=8,
        )
        rental = install_rental_saas_http_runtime(app)
    finally:
        control_database.dispose()

    assert isinstance(shared, SqlAlchemyTenantBusinessHttpRuntime)
    assert app.extensions[TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION] is shared
    assert app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] is rental


@pytest.mark.parametrize(
    ("override", "expected_exception"),
    [
        ({"control_database": object()}, TypeError),
        ({"root_key_directory": Path("relative")}, ValueError),
        ({"database_instances": object()}, TypeError),
        ({"engine_pool_settings": object()}, TypeError),
        ({"max_cache_entries": 0}, ValueError),
    ],
)
def test_invalid_shared_composition_publishes_nothing(
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
            install_tenant_business_http_runtime(app, **arguments)
    finally:
        control_database.dispose()

    assert TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION not in app.extensions
