from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.database_identity import TenantDatabaseIdentity
from app.tenancy import (
    TenancyError,
    TenancyErrorCode,
    TenantContext,
    TenantContextSource,
)
from inventory_control import ControlBase, ControlDatabase
from inventory_control.crypto import RootKeyLifecycle
from inventory_control.models import (
    DatabaseIdentityControlRecord,
    PlatformRootKeyVersion,
    Tenant,
    TenantDatabase,
)
from inventory_control.routing import (
    AccountKind,
    DatabaseInstanceConfig,
    DatabaseInstanceRegistry,
    SqlAlchemyEngineFactory,
    SqlAlchemyRouteRepository,
    SqlAlchemyTenantRouterScope,
    TenantEnginePoolSettings,
)


TENANT_ID = UUID("11111111-1111-4111-8111-111111111111")
DATABASE_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
COMMIT_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
ROOT_VERSION = 4
ROOT_MATERIAL = bytes(range(32))
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)

@pytest.fixture
def control_database(mysql_routed_database):
    return mysql_routed_database


@pytest.fixture
def tenant_engine(control_database):
    engine = control_database.engine
    with Session(engine) as session, session.begin():
        session.add(
            TenantDatabaseIdentity(
                tenant_id=str(TENANT_ID),
                database_uuid=str(DATABASE_ID),
                created_at=NOW.replace(tzinfo=None),
                schema_generation=3,
            )
        )
    return engine


@pytest.fixture
def root_key_directory(tmp_path: Path) -> Path:
    key = tmp_path / f"v{ROOT_VERSION}"
    key.write_bytes(base64.b64encode(ROOT_MATERIAL) + b"\n")
    key.chmod(0o400)
    return tmp_path


def _seed_control(database: ControlDatabase) -> None:
    with database.transaction() as session:
        session.add(
            PlatformRootKeyVersion(
                version=ROOT_VERSION,
                fingerprint_sha256=hashlib.sha256(ROOT_MATERIAL).digest(),
                status=RootKeyLifecycle.ACTIVE.value,
                activated_at=NOW,
            )
        )
        session.add(
            Tenant(
                id=str(TENANT_ID),
                status="active",
                access_version=7,
                row_version=3,
            )
        )
        session.add(
            TenantDatabase(
                tenant_id=str(TENANT_ID),
                database_uuid=str(DATABASE_ID),
                database_instance_key="primary",
                database_name="tenant_inventory",
                status="ready",
                schema_version="tenant-schema-3",
                activated_by_registration_commit_uuid=str(COMMIT_ID),
                activation_route_version=2,
                activation_credential_generation=1,
                dml_username="tenant_dml_g2",
                dml_credential_generation=2,
                dml_root_key_version=ROOT_VERSION,
                dml_derivation_version=1,
                route_version=9,
                dml_desired_login_state="active",
                dml_observed_login_state="active",
                dml_login_state_version=5,
                platform_read_username="tenant_read_g3",
                platform_read_credential_generation=3,
                platform_read_root_key_version=ROOT_VERSION,
                platform_read_derivation_version=2,
                platform_read_route_version=11,
                row_version=6,
            )
        )
        session.add(
            DatabaseIdentityControlRecord(
                tenant_id=str(TENANT_ID),
                database_uuid=str(DATABASE_ID),
                expected_schema_generation=3,
                observed_schema_generation=3,
                identity_created_at=NOW,
            )
        )


def _tenant_context(request_id: str) -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_ID,
        access_version=7,
        source=TenantContextSource.WEB_SESSION,
        principal_ref="user:test",
        source_ref="session:test",
        request_id=request_id,
    )


def _scope(root_key_directory: Path) -> SqlAlchemyTenantRouterScope:
    return SqlAlchemyTenantRouterScope(
        root_key_directory=root_key_directory,
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
        max_cache_entries=4,
    )


def test_two_bindings_share_engine_cache_but_use_distinct_control_sessions(
    control_database,
    tenant_engine: Engine,
    root_key_directory,
    monkeypatch,
) -> None:
    _seed_control(control_database)
    created: list[UUID] = []
    route_sessions: list[Session] = []
    original_route_read = SqlAlchemyRouteRepository.get_current_ready_route

    def create_engine(_factory, *, route, identity, password):
        assert isinstance(password, str) and password
        created.append(route.tenant_uuid)
        assert identity == route.routing_identity()
        return tenant_engine

    def route_read(repository, **kwargs):
        route_sessions.append(repository._session)
        return original_route_read(repository, **kwargs)

    monkeypatch.setattr(SqlAlchemyEngineFactory, "create", create_engine)
    monkeypatch.setattr(
        SqlAlchemyRouteRepository,
        "get_current_ready_route",
        route_read,
    )
    scope = _scope(root_key_directory)

    with control_database.transaction() as first_session:
        with scope(first_session) as first_router:
            first_engine = first_router.get_engine(
                _tenant_context("request-1"),
                account_kind=AccountKind.DML,
            )
    with control_database.transaction() as second_session:
        with scope(second_session) as second_router:
            second_engine = second_router.get_engine(
                _tenant_context("request-2"),
                account_kind=AccountKind.DML,
            )

    assert first_router is second_router
    assert first_engine is tenant_engine
    assert second_engine is tenant_engine
    assert len(created) == 1
    assert route_sessions == [first_session, second_session]
    assert first_session is not second_session
    assert not first_session.in_transaction()
    assert not second_session.in_transaction()


def test_binding_is_reset_after_exception_and_cannot_leak_closed_session(
    control_database,
    tenant_engine: Engine,
    root_key_directory,
    monkeypatch,
) -> None:
    _seed_control(control_database)
    monkeypatch.setattr(
        SqlAlchemyEngineFactory,
        "create",
        lambda *_args, **_kwargs: tenant_engine,
    )
    scope = _scope(root_key_directory)
    captured = None

    with pytest.raises(LookupError, match="forced"):
        with control_database.transaction() as failed_session:
            with scope(failed_session) as router:
                captured = router
                raise LookupError("forced")

    assert captured is not None
    with pytest.raises(TenancyError) as caught:
        captured.get_engine(
            _tenant_context("outside-scope"),
            account_kind=AccountKind.DML,
        )
    assert caught.value.code == TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE.value

    with control_database.transaction() as fresh_session:
        with scope(fresh_session) as router:
            assert (
                router.get_engine(
                    _tenant_context("fresh-scope"),
                    account_kind=AccountKind.DML,
                )
                is tenant_engine
            )


def test_scope_rejects_relative_key_path_and_non_explicit_transaction(
    control_database,
) -> None:
    with pytest.raises(ValueError, match="absolute path"):
        _scope(Path("relative/keys"))

    scope = _scope(Path("/absolute/not-read-at-construction"))
    with control_database.new_session() as session:
        with pytest.raises(RuntimeError, match="explicit active transaction"):
            with scope(session):
                pytest.fail("scope must not be entered")
