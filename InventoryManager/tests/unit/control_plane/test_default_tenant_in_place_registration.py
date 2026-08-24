from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa

from app import create_app, db
from app.models.database_identity import TenantDatabaseIdentity
from app.services.migration.default_tenant_registration import (
    DefaultTenantInPlaceRegistrationService,
    DefaultTenantRegistrationConflictError,
    DefaultTenantRegistrationInputError,
    DefaultTenantRegistrationTransactionError,
    DefaultTenantRouteRegistration,
)
from inventory_control import ControlBase, ControlDatabase
from inventory_control.crypto import RootKey
from inventory_control.default_migration import (
    DefaultTenantMigrationManifest,
    bind_default_tenant_identity_inputs,
)
from inventory_control.models import (
    DatabaseIdentityControlRecord,
    Tenant,
    TenantDatabase,
    TenantMembership,
    User,
)
from tests.support.test_database import build_mysql_test_config


TENANT_UUID = UUID("30000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("30000000-0000-4000-8000-000000000002")
PLAN_UUID = UUID("30000000-0000-4000-8000-000000000003")
NOW = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)
ROOT_KEY = RootKey(version=7, material=bytes(range(32)))


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _identity_inputs(*, phone: str = "13800138000"):
    return bind_default_tenant_identity_inputs(
        root_key=ROOT_KEY,
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        migration_idempotency_key="default-tenant-registration-v1",
        display_name="光影 租界",
        first_admin_phone=phone,
    )


def _manifest():
    inputs = _identity_inputs()
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="default-tenant-registration-v1",
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        source_schema_name="inventory_management",
        baseline_migration_id="initial-baseline-v1",
        core_plan_revision_uuid=PLAN_UUID,
        control_schema_head="202608220026",
        tenant_schema_head="20260824_legacy_history",
        source_snapshot_digest=_digest("source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=inputs.display_name_commitment,
        first_admin_phone_input_commitment=(
            inputs.first_admin_phone_commitment
        ),
    )


def _route():
    return DefaultTenantRouteRegistration(
        database_instance_key="isolated-mysql-test",
        schema_generation=9,
        schema_digest=_digest("tenant-schema"),
        dml_username="tenant_dml_g1",
        dml_credential_generation=1,
        dml_root_key_version=7,
        dml_derivation_version=1,
        platform_read_username="tenant_read_g1",
        platform_read_credential_generation=1,
        platform_read_root_key_version=7,
        platform_read_derivation_version=1,
    )


@pytest.fixture
def databases(mysql_routed_database):
    application = create_app(build_mysql_test_config())
    control = mysql_routed_database
    with application.app_context():
        try:
            yield application, control
        finally:
            db.session.remove()


def _write_tenant_identity(manifest):
    session = db.session()
    with session.begin():
        return DefaultTenantInPlaceRegistrationService(
            clock=lambda: NOW
        ).write_tenant_database_identity(
            session,
            manifest=manifest,
            schema_generation=9,
        )


def test_in_place_registration_creates_and_exactly_replays_both_sides(
    databases,
) -> None:
    _application, control = databases
    manifest = _manifest()
    inputs = _identity_inputs()
    route = _route()
    tenant_first = _write_tenant_identity(manifest)
    tenant_replay = _write_tenant_identity(manifest)
    service = DefaultTenantInPlaceRegistrationService(clock=lambda: NOW)
    with control.transaction() as session:
        control_first = service.write_control_registration(
            session,
            manifest=manifest,
            identity_inputs=inputs,
            tenant_identity=tenant_first,
            route=route,
        )
    with control.transaction() as session:
        control_replay = service.write_control_registration(
            session,
            manifest=manifest,
            identity_inputs=inputs,
            tenant_identity=tenant_replay,
            route=route,
        )

    assert tenant_first.created is True
    assert tenant_replay.created is False
    assert tenant_replay.identity_created_at == tenant_first.identity_created_at
    assert control_first.created is True
    assert control_replay.created is False
    assert control_replay.admin_user_uuid == control_first.admin_user_uuid
    assert control_replay.admin_membership_uuid == (
        control_first.admin_membership_uuid
    )
    identity = db.session.scalar(sa.select(TenantDatabaseIdentity))
    assert identity.tenant_id == str(TENANT_UUID)
    assert identity.database_uuid == str(DATABASE_UUID)
    assert identity.schema_generation == 9
    with control.new_session() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        user = session.get(User, str(control_first.admin_user_uuid))
        membership = session.get(
            TenantMembership,
            str(control_first.admin_membership_uuid),
        )
        database_route = session.get(TenantDatabase, str(TENANT_UUID))
        control_identity = session.get(
            DatabaseIdentityControlRecord,
            str(TENANT_UUID),
        )
        assert tenant.name == "光影 租界"
        assert tenant.status == "provisioning"
        assert user.phone_e164 == "+8613800138000"
        assert user.phone_verified_at is None
        assert user.status == "unverified"
        assert membership.role_key == "admin"
        assert membership.source_type == "migration"
        assert database_route.database_name == "inventory_management"
        assert database_route.status == "provisional"
        assert database_route.dml_username != (
            database_route.platform_read_username
        )
        assert control_identity.expected_schema_sha256 == route.schema_digest
        assert control_identity.observed_schema_sha256 == route.schema_digest


def test_changed_controlled_identity_is_rejected_before_control_write(
    databases,
) -> None:
    _application, control = databases
    manifest = _manifest()
    tenant_identity = _write_tenant_identity(manifest)

    with control.transaction() as session:
        with pytest.raises(DefaultTenantRegistrationInputError):
            DefaultTenantInPlaceRegistrationService().write_control_registration(
                session,
                manifest=manifest,
                identity_inputs=_identity_inputs(phone="13900139000"),
                tenant_identity=tenant_identity,
                route=_route(),
            )

    with control.new_session() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(Tenant)) == 0
        assert session.scalar(sa.select(sa.func.count()).select_from(User)) == 0


def test_existing_tenant_identity_mismatch_is_fail_closed(databases) -> None:
    _application, _control = databases
    manifest = _manifest()
    db.session.add(
        TenantDatabaseIdentity(
            singleton_key=1,
            tenant_id=str(TENANT_UUID),
            database_uuid="30000000-0000-4000-8000-000000000099",
            schema_generation=9,
        )
    )
    db.session.commit()

    with pytest.raises(DefaultTenantRegistrationConflictError):
        _write_tenant_identity(manifest)


def test_partial_control_identity_never_gets_silently_completed(databases) -> None:
    _application, control = databases
    manifest = _manifest()
    tenant_identity = _write_tenant_identity(manifest)
    with control.transaction() as session:
        session.add(
            Tenant(
                id=str(TENANT_UUID),
                name="光影 租界",
                status="provisioning",
                timezone="Asia/Shanghai",
                locale="zh-CN",
            )
        )

    with control.transaction() as session:
        with pytest.raises(DefaultTenantRegistrationConflictError):
            DefaultTenantInPlaceRegistrationService().write_control_registration(
                session,
                manifest=manifest,
                identity_inputs=_identity_inputs(),
                tenant_identity=tenant_identity,
                route=_route(),
            )


def test_both_writers_require_explicit_caller_transactions(databases) -> None:
    _application, control = databases
    manifest = _manifest()
    tenant_session = db.session()
    with pytest.raises(DefaultTenantRegistrationTransactionError):
        DefaultTenantInPlaceRegistrationService().write_tenant_database_identity(
            tenant_session,
            manifest=manifest,
            schema_generation=9,
        )
    with control.new_session() as control_session:
        with pytest.raises(DefaultTenantRegistrationTransactionError):
            DefaultTenantInPlaceRegistrationService().write_control_registration(
                control_session,
                manifest=manifest,
                identity_inputs=_identity_inputs(),
                tenant_identity=(
                    # The transaction guard is reached only after all public
                    # inputs validate, so use a valid detached result.
                    _write_tenant_identity(manifest)
                ),
                route=_route(),
            )


def test_route_registration_rejects_shared_dml_and_read_identity() -> None:
    with pytest.raises(DefaultTenantRegistrationInputError):
        DefaultTenantRouteRegistration(
            database_instance_key="isolated-mysql-test",
            schema_generation=9,
            schema_digest=_digest("tenant-schema"),
            dml_username="shared_user",
            dml_credential_generation=1,
            dml_root_key_version=7,
            dml_derivation_version=1,
            platform_read_username="shared_user",
            platform_read_credential_generation=1,
            platform_read_root_key_version=7,
            platform_read_derivation_version=1,
        )
