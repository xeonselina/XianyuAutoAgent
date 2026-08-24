from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask

from app import create_app
from app.services.gantt.http_runtime import (
    GANTT_SAAS_HTTP_RUNTIME_EXTENSION,
)
from app.services.inspection.http_runtime import (
    INSPECTION_SAAS_HTTP_RUNTIME_EXTENSION,
)
from app.services.platform_identity.http_runtime import (
    PLATFORM_IDENTITY_HTTP_RUNTIME_EXTENSION,
)
from app.services.platform_tenant_read.http_runtime import (
    PLATFORM_TENANT_READ_HTTP_RUNTIME_EXTENSION,
)
from app.services.rental.http_runtime import (
    RENTAL_SAAS_HTTP_RUNTIME_EXTENSION,
)
from app.services.relay.http_runtime import RELAY_SAAS_HTTP_RUNTIME_EXTENSION
from app.services.shipping.tracking_http_runtime import (
    SF_TRACKING_HTTP_RUNTIME_EXTENSION,
)
from app.services.shipping.batch_http_runtime import (
    SF_BATCH_SHIPPING_HTTP_RUNTIME_EXTENSION,
)
from app.services.warehouse.http_runtime import (
    WAREHOUSE_SAAS_HTTP_RUNTIME_EXTENSION,
)
from app.services.xianyu_sync.http_runtime import (
    XIANYU_SYNC_HTTP_RUNTIME_EXTENSION,
)
from app.services.saas_composition import (
    ENABLE_SAAS_CORE_HTTP_RUNTIME,
    SAAS_CORE_HTTP_RUNTIME_SETTINGS,
    SaasCoreHttpRuntimeSettings,
    install_configured_saas_core_http_runtimes,
    install_saas_core_http_runtime_bundle,
)
from app.services.tenant_business.http_runtime import (
    TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION,
)
from app.services.tenant_identity.http_runtime import (
    TENANT_IDENTITY_HTTP_RUNTIME_EXTENSION,
)
from app.services.tenant_subscription.http_runtime import (
    TENANT_SUBSCRIPTION_HTTP_RUNTIME_EXTENSION,
)
from inventory_control import init_control_database
from inventory_control.routing import (
    DatabaseInstanceConfig,
    DatabaseInstanceRegistry,
    TenantEnginePoolSettings,
)


RUNTIME_KEYS = (
    TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION,
    TENANT_IDENTITY_HTTP_RUNTIME_EXTENSION,
    TENANT_SUBSCRIPTION_HTTP_RUNTIME_EXTENSION,
    PLATFORM_IDENTITY_HTTP_RUNTIME_EXTENSION,
    PLATFORM_TENANT_READ_HTTP_RUNTIME_EXTENSION,
    GANTT_SAAS_HTTP_RUNTIME_EXTENSION,
    RENTAL_SAAS_HTTP_RUNTIME_EXTENSION,
    INSPECTION_SAAS_HTTP_RUNTIME_EXTENSION,
    WAREHOUSE_SAAS_HTTP_RUNTIME_EXTENSION,
    RELAY_SAAS_HTTP_RUNTIME_EXTENSION,
    SF_BATCH_SHIPPING_HTTP_RUNTIME_EXTENSION,
)
DISCONNECTED_TEST_DATABASE_URL = (
    "mysql+pymysql://unused:unused@127.0.0.1/inventory_management_test"
)


def _settings(root: Path) -> SaasCoreHttpRuntimeSettings:
    return SaasCoreHttpRuntimeSettings(
        root_key_directory=root,
        database_instances=DatabaseInstanceRegistry(
            [
                DatabaseInstanceConfig(
                    key="primary",
                    host="mysql.internal",
                )
            ]
        ),
        engine_pool_settings=TenantEnginePoolSettings(
            pool_size=1,
            max_overflow=0,
            pool_timeout_seconds=2,
            pool_recycle_seconds=30,
        ),
        max_cache_entries=8,
        platform_read_policy_version=1,
        platform_read_query_timeout_ms=2_000,
    )


class _TrackingAdapter:
    def query_routes(self, _request):
        return ()


class _XianyuScheduleGate:
    def evaluate(self, _session, *, tenant, now):
        raise AssertionError("composition must not evaluate the gate")


def _bare_app(root: Path) -> Flask:
    app = Flask(__name__)
    app.config.update(
        CONTROL_DATABASE_URL=DISCONNECTED_TEST_DATABASE_URL,
        CONTROL_DATABASE_ENGINE_OPTIONS={},
        ENABLE_SAAS_CORE_HTTP_RUNTIME=True,
        SAAS_CORE_HTTP_RUNTIME_SETTINGS=_settings(root),
    )
    init_control_database(app)
    return app


def test_bundle_is_built_and_published_atomically_without_connecting(
    tmp_path: Path,
) -> None:
    app = _bare_app(tmp_path)
    bundle = install_configured_saas_core_http_runtimes(app)

    assert bundle is not None
    assert app.extensions[TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION] is (
        bundle.tenant_business
    )
    assert app.extensions[TENANT_IDENTITY_HTTP_RUNTIME_EXTENSION] is (
        bundle.identity
    )
    assert bundle.identity.control_database is (
        bundle.tenant_business.control_database
    )
    assert bundle.identity.tenant_http_boundary is (
        bundle.tenant_business.tenant_http_boundary
    )
    assert app.extensions[TENANT_SUBSCRIPTION_HTTP_RUNTIME_EXTENSION] is (
        bundle.subscription
    )
    assert bundle.subscription.control_database is (
        bundle.tenant_business.control_database
    )
    assert bundle.subscription.tenant_http_boundary is (
        bundle.tenant_business.tenant_http_boundary
    )
    assert app.extensions[PLATFORM_IDENTITY_HTTP_RUNTIME_EXTENSION] is (
        bundle.platform_identity
    )
    assert app.extensions[PLATFORM_TENANT_READ_HTTP_RUNTIME_EXTENSION] is (
        bundle.platform_tenant_read
    )
    assert bundle.platform_tenant_read.control_database is (
        bundle.tenant_business.control_database
    )
    assert bundle.platform_tenant_read.platform_boundary is (
        bundle.platform_identity.boundary
    )
    assert app.extensions[GANTT_SAAS_HTTP_RUNTIME_EXTENSION] is bundle.gantt
    assert app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] is bundle.rental
    assert app.extensions[INSPECTION_SAAS_HTTP_RUNTIME_EXTENSION] is (
        bundle.inspection
    )
    assert app.extensions[WAREHOUSE_SAAS_HTTP_RUNTIME_EXTENSION] is (
        bundle.warehouse
    )
    assert app.extensions[RELAY_SAAS_HTTP_RUNTIME_EXTENSION] is bundle.relay
    assert app.extensions[SF_BATCH_SHIPPING_HTTP_RUNTIME_EXTENSION] is (
        bundle.sf_batch_shipping
    )
    assert bundle.sf_batch_shipping.tenant_business_runtime is (
        bundle.tenant_business
    )
    assert bundle.sf_batch_shipping.control_database is (
        bundle.tenant_business.control_database
    )
    app.extensions["inventory_control"].dispose()


def test_enabled_missing_or_partial_composition_publishes_nothing(
    tmp_path: Path,
) -> None:
    app = Flask(__name__)
    app.config.update(
        CONTROL_DATABASE_URL=DISCONNECTED_TEST_DATABASE_URL,
        CONTROL_DATABASE_ENGINE_OPTIONS={},
        ENABLE_SAAS_CORE_HTTP_RUNTIME=True,
    )
    init_control_database(app)
    with pytest.raises(RuntimeError):
        install_configured_saas_core_http_runtimes(app)
    assert not any(key in app.extensions for key in RUNTIME_KEYS)

    app.extensions[GANTT_SAAS_HTTP_RUNTIME_EXTENSION] = object()
    with pytest.raises(RuntimeError):
        install_saas_core_http_runtime_bundle(
            app,
            settings=_settings(tmp_path),
        )
    assert not any(
        key in app.extensions
        for key in RUNTIME_KEYS
        if key != GANTT_SAAS_HTTP_RUNTIME_EXTENSION
    )
    app.extensions["inventory_control"].dispose()


def test_optional_tracking_runtime_uses_the_atomic_shared_graph(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    settings = SaasCoreHttpRuntimeSettings(
        root_key_directory=settings.root_key_directory,
        database_instances=settings.database_instances,
        engine_pool_settings=settings.engine_pool_settings,
        max_cache_entries=settings.max_cache_entries,
        platform_read_policy_version=settings.platform_read_policy_version,
        platform_read_query_timeout_ms=(
            settings.platform_read_query_timeout_ms
        ),
        sf_tracking_adapter=_TrackingAdapter(),
    )
    app = _bare_app(tmp_path)
    app.config[SAAS_CORE_HTTP_RUNTIME_SETTINGS] = settings

    bundle = install_configured_saas_core_http_runtimes(app)

    assert bundle is not None
    assert app.extensions[SF_TRACKING_HTTP_RUNTIME_EXTENSION] is (
        bundle.sf_tracking
    )
    assert bundle.sf_tracking.tenant_business_runtime is (
        bundle.tenant_business
    )
    assert bundle.sf_tracking.control_database is (
        bundle.tenant_business.control_database
    )
    app.extensions["inventory_control"].dispose()


def test_optional_xianyu_runtime_uses_the_atomic_shared_graph(
    tmp_path: Path,
) -> None:
    base = _settings(tmp_path)
    settings = SaasCoreHttpRuntimeSettings(
        root_key_directory=base.root_key_directory,
        database_instances=base.database_instances,
        engine_pool_settings=base.engine_pool_settings,
        max_cache_entries=base.max_cache_entries,
        platform_read_policy_version=base.platform_read_policy_version,
        platform_read_query_timeout_ms=base.platform_read_query_timeout_ms,
        xianyu_schedule_gate=_XianyuScheduleGate(),
    )
    app = _bare_app(tmp_path)
    app.config[SAAS_CORE_HTTP_RUNTIME_SETTINGS] = settings

    bundle = install_configured_saas_core_http_runtimes(app)

    assert bundle is not None
    assert app.extensions[XIANYU_SYNC_HTTP_RUNTIME_EXTENSION] is (
        bundle.xianyu_sync
    )
    assert bundle.xianyu_sync.tenant_business_runtime is (
        bundle.tenant_business
    )
    assert bundle.xianyu_sync.job_coordinator.database is (
        bundle.tenant_business.control_database
    )
    app.extensions["inventory_control"].dispose()


def test_application_factory_uses_only_explicit_typed_settings(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)

    class Configured:
        TESTING = True
        DEBUG = False
        SQLALCHEMY_DATABASE_URI = DISCONNECTED_TEST_DATABASE_URL
        SQLALCHEMY_ENGINE_OPTIONS = {}
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        CONTROL_DATABASE_URL = DISCONNECTED_TEST_DATABASE_URL
        CONTROL_DATABASE_ENGINE_OPTIONS = {}
        ENABLE_SAAS_CORE_HTTP_RUNTIME = True
        SAAS_CORE_HTTP_RUNTIME_SETTINGS = settings

    app = create_app(Configured)

    assert all(key in app.extensions for key in RUNTIME_KEYS)
    assert app.extensions[TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION] is (
        app.extensions[GANTT_SAAS_HTTP_RUNTIME_EXTENSION]
        .tenant_business_runtime
    )
    app.extensions["inventory_control"].dispose()


def test_disabled_configuration_keeps_fail_closed_extensions_absent() -> None:
    app = Flask(__name__)
    app.config[ENABLE_SAAS_CORE_HTTP_RUNTIME] = False

    assert install_configured_saas_core_http_runtimes(app) is None
    assert not any(key in app.extensions for key in RUNTIME_KEYS)
