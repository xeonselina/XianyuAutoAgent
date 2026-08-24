from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.tenancy import TenancyError, TenancyErrorCode
from inventory_control.models import (
    DatabaseIdentityControlRecord,
    DisasterRecoveryRun,
    Tenant,
    TenantDatabase,
)
from inventory_control.routing import (
    AccountKind,
    AccountLoginState,
    SqlAlchemyRouteRepository,
    TenantRouteStatus,
)


TENANT_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
DATABASE_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
COMMIT_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


@pytest.fixture
def engine(mysql_control_database):
    return mysql_control_database.engine


def seed_ready_route(engine, *, desired="active", observed="active") -> None:
    with Session(engine) as session, session.begin():
        tenant = Tenant(
            id=str(TENANT_ID),
            name="Tenant",
            slug="tenant",
            status="active",
            access_version=7,
            row_version=3,
        )
        route = TenantDatabase(
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
            dml_root_key_version=4,
            dml_derivation_version=1,
            route_version=9,
            dml_desired_login_state=desired,
            dml_observed_login_state=observed,
            dml_login_state_version=5,
            platform_read_username="tenant_read_g3",
            platform_read_credential_generation=3,
            platform_read_root_key_version=4,
            platform_read_derivation_version=2,
            platform_read_route_version=11,
            row_version=6,
        )
        identity = DatabaseIdentityControlRecord(
            tenant_id=str(TENANT_ID),
            database_uuid=str(DATABASE_ID),
            expected_schema_generation=3,
            observed_schema_generation=3,
            identity_created_at=sa.func.current_timestamp(),
        )
        session.add_all((tenant, route, identity))


def test_repository_projects_independent_published_five_tuples(engine):
    seed_ready_route(engine)

    with Session(engine) as session, session.begin():
        repository = SqlAlchemyRouteRepository(session=session)
        dml = repository.get_current_ready_route(
            tenant_uuid=TENANT_ID,
            access_version=7,
            account_kind=AccountKind.DML,
        )
        platform_read = repository.get_current_ready_route(
            tenant_uuid=TENANT_ID,
            access_version=7,
            account_kind=AccountKind.PLATFORM_READ,
        )

    assert dml is not None
    assert dml.status is TenantRouteStatus.READY
    assert dml.account_kind is AccountKind.DML
    assert dml.username == "tenant_dml_g2"
    assert dml.credential_generation == 2
    assert dml.root_key_version == 4
    assert dml.derivation_version == 1
    assert dml.route_version == 9
    assert dml.desired_login_state is AccountLoginState.ACTIVE
    assert dml.expected_schema_generation == 3

    assert platform_read is not None
    assert platform_read.account_kind is AccountKind.PLATFORM_READ
    assert platform_read.username == "tenant_read_g3"
    assert platform_read.credential_generation == 3
    assert platform_read.root_key_version == 4
    assert platform_read.derivation_version == 2
    assert platform_read.route_version == 11
    assert platform_read.routing_identity() != dml.routing_identity()


def test_repository_requires_caller_transaction_and_exact_access_version(engine):
    seed_ready_route(engine)

    with Session(engine) as session:
        repository = SqlAlchemyRouteRepository(session=session)
        with pytest.raises(TenancyError) as caught:
            repository.get_current_ready_route(
                tenant_uuid=TENANT_ID,
                access_version=7,
                account_kind=AccountKind.DML,
            )
        assert caught.value.code == TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE.value

        with session.begin():
            assert (
                repository.get_current_ready_route(
                    tenant_uuid=TENANT_ID,
                    access_version=6,
                    account_kind=AccountKind.DML,
                )
                is None
            )


def test_repository_never_uses_platform_read_as_dml_fallback(engine):
    seed_ready_route(engine, desired="active", observed="locked")

    with Session(engine) as session, session.begin():
        repository = SqlAlchemyRouteRepository(session=session)
        dml = repository.get_current_ready_route(
            tenant_uuid=TENANT_ID,
            access_version=7,
            account_kind=AccountKind.DML,
        )
        platform_read = repository.get_current_ready_route(
            tenant_uuid=TENANT_ID,
            access_version=7,
            account_kind=AccountKind.PLATFORM_READ,
        )

    assert dml is None
    assert platform_read is not None
    assert platform_read.username == "tenant_read_g3"


def test_repository_returns_none_for_nonready_or_incomplete_identity(engine):
    seed_ready_route(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.update(TenantDatabase)
            .where(TenantDatabase.tenant_id == str(TENANT_ID))
            .values(status="provisional")
        )

    with Session(engine) as session, session.begin():
        repository = SqlAlchemyRouteRepository(session=session)
        assert (
            repository.get_current_ready_route(
                tenant_uuid=TENANT_ID,
                access_version=7,
                account_kind=AccountKind.DML,
            )
            is None
        )

    with engine.begin() as connection:
        connection.execute(
            sa.update(TenantDatabase)
            .where(TenantDatabase.tenant_id == str(TENANT_ID))
            .values(status="ready")
        )
        connection.execute(
            sa.update(DatabaseIdentityControlRecord)
            .where(DatabaseIdentityControlRecord.tenant_id == str(TENANT_ID))
            .values(observed_schema_generation=None)
        )

    with Session(engine) as session, session.begin():
        repository = SqlAlchemyRouteRepository(session=session)
        assert (
            repository.get_current_ready_route(
                tenant_uuid=TENANT_ID,
                access_version=7,
                account_kind=AccountKind.PLATFORM_READ,
            )
            is None
        )


def test_repository_holds_revision_digest_or_route_metadata_drift(engine):
    seed_ready_route(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.update(DatabaseIdentityControlRecord)
            .where(DatabaseIdentityControlRecord.tenant_id == str(TENANT_ID))
            .values(
                expected_schema_revision="tenant-schema-4",
                expected_schema_sha256=b"x" * 32,
                observed_schema_revision="tenant-schema-4",
                observed_schema_sha256=b"x" * 32,
            )
        )

    with Session(engine) as session, session.begin():
        repository = SqlAlchemyRouteRepository(session=session)
        assert (
            repository.get_current_ready_route(
                tenant_uuid=TENANT_ID,
                access_version=7,
                account_kind=AccountKind.DML,
            )
            is None
        )


def test_repository_signature_does_not_accept_database_or_dsn(engine):
    seed_ready_route(engine)
    with Session(engine) as session, session.begin():
        repository = SqlAlchemyRouteRepository(session=session)
        with pytest.raises(TypeError):
            repository.get_current_ready_route(
                tenant_uuid=TENANT_ID,
                access_version=7,
                account_kind=AccountKind.DML,
                database_name="client_database",
            )
        with pytest.raises(TypeError):
            repository.get_current_ready_route(
                tenant_uuid=TENANT_ID,
                access_version=7,
                account_kind=AccountKind.DML,
                dsn="mysql://client-controlled",
            )


def test_route_metadata_has_no_password_or_secret_storage_columns():
    column_names = {column.name for column in TenantDatabase.__table__.columns}
    assert not any(
        marker in column_name
        for column_name in column_names
        for marker in ("password", "hash", "ciphertext", "secret", "dsn")
    )
    assert "dml_username" in column_names
    assert "platform_read_username" in column_names
