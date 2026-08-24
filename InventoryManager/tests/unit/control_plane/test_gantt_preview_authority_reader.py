from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import event

from inventory_control import ControlBase, ControlDatabase
from inventory_control.crypto import RootKeyLifecycle
from inventory_control.domain.rbac import TenantRole
from inventory_control.domain.tenant_gate import EffectiveTenantGate
from inventory_control.models import (
    DisasterRecoveryRun,
    PlanRevision,
    PlatformRootKeyVersion,
    Subscription,
    Tenant,
    TenantMembership,
    TenantRecoveryHold,
    TenantSuspension,
    TenantUserSession,
    User,
)
from inventory_control.proofs import (
    GanttPreviewAuthorityError,
    SqlAlchemyGanttPreviewAuthorityReader,
)
from inventory_control.tenant_http import AuthContext


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
FUTURE = datetime(2099, 1, 1, tzinfo=timezone.utc)
TENANT_ID = "10000000-0000-4000-8000-000000000001"
USER_ID = "10000000-0000-4000-8000-000000000002"
SESSION_ID = "10000000-0000-4000-8000-000000000003"
RUN_ID = "10000000-0000-4000-8000-000000000004"
HOLD_ID = "10000000-0000-4000-8000-000000000005"
MEMBERSHIP_ID = "10000000-0000-4000-8000-000000000006"
DATABASE_ID = "10000000-0000-4000-8000-000000000007"
PLAN_ID = "10000000-0000-4000-8000-000000000008"
SUBSCRIPTION_ID = "10000000-0000-4000-8000-000000000009"
ROOT_MATERIAL = bytes(range(32))
ROOT_VERSION = 7
ENTITLEMENTS = {"features": {}, "limits": {"member_seats": 10}}
ENTITLEMENTS_DIGEST = b"e" * 32


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


@pytest.fixture
def root_key_directory(tmp_path: Path) -> Path:
    key_path = tmp_path / f"v{ROOT_VERSION}"
    key_path.write_bytes(base64.b64encode(ROOT_MATERIAL) + b"\n")
    key_path.chmod(0o400)
    return tmp_path


def _auth_context(**changes) -> AuthContext:
    values = {
        "session_id": SESSION_ID,
        "user_id": USER_ID,
        "membership_id": MEMBERSHIP_ID,
        "tenant_id": TENANT_ID,
        "role": TenantRole.OPERATOR,
        "user_auth_version": 4,
        "tenant_access_version": 8,
        "tenant_timezone": "Asia/Shanghai",
        "effective_gate": EffectiveTenantGate.ACTIVE,
    }
    values.update(changes)
    return AuthContext(**values)


def _seed(database: ControlDatabase) -> None:
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
            DisasterRecoveryRun(
                id=RUN_ID,
                kind="initial_baseline",
                policy_version=1,
                status="completed",
                expected_survivor_count=1,
                actual_survivor_count=1,
                sealed_coverage_digest=b"s" * 32,
                final_coverage_digest=b"f" * 32,
                host_installation_fingerprint="a" * 64,
                deployment_marker_fingerprint="b" * 64,
                row_version=1,
                started_at=NOW,
                reviewing_at=NOW,
                completed_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            Tenant(
                id=TENANT_ID,
                status="active",
                access_version=8,
                row_version=3,
                timezone="Asia/Shanghai",
            )
        )
        session.add(
            User(
                id=USER_ID,
                phone_region_iso2="CN",
                phone_e164="+8613800000000",
                phone_normalization_version=1,
                phone_metadata_version="cn-mobile-v1",
                phone_verified_at=NOW,
                status="active",
                auth_version=4,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            TenantMembership(
                id=MEMBERSHIP_ID,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                role_key="operator",
                status="active",
                source_type="migration",
                row_version=2,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            TenantUserSession(
                id=SESSION_ID,
                user_id=USER_ID,
                token_digest_sha256=b"t" * 32,
                csrf_digest_sha256=b"c" * 32,
                auth_version_at_issue=4,
                tenant_access_version_at_issue=8,
                policy_version=1,
                csrf_generation=1,
                idle_timeout_seconds=3600,
                created_at=NOW,
                last_seen_at=NOW,
                idle_expires_at=FUTURE - timedelta(days=1),
                absolute_expires_at=FUTURE,
            )
        )
        session.add(
            TenantRecoveryHold(
                id=HOLD_ID,
                recovery_run_id=RUN_ID,
                tenant_id=TENANT_ID,
                database_uuid=DATABASE_ID,
                state="released",
                hold_revision=2,
                snapshot_underlying_status="active",
                snapshot_access_version=8,
                expected_dml_login_state_version=1,
                dml_convergence_status="active",
                held_at=NOW,
                released_at=NOW,
                row_version=2,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            PlanRevision(
                id=PLAN_ID,
                code="core",
                revision=1,
                name="Core",
                entitlements_schema_version=1,
                entitlements_json=ENTITLEMENTS,
                entitlements_digest=ENTITLEMENTS_DIGEST,
                active=True,
            )
        )
        session.add(
            Subscription(
                id=SUBSCRIPTION_ID,
                tenant_id=TENANT_ID,
                plan_revision_uuid=PLAN_ID,
                entitlements_schema_version=1,
                entitlements_json=ENTITLEMENTS,
                entitlements_digest=ENTITLEMENTS_DIGEST,
                status="active",
                expires_at=FUTURE,
                row_version=1,
                provider="manual",
            )
        )


def _reader(database, directory):
    return SqlAlchemyGanttPreviewAuthorityReader(
        control_database=database,
        root_key_directory=directory,
    )


def test_reader_returns_current_database_authority_in_one_read_only_transaction(
    control_database,
    root_key_directory,
) -> None:
    _seed(control_database)
    statements: list[str] = []
    transactions: list[None] = []

    def capture_sql(_connection, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    def capture_begin(_connection):
        transactions.append(None)

    event.listen(control_database.engine, "before_cursor_execute", capture_sql)
    event.listen(control_database.engine, "begin", capture_begin)
    try:
        current = _reader(
            control_database, root_key_directory
        ).read_current(auth_context=_auth_context())
    finally:
        event.remove(
            control_database.engine, "before_cursor_execute", capture_sql
        )
        event.remove(control_database.engine, "begin", capture_begin)

    assert len(transactions) == 1
    assert statements
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    assert str(current.authority.tenant_uuid) == TENANT_ID
    assert str(current.authority.actor_user_uuid) == USER_ID
    assert str(current.authority.actor_session_uuid) == SESSION_ID
    assert str(current.authority.recovery_run_uuid) == RUN_ID
    assert str(current.authority.recovery_hold_uuid) == HOLD_ID
    assert current.authority.recovery_hold_revision == 2
    assert str(current.membership_uuid) == MEMBERSHIP_ID
    assert current.role is TenantRole.OPERATOR
    assert current.session_is_current is True
    assert current.effective_gate is EffectiveTenantGate.ACTIVE
    assert current.active_root_key.version == ROOT_VERSION
    assert current.active_root_key._material_bytes() == ROOT_MATERIAL
    assert current.database_now.tzinfo is timezone.utc
    assert current.database_now.microsecond == 0
    assert current.tenant_timezone == "Asia/Shanghai"
    assert ROOT_MATERIAL.hex() not in repr(current)


def test_lock_current_keeps_transaction_open_until_scope_exit_and_rolls_back(
    control_database,
    root_key_directory,
) -> None:
    _seed(control_database)
    events: list[str] = []

    def capture_begin(_connection):
        events.append("begin")

    def capture_commit(_connection):
        events.append("commit")

    def capture_rollback(_connection):
        events.append("rollback")

    event.listen(control_database.engine, "begin", capture_begin)
    event.listen(control_database.engine, "commit", capture_commit)
    event.listen(control_database.engine, "rollback", capture_rollback)
    reader = _reader(control_database, root_key_directory)
    try:
        with reader.lock_current(auth_context=_auth_context()) as current:
            assert current.session_is_current is True
            assert events == ["begin"]
        assert events == ["begin", "commit"]

        with pytest.raises(RuntimeError, match="tenant transaction failed"):
            with reader.lock_current(auth_context=_auth_context()):
                assert events == ["begin", "commit", "begin"]
                raise RuntimeError("tenant transaction failed")
        assert events == ["begin", "commit", "begin", "rollback"]
    finally:
        event.remove(control_database.engine, "begin", capture_begin)
        event.remove(control_database.engine, "commit", capture_commit)
        event.remove(control_database.engine, "rollback", capture_rollback)


@pytest.mark.parametrize(
    "context_change",
    [
        {"session_id": "20000000-0000-4000-8000-000000000003"},
        {"user_id": "20000000-0000-4000-8000-000000000002"},
        {"membership_id": "20000000-0000-4000-8000-000000000006"},
        {"tenant_id": "20000000-0000-4000-8000-000000000001"},
        {"role": TenantRole.ADMIN},
        {"user_auth_version": 5},
        {"tenant_access_version": 9},
    ],
)
def test_auth_context_is_only_compared_to_current_rows(
    control_database,
    root_key_directory,
    context_change,
) -> None:
    _seed(control_database)

    with pytest.raises(GanttPreviewAuthorityError) as caught:
        _reader(control_database, root_key_directory).read_current(
            auth_context=_auth_context(**context_change)
        )

    assert str(caught.value) == "current Gantt preview authority is unavailable"


@pytest.mark.parametrize(
    ("model", "field", "value"),
    [
        (TenantUserSession, "revoked_at", NOW),
        (User, "auth_version", 5),
        (TenantMembership, "role_key", "admin"),
        (Tenant, "access_version", 9),
        (Tenant, "status", "expired"),
        (Tenant, "timezone", "Not/A-Timezone"),
        (Subscription, "status", "expired"),
        (TenantRecoveryHold, "state", "held"),
        (DisasterRecoveryRun, "status", "reviewing"),
    ],
)
def test_current_identity_gate_recovery_or_timezone_drift_fails_closed(
    control_database,
    root_key_directory,
    model,
    field,
    value,
) -> None:
    _seed(control_database)
    with control_database.transaction() as session:
        row = session.scalar(sa.select(model).with_for_update())
        setattr(row, field, value)
        if model is TenantUserSession and field == "revoked_at":
            row.revoked_reason_code = "test_revocation"
        if model is TenantRecoveryHold and field == "state":
            row.released_at = None

    with pytest.raises(GanttPreviewAuthorityError) as caught:
        _reader(control_database, root_key_directory).read_current(
            auth_context=_auth_context()
        )

    assert str(caught.value) == "current Gantt preview authority is unavailable"


def test_unresolved_suspension_denies_even_if_tenant_status_drifted_active(
    control_database,
    root_key_directory,
) -> None:
    _seed(control_database)
    with control_database.transaction() as session:
        session.add(
            TenantSuspension(
                id="10000000-0000-4000-8000-000000000010",
                tenant_id=TENANT_ID,
                state="freezing",
                initial_reason_code="ops",
                barrier_generation=1,
                committed_tenant_row_version=3,
                committed_access_version=8,
                requested_at=NOW,
                row_version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    with pytest.raises(GanttPreviewAuthorityError, match="unavailable"):
        _reader(control_database, root_key_directory).read_current(
            auth_context=_auth_context()
        )


def test_missing_current_hold_fails_without_fabricating_no_hold_identity(
    control_database,
    root_key_directory,
) -> None:
    _seed(control_database)
    with control_database.transaction() as session:
        hold = session.get(TenantRecoveryHold, HOLD_ID)
        session.delete(hold)

    with pytest.raises(GanttPreviewAuthorityError, match="unavailable"):
        _reader(control_database, root_key_directory).read_current(
            auth_context=_auth_context()
        )


def test_root_registry_or_file_drift_fails_without_path_or_material_disclosure(
    control_database,
    root_key_directory,
) -> None:
    _seed(control_database)
    key_path = root_key_directory / f"v{ROOT_VERSION}"
    key_path.chmod(0o600)
    key_path.write_bytes(base64.b64encode(b"x" * 32) + b"\n")
    key_path.chmod(0o400)

    with pytest.raises(GanttPreviewAuthorityError) as caught:
        _reader(control_database, root_key_directory).read_current(
            auth_context=_auth_context()
        )

    assert str(caught.value) == "current Gantt preview authority is unavailable"
    assert str(root_key_directory) not in str(caught.value)
    assert (b"x" * 32).hex() not in str(caught.value)


def test_reader_has_no_relative_or_environment_root_path_fallback(
    control_database,
) -> None:
    with pytest.raises(ValueError, match="absolute"):
        SqlAlchemyGanttPreviewAuthorityReader(
            control_database=control_database,
            root_key_directory="keys",
        )
