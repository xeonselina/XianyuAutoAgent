from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from inventory_control import ControlBase, ControlDatabase, PlatformRootKeyVersion
from inventory_control.crypto import (
    RootKeyLifecycle,
    RootKeyLifecycleConflictError,
    RootKeyLifecycleTransactionError,
    RootKeyReferenceError,
    SqlAlchemyRootKeyLifecycleService,
)
from inventory_control.models.foundation import Tenant, TenantDatabase


NOW = datetime(2026, 8, 22, 6, 0, tzinfo=timezone.utc)
FP1 = hashlib.sha256(b"root-key-one").digest()
FP2 = hashlib.sha256(b"root-key-two").digest()
FP3 = hashlib.sha256(b"root-key-three").digest()


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


def _service(session, *, now=NOW):
    return SqlAlchemyRootKeyLifecycleService(
        session=session,
        database_clock=lambda _session: now,
    )


def _bootstrap(control_database):
    with control_database.transaction() as session:
        return _service(session).bootstrap(version=1, fingerprint_sha256=FP1)


def test_bootstrap_is_caller_transactional_and_exactly_replayable(control_database):
    result = _bootstrap(control_database)
    assert result.version == 1
    assert result.status is RootKeyLifecycle.ACTIVE
    assert result.previous_active_version is None
    assert result.activated_at == NOW
    assert result.replayed is False

    with control_database.transaction() as session:
        replay = _service(session).bootstrap(version=1, fingerprint_sha256=FP1)
        assert replay == type(replay)(
            version=1,
            status=RootKeyLifecycle.ACTIVE,
            previous_active_version=None,
            activated_at=NOW,
            retired_at=None,
            replayed=True,
        )

    with control_database.transaction() as session:
        with pytest.raises(
            RootKeyLifecycleConflictError,
            match="ROOT_KEY_REGISTRY_ALREADY_BOOTSTRAPPED",
        ):
            _service(session).bootstrap(version=1, fingerprint_sha256=FP2)


def test_activate_new_demotes_old_version_and_preserves_single_active(control_database):
    _bootstrap(control_database)
    activated_at = NOW + timedelta(hours=1)
    with control_database.transaction() as session:
        result = _service(session, now=activated_at).activate_new(
            expected_active_version=1,
            new_version=2,
            fingerprint_sha256=FP2,
        )
        assert result.previous_active_version == 1
        assert result.status is RootKeyLifecycle.ACTIVE
        assert result.replayed is False

    with control_database.transaction() as session:
        rows = tuple(
            session.scalars(
                sa.select(PlatformRootKeyVersion).order_by(
                    PlatformRootKeyVersion.version
                )
            )
        )
        assert [(row.version, row.status) for row in rows] == [
            (1, "legacy"),
            (2, "active"),
        ]
        replay = _service(session).activate_new(
            expected_active_version=1,
            new_version=2,
            fingerprint_sha256=FP2,
        )
        assert replay.replayed is True
        assert replay.version == 2


def test_activate_replay_requires_the_expected_predecessor(control_database):
    with control_database.transaction() as session:
        _service(session).bootstrap(version=2, fingerprint_sha256=FP2)
    with control_database.transaction() as session:
        with pytest.raises(
            RootKeyLifecycleConflictError,
            match="ROOT_KEY_VERSION_ALREADY_EXISTS",
        ):
            _service(session).activate_new(
                expected_active_version=1,
                new_version=2,
                fingerprint_sha256=FP2,
            )


@pytest.mark.parametrize(
    ("expected, version, fingerprint, code"),
    [
        (2, 2, FP2, "ROOT_KEY_VERSION_NOT_MONOTONIC"),
        (9, 10, FP3, "ROOT_KEY_ACTIVE_VERSION_CHANGED"),
        (1, 3, FP1, "ROOT_KEY_FINGERPRINT_ALREADY_EXISTS"),
    ],
)
def test_activate_new_rejects_stale_or_reused_identity(
    control_database,
    expected,
    version,
    fingerprint,
    code,
):
    _bootstrap(control_database)
    with control_database.transaction() as session:
        with pytest.raises(RootKeyLifecycleConflictError, match=code):
            _service(session).activate_new(
                expected_active_version=expected,
                new_version=version,
                fingerprint_sha256=fingerprint,
            )


def test_reference_inventory_blocks_retirement_until_routes_are_rotated(
    control_database,
):
    _bootstrap(control_database)
    with control_database.transaction() as session:
        _service(session).activate_new(
            expected_active_version=1,
            new_version=2,
            fingerprint_sha256=FP2,
        )
    with control_database.transaction() as session:
        tenant = Tenant(
            id="00000000-0000-4000-8000-000000000001",
            status="active",
            access_version=1,
            row_version=1,
        )
        route = TenantDatabase(
            tenant_id=tenant.id,
            database_uuid="00000000-0000-4000-8000-000000000003",
            database_instance_key="local-test-instance",
            database_name="tenant_test_only",
            status="provisional",
            route_version=1,
            row_version=1,
            dml_username="tenant_dml_v1",
            dml_credential_generation=1,
            dml_root_key_version=1,
            dml_derivation_version=1,
            dml_desired_login_state="active",
            dml_observed_login_state="active",
            dml_login_state_version=1,
            platform_read_username="tenant_read_v1",
            platform_read_credential_generation=1,
            platform_read_root_key_version=1,
            platform_read_derivation_version=1,
            platform_read_route_version=1,
        )
        session.add_all([tenant, route])

    with control_database.transaction() as session:
        service = _service(session)
        inventory = service.inspect_references(version=1)
        assert inventory.total_references == 2
        assert {
            (item.table_name, item.column_name, item.count)
            for item in inventory.references
        } == {
            ("tenant_databases", "dml_root_key_version", 1),
            ("tenant_databases", "platform_read_root_key_version", 1),
        }
        with pytest.raises(RootKeyReferenceError) as captured:
            service.retire(version=1, expected_active_version=2)
        assert captured.value.inventory == inventory

    with control_database.transaction() as session:
        route = session.get(
            TenantDatabase,
            "00000000-0000-4000-8000-000000000001",
        )
        route.dml_root_key_version = 2
        route.platform_read_root_key_version = 2

    retired_at = NOW + timedelta(hours=2)
    with control_database.transaction() as session:
        result = _service(session, now=retired_at).retire(
            version=1,
            expected_active_version=2,
        )
        assert result.status is RootKeyLifecycle.RETIRED
        assert result.retired_at == retired_at
        assert result.replayed is False

    with control_database.transaction() as session:
        replay = _service(session).retire(
            version=1,
            expected_active_version=2,
        )
        assert replay.replayed is True
        assert replay.retired_at == retired_at


def test_active_version_cannot_be_retired(control_database):
    _bootstrap(control_database)
    with control_database.transaction() as session:
        with pytest.raises(
            RootKeyLifecycleConflictError,
            match="ROOT_KEY_VERSION_NOT_LEGACY",
        ):
            _service(session).retire(version=1, expected_active_version=1)


def test_mutations_require_a_clean_explicit_caller_transaction(control_database):
    with control_database.new_session() as session:
        with pytest.raises(
            RootKeyLifecycleTransactionError,
            match="ROOT_KEY_EXPLICIT_TRANSACTION_REQUIRED",
        ):
            _service(session).bootstrap(version=1, fingerprint_sha256=FP1)

    with control_database.new_session() as session:
        session.scalar(sa.select(sa.literal(1)))
        with pytest.raises(
            RootKeyLifecycleTransactionError,
            match="ROOT_KEY_EXPLICIT_TRANSACTION_REQUIRED",
        ):
            _service(session).bootstrap(version=1, fingerprint_sha256=FP1)

    with control_database.new_session() as session:
        transaction = session.begin()
        session.add(
            PlatformRootKeyVersion(
                version=1,
                fingerprint_sha256=FP1,
                status="active",
                activated_at=NOW,
            )
        )
        with pytest.raises(
            RootKeyLifecycleTransactionError,
            match="ROOT_KEY_CLEAN_TRANSACTION_REQUIRED",
        ):
            _service(session).bootstrap(version=1, fingerprint_sha256=FP1)
        transaction.rollback()


def test_registry_lifecycle_has_no_key_material_or_filesystem_parameter():
    import inspect

    source = inspect.getsource(SqlAlchemyRootKeyLifecycleService)
    lowered = source.lower()
    assert "password" not in lowered
    assert "key_material" not in lowered
    assert "directory" not in lowered
    assert "path" not in lowered
