from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa

from inventory_control import ControlBase, ControlDatabase
from inventory_control.crypto import (
    RootKey,
    RootKeyLifecycle,
    RootKeyRing,
    derive_provider_account_fingerprint,
)
from inventory_control.domain import EffectiveTenantGate, TenantRole
from inventory_control.integrations import (
    HistoricalTrackingCredentialError,
    ProviderAccountIdempotencyConflictError,
    ProviderAccountCredentialAuthenticationError,
    ProviderAccountStateConflictError,
    ProviderAccountTransactionError,
    ProviderContextError,
    ProviderValidationOutcome,
    ProviderValidationReconciliation,
    SfAdminClaimProof,
    SfClaimAuthorityDenied,
    SfClaimOwner,
    SfClaimPersistenceService,
    SfProviderContextResolver,
    SfWaybillCredentialError,
    SfWaybillCredentialFactory,
    SfHistoricalTrackingCredentialFactory,
    SfTrackingQueryItem,
    TenantIntegrationService,
    TenantProviderAccountBindingCoordinator,
    TenantProviderAccountEnvelopeService,
    TenantProviderAccountService,
)
from inventory_control.integrations.sf_waybill import _cargo_snapshot_json
from inventory_control.models import (
    ProviderAccountClaim,
    Tenant,
    TenantIntegration,
    TenantProviderAccount,
    TenantProviderAccountSecretRevision,
    TenantProviderAccountSecretEnvelopeEvent,
)


ROOT_KEY = RootKey(version=1, material=b"a" * 32)
TENANT_UUID = UUID("10000000-0000-4000-8000-000000000001")
INTEGRATION_UUID = UUID("10000000-0000-4000-8000-000000000002")
ACCOUNT_UUID = UUID("10000000-0000-4000-8000-000000000003")
WAREHOUSE_UUID = UUID("10000000-0000-4000-8000-000000000004")
USER_UUID = UUID("10000000-0000-4000-8000-000000000005")
SESSION_UUID = UUID("10000000-0000-4000-8000-000000000006")
OTP_UUID = UUID("10000000-0000-4000-8000-000000000007")
ACTION_UUID = UUID("10000000-0000-4000-8000-000000000008")
ATTEMPT_UUID = UUID("10000000-0000-4000-8000-000000000009")
ACCOUNT_SECRET = "001234567890"
REQUEST_DIGEST = hashlib.sha256(b"bind-request").digest()
RESULT_DIGEST = hashlib.sha256(b"provider-result").digest()


@pytest.mark.parametrize("name", ("租赁\n设备", "租赁\t设备", "租赁\x7f设备"))
def test_waybill_cargo_name_rejects_control_characters(name):
    with pytest.raises(SfWaybillCredentialError):
        _cargo_snapshot_json({"items": [{"name": name, "count": 1}]})


@pytest.fixture
def control_database(mysql_control_database):
    database = mysql_control_database
    with database.transaction() as session:
        session.add(Tenant(id=str(TENANT_UUID), status="active"))
    with database.transaction() as session:
        integrations = TenantIntegrationService(session)
        integrations.create_integration(
            integration_uuid=INTEGRATION_UUID,
            tenant_uuid=TENANT_UUID,
            provider="sf",
            name="main-sf",
        )
    with database.transaction() as session:
        pending = TenantIntegrationService(session).create_pending_revision(
            integration_uuid=INTEGRATION_UUID,
            credentials={"partner_id": "partner", "checkword": "checkword"},
            root_key=ROOT_KEY,
            created_by_user_uuid=USER_UUID,
            action_uuid=UUID("10000000-0000-4000-8000-000000000010"),
            idempotency_key="integration-revision-1",
            expected_integration_row_version=1,
            expected_current_secret_revision_uuid=None,
        )
    integration_attempt = UUID("10000000-0000-4000-8000-000000000011")
    with database.transaction() as session:
        TenantIntegrationService(session).begin_provider_validation(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=integration_attempt,
            expected_revision_row_version=1,
        )
    with database.transaction() as session:
        TenantIntegrationService(session).record_provider_validation_result(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=integration_attempt,
            outcome=ProviderValidationOutcome.SUCCESS,
            provider_result_digest=hashlib.sha256(b"integration-ok").digest(),
            safe_code="VALID",
        )
    return database


def _proof() -> SfAdminClaimProof:
    return SfAdminClaimProof(
        tenant_uuid=TENANT_UUID,
        actor_user_uuid=USER_UUID,
        actor_session_uuid=SESSION_UUID,
        role=TenantRole.ADMIN,
        effective_gate=EffectiveTenantGate.ACTIVE,
        tenant_access_version=1,
        otp_challenge_uuid=OTP_UUID,
        otp_purpose="sf_account_bind",
        otp_action_uuid=ACTION_UUID,
        otp_request_digest=REQUEST_DIGEST,
        otp_consumed=True,
    )


def _owner() -> SfClaimOwner:
    return SfClaimOwner(
        tenant_uuid=TENANT_UUID,
        provider_account_uuid=ACCOUNT_UUID,
        warehouse_uuid=WAREHOUSE_UUID,
    )


def _reserve(control_database):
    fingerprint = derive_provider_account_fingerprint(
        root_key=ROOT_KEY,
        provider="sf",
        canonical_account=ACCOUNT_SECRET,
    )
    with control_database.transaction() as session:
        return SfClaimPersistenceService(session).reserve_claim(
            fingerprint=fingerprint,
            owner=_owner(),
            proof=_proof(),
            expected_generation=1,
            expected_row_version=1,
            action_uuid=ACTION_UUID,
            request_digest=REQUEST_DIGEST,
            reservation_expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )


def _create_pending(control_database, claim, *, secret=ACCOUNT_SECRET):
    with control_database.transaction() as session:
        return TenantProviderAccountService(session).create_pending_revision(
            provider_account_uuid=ACCOUNT_UUID,
            tenant_uuid=TENANT_UUID,
            integration_uuid=INTEGRATION_UUID,
            warehouse_uuid=WAREHOUSE_UUID,
            label="Main warehouse",
            account_secret=secret,
            root_key=ROOT_KEY,
            claim_uuid=claim.claim_uuid,
            expected_claim_generation=claim.generation,
            expected_claim_row_version=claim.row_version,
            target_binding_revision=1,
            expected_warehouse_provider_account_uuid=None,
            expected_warehouse_binding_revision=None,
            created_by_user_uuid=USER_UUID,
            action_uuid=ACTION_UUID,
            request_digest=REQUEST_DIGEST,
            idempotency_key="provider-account-revision-1",
            expected_account_row_version=None,
            expected_current_secret_revision_uuid=None,
            expected_current_global_claim_uuid=None,
        )


def _begin(control_database, revision_uuid):
    with control_database.transaction() as session:
        return TenantProviderAccountService(session).begin_provider_validation(
            revision_uuid=revision_uuid,
            attempt_uuid=ATTEMPT_UUID,
            expected_revision_row_version=1,
        )


def _record_unknown(control_database):
    claim = _reserve(control_database)
    pending = _create_pending(control_database, claim)
    _begin(control_database, pending.revision_uuid)
    with control_database.transaction() as session:
        TenantProviderAccountService(session).record_provider_validation_result(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=ATTEMPT_UUID,
            outcome=ProviderValidationOutcome.UNKNOWN,
            provider_result_digest=RESULT_DIGEST,
            safe_code="RESULT_UNKNOWN",
        )
    return claim, pending


def _submit_with_coordinator(control_database, *, target_binding_revision=1):
    with control_database.transaction() as session:
        return TenantProviderAccountBindingCoordinator(session).submit(
            provider_account_uuid=ACCOUNT_UUID,
            tenant_uuid=TENANT_UUID,
            integration_uuid=INTEGRATION_UUID,
            warehouse_uuid=WAREHOUSE_UUID,
            label="Main warehouse",
            account_secret=ACCOUNT_SECRET,
            root_key=ROOT_KEY,
            proof=_proof(),
            action_uuid=ACTION_UUID,
            request_digest=REQUEST_DIGEST,
            idempotency_key="provider-account-coordinator-1",
            reservation_expires_at=(
                datetime.now(timezone.utc) + timedelta(minutes=30)
            ),
            expected_account_row_version=None,
            expected_current_secret_revision_uuid=None,
            expected_current_global_claim_uuid=None,
            target_binding_revision=target_binding_revision,
            expected_warehouse_provider_account_uuid=None,
            expected_warehouse_binding_revision=None,
        )


def _activate_provider_account(control_database):
    claim = _reserve(control_database)
    pending = _create_pending(control_database, claim)
    _begin(control_database, pending.revision_uuid)
    with control_database.transaction() as session:
        TenantProviderAccountService(session).record_provider_validation_result(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=ATTEMPT_UUID,
            outcome=ProviderValidationOutcome.SUCCESS,
            provider_result_digest=RESULT_DIGEST,
            safe_code="VALID",
            proof=_proof(),
            owner=_owner(),
            binding_revision=1,
        )
    return pending


def test_historical_tracking_factory_resolves_both_exact_revisions_once(
    control_database,
):
    pending = _activate_provider_account(control_database)
    key_ring = RootKeyRing(
        active_version=ROOT_KEY.version,
        keys={ROOT_KEY.version: ROOT_KEY},
        statuses={ROOT_KEY.version: RootKeyLifecycle.ACTIVE},
    )
    item = SfTrackingQueryItem(
        shipment_uuid="80000000-0000-4000-8000-000000000001",
        waybill_no="SF-HISTORICAL-1",
    )

    with control_database.transaction() as session:
        integration = session.get(TenantIntegration, str(INTEGRATION_UUID))
        request = SfHistoricalTrackingCredentialFactory(session).prepare(
            tenant_uuid=TENANT_UUID,
            warehouse_uuid=WAREHOUSE_UUID,
            integration_uuid=INTEGRATION_UUID,
            provider_account_uuid=ACCOUNT_UUID,
            integration_secret_revision_uuid=(
                integration.current_secret_revision_id
            ),
            provider_account_secret_revision_uuid=pending.revision_uuid,
            binding_revision=1,
            phone_last4="9000",
            items=(item,),
            root_key_ring=key_ring,
        )

    assert request.context.historical is True
    assert request.context.provider_account_secret_revision_uuid == str(
        pending.revision_uuid
    )
    assert ACCOUNT_SECRET not in repr(request)
    assert "partner" not in repr(request)
    credentials, account_secret = request.take_credentials()
    assert dict(credentials) == {
        "partner_id": "partner",
        "checkword": "checkword",
    }
    assert account_secret == ACCOUNT_SECRET
    with pytest.raises(HistoricalTrackingCredentialError):
        request.take_credentials()


def test_historical_tracking_factory_never_falls_back_to_an_available_new_key(
    control_database,
):
    pending = _activate_provider_account(control_database)
    replacement_key = RootKey(version=2, material=b"b" * 32)
    replacement_only = RootKeyRing(
        active_version=2,
        keys={2: replacement_key},
        statuses={2: RootKeyLifecycle.ACTIVE},
    )

    with pytest.raises(HistoricalTrackingCredentialError):
        with control_database.transaction() as session:
            integration = session.get(TenantIntegration, str(INTEGRATION_UUID))
            SfHistoricalTrackingCredentialFactory(session).prepare(
                tenant_uuid=TENANT_UUID,
                warehouse_uuid=WAREHOUSE_UUID,
                integration_uuid=INTEGRATION_UUID,
                provider_account_uuid=ACCOUNT_UUID,
                integration_secret_revision_uuid=(
                    integration.current_secret_revision_id
                ),
                provider_account_secret_revision_uuid=pending.revision_uuid,
                binding_revision=1,
                phone_last4="9000",
                items=(
                    SfTrackingQueryItem(
                        shipment_uuid=(
                            "80000000-0000-4000-8000-000000000002"
                        ),
                        waybill_no="SF-HISTORICAL-2",
                    ),
                ),
                root_key_ring=replacement_only,
            )


def test_waybill_factory_builds_derived_identity_and_one_shot_exact_credentials(
    control_database,
):
    pending = _activate_provider_account(control_database)
    key_ring = RootKeyRing(
        active_version=ROOT_KEY.version,
        keys={ROOT_KEY.version: ROOT_KEY},
        statuses={ROOT_KEY.version: RootKeyLifecycle.ACTIVE},
    )
    shipment_uuid = UUID("80000000-0000-4000-8000-000000000002")
    with control_database.transaction() as session:
        integration = session.get(TenantIntegration, str(INTEGRATION_UUID))
        request = SfWaybillCredentialFactory(session).prepare_create(
            tenant_uuid=TENANT_UUID,
            warehouse_uuid=WAREHOUSE_UUID,
            integration_uuid=INTEGRATION_UUID,
            provider_account_uuid=ACCOUNT_UUID,
            integration_secret_revision_uuid=(
                integration.current_secret_revision_id
            ),
            provider_account_secret_revision_uuid=pending.revision_uuid,
            binding_revision=1,
            shipment_uuid=shipment_uuid,
            sender_snapshot={"contact": "sender-private"},
            receiver_snapshot={"contact": "receiver-private"},
            cargo_snapshot={
                "items": [{"name": "租赁设备", "count": 1}]
            },
            express_type_id=2,
            scheduled_dispatch_at=datetime(2026, 8, 23, 9),
            root_key_ring=key_ring,
        )

    assert request.provider_order_id == f"sf:{TENANT_UUID}:{shipment_uuid}"
    assert request.sender_snapshot == {"contact": "sender-private"}
    first_copy = dict(request.receiver_snapshot)
    first_copy["contact"] = "changed"
    assert request.receiver_snapshot == {"contact": "receiver-private"}
    rendered = repr(request)
    for private in (
        "sender-private",
        "receiver-private",
        "partner",
        "checkword",
        ACCOUNT_SECRET,
    ):
        assert private not in rendered
    credentials, account_secret = request.take_credentials()
    assert dict(credentials) == {
        "partner_id": "partner",
        "checkword": "checkword",
    }
    assert account_secret == ACCOUNT_SECRET
    with pytest.raises(SfWaybillCredentialError):
        request.take_credentials()


def test_waybill_factory_rejects_binding_fence_drift(control_database):
    pending = _activate_provider_account(control_database)
    key_ring = RootKeyRing(
        active_version=ROOT_KEY.version,
        keys={ROOT_KEY.version: ROOT_KEY},
        statuses={ROOT_KEY.version: RootKeyLifecycle.ACTIVE},
    )
    with control_database.transaction() as session:
        integration = session.get(TenantIntegration, str(INTEGRATION_UUID))
        with pytest.raises(SfWaybillCredentialError):
            SfWaybillCredentialFactory(session).prepare_create(
                tenant_uuid=TENANT_UUID,
                warehouse_uuid=WAREHOUSE_UUID,
                integration_uuid=INTEGRATION_UUID,
                provider_account_uuid=ACCOUNT_UUID,
                integration_secret_revision_uuid=(
                    integration.current_secret_revision_id
                ),
                provider_account_secret_revision_uuid=pending.revision_uuid,
                binding_revision=2,
                shipment_uuid="80000000-0000-4000-8000-000000000003",
                sender_snapshot={"contact": "sender-private"},
                receiver_snapshot={"contact": "receiver-private"},
                cargo_snapshot={
                    "items": [{"name": "租赁设备", "count": 1}]
                },
                express_type_id=2,
                scheduled_dispatch_at=datetime(2026, 8, 23, 9),
                root_key_ring=key_ring,
            )


def test_waybill_query_factory_omits_customer_snapshots_and_is_one_shot(
    control_database,
):
    pending = _activate_provider_account(control_database)
    key_ring = RootKeyRing(
        active_version=ROOT_KEY.version,
        keys={ROOT_KEY.version: ROOT_KEY},
        statuses={ROOT_KEY.version: RootKeyLifecycle.ACTIVE},
    )
    shipment_uuid = UUID("80000000-0000-4000-8000-000000000004")
    with control_database.transaction() as session:
        integration = session.get(TenantIntegration, str(INTEGRATION_UUID))
        request = SfWaybillCredentialFactory(session).prepare_query(
            tenant_uuid=TENANT_UUID,
            warehouse_uuid=WAREHOUSE_UUID,
            integration_uuid=INTEGRATION_UUID,
            provider_account_uuid=ACCOUNT_UUID,
            integration_secret_revision_uuid=(
                integration.current_secret_revision_id
            ),
            provider_account_secret_revision_uuid=pending.revision_uuid,
            binding_revision=1,
            shipment_uuid=shipment_uuid,
            root_key_ring=key_ring,
        )

    assert request.provider_order_id == f"sf:{TENANT_UUID}:{shipment_uuid}"
    rendered = repr(request)
    for private in ("partner", "checkword", ACCOUNT_SECRET):
        assert private not in rendered
    assert not hasattr(request, "sender_snapshot")
    assert not hasattr(request, "receiver_snapshot")
    credentials, account_secret = request.take_credentials()
    assert dict(credentials) == {
        "partner_id": "partner",
        "checkword": "checkword",
    }
    assert account_secret == ACCOUNT_SECRET
    with pytest.raises(SfWaybillCredentialError):
        request.take_credentials()


def test_binding_coordinator_reserves_and_replays_one_submission(control_database):
    first = _submit_with_coordinator(control_database)
    replay = _submit_with_coordinator(control_database)

    assert first.claim_was_reserved is True
    assert first.claim_generation == 2
    assert replay.claim_uuid == first.claim_uuid
    assert replay.revision.revision_uuid == first.revision.revision_uuid
    assert replay.idempotent_replay is True

    with pytest.raises(ProviderAccountIdempotencyConflictError):
        _submit_with_coordinator(control_database, target_binding_revision=2)


def test_current_account_revision_envelope_rotates_without_semantic_change(
    control_database,
):
    claim = _reserve(control_database)
    pending = _create_pending(control_database, claim)
    _begin(control_database, pending.revision_uuid)
    with control_database.transaction() as session:
        TenantProviderAccountService(session).record_provider_validation_result(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=ATTEMPT_UUID,
            outcome=ProviderValidationOutcome.SUCCESS,
            provider_result_digest=RESULT_DIGEST,
            safe_code="VALID",
            proof=_proof(),
            owner=_owner(),
            binding_revision=1,
        )
    next_key = RootKey(version=2, material=b"b" * 32)
    run_id = UUID("40000000-0000-4000-8000-000000000001")
    action_id = UUID("40000000-0000-4000-8000-000000000002")
    with control_database.transaction() as session:
        rotated = TenantProviderAccountEnvelopeService(
            session
        ).rewrap_exact_revision(
            revision_uuid=pending.revision_uuid,
            old_root_key=ROOT_KEY,
            new_root_key=next_key,
            rotation_run_uuid=run_id,
            rotation_action_uuid=action_id,
            idempotency_key="provider-account-envelope-rotation-1",
            expected_envelope_row_version=1,
        )
    with control_database.transaction() as session:
        replay = TenantProviderAccountEnvelopeService(
            session
        ).rewrap_exact_revision(
            revision_uuid=pending.revision_uuid,
            old_root_key=ROOT_KEY,
            new_root_key=next_key,
            rotation_run_uuid=run_id,
            rotation_action_uuid=action_id,
            idempotency_key="provider-account-envelope-rotation-1",
            expected_envelope_row_version=1,
        )
        revealed = TenantProviderAccountService(session).use_exact_revision(
            revision_uuid=pending.revision_uuid,
            root_key=next_key,
            consumer=lambda secret: secret._provider_value(),
        )

    assert rotated.envelope_generation == 2
    assert replay.event_uuid == rotated.event_uuid
    assert replay.idempotent_replay is True
    assert revealed == ACCOUNT_SECRET
    with control_database.new_session() as session:
        revision = session.get(
            TenantProviderAccountSecretRevision, pending.revision_uuid
        )
        event = session.get(
            TenantProviderAccountSecretEnvelopeEvent, rotated.event_uuid
        )
        assert revision.root_key_version == 2
        assert revision.envelope_generation == 2
        assert revision.last_envelope_rotation_event_id == event.id
        assert event.before_ciphertext_digest != event.after_ciphertext_digest
    with control_database.transaction() as session:
        with pytest.raises(ProviderAccountCredentialAuthenticationError):
            TenantProviderAccountService(session).use_exact_revision(
                revision_uuid=pending.revision_uuid,
                root_key=ROOT_KEY,
                consumer=lambda secret: secret._provider_value(),
            )


def test_pending_revision_is_idempotent_encrypted_and_safe(control_database):
    claim = _reserve(control_database)
    first = _create_pending(control_database, claim)
    replay = _create_pending(control_database, claim)

    assert replay.revision_uuid == first.revision_uuid
    assert replay.idempotent_replay is True
    assert ACCOUNT_SECRET not in repr(first)
    assert set(asdict(first)).isdisjoint(
        {"account_secret_ciphertext", "account_secret_nonce", "account_secret"}
    )
    with control_database.new_session() as session:
        account = session.get(TenantProviderAccount, str(ACCOUNT_UUID))
        revision = session.get(
            TenantProviderAccountSecretRevision, first.revision_uuid
        )
        integration = session.get(TenantIntegration, str(INTEGRATION_UUID))
        assert account.masked_hint == "****7890"
        assert account.current_secret_revision_id is None
        assert revision.account_secret_ciphertext != ACCOUNT_SECRET.encode("ascii")
        assert revision.validation_integration_secret_revision_id == (
            integration.current_secret_revision_id
        )
        assert revision.expected_claim_generation == claim.generation

    with pytest.raises(ProviderAccountIdempotencyConflictError):
        _create_pending(control_database, claim, secret="009999999999")


def test_success_activates_claim_account_and_exact_revision_atomically(
    control_database,
):
    claim = _reserve(control_database)
    pending = _create_pending(control_database, claim)
    started = _begin(control_database, pending.revision_uuid)
    with control_database.transaction() as session:
        observed = TenantProviderAccountService(
            session
        ).use_pending_revision_for_validation(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=ATTEMPT_UUID,
            root_key=ROOT_KEY,
            consumer=lambda secret: (secret._provider_value(), secret.masked_hint),
        )
    with control_database.transaction() as session:
        current = TenantProviderAccountService(
            session
        ).record_provider_validation_result(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=ATTEMPT_UUID,
            outcome=ProviderValidationOutcome.SUCCESS,
            provider_result_digest=RESULT_DIGEST,
            safe_code="VALID",
            proof=_proof(),
            owner=_owner(),
            binding_revision=1,
        )

    assert started.verification_status == "submitting"
    assert observed == (ACCOUNT_SECRET, "****7890")
    assert current.status == "current"
    assert current.activated_claim_generation == claim.generation + 1
    with control_database.new_session() as session:
        account = session.get(TenantProviderAccount, str(ACCOUNT_UUID))
        claim_row = session.get(ProviderAccountClaim, str(claim.claim_uuid))
        assert account.status == "active"
        assert account.current_secret_revision_id == current.revision_uuid
        assert account.current_global_claim_id == str(claim.claim_uuid)
        assert account.current_claim_generation == claim_row.claim_generation
        assert claim_row.claim_status == "active"
        assert claim_row.active_binding_revision == 1

    with control_database.transaction() as session:
        historical = TenantProviderAccountService(session).use_exact_revision(
            revision_uuid=current.revision_uuid,
            root_key=ROOT_KEY,
            consumer=lambda secret: secret._provider_value(),
        )
    assert historical == ACCOUNT_SECRET


def test_integration_pointer_drift_blocks_claim_and_account_activation(
    control_database,
):
    claim = _reserve(control_database)
    pending = _create_pending(control_database, claim)
    _begin(control_database, pending.revision_uuid)
    with control_database.transaction() as session:
        session.execute(
            sa.update(TenantIntegration)
            .where(TenantIntegration.id == str(INTEGRATION_UUID))
            .values(row_version=TenantIntegration.row_version + 1)
        )

    with pytest.raises(ProviderAccountStateConflictError):
        with control_database.transaction() as session:
            TenantProviderAccountService(session).record_provider_validation_result(
                revision_uuid=pending.revision_uuid,
                attempt_uuid=ATTEMPT_UUID,
                outcome=ProviderValidationOutcome.SUCCESS,
                provider_result_digest=RESULT_DIGEST,
                safe_code="VALID",
                proof=_proof(),
                owner=_owner(),
                binding_revision=1,
            )

    with control_database.new_session() as session:
        account = session.get(TenantProviderAccount, str(ACCOUNT_UUID))
        claim_row = session.get(ProviderAccountClaim, str(claim.claim_uuid))
        revision = session.get(
            TenantProviderAccountSecretRevision, pending.revision_uuid
        )
        assert account.status == "pending"
        assert account.current_secret_revision_id is None
        assert claim_row.claim_status == "reserved"
        assert revision.verification_status == "submitting"


def test_revalidation_of_same_active_claim_supersedes_revision_without_new_claim_event(
    control_database,
):
    claim = _reserve(control_database)
    first_pending = _create_pending(control_database, claim)
    _begin(control_database, first_pending.revision_uuid)
    with control_database.transaction() as session:
        first = TenantProviderAccountService(session).record_provider_validation_result(
            revision_uuid=first_pending.revision_uuid,
            attempt_uuid=ATTEMPT_UUID,
            outcome=ProviderValidationOutcome.SUCCESS,
            provider_result_digest=RESULT_DIGEST,
            safe_code="VALID",
            proof=_proof(),
            owner=_owner(),
            binding_revision=1,
        )
    with control_database.new_session() as session:
        account = session.get(TenantProviderAccount, str(ACCOUNT_UUID))
        active_claim = session.get(ProviderAccountClaim, str(claim.claim_uuid))
        account_row_version = account.row_version
        claim_generation = active_claim.claim_generation
        claim_row_version = active_claim.row_version
        claim_event_sequence = active_claim.event_sequence

    next_action = UUID("30000000-0000-4000-8000-000000000001")
    next_attempt = UUID("30000000-0000-4000-8000-000000000002")
    next_digest = hashlib.sha256(b"same-claim-revalidation").digest()
    next_proof = SfAdminClaimProof(
        tenant_uuid=TENANT_UUID,
        actor_user_uuid=USER_UUID,
        actor_session_uuid=SESSION_UUID,
        role=TenantRole.ADMIN,
        effective_gate=EffectiveTenantGate.ACTIVE,
        tenant_access_version=1,
        otp_challenge_uuid=UUID("30000000-0000-4000-8000-000000000003"),
        otp_purpose="sf_account_rebind",
        otp_action_uuid=next_action,
        otp_request_digest=next_digest,
        otp_consumed=True,
    )
    with control_database.transaction() as session:
        second_pending = TenantProviderAccountService(
            session
        ).create_pending_revision(
            provider_account_uuid=ACCOUNT_UUID,
            tenant_uuid=TENANT_UUID,
            integration_uuid=INTEGRATION_UUID,
            warehouse_uuid=WAREHOUSE_UUID,
            label="Main warehouse",
            account_secret=ACCOUNT_SECRET,
            root_key=ROOT_KEY,
            claim_uuid=claim.claim_uuid,
            expected_claim_generation=claim_generation,
            expected_claim_row_version=claim_row_version,
            target_binding_revision=1,
            expected_warehouse_provider_account_uuid=ACCOUNT_UUID,
            expected_warehouse_binding_revision=1,
            created_by_user_uuid=USER_UUID,
            action_uuid=next_action,
            request_digest=next_digest,
            idempotency_key="provider-account-revision-2",
            expected_account_row_version=account_row_version,
            expected_current_secret_revision_uuid=first.revision_uuid,
            expected_current_global_claim_uuid=claim.claim_uuid,
        )
    with control_database.transaction() as session:
        TenantProviderAccountService(session).begin_provider_validation(
            revision_uuid=second_pending.revision_uuid,
            attempt_uuid=next_attempt,
            expected_revision_row_version=1,
        )
    with control_database.transaction() as session:
        second = TenantProviderAccountService(session).record_provider_validation_result(
            revision_uuid=second_pending.revision_uuid,
            attempt_uuid=next_attempt,
            outcome=ProviderValidationOutcome.SUCCESS,
            provider_result_digest=hashlib.sha256(b"second-valid").digest(),
            safe_code="VALID",
            proof=next_proof,
            owner=_owner(),
            binding_revision=1,
        )

    assert second.activated_claim_generation == claim_generation
    with control_database.new_session() as session:
        previous = session.get(
            TenantProviderAccountSecretRevision, first.revision_uuid
        )
        account = session.get(TenantProviderAccount, str(ACCOUNT_UUID))
        unchanged_claim = session.get(ProviderAccountClaim, str(claim.claim_uuid))
        assert previous.status == "superseded"
        assert account.current_secret_revision_id == second.revision_uuid
        assert unchanged_claim.claim_generation == claim_generation
        assert unchanged_claim.event_sequence == claim_event_sequence


def test_current_resolver_freezes_exact_ids_and_history_ignores_released_claim(
    control_database,
):
    claim = _reserve(control_database)
    pending = _create_pending(control_database, claim)
    _begin(control_database, pending.revision_uuid)
    with control_database.transaction() as session:
        TenantProviderAccountService(session).record_provider_validation_result(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=ATTEMPT_UUID,
            outcome=ProviderValidationOutcome.SUCCESS,
            provider_result_digest=RESULT_DIGEST,
            safe_code="VALID",
            proof=_proof(),
            owner=_owner(),
            binding_revision=1,
        )
    with control_database.transaction() as session:
        current = SfProviderContextResolver(session).resolve_current(
            tenant_uuid=TENANT_UUID,
            warehouse_uuid=WAREHOUSE_UUID,
            provider_account_uuid=ACCOUNT_UUID,
            binding_revision=1,
        )

    assert current.provider_account_secret_revision_uuid == pending.revision_uuid
    assert current.claim_generation == claim.generation + 1
    with pytest.raises(ProviderContextError):
        with control_database.transaction() as session:
            SfProviderContextResolver(session).resolve_current(
                tenant_uuid=TENANT_UUID,
                warehouse_uuid=WAREHOUSE_UUID,
                provider_account_uuid=ACCOUNT_UUID,
                binding_revision=2,
            )

    unbind_action = UUID("40000000-0000-4000-8000-000000000001")
    unbind_digest = hashlib.sha256(b"unbind").digest()
    unbind_proof = SfAdminClaimProof(
        tenant_uuid=TENANT_UUID,
        actor_user_uuid=USER_UUID,
        actor_session_uuid=SESSION_UUID,
        role=TenantRole.ADMIN,
        effective_gate=EffectiveTenantGate.ACTIVE,
        tenant_access_version=1,
        otp_challenge_uuid=UUID("40000000-0000-4000-8000-000000000002"),
        otp_purpose="sf_account_unbind",
        otp_action_uuid=unbind_action,
        otp_request_digest=unbind_digest,
        otp_consumed=True,
    )
    with control_database.new_session() as session:
        active_claim = session.get(ProviderAccountClaim, str(claim.claim_uuid))
        active_generation = active_claim.claim_generation
        active_row_version = active_claim.row_version
    with control_database.transaction() as session:
        released_account = TenantProviderAccountService(
            session
        ).release_current_claim(
            provider_account_uuid=ACCOUNT_UUID,
            warehouse_uuid=WAREHOUSE_UUID,
            proof=unbind_proof,
            action_uuid=unbind_action,
            request_digest=unbind_digest,
            expected_account_row_version=2,
            expected_claim_generation=active_generation,
            expected_claim_row_version=active_row_version,
        )
    assert released_account.status == "inactive"
    with control_database.transaction() as session:
        replay = TenantProviderAccountService(session).release_current_claim(
            provider_account_uuid=ACCOUNT_UUID,
            warehouse_uuid=WAREHOUSE_UUID,
            proof=unbind_proof,
            action_uuid=unbind_action,
            request_digest=unbind_digest,
            expected_account_row_version=2,
            expected_claim_generation=active_generation,
            expected_claim_row_version=active_row_version,
        )
    assert replay.idempotent_replay is True
    with pytest.raises(ProviderContextError):
        with control_database.transaction() as session:
            SfProviderContextResolver(session).resolve_current(
                tenant_uuid=TENANT_UUID,
                warehouse_uuid=WAREHOUSE_UUID,
                provider_account_uuid=ACCOUNT_UUID,
                binding_revision=1,
            )
    with control_database.transaction() as session:
        historical = SfProviderContextResolver(session).resolve_historical(
            tenant_uuid=TENANT_UUID,
            warehouse_uuid=WAREHOUSE_UUID,
            binding_revision=1,
            integration_secret_revision_uuid=(
                current.integration_secret_revision_uuid
            ),
            provider_account_secret_revision_uuid=(
                current.provider_account_secret_revision_uuid
            ),
        )
    assert historical.historical is True
    assert historical.global_claim_uuid == current.global_claim_uuid


@pytest.mark.parametrize(
    "gate",
    [EffectiveTenantGate.EXPIRED, EffectiveTenantGate.SUSPENDED],
)
def test_expired_or_suspended_unbind_rolls_back_claim_and_account(
    control_database,
    gate,
):
    claim = _reserve(control_database)
    pending = _create_pending(control_database, claim)
    _begin(control_database, pending.revision_uuid)
    with control_database.transaction() as session:
        TenantProviderAccountService(session).record_provider_validation_result(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=ATTEMPT_UUID,
            outcome=ProviderValidationOutcome.SUCCESS,
            provider_result_digest=RESULT_DIGEST,
            safe_code="VALID",
            proof=_proof(),
            owner=_owner(),
            binding_revision=1,
        )
    with control_database.new_session() as session:
        account = session.get(TenantProviderAccount, str(ACCOUNT_UUID))
        active_claim = session.get(ProviderAccountClaim, str(claim.claim_uuid))
        account_row_version = account.row_version
        claim_generation = active_claim.claim_generation
        claim_row_version = active_claim.row_version
    action = UUID("50000000-0000-4000-8000-000000000001")
    digest = hashlib.sha256(b"blocked-unbind").digest()
    blocked_proof = SfAdminClaimProof(
        tenant_uuid=TENANT_UUID,
        actor_user_uuid=USER_UUID,
        actor_session_uuid=SESSION_UUID,
        role=TenantRole.ADMIN,
        effective_gate=gate,
        tenant_access_version=1,
        otp_challenge_uuid=UUID("50000000-0000-4000-8000-000000000002"),
        otp_purpose="sf_account_unbind",
        otp_action_uuid=action,
        otp_request_digest=digest,
        otp_consumed=True,
    )

    with pytest.raises(SfClaimAuthorityDenied):
        with control_database.transaction() as session:
            TenantProviderAccountService(session).release_current_claim(
                provider_account_uuid=ACCOUNT_UUID,
                warehouse_uuid=WAREHOUSE_UUID,
                proof=blocked_proof,
                action_uuid=action,
                request_digest=digest,
                expected_account_row_version=account_row_version,
                expected_claim_generation=claim_generation,
                expected_claim_row_version=claim_row_version,
            )

    with control_database.new_session() as session:
        account = session.get(TenantProviderAccount, str(ACCOUNT_UUID))
        unchanged_claim = session.get(ProviderAccountClaim, str(claim.claim_uuid))
        assert account.status == "active"
        assert account.current_global_claim_id == str(claim.claim_uuid)
        assert unchanged_claim.claim_status == "active"
        assert unchanged_claim.claim_generation == claim_generation


@pytest.mark.parametrize(
    ("outcome", "expected_verification", "expected_account_status"),
    [
        (ProviderValidationOutcome.DEFINITIVE_FAILURE, "failed", "verification_failed"),
        (ProviderValidationOutcome.UNKNOWN, "unknown", "pending"),
    ],
)
def test_non_success_never_switches_current_pointer(
    control_database,
    outcome,
    expected_verification,
    expected_account_status,
):
    claim = _reserve(control_database)
    pending = _create_pending(control_database, claim)
    _begin(control_database, pending.revision_uuid)
    with control_database.transaction() as session:
        result = TenantProviderAccountService(
            session
        ).record_provider_validation_result(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=ATTEMPT_UUID,
            outcome=outcome,
            provider_result_digest=RESULT_DIGEST,
            safe_code="NOT_CONFIRMED",
        )

    assert result.verification_status == expected_verification
    assert result.requires_reconciliation is (
        outcome is ProviderValidationOutcome.UNKNOWN
    )
    with control_database.new_session() as session:
        account = session.get(TenantProviderAccount, str(ACCOUNT_UUID))
        claim_row = session.get(ProviderAccountClaim, str(claim.claim_uuid))
        assert account.status == expected_account_status
        assert account.current_secret_revision_id is None
        assert claim_row.claim_status == "reserved"


def test_unknown_reconciliation_can_remain_quarantined_and_replay(
    control_database,
):
    claim, pending = _record_unknown(control_database)
    updated_digest = hashlib.sha256(b"provider-result-still-unknown").digest()

    with control_database.transaction() as session:
        observed = TenantProviderAccountService(
            session
        ).use_unknown_revision_for_reconciliation(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=ATTEMPT_UUID,
            root_key=ROOT_KEY,
            consumer=lambda secret: secret._provider_value(),
        )
    with control_database.transaction() as session:
        updated = TenantProviderAccountService(
            session
        ).reconcile_unknown_validation(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=ATTEMPT_UUID,
            resolution=ProviderValidationReconciliation.STILL_UNKNOWN,
            provider_result_digest=updated_digest,
            safe_code="STILL_UNKNOWN",
        )
    with control_database.transaction() as session:
        replay = TenantProviderAccountService(
            session
        ).reconcile_unknown_validation(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=ATTEMPT_UUID,
            resolution=ProviderValidationReconciliation.STILL_UNKNOWN,
            provider_result_digest=updated_digest,
            safe_code="STILL_UNKNOWN",
        )

    assert observed == ACCOUNT_SECRET
    assert updated.verification_status == "unknown"
    assert updated.requires_reconciliation is True
    assert replay.idempotent_replay is True
    with control_database.new_session() as session:
        account = session.get(TenantProviderAccount, str(ACCOUNT_UUID))
        claim_row = session.get(ProviderAccountClaim, str(claim.claim_uuid))
        assert account.status == "pending"
        assert account.current_secret_revision_id is None
        assert claim_row.claim_status == "reserved"


@pytest.mark.parametrize(
    ("resolution", "revision_status", "account_status", "claim_status"),
    [
        (
            ProviderValidationReconciliation.CONFIRMED_SUCCESS,
            "current",
            "active",
            "active",
        ),
        (
            ProviderValidationReconciliation.CONFIRMED_FAILURE,
            "revoked",
            "verification_failed",
            "reserved",
        ),
    ],
)
def test_unknown_reconciliation_reaches_one_explicit_terminal_result(
    control_database,
    resolution,
    revision_status,
    account_status,
    claim_status,
):
    claim, pending = _record_unknown(control_database)
    reconciled_digest = hashlib.sha256(b"provider-result-reconciled").digest()

    with control_database.transaction() as session:
        result = TenantProviderAccountService(
            session
        ).reconcile_unknown_validation(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=ATTEMPT_UUID,
            resolution=resolution,
            provider_result_digest=reconciled_digest,
            safe_code="RECONCILED",
            proof=_proof(),
            owner=_owner(),
            binding_revision=1,
        )

    assert result.status == revision_status
    assert result.requires_reconciliation is False
    with control_database.new_session() as session:
        account = session.get(TenantProviderAccount, str(ACCOUNT_UUID))
        claim_row = session.get(ProviderAccountClaim, str(claim.claim_uuid))
        assert account.status == account_status
        assert claim_row.claim_status == claim_status
        assert account.current_secret_revision_id == (
            result.revision_uuid if account_status == "active" else None
        )

    with pytest.raises(ProviderAccountStateConflictError):
        with control_database.transaction() as session:
            TenantProviderAccountService(session).reconcile_unknown_validation(
                revision_uuid=pending.revision_uuid,
                attempt_uuid=ATTEMPT_UUID,
                resolution=resolution,
                provider_result_digest=reconciled_digest,
                safe_code="RECONCILED",
                proof=_proof(),
                owner=_owner(),
                binding_revision=1,
            )


def test_service_requires_explicit_transaction(control_database):
    with control_database.new_session() as session:
        with pytest.raises(ProviderAccountTransactionError):
            TenantProviderAccountService(session).begin_provider_validation(
                revision_uuid=UUID("20000000-0000-4000-8000-000000000001"),
                attempt_uuid=ATTEMPT_UUID,
                expected_revision_row_version=1,
            )
