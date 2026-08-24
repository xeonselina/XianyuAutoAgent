from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import UUID

import pytest
import sqlalchemy as sa

from inventory_control import ControlBase, ControlDatabase
from inventory_control.fleet_migrations import (
    FleetMigrationControlIdentityError,
    FleetMigrationObservation,
    FleetMigrationPersistenceService,
    FleetMigrationState,
    FleetMigrationTransactionError,
    FleetRouteDisposition,
    FleetSchemaIdentity,
    FleetSchemaOperationFence,
)
from inventory_control.fleet_migrations.persistence import (
    _read_database_utc_now,
)
from inventory_control.fleet_migrations.domain import (
    FleetMigrationObservationRejected,
)
from inventory_control.models import (
    DatabaseIdentityControlRecord,
    PlatformSchemaOperationLease,
    Tenant,
    TenantDatabase,
    TenantFleetMigration,
)
from inventory_control.routing import AccountKind, SqlAlchemyRouteRepository
from inventory_control.schema_operations import (
    SCHEMA_OPERATION_LEASE_KEY,
    SchemaOperationLeaseFenceConflict,
    SchemaOperationLeasePersistenceService,
    SchemaOperationLeaseState,
    SchemaOperationPurpose,
)


NOW = datetime(2026, 8, 22, 12, 0, 0, 123456, tzinfo=timezone.utc)
TENANT_UUID = UUID("a1000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("a1000000-0000-4000-8000-000000000002")
MIGRATION_UUID = UUID("a1000000-0000-4000-8000-000000000003")
COMMIT_UUID = UUID("a1000000-0000-4000-8000-000000000004")
CLAIM_A = UUID("a1000000-0000-4000-8000-000000000005")
CLAIM_B = UUID("a1000000-0000-4000-8000-000000000006")


@pytest.fixture
def control_database(mysql_control_database):
    with mysql_control_database.transaction() as session:
        session.add_all(
            (
                Tenant(
                    id=str(TENANT_UUID),
                    name="Tenant",
                    slug="tenant",
                    status="active",
                    access_version=1,
                    row_version=1,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                TenantDatabase(
                    tenant_id=str(TENANT_UUID),
                    database_uuid=str(DATABASE_UUID),
                    database_instance_key="test-instance",
                    database_name="tenant_inventory",
                    status="ready",
                    schema_version="rev_8",
                    activated_by_registration_commit_uuid=str(COMMIT_UUID),
                    activation_route_version=1,
                    activation_credential_generation=1,
                    dml_username="tenant_dml_g1",
                    dml_credential_generation=1,
                    dml_root_key_version=1,
                    dml_derivation_version=1,
                    route_version=1,
                    dml_desired_login_state="active",
                    dml_observed_login_state="active",
                    dml_login_state_version=1,
                    platform_read_username="tenant_read_g1",
                    platform_read_credential_generation=1,
                    platform_read_root_key_version=1,
                    platform_read_derivation_version=1,
                    platform_read_route_version=1,
                    row_version=1,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                DatabaseIdentityControlRecord(
                    tenant_id=str(TENANT_UUID),
                    database_uuid=str(DATABASE_UUID),
                    expected_schema_generation=8,
                    observed_schema_generation=8,
                    identity_created_at=NOW,
                    last_verified_at=NOW,
                    created_at=NOW,
                ),
                PlatformSchemaOperationLease(
                    lease_key=SCHEMA_OPERATION_LEASE_KEY,
                    state=SchemaOperationLeaseState.AVAILABLE.value,
                    generation=0,
                    fencing_token=0,
                    row_version=1,
                    observed_at=NOW,
                ),
            )
        )
    return mysql_control_database


def _identity(
    generation: int,
    *,
    digest_byte: int | None = None,
    tenant_uuid: UUID = TENANT_UUID,
    database_uuid: UUID = DATABASE_UUID,
):
    selected = generation if digest_byte is None else digest_byte
    return FleetSchemaIdentity(
        tenant_uuid=tenant_uuid,
        database_uuid=database_uuid,
        schema_generation=generation,
        schema_revision=f"rev_{generation}",
        schema_sha256=bytes([selected]) * 32,
    )


def _observation(identity, *, at=None):
    return FleetMigrationObservation(
        identity=identity,
        observed_at=at or NOW + timedelta(seconds=1),
    )


def _service(session, *, now):
    return FleetMigrationPersistenceService(
        session,
        database_clock=lambda _: now,
    )


def _claim(control_database, *, now=NOW, claim_id=CLAIM_A, expected=1):
    with control_database.transaction() as session:
        claimed = SchemaOperationLeasePersistenceService(
            session,
            database_clock=lambda _: now,
        ).claim(
            claim_id=claim_id,
            owner_id="fleet-worker-a" if claim_id == CLAIM_A else "fleet-worker-b",
            purpose=SchemaOperationPurpose.FLEET_MIGRATION,
            expected_row_version=expected,
            lease_expires_at=now + timedelta(minutes=10),
        )
    return FleetSchemaOperationFence(
        claim_id=claimed.lease.claim_id,
        owner_id=claimed.lease.owner_id,
        generation=claimed.lease.generation,
        fencing_token=claimed.lease.fencing_token,
        row_version=claimed.lease.row_version,
    )


def _queue(control_database, *, now=None):
    with control_database.transaction() as session:
        return _service(
            session,
            now=now or NOW + timedelta(microseconds=1),
        ).queue(
            migration_uuid=MIGRATION_UUID,
            source=_identity(8),
            target=_identity(9),
        )


def test_queue_binds_legacy_identity_metadata_and_exactly_replays(
    control_database,
):
    queued = _queue(control_database)
    replay = _queue(control_database, now=NOW + timedelta(seconds=5))

    assert queued.created and not queued.idempotent_replay
    assert replay.idempotent_replay and not replay.created
    assert replay.target == queued.target
    with control_database.transaction() as session:
        row = session.get(TenantFleetMigration, str(MIGRATION_UUID))
        identity = session.get(
            DatabaseIdentityControlRecord,
            str(TENANT_UUID),
        )
        assert row.route_disposition == "routable_previous"
        assert row.last_observed_schema_generation is None
        assert identity.expected_schema_revision == "rev_8"
        assert bytes(identity.expected_schema_sha256) == bytes([8]) * 32
        assert identity.observed_schema_revision == "rev_8"
        assert identity.row_version == 2


def test_begin_response_loss_replays_without_advancing_the_attempt(
    control_database,
):
    fence = _claim(control_database)
    _queue(control_database)
    observation = _observation(_identity(8))

    with control_database.transaction() as session:
        first = _service(
            session,
            now=NOW + timedelta(seconds=1),
        ).begin(
            migration_uuid=MIGRATION_UUID,
            expected_row_version=1,
            observation=observation,
            schema_operation_fence=fence,
        )
    with control_database.transaction() as session:
        replay = _service(
            session,
            now=NOW + timedelta(seconds=2),
        ).begin(
            migration_uuid=MIGRATION_UUID,
            expected_row_version=1,
            observation=observation,
            schema_operation_fence=fence,
        )

    assert first.target.state is FleetMigrationState.RUNNING
    assert first.target.operation_generation == 1
    assert replay.idempotent_replay
    assert replay.target.row_version == 2
    assert replay.target.attempt_count == 1


def test_failed_previous_revision_is_routable_and_retryable(control_database):
    fence = _claim(control_database)
    _queue(control_database)
    with control_database.transaction() as session:
        _service(session, now=NOW + timedelta(seconds=1)).begin(
            migration_uuid=MIGRATION_UUID,
            expected_row_version=1,
            observation=_observation(_identity(8)),
            schema_operation_fence=fence,
        )
    with control_database.transaction() as session:
        failed = _service(session, now=NOW + timedelta(seconds=2)).fail(
            migration_uuid=MIGRATION_UUID,
            expected_row_version=2,
            expected_operation_generation=1,
            observation=_observation(
                _identity(8),
                at=NOW + timedelta(seconds=2),
            ),
            safe_error_code="DDL_TIMEOUT",
            schema_operation_fence=fence,
        )
    with control_database.transaction() as session:
        retried = _service(session, now=NOW + timedelta(seconds=3)).retry(
            migration_uuid=MIGRATION_UUID,
            expected_row_version=3,
            observation=_observation(
                _identity(8),
                at=NOW + timedelta(seconds=3),
            ),
            schema_operation_fence=fence,
        )

    assert failed.target.state is FleetMigrationState.FAILED
    assert failed.route_disposition is FleetRouteDisposition.ROUTABLE_PREVIOUS
    assert retried.target.state is FleetMigrationState.RUNNING
    assert retried.target.operation_generation == 2
    assert retried.target.attempt_count == 2


def test_success_persists_target_identity_and_shared_fence_evidence(
    control_database,
):
    fence = _claim(control_database)
    _queue(control_database)
    with control_database.transaction() as session:
        _service(session, now=NOW + timedelta(seconds=1)).begin(
            migration_uuid=MIGRATION_UUID,
            expected_row_version=1,
            observation=_observation(_identity(8)),
            schema_operation_fence=fence,
        )
    with control_database.transaction() as session:
        succeeded = _service(session, now=NOW + timedelta(seconds=2)).succeed(
            migration_uuid=MIGRATION_UUID,
            expected_row_version=2,
            expected_operation_generation=1,
            observation=_observation(
                _identity(9),
                at=NOW + timedelta(seconds=2),
            ),
            schema_operation_fence=fence,
        )

    assert succeeded.target.state is FleetMigrationState.SUCCEEDED
    with control_database.transaction() as session:
        row = session.get(TenantFleetMigration, str(MIGRATION_UUID))
        assert row.schema_operation_claim_uuid == str(fence.claim_id)
        assert row.schema_operation_owner_id == fence.owner_id
        assert row.schema_operation_generation == fence.generation
        assert row.schema_operation_fencing_token == fence.fencing_token
        assert row.schema_operation_row_version == fence.row_version
        assert row.last_observed_schema_revision == "rev_9"
        assert bytes(row.last_observed_schema_sha256) == bytes([9]) * 32


def test_drift_holds_only_the_affected_route(control_database):
    fence = _claim(control_database)
    _queue(control_database)
    with control_database.transaction() as session:
        _service(session, now=NOW + timedelta(seconds=1)).begin(
            migration_uuid=MIGRATION_UUID,
            expected_row_version=1,
            observation=_observation(_identity(8)),
            schema_operation_fence=fence,
        )
    drifted = _identity(8, digest_byte=99)
    with control_database.transaction() as session:
        failed = _service(session, now=NOW + timedelta(seconds=2)).fail(
            migration_uuid=MIGRATION_UUID,
            expected_row_version=2,
            expected_operation_generation=1,
            observation=_observation(
                drifted,
                at=NOW + timedelta(seconds=2),
            ),
            safe_error_code="SCHEMA_DRIFT",
            schema_operation_fence=fence,
        )

    assert failed.route_disposition is FleetRouteDisposition.HOLD_SCHEMA_DRIFT
    with control_database.transaction() as session:
        identity = session.get(
            DatabaseIdentityControlRecord,
            str(TENANT_UUID),
        )
        assert bytes(identity.expected_schema_sha256) == bytes([8]) * 32
        assert bytes(identity.observed_schema_sha256) == bytes([99]) * 32
        assert (
            SqlAlchemyRouteRepository(session=session).get_current_ready_route(
                tenant_uuid=TENANT_UUID,
                access_version=1,
                account_kind=AccountKind.DML,
            )
            is None
        )


def test_identity_mismatch_holds_then_a_current_retry_recovers_the_route(
    control_database,
):
    fence = _claim(control_database)
    _queue(control_database)
    with control_database.transaction() as session:
        _service(session, now=NOW + timedelta(seconds=1)).begin(
            migration_uuid=MIGRATION_UUID,
            expected_row_version=1,
            observation=_observation(_identity(8)),
            schema_operation_fence=fence,
        )

    other_database = UUID("a1000000-0000-4000-8000-000000000099")
    with control_database.transaction() as session:
        failed = _service(session, now=NOW + timedelta(seconds=2)).fail(
            migration_uuid=MIGRATION_UUID,
            expected_row_version=2,
            expected_operation_generation=1,
            observation=_observation(
                _identity(8, database_uuid=other_database),
                at=NOW + timedelta(seconds=2),
            ),
            safe_error_code="IDENTITY_MISMATCH",
            schema_operation_fence=fence,
        )
    assert (
        failed.route_disposition
        is FleetRouteDisposition.HOLD_IDENTITY_MISMATCH
    )

    with control_database.transaction() as session:
        row = session.get(TenantFleetMigration, str(MIGRATION_UUID))
        identity = session.get(
            DatabaseIdentityControlRecord,
            str(TENANT_UUID),
        )
        assert row.last_observed_database_uuid == str(other_database)
        assert identity.observed_schema_generation is None
        assert identity.observed_schema_revision is None
        assert identity.observed_schema_sha256 is None
        assert (
            SqlAlchemyRouteRepository(session=session).get_current_ready_route(
                tenant_uuid=TENANT_UUID,
                access_version=1,
                account_kind=AccountKind.DML,
            )
            is None
        )

    with control_database.transaction() as session:
        retried = _service(session, now=NOW + timedelta(seconds=3)).retry(
            migration_uuid=MIGRATION_UUID,
            expected_row_version=3,
            observation=_observation(
                _identity(8),
                at=NOW + timedelta(seconds=3),
            ),
            schema_operation_fence=fence,
        )
    assert retried.target.state is FleetMigrationState.RUNNING
    with control_database.transaction() as session:
        assert (
            SqlAlchemyRouteRepository(session=session).get_current_ready_route(
                tenant_uuid=TENANT_UUID,
                access_version=1,
                account_kind=AccountKind.DML,
            )
            is not None
        )


def test_target_already_applied_converges_without_a_running_ddl_state(
    control_database,
):
    fence = _claim(control_database)
    _queue(control_database)
    with control_database.transaction() as session:
        result = _service(session, now=NOW + timedelta(seconds=1)).begin(
            migration_uuid=MIGRATION_UUID,
            expected_row_version=1,
            observation=_observation(_identity(9)),
            schema_operation_fence=fence,
        )

    assert result.target.state is FleetMigrationState.SUCCEEDED
    assert result.route_disposition is FleetRouteDisposition.ROUTABLE_CURRENT
    with control_database.transaction() as session:
        route = session.get(TenantDatabase, str(TENANT_UUID))
        identity = session.get(
            DatabaseIdentityControlRecord,
            str(TENANT_UUID),
        )
        assert route.schema_version == "rev_9"
        assert route.row_version == 2
        assert identity.expected_schema_generation == 9
        assert identity.observed_schema_generation == 9
        assert bytes(identity.expected_schema_sha256) == bytes([9]) * 32


def test_stale_shared_fence_cannot_begin(control_database):
    first = _claim(control_database)
    _queue(control_database)
    expiry = NOW + timedelta(minutes=10)
    with control_database.transaction() as session:
        takeover = SchemaOperationLeasePersistenceService(
            session,
            database_clock=lambda _: expiry,
        ).claim(
            claim_id=CLAIM_B,
            owner_id="fleet-worker-b",
            purpose=SchemaOperationPurpose.FLEET_MIGRATION,
            expected_row_version=first.row_version,
            lease_expires_at=expiry + timedelta(minutes=10),
        )
    assert takeover.lease.generation == first.generation + 1

    with control_database.transaction() as session:
        with pytest.raises(SchemaOperationLeaseFenceConflict):
            _service(session, now=expiry + timedelta(seconds=1)).begin(
                migration_uuid=MIGRATION_UUID,
                expected_row_version=1,
                observation=_observation(
                    _identity(8),
                    at=expiry + timedelta(seconds=1),
                ),
                schema_operation_fence=first,
            )


def test_stale_observation_cannot_overwrite_newer_control_evidence(
    control_database,
):
    fence = _claim(control_database)
    _queue(control_database)
    with control_database.transaction() as session:
        _service(session, now=NOW + timedelta(seconds=2)).begin(
            migration_uuid=MIGRATION_UUID,
            expected_row_version=1,
            observation=_observation(
                _identity(8),
                at=NOW + timedelta(seconds=2),
            ),
            schema_operation_fence=fence,
        )

    with control_database.transaction() as session:
        with pytest.raises(FleetMigrationObservationRejected):
            _service(session, now=NOW + timedelta(seconds=3)).fail(
                migration_uuid=MIGRATION_UUID,
                expected_row_version=2,
                expected_operation_generation=1,
                observation=_observation(
                    _identity(8),
                    at=NOW + timedelta(seconds=1),
                ),
                safe_error_code="STALE_OBSERVATION",
                schema_operation_fence=fence,
            )

    with control_database.transaction() as session:
        row = session.get(TenantFleetMigration, str(MIGRATION_UUID))
        assert row.state == "running"
        assert row.row_version == 2


def test_caller_rollback_removes_queue_and_identity_binding(control_database):
    with control_database.new_session() as session:
        transaction = session.begin()
        _service(session, now=NOW + timedelta(seconds=1)).queue(
            migration_uuid=MIGRATION_UUID,
            source=_identity(8),
            target=_identity(9),
        )
        transaction.rollback()

    with control_database.transaction() as session:
        assert session.get(TenantFleetMigration, str(MIGRATION_UUID)) is None
        identity = session.get(
            DatabaseIdentityControlRecord,
            str(TENANT_UUID),
        )
        assert identity.expected_schema_revision is None
        assert identity.expected_schema_sha256 is None
        assert identity.row_version == 1


def test_service_requires_clean_explicit_transaction(control_database):
    with control_database.new_session() as session:
        with pytest.raises(FleetMigrationTransactionError):
            _service(session, now=NOW).queue(
                migration_uuid=MIGRATION_UUID,
                source=_identity(8),
                target=_identity(9),
            )

    with control_database.new_session() as session:
        transaction = session.begin()
        try:
            session.add(Tenant(name="dirty"))
            with pytest.raises(FleetMigrationTransactionError):
                _service(session, now=NOW).queue(
                    migration_uuid=MIGRATION_UUID,
                    source=_identity(8),
                    target=_identity(9),
                )
        finally:
            transaction.rollback()


def test_queue_rejects_route_or_control_identity_mismatch(control_database):
    with control_database.transaction() as session:
        route = session.get(TenantDatabase, str(TENANT_UUID))
        route.schema_version = "unexpected"

    with control_database.transaction() as session:
        with pytest.raises(FleetMigrationControlIdentityError):
            _service(session, now=NOW).queue(
                migration_uuid=MIGRATION_UUID,
                source=_identity(8),
                target=_identity(9),
            )


def test_database_clock_uses_mysql_microseconds_and_is_read_after_locks(
    control_database,
):
    session = Mock()
    session.get_bind.return_value.dialect.name = "mysql"
    session.scalar.return_value = NOW.replace(tzinfo=None)
    assert _read_database_utc_now(session) == NOW
    assert str(session.scalar.call_args.args[0]) == "SELECT UTC_TIMESTAMP(6)"

    statements: list[str] = []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lower())

    sa.event.listen(control_database.engine, "before_cursor_execute", capture)
    try:
        with control_database.transaction() as transaction_session:
            def locked_clock(_session):
                assert any(
                    "database_identity_control_records" in statement
                    and statement.lstrip().startswith("select")
                    for statement in statements
                )
                return NOW

            FleetMigrationPersistenceService(
                transaction_session,
                database_clock=locked_clock,
            ).queue(
                migration_uuid=MIGRATION_UUID,
                source=_identity(8),
                target=_identity(9),
            )
    finally:
        sa.event.remove(
            control_database.engine,
            "before_cursor_execute",
            capture,
        )


def test_persistence_contract_has_no_schema_name_or_secret_inputs():
    with pytest.raises(ValueError):
        FleetSchemaOperationFence(
            claim_id=CLAIM_A,
            owner_id="bad owner with spaces",
            generation=1,
            fencing_token=1,
            row_version=1,
        )

    column_names = {column.name for column in TenantFleetMigration.__table__.columns}
    assert not any(
        marker in column_name
        for column_name in column_names
        for marker in (
            "database_name",
            "schema_name",
            "dsn",
            "url",
            "password",
            "secret",
            "credential",
        )
    )
