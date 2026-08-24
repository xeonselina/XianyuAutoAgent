from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa

from inventory_control import ControlBase, ControlDatabase
from inventory_control.models import (
    DatabaseIdentityControlRecord,
    DisasterRecoveryRun,
    PlanRevision,
    PlatformAdmin,
    PlatformAdminSession,
    PlatformAdminTotpCredential,
    PlatformSchemaOperationLease,
    RedemptionCode,
    RedemptionCodeBatch,
    RedemptionCodeReplacement,
    RegistrationIntegrityIncident,
    Subscription,
    SubscriptionEvent,
    Tenant,
    TenantDatabase,
    TenantInvitation,
    TenantMembership,
    TenantRegistrationAttempt,
    TenantRegistrationCommit,
    TenantRecoveryHold,
    User,
)
from inventory_control.models.registration import (
    TenantRegistrationProvisioningProof,
)
from inventory_control.models.sms import SmsChallenge
from inventory_control.registration import persistence as registration_persistence
from inventory_control.registration import (
    REGISTRATION_RESERVATION_REVISION,
    REGISTRATION_RETRY_REVISION,
    DatabaseAdvisoryLockHandle,
    GlobalSchemaPublicationFenceHandle,
    PersistedTenantReadyProof,
    ProvisionalTenantEndpoint,
    ProvisionedRegistrationFacts,
    ReadyPublicationState,
    RegistrationAuthorityError,
    RegistrationAuthorityFacts,
    RegistrationCodeError,
    RegistrationConflictError,
    RegistrationFenceError,
    RegistrationFinalCommitPlan,
    RegistrationFinalPublicationAuthority,
    RegistrationFinalPublicationInvariantError,
    RegistrationFinalPublicationRequest,
    RegistrationFinalizationResult,
    RegistrationOtpError,
    RegistrationPersistenceAtomicFinalCommitPort,
    RegistrationPersistenceCommittedPublicationCurrentRead,
    RegistrationPersistenceService,
    RegistrationSchemaOperationFence,
    RegistrationTransactionError,
    RecoveryRegistrationAuthorityAdapter,
    registration_publication_lock_binding_digest,
    reservation_action_digest,
    retry_action_digest,
)
from inventory_control.recovery import RecoveryAuthorityService
from inventory_control.subscriptions import parse_core_entitlements


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
RUN_UUID = UUID("30000000-0000-4000-8000-000000000001")
HOLD_UUID = UUID("30000000-0000-4000-8000-000000000002")
USER_UUID = UUID("30000000-0000-4000-8000-000000000003")
PLAN_UUID = UUID("30000000-0000-4000-8000-000000000004")
ADMIN_UUID = UUID("30000000-0000-4000-8000-000000000005")
BATCH_UUID = UUID("30000000-0000-4000-8000-000000000006")
CODE_UUID = UUID("30000000-0000-4000-8000-000000000007")
ATTEMPT_UUID = UUID("30000000-0000-4000-8000-000000000008")
TENANT_UUID = UUID("30000000-0000-4000-8000-000000000009")
DATABASE_UUID = UUID("30000000-0000-4000-8000-000000000010")
CHALLENGE_UUID = UUID("30000000-0000-4000-8000-000000000011")
RETRY_CHALLENGE_UUID = UUID("30000000-0000-4000-8000-000000000012")
COMMIT_UUID = UUID("30000000-0000-4000-8000-000000000013")
MEMBERSHIP_UUID = UUID("30000000-0000-4000-8000-000000000014")
SUBSCRIPTION_UUID = UUID("30000000-0000-4000-8000-000000000015")
EVENT_UUID = UUID("30000000-0000-4000-8000-000000000016")
DEFAULT_WAREHOUSE_UUID = UUID("30000000-0000-4000-8000-000000000017")
SCHEMA_CLAIM_UUID = UUID("30000000-0000-4000-8000-000000000018")
LOOKUP_HASH = hashlib.sha256(b"registration-code").digest()
SCHEMA_DIGEST = hashlib.sha256(b"tenant-schema-v1").digest()
IDENTITY_DIGEST = hashlib.sha256(b"database-identity-v1").digest()
DEFAULT_WAREHOUSE_DIGEST = hashlib.sha256(b"default-warehouse-v1").digest()
SMOKE_PROOF_DIGEST = hashlib.sha256(b"smoke-proof-v1").digest()
ADVISORY_LOCK_PROOF_DIGEST = hashlib.sha256(
    b"advisory-lock-proof-v1"
).digest()
READY_PROOF_UUID = UUID("30000000-0000-4000-8000-000000000019")
ENTITLEMENTS = {
    "features": {"multi_warehouse": True},
    "limits": {"member_seats": 10},
}
TENANT_NAME = "Acme Rentals"
TENANT_SLUG = "acme-rentals"
RESERVATION_KEY = "registration-reserve-1"
FINAL_KEY = "registration-finalize-1"
LEASE_OWNER = "worker-1"
LEASE_TOKEN = "lease-token-1"
LEASE_EXPIRES_AT = NOW + timedelta(minutes=30)
SERVICE_SECONDS = 30 * 24 * 60 * 60
HOST_FINGERPRINT = "h" * 64
DEPLOYMENT_MARKER_FINGERPRINT = "d" * 64
READY_PROOF_REQUEST_DIGEST = (
    registration_persistence._database_ready_request_digest(
        attempt_uuid=str(ATTEMPT_UUID),
        expected_attempt_row_version=1,
        expected_provisioning_generation=1,
        expected_code_row_version=2,
        current_recovery_run_uuid=RUN_UUID,
        schema_operation_fence=RegistrationSchemaOperationFence(
            claim_uuid=SCHEMA_CLAIM_UUID,
            owner_id="schema-worker-1",
            generation=1,
            fencing_token=1,
            row_version=2,
        ),
        provisioned=ProvisionedRegistrationFacts(
            tenant_uuid=TENANT_UUID,
            database_uuid=DATABASE_UUID,
            provisioning_generation=1,
            lease_owner=LEASE_OWNER,
            lease_token=LEASE_TOKEN,
            schema_generation=1,
            schema_digest=SCHEMA_DIGEST,
            database_identity_digest=IDENTITY_DIGEST,
            route_version=1,
            initial_credential_generation=1,
            dml_login_state_version=1,
            default_warehouse_uuid=DEFAULT_WAREHOUSE_UUID,
            default_warehouse_digest=DEFAULT_WAREHOUSE_DIGEST,
            smoke_proof_digest=SMOKE_PROOF_DIGEST,
            advisory_lock_proof_digest=ADVISORY_LOCK_PROOF_DIGEST,
            backup_ddl_lease_held=True,
            database_advisory_lock_held=True,
            smoke_passed=True,
            business_route_unpublished=True,
        ),
    )
)


@dataclass
class AuthorityReader:
    facts: RegistrationAuthorityFacts
    calls: int = 0

    def __call__(
        self,
        session,
        *,
        tenant_uuid,
        expected_recovery_run_uuid,
        database_now,
    ) -> RegistrationAuthorityFacts:
        del session, tenant_uuid, expected_recovery_run_uuid, database_now
        self.calls += 1
        return self.facts


@dataclass
class ProvisioningReader:
    facts: ProvisionedRegistrationFacts
    calls: int = 0

    def __call__(
        self,
        session,
        *,
        tenant_uuid,
        database_uuid,
        provisioning_generation,
        worker_lease_owner,
        worker_lease_token,
        schema_operation_fence,
        database_now,
    ) -> ProvisionedRegistrationFacts:
        del (
            session,
            tenant_uuid,
            database_uuid,
            provisioning_generation,
            worker_lease_owner,
            worker_lease_token,
            schema_operation_fence,
            database_now,
        )
        self.calls += 1
        return self.facts


@pytest.fixture
def database(mysql_control_database):
    value = mysql_control_database
    snapshot = parse_core_entitlements(
        schema_version=1,
        entitlements=ENTITLEMENTS,
    )
    with value.transaction() as session:
        session.add_all(
            [
                User(
                    id=str(USER_UUID),
                    phone_e164="+8613812345678",
                    phone_normalization_version=1,
                    phone_metadata_version="cn-mobile-v1",
                    phone_verified_at=NOW - timedelta(minutes=5),
                    status="active",
                ),
                PlatformAdmin(
                    id=str(ADMIN_UUID),
                    username_canonical="registration-admin",
                    status="active",
                    password_hash_encoded="scrypt$redacted",
                    password_hash_algorithm="scrypt",
                    password_hash_version=1,
                    created_at=NOW - timedelta(days=1),
                    updated_at=NOW - timedelta(days=1),
                ),
                PlanRevision(
                    id=str(PLAN_UUID),
                    code="core",
                    revision=1,
                    name="Core",
                    entitlements_schema_version=1,
                    entitlements_json=ENTITLEMENTS,
                    entitlements_digest=snapshot.digest_sha256,
                    active=True,
                    created_at=NOW - timedelta(days=1),
                    updated_at=NOW - timedelta(days=1),
                ),
                DisasterRecoveryRun(
                    id=str(RUN_UUID),
                    kind="initial_baseline",
                    policy_version=1,
                    status="completed",
                    expected_survivor_count=0,
                    actual_survivor_count=0,
                    host_installation_fingerprint=HOST_FINGERPRINT,
                    deployment_marker_fingerprint=(
                        DEPLOYMENT_MARKER_FINGERPRINT
                    ),
                    row_version=1,
                    started_at=NOW - timedelta(days=1),
                    reviewing_at=NOW - timedelta(hours=1),
                    completed_at=NOW - timedelta(minutes=30),
                    created_at=NOW - timedelta(days=1),
                    updated_at=NOW - timedelta(minutes=30),
                ),
                PlatformSchemaOperationLease(
                    lease_key="fleet_schema_operation",
                    state="available",
                    generation=0,
                    fencing_token=0,
                    row_version=1,
                    observed_at=NOW - timedelta(hours=1),
                ),
            ]
        )
        session.flush()
        session.add(
            RedemptionCodeBatch(
                id=str(BATCH_UUID),
                generation_request_uuid=(
                    "30000000-0000-4000-8000-000000000099"
                ),
                request_digest=hashlib.sha256(b"batch").digest(),
                name="Registration test batch",
                quantity=1,
                plan_revision_uuid=str(PLAN_UUID),
                entitlements_schema_version=1,
                entitlements_json=ENTITLEMENTS,
                entitlements_digest=snapshot.digest_sha256,
                service_duration_seconds=SERVICE_SECONDS,
                default_redeem_before=NOW + timedelta(days=7),
                created_by_platform_admin_id=str(ADMIN_UUID),
                created_at=NOW - timedelta(days=1),
                plaintext_exported_at=NOW - timedelta(days=1),
            )
        )
        session.flush()
        session.add(
            RedemptionCode(
                id=str(CODE_UUID),
                crypto_context_uuid=(
                    "30000000-0000-4000-8000-000000000098"
                ),
                batch_id=str(BATCH_UUID),
                code_prefix="ABCD",
                lookup_hash=LOOKUP_HASH,
                code_ciphertext=b"x" * 42,
                code_nonce=b"n" * 12,
                secret_revision=1,
                root_key_version=1,
                crypto_version=1,
                aad_version=1,
                status="active",
                plan_revision_uuid=str(PLAN_UUID),
                entitlements_schema_version=1,
                entitlements_json=ENTITLEMENTS,
                entitlements_digest=snapshot.digest_sha256,
                service_duration_seconds=SERVICE_SECONDS,
                redeem_before=NOW + timedelta(days=7),
                created_under_recovery_run_uuid=str(RUN_UUID),
                row_version=1,
                created_at=NOW - timedelta(days=1),
                updated_at=NOW - timedelta(days=1),
            )
        )
    return value


def _authority(**overrides) -> AuthorityReader:
    values = {
        "current_recovery_run_uuid": RUN_UUID,
        "recovery_run_completed": True,
        "external_marker_matches": True,
        "marker_generation": 1,
        "released_hold_uuid": HOLD_UUID,
        "released_hold_revision": 1,
        "released_hold_ready": True,
    }
    values.update(overrides)
    return AuthorityReader(RegistrationAuthorityFacts(**values))


def _service(
    reader: AuthorityReader | None = None,
    *,
    provisioning_reader: ProvisioningReader | None = None,
):
    authority = reader or _authority()
    return (
        RegistrationPersistenceService(
            authority_current_read=authority,
            provisioning_current_read=provisioning_reader,
            database_clock=lambda _session: NOW,
        ),
        authority,
    )


def _service_with_clock(*moments: datetime):
    authority = _authority()
    remaining = iter(moments)
    observed: list[datetime] = []

    def clock(_session):
        value = next(remaining)
        observed.append(value)
        return value

    return (
        RegistrationPersistenceService(
            authority_current_read=authority,
            database_clock=clock,
        ),
        observed,
    )


def _integrated_service():
    recovery = RecoveryAuthorityService(database_clock=lambda _session: NOW)
    adapter = RecoveryRegistrationAuthorityAdapter(
        recovery_authority=recovery,
        expected_deployment_marker_fingerprint=(
            DEPLOYMENT_MARKER_FINGERPRINT
        ),
    )
    return RegistrationPersistenceService(
        authority_current_read=adapter,
        released_hold_baseline_write=adapter.create_released_baseline,
        database_clock=lambda _session: NOW,
    )


def _reservation_digest(**overrides) -> bytes:
    values = {
        "user_uuid": str(USER_UUID),
        "code_lookup_hash": LOOKUP_HASH,
        "attempt_uuid": str(ATTEMPT_UUID),
        "provisional_tenant_uuid": str(TENANT_UUID),
        "provisional_database_uuid": str(DATABASE_UUID),
        "requested_tenant_name": TENANT_NAME,
        "idempotency_key": RESERVATION_KEY,
        "expected_code_row_version": 1,
        "current_recovery_run_uuid": str(RUN_UUID),
    }
    values.update(overrides)
    return reservation_action_digest(**values)


def _add_consumed_challenge(
    database,
    *,
    challenge_uuid=CHALLENGE_UUID,
    action_digest=None,
    revision=REGISTRATION_RESERVATION_REVISION,
):
    digest = action_digest or _reservation_digest()
    with database.transaction() as session:
        session.add(
            SmsChallenge(
                id=str(challenge_uuid),
                purpose="register",
                canonical_phone_e164="+8613812345678",
                phone_normalization_version=1,
                phone_metadata_version="cn-mobile-v1",
                user_id=str(USER_UUID),
                tenant_id=None,
                actor_session_id=None,
                action_payload_digest_sha256=digest,
                authoritative_revision=revision,
                code_hmac_sha256=hashlib.sha256(b"otp").digest(),
                root_key_version=1,
                hmac_protocol_version=1,
                policy_version=1,
                max_wrong_attempts=5,
                trusted_source_bucket="test-source",
                delivery_state="sent",
                verification_state="consumed",
                wrong_attempt_count=0,
                row_version=2,
                created_at=NOW - timedelta(minutes=5),
                expires_at=NOW + timedelta(minutes=5),
                delivery_recorded_at=NOW - timedelta(minutes=5),
                consumed_at=NOW - timedelta(minutes=1),
            )
        )


def _retry_digest(**overrides) -> bytes:
    values = {
        "attempt_uuid": str(ATTEMPT_UUID),
        "user_uuid": str(USER_UUID),
        "canonical_phone": "+8613812345678",
        "phone_normalization_version": 1,
        "expected_attempt_row_version": 2,
        "expected_provisioning_generation": 1,
        "expected_code_row_version": 2,
        "lease_owner": LEASE_OWNER,
        "lease_token": LEASE_TOKEN,
        "lease_expires_at": LEASE_EXPIRES_AT,
        "current_recovery_run_uuid": str(RUN_UUID),
    }
    values.update(overrides)
    return retry_action_digest(**values)


def _reserve(database, *, service=None, **overrides):
    value = service or _service()[0]
    params = {
        "challenge_uuid": CHALLENGE_UUID,
        "user_uuid": USER_UUID,
        "code_lookup_hash": LOOKUP_HASH,
        "attempt_uuid": ATTEMPT_UUID,
        "provisional_tenant_uuid": TENANT_UUID,
        "provisional_database_uuid": DATABASE_UUID,
        "requested_tenant_name": TENANT_NAME,
        "idempotency_key": RESERVATION_KEY,
        "expected_code_row_version": 1,
        "current_recovery_run_uuid": RUN_UUID,
    }
    params.update(overrides)
    with database.transaction() as session:
        return value.reserve_after_verified_otp(session, **params)


def _make_route(database):
    with database.transaction() as session:
        session.add(
            TenantDatabase(
                tenant_id=str(TENANT_UUID),
                database_uuid=str(DATABASE_UUID),
                database_instance_key="test-instance",
                database_name="tenant_acme",
                status="provisional",
                schema_version="tenant-v1",
                dml_username="tenant_acme_dml_g1",
                dml_credential_generation=1,
                dml_root_key_version=1,
                dml_derivation_version=1,
                route_version=1,
                dml_desired_login_state="active",
                dml_observed_login_state="active",
                dml_login_state_version=1,
                platform_read_username="tenant_acme_read_g1",
                platform_read_credential_generation=1,
                platform_read_root_key_version=1,
                platform_read_derivation_version=1,
                platform_read_route_version=1,
                row_version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()
        session.add(
            DatabaseIdentityControlRecord(
                tenant_id=str(TENANT_UUID),
                database_uuid=str(DATABASE_UUID),
                expected_schema_generation=1,
                observed_schema_generation=1,
                identity_created_at=NOW,
                last_verified_at=NOW,
                created_at=NOW,
            )
        )


def _make_ready(database):
    _make_route(database)
    with database.transaction() as session:
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        assert attempt is not None
        attempt.status = "ready"
        attempt.lease_owner = LEASE_OWNER
        attempt.lease_token = LEASE_TOKEN
        attempt.lease_expires_at = LEASE_EXPIRES_AT
        attempt.row_version = 2
        attempt.updated_at = NOW
        session.add(
            TenantRegistrationProvisioningProof(
                id=str(READY_PROOF_UUID),
                attempt_uuid=str(ATTEMPT_UUID),
                user_uuid=str(USER_UUID),
                tenant_uuid=str(TENANT_UUID),
                database_uuid=str(DATABASE_UUID),
                recovery_run_uuid=str(RUN_UUID),
                provisioning_execution_generation=1,
                expected_attempt_row_version=1,
                worker_lease_owner=LEASE_OWNER,
                worker_lease_token_digest=hashlib.sha256(
                    b"inventory-manager/registration-worker-lease-token/v1\x00"
                    + LEASE_TOKEN.encode("ascii")
                ).digest(),
                worker_lease_expires_at=LEASE_EXPIRES_AT,
                outcome="ready",
                safe_error_code=None,
                result_request_digest=READY_PROOF_REQUEST_DIGEST,
                schema_operation_claim_uuid=str(SCHEMA_CLAIM_UUID),
                schema_operation_owner_id="schema-worker-1",
                schema_operation_generation=1,
                schema_operation_fencing_token=1,
                schema_operation_row_version=2,
                schema_generation=1,
                schema_digest=SCHEMA_DIGEST,
                database_identity_digest=IDENTITY_DIGEST,
                route_version=1,
                initial_credential_generation=1,
                dml_login_state_version=1,
                default_warehouse_uuid=str(DEFAULT_WAREHOUSE_UUID),
                default_warehouse_digest=DEFAULT_WAREHOUSE_DIGEST,
                smoke_proof_digest=SMOKE_PROOF_DIGEST,
                advisory_lock_proof_digest=ADVISORY_LOCK_PROOF_DIGEST,
                proof_policy_version=1,
                recorded_at=NOW,
            )
        )


def _make_failed(database):
    with database.transaction() as session:
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        assert attempt is not None
        attempt.status = "failed"
        attempt.row_version = 2
        attempt.last_safe_error_code = "provisioning_failed"
        attempt.updated_at = NOW


def _add_pending_invitations(database):
    tenant_ids = (
        UUID("30000000-0000-4000-8000-000000000060"),
        UUID("30000000-0000-4000-8000-000000000061"),
    )
    invitation_ids = (
        UUID("30000000-0000-4000-8000-000000000062"),
        UUID("30000000-0000-4000-8000-000000000063"),
    )
    with database.transaction() as session:
        for index, tenant_id in enumerate(tenant_ids):
            session.add(
                Tenant(
                    id=str(tenant_id),
                    name=f"Inviting tenant {index}",
                    slug=f"inviting-tenant-{index}",
                    public_identity_published_at=NOW,
                    status="active",
                    access_version=1,
                    row_version=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        session.flush()
        for index, (tenant_id, invitation_id) in enumerate(
            zip(tenant_ids, invitation_ids, strict=True)
        ):
            session.add(
                TenantInvitation(
                    id=str(invitation_id),
                    tenant_id=str(tenant_id),
                    user_id=str(USER_UUID),
                    phone_e164="+8613812345678",
                    phone_normalization_version=1,
                    role_key="operator",
                    token_hash=hashlib.sha256(
                        f"invitation-{index}".encode("ascii")
                    ).digest(),
                    token_generation=1,
                    status="pending",
                    expires_at=NOW + timedelta(days=1),
                    row_version=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
    return invitation_ids


def _retry(database, *, service=None, **overrides):
    value = service or _service()[0]
    params = {
        "challenge_uuid": RETRY_CHALLENGE_UUID,
        "attempt_uuid": ATTEMPT_UUID,
        "expected_attempt_row_version": 2,
        "expected_provisioning_generation": 1,
        "expected_code_row_version": 2,
        "lease_owner": LEASE_OWNER,
        "lease_token": LEASE_TOKEN,
        "lease_expires_at": LEASE_EXPIRES_AT,
        "current_recovery_run_uuid": RUN_UUID,
    }
    params.update(overrides)
    with database.transaction() as session:
        return value.retry_failed_after_verified_otp(session, **params)


def _provisioned(**overrides):
    values = {
        "tenant_uuid": TENANT_UUID,
        "database_uuid": DATABASE_UUID,
        "provisioning_generation": 1,
        "lease_owner": LEASE_OWNER,
        "lease_token": LEASE_TOKEN,
        "schema_generation": 1,
        "schema_digest": SCHEMA_DIGEST,
        "database_identity_digest": IDENTITY_DIGEST,
        "route_version": 1,
        "initial_credential_generation": 1,
        "dml_login_state_version": 1,
        "default_warehouse_uuid": DEFAULT_WAREHOUSE_UUID,
        "default_warehouse_digest": DEFAULT_WAREHOUSE_DIGEST,
        "smoke_proof_digest": SMOKE_PROOF_DIGEST,
        "advisory_lock_proof_digest": ADVISORY_LOCK_PROOF_DIGEST,
        "backup_ddl_lease_held": True,
        "database_advisory_lock_held": True,
        "smoke_passed": True,
        "business_route_unpublished": True,
    }
    values.update(overrides)
    return ProvisionedRegistrationFacts(**values)


def _schema_fence(**overrides):
    values = {
        "claim_uuid": SCHEMA_CLAIM_UUID,
        "owner_id": "schema-worker-1",
        "generation": 1,
        "fencing_token": 1,
        "row_version": 2,
    }
    values.update(overrides)
    return RegistrationSchemaOperationFence(**values)


@dataclass
class FinalFenceProbe:
    calls: list[object]
    fail: bool = False

    def __call__(self, *, control_transaction):
        assert control_transaction.in_transaction()
        self.calls.append(control_transaction)
        if self.fail:
            raise RuntimeError("simulated final fence loss")


def _publication_request(*, attempt_row_version=2, code_row_version=2):
    return RegistrationFinalPublicationRequest(
        attempt_uuid=ATTEMPT_UUID,
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        current_recovery_run_uuid=RUN_UUID,
        provisioning_generation=1,
        expected_attempt_row_version=attempt_row_version,
        expected_code_row_version=code_row_version,
        ready_proof_uuid=READY_PROOF_UUID,
        ready_proof_request_digest=READY_PROOF_REQUEST_DIGEST,
        lock_idempotency_key="registration-final-lock-v1",
        plan=_plan(),
    )


def _publication_authority(
    request,
    *,
    committed=False,
):
    commit_uuid = COMMIT_UUID if committed else None
    return RegistrationFinalPublicationAuthority(
        state=(
            ReadyPublicationState.COMMITTED
            if committed
            else ReadyPublicationState.PROVISIONAL_READY
        ),
        attempt_uuid=ATTEMPT_UUID,
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        current_recovery_run_uuid=RUN_UUID,
        provisioning_generation=1,
        attempt_row_version=request.expected_attempt_row_version,
        code_row_version=request.expected_code_row_version,
        tenant_status="active" if committed else "provisioning",
        attempt_status="active" if committed else "ready",
        endpoint=ProvisionalTenantEndpoint(
            tenant_uuid=TENANT_UUID,
            database_uuid=DATABASE_UUID,
            endpoint_identity_digest=hashlib.sha256(
                b"registration-publication-endpoint"
            ).digest(),
            route_version=1,
            initial_credential_generation=1,
            dml_login_state_version=1,
            status="ready" if committed else "provisional",
            activated_by_registration_commit_uuid=commit_uuid,
        ),
        ready_proof=PersistedTenantReadyProof(
            proof_uuid=READY_PROOF_UUID,
            request_digest=READY_PROOF_REQUEST_DIGEST,
            tenant_uuid=TENANT_UUID,
            database_uuid=DATABASE_UUID,
            provisioning_generation=1,
            schema_generation=1,
            schema_digest=SCHEMA_DIGEST,
            database_identity_digest=IDENTITY_DIGEST,
            smoke_proof_digest=SMOKE_PROOF_DIGEST,
            advisory_lock_proof_digest=ADVISORY_LOCK_PROOF_DIGEST,
            recorded_schema_fence=_schema_fence(),
            proof_policy_version=1,
        ),
        provisioned=_provisioned(),
        existing_registration_commit_uuid=commit_uuid,
    )


def _publication_fences(request):
    fence = GlobalSchemaPublicationFenceHandle(
        schema_operation_fence=_schema_fence(),
        purpose="provisioning",
        request_binding_digest=registration_publication_lock_binding_digest(
            request
        ),
    )
    advisory = DatabaseAdvisoryLockHandle(
        database_uuid=DATABASE_UUID,
        owner_id="registration-final-worker-1",
        lock_key_sha256=hashlib.sha256(b"registration-db-lock").digest(),
        acquisition_proof_digest=hashlib.sha256(
            b"registration-db-lock-proof"
        ).digest(),
        schema_claim_uuid=fence.claim_uuid,
        schema_fencing_token=fence.fencing_token,
    )
    return fence, advisory


def _publish_with_adapter(
    database,
    *,
    persistence,
    request,
    authority,
    callback,
):
    fence, advisory = _publication_fences(request)
    return RegistrationPersistenceAtomicFinalCommitPort(
        control_database=database,
        persistence=persistence,
    ).finalize(
        request=request,
        authority=authority,
        schema_fence=fence,
        advisory_lock=advisory,
        fence_current_read=callback,
    )


def _read_publication_replay(database, *, persistence, request):
    return RegistrationPersistenceCommittedPublicationCurrentRead(
        control_database=database,
        persistence=persistence,
    )(request=request)


def _hold_schema_lease(database, *, expires_at=LEASE_EXPIRES_AT):
    with database.transaction() as session:
        row = session.get(
            PlatformSchemaOperationLease,
            "fleet_schema_operation",
        )
        assert row is not None
        row.state = "held"
        row.generation = 1
        row.fencing_token = 1
        row.row_version = 2
        row.observed_at = NOW
        row.owner_id = "schema-worker-1"
        row.claim_id = str(SCHEMA_CLAIM_UUID)
        row.purpose = "provisioning"
        row.acquired_at = NOW
        row.expires_at = expires_at
        row.last_claim_id = str(SCHEMA_CLAIM_UUID)
        row.last_effect = "claimed"
        row.last_request_digest = hashlib.sha256(
            b"schema-claim"
        ).digest()


def _release_schema_lease(database):
    with database.transaction() as session:
        row = session.get(
            PlatformSchemaOperationLease,
            "fleet_schema_operation",
        )
        assert row is not None
        row.state = "available"
        row.row_version += 1
        row.observed_at = NOW + timedelta(seconds=1)
        row.owner_id = None
        row.claim_id = None
        row.purpose = None
        row.acquired_at = None
        row.expires_at = None
        row.last_effect = "released"
        row.last_request_digest = hashlib.sha256(
            b"schema-release"
        ).digest()


def _add_replacement_lineage(database):
    replacement_code_uuid = UUID("30000000-0000-4000-8000-000000000092")
    platform_session_uuid = UUID("30000000-0000-4000-8000-000000000093")
    snapshot = parse_core_entitlements(
        schema_version=1,
        entitlements=ENTITLEMENTS,
    )
    with database.transaction() as session:
        session.add(
            PlatformAdminTotpCredential(
                id="30000000-0000-4000-8000-000000000094",
                platform_admin_id=str(ADMIN_UUID),
                generation=1,
                secret_revision=1,
                status="confirmed",
                seed_nonce=b"n" * 12,
                seed_ciphertext=b"c" * 32,
                root_key_version=1,
                crypto_version=1,
                aad_version=1,
                totp_algorithm="SHA1",
                totp_digits=6,
                totp_period_seconds=30,
                last_accepted_time_step=1,
                row_version=1,
                created_at=NOW - timedelta(days=1),
                confirmed_at=NOW - timedelta(days=1),
            )
        )
        session.flush()
        session.add(
            PlatformAdminSession(
                id=str(platform_session_uuid),
                platform_admin_id=str(ADMIN_UUID),
                token_digest_sha256=hashlib.sha256(b"platform-token").digest(),
                csrf_digest_sha256=hashlib.sha256(b"platform-csrf").digest(),
                auth_version_at_issue=1,
                setup_version_at_issue=1,
                mfa_method="totp",
                mfa_verified_at=NOW - timedelta(minutes=1),
                totp_credential_id=(
                    "30000000-0000-4000-8000-000000000094"
                ),
                totp_time_step=1,
                policy_version=1,
                idle_timeout_seconds=900,
                created_at=NOW,
                last_seen_at=NOW,
                idle_expires_at=NOW + timedelta(minutes=15),
                absolute_expires_at=NOW + timedelta(hours=8),
            )
        )
        session.add(
            RedemptionCode(
                id=str(replacement_code_uuid),
                crypto_context_uuid=(
                    "30000000-0000-4000-8000-000000000095"
                ),
                batch_id=str(BATCH_UUID),
                code_prefix="WXYZ",
                lookup_hash=hashlib.sha256(b"replacement-code").digest(),
                code_ciphertext=b"y" * 42,
                code_nonce=b"m" * 12,
                secret_revision=1,
                root_key_version=1,
                crypto_version=1,
                aad_version=1,
                status="active",
                plan_revision_uuid=str(PLAN_UUID),
                entitlements_schema_version=1,
                entitlements_json=ENTITLEMENTS,
                entitlements_digest=snapshot.digest_sha256,
                service_duration_seconds=SERVICE_SECONDS,
                redeem_before=NOW + timedelta(days=7),
                created_under_recovery_run_uuid=str(RUN_UUID),
                row_version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()
        session.add(
            RedemptionCodeReplacement(
                id="30000000-0000-4000-8000-000000000096",
                source_code_uuid=str(CODE_UUID),
                replacement_code_uuid=str(replacement_code_uuid),
                source_attempt_uuid=str(ATTEMPT_UUID),
                source_user_uuid=str(USER_UUID),
                source_provisional_tenant_uuid=str(TENANT_UUID),
                source_provisional_database_uuid=str(DATABASE_UUID),
                chain_root_code_uuid=str(CODE_UUID),
                chain_generation=1,
                plan_revision_uuid=str(PLAN_UUID),
                entitlements_schema_version=1,
                entitlements_digest=snapshot.digest_sha256,
                service_duration_seconds=SERVICE_SECONDS,
                replacement_redeem_before=NOW + timedelta(days=7),
                fenced_provisioning_generation=1,
                platform_admin_uuid=str(ADMIN_UUID),
                platform_session_uuid=str(platform_session_uuid),
                reason_code="provisioning_replacement",
                idempotency_key="replacement-race-1",
                request_digest=hashlib.sha256(b"replacement").digest(),
                expected_source_code_row_version=2,
                expected_source_attempt_row_version=2,
                current_recovery_run_uuid=str(RUN_UUID),
                platform_audit_uuid=(
                    "30000000-0000-4000-8000-000000000097"
                ),
                created_at=NOW,
            )
        )


def _claim(database, *, service=None, **overrides):
    value = service or _service()[0]
    params = {
        "attempt_uuid": ATTEMPT_UUID,
        "expected_attempt_row_version": 1,
        "expected_provisioning_generation": 1,
        "expected_code_row_version": 2,
        "lease_owner": LEASE_OWNER,
        "lease_token": LEASE_TOKEN,
        "lease_expires_at": LEASE_EXPIRES_AT,
        "current_recovery_run_uuid": RUN_UUID,
    }
    params.update(overrides)
    with database.transaction() as session:
        return value.claim_provisioning_worker(session, **params)


def _record_ready(database, *, service, provisioned=None, **overrides):
    params = {
        "attempt_uuid": ATTEMPT_UUID,
        "expected_attempt_row_version": 2,
        "expected_provisioning_generation": 1,
        "expected_code_row_version": 2,
        "current_recovery_run_uuid": RUN_UUID,
        "schema_operation_fence": _schema_fence(),
        "provisioned": provisioned or _provisioned(),
    }
    params.update(overrides)
    with database.transaction() as session:
        return service.record_database_ready(session, **params)


def _record_failure(database, *, service=None, **overrides):
    value = service or _service()[0]
    params = {
        "attempt_uuid": ATTEMPT_UUID,
        "expected_attempt_row_version": 2,
        "expected_provisioning_generation": 1,
        "expected_code_row_version": 2,
        "lease_owner": LEASE_OWNER,
        "lease_token": LEASE_TOKEN,
        "safe_error_code": "tenant_schema_migration_failed",
        "current_recovery_run_uuid": RUN_UUID,
    }
    params.update(overrides)
    with database.transaction() as session:
        return value.record_provisioning_failure(session, **params)


def _plan(**overrides):
    values = {
        "registration_commit_uuid": COMMIT_UUID,
        "membership_uuid": MEMBERSHIP_UUID,
        "subscription_uuid": SUBSCRIPTION_UUID,
        "subscription_event_uuid": EVENT_UUID,
        "published_tenant_name": TENANT_NAME,
        "published_slug": TENANT_SLUG,
        "idempotency_key": FINAL_KEY,
    }
    values.update(overrides)
    return RegistrationFinalCommitPlan(**values)


def _finalize(database, *, service=None, plan=None, provisioned=None, **overrides):
    value = service or _service()[0]
    params = {
        "attempt_uuid": ATTEMPT_UUID,
        "expected_attempt_row_version": 2,
        "expected_code_row_version": 2,
        "current_recovery_run_uuid": RUN_UUID,
        "provisioned": provisioned or _provisioned(),
        "plan": plan or _plan(),
        "fence_current_read": _accept_final_fence,
    }
    params.update(overrides)
    with database.transaction() as session:
        return value.finalize_registration(session, **params)


def _accept_final_fence(*, control_transaction):
    assert control_transaction.in_transaction()


def test_provisioning_claim_initial_replay_and_active_lease_rejection(database):
    _add_consumed_challenge(database)
    _reserve(database)
    service, _authority_reader = _service()

    created = _claim(database, service=service)
    replay = _claim(database, service=service)

    assert created.created is True
    assert created.status == "provisioning"
    assert created.row_version == 2
    assert replay.created is False
    assert replay.row_version == 2
    with pytest.raises(RegistrationFenceError):
        _claim(
            database,
            service=service,
            expected_attempt_row_version=2,
            lease_owner="worker-2",
            lease_token="lease-token-2",
        )


def test_registration_mysql_clock_uses_utc_microseconds_and_preserves_fsp():
    observed = datetime(
        2026,
        8,
        22,
        12,
        0,
        0,
        654321,
        tzinfo=timezone.utc,
    )

    class Dialect:
        name = "mysql"

    class Bind:
        dialect = Dialect()

    class FakeSession:
        statement = None

        def get_bind(self):
            return Bind()

        def scalar(self, statement):
            self.statement = statement
            return observed

    session = FakeSession()
    result = registration_persistence._read_database_utc_now(session)

    assert str(session.statement) == "SELECT UTC_TIMESTAMP(6)"
    assert result == observed
    assert result.microsecond == 654321


def test_provisioning_expired_takeover_is_same_generation_and_aba_safe(database):
    _add_consumed_challenge(database)
    _reserve(database)
    _claim(database)
    with database.transaction() as session:
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        assert attempt is not None
        attempt.lease_expires_at = NOW - timedelta(microseconds=1)

    takeover = _claim(
        database,
        expected_attempt_row_version=2,
        lease_owner="worker-2",
        lease_token="lease-token-2",
    )
    replay = _claim(
        database,
        expected_attempt_row_version=2,
        lease_owner="worker-2",
        lease_token="lease-token-2",
    )

    assert takeover.created is True
    assert takeover.provisioning_generation == 1
    assert takeover.row_version == 3
    assert replay.created is False
    with pytest.raises(RegistrationFenceError):
        _claim(database)


def test_provisioning_claim_uses_post_lock_database_time(database):
    _add_consumed_challenge(database)
    _reserve(database)
    moments = iter((NOW, LEASE_EXPIRES_AT + timedelta(microseconds=1)))
    service = RegistrationPersistenceService(
        authority_current_read=_authority(),
        database_clock=lambda _session: next(moments),
    )

    with pytest.raises(RegistrationFenceError):
        _claim(database, service=service)

    with database.transaction() as session:
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        assert attempt is not None and attempt.status == "reserved"


def test_database_ready_persists_proof_and_replays_after_schema_release(
    database,
):
    _add_consumed_challenge(database)
    _reserve(database)
    _claim(database)
    _make_route(database)
    _hold_schema_lease(database)
    reader = ProvisioningReader(_provisioned())
    service, _authority_reader = _service(provisioning_reader=reader)

    created = _record_ready(database, service=service)
    _release_schema_lease(database)
    replay = _record_ready(database, service=service)

    assert created.created is True
    assert replay.created is False
    assert replay.proof_uuid == created.proof_uuid
    assert reader.calls == 1
    with database.transaction() as session:
        proof = session.get(
            TenantRegistrationProvisioningProof,
            str(created.proof_uuid),
        )
        assert proof is not None and proof.outcome == "ready"
        assert LEASE_TOKEN not in repr(proof.worker_lease_token_digest)
        assert not hasattr(proof, "worker_lease_token")


def test_persisted_database_ready_proof_is_required_and_authorizes_finalize(
    database,
):
    _add_consumed_challenge(database)
    _reserve(database)
    _claim(database)
    _make_route(database)
    _hold_schema_lease(database)
    reader = ProvisioningReader(_provisioned())
    service, _authority_reader = _service(provisioning_reader=reader)
    _record_ready(database, service=service)

    result = _finalize(
        database,
        service=service,
        expected_attempt_row_version=3,
    )

    assert result.created is True
    assert result.status == "active"
    with database.transaction() as session:
        commit = session.get(TenantRegistrationCommit, str(COMMIT_UUID))
        assert commit is not None
        assert commit.schema_generation == 1
        assert commit.database_identity_digest == IDENTITY_DIGEST


def test_database_ready_rejects_schema_lease_expiry_crossing_callback(database):
    _add_consumed_challenge(database)
    _reserve(database)
    _claim(database)
    _make_route(database)
    schema_expiry = NOW + timedelta(seconds=1)
    _hold_schema_lease(database, expires_at=schema_expiry)
    reader = ProvisioningReader(_provisioned())
    moments = iter(
        (
            NOW,
            NOW,
            schema_expiry + timedelta(microseconds=1),
        )
    )
    service = RegistrationPersistenceService(
        authority_current_read=_authority(),
        provisioning_current_read=reader,
        database_clock=lambda _session: next(moments),
    )

    with pytest.raises(RegistrationFenceError):
        _record_ready(database, service=service)

    with database.transaction() as session:
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        assert attempt is not None and attempt.status == "provisioning"
        assert session.scalar(
            sa.select(
                sa.func.count(TenantRegistrationProvisioningProof.id)
            )
        ) == 0


def test_expired_ready_takeover_requires_new_proof_for_new_worker(database):
    _add_consumed_challenge(database)
    _reserve(database)
    _claim(database)
    _make_route(database)
    _hold_schema_lease(database)
    first_reader = ProvisioningReader(_provisioned())
    first_service, _ = _service(provisioning_reader=first_reader)
    first = _record_ready(database, service=first_service)
    with database.transaction() as session:
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        assert attempt is not None
        attempt.lease_expires_at = NOW - timedelta(microseconds=1)

    takeover = _claim(
        database,
        expected_attempt_row_version=3,
        lease_owner="worker-2",
        lease_token="lease-token-2",
    )
    second_facts = _provisioned(
        lease_owner="worker-2",
        lease_token="lease-token-2",
    )
    second_reader = ProvisioningReader(second_facts)
    second_service, _ = _service(provisioning_reader=second_reader)
    second = _record_ready(
        database,
        service=second_service,
        expected_attempt_row_version=4,
        provisioned=second_facts,
    )

    assert takeover.status == "provisioning"
    assert takeover.provisioning_generation == 1
    assert second.proof_uuid != first.proof_uuid
    with database.transaction() as session:
        proofs = tuple(
            session.scalars(
                sa.select(TenantRegistrationProvisioningProof)
                .order_by(TenantRegistrationProvisioningProof.id)
            )
        )
        assert len(proofs) == 2


def test_provisioning_failure_replays_and_keeps_code_reserved(database):
    _add_consumed_challenge(database)
    _reserve(database)
    _claim(database)

    created = _record_failure(database)
    replay = _record_failure(database)

    assert created.created is True
    assert replay.created is False
    assert replay.proof_uuid == created.proof_uuid
    with database.transaction() as session:
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        code = session.get(RedemptionCode, str(CODE_UUID))
        assert attempt is not None and attempt.status == "failed"
        assert attempt.lease_owner is None and attempt.lease_token is None
        assert code is not None and code.status == "reserved"
        assert code.reserved_registration_attempt_uuid == str(ATTEMPT_UUID)


def test_finalize_rejects_ready_state_without_persisted_proof(database):
    _add_consumed_challenge(database)
    _reserve(database)
    _make_route(database)
    with database.transaction() as session:
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        assert attempt is not None
        attempt.status = "ready"
        attempt.lease_owner = LEASE_OWNER
        attempt.lease_token = LEASE_TOKEN
        attempt.lease_expires_at = LEASE_EXPIRES_AT
        attempt.row_version = 2

    with pytest.raises(RegistrationFenceError):
        _finalize(database)


def test_reserve_after_consumed_otp_and_replay(database):
    _add_consumed_challenge(database)
    service, authority = _service()

    created = _reserve(database, service=service)
    replayed = _reserve(database, service=service)

    assert created.created is True
    assert replayed.created is False
    assert replayed == created.__class__(
        attempt_uuid=created.attempt_uuid,
        user_uuid=created.user_uuid,
        code_uuid=created.code_uuid,
        tenant_uuid=created.tenant_uuid,
        database_uuid=created.database_uuid,
        status=created.status,
        provisioning_generation=created.provisioning_generation,
        row_version=created.row_version,
        created=False,
    )
    assert authority.calls == 2
    with database.transaction() as session:
        code = session.get(RedemptionCode, str(CODE_UUID))
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        tenant = session.get(Tenant, str(TENANT_UUID))
        assert code is not None and attempt is not None and tenant is not None
        assert code.status == "reserved"
        assert code.reserved_user_uuid == str(USER_UUID)
        assert code.reserved_registration_attempt_uuid == str(ATTEMPT_UUID)
        assert code.row_version == 2
        assert attempt.status == "reserved"
        assert tenant.status == "provisioning"


def test_reservation_uses_database_time_after_all_authoritative_locks(database):
    _add_consumed_challenge(database)
    with database.transaction() as session:
        code = session.get(RedemptionCode, str(CODE_UUID))
        assert code is not None
        code.redeem_before = NOW + timedelta(seconds=1)
    service, observed = _service_with_clock(
        NOW,
        NOW + timedelta(seconds=2),
    )

    with pytest.raises(RegistrationCodeError):
        _reserve(database, service=service)

    assert observed == [NOW, NOW + timedelta(seconds=2)]
    with database.transaction() as session:
        assert session.get(Tenant, str(TENANT_UUID)) is None
        code = session.get(RedemptionCode, str(CODE_UUID))
        assert code is not None and code.status == "active"


def test_reserved_code_cannot_be_rebound_by_a_different_request(database):
    _add_consumed_challenge(database)
    service, _ = _service()
    _reserve(database, service=service)
    other_challenge = UUID("30000000-0000-4000-8000-000000000080")
    other_attempt = UUID("30000000-0000-4000-8000-000000000081")
    other_tenant = UUID("30000000-0000-4000-8000-000000000082")
    other_database = UUID("30000000-0000-4000-8000-000000000083")
    digest = _reservation_digest(
        attempt_uuid=str(other_attempt),
        provisional_tenant_uuid=str(other_tenant),
        provisional_database_uuid=str(other_database),
        idempotency_key="registration-reserve-other",
        expected_code_row_version=2,
    )
    _add_consumed_challenge(
        database,
        challenge_uuid=other_challenge,
        action_digest=digest,
    )

    with pytest.raises(RegistrationConflictError):
        _reserve(
            database,
            service=service,
            challenge_uuid=other_challenge,
            attempt_uuid=other_attempt,
            provisional_tenant_uuid=other_tenant,
            provisional_database_uuid=other_database,
            idempotency_key="registration-reserve-other",
            expected_code_row_version=2,
        )

    with database.transaction() as session:
        assert session.get(TenantRegistrationAttempt, str(other_attempt)) is None
        code = session.get(RedemptionCode, str(CODE_UUID))
        assert code is not None
        assert code.reserved_registration_attempt_uuid == str(ATTEMPT_UUID)


def test_final_commit_persists_all_anchors_and_response_loss_replays(database):
    _add_consumed_challenge(database)
    _reserve(database)
    _make_ready(database)
    service, authority = _service()

    created = _finalize(database, service=service)
    replayed = _finalize(database, service=service)

    assert created.created is True
    assert created.status == "active"
    assert replayed.created is False
    assert replayed.registration_commit_uuid == COMMIT_UUID
    assert replayed.membership_uuid == MEMBERSHIP_UUID
    assert replayed.subscription_uuid == SUBSCRIPTION_UUID
    assert replayed.subscription_event_uuid == EVENT_UUID
    assert authority.calls == 2

    with database.transaction() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        code = session.get(RedemptionCode, str(CODE_UUID))
        route = session.get(TenantDatabase, str(TENANT_UUID))
        membership = session.get(TenantMembership, str(MEMBERSHIP_UUID))
        subscription = session.get(Subscription, str(SUBSCRIPTION_UUID))
        event = session.get(SubscriptionEvent, str(EVENT_UUID))
        commit = session.get(TenantRegistrationCommit, str(COMMIT_UUID))
        assert tenant is not None and tenant.status == "active"
        assert tenant.name == TENANT_NAME and tenant.slug == TENANT_SLUG
        assert attempt is not None and attempt.status == "active"
        assert attempt.registration_commit_uuid == str(COMMIT_UUID)
        assert attempt.lease_owner is None and attempt.row_version == 4
        assert code is not None and code.status == "redeemed"
        assert code.registration_commit_uuid == str(COMMIT_UUID)
        assert code.row_version == 3
        assert route is not None and route.status == "ready"
        assert route.activated_by_registration_commit_uuid == str(COMMIT_UUID)
        assert route.activation_route_version == 1
        assert route.activation_credential_generation == 1
        assert route.row_version == 2
        assert membership is not None and membership.role_key == "admin"
        assert subscription is not None
        assert subscription.expires_at.replace(tzinfo=timezone.utc) == (
            NOW + timedelta(seconds=SERVICE_SECONDS)
        )
        assert event is not None and event.source_uuid == str(COMMIT_UUID)
        assert commit is not None
        assert commit.database_identity_digest == IDENTITY_DIGEST
        assert commit.released_hold_uuid == str(HOLD_UUID)


def test_publication_replay_current_read_distinguishes_unpublished_and_exact(
    database,
):
    _add_consumed_challenge(database)
    persistence, _ = _service()
    _reserve(database, service=persistence)
    _make_ready(database)
    request = _publication_request()

    assert (
        _read_publication_replay(
            database,
            persistence=persistence,
            request=request,
        )
        is None
    )

    _finalize(database, service=persistence)
    _hold_schema_lease(database)
    _release_schema_lease(database)
    replayed = _read_publication_replay(
        database,
        persistence=persistence,
        request=request,
    )

    assert replayed is not None
    assert replayed.created is False
    assert replayed.registration_commit_uuid == COMMIT_UUID
    assert replayed.membership_uuid == MEMBERSHIP_UUID
    assert replayed.subscription_uuid == SUBSCRIPTION_UUID
    assert replayed.subscription_event_uuid == EVENT_UUID


@pytest.mark.parametrize(
    "changed_request",
    (
        replace(_publication_request(), expected_attempt_row_version=3),
        replace(_publication_request(), expected_code_row_version=3),
        replace(
            _publication_request(),
            ready_proof_request_digest=hashlib.sha256(
                b"changed-ready-proof"
            ).digest(),
        ),
        replace(
            _publication_request(),
            plan=replace(
                _plan(),
                published_slug="changed-replay",
            ),
        ),
        replace(
            _publication_request(),
            plan=replace(
                _plan(),
                idempotency_key="changed-finalization-key",
            ),
        ),
    ),
)
def test_publication_replay_current_read_rejects_any_input_drift(
    database,
    changed_request,
):
    _add_consumed_challenge(database)
    persistence, _ = _service()
    _reserve(database, service=persistence)
    _make_ready(database)
    _finalize(database, service=persistence)

    with pytest.raises(RegistrationFinalPublicationInvariantError):
        _read_publication_replay(
            database,
            persistence=persistence,
            request=changed_request,
        )


def test_publication_replay_accepts_legally_disabled_historical_membership(
    database,
):
    _add_consumed_challenge(database)
    persistence, _ = _service()
    _reserve(database, service=persistence)
    _make_ready(database)
    _finalize(database, service=persistence)
    with database.transaction() as session:
        membership = session.get(TenantMembership, str(MEMBERSHIP_UUID))
        assert membership is not None
        membership.status = "disabled"
        membership.row_version += 1

    replayed = _read_publication_replay(
        database,
        persistence=persistence,
        request=_publication_request(),
    )

    assert replayed is not None
    assert replayed.created is False
    assert replayed.registration_commit_uuid == COMMIT_UUID


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("worker_lease_token_digest", hashlib.sha256(b"tampered-token").digest()),
        ("schema_operation_fencing_token", 2),
        ("default_warehouse_digest", hashlib.sha256(b"tampered-warehouse").digest()),
        ("smoke_proof_digest", hashlib.sha256(b"tampered-smoke").digest()),
        ("advisory_lock_proof_digest", hashlib.sha256(b"tampered-lock").digest()),
    ),
)
def test_publication_replay_reauthenticates_persisted_ready_proof(
    database,
    field,
    value,
):
    _add_consumed_challenge(database)
    persistence, _ = _service()
    _reserve(database, service=persistence)
    _make_ready(database)
    with database.transaction() as session:
        proof = session.get(
            TenantRegistrationProvisioningProof,
            str(READY_PROOF_UUID),
        )
        assert proof is not None
        setattr(proof, field, value)

    with pytest.raises(RegistrationFinalPublicationInvariantError):
        _read_publication_replay(
            database,
            persistence=persistence,
            request=_publication_request(),
        )


def test_route_only_publication_footprint_is_not_treated_as_unpublished(
    database,
):
    _add_consumed_challenge(database)
    persistence, _ = _service()
    _reserve(database, service=persistence)
    _make_ready(database)
    with database.transaction() as session:
        route = session.get(TenantDatabase, str(TENANT_UUID))
        assert route is not None
        route.status = "ready"
        route.activated_by_registration_commit_uuid = str(COMMIT_UUID)
        route.activation_route_version = 1
        route.activation_credential_generation = 1

    with pytest.raises(RegistrationFinalPublicationInvariantError):
        _read_publication_replay(
            database,
            persistence=persistence,
            request=_publication_request(),
        )


def test_complete_replay_survives_legal_current_projection_advances(database):
    _add_consumed_challenge(database)
    persistence, _ = _service()
    _reserve(database, service=persistence)
    _make_ready(database)
    _finalize(database, service=persistence)
    next_plan_uuid = UUID("30000000-0000-4000-8000-000000000081")
    snapshot = parse_core_entitlements(schema_version=1, entitlements=ENTITLEMENTS)
    with database.transaction() as session:
        session.add(
            PlanRevision(
                id=str(next_plan_uuid),
                code="core",
                revision=2,
                name="Core renewal",
                entitlements_schema_version=1,
                entitlements_json=ENTITLEMENTS,
                entitlements_digest=snapshot.digest_sha256,
                active=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        tenant = session.get(Tenant, str(TENANT_UUID))
        membership = session.get(TenantMembership, str(MEMBERSHIP_UUID))
        subscription = session.get(Subscription, str(SUBSCRIPTION_UUID))
        assert tenant is not None and membership is not None
        assert subscription is not None
        tenant.status = "suspended"
        membership.status = "released"
        membership.released_at = NOW + timedelta(days=1)
        membership.row_version += 1
        subscription.plan_revision_uuid = str(next_plan_uuid)
        subscription.expires_at = subscription.expires_at + timedelta(days=30)
        subscription.row_version += 1

    replayed = _read_publication_replay(
        database,
        persistence=persistence,
        request=_publication_request(),
    )
    assert replayed is not None and replayed.registration_commit_uuid == COMMIT_UUID
    ordinary_replay = _finalize(database, service=persistence)
    assert ordinary_replay.created is False
    assert ordinary_replay.registration_commit_uuid == COMMIT_UUID


def test_complete_replay_rejects_replacement_lineage(database):
    _add_consumed_challenge(database)
    persistence, _ = _service()
    _reserve(database, service=persistence)
    _make_ready(database)
    _finalize(database, service=persistence)
    _add_replacement_lineage(database)

    with pytest.raises(RegistrationFinalPublicationInvariantError):
        _read_publication_replay(
            database,
            persistence=persistence,
            request=_publication_request(),
        )


def test_complete_replay_rejects_open_integrity_incident(database):
    _add_consumed_challenge(database)
    persistence, _ = _service()
    _reserve(database, service=persistence)
    _make_ready(database)
    _finalize(database, service=persistence)
    with database.transaction() as session:
        session.add(
            RegistrationIntegrityIncident(
                id="30000000-0000-4000-8000-000000000082",
                attempt_uuid=str(ATTEMPT_UUID),
                code_uuid=str(CODE_UUID),
                user_uuid=str(USER_UUID),
                provisional_tenant_uuid=str(TENANT_UUID),
                provisional_database_uuid=str(DATABASE_UUID),
                detected_attempt_status="active",
                detected_replacement_uuid=None,
                provisioning_generation=1,
                presence_bitmap=127,
                presence_digest=hashlib.sha256(b"open-incident").digest(),
                current_recovery_run_uuid=str(RUN_UUID),
                marker_generation=1,
                state="open",
                resolution_source=None,
                evidence_policy_version=1,
                safe_evidence_reference="registration-finalization/v1:test",
                decision_digest=None,
                platform_audit_uuid=None,
                row_version=1,
                detected_at=NOW,
                resolved_at=None,
            )
        )

    with pytest.raises(RegistrationFinalPublicationInvariantError):
        _read_publication_replay(
            database,
            persistence=persistence,
            request=_publication_request(),
        )


def test_atomic_publication_adapter_commits_and_exact_replay_rechecks_fence(
    database,
):
    _add_consumed_challenge(database)
    persistence, _ = _service()
    _reserve(database, service=persistence)
    _make_ready(database)
    first_request = _publication_request()
    first_fence = FinalFenceProbe(calls=[])

    created = _publish_with_adapter(
        database,
        persistence=persistence,
        request=first_request,
        authority=_publication_authority(first_request),
        callback=first_fence,
    )

    replay_request = _publication_request()
    replay_fence = FinalFenceProbe(calls=[])
    replayed = _publish_with_adapter(
        database,
        persistence=persistence,
        request=replay_request,
        authority=_publication_authority(replay_request, committed=True),
        callback=replay_fence,
    )

    assert created.created is True and created.status == "active"
    assert replayed.created is False and replayed.status == "active"
    assert replayed.registration_commit_uuid == COMMIT_UUID
    assert len(first_fence.calls) == 1
    assert len(replay_fence.calls) == 1
    with database.transaction() as session:
        assert session.scalar(
            sa.select(sa.func.count(TenantRegistrationCommit.id))
        ) == 1
        assert session.scalar(sa.select(sa.func.count(TenantMembership.id))) == 1
        assert session.scalar(sa.select(sa.func.count(Subscription.id))) == 1


@pytest.mark.parametrize(
    "precondition",
    ("happy_path", "security_block", "integrity_block"),
)
def test_final_fence_failure_precedes_every_finalization_mutation(
    database,
    precondition,
):
    _add_consumed_challenge(database)
    persistence, _ = _service()
    _reserve(database, service=persistence)
    _make_ready(database)
    with database.transaction() as session:
        if precondition == "security_block":
            user = session.get(User, str(USER_UUID))
            assert user is not None
            user.status = "disabled"
        elif precondition == "integrity_block":
            tenant = session.get(Tenant, str(TENANT_UUID))
            assert tenant is not None
            tenant.name = "preexisting-partial-anchor"

    request = _publication_request()
    fence = FinalFenceProbe(calls=[], fail=True)
    with pytest.raises(RegistrationFenceError):
        _publish_with_adapter(
            database,
            persistence=persistence,
            request=request,
            authority=_publication_authority(request),
            callback=fence,
        )

    assert len(fence.calls) == 1
    with database.transaction() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        route = session.get(TenantDatabase, str(TENANT_UUID))
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        code = session.get(RedemptionCode, str(CODE_UUID))
        assert tenant is not None and tenant.status == "provisioning"
        assert route is not None and route.status == "provisional"
        assert route.activated_by_registration_commit_uuid is None
        assert attempt is not None and attempt.status == "ready"
        assert attempt.registration_commit_uuid is None
        assert attempt.lease_owner == LEASE_OWNER
        assert code is not None and code.status == "reserved"
        assert session.scalar(
            sa.select(sa.func.count(TenantRegistrationCommit.id))
        ) == 0
        assert session.scalar(sa.select(sa.func.count(TenantMembership.id))) == 0
        assert session.scalar(sa.select(sa.func.count(Subscription.id))) == 0
        assert session.scalar(sa.select(sa.func.count(SubscriptionEvent.id))) == 0
        assert session.scalar(
            sa.select(sa.func.count(RegistrationIntegrityIncident.id))
        ) == 0


def test_atomic_adapter_rolls_back_if_persistence_omits_fence_callback(database):
    _add_consumed_challenge(database)
    base, _ = _service()
    _reserve(database, service=base)
    _make_ready(database)

    class OmittingFinalFencePersistence(RegistrationPersistenceService):
        def finalize_registration(
            self,
            session,
            *,
            attempt_uuid,
            expected_attempt_row_version,
            expected_code_row_version,
            current_recovery_run_uuid,
            provisioned,
            plan,
            fence_current_read,
        ):
            del (
                attempt_uuid,
                expected_attempt_row_version,
                expected_code_row_version,
                current_recovery_run_uuid,
                provisioned,
                fence_current_read,
            )
            tenant = session.get(Tenant, str(TENANT_UUID))
            route = session.get(TenantDatabase, str(TENANT_UUID))
            attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
            assert tenant is not None and route is not None and attempt is not None
            tenant.name = TENANT_NAME
            tenant.slug = TENANT_SLUG
            tenant.public_identity_published_at = NOW
            tenant.status = "active"
            tenant.row_version += 1
            route.status = "ready"
            route.activated_by_registration_commit_uuid = str(COMMIT_UUID)
            route.activation_route_version = 1
            route.activation_credential_generation = 1
            route.row_version += 1
            attempt.status = "active"
            attempt.registration_commit_uuid = str(COMMIT_UUID)
            attempt.lease_owner = None
            attempt.lease_token = None
            attempt.lease_expires_at = None
            attempt.row_version = 4
            attempt.completed_at = NOW
            session.flush()
            return RegistrationFinalizationResult(
                attempt_uuid=ATTEMPT_UUID,
                status="active",
                registration_commit_uuid=plan.registration_commit_uuid,
                membership_uuid=plan.membership_uuid,
                subscription_uuid=plan.subscription_uuid,
                subscription_event_uuid=plan.subscription_event_uuid,
                resulting_attempt_row_version=4,
                created=True,
            )

    omitting = OmittingFinalFencePersistence(
        authority_current_read=_authority(),
        database_clock=lambda _session: NOW,
    )
    request = _publication_request()
    callback = FinalFenceProbe(calls=[])
    with pytest.raises(RegistrationFinalPublicationInvariantError):
        _publish_with_adapter(
            database,
            persistence=omitting,
            request=request,
            authority=_publication_authority(request),
            callback=callback,
        )

    assert callback.calls == []
    with database.transaction() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        route = session.get(TenantDatabase, str(TENANT_UUID))
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        assert tenant is not None and tenant.status == "provisioning"
        assert tenant.name is None and tenant.slug is None
        assert route is not None and route.status == "provisional"
        assert route.activated_by_registration_commit_uuid is None
        assert attempt is not None and attempt.status == "ready"
        assert attempt.registration_commit_uuid is None
        assert session.scalar(
            sa.select(sa.func.count(TenantRegistrationCommit.id))
        ) == 0
        assert session.scalar(sa.select(sa.func.count(TenantMembership.id))) == 0
        assert session.scalar(sa.select(sa.func.count(Subscription.id))) == 0


def test_completed_registration_replay_uses_immutable_route_anchor_after_rotation(
    database,
):
    _add_consumed_challenge(database)
    _reserve(database)
    _make_ready(database)
    service, _ = _service()
    created = _finalize(database, service=service)
    assert created.created is True

    with database.transaction() as session:
        route = session.get(TenantDatabase, str(TENANT_UUID))
        assert route is not None
        route.dml_username = "tenant_acme_dml_g2"
        route.dml_credential_generation = 2
        route.route_version = 2
        route.dml_login_state_version = 2
        route.row_version += 1
        route.updated_at = NOW

    replayed = _finalize(database, service=service)

    assert replayed.created is False
    assert replayed.registration_commit_uuid == COMMIT_UUID
    with database.transaction() as session:
        route = session.get(TenantDatabase, str(TENANT_UUID))
        assert route is not None
        assert route.activation_route_version == 1
        assert route.activation_credential_generation == 1
        assert route.route_version == 2
        assert route.dml_credential_generation == 2


def test_final_commit_supersedes_all_pending_phone_invitations(database):
    invitation_ids = _add_pending_invitations(database)
    _add_consumed_challenge(database)
    _reserve(database)
    _make_ready(database)

    _finalize(database)

    with database.transaction() as session:
        invitations = tuple(
            session.get(TenantInvitation, str(invitation_id))
            for invitation_id in invitation_ids
        )
        assert all(invitation is not None for invitation in invitations)
        assert {invitation.status for invitation in invitations} == {
            "superseded"
        }
        assert all(invitation.user_id is None for invitation in invitations)
        assert all(
            invitation.terminal_reason_code == "registration_committed"
            for invitation in invitations
        )
        assert all(invitation.superseded_at is not None for invitation in invitations)


def test_completed_commit_rejects_changed_replay_plan(database):
    _add_consumed_challenge(database)
    _reserve(database)
    _make_ready(database)
    _finalize(database)
    changed = _plan(
        registration_commit_uuid=UUID(
            "30000000-0000-4000-8000-000000000070"
        ),
        membership_uuid=UUID("30000000-0000-4000-8000-000000000071"),
        subscription_uuid=UUID("30000000-0000-4000-8000-000000000072"),
        subscription_event_uuid=UUID(
            "30000000-0000-4000-8000-000000000073"
        ),
        published_slug="changed-replay",
        idempotency_key="registration-finalize-changed",
    )

    with pytest.raises(RegistrationConflictError):
        _finalize(database, plan=changed)

    with database.transaction() as session:
        commits = tuple(session.scalars(sa.select(TenantRegistrationCommit)))
        assert len(commits) == 1 and commits[0].id == str(COMMIT_UUID)


def test_completed_commit_rejects_changed_provisioning_evidence(database):
    _add_consumed_challenge(database)
    _reserve(database)
    _make_ready(database)
    _finalize(database)

    with pytest.raises(RegistrationConflictError):
        _finalize(
            database,
            provisioned=_provisioned(
                schema_digest=hashlib.sha256(b"different-schema").digest()
            ),
        )

    with database.transaction() as session:
        commits = tuple(session.scalars(sa.select(TenantRegistrationCommit)))
        assert len(commits) == 1 and commits[0].id == str(COMMIT_UUID)


def test_recovery_adapter_creates_released_hold_in_final_transaction(database):
    _add_consumed_challenge(database)
    service = _integrated_service()
    _reserve(database, service=service)
    _make_ready(database)

    created = _finalize(database, service=service)
    replayed = _finalize(database, service=service)

    assert created.created is True
    assert replayed.created is False
    with database.transaction() as session:
        holds = tuple(session.scalars(sa.select(TenantRecoveryHold)))
        assert len(holds) == 1
        hold = holds[0]
        persisted_hold_uuid = hold.id
        commit = session.get(TenantRegistrationCommit, str(COMMIT_UUID))
        assert hold.recovery_run_id == str(RUN_UUID)
        assert hold.tenant_id == str(TENANT_UUID)
        assert hold.database_uuid == str(DATABASE_UUID)
        assert hold.state == "released"
        assert hold.created_from_registration_commit_uuid == str(COMMIT_UUID)
        assert hold.initial_hold_revision == 1
        assert hold.hold_revision == 1
        assert hold.expected_dml_login_state_version == 1
        assert hold.dml_convergence_status == "active"
        assert commit is not None and commit.released_hold_uuid == hold.id
        assert commit.released_hold_revision_at_commit == hold.hold_revision

    with database.transaction() as session:
        hold = session.get(TenantRecoveryHold, persisted_hold_uuid)
        assert hold is not None
        hold.hold_revision = 2
        hold.row_version += 1
        hold.review_reason_code = "later_review"

    rotated_hold_replay = _finalize(database, service=service)
    assert rotated_hold_replay.created is False
    assert rotated_hold_replay.registration_commit_uuid == COMMIT_UUID


def test_recovery_baseline_and_final_anchors_rollback_with_caller(database):
    _add_consumed_challenge(database)
    service = _integrated_service()
    _reserve(database, service=service)
    _make_ready(database)

    class AbortOuterTransaction(RuntimeError):
        pass

    session = database.new_session()
    try:
        with pytest.raises(AbortOuterTransaction):
            with session.begin():
                result = service.finalize_registration(
                    session,
                    attempt_uuid=ATTEMPT_UUID,
                    expected_attempt_row_version=2,
                    expected_code_row_version=2,
                    current_recovery_run_uuid=RUN_UUID,
                    provisioned=_provisioned(),
                    plan=_plan(),
                    fence_current_read=_accept_final_fence,
                )
                assert result.created is True
                assert session.scalar(
                    sa.select(sa.func.count(TenantRecoveryHold.id))
                ) == 1
                raise AbortOuterTransaction()
    finally:
        session.close()

    with database.transaction() as session:
        assert session.scalar(
            sa.select(sa.func.count(TenantRecoveryHold.id))
        ) == 0
        assert session.scalar(
            sa.select(sa.func.count(TenantRegistrationCommit.id))
        ) == 0
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        code = session.get(RedemptionCode, str(CODE_UUID))
        tenant = session.get(Tenant, str(TENANT_UUID))
        assert attempt is not None and attempt.status == "ready"
        assert code is not None and code.status == "reserved"
        assert tenant is not None and tenant.status == "provisioning"


def test_original_user_can_retry_failed_attempt_and_replay_same_fence(database):
    _add_consumed_challenge(database)
    _reserve(database)
    _make_failed(database)
    _add_consumed_challenge(
        database,
        challenge_uuid=RETRY_CHALLENGE_UUID,
        action_digest=_retry_digest(),
        revision=REGISTRATION_RETRY_REVISION,
    )
    service, authority = _service()

    created = _retry(database, service=service)
    replayed = _retry(database, service=service)

    assert created.created is True
    assert created.status == "provisioning"
    assert created.provisioning_generation == 2
    assert created.row_version == 3
    assert replayed.created is False
    assert replayed.provisioning_generation == 2
    assert replayed.row_version == 3
    assert authority.calls == 2


def test_retry_uses_post_lock_time_and_rejects_newly_expired_lease(database):
    _add_consumed_challenge(database)
    _reserve(database)
    _make_failed(database)
    expires_at = NOW + timedelta(seconds=1)
    _add_consumed_challenge(
        database,
        challenge_uuid=RETRY_CHALLENGE_UUID,
        action_digest=_retry_digest(lease_expires_at=expires_at),
        revision=REGISTRATION_RETRY_REVISION,
    )
    service, observed = _service_with_clock(
        NOW,
        NOW + timedelta(seconds=2),
    )

    with pytest.raises(ValueError, match="must be in the future"):
        _retry(
            database,
            service=service,
            lease_expires_at=expires_at,
        )

    assert observed == [NOW, NOW + timedelta(seconds=2)]
    with database.transaction() as session:
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        assert attempt is not None and attempt.status == "failed"


def test_retry_microsecond_lease_expiry_round_trips_and_exactly_replays(
    database,
):
    _add_consumed_challenge(database)
    _reserve(database)
    _make_failed(database)
    expires_at = LEASE_EXPIRES_AT + timedelta(microseconds=123456)
    _add_consumed_challenge(
        database,
        challenge_uuid=RETRY_CHALLENGE_UUID,
        action_digest=_retry_digest(lease_expires_at=expires_at),
        revision=REGISTRATION_RETRY_REVISION,
    )
    service, _authority_reader = _service()

    created = _retry(
        database,
        service=service,
        lease_expires_at=expires_at,
    )
    replay = _retry(
        database,
        service=service,
        lease_expires_at=expires_at,
    )

    assert created.created is True
    assert replay.created is False
    with database.transaction() as session:
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        assert attempt is not None
        assert attempt.lease_expires_at.microsecond == 123456


def test_finalization_uses_post_lock_time_for_worker_lease(database):
    _add_consumed_challenge(database)
    _reserve(database)
    _make_ready(database)
    service, observed = _service_with_clock(
        NOW,
        LEASE_EXPIRES_AT + timedelta(seconds=1),
    )

    with pytest.raises(RegistrationFenceError):
        _finalize(database, service=service)

    assert observed == [NOW, LEASE_EXPIRES_AT + timedelta(seconds=1)]
    with database.transaction() as session:
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        assert attempt is not None and attempt.status == "ready"
        assert session.scalar(
            sa.select(sa.func.count(TenantRegistrationCommit.id))
        ) == 0


def test_retry_rejects_an_otp_consumed_for_a_different_user(database):
    _add_consumed_challenge(database)
    _reserve(database)
    _make_failed(database)
    other_user_uuid = UUID("30000000-0000-4000-8000-000000000090")
    with database.transaction() as session:
        session.add(
            User(
                id=str(other_user_uuid),
                phone_e164="+8613912345678",
                phone_normalization_version=1,
                phone_metadata_version="cn-mobile-v1",
                phone_verified_at=NOW,
                status="active",
            )
        )
    # The digest is for the immutable original user, but the challenge itself
    # belongs to another identity.  Possessing that OTP cannot advance the
    # original user's reservation.
    with database.transaction() as session:
        session.add(
            SmsChallenge(
                id=str(RETRY_CHALLENGE_UUID),
                purpose="register",
                canonical_phone_e164="+8613912345678",
                phone_normalization_version=1,
                phone_metadata_version="cn-mobile-v1",
                user_id=str(other_user_uuid),
                action_payload_digest_sha256=_retry_digest(),
                authoritative_revision=REGISTRATION_RETRY_REVISION,
                code_hmac_sha256=hashlib.sha256(b"other-otp").digest(),
                root_key_version=1,
                hmac_protocol_version=1,
                policy_version=1,
                max_wrong_attempts=5,
                trusted_source_bucket="test-source",
                delivery_state="sent",
                verification_state="consumed",
                wrong_attempt_count=0,
                row_version=2,
                created_at=NOW - timedelta(minutes=5),
                expires_at=NOW + timedelta(minutes=5),
                delivery_recorded_at=NOW - timedelta(minutes=5),
                consumed_at=NOW - timedelta(minutes=1),
            )
        )

    with pytest.raises(RegistrationOtpError):
        _retry(database)
    with database.transaction() as session:
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        assert attempt is not None and attempt.status == "failed"
        assert attempt.provisioning_execution_generation == 1


@pytest.mark.parametrize(
    ("field", "value", "error_type"),
    [
        ("expected_attempt_row_version", 1, RegistrationFenceError),
        ("expected_code_row_version", 1, RegistrationCodeError),
        (
            "provisioned",
            _provisioned(provisioning_generation=2),
            RegistrationFenceError,
        ),
        (
            "provisioned",
            _provisioned(lease_token="different-token"),
            RegistrationFenceError,
        ),
        (
            "provisioned",
            _provisioned(database_uuid=UUID(
                "30000000-0000-4000-8000-000000000091"
            )),
            RegistrationFenceError,
        ),
    ],
)
def test_final_commit_requires_attempt_code_route_and_worker_fences(
    database,
    field,
    value,
    error_type,
):
    _add_consumed_challenge(database)
    _reserve(database)
    _make_ready(database)

    with pytest.raises(error_type):
        _finalize(database, **{field: value})

    with database.transaction() as session:
        assert session.scalar(sa.select(sa.func.count(TenantRegistrationCommit.id))) == 0
        assert session.scalar(sa.select(sa.func.count(Subscription.id))) == 0
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        code = session.get(RedemptionCode, str(CODE_UUID))
        assert attempt is not None and attempt.status == "ready"
        assert code is not None and code.status == "reserved"


def test_user_disabled_after_provisioning_is_security_blocked(database):
    _add_consumed_challenge(database)
    _reserve(database)
    _make_ready(database)
    with database.transaction() as session:
        user = session.get(User, str(USER_UUID))
        assert user is not None
        user.status = "disabled"

    result = _finalize(database)

    assert result.status == "security_blocked"
    assert result.registration_commit_uuid is None
    with database.transaction() as session:
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        code = session.get(RedemptionCode, str(CODE_UUID))
        tenant = session.get(Tenant, str(TENANT_UUID))
        assert attempt is not None and attempt.status == "security_blocked"
        assert attempt.lease_owner is None
        assert code is not None and code.status == "reserved"
        assert tenant is not None and tenant.status == "provisioning"
        assert session.scalar(
            sa.select(sa.func.count(TenantRegistrationCommit.id))
        ) == 0


def test_current_recovery_authority_is_required_for_reserve_and_commit(database):
    _add_consumed_challenge(database)
    denied_reader = _authority(recovery_run_completed=False)
    denied_service, _ = _service(denied_reader)

    with pytest.raises(RegistrationAuthorityError):
        _reserve(database, service=denied_service)

    with database.transaction() as session:
        assert session.get(Tenant, str(TENANT_UUID)) is None
        code = session.get(RedemptionCode, str(CODE_UUID))
        assert code is not None and code.status == "active"

    allowed_service, _ = _service()
    _reserve(database, service=allowed_service)
    _make_ready(database)
    hold_denied_service, _ = _service(
        _authority(released_hold_ready=False)
    )
    with pytest.raises(RegistrationAuthorityError):
        _finalize(database, service=hold_denied_service)


def test_preexisting_replacement_wins_race_and_final_commit_fails_closed(database):
    _add_consumed_challenge(database)
    _reserve(database)
    _make_ready(database)
    replacement_code_uuid = UUID("30000000-0000-4000-8000-000000000092")
    platform_session_uuid = UUID("30000000-0000-4000-8000-000000000093")
    snapshot = parse_core_entitlements(
        schema_version=1,
        entitlements=ENTITLEMENTS,
    )
    with database.transaction() as session:
        session.add(
            PlatformAdminTotpCredential(
                id="30000000-0000-4000-8000-000000000094",
                platform_admin_id=str(ADMIN_UUID),
                generation=1,
                secret_revision=1,
                status="confirmed",
                seed_nonce=b"n" * 12,
                seed_ciphertext=b"c" * 32,
                root_key_version=1,
                crypto_version=1,
                aad_version=1,
                totp_algorithm="SHA1",
                totp_digits=6,
                totp_period_seconds=30,
                last_accepted_time_step=1,
                row_version=1,
                created_at=NOW - timedelta(days=1),
                confirmed_at=NOW - timedelta(days=1),
            )
        )
        session.flush()
        session.add(
            PlatformAdminSession(
                id=str(platform_session_uuid),
                platform_admin_id=str(ADMIN_UUID),
                token_digest_sha256=hashlib.sha256(b"platform-token").digest(),
                csrf_digest_sha256=hashlib.sha256(b"platform-csrf").digest(),
                auth_version_at_issue=1,
                setup_version_at_issue=1,
                mfa_method="totp",
                mfa_verified_at=NOW - timedelta(minutes=1),
                totp_credential_id=(
                    "30000000-0000-4000-8000-000000000094"
                ),
                totp_time_step=1,
                policy_version=1,
                idle_timeout_seconds=900,
                created_at=NOW,
                last_seen_at=NOW,
                idle_expires_at=NOW + timedelta(minutes=15),
                absolute_expires_at=NOW + timedelta(hours=8),
            )
        )
        session.add(
            RedemptionCode(
                id=str(replacement_code_uuid),
                crypto_context_uuid=(
                    "30000000-0000-4000-8000-000000000095"
                ),
                batch_id=str(BATCH_UUID),
                code_prefix="WXYZ",
                lookup_hash=hashlib.sha256(b"replacement-code").digest(),
                code_ciphertext=b"y" * 42,
                code_nonce=b"m" * 12,
                secret_revision=1,
                root_key_version=1,
                crypto_version=1,
                aad_version=1,
                status="active",
                plan_revision_uuid=str(PLAN_UUID),
                entitlements_schema_version=1,
                entitlements_json=ENTITLEMENTS,
                entitlements_digest=snapshot.digest_sha256,
                service_duration_seconds=SERVICE_SECONDS,
                redeem_before=NOW + timedelta(days=7),
                created_under_recovery_run_uuid=str(RUN_UUID),
                row_version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.flush()
        session.add(
            RedemptionCodeReplacement(
                id="30000000-0000-4000-8000-000000000096",
                source_code_uuid=str(CODE_UUID),
                replacement_code_uuid=str(replacement_code_uuid),
                source_attempt_uuid=str(ATTEMPT_UUID),
                source_user_uuid=str(USER_UUID),
                source_provisional_tenant_uuid=str(TENANT_UUID),
                source_provisional_database_uuid=str(DATABASE_UUID),
                chain_root_code_uuid=str(CODE_UUID),
                chain_generation=1,
                plan_revision_uuid=str(PLAN_UUID),
                entitlements_schema_version=1,
                entitlements_digest=snapshot.digest_sha256,
                service_duration_seconds=SERVICE_SECONDS,
                replacement_redeem_before=NOW + timedelta(days=7),
                fenced_provisioning_generation=1,
                platform_admin_uuid=str(ADMIN_UUID),
                platform_session_uuid=str(platform_session_uuid),
                reason_code="provisioning_replacement",
                idempotency_key="replacement-race-1",
                request_digest=hashlib.sha256(b"replacement").digest(),
                expected_source_code_row_version=2,
                expected_source_attempt_row_version=2,
                current_recovery_run_uuid=str(RUN_UUID),
                platform_audit_uuid=(
                    "30000000-0000-4000-8000-000000000097"
                ),
                created_at=NOW,
            )
        )

    with pytest.raises(RegistrationFenceError):
        _finalize(database)

    with database.transaction() as session:
        assert session.scalar(sa.select(sa.func.count(TenantRegistrationCommit.id))) == 0
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        assert attempt is not None and attempt.status == "ready"


def test_partial_anchor_creates_one_stable_integrity_incident(database):
    _add_consumed_challenge(database)
    _reserve(database)
    _make_ready(database)
    with database.transaction() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        assert tenant is not None
        tenant.name = "partially-published"

    first = _finalize(database)
    second = _finalize(database)

    assert first.status == "integrity_blocked"
    assert first.integrity_incident_uuid is not None
    assert second.integrity_incident_uuid == first.integrity_incident_uuid
    assert second.resulting_attempt_row_version == first.resulting_attempt_row_version
    with database.transaction() as session:
        incidents = tuple(session.scalars(sa.select(RegistrationIntegrityIncident)))
        attempt = session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID))
        code = session.get(RedemptionCode, str(CODE_UUID))
        assert len(incidents) == 1
        assert incidents[0].state == "open"
        assert incidents[0].presence_bitmap != 0
        assert attempt is not None and attempt.status == "integrity_blocked"
        assert attempt.lease_owner is None
        assert code is not None and code.status == "reserved"


def test_service_uses_caller_transaction_and_outer_rollback_is_authoritative(database):
    _add_consumed_challenge(database)
    service, _ = _service()

    session = database.new_session()
    try:
        with pytest.raises(RegistrationTransactionError):
            service.reserve_after_verified_otp(
                session,
                challenge_uuid=CHALLENGE_UUID,
                user_uuid=USER_UUID,
                code_lookup_hash=LOOKUP_HASH,
                attempt_uuid=ATTEMPT_UUID,
                provisional_tenant_uuid=TENANT_UUID,
                provisional_database_uuid=DATABASE_UUID,
                requested_tenant_name=TENANT_NAME,
                idempotency_key=RESERVATION_KEY,
                expected_code_row_version=1,
                current_recovery_run_uuid=RUN_UUID,
            )
    finally:
        session.close()

    class AbortOuterTransaction(RuntimeError):
        pass

    session = database.new_session()
    try:
        with pytest.raises(AbortOuterTransaction):
            with session.begin():
                result = service.reserve_after_verified_otp(
                    session,
                    challenge_uuid=CHALLENGE_UUID,
                    user_uuid=USER_UUID,
                    code_lookup_hash=LOOKUP_HASH,
                    attempt_uuid=ATTEMPT_UUID,
                    provisional_tenant_uuid=TENANT_UUID,
                    provisional_database_uuid=DATABASE_UUID,
                    requested_tenant_name=TENANT_NAME,
                    idempotency_key=RESERVATION_KEY,
                    expected_code_row_version=1,
                    current_recovery_run_uuid=RUN_UUID,
                )
                assert result.created is True
                assert session.in_transaction()
                raise AbortOuterTransaction()
    finally:
        session.close()

    with database.transaction() as session:
        assert session.get(Tenant, str(TENANT_UUID)) is None
        assert session.get(TenantRegistrationAttempt, str(ATTEMPT_UUID)) is None
        code = session.get(RedemptionCode, str(CODE_UUID))
        assert code is not None and code.status == "active"
        assert code.row_version == 1


def test_dirty_caller_unit_of_work_is_rejected_without_implicit_flush(database):
    _add_consumed_challenge(database)
    service, _ = _service()
    with pytest.raises(RegistrationTransactionError):
        with database.transaction() as session:
            user = session.get(User, str(USER_UUID))
            assert user is not None
            user.status = "disabled"
            service.reserve_after_verified_otp(
                session,
                challenge_uuid=CHALLENGE_UUID,
                user_uuid=USER_UUID,
                code_lookup_hash=LOOKUP_HASH,
                attempt_uuid=ATTEMPT_UUID,
                provisional_tenant_uuid=TENANT_UUID,
                provisional_database_uuid=DATABASE_UUID,
                requested_tenant_name=TENANT_NAME,
                idempotency_key=RESERVATION_KEY,
                expected_code_row_version=1,
                current_recovery_run_uuid=RUN_UUID,
            )

    with database.transaction() as session:
        user = session.get(User, str(USER_UUID))
        assert user is not None and user.status == "active"
