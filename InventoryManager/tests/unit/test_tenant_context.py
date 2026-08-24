import base64
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
from flask import Blueprint, Flask, request
from sqlalchemy import create_engine

from app import create_app
from app.control.models import Tenant
from app.control.store import ControlStore
from app.crypto import SecretBox
from app.tenant_context import (
    TenantEngineRegistry,
    TenantSession,
    bind_tenant,
    current_tenant_id,
    reset_tenant,
)
from app.utils.response import error
from config import ProductionConfig, TestingConfig


MASTER_KEY = base64.b64encode(bytes(range(32))).decode("ascii")


class FakeFlaskSqlAlchemy:
    def __init__(self, default_engine):
        self.engines = {None: default_engine}


def _tenant(box, tenant_id=7, password="pa@ss:/?#[]% word"):
    return Tenant(
        id=tenant_id,
        name=f"Tenant {tenant_id}",
        status="active",
        expires_at=None,
        db_name=f"tenant_{tenant_id}_test",
        db_username=f"tenant_{tenant_id}_user",
        db_password_ciphertext=box.encrypt(
            password,
            purpose="tenant-db-password",
        ),
        provisioning_status="active",
    )


def test_tenant_session_prefers_explicit_then_context_then_default_bind():
    default_engine = create_engine("sqlite://")
    tenant_engine = create_engine("sqlite://")
    explicit_engine = create_engine("sqlite://")
    session = TenantSession(FakeFlaskSqlAlchemy(default_engine))
    token = bind_tenant(41, tenant_engine)

    try:
        assert session.get_bind(bind=explicit_engine) is explicit_engine
        assert session.get_bind() is tenant_engine
        assert current_tenant_id() == 41
    finally:
        reset_tenant(token)

    assert session.get_bind() is default_engine
    assert current_tenant_id() is None
    session.close()
    for engine in (default_engine, tenant_engine, explicit_engine):
        engine.dispose()


def test_concurrent_tenant_contexts_do_not_overwrite_each_other():
    default_engine = create_engine("sqlite://")
    tenant_engines = {
        11: create_engine("sqlite://"),
        22: create_engine("sqlite://"),
    }
    both_bound = Barrier(2)

    def observe_binding(tenant_id):
        session = TenantSession(FakeFlaskSqlAlchemy(default_engine))
        token = bind_tenant(tenant_id, tenant_engines[tenant_id])
        try:
            both_bound.wait()
            return current_tenant_id(), session.get_bind()
        finally:
            reset_tenant(token)
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        observed = dict(
            zip(
                tenant_engines,
                executor.map(observe_binding, tenant_engines),
            )
        )

    assert observed[11] == (11, tenant_engines[11])
    assert observed[22] == (22, tenant_engines[22])
    assert current_tenant_id() is None
    default_engine.dispose()
    for engine in tenant_engines.values():
        engine.dispose()


def test_registry_builds_encoded_tenant_url_and_small_pool():
    box = SecretBox.from_base64(MASTER_KEY)
    password = "pa@ss:/?#[]% word"
    registry = TenantEngineRegistry(
        secret_box=box,
        host="db.internal",
        port=3307,
        pool_size=2,
    )

    engine = registry.get(_tenant(box, password=password))

    assert engine.url.drivername == "mysql+pymysql"
    assert engine.url.username == "tenant_7_user"
    assert engine.url.password == password
    assert engine.url.host == "db.internal"
    assert engine.url.port == 3307
    assert engine.url.database == "tenant_7_test"
    assert engine.pool.size() == 2
    assert engine.pool._max_overflow == 1
    registry.dispose_all()


def test_registry_caches_once_under_concurrency_and_disposes_all():
    box = SecretBox.from_base64(MASTER_KEY)
    registry = TenantEngineRegistry(
        secret_box=box,
        host="127.0.0.1",
        port=3306,
    )
    tenant = _tenant(box)
    simultaneous_gets = Barrier(8)

    def get_engine(_index):
        simultaneous_gets.wait()
        return registry.get(tenant)

    with ThreadPoolExecutor(max_workers=8) as executor:
        engines = list(executor.map(get_engine, range(8)))

    first_engine = engines[0]
    first_pool = first_engine.pool
    assert all(engine is first_engine for engine in engines)

    registry.dispose_all()

    assert first_engine.pool is not first_pool
    assert registry.get(tenant) is not first_engine
    registry.dispose_all()


def test_error_code_is_optional_and_preserves_existing_response_shape():
    assert error("missing", status_code=401).to_dict() == {
        "success": False,
        "message": "missing",
    }
    assert error(
        "missing",
        status_code=401,
        code="AUTH_REQUIRED",
    ).to_dict() == {
        "success": False,
        "message": "missing",
        "code": "AUTH_REQUIRED",
    }


def test_auth_bypass_is_allowed_only_in_testing():
    class UnsafeBypassConfig(TestingConfig):
        TESTING = False
        AUTH_BYPASS_FOR_TESTS = True

    with pytest.raises(RuntimeError, match="AUTH_BYPASS_FOR_TESTS"):
        create_app(UnsafeBypassConfig)


def test_production_rejects_auth_bypass_even_when_testing_is_true():
    class ProductionTestingConfig(ProductionConfig):
        TESTING = True
        AUTH_BYPASS_FOR_TESTS = True
        SAAS_MASTER_KEY = MASTER_KEY
        DEV_SMS_CODE = None

    with pytest.raises(RuntimeError, match="AUTH_BYPASS_FOR_TESTS"):
        create_app(ProductionTestingConfig)


def test_runtime_production_flag_never_honors_test_auth_bypass():
    class BypassTestingConfig(TestingConfig):
        AUTH_BYPASS_FOR_TESTS = True

    application = create_app(BypassTestingConfig)

    @application.get("/api/_runtime-production-probe")
    def runtime_production_probe():
        return {"bypassed": True}

    application.config["IS_PRODUCTION"] = True

    response = application.test_client().get(
        "/api/_runtime-production-probe"
    )

    assert response.status_code == 401
    assert response.get_json()["code"] == "AUTH_REQUIRED"


def test_tenant_gate_runs_before_early_short_circuit_blueprint(monkeypatch):
    early_blueprint = Blueprint("early_short_circuit", __name__)

    @early_blueprint.before_app_request
    def short_circuit_business_request():
        if request.path == "/api/_early-short-circuit-probe":
            return {"short_circuited": True}
        return None

    original_register_blueprint = Flask.register_blueprint
    early_blueprint_registered = False

    def register_blueprint_with_early_app_hook(
        application,
        blueprint,
        **options,
    ):
        nonlocal early_blueprint_registered
        if not early_blueprint_registered:
            early_blueprint_registered = True
            original_register_blueprint(application, early_blueprint)
        return original_register_blueprint(
            application,
            blueprint,
            **options,
        )

    monkeypatch.setattr(
        Flask,
        "register_blueprint",
        register_blueprint_with_early_app_hook,
    )

    class SecuredTestingConfig(TestingConfig):
        AUTH_BYPASS_FOR_TESTS = False

    application = create_app(SecuredTestingConfig)
    response = application.test_client().get(
        "/api/_early-short-circuit-probe"
    )

    assert response.status_code == 401
    assert response.get_json()["code"] == "AUTH_REQUIRED"


def test_app_extensions_own_and_dispose_database_resources(tmp_path):
    class TenantResourceConfig(TestingConfig):
        AUTH_BYPASS_FOR_TESTS = False
        CONTROL_DATABASE_URL = (
            f"sqlite+pysqlite:///{tmp_path / 'control.db'}"
        )
        SAAS_MASTER_KEY = MASTER_KEY

    application = create_app(TenantResourceConfig)
    store = application.extensions["control_store"]
    registry = application.extensions["tenant_engine_registry"]
    finalizer = application.extensions["tenant_resource_finalizer"]

    assert isinstance(store, ControlStore)
    assert isinstance(registry, TenantEngineRegistry)
    control_pool = store.engine.pool
    tenant_engine = registry.get(_tenant(store.secret_box))
    tenant_pool = tenant_engine.pool

    finalizer()

    assert finalizer.alive is False
    assert store.engine.pool is not control_pool
    assert tenant_engine.pool is not tenant_pool


def test_create_app_does_not_start_in_process_scheduler(monkeypatch):
    scheduler_calls = []
    fake_scheduler = SimpleNamespace(
        init_scheduler=lambda application: scheduler_calls.append(application)
    )
    monkeypatch.setitem(sys.modules, "app.utils.scheduler", fake_scheduler)

    class BypassTestingConfig(TestingConfig):
        AUTH_BYPASS_FOR_TESTS = True

    application = create_app(BypassTestingConfig)

    assert application.testing is True
    assert scheduler_calls == []
