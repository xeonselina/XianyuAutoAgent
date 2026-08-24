from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa

from app.services.tenant_integrations import (
    CredentialValidationDecision,
    CredentialValidationResult,
    PROVIDER_ACCOUNT_REVISION_SOURCE_TYPE,
    PROVIDER_ACCOUNT_VALIDATION_EVENT_TYPE,
    PROVIDER_BINDING_APPLY_EVENT_TYPE,
    PROVIDER_BINDING_REMOVE_EVENT_TYPE,
    PROVIDER_CLAIM_RELEASE_SOURCE_TYPE,
    SfWarehouseBindingApplyResult,
    TenantProviderAccountOutboxAuthority,
    TenantProviderAccountValidationHandler,
    TenantProviderBindingApplyHandler,
    TenantProviderBindingRemoveHandler,
    TenantProviderUnbindingOutboxAuthority,
)
from inventory_control import (
    ControlBase,
    ControlDatabase,
    PlatformRootKeyVersion,
    TenantDatabase,
)
from inventory_control.crypto import RootKey, derive_provider_account_fingerprint
from inventory_control.domain import EffectiveTenantGate, TenantRole
from inventory_control.integrations import (
    ProviderValidationOutcome,
    SfAdminClaimProof,
    SfClaimOwner,
    SfClaimPersistenceService,
    TenantIntegrationService,
    TenantProviderAccountService,
)
from inventory_control.jobs import (
    ControlJobService,
    ControlOutboxService,
    ControlTenantGateReader,
    DurableOrdinaryOutboxWorker,
    OutboxAuthorityVerdict,
)
from inventory_control.models import (
    ControlOutboxEvent,
    ProviderAccountClaim,
    SmsChallenge,
    Tenant,
    TenantIntegration,
    TenantMembership,
    TenantProviderAccount,
    TenantProviderAccountSecretRevision,
    TenantSensitiveActionIntent,
    TenantSensitiveActionIntentChallenge,
    TenantUserSession,
    User,
)
from inventory_control.models.subscriptions import PlanRevision, Subscription


# Keep database-current-time fences stable regardless of the wall-clock date on
# which this deterministic worker fixture is replayed.
NOW = datetime(2099, 8, 23, 4, 30, tzinfo=timezone.utc)
TENANT_ID = UUID("7b000000-0000-4000-8000-000000000001")
INTEGRATION_ID = UUID("7b000000-0000-4000-8000-000000000002")
ACCOUNT_ID = UUID("7b000000-0000-4000-8000-000000000003")
WAREHOUSE_ID = UUID("7b000000-0000-4000-8000-000000000004")
USER_ID = UUID("7b000000-0000-4000-8000-000000000005")
SESSION_ID = UUID("7b000000-0000-4000-8000-000000000006")
CHALLENGE_ID = UUID("7b000000-0000-4000-8000-000000000007")
ACTION_ID = UUID("7b000000-0000-4000-8000-000000000008")
INTEGRATION_ACTION_ID = UUID("7b000000-0000-4000-8000-000000000009")
ROOT_KEY = RootKey(version=11, material=b"p" * 32)
REQUEST_DIGEST = hashlib.sha256(b"provider-account-bind-request").digest()
MAC_KEY = b"provider-account-validation-key!"


class _Authority:
    def lock_current_outbox_authority(self, _session, *, facts, phase):
        return facts, phase

    def evaluate_locked_outbox_authority(
        self,
        _session,
        *,
        locked_authority,
        facts,
        phase,
        now,
    ):
        assert locked_authority == (facts, phase)
        return OutboxAuthorityVerdict(
            allowed=True,
            current_recovery_run_verified=True,
            current_source_generation=facts.source_generation,
            current_tenant_access_version=facts.tenant_access_version,
            reason_code="authority_allowed",
        )


class _Validator:
    def __init__(self, decision, *, raises=False):
        self.decision = decision
        self.raises = raises
        self.calls = 0
        self.integration_credentials = None
        self.account_secret = None
        self.request_repr = None

    def validate_account(self, request):
        self.calls += 1
        self.request_repr = repr(request)
        credentials, account_secret = request.take_credentials()
        self.integration_credentials = dict(credentials)
        self.account_secret = account_secret
        if self.raises:
            raise RuntimeError("provider response was lost")
        return CredentialValidationResult(
            self.decision,
            safe_code={
                CredentialValidationDecision.VALID: "ACCOUNT_VALID",
                CredentialValidationDecision.INVALID: "ACCOUNT_REJECTED",
                CredentialValidationDecision.UNKNOWN: "PROVIDER_TIMEOUT",
            }[self.decision],
            safe_facts_digest=hashlib.sha256(
                f"account:{self.decision.value}".encode("ascii")
            ).digest(),
        )


class _BindingApplier:
    def __init__(self):
        self.calls = []

    def apply_binding(self, request):
        self.calls.append(request)
        return SfWarehouseBindingApplyResult(
            safe_code="WAREHOUSE_BINDING_APPLIED",
            safe_facts_digest=hashlib.sha256(b"binding-applied").digest(),
            binding_revision=request.target_binding_revision,
            idempotent_replay=False,
        )

    def remove_binding(self, request):
        self.calls.append(request)
        return SfWarehouseBindingApplyResult(
            safe_code="WAREHOUSE_BINDING_REMOVED",
            safe_facts_digest=hashlib.sha256(b"binding-removed").digest(),
            binding_revision=request.expected_binding_revision + 1,
            idempotent_replay=False,
        )


@pytest.fixture
def harness(tmp_path, mysql_control_database):
    database = mysql_control_database
    key_file = tmp_path / f"v{ROOT_KEY.version}"
    key_file.write_bytes(base64.b64encode(ROOT_KEY._material_bytes()) + b"\n")
    key_file.chmod(0o400)
    try:
        _seed_control_authority(database)
        _seed_active_integration(database)
        claim = _reserve_claim(database)
        with database.transaction() as session:
            pending = TenantProviderAccountService(session).create_pending_revision(
                provider_account_uuid=ACCOUNT_ID,
                tenant_uuid=TENANT_ID,
                integration_uuid=INTEGRATION_ID,
                warehouse_uuid=WAREHOUSE_ID,
                label="Main warehouse",
                account_secret="001234567890",
                root_key=ROOT_KEY,
                claim_uuid=claim.claim_uuid,
                expected_claim_generation=claim.generation,
                expected_claim_row_version=claim.row_version,
                target_binding_revision=1,
                expected_warehouse_provider_account_uuid=None,
                expected_warehouse_binding_revision=None,
                created_by_user_uuid=USER_ID,
                action_uuid=ACTION_ID,
                request_digest=REQUEST_DIGEST,
                idempotency_key=f"sf-account:{ACTION_ID}",
                expected_account_row_version=None,
                expected_current_secret_revision_uuid=None,
                expected_current_global_claim_uuid=None,
            )
            event = ControlJobService().enqueue_outbox(
                session,
                tenant_id=str(TENANT_ID),
                tenant_access_version=1,
                source_type=PROVIDER_ACCOUNT_REVISION_SOURCE_TYPE,
                source_uuid=pending.revision_uuid,
                source_generation=pending.revision_no,
                event_type=PROVIDER_ACCOUNT_VALIDATION_EVENT_TYPE,
                payload={
                    "revision_uuid": pending.revision_uuid,
                    "revision_row_version": pending.row_version,
                },
                idempotency_key=f"sf-account:{ACTION_ID}",
                max_attempts=1,
                available_at=NOW,
            )
        yield database, tmp_path, event.id, pending.revision_uuid
    finally:
        pass


def _seed_control_authority(database):
    entitlements = {"features": {}, "limits": {"member_seats": 10}}
    digest = hashlib.sha256(b"provider-account-entitlements").digest()
    with database.transaction() as session:
        plan = PlanRevision(
            code="core",
            revision=1,
            name="Core",
            entitlements_schema_version=1,
            entitlements_json=entitlements,
            entitlements_digest=digest,
        )
        tenant = Tenant(id=str(TENANT_ID), status="active", access_version=1)
        user = User(
            id=str(USER_ID),
            phone_region_iso2="CN",
            phone_e164="+8613800001234",
            phone_normalization_version=1,
            phone_metadata_version="test-v1",
            phone_verified_at=NOW - timedelta(days=1),
            status="active",
            auth_version=1,
        )
        session.add_all((
            plan,
            tenant,
            user,
            PlatformRootKeyVersion(
                version=ROOT_KEY.version,
                fingerprint_sha256=bytes.fromhex(ROOT_KEY.fingerprint_sha256),
                status="active",
                activated_at=NOW,
            ),
        ))
        session.flush()
        session.add_all((
            TenantDatabase(
                tenant_id=str(TENANT_ID),
                database_instance_key="primary",
                database_name="tenant_7b000000000040008000000000000001",
                status="ready",
                schema_version="test-head",
                activated_by_registration_commit_uuid=(
                    "7b000000-0000-4000-8000-000000000099"
                ),
                activation_route_version=1,
                activation_credential_generation=1,
                dml_username="tenant_dml_g1",
                dml_credential_generation=1,
                dml_root_key_version=1,
                dml_derivation_version=1,
                dml_desired_login_state="active",
                dml_observed_login_state="active",
                dml_login_state_version=1,
                platform_read_username="tenant_read_g1",
                platform_read_credential_generation=1,
                platform_read_root_key_version=1,
                platform_read_derivation_version=1,
                platform_read_route_version=1,
            ),
            Subscription(
                tenant_id=str(TENANT_ID),
                plan_revision_uuid=plan.id,
                entitlements_schema_version=1,
                entitlements_json=entitlements,
                entitlements_digest=digest,
                status="active",
                expires_at=NOW + timedelta(days=30),
            ),
            TenantMembership(
                id="7b000000-0000-4000-8000-000000000010",
                tenant_id=str(TENANT_ID),
                user_id=str(USER_ID),
                role_key="admin",
                status="active",
                source_type="registration",
                row_version=1,
            ),
            TenantUserSession(
                id=str(SESSION_ID),
                user_id=str(USER_ID),
                token_digest_sha256=hashlib.sha256(b"session-token").digest(),
                csrf_digest_sha256=hashlib.sha256(b"session-csrf").digest(),
                auth_version_at_issue=1,
                tenant_access_version_at_issue=1,
                policy_version=1,
                csrf_generation=1,
                idle_timeout_seconds=3600,
                created_at=NOW - timedelta(minutes=5),
                last_seen_at=NOW,
                idle_expires_at=NOW + timedelta(hours=1),
                absolute_expires_at=NOW + timedelta(days=1),
            ),
        ))
        session.flush()
        session.add(
            SmsChallenge(
                id=str(CHALLENGE_ID),
                purpose="sf_account_bind",
                canonical_phone_e164=user.phone_e164,
                phone_normalization_version=1,
                phone_metadata_version="test-v1",
                user_id=str(USER_ID),
                tenant_id=str(TENANT_ID),
                actor_session_id=str(SESSION_ID),
                action_payload_digest_sha256=hashlib.sha256(b"action").digest(),
                authoritative_revision=f"sensitive-intent:{ACTION_ID}:1",
                code_hmac_sha256=hashlib.sha256(b"code").digest(),
                root_key_version=ROOT_KEY.version,
                hmac_protocol_version=1,
                policy_version=1,
                max_wrong_attempts=5,
                trusted_source_bucket="test-source",
                delivery_state="sent",
                verification_state="consumed",
                wrong_attempt_count=0,
                row_version=3,
                created_at=NOW - timedelta(minutes=4),
                expires_at=NOW + timedelta(minutes=1),
                delivery_recorded_at=NOW - timedelta(minutes=4),
                consumed_at=NOW - timedelta(minutes=1),
            )
        )
        session.flush()
        session.add_all((
            TenantSensitiveActionIntent(
                id=str(ACTION_ID),
                tenant_id=str(TENANT_ID),
                actor_user_id=str(USER_ID),
                actor_session_id=str(SESSION_ID),
                purpose="sf_account_bind",
                action_subtype="sf.account_bind",
                target_type="warehouse",
                target_uuid=str(WAREHOUSE_ID),
                expected_target_revision="binding:absent:target:1",
                canonicalization_version=1,
                context_mac_version=1,
                root_key_version=ROOT_KEY.version,
                request_context_mac_sha256=hashlib.sha256(b"context").digest(),
                idempotency_key=f"sf-account:{ACTION_ID}",
                status="succeeded",
                safe_result_code="provider_account_revision_pending",
                request_id=f"sensitive-action:{ACTION_ID}",
                correlation_id=f"provider-account:{ACCOUNT_ID}",
                row_version=3,
                created_at=NOW - timedelta(minutes=4),
                updated_at=NOW - timedelta(minutes=1),
                expires_at=NOW + timedelta(minutes=1),
                authorized_at=NOW - timedelta(minutes=1),
                completed_at=NOW - timedelta(minutes=1),
            ),
            TenantSensitiveActionIntentChallenge(
                intent_id=str(ACTION_ID),
                challenge_role="primary",
                challenge_id=str(CHALLENGE_ID),
                created_at=NOW - timedelta(minutes=4),
            ),
        ))


def _seed_active_integration(database):
    with database.transaction() as session:
        service = TenantIntegrationService(session)
        service.create_integration(
            integration_uuid=INTEGRATION_ID,
            tenant_uuid=TENANT_ID,
            provider="sf",
            name="main-sf",
        )
        pending = service.create_pending_revision(
            integration_uuid=INTEGRATION_ID,
            credentials={"partner_id": "partner-value", "checkword": "checkword"},
            root_key=ROOT_KEY,
            created_by_user_uuid=USER_ID,
            action_uuid=INTEGRATION_ACTION_ID,
            idempotency_key="integration:provider-account-test",
            expected_integration_row_version=1,
            expected_current_secret_revision_uuid=None,
        )
    attempt = UUID("7b000000-0000-4000-8000-000000000011")
    with database.transaction() as session:
        TenantIntegrationService(session).begin_provider_validation(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=attempt,
            expected_revision_row_version=1,
        )
    with database.transaction() as session:
        TenantIntegrationService(session).record_provider_validation_result(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=attempt,
            outcome=ProviderValidationOutcome.SUCCESS,
            provider_result_digest=hashlib.sha256(b"integration-valid").digest(),
            safe_code="VALID",
            completed_at=NOW,
        )


def _reserve_claim(database):
    owner = SfClaimOwner(TENANT_ID, ACCOUNT_ID, WAREHOUSE_ID)
    proof = SfAdminClaimProof(
        tenant_uuid=TENANT_ID,
        actor_user_uuid=USER_ID,
        actor_session_uuid=SESSION_ID,
        role=TenantRole.ADMIN,
        effective_gate=EffectiveTenantGate.ACTIVE,
        tenant_access_version=1,
        otp_challenge_uuid=CHALLENGE_ID,
        otp_purpose="sf_account_bind",
        otp_action_uuid=ACTION_ID,
        otp_request_digest=REQUEST_DIGEST,
        otp_consumed=True,
    )
    with database.transaction() as session:
        return SfClaimPersistenceService(
            session,
            database_clock=lambda _session: NOW,
        ).reserve_claim(
            fingerprint=derive_provider_account_fingerprint(
                root_key=ROOT_KEY,
                provider="sf",
                canonical_account="001234567890",
            ),
            owner=owner,
            proof=proof,
            expected_generation=1,
            expected_row_version=1,
            action_uuid=ACTION_ID,
            request_digest=REQUEST_DIGEST,
            reservation_expires_at=NOW + timedelta(minutes=30),
        )


def _run(harness, validator, *, authority=None):
    database, keys, _event_id, _revision_id = harness
    handler = TenantProviderAccountValidationHandler(
        root_key_directory=keys,
        validator=validator,
    )
    worker = DurableOrdinaryOutboxWorker(
        database=database,
        authority=authority or _Authority(),
        handlers={PROVIDER_ACCOUNT_VALIDATION_EVENT_TYPE: handler},
        heartbeat_recorder=None,
        worker_id="provider-account-validator-1",
        result_mac_key=MAC_KEY,
        lease_duration=timedelta(minutes=2),
        clock=lambda: NOW,
        allow_sqlite_claim_for_tests=True,
        service=ControlOutboxService(database_clock=lambda _session: NOW),
    )
    return worker.run_once()


def _gate_reader():
    return ControlTenantGateReader(
        recovery_hold_released=lambda _session, **_kwargs: True,
        unresolved_deletion=lambda _session, **_kwargs: False,
        unresolved_suspension=lambda _session, **_kwargs: False,
        database_clock=lambda _session: NOW,
    )


def _run_binding(database, applier):
    return DurableOrdinaryOutboxWorker(
        database=database,
        authority=_Authority(),
        handlers={
            PROVIDER_BINDING_APPLY_EVENT_TYPE: TenantProviderBindingApplyHandler(
                applier=applier
            )
        },
        heartbeat_recorder=None,
        worker_id="provider-binding-worker-1",
        result_mac_key=MAC_KEY,
        lease_duration=timedelta(minutes=2),
        clock=lambda: NOW,
        allow_sqlite_claim_for_tests=True,
        service=ControlOutboxService(database_clock=lambda _session: NOW),
    ).run_once()


def _run_unbinding(database, applier):
    return DurableOrdinaryOutboxWorker(
        database=database,
        authority=TenantProviderUnbindingOutboxAuthority(_gate_reader()),
        handlers={
            PROVIDER_BINDING_REMOVE_EVENT_TYPE: (
                TenantProviderBindingRemoveHandler(applier=applier)
            )
        },
        heartbeat_recorder=None,
        worker_id="provider-unbinding-worker-1",
        result_mac_key=MAC_KEY,
        lease_duration=timedelta(minutes=2),
        clock=lambda: NOW,
        allow_sqlite_claim_for_tests=True,
        service=ControlOutboxService(database_clock=lambda _session: NOW),
    ).run_once()


@pytest.mark.parametrize(
    ("decision", "revision_status", "verification", "account_status"),
    [
        (CredentialValidationDecision.VALID, "current", "succeeded", "active"),
        (
            CredentialValidationDecision.INVALID,
            "revoked",
            "failed",
            "verification_failed",
        ),
    ],
)
def test_known_result_finishes_exact_account_revision(
    harness,
    decision,
    revision_status,
    verification,
    account_status,
):
    database, _keys, event_id, revision_id = harness
    validator = _Validator(decision)

    result = _run(harness, validator)

    assert result.state == "succeeded"
    assert validator.calls == 1
    assert validator.integration_credentials == {
        "partner_id": "partner-value",
        "checkword": "checkword",
    }
    assert validator.account_secret == "001234567890"
    assert "partner-value" not in validator.request_repr
    assert "001234567890" not in validator.request_repr
    with database.new_session() as session:
        event = session.get(ControlOutboxEvent, event_id)
        revision = session.get(TenantProviderAccountSecretRevision, revision_id)
        account = session.get(TenantProviderAccount, str(ACCOUNT_ID))
        assert event.state == "succeeded"
        assert revision.status == revision_status
        assert revision.verification_status == verification
        assert account.status == account_status
        assert "001234567890" not in str(event.payload)


@pytest.mark.parametrize("raises", [False, True])
def test_unknown_result_never_retries_or_activates_claim(harness, raises):
    database, _keys, event_id, revision_id = harness
    validator = _Validator(CredentialValidationDecision.UNKNOWN, raises=raises)

    result = _run(harness, validator)

    assert result.state == "recovery_quarantined"
    assert result.reason_code == "provider_result_unknown"
    with database.new_session() as session:
        event = session.get(ControlOutboxEvent, event_id)
        revision = session.get(TenantProviderAccountSecretRevision, revision_id)
        account = session.get(TenantProviderAccount, str(ACCOUNT_ID))
        assert event.attempts == 1
        assert revision.status == "pending_validation"
        assert revision.verification_status == "unknown"
        assert account.current_secret_revision_id is None


def test_current_gate_blocks_suspended_tenant_before_provider(harness):
    database, _keys, event_id, revision_id = harness
    with database.transaction() as session:
        session.get(Tenant, str(TENANT_ID)).status = "suspended"
    validator = _Validator(CredentialValidationDecision.VALID)

    result = _run(
        harness,
        validator,
        authority=TenantProviderAccountOutboxAuthority(_gate_reader()),
    )

    assert result.state == "idle"
    assert validator.calls == 0
    with database.new_session() as session:
        event = session.get(ControlOutboxEvent, event_id)
        revision = session.get(TenantProviderAccountSecretRevision, revision_id)
        assert event.state == "recovery_quarantined"
        assert event.last_error_code == "tenant_suspended"
        assert revision.verification_status == "not_attempted"


def test_current_authority_allows_exact_active_sources(harness):
    database, _keys, event_id, revision_id = harness
    validator = _Validator(CredentialValidationDecision.VALID)

    result = _run(
        harness,
        validator,
        authority=TenantProviderAccountOutboxAuthority(_gate_reader()),
    )

    assert result.state == "succeeded"
    assert validator.calls == 1
    with database.new_session() as session:
        assert session.get(ControlOutboxEvent, event_id).state == "succeeded"
        assert session.get(
            TenantProviderAccountSecretRevision, revision_id
        ).status == "current"


def test_success_enqueues_and_applies_exact_tenant_binding_command(harness):
    database, _keys, _event_id, revision_id = harness
    validation = _run(harness, _Validator(CredentialValidationDecision.VALID))
    applier = _BindingApplier()

    binding = _run_binding(database, applier)

    assert validation.state == "succeeded"
    assert binding.state == "succeeded"
    assert len(applier.calls) == 1
    command = applier.calls[0]
    assert command.tenant_id == str(TENANT_ID)
    assert command.warehouse_id == str(WAREHOUSE_ID)
    assert command.provider_account_id == str(ACCOUNT_ID)
    assert command.account_revision_id == revision_id
    assert command.target_binding_revision == 1
    assert command.expected_provider_account_id is None
    assert command.expected_binding_revision is None


def test_released_claim_event_authorizes_cleanup_after_new_reservation(harness):
    database, _keys, _event_id, _revision_id = harness
    assert _run(
        harness,
        _Validator(CredentialValidationDecision.VALID),
    ).state == "succeeded"
    assert _run_binding(database, _BindingApplier()).state == "succeeded"

    unbind_action = UUID("7b000000-0000-4000-8000-000000000021")
    unbind_challenge = UUID("7b000000-0000-4000-8000-000000000022")
    unbind_digest = hashlib.sha256(b"provider-account-unbind").digest()
    with database.transaction() as session:
        account = session.get(TenantProviderAccount, str(ACCOUNT_ID))
        claim = session.get(ProviderAccountClaim, account.current_global_claim_id)
        released = TenantProviderAccountService(session).release_current_claim(
            provider_account_uuid=ACCOUNT_ID,
            warehouse_uuid=WAREHOUSE_ID,
            proof=SfAdminClaimProof(
                tenant_uuid=TENANT_ID,
                actor_user_uuid=USER_ID,
                actor_session_uuid=SESSION_ID,
                role=TenantRole.ADMIN,
                effective_gate=EffectiveTenantGate.ACTIVE,
                tenant_access_version=1,
                otp_challenge_uuid=unbind_challenge,
                otp_purpose="sf_account_unbind",
                otp_action_uuid=unbind_action,
                otp_request_digest=unbind_digest,
                otp_consumed=True,
            ),
            action_uuid=unbind_action,
            request_digest=unbind_digest,
            expected_account_row_version=account.row_version,
            expected_claim_generation=claim.claim_generation,
            expected_claim_row_version=claim.row_version,
        )
        session.flush()
        released_claim = session.get(
            ProviderAccountClaim,
            claim.id,
            populate_existing=True,
        )
        removal = ControlJobService().enqueue_outbox(
            session,
            tenant_id=str(TENANT_ID),
            tenant_access_version=1,
            source_type=PROVIDER_CLAIM_RELEASE_SOURCE_TYPE,
            source_uuid=released_claim.id,
            source_generation=released_claim.claim_generation,
            event_type=PROVIDER_BINDING_REMOVE_EVENT_TYPE,
            payload={
                "provider_account_uuid": str(ACCOUNT_ID),
                "warehouse_uuid": str(WAREHOUSE_ID),
                "expected_binding_revision": 1,
            },
            idempotency_key=f"sf-unbinding:{unbind_action}",
            max_attempts=1,
            available_at=NOW,
        )
        assert released.status == "inactive"

    # A different owner can reserve the globally released fingerprint before
    # the old tenant's local cleanup runs.  Cleanup authority is the immutable
    # release event, so current global ownership must not block this leg.
    next_tenant = UUID("7b000000-0000-4000-8000-000000000031")
    next_account = UUID("7b000000-0000-4000-8000-000000000032")
    next_warehouse = UUID("7b000000-0000-4000-8000-000000000033")
    next_action = UUID("7b000000-0000-4000-8000-000000000034")
    next_digest = hashlib.sha256(b"next-provider-owner").digest()
    with database.transaction() as session:
        current = session.get(ProviderAccountClaim, removal.source_uuid)
        SfClaimPersistenceService(
            session,
            database_clock=lambda _session: NOW,
        ).reserve_claim(
            fingerprint=derive_provider_account_fingerprint(
                root_key=ROOT_KEY,
                provider="sf",
                canonical_account="001234567890",
            ),
            owner=SfClaimOwner(next_tenant, next_account, next_warehouse),
            proof=SfAdminClaimProof(
                tenant_uuid=next_tenant,
                actor_user_uuid=UUID(
                    "7b000000-0000-4000-8000-000000000035"
                ),
                actor_session_uuid=UUID(
                    "7b000000-0000-4000-8000-000000000036"
                ),
                role=TenantRole.ADMIN,
                effective_gate=EffectiveTenantGate.ACTIVE,
                tenant_access_version=1,
                otp_challenge_uuid=UUID(
                    "7b000000-0000-4000-8000-000000000037"
                ),
                otp_purpose="sf_account_bind",
                otp_action_uuid=next_action,
                otp_request_digest=next_digest,
                otp_consumed=True,
            ),
            expected_generation=current.claim_generation,
            expected_row_version=current.row_version,
            action_uuid=next_action,
            request_digest=next_digest,
            reservation_expires_at=NOW + timedelta(minutes=30),
        )

    applier = _BindingApplier()
    result = _run_unbinding(database, applier)

    assert result.state == "succeeded"
    assert len(applier.calls) == 1
    command = applier.calls[0]
    assert command.tenant_id == str(TENANT_ID)
    assert command.provider_account_id == str(ACCOUNT_ID)
    assert command.claim_id == removal.source_uuid
    assert command.release_generation == removal.source_generation
    assert command.expected_binding_revision == 1


def test_integration_pointer_drift_blocks_provider_dispatch(harness):
    database, _keys, event_id, revision_id = harness
    with database.transaction() as session:
        session.get(TenantIntegration, str(INTEGRATION_ID)).status = "inactive"
    validator = _Validator(CredentialValidationDecision.VALID)

    result = _run(
        harness,
        validator,
        authority=TenantProviderAccountOutboxAuthority(_gate_reader()),
    )

    assert result.state == "idle"
    assert validator.calls == 0
    with database.new_session() as session:
        event = session.get(ControlOutboxEvent, event_id)
        revision = session.get(TenantProviderAccountSecretRevision, revision_id)
        assert event.state == "recovery_quarantined"
        assert event.last_error_code == "provider_account_source_stale"
        assert revision.verification_status == "not_attempted"


def test_d48_session_or_membership_drift_quarantines_success(harness):
    database, _keys, event_id, revision_id = harness
    with database.transaction() as session:
        membership = session.scalar(
            sa.select(TenantMembership).where(
                TenantMembership.tenant_id == str(TENANT_ID)
            )
        )
        membership.role_key = "operator"
    validator = _Validator(CredentialValidationDecision.VALID)

    result = _run(harness, validator)

    assert result.state == "recovery_quarantined"
    assert result.reason_code == "result_persistence_failed"
    assert validator.calls == 1
    with database.new_session() as session:
        event = session.get(ControlOutboxEvent, event_id)
        revision = session.get(TenantProviderAccountSecretRevision, revision_id)
        assert event.state == "recovery_quarantined"
        assert revision.status == "pending_validation"
        assert revision.verification_status == "unknown"
