from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from inventory_control import ControlDatabase
from inventory_control.fleet_migrations.runner import advisory_lock_name
from inventory_control.models.registration import (
    TenantRegistrationAttempt,
    TenantRegistrationProvisioningProof,
)
from inventory_control.models import (
    PlanRevision,
    PlatformAdmin,
    RedemptionCode,
    RedemptionCodeBatch,
    User,
)
from inventory_control.models.schema_operations import (
    PlatformSchemaOperationLease,
)
from inventory_control.registration.persistence import (
    RegistrationFinalCommitPlan,
    RegistrationSchemaOperationFence,
)
from inventory_control.registration.publication import (
    GlobalSchemaPublicationFenceHandle,
    RegistrationFinalPublicationFenceError,
    RegistrationFinalPublicationRequest,
    registration_publication_lock_binding_digest,
)
from inventory_control.registration.publication_adapters import (
    ControlDatabaseGlobalSchemaPublicationFencePort,
    DedicatedConnectionDatabaseAdvisoryPublicationLockPort,
    SQLAlchemyDedicatedPublicationLockConnectionFactory,
)
from inventory_control.schema_operations import (
    SCHEMA_OPERATION_LEASE_KEY,
    SchemaOperationLeasePersistenceService,
    SchemaOperationLeaseState,
    SchemaOperationPurpose,
)


NOW = datetime(2026, 8, 22, 12, 0, 0, 123456, tzinfo=timezone.utc)
ATTEMPT_UUID = UUID("d1000000-0000-4000-8000-000000000001")
TENANT_UUID = UUID("d1000000-0000-4000-8000-000000000002")
DATABASE_UUID = UUID("d1000000-0000-4000-8000-000000000003")
OTHER_DATABASE_UUID = UUID("d1000000-0000-4000-8000-000000000013")
RUN_UUID = UUID("d1000000-0000-4000-8000-000000000004")
PROOF_UUID = UUID("d1000000-0000-4000-8000-000000000005")
CLAIM_UUID = UUID("d1000000-0000-4000-8000-000000000006")
COMMIT_UUID = UUID("d1000000-0000-4000-8000-000000000007")
MEMBERSHIP_UUID = UUID("d1000000-0000-4000-8000-000000000008")
SUBSCRIPTION_UUID = UUID("d1000000-0000-4000-8000-000000000009")
EVENT_UUID = UUID("d1000000-0000-4000-8000-000000000010")
WAREHOUSE_UUID = UUID("d1000000-0000-4000-8000-000000000011")
USER_UUID = UUID("d1000000-0000-4000-8000-000000000012")
PLAN_UUID = UUID("d1000000-0000-4000-8000-000000000014")
ADMIN_UUID = UUID("d1000000-0000-4000-8000-000000000015")
BATCH_UUID = UUID("d1000000-0000-4000-8000-000000000016")
CODE_UUID = UUID("d1000000-0000-4000-8000-000000000017")
READY_DIGEST = hashlib.sha256(b"ready-proof-request").digest()
SCHEMA_DIGEST = hashlib.sha256(b"schema").digest()
IDENTITY_DIGEST = hashlib.sha256(b"identity").digest()
SMOKE_DIGEST = hashlib.sha256(b"smoke").digest()
ADVISORY_DIGEST = hashlib.sha256(b"advisory-proof").digest()
ENTITLEMENTS = {"features": {}, "limits": {"member_seats": 10}}
ENTITLEMENTS_DIGEST = hashlib.sha256(b"publication-entitlements").digest()


def _request() -> RegistrationFinalPublicationRequest:
    return RegistrationFinalPublicationRequest(
        attempt_uuid=ATTEMPT_UUID,
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        current_recovery_run_uuid=RUN_UUID,
        provisioning_generation=1,
        expected_attempt_row_version=3,
        expected_code_row_version=2,
        ready_proof_uuid=PROOF_UUID,
        ready_proof_request_digest=READY_DIGEST,
        lock_idempotency_key="registration-publication-adapter-v1",
        plan=RegistrationFinalCommitPlan(
            registration_commit_uuid=COMMIT_UUID,
            membership_uuid=MEMBERSHIP_UUID,
            subscription_uuid=SUBSCRIPTION_UUID,
            subscription_event_uuid=EVENT_UUID,
            published_tenant_name="Adapter Test Tenant",
            published_slug="adapter-test-tenant",
            idempotency_key="registration-final-adapter-v1",
        ),
    )


@pytest.fixture
def control_database(mysql_routed_database):
    database = mysql_routed_database
    with database.transaction() as session:
        session.add_all((
            User(
                id=str(USER_UUID),
                phone_e164="+8613812345678",
                phone_normalization_version=1,
                phone_metadata_version="cn-mobile-v1",
                phone_verified_at=NOW - timedelta(minutes=5),
                status="active",
                created_at=NOW - timedelta(days=1),
                updated_at=NOW - timedelta(days=1),
            ),
            PlanRevision(
                id=str(PLAN_UUID),
                code="publication-adapter",
                revision=1,
                name="Publication Adapter",
                entitlements_schema_version=1,
                entitlements_json=ENTITLEMENTS,
                entitlements_digest=ENTITLEMENTS_DIGEST,
                active=True,
                created_at=NOW - timedelta(days=1),
                updated_at=NOW - timedelta(days=1),
            ),
            PlatformAdmin(
                id=str(ADMIN_UUID),
                username_canonical="publication.adapter.admin",
                status="active",
                password_hash_encoded="$test-v1$redacted",
                password_hash_algorithm="test",
                password_hash_version=1,
                created_at=NOW - timedelta(days=1),
                updated_at=NOW - timedelta(days=1),
            ),
            PlatformSchemaOperationLease(
                lease_key=SCHEMA_OPERATION_LEASE_KEY,
                state=SchemaOperationLeaseState.AVAILABLE.value,
                generation=0,
                fencing_token=0,
                row_version=1,
                observed_at=NOW,
            ),
        ))
        session.flush()
        session.add(
            RedemptionCodeBatch(
                id=str(BATCH_UUID),
                generation_request_uuid=str(uuid4()),
                request_digest=hashlib.sha256(b"publication-batch").digest(),
                name="Publication adapter batch",
                quantity=1,
                plan_revision_uuid=str(PLAN_UUID),
                entitlements_schema_version=1,
                entitlements_json=ENTITLEMENTS,
                entitlements_digest=ENTITLEMENTS_DIGEST,
                service_duration_seconds=30 * 24 * 60 * 60,
                default_redeem_before=NOW + timedelta(days=30),
                created_by_platform_admin_id=str(ADMIN_UUID),
                created_at=NOW - timedelta(days=1),
                plaintext_exported_at=NOW - timedelta(hours=23),
            )
        )
        session.flush()
        session.add(
            RedemptionCode(
                id=str(CODE_UUID),
                crypto_context_uuid=str(uuid4()),
                batch_id=str(BATCH_UUID),
                code_prefix="TEST",
                lookup_hash=hashlib.sha256(b"publication-code").digest(),
                code_ciphertext=b"c" * 42,
                code_nonce=b"n" * 12,
                secret_revision=1,
                root_key_version=1,
                crypto_version=1,
                aad_version=1,
                status="active",
                plan_revision_uuid=str(PLAN_UUID),
                entitlements_schema_version=1,
                entitlements_json=ENTITLEMENTS,
                entitlements_digest=ENTITLEMENTS_DIGEST,
                service_duration_seconds=30 * 24 * 60 * 60,
                redeem_before=NOW + timedelta(days=30),
                created_under_recovery_run_uuid=str(RUN_UUID),
                row_version=1,
                created_at=NOW - timedelta(days=1),
                updated_at=NOW - timedelta(days=1),
            )
        )
        session.flush()
        session.add(
            TenantRegistrationAttempt(
                id=str(ATTEMPT_UUID),
                user_id=str(USER_UUID),
                redemption_code_id=str(CODE_UUID),
                requested_tenant_name="Adapter Test Tenant",
                provisional_tenant_uuid=str(TENANT_UUID),
                provisional_database_uuid=str(DATABASE_UUID),
                status="provisioning",
                idempotency_key="publication-adapter-attempt-v1",
                request_digest=READY_DIGEST,
                provisioning_execution_generation=1,
                lease_owner="registration-provisioner-1",
                lease_token="worker-token",
                lease_expires_at=NOW + timedelta(minutes=30),
                attempt_count=0,
                recovery_run_uuid=str(RUN_UUID),
                row_version=3,
                created_at=NOW - timedelta(minutes=5),
                updated_at=NOW,
            )
        )
    with database.transaction() as session:
        claimed = SchemaOperationLeasePersistenceService(
            session,
            database_clock=lambda _session: NOW,
        ).claim(
            claim_id=CLAIM_UUID,
            owner_id="registration-provisioner-1",
            purpose=SchemaOperationPurpose.PROVISIONING,
            expected_row_version=1,
            lease_expires_at=NOW + timedelta(hours=1),
        )
    lease = claimed.lease
    with database.transaction() as session:
        session.add(
            TenantRegistrationProvisioningProof(
                id=str(PROOF_UUID),
                attempt_uuid=str(ATTEMPT_UUID),
                user_uuid="d1000000-0000-4000-8000-000000000012",
                tenant_uuid=str(TENANT_UUID),
                database_uuid=str(DATABASE_UUID),
                recovery_run_uuid=str(RUN_UUID),
                provisioning_execution_generation=1,
                expected_attempt_row_version=2,
                worker_lease_owner="registration-provisioner-1",
                worker_lease_token_digest=hashlib.sha256(
                    b"worker-token"
                ).digest(),
                worker_lease_expires_at=NOW + timedelta(minutes=30),
                outcome="ready",
                safe_error_code=None,
                result_request_digest=READY_DIGEST,
                schema_operation_claim_uuid=str(lease.claim_id),
                schema_operation_owner_id=lease.owner_id,
                schema_operation_generation=lease.generation,
                schema_operation_fencing_token=lease.fencing_token,
                schema_operation_row_version=lease.row_version,
                schema_generation=1,
                schema_digest=SCHEMA_DIGEST,
                database_identity_digest=IDENTITY_DIGEST,
                route_version=1,
                initial_credential_generation=1,
                dml_login_state_version=1,
                default_warehouse_uuid=str(WAREHOUSE_UUID),
                default_warehouse_digest=hashlib.sha256(
                    b"warehouse"
                ).digest(),
                smoke_proof_digest=SMOKE_DIGEST,
                advisory_lock_proof_digest=ADVISORY_DIGEST,
                proof_policy_version=1,
                recorded_at=NOW + timedelta(seconds=1),
            )
        )
    return database


def _global_port(control_database, *, clock=None):
    return ControlDatabaseGlobalSchemaPublicationFencePort(
        control_database=control_database,
        database_clock=clock or (lambda _session: NOW + timedelta(minutes=10)),
    )


@pytest.fixture
def provisioner_engine(mysql_routed_database):
    return mysql_routed_database.engine


def _track_pool(engine):
    active: dict[int, int] = {}
    checkins: list[int] = []
    invalidations: list[int] = []
    physical_closes: list[int] = []
    transaction_outcomes: list[str] = []

    @sa.event.listens_for(engine, "checkout")
    def on_checkout(dbapi_connection, connection_record, _proxy):
        record_id = id(connection_record)
        connection_id = id(dbapi_connection)
        active[record_id] = connection_id

    @sa.event.listens_for(engine, "checkin")
    def on_checkin(_dbapi_connection, connection_record):
        checkins.append(id(connection_record))
        active.pop(id(connection_record), None)

    @sa.event.listens_for(engine.pool, "invalidate")
    def on_invalidate(dbapi_connection, _connection_record, _error):
        invalidations.append(id(dbapi_connection))

    @sa.event.listens_for(engine.pool, "close")
    def on_close(dbapi_connection, _connection_record):
        physical_closes.append(id(dbapi_connection))

    @sa.event.listens_for(engine, "commit")
    def on_commit(_connection):
        transaction_outcomes.append("commit")

    @sa.event.listens_for(engine, "rollback")
    def on_rollback(_connection):
        transaction_outcomes.append("rollback")

    return {
        "active": active,
        "checkins": checkins,
        "invalidations": invalidations,
        "physical_closes": physical_closes,
        "transaction_outcomes": transaction_outcomes,
    }


def test_sqlalchemy_factory_resolves_exact_target_and_owns_each_connection(
    provisioner_engine,
):
    tracked = _track_pool(provisioner_engine)
    resolved: list[UUID] = []

    def resolve_engine(database_uuid):
        resolved.append(database_uuid)
        return provisioner_engine

    factory = SQLAlchemyDedicatedPublicationLockConnectionFactory(
        engine_resolver=resolve_engine,
    )
    first = factory(DATABASE_UUID)
    second = factory(OTHER_DATABASE_UUID)
    first_token = first.scalar(
        sa.text("SELECT CONNECTION_ID()")
    )
    second_token = second.scalar(
        sa.text("SELECT CONNECTION_ID()")
    )

    # A Session checked out while both publication connections are live must
    # receive a third physical connection; the factory never accepts/reuses it.
    with sa.orm.Session(provisioner_engine) as business_session:
        business_token = business_session.scalar(
            sa.text("SELECT CONNECTION_ID()")
        )
    assert len({first_token, second_token, business_token}) == 3
    assert resolved == [DATABASE_UUID, OTHER_DATABASE_UUID]
    assert len(tracked["active"]) == 2

    first.rollback()
    first.close()
    second.rollback()
    second.close()

    assert tracked["active"] == {}
    assert len(tracked["invalidations"]) == 2
    assert len(tracked["physical_closes"]) == 2


def test_sqlalchemy_factory_commit_rollback_close_and_no_pool_leak(
    provisioner_engine,
):
    tracked = _track_pool(provisioner_engine)
    factory = SQLAlchemyDedicatedPublicationLockConnectionFactory(
        engine_resolver=lambda database_uuid: provisioner_engine,
    )

    insert_probe = sa.text(
        "INSERT INTO device_models "
        "(name, display_name, is_active, is_accessory, created_at, updated_at) "
        "VALUES (:name, :name, 1, 0, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6)) "
        "RETURNING id"
    )

    committed = factory(DATABASE_UUID)
    assert isinstance(
        committed.scalar(insert_probe, {"name": "publication-probe-1"}),
        int,
    )
    committed.commit()
    committed.close()
    assert tracked["transaction_outcomes"] == ["commit"]
    assert tracked["active"] == {}

    rolled_back = factory(DATABASE_UUID)
    assert isinstance(
        rolled_back.scalar(insert_probe, {"name": "publication-probe-2"}),
        int,
    )
    rolled_back.rollback()
    rolled_back.close()
    assert tracked["transaction_outcomes"] == ["commit", "rollback"]
    assert len(tracked["invalidations"]) == 1
    assert tracked["active"] == {}

    closed_without_outcome = factory(DATABASE_UUID)
    assert isinstance(
        closed_without_outcome.scalar(
            insert_probe,
            {"name": "publication-probe-3"},
        ),
        int,
    )
    closed_without_outcome.close()
    assert tracked["transaction_outcomes"] == [
        "commit",
        "rollback",
        "rollback",
    ]
    assert len(tracked["invalidations"]) == 2
    assert len(tracked["physical_closes"]) == 2
    assert tracked["active"] == {}

    with provisioner_engine.connect() as connection:
        values = connection.scalars(
            sa.text(
                "SELECT name FROM device_models "
                "WHERE name LIKE 'publication-probe-%' ORDER BY name"
            ),
        ).all()
    assert values == ["publication-probe-1"]
    assert tracked["active"] == {}


def test_invalid_resolved_engine_fails_closed_before_database_io():
    resolved: list[UUID] = []

    def resolve_engine(database_uuid):
        resolved.append(database_uuid)
        return object()

    port = DedicatedConnectionDatabaseAdvisoryPublicationLockPort(
        connection_factory=(
            SQLAlchemyDedicatedPublicationLockConnectionFactory(
                engine_resolver=resolve_engine,
            )
        ),
        lock_timeout_seconds=1,
    )

    with pytest.raises(RegistrationFinalPublicationFenceError) as caught:
        port.acquire(
            request=_request(),
            schema_fence=_schema_handle(_request()),
        )

    assert str(caught.value) == "REGISTRATION_FINAL_PUBLICATION_FENCE_REJECTED"
    assert "CONNECTION_ID" not in str(caught.value)
    assert resolved == [DATABASE_UUID]


def test_sqlalchemy_factory_keeps_one_physical_connection_for_lock_lifecycle(
    provisioner_engine,
):
    statement_connections: list[int] = []

    @sa.event.listens_for(provisioner_engine, "before_cursor_execute")
    def record_statement_connection(
        connection,
        _cursor,
        _statement,
        _parameters,
        _context,
        _executemany,
    ):
        statement_connections.append(
            id(connection.connection.dbapi_connection)
        )

    tracked = _track_pool(provisioner_engine)
    resolved: list[UUID] = []

    def resolve_engine(database_uuid):
        resolved.append(database_uuid)
        return provisioner_engine

    port = DedicatedConnectionDatabaseAdvisoryPublicationLockPort(
        connection_factory=(
            SQLAlchemyDedicatedPublicationLockConnectionFactory(
                engine_resolver=resolve_engine,
            )
        ),
        lock_timeout_seconds=1,
    )
    request = _request()
    schema_fence = _schema_handle(request)

    handle = port.acquire(request=request, schema_fence=schema_fence)
    port.require_current(
        request=request,
        schema_fence=schema_fence,
        advisory_lock=handle,
    )
    port.release(
        request=request,
        schema_fence=schema_fence,
        advisory_lock=handle,
    )
    sa.event.remove(
        provisioner_engine,
        "before_cursor_execute",
        record_statement_connection,
    )

    assert resolved == [DATABASE_UUID]
    assert len(statement_connections) == 8
    assert len(set(statement_connections)) == 1
    assert tracked["transaction_outcomes"] == ["commit"]
    assert tracked["invalidations"] == []
    assert tracked["physical_closes"] == []
    assert tracked["active"] == {}
    with provisioner_engine.connect() as connection:
        assert connection.scalar(
            sa.text("SELECT IS_USED_LOCK(:lock_name)"),
            {"lock_name": advisory_lock_name(DATABASE_UUID)},
        ) is None


def test_global_adapter_uses_uninterrupted_ready_claim_and_real_persistence(
    control_database,
):
    request = _request()
    port = _global_port(control_database)

    handle = port.acquire(request=request)
    assert handle.claim_uuid == CLAIM_UUID
    assert handle.fencing_token == 1
    assert handle.schema_operation_fence.row_version == 2
    port.require_current(request=request, fence=handle)
    with control_database.transaction() as final_session:
        transaction = final_session.get_transaction()
        physical_connection = (
            final_session.connection().connection.dbapi_connection
        )
        port.require_current_in_transaction(
            control_transaction=final_session,
            request=request,
            fence=handle,
        )
        assert final_session.get_transaction() is transaction
        assert (
            final_session.connection().connection.dbapi_connection
            is physical_connection
        )
        assert not final_session.dirty

    port.release(request=request, fence=handle)
    # A response-lost or concurrent exact caller may observe that this same
    # claim was already released; it must not turn a safe no-op into a leak.
    port.release(request=request, fence=handle)
    with control_database.transaction() as session:
        row = session.get(
            PlatformSchemaOperationLease,
            SCHEMA_OPERATION_LEASE_KEY,
        )
        assert row is not None
        assert row.state == "available"
        assert row.row_version == 3


def test_global_adapter_accepts_same_claim_renewal_row_version_advance(
    control_database,
):
    request = _request()
    with control_database.transaction() as session:
        renewed = SchemaOperationLeasePersistenceService(
            session,
            database_clock=lambda _session: NOW + timedelta(minutes=1),
        ).renew(
            claim_id=CLAIM_UUID,
            owner_id="registration-provisioner-1",
            purpose=SchemaOperationPurpose.PROVISIONING,
            fencing_token=1,
            expected_row_version=2,
            lease_expires_at=NOW + timedelta(hours=2),
        )
    assert renewed.lease.row_version == 3

    port = _global_port(control_database)
    handle = port.acquire(request=request)
    assert handle.schema_operation_fence.row_version == 3

    with control_database.transaction() as session:
        SchemaOperationLeasePersistenceService(
            session,
            database_clock=lambda _session: NOW + timedelta(minutes=2),
        ).renew(
            claim_id=CLAIM_UUID,
            owner_id="registration-provisioner-1",
            purpose=SchemaOperationPurpose.PROVISIONING,
            fencing_token=1,
            expected_row_version=3,
            lease_expires_at=NOW + timedelta(hours=3),
        )

    port.require_current(request=request, fence=handle)
    port.release(request=request, fence=handle)
    with control_database.transaction() as session:
        row = session.get(PlatformSchemaOperationLease, SCHEMA_OPERATION_LEASE_KEY)
        assert row is not None and row.state == "available"
        assert row.row_version == 5


def test_global_adapter_rejects_expiry_turnover_and_wrong_final_session(
    control_database,
):
    request = _request()
    expired = _global_port(
        control_database,
        clock=lambda _session: NOW + timedelta(hours=2),
    )
    with pytest.raises(RegistrationFinalPublicationFenceError) as caught:
        expired.acquire(request=request)
    assert str(caught.value) == "REGISTRATION_FINAL_PUBLICATION_FENCE_REJECTED"
    assert "registration-provisioner-1" not in str(caught.value)

    port = _global_port(control_database)
    handle = port.acquire(request=request)
    other = ControlDatabase.from_url(
        control_database.engine.url.render_as_string(hide_password=False),
        engine_options={"pool_pre_ping": True},
    )
    try:
        with other.transaction() as wrong_session:
            with pytest.raises(RegistrationFinalPublicationFenceError):
                port.require_current_in_transaction(
                    control_transaction=wrong_session,
                    request=request,
                    fence=handle,
                )
    finally:
        other.dispose()
    port.release(request=request, fence=handle)


def test_global_adapter_rejects_proof_or_claim_drift_without_details(
    control_database,
):
    request = _request()
    with control_database.transaction() as session:
        proof = session.get(TenantRegistrationProvisioningProof, str(PROOF_UUID))
        assert proof is not None
        proof.result_request_digest = hashlib.sha256(b"drift").digest()

    with pytest.raises(RegistrationFinalPublicationFenceError) as caught:
        _global_port(control_database).acquire(request=request)
    assert str(caught.value) == "REGISTRATION_FINAL_PUBLICATION_FENCE_REJECTED"
    assert "drift" not in repr(caught.value)


class FakeDedicatedConnection:
    def __init__(
        self,
        *,
        connection_id=41,
        get_lock_result=1,
        raise_after_get_lock=False,
        raise_on_commit=False,
    ):
        self.connection_id = connection_id
        self.get_lock_result = get_lock_result
        self.raise_after_get_lock = raise_after_get_lock
        self.raise_on_commit = raise_on_commit
        self.lock_name: str | None = None
        self.lock_owner: int | None = None
        self.closed = False
        self.commits = 0
        self.rollbacks = 0
        self.calls: list[tuple[str, dict[str, object]]] = []

    def scalar(self, statement, parameters=None):
        sql = str(statement)
        params = dict(parameters or {})
        self.calls.append((sql, params))
        if sql == "SELECT CONNECTION_ID()":
            return self.connection_id
        if sql == "SELECT GET_LOCK(:lock_name, :timeout_seconds)":
            if self.get_lock_result == 1:
                self.lock_name = str(params["lock_name"])
                self.lock_owner = self.connection_id
            if self.raise_after_get_lock:
                raise RuntimeError("private-driver-detail")
            return self.get_lock_result
        if sql == "SELECT IS_USED_LOCK(:lock_name)":
            if params["lock_name"] == self.lock_name:
                return self.lock_owner
            return None
        if sql == "SELECT RELEASE_LOCK(:lock_name)":
            if (
                params["lock_name"] == self.lock_name
                and self.lock_owner == self.connection_id
            ):
                self.lock_owner = None
                return 1
            return 0
        raise AssertionError("unexpected closed SQL statement")

    def commit(self):
        self.commits += 1
        if self.raise_on_commit:
            raise RuntimeError("private-driver-commit-detail")

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class FakeDedicatedFactory:
    def __init__(self, connection):
        self.connection = connection
        self.database_uuids: list[UUID] = []

    def __call__(self, database_uuid):
        self.database_uuids.append(database_uuid)
        return self.connection


def _schema_handle(request):
    # Reuse the concrete handle constructor without introducing a second
    # connection or control database into advisory-only tests.
    return GlobalSchemaPublicationFenceHandle(
        schema_operation_fence=RegistrationSchemaOperationFence(
            claim_uuid=CLAIM_UUID,
            owner_id="registration-provisioner-1",
            generation=1,
            fencing_token=1,
            row_version=2,
        ),
        purpose="provisioning",
        request_binding_digest=registration_publication_lock_binding_digest(
            request
        ),
    )


def test_advisory_adapter_uses_uuid_factory_closed_sql_and_one_connection():
    request = _request()
    schema_fence = _schema_handle(request)
    connection = FakeDedicatedConnection()
    factory = FakeDedicatedFactory(connection)
    port = DedicatedConnectionDatabaseAdvisoryPublicationLockPort(
        connection_factory=factory,
        lock_timeout_seconds=7,
    )

    handle = port.acquire(request=request, schema_fence=schema_fence)
    assert factory.database_uuids == [DATABASE_UUID]
    assert connection.closed is False
    assert connection.lock_name == advisory_lock_name(DATABASE_UUID)
    port.require_current(
        request=request,
        schema_fence=schema_fence,
        advisory_lock=handle,
    )
    port.release(
        request=request,
        schema_fence=schema_fence,
        advisory_lock=handle,
    )

    assert connection.closed is True
    assert connection.lock_owner is None
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert all(
        set(parameters) <= {"lock_name", "timeout_seconds"}
        for _, parameters in connection.calls
    )
    assert not any(
        key in parameters
        for _, parameters in connection.calls
        for key in ("dsn", "schema", "database_name", "sql")
    )


def test_advisory_adapter_fails_closed_on_denial_or_lost_ownership():
    request = _request()
    schema_fence = _schema_handle(request)
    denied_connection = FakeDedicatedConnection(get_lock_result=0)
    denied = DedicatedConnectionDatabaseAdvisoryPublicationLockPort(
        connection_factory=FakeDedicatedFactory(denied_connection),
        lock_timeout_seconds=1,
    )
    with pytest.raises(RegistrationFinalPublicationFenceError) as caught:
        denied.acquire(request=request, schema_fence=schema_fence)
    assert denied_connection.closed is True
    assert denied_connection.commits == 0
    assert denied_connection.rollbacks == 1
    assert "GET_LOCK" not in str(caught.value)

    connection = FakeDedicatedConnection()
    port = DedicatedConnectionDatabaseAdvisoryPublicationLockPort(
        connection_factory=FakeDedicatedFactory(connection),
        lock_timeout_seconds=1,
    )
    handle = port.acquire(request=request, schema_fence=schema_fence)
    connection.lock_owner = 999
    with pytest.raises(RegistrationFinalPublicationFenceError):
        port.require_current(
            request=request,
            schema_fence=schema_fence,
            advisory_lock=handle,
        )
    with pytest.raises(RegistrationFinalPublicationFenceError):
        port.release(
            request=request,
            schema_fence=schema_fence,
            advisory_lock=handle,
        )
    assert connection.closed is True
    assert connection.commits == 0
    assert connection.rollbacks == 1


def test_advisory_unknown_acquire_releases_same_connection_and_closes():
    request = _request()
    schema_fence = _schema_handle(request)
    connection = FakeDedicatedConnection(raise_after_get_lock=True)
    port = DedicatedConnectionDatabaseAdvisoryPublicationLockPort(
        connection_factory=FakeDedicatedFactory(connection),
        lock_timeout_seconds=1,
    )

    with pytest.raises(RegistrationFinalPublicationFenceError) as caught:
        port.acquire(request=request, schema_fence=schema_fence)

    assert str(caught.value) == "REGISTRATION_FINAL_PUBLICATION_FENCE_REJECTED"
    assert connection.lock_owner is None
    assert connection.closed is True
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert [sql for sql, _ in connection.calls][-1] == (
        "SELECT RELEASE_LOCK(:lock_name)"
    )


def test_advisory_handle_is_bound_to_schema_fence_and_cannot_be_replayed():
    request = _request()
    schema_fence = _schema_handle(request)
    connection = FakeDedicatedConnection()
    port = DedicatedConnectionDatabaseAdvisoryPublicationLockPort(
        connection_factory=FakeDedicatedFactory(connection),
        lock_timeout_seconds=1,
    )
    handle = port.acquire(request=request, schema_fence=schema_fence)
    forged = replace(
        handle,
        acquisition_proof_digest=hashlib.sha256(b"forged").digest(),
    )
    with pytest.raises(RegistrationFinalPublicationFenceError):
        port.require_current(
            request=request,
            schema_fence=schema_fence,
            advisory_lock=forged,
        )
    port.release(
        request=request,
        schema_fence=schema_fence,
        advisory_lock=handle,
    )

    with pytest.raises(RegistrationFinalPublicationFenceError):
        port.require_current(
            request=request,
            schema_fence=schema_fence,
            advisory_lock=handle,
        )


def test_advisory_commit_failure_rolls_back_closes_and_forgets_hold():
    request = _request()
    schema_fence = _schema_handle(request)
    connection = FakeDedicatedConnection(raise_on_commit=True)
    port = DedicatedConnectionDatabaseAdvisoryPublicationLockPort(
        connection_factory=FakeDedicatedFactory(connection),
        lock_timeout_seconds=1,
    )
    handle = port.acquire(request=request, schema_fence=schema_fence)

    with pytest.raises(RegistrationFinalPublicationFenceError) as caught:
        port.release(
            request=request,
            schema_fence=schema_fence,
            advisory_lock=handle,
        )

    assert str(caught.value) == "REGISTRATION_FINAL_PUBLICATION_FENCE_REJECTED"
    assert connection.commits == 1
    assert connection.rollbacks == 1
    assert connection.closed is True
