from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from unittest.mock import Mock
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from inventory_control import ControlBase, ControlDatabase
from inventory_control.models.schema_operations import (
    PlatformSchemaOperationLease,
)
from inventory_control.schema_operations import (
    SCHEMA_OPERATION_LEASE_KEY,
    SchemaOperationLeaseEffect,
    SchemaOperationLeaseFenceConflict,
    SchemaOperationLeaseIdempotencyConflict,
    SchemaOperationLeasePersistenceService,
    SchemaOperationLeaseState,
    SchemaOperationLeaseUnavailable,
    SchemaOperationPurpose,
    SchemaOperationStoredStateError,
    SchemaOperationTransactionError,
    require_live_schema_operation_fence,
)
from inventory_control.schema_operations.persistence import (
    _read_database_utc_now,
)


NOW = datetime(2026, 8, 22, 12, 0, 0, 123456, tzinfo=timezone.utc)
CLAIM_A = UUID("93000000-0000-4000-8000-000000000001")
CLAIM_B = UUID("93000000-0000-4000-8000-000000000002")


@pytest.fixture
def control_database(mysql_control_database):
    database = mysql_control_database
    with database.transaction() as session:
        session.add(
            PlatformSchemaOperationLease(
                lease_key=SCHEMA_OPERATION_LEASE_KEY,
                state=SchemaOperationLeaseState.AVAILABLE.value,
                generation=0,
                fencing_token=0,
                row_version=1,
                observed_at=NOW,
            )
        )
    yield database


def _service(session, *, now=NOW):
    return SchemaOperationLeasePersistenceService(
        session,
        database_clock=lambda _: now,
    )


def _claim(
    session,
    *,
    claim_id=CLAIM_A,
    owner_id="schema-worker-a",
    purpose=SchemaOperationPurpose.PROVISIONING,
    expected_row_version=1,
    expires_at=None,
    now=NOW,
):
    return _service(session, now=now).claim(
        claim_id=claim_id,
        owner_id=owner_id,
        purpose=purpose,
        expected_row_version=expected_row_version,
        lease_expires_at=expires_at or NOW + timedelta(minutes=10),
    )


def test_service_requires_a_clean_explicit_caller_transaction(
    control_database,
):
    with control_database.new_session() as session:
        with pytest.raises(SchemaOperationTransactionError):
            _claim(session)

    with control_database.new_session() as session:
        transaction = session.begin()
        try:
            session.add(
                PlatformSchemaOperationLease(
                    lease_key="not-the-singleton",
                    state="available",
                    generation=0,
                    fencing_token=0,
                    row_version=1,
                    observed_at=NOW,
                )
            )
            with pytest.raises(SchemaOperationTransactionError):
                _claim(session)
        finally:
            transaction.rollback()


def test_database_clock_is_read_only_after_the_locking_select(
    control_database,
):
    statements: list[str] = []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lower())

    sa.event.listen(control_database.engine, "before_cursor_execute", capture)
    try:
        with control_database.transaction() as session:

            def clock(_session):
                assert any(
                    statement.lstrip().startswith("select")
                    and "platform_schema_operation_leases" in statement
                    for statement in statements
                )
                return NOW

            SchemaOperationLeasePersistenceService(
                session,
                database_clock=clock,
            ).claim(
                claim_id=CLAIM_A,
                owner_id="schema-worker-a",
                purpose=SchemaOperationPurpose.BACKUP,
                expected_row_version=1,
                lease_expires_at=NOW + timedelta(minutes=10),
            )
    finally:
        sa.event.remove(
            control_database.engine,
            "before_cursor_execute",
            capture,
        )


@pytest.mark.parametrize(
    ("dialect_name", "expected_sql"),
    (
        ("mysql", "SELECT UTC_TIMESTAMP(6)"),
        ("mariadb", "SELECT UTC_TIMESTAMP(6)"),
    ),
)
def test_default_database_clock_keeps_microseconds_and_is_dialect_safe(
    dialect_name,
    expected_sql,
):
    session = Mock()
    session.get_bind.return_value.dialect.name = dialect_name
    session.scalar.return_value = NOW.replace(tzinfo=None)

    assert _read_database_utc_now(session) == NOW
    statement = session.scalar.call_args.args[0]
    assert str(statement) == expected_sql


def test_public_final_fence_locks_then_validates_without_mutation(
    control_database,
):
    with control_database.transaction() as session:
        claimed = _claim(session)

    statements: list[str] = []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lower())

    sa.event.listen(control_database.engine, "before_cursor_execute", capture)
    try:
        with control_database.transaction() as session:

            def clock(_session):
                assert any(
                    statement.lstrip().startswith("select")
                    and "platform_schema_operation_leases" in statement
                    for statement in statements
                )
                return NOW + timedelta(seconds=1, microseconds=111111)

            current = SchemaOperationLeasePersistenceService(
                session,
                database_clock=clock,
            ).require_live_schema_operation_fence(
                claim_id=CLAIM_A,
                owner_id="schema-worker-a",
                purpose=SchemaOperationPurpose.PROVISIONING,
                generation=claimed.lease.generation,
                fencing_token=claimed.lease.fencing_token,
                expected_row_version=claimed.lease.row_version,
            )
            assert current == claimed.lease
            assert not session.dirty
    finally:
        sa.event.remove(
            control_database.engine,
            "before_cursor_execute",
            capture,
        )

    assert not any(statement.lstrip().startswith("update") for statement in statements)
    assert (
        require_live_schema_operation_fence(
            current,
            claim_id=CLAIM_A,
            owner_id="schema-worker-a",
            purpose=SchemaOperationPurpose.PROVISIONING,
            generation=claimed.lease.generation,
            fencing_token=claimed.lease.fencing_token,
            expected_row_version=claimed.lease.row_version,
            database_now=NOW + timedelta(seconds=2),
        )
        == claimed.lease
    )

    with control_database.transaction() as session:
        with pytest.raises(SchemaOperationLeaseFenceConflict):
            _service(
                session,
                now=NOW + timedelta(seconds=2),
            ).require_live_fence(
                claim_id=CLAIM_A,
                owner_id="schema-worker-a",
                purpose=SchemaOperationPurpose.PROVISIONING,
                generation=claimed.lease.generation,
                fencing_token=claimed.lease.fencing_token,
                expected_row_version=claimed.lease.row_version + 1,
            )


def test_service_touches_only_the_singleton_lease_table(control_database):
    statements: list[str] = []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lower())

    sa.event.listen(control_database.engine, "before_cursor_execute", capture)
    try:
        with control_database.transaction() as session:
            _claim(session)
    finally:
        sa.event.remove(
            control_database.engine,
            "before_cursor_execute",
            capture,
        )

    data_statements = [
        statement
        for statement in statements
        if statement.lstrip().startswith(("select", "insert", "update"))
    ]
    assert data_statements
    assert all(
        "platform_schema_operation_leases" in statement for statement in data_statements
    )
    assert not any(
        forbidden in statement
        for statement in data_statements
        for forbidden in (
            "tenant_databases",
            "platform_backup_leases",
            "account_mutation",
            "password",
            "credential",
        )
    )


def test_claim_renew_release_and_exact_replays_round_trip(control_database):
    first_expiry = NOW + timedelta(minutes=10, microseconds=111111)
    with control_database.transaction() as session:
        claimed = _claim(session, expires_at=first_expiry)
    assert claimed.effect is SchemaOperationLeaseEffect.CLAIMED
    assert (claimed.lease.generation, claimed.lease.fencing_token) == (1, 1)
    assert claimed.lease.expires_at == first_expiry

    with control_database.transaction() as session:
        replay = _claim(
            session,
            expected_row_version=1,
            expires_at=first_expiry,
            now=NOW + timedelta(seconds=1),
        )
    assert replay.idempotent_replay
    assert replay.lease.row_version == 2

    renewed_expiry = NOW + timedelta(minutes=20, microseconds=222222)
    with control_database.transaction() as session:
        renewed = _service(
            session,
            now=NOW + timedelta(minutes=1),
        ).renew(
            claim_id=CLAIM_A,
            owner_id="schema-worker-a",
            purpose=SchemaOperationPurpose.PROVISIONING,
            fencing_token=claimed.lease.fencing_token,
            expected_row_version=claimed.lease.row_version,
            lease_expires_at=renewed_expiry,
        )
    assert renewed.lease.expires_at == renewed_expiry
    assert renewed.lease.row_version == 3
    assert renewed.lease.fencing_token == claimed.lease.fencing_token

    with control_database.transaction() as session:
        renew_replay = _service(
            session,
            now=NOW + timedelta(minutes=2),
        ).renew(
            claim_id=CLAIM_A,
            owner_id="schema-worker-a",
            purpose=SchemaOperationPurpose.PROVISIONING,
            fencing_token=claimed.lease.fencing_token,
            expected_row_version=claimed.lease.row_version,
            lease_expires_at=renewed_expiry,
        )
    assert renew_replay.idempotent_replay

    with control_database.transaction() as session:
        released = _service(
            session,
            now=NOW + timedelta(minutes=3),
        ).release(
            claim_id=CLAIM_A,
            owner_id="schema-worker-a",
            purpose=SchemaOperationPurpose.PROVISIONING,
            fencing_token=claimed.lease.fencing_token,
            expected_row_version=renewed.lease.row_version,
        )
    assert released.lease.state is SchemaOperationLeaseState.AVAILABLE
    assert released.lease.row_version == 4

    with control_database.transaction() as session:
        release_replay = _service(
            session,
            now=NOW + timedelta(minutes=4),
        ).release(
            claim_id=CLAIM_A,
            owner_id="schema-worker-a",
            purpose=SchemaOperationPurpose.PROVISIONING,
            fencing_token=claimed.lease.fencing_token,
            expected_row_version=renewed.lease.row_version,
        )
    assert release_replay.idempotent_replay


def test_active_different_purpose_is_mutually_exclusive(control_database):
    with control_database.transaction() as session:
        _claim(session, purpose=SchemaOperationPurpose.BACKUP)

    with control_database.transaction() as session:
        with pytest.raises(SchemaOperationLeaseUnavailable):
            _claim(
                session,
                claim_id=CLAIM_B,
                owner_id="restore-worker",
                purpose=SchemaOperationPurpose.RESTORE,
                expected_row_version=2,
                expires_at=NOW + timedelta(minutes=20),
                now=NOW + timedelta(minutes=1),
            )


def test_expired_takeover_increments_generation_and_fences_stale_release(
    control_database,
):
    expiry = NOW + timedelta(minutes=5)
    with control_database.transaction() as session:
        first = _claim(
            session,
            purpose=SchemaOperationPurpose.BACKUP,
            expires_at=expiry,
        )

    with control_database.transaction() as session:
        takeover = _claim(
            session,
            claim_id=CLAIM_B,
            owner_id="migration-worker",
            purpose=SchemaOperationPurpose.FLEET_MIGRATION,
            expected_row_version=first.lease.row_version,
            expires_at=NOW + timedelta(minutes=20),
            now=expiry,
        )
    assert (takeover.lease.generation, takeover.lease.fencing_token) == (2, 2)

    with control_database.transaction() as session:
        with pytest.raises(SchemaOperationLeaseFenceConflict):
            _service(
                session,
                now=expiry + timedelta(seconds=1),
            ).release(
                claim_id=CLAIM_A,
                owner_id="schema-worker-a",
                purpose=SchemaOperationPurpose.BACKUP,
                fencing_token=first.lease.fencing_token,
                expected_row_version=first.lease.row_version,
            )

    with control_database.transaction() as session:
        row = session.get(
            PlatformSchemaOperationLease,
            SCHEMA_OPERATION_LEASE_KEY,
        )
        assert row is not None
        assert row.claim_id == str(CLAIM_B)
        assert row.purpose == SchemaOperationPurpose.FLEET_MIGRATION.value
        assert row.fencing_token == 2


def test_claim_release_reclaim_aba_does_not_replay_old_requests(
    control_database,
):
    with control_database.transaction() as session:
        first = _claim(session)
    with control_database.transaction() as session:
        released = _service(
            session,
            now=NOW + timedelta(minutes=1),
        ).release(
            claim_id=CLAIM_A,
            owner_id="schema-worker-a",
            purpose=SchemaOperationPurpose.PROVISIONING,
            fencing_token=first.lease.fencing_token,
            expected_row_version=first.lease.row_version,
        )

    with control_database.transaction() as session:
        with pytest.raises(SchemaOperationLeaseIdempotencyConflict):
            _claim(
                session,
                expected_row_version=1,
                expires_at=NOW + timedelta(minutes=30),
                now=NOW + timedelta(minutes=2),
            )

    with control_database.transaction() as session:
        second = _claim(
            session,
            claim_id=CLAIM_B,
            owner_id="schema-worker-b",
            purpose=SchemaOperationPurpose.DELETION,
            expected_row_version=released.lease.row_version,
            expires_at=NOW + timedelta(minutes=30),
            now=NOW + timedelta(minutes=2),
        )
    assert second.lease.fencing_token == 2

    with control_database.transaction() as session:
        with pytest.raises(SchemaOperationLeaseFenceConflict):
            _service(
                session,
                now=NOW + timedelta(minutes=3),
            ).release(
                claim_id=CLAIM_A,
                owner_id="schema-worker-a",
                purpose=SchemaOperationPurpose.PROVISIONING,
                fencing_token=first.lease.fencing_token,
                expected_row_version=first.lease.row_version,
            )


def test_two_concurrent_purposes_have_only_one_effective_owner(
    control_database,
):
    barrier = Barrier(2)

    def compete(claim_id, owner_id, purpose):
        barrier.wait()
        try:
            with control_database.transaction() as session:
                result = _claim(
                    session,
                    claim_id=claim_id,
                    owner_id=owner_id,
                    purpose=purpose,
                    expires_at=NOW + timedelta(minutes=10),
                )
            return ("claimed", result.lease.claim_id)
        except (SchemaOperationLeaseUnavailable, SchemaOperationLeaseFenceConflict):
            return ("rejected", None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            executor.map(
                lambda values: compete(*values),
                (
                    (CLAIM_A, "backup-worker", SchemaOperationPurpose.BACKUP),
                    (
                        CLAIM_B,
                        "migration-worker",
                        SchemaOperationPurpose.FLEET_MIGRATION,
                    ),
                ),
            )
        )
    assert [outcome[0] for outcome in outcomes].count("claimed") == 1
    assert [outcome[0] for outcome in outcomes].count("rejected") == 1


def test_missing_singleton_fails_closed(mysql_control_database):
    with mysql_control_database.transaction() as session:
        with pytest.raises(SchemaOperationStoredStateError):
            _claim(session)


def test_model_constraints_reject_incomplete_or_unknown_state(
    mysql_control_database,
):
    engine = mysql_control_database.engine
    table = PlatformSchemaOperationLease.__table__
    invalid_rows = (
        {
            "lease_key": "wrong-scope",
            "state": "available",
            "generation": 0,
            "fencing_token": 0,
            "row_version": 1,
            "observed_at": NOW,
        },
        {
            "lease_key": SCHEMA_OPERATION_LEASE_KEY,
            "state": "held",
            "generation": 1,
            "fencing_token": 1,
            "row_version": 2,
            "observed_at": NOW,
            "owner_id": "worker",
            "claim_id": str(CLAIM_A),
            "purpose": "unknown",
            "acquired_at": NOW,
            "expires_at": NOW + timedelta(minutes=1),
            "last_claim_id": str(CLAIM_A),
            "last_effect": "claimed",
            "last_request_digest": b"x" * 32,
        },
        {
            "lease_key": SCHEMA_OPERATION_LEASE_KEY,
            "state": "held",
            "generation": 1,
            "fencing_token": 1,
            "row_version": 2,
            "observed_at": NOW,
            "owner_id": "worker",
            "claim_id": str(CLAIM_A),
            "purpose": "backup",
            "acquired_at": NOW,
            "expires_at": NOW + timedelta(minutes=1),
            "last_claim_id": str(CLAIM_A),
            "last_effect": "claimed",
            "last_request_digest": b"short",
        },
    )
    for invalid in invalid_rows:
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(sa.insert(table).values(**invalid))
