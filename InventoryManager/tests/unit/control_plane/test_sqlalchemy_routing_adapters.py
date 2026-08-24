from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import URL

from app.tenancy import (
    ExpectedDatabaseIdentity,
    TenantContext,
    TenantContextSource,
    TenancyError,
    TenancyErrorCode,
)
from inventory_control.crypto import RootKey
from inventory_control.routing import (
    AccountKind,
    AccountLoginState,
    DatabaseInstanceConfig,
    DatabaseInstanceRegistry,
    SqlAlchemyEngineFactory,
    SqlAlchemyIdentityVerifier,
    TenantDatabaseRouter,
    TenantEnginePoolSettings,
    TenantRoute,
    TenantRouteStatus,
)
from inventory_control.routing import sqlalchemy_adapters


TENANT_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
OTHER_TENANT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
DATABASE_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ROOT_MATERIAL = bytes(range(32))


def route(
    *,
    instance_key: str = "primary",
    database_name: str = "tenant_database",
    username: str = "tenant_dml_g1",
) -> TenantRoute:
    return TenantRoute(
        tenant_uuid=TENANT_ID,
        tenant_access_version=7,
        status=TenantRouteStatus.READY,
        account_kind=AccountKind.DML,
        database_uuid=DATABASE_ID,
        database_instance_key=instance_key,
        database_name=database_name,
        username=username,
        credential_generation=1,
        root_key_version=1,
        derivation_version=1,
        route_version=1,
        desired_login_state=AccountLoginState.ACTIVE,
        expected_schema_generation=3,
    )


def instance(*, options=None) -> DatabaseInstanceConfig:
    return DatabaseInstanceConfig(
        key="primary",
        host="mysql.internal",
        port=3307,
        options=options or {},
    )


def registry(*, options=None) -> DatabaseInstanceRegistry:
    return DatabaseInstanceRegistry([instance(options=options)])


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []
        self.exit_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.exit_calls += 1

    def execute(self, statement):
        self.statements.append(statement)
        return FakeResult(self.rows)


class FakeEngine:
    def __init__(self, rows=()):
        self.connection = FakeConnection(rows)
        self.connect_calls = 0
        self.dispose_calls = 0

    def connect(self):
        self.connect_calls += 1
        return self.connection

    def dispose(self):
        self.dispose_calls += 1


def identity_row(*, tenant_id=TENANT_ID, schema_generation=3):
    return SimpleNamespace(
        tenant_id=str(tenant_id),
        database_uuid=str(DATABASE_ID),
        created_at=datetime(2026, 8, 22, 12, 0, 0),
        schema_generation=schema_generation,
    )


def expected_identity() -> ExpectedDatabaseIdentity:
    return ExpectedDatabaseIdentity(
        tenant_id=TENANT_ID,
        database_uuid=DATABASE_ID,
        schema_generation=3,
    )


def context() -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_ID,
        access_version=7,
        source=TenantContextSource.WEB_SESSION,
        principal_ref="user:test",
        source_ref="session:test",
        request_id="request-test",
    )


def assert_not_in_exception_tree(error: BaseException, *sensitive: str) -> None:
    pending = [error]
    seen = set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        rendered = f"{current!s}\n{current!r}"
        for value in sensitive:
            assert value not in rendered
        pending.extend((current.__cause__, current.__context__))


def test_instance_registry_is_immutable_and_unknown_keys_fail_closed():
    configured_options = {"charset": "utf8mb4"}
    configured_instance = instance(options=configured_options)
    configured_registry = DatabaseInstanceRegistry([configured_instance])
    configured_options["charset"] = "latin1"

    assert configured_registry.resolve("primary").options == {
        "charset": "utf8mb4"
    }
    with pytest.raises(TypeError):
        configured_instance.options["charset"] = "latin1"

    unknown_key = "request-controlled-private-instance"
    with pytest.raises(TenancyError) as caught:
        configured_registry.resolve(unknown_key)

    assert caught.value.code == TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE.value
    assert unknown_key not in str(caught.value)
    assert "primary" not in repr(configured_instance)
    assert "mysql.internal" not in repr(configured_instance)
    assert "utf8mb4" not in repr(configured_instance)
    assert repr(configured_registry) == "DatabaseInstanceRegistry(instance_count=1)"


@pytest.mark.parametrize(
    "options",
    [
        {"database": "other_schema"},
        {"init_command": "USE other_schema"},
        {"password": "do-not-accept"},
        {"url": "mysql://example"},
        {"charset": "utf8mb4\ninit_command=USE other_schema"},
        {"charset": ""},
        {"charset": 123},
    ],
)
def test_instance_options_reject_schema_switching_credentials_and_bad_values(
    options,
):
    with pytest.raises((TypeError, ValueError)) as caught:
        instance(options=options)

    rendered = str(caught.value)
    assert "other_schema" not in rendered
    assert "do-not-accept" not in rendered
    assert "mysql://example" not in rendered


def test_engine_factory_uses_url_create_for_special_characters_and_small_pool(
    monkeypatch,
):
    special_password = "pass:/?#[]@!$&'()*+,;=%"
    special_database = "tenant/name?with#characters"
    special_username = "tenant:user@host/name"
    tenant_route = route(
        database_name=special_database,
        username=special_username,
    )
    fake_engine = FakeEngine()
    calls = []

    def fake_create_engine(url, **kwargs):
        calls.append((url, kwargs))
        return fake_engine

    monkeypatch.setattr(sqlalchemy_adapters.sa, "create_engine", fake_create_engine)
    factory = SqlAlchemyEngineFactory(
        registry=registry(
            options={
                "charset": "utf8mb4",
                "connect_timeout": "3",
            }
        )
    )

    created = factory.create(
        route=tenant_route,
        identity=tenant_route.routing_identity(),
        password=special_password,
    )

    assert created is fake_engine
    assert len(calls) == 1
    url, kwargs = calls[0]
    assert isinstance(url, URL)
    assert url.drivername == "mysql+pymysql"
    assert url.username == special_username
    assert url.password == special_password
    assert url.host == "mysql.internal"
    assert url.port == 3307
    assert url.database == special_database
    assert dict(url.query) == {
        "charset": "utf8mb4",
        "connect_timeout": "3",
    }
    assert special_password not in str(url)
    assert kwargs == {
        "pool_size": 1,
        "max_overflow": 0,
        "pool_timeout": 5,
        "pool_recycle": 300,
        "pool_pre_ping": True,
        "pool_reset_on_return": "rollback",
        "pool_use_lifo": True,
        "hide_parameters": True,
    }
    assert special_password not in repr(factory)
    assert special_database not in repr(factory)
    assert special_username not in repr(factory)


def test_factory_has_no_raw_dsn_entrypoint_and_unknown_instance_never_connects(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        sqlalchemy_adapters.sa,
        "create_engine",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    factory = SqlAlchemyEngineFactory(registry=registry())
    unknown_route = route(instance_key="missing-instance")

    with pytest.raises(TenancyError) as caught:
        factory.create(
            route=unknown_route,
            identity=unknown_route.routing_identity(),
            password="ephemeral-password",
        )

    assert caught.value.code == TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE.value
    assert calls == []

    with pytest.raises(TypeError):
        factory.create(
            route=route(),
            identity=route().routing_identity(),
            password="ephemeral-password",
            database_url="mysql://not-accepted",
        )


def test_factory_failure_does_not_expose_password_or_full_url(monkeypatch):
    password = "derived-password-that-must-not-leak"
    tenant_route = route(
        database_name="private_database",
        username="private_user",
    )
    full_url = (
        "mysql+pymysql://private_user:"
        f"{password}@mysql.internal:3307/private_database"
    )

    def fail_create_engine(url, **kwargs):
        raise RuntimeError(f"driver rejected {full_url}")

    monkeypatch.setattr(sqlalchemy_adapters.sa, "create_engine", fail_create_engine)

    with pytest.raises(TenancyError) as caught:
        SqlAlchemyEngineFactory(registry=registry()).create(
            route=tenant_route,
            identity=tenant_route.routing_identity(),
            password=password,
        )

    assert caught.value.code == TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE.value
    assert_not_in_exception_tree(caught.value, password, full_url)


def test_identity_verifier_uses_one_fixed_unqualified_query():
    engine = FakeEngine([identity_row()])

    result = SqlAlchemyIdentityVerifier().verify(
        engine=engine,
        expected=expected_identity(),
    )

    assert result is None
    assert engine.connect_calls == 1
    assert engine.connection.exit_calls == 1
    assert len(engine.connection.statements) == 1
    statement = engine.connection.statements[0]
    selected_table = statement.get_final_froms()[0]
    assert selected_table.name == "database_identity"
    assert selected_table.schema is None
    rendered = str(statement)
    assert "USE " not in rendered.upper()
    assert "database_identity" in rendered
    assert " LIMIT " in rendered.upper()


def test_identity_mismatch_is_precise_and_router_disposes_engine(monkeypatch):
    failed_engine = FakeEngine([identity_row(tenant_id=OTHER_TENANT_ID)])
    monkeypatch.setattr(
        sqlalchemy_adapters.sa,
        "create_engine",
        lambda url, **kwargs: failed_engine,
    )
    tenant_route = route()

    class Repository:
        def get_current_ready_route(
            self, *, tenant_uuid, access_version, account_kind
        ):
            return tenant_route

    class RootKeys:
        def get_root_key(self, *, version):
            return RootKey(version=1, material=ROOT_MATERIAL)

    router = TenantDatabaseRouter(
        repository=Repository(),
        root_key_provider=RootKeys(),
        engine_factory=SqlAlchemyEngineFactory(registry=registry()),
        identity_verifier=SqlAlchemyIdentityVerifier(),
        max_cache_entries=2,
    )

    with pytest.raises(TenancyError) as caught:
        router.get_engine(context(), account_kind=AccountKind.DML)

    assert caught.value.code == TenancyErrorCode.DATABASE_IDENTITY_MISMATCH.value
    assert failed_engine.dispose_calls == 1
    assert failed_engine.connect_calls == 1


def test_identity_connection_failure_is_redacted():
    secret_url = "mysql+pymysql://user:secret@private/schema"

    class FailingEngine:
        def connect(self):
            raise RuntimeError(secret_url)

    with pytest.raises(TenancyError) as caught:
        SqlAlchemyIdentityVerifier().verify(
            engine=FailingEngine(),
            expected=expected_identity(),
        )

    assert caught.value.code == TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE.value
    assert_not_in_exception_tree(caught.value, secret_url, "secret")


@pytest.mark.parametrize(
    "settings",
    [
        {"pool_size": 0},
        {"pool_size": True},
        {"max_overflow": -1},
        {"pool_timeout_seconds": 0},
        {"pool_recycle_seconds": 0},
    ],
)
def test_pool_settings_have_explicit_boundaries(settings):
    with pytest.raises(ValueError):
        TenantEnginePoolSettings(**settings)
