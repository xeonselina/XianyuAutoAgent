from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import UUID

import pytest
import sqlalchemy as sa

from inventory_control import ControlBase, ControlDatabase
from inventory_control.models.account_mutations import (
    TenantDatabaseAccountMutationLease,
    TenantDatabaseAccountRotation,
)
from inventory_control.routing import (
    AccountCandidatePreparationProof,
    AccountGeneration,
    AccountKind,
    AccountLeaseEffectKind,
    AccountLoginState,
    AccountMutationFenceConflict,
    AccountMutationLeaseExpired,
    AccountMutationLeasePersistenceService,
    AccountMutationLeaseUnavailable,
    AccountMutationProofRejected,
    AccountMutationTransactionError,
    AccountRevocationProof,
    AccountRotationPersistenceService,
    AccountRotationPurpose,
    AccountRotationState,
    AccountUnlockAuthority,
    AccountUnlockAuthorityProof,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
TENANT = UUID("81000000-0000-4000-8000-000000000001")
DATABASE = UUID("81000000-0000-4000-8000-000000000002")
ROTATION = UUID("81000000-0000-4000-8000-000000000003")
OWNER_A = "account-worker-a"
OWNER_B = "account-worker-b"
PURPOSE = AccountRotationPurpose.SUSPENSION_RESOLVE
PREVIOUS = AccountGeneration(
    username="tenant_dml_g7",
    credential_generation=7,
    root_key_version=2,
    derivation_version=1,
)
CANDIDATE = AccountGeneration(
    username="tenant_dml_g8",
    credential_generation=8,
    root_key_version=3,
    derivation_version=2,
)


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


def _lease_service(session, *, now=NOW):
    return AccountMutationLeasePersistenceService(
        session,
        database_clock=lambda _: now,
    )


def _rotation_service(session, *, now=NOW):
    return AccountRotationPersistenceService(
        session,
        database_clock=lambda _: now,
    )


def _claim(
    session,
    *,
    tenant=TENANT,
    owner=OWNER_A,
    purpose=PURPOSE.value,
    expires_at=None,
    now=NOW,
):
    return _lease_service(session, now=now).claim_lease(
        tenant_uuid=tenant,
        account_kind=AccountKind.DML,
        owner=owner,
        purpose=purpose,
        expected_row_version=1,
        lease_expires_at=expires_at or NOW + timedelta(minutes=10),
    )


def _start(
    service,
    *,
    rotation=ROTATION,
    previous=PREVIOUS,
    candidate=CANDIDATE,
):
    return service.start_rotation(
        rotation_uuid=rotation,
        tenant_uuid=TENANT,
        database_uuid=DATABASE,
        account_kind=AccountKind.DML,
        purpose=PURPOSE,
        previous=previous,
        candidate=candidate,
        inherited_desired_login_state=AccountLoginState.LOCKED,
        expected_tenant_access_version=13,
        expected_route_version=9,
        expected_login_state_version=6,
        expected_row_version=0,
    )


def _preparation_proof(
    *,
    rotation=ROTATION,
    candidate=CANDIDATE,
):
    return AccountCandidatePreparationProof(
        rotation_uuid=rotation,
        tenant_uuid=TENANT,
        database_uuid=DATABASE,
        account_kind=AccountKind.DML,
        candidate=candidate,
        candidate_created=True,
        candidate_locked=True,
        candidate_unpublished=True,
    )


def _unlock_proof(lease, **changes):
    values = {
        "rotation_uuid": ROTATION,
        "tenant_uuid": TENANT,
        "database_uuid": DATABASE,
        "account_kind": AccountKind.DML,
        "previous": PREVIOUS,
        "candidate": CANDIDATE,
        "authority": AccountUnlockAuthority.SUSPENSION_RESOLVE,
        "expected_tenant_access_version": 13,
        "expected_route_version": 9,
        "expected_login_state_version": 6,
        "lease_owner": OWNER_A,
        "lease_fencing_token": lease.fencing_token,
        "database_identity_verified": True,
        "positive_permissions_verified": True,
        "cross_schema_rejected": True,
        "candidate_unpublished": True,
        "other_generations_locked": True,
        "advisory_lock_held": True,
        "application_route_denied": True,
    }
    values.update(changes)
    return AccountUnlockAuthorityProof(**values)


def _revocation_proof(lease):
    return AccountRevocationProof(
        rotation_uuid=ROTATION,
        tenant_uuid=TENANT,
        database_uuid=DATABASE,
        account_kind=AccountKind.DML,
        previous=PREVIOUS,
        candidate=CANDIDATE,
        lease_owner=OWNER_A,
        lease_fencing_token=lease.fencing_token,
        candidate_published=True,
        previous_locked=True,
        previous_connections_drained=True,
        previous_revoked=True,
    )


def test_services_require_an_explicit_clean_caller_transaction(
    control_database,
):
    with control_database.new_session() as session:
        with pytest.raises(AccountMutationTransactionError):
            _claim(session)
        with pytest.raises(AccountMutationTransactionError):
            _rotation_service(session).start_rotation(
                rotation_uuid=ROTATION,
                tenant_uuid=TENANT,
                database_uuid=DATABASE,
                account_kind=AccountKind.DML,
                purpose=PURPOSE,
                previous=PREVIOUS,
                candidate=CANDIDATE,
                inherited_desired_login_state=AccountLoginState.LOCKED,
                expected_tenant_access_version=13,
                expected_route_version=9,
                expected_login_state_version=6,
            )

    with control_database.new_session() as session:
        transaction = session.begin()
        try:
            session.add(
                TenantDatabaseAccountMutationLease(
                    tenant_id=str(TENANT),
                    account_kind=AccountKind.DML.value,
                )
            )
            with pytest.raises(AccountMutationTransactionError):
                _claim(session)
        finally:
            transaction.rollback()


def test_lease_transaction_executes_only_against_the_lease_table(
    control_database,
):
    statements = []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lower())

    sa.event.listen(
        control_database.engine,
        "before_cursor_execute",
        capture,
    )
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
        "tenant_database_account_mutation_leases" in statement
        for statement in data_statements
    )
    forbidden = (
        " tenant ",
        "tenant_databases",
        "recovery_run",
        "account_rotations",
    )
    assert not any(
        name in statement
        for statement in data_statements
        for name in forbidden
    )


def test_lease_takeover_is_monotonic_and_stale_owner_is_fenced(
    control_database,
):
    expires = NOW + timedelta(minutes=5)
    with control_database.transaction() as session:
        first = _claim(session, expires_at=expires)
    assert first.effect is AccountLeaseEffectKind.CLAIMED
    assert (first.lease.fencing_token, first.lease.row_version) == (1, 2)

    takeover_expires = NOW + timedelta(minutes=20)
    with control_database.transaction() as session:
        takeover = _lease_service(
            session,
            now=expires,
        ).claim_lease(
            tenant_uuid=TENANT,
            account_kind=AccountKind.DML,
            owner=OWNER_B,
            purpose=PURPOSE.value,
            expected_row_version=first.lease.row_version,
            lease_expires_at=takeover_expires,
        )
    assert takeover.lease.owner == OWNER_B
    assert takeover.lease.fencing_token == 2
    assert takeover.lease.row_version == 3

    with control_database.transaction() as session:
        replay = _lease_service(
            session,
            now=expires + timedelta(seconds=1),
        ).claim_lease(
            tenant_uuid=TENANT,
            account_kind=AccountKind.DML,
            owner=OWNER_B,
            purpose=PURPOSE.value,
            expected_row_version=first.lease.row_version,
            lease_expires_at=takeover_expires,
        )
        assert replay.idempotent_replay
        with pytest.raises(AccountMutationFenceConflict):
            _lease_service(
                session,
                now=expires + timedelta(seconds=1),
            ).renew_lease(
                tenant_uuid=TENANT,
                account_kind=AccountKind.DML,
                owner=OWNER_A,
                fencing_token=first.lease.fencing_token,
                expected_row_version=takeover.lease.row_version,
                lease_expires_at=NOW + timedelta(minutes=30),
            )


def test_lease_renew_and_release_persist_without_advancing_the_token(
    control_database,
):
    with control_database.transaction() as session:
        claimed = _claim(session)
    with control_database.transaction() as session:
        renewed = _lease_service(
            session,
            now=NOW + timedelta(minutes=1),
        ).renew_lease(
            tenant_uuid=TENANT,
            account_kind=AccountKind.DML,
            owner=OWNER_A,
            fencing_token=claimed.lease.fencing_token,
            expected_row_version=claimed.lease.row_version,
            lease_expires_at=NOW + timedelta(minutes=20),
        )
    assert renewed.effect is AccountLeaseEffectKind.RENEWED
    assert renewed.lease.fencing_token == claimed.lease.fencing_token
    assert renewed.lease.row_version == claimed.lease.row_version + 1

    with control_database.transaction() as session:
        service = _lease_service(session, now=NOW + timedelta(minutes=2))
        released = service.release_lease(
            tenant_uuid=TENANT,
            account_kind=AccountKind.DML,
            owner=OWNER_A,
            fencing_token=renewed.lease.fencing_token,
            expected_row_version=renewed.lease.row_version,
        )
        replay = service.release_lease(
            tenant_uuid=TENANT,
            account_kind=AccountKind.DML,
            owner=OWNER_A,
            fencing_token=renewed.lease.fencing_token,
            expected_row_version=renewed.lease.row_version,
        )
    assert released.effect is AccountLeaseEffectKind.RELEASED
    assert released.lease.fencing_token == renewed.lease.fencing_token
    assert released.lease.owner is None
    assert replay.idempotent_replay
    assert replay.lease.row_version == released.lease.row_version


def test_claim_replay_is_bound_to_row_version_and_rejects_aba_cycle(
    control_database,
):
    expires = NOW + timedelta(minutes=10, microseconds=123456)
    with control_database.transaction() as session:
        first = _claim(session, expires_at=expires)
    with control_database.transaction() as session:
        released = _lease_service(session).release_lease(
            tenant_uuid=TENANT,
            account_kind=AccountKind.DML,
            owner=OWNER_A,
            fencing_token=first.lease.fencing_token,
            expected_row_version=first.lease.row_version,
        )
    with control_database.transaction() as session:
        second = _lease_service(session).claim_lease(
            tenant_uuid=TENANT,
            account_kind=AccountKind.DML,
            owner=OWNER_A,
            purpose=PURPOSE.value,
            expected_row_version=released.lease.row_version,
            lease_expires_at=expires,
        )
    assert second.lease.fencing_token == first.lease.fencing_token + 1
    assert second.lease.expires_at == expires
    assert second.lease.expires_at.microsecond == 123456

    with control_database.transaction() as session:
        with pytest.raises(AccountMutationFenceConflict):
            _lease_service(session).claim_lease(
                tenant_uuid=TENANT,
                account_kind=AccountKind.DML,
                owner=OWNER_A,
                purpose=PURPOSE.value,
                expected_row_version=1,
                lease_expires_at=expires,
            )
        replay = _lease_service(session).claim_lease(
            tenant_uuid=TENANT,
            account_kind=AccountKind.DML,
            owner=OWNER_A,
            purpose=PURPOSE.value,
            expected_row_version=released.lease.row_version,
            lease_expires_at=expires,
        )
    assert replay.idempotent_replay
    assert replay.lease == second.lease


def test_concurrent_first_claim_accepts_only_one_create_and_exact_replay(
    control_database,
):
    ready = Barrier(2)
    expires = NOW + timedelta(minutes=10)

    def claim_once():
        ready.wait()
        with control_database.transaction() as session:
            return _lease_service(session).claim_lease(
                tenant_uuid=TENANT,
                account_kind=AccountKind.DML,
                owner=OWNER_A,
                purpose=PURPOSE.value,
                expected_row_version=1,
                lease_expires_at=expires,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: claim_once(), range(2)))

    assert sorted(result.idempotent_replay for result in results) == [False, True]
    assert {result.lease.fencing_token for result in results} == {1}
    with control_database.new_session() as session:
        count = session.scalar(
            sa.select(sa.func.count()).select_from(
                TenantDatabaseAccountMutationLease
            )
        )
        assert count == 1


def test_competing_first_claim_fails_closed_without_owner_disclosure(
    control_database,
):
    with control_database.transaction() as session:
        _claim(session)
    with control_database.transaction() as session:
        with pytest.raises(AccountMutationLeaseUnavailable) as caught:
            _lease_service(session).claim_lease(
                tenant_uuid=TENANT,
                account_kind=AccountKind.DML,
                owner=OWNER_B,
                purpose=PURPOSE.value,
                expected_row_version=1,
                lease_expires_at=NOW + timedelta(minutes=20),
            )
    assert OWNER_A not in str(caught.value)


def test_full_rotation_persists_every_success_state_and_exact_replay(
    control_database,
):
    with control_database.transaction() as session:
        lease = _claim(session).lease
        service = _rotation_service(session)
        seen = []

        started = _start(service)
        seen.append(started.rotation.state)
        assert _start(service).idempotent_replay

        prepared = service.prepare_rotation(
            rotation_uuid=ROTATION,
            expected_row_version=started.row_version,
            proof=_preparation_proof(),
        )
        seen.append(prepared.rotation.state)
        replay = service.prepare_rotation(
            rotation_uuid=ROTATION,
            expected_row_version=started.row_version,
            proof=_preparation_proof(),
        )
        assert replay.idempotent_replay
        assert replay.row_version == prepared.row_version

        testing = service.begin_candidate_testing(
            rotation_uuid=ROTATION,
            expected_row_version=prepared.row_version,
            proof=_unlock_proof(lease),
        )
        seen.append(testing.rotation.state)
        assert service.begin_candidate_testing(
            rotation_uuid=ROTATION,
            expected_row_version=prepared.row_version,
            proof=_unlock_proof(lease),
        ).idempotent_replay

        verified = service.verify_candidate(
            rotation_uuid=ROTATION,
            expected_row_version=testing.row_version,
            proof=_unlock_proof(lease),
        )
        seen.append(verified.rotation.state)
        assert service.verify_candidate(
            rotation_uuid=ROTATION,
            expected_row_version=testing.row_version,
            proof=_unlock_proof(lease),
        ).idempotent_replay

        switched = service.switch_candidate(
            rotation_uuid=ROTATION,
            expected_row_version=verified.row_version,
            proof=_unlock_proof(lease),
        )
        seen.append(switched.rotation.state)
        assert switched.effects.publish_candidate
        assert service.switch_candidate(
            rotation_uuid=ROTATION,
            expected_row_version=verified.row_version,
            proof=_unlock_proof(lease),
        ).idempotent_replay

        draining = service.begin_draining(
            rotation_uuid=ROTATION,
            expected_row_version=switched.row_version,
        )
        seen.append(draining.rotation.state)
        assert service.begin_draining(
            rotation_uuid=ROTATION,
            expected_row_version=switched.row_version,
        ).idempotent_replay

        revoked = service.revoke_previous(
            rotation_uuid=ROTATION,
            expected_row_version=draining.row_version,
            proof=_revocation_proof(lease),
        )
        seen.append(revoked.rotation.state)
        assert service.revoke_previous(
            rotation_uuid=ROTATION,
            expected_row_version=draining.row_version,
            proof=_revocation_proof(lease),
        ).idempotent_replay

        assert seen == [
            AccountRotationState.PREPARING,
            AccountRotationState.PREPARED_LOCKED,
            AccountRotationState.CANDIDATE_TESTING,
            AccountRotationState.VERIFIED,
            AccountRotationState.SWITCHED,
            AccountRotationState.DRAINING,
            AccountRotationState.REVOKED,
        ]
        assert revoked.row_version == 7
        assert revoked.rotation.transition_sequence == 7

    with control_database.new_session() as session:
        stored = session.scalar(
            sa.select(TenantDatabaseAccountRotation).where(
                TenantDatabaseAccountRotation.rotation_id == str(ROTATION)
            )
        )
        assert stored.state == AccountRotationState.REVOKED.value
        assert stored.candidate_published is True
        assert stored.previous_locked is True
        assert stored.previous_revoked is True
        assert stored.row_version == 7


def test_proof_failure_and_stale_row_fence_never_publish_candidate(
    control_database,
):
    with control_database.transaction() as session:
        lease = _claim(session).lease
        service = _rotation_service(session)
        started = _start(service)
        prepared = service.prepare_rotation(
            rotation_uuid=ROTATION,
            expected_row_version=started.row_version,
            proof=_preparation_proof(),
        )
        with pytest.raises(AccountMutationProofRejected) as rejected:
            service.begin_candidate_testing(
                rotation_uuid=ROTATION,
                expected_row_version=prepared.row_version,
                proof=_unlock_proof(
                    lease,
                    cross_schema_rejected=False,
                ),
            )
        assert rejected.value.effects.publish_candidate is False

        with pytest.raises(AccountMutationFenceConflict) as fenced:
            service.begin_candidate_testing(
                rotation_uuid=ROTATION,
                expected_row_version=started.row_version,
                proof=_unlock_proof(lease),
            )
        assert fenced.value.effects.publish_candidate is False

        stored = session.scalar(
            sa.select(TenantDatabaseAccountRotation).where(
                TenantDatabaseAccountRotation.rotation_id == str(ROTATION)
            )
        )
        assert stored.state == AccountRotationState.PREPARED_LOCKED.value
        assert stored.candidate_published is False
        assert stored.row_version == prepared.row_version


def test_rotation_cas_rejects_a_concurrent_row_version_change(
    control_database,
):
    with control_database.transaction() as session:
        _claim(session)
        started = _start(_rotation_service(session))

    class ConcurrentWriteService(AccountRotationPersistenceService):
        def _lock_required_lease(self, tenant_uuid, account_kind):
            lease = super()._lock_required_lease(tenant_uuid, account_kind)
            self._session.execute(
                sa.update(TenantDatabaseAccountRotation)
                .where(
                    TenantDatabaseAccountRotation.rotation_id
                    == str(ROTATION)
                )
                .values(row_version=started.row_version + 1)
                .execution_options(synchronize_session=False)
            )
            return lease

    with control_database.transaction() as session:
        service = ConcurrentWriteService(session, database_clock=lambda _: NOW)
        with pytest.raises(AccountMutationFenceConflict) as caught:
            service.prepare_rotation(
                rotation_uuid=ROTATION,
                expected_row_version=started.row_version,
                proof=_preparation_proof(),
            )
        assert caught.value.effects.publish_candidate is False


def test_database_now_is_read_after_required_rows_are_locked(
    control_database,
):
    far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    with control_database.transaction() as session:
        claimed = _claim(session, expires_at=far_future)
    with control_database.transaction() as session:
        renewed = _lease_service(session, now=NOW).renew_lease(
            tenant_uuid=TENANT,
            account_kind=AccountKind.DML,
            owner=OWNER_A,
            fencing_token=claimed.lease.fencing_token,
            expected_row_version=claimed.lease.row_version,
            lease_expires_at=far_future + timedelta(days=1),
        )

    statements = []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement.lower())

    sa.event.listen(
        control_database.engine,
        "before_cursor_execute",
        capture,
    )
    try:
        with control_database.transaction() as session:
            AccountMutationLeasePersistenceService(session).renew_lease(
                tenant_uuid=TENANT,
                account_kind=AccountKind.DML,
                owner=OWNER_A,
                fencing_token=renewed.lease.fencing_token,
                expected_row_version=renewed.lease.row_version,
                lease_expires_at=far_future + timedelta(days=2),
            )
    finally:
        sa.event.remove(
            control_database.engine,
            "before_cursor_execute",
            capture,
        )
    lease_select = next(
        index
        for index, statement in enumerate(statements)
        if statement.lstrip().startswith("select")
        and "tenant_database_account_mutation_leases" in statement
        and "where" in statement
    )
    clock_select = next(
        index
        for index, statement in enumerate(statements)
        if statement.lstrip().startswith("select")
        and "utc_timestamp" in statement
    )
    assert lease_select < clock_select

    with control_database.transaction() as session:
        started = _start(_rotation_service(session))
    statements.clear()
    sa.event.listen(
        control_database.engine,
        "before_cursor_execute",
        capture,
    )
    try:
        with control_database.transaction() as session:
            AccountRotationPersistenceService(session).prepare_rotation(
                rotation_uuid=ROTATION,
                expected_row_version=started.row_version,
                proof=_preparation_proof(),
            )
    finally:
        sa.event.remove(
            control_database.engine,
            "before_cursor_execute",
            capture,
        )
    rotation_select = next(
        index
        for index, statement in enumerate(statements)
        if statement.lstrip().startswith("select")
        and "tenant_database_account_rotations" in statement
    )
    lease_select = next(
        index
        for index, statement in enumerate(statements)
        if statement.lstrip().startswith("select")
        and "tenant_database_account_mutation_leases" in statement
    )
    clock_select = next(
        index
        for index, statement in enumerate(statements)
        if statement.lstrip().startswith("select")
        and "utc_timestamp" in statement
    )
    assert rotation_select < lease_select < clock_select


def test_lock_wait_crossing_lease_expiry_cannot_publish_candidate(
    control_database,
):
    expires = NOW + timedelta(minutes=1)
    with control_database.transaction() as session:
        lease = _claim(session, expires_at=expires).lease
        service = _rotation_service(session)
        started = _start(service)
        prepared = service.prepare_rotation(
            rotation_uuid=ROTATION,
            expected_row_version=started.row_version,
            proof=_preparation_proof(),
        )
        testing = service.begin_candidate_testing(
            rotation_uuid=ROTATION,
            expected_row_version=prepared.row_version,
            proof=_unlock_proof(lease),
        )
        verified = service.verify_candidate(
            rotation_uuid=ROTATION,
            expected_row_version=testing.row_version,
            proof=_unlock_proof(lease),
        )

    observed_now = {"value": NOW}

    class ExpiryCrossingService(AccountRotationPersistenceService):
        def _lock_required_lease(self, tenant_uuid, account_kind):
            row = super()._lock_required_lease(tenant_uuid, account_kind)
            observed_now["value"] = expires
            return row

    with control_database.transaction() as session:
        service = ExpiryCrossingService(
            session,
            database_clock=lambda _: observed_now["value"],
        )
        with pytest.raises(AccountMutationLeaseExpired) as caught:
            service.switch_candidate(
                rotation_uuid=ROTATION,
                expected_row_version=verified.row_version,
                proof=_unlock_proof(lease),
            )
        assert caught.value.effects.publish_candidate is False

    with control_database.new_session() as session:
        stored = session.scalar(
            sa.select(TenantDatabaseAccountRotation).where(
                TenantDatabaseAccountRotation.rotation_id == str(ROTATION)
            )
        )
        assert stored.state == AccountRotationState.VERIFIED.value
        assert stored.candidate_published is False


def test_failed_rotation_is_persisted_and_replays_after_lease_expiry(
    control_database,
):
    with control_database.transaction() as session:
        _claim(session, expires_at=NOW + timedelta(minutes=1))
        service = _rotation_service(session)
        started = _start(service)
        prepared = service.prepare_rotation(
            rotation_uuid=ROTATION,
            expected_row_version=started.row_version,
            proof=_preparation_proof(),
        )
        failed = service.fail_rotation(
            rotation_uuid=ROTATION,
            expected_row_version=prepared.row_version,
            safe_error_code="CANDIDATE_CONNECTION_FAILED",
        )
        assert failed.rotation.state is AccountRotationState.FAILED
        assert failed.rotation.candidate_locked is True
        assert failed.effects.publish_candidate is False

    with control_database.transaction() as session:
        replay = _rotation_service(
            session,
            now=NOW + timedelta(hours=1),
        ).fail_rotation(
            rotation_uuid=ROTATION,
            expected_row_version=prepared.row_version,
            safe_error_code="CANDIDATE_CONNECTION_FAILED",
        )
        assert replay.idempotent_replay
        assert replay.row_version == failed.row_version


def test_outer_rollbacks_remove_lease_and_rotation_changes(control_database):
    with control_database.new_session() as session:
        outer = session.begin()
        _claim(session)
        outer.rollback()
    with control_database.new_session() as session:
        assert session.get(
            TenantDatabaseAccountMutationLease,
            (str(TENANT), AccountKind.DML.value),
        ) is None

    with control_database.transaction() as session:
        _claim(session)
    with control_database.new_session() as session:
        outer = session.begin()
        _start(_rotation_service(session))
        outer.rollback()
    with control_database.new_session() as session:
        assert session.scalar(
            sa.select(TenantDatabaseAccountRotation).where(
                TenantDatabaseAccountRotation.rotation_id == str(ROTATION)
            )
        ) is None


def test_persistence_schema_contains_no_secret_material():
    tables = (
        TenantDatabaseAccountMutationLease.__table__,
        TenantDatabaseAccountRotation.__table__,
    )
    column_names = {
        column.name.lower()
        for table in tables
        for column in table.columns
    }
    for forbidden in (
        "password",
        "password_hash",
        "ciphertext",
        "nonce",
        "dsn",
        "connection_url",
    ):
        assert not any(forbidden in name for name in column_names)
    digest = TenantDatabaseAccountRotation.__table__.c.last_request_digest
    assert digest.type.length == 32
    assert len(AccountRotationState) == 8
