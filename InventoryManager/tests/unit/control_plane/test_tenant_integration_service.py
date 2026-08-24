from __future__ import annotations

import hashlib
from dataclasses import asdict
from uuid import UUID

import pytest
import sqlalchemy as sa

from inventory_control import ControlBase, ControlDatabase
from inventory_control.crypto import RootKey
from inventory_control.integrations import (
    IntegrationCredentialAuthenticationError,
    IntegrationIdempotencyConflictError,
    IntegrationStateConflictError,
    IntegrationTransactionRequiredError,
    IntegrationValidationUnknownError,
    ProviderValidationOutcome,
    ProviderValidationReconciliation,
    TenantIntegrationService,
)
from inventory_control.models import (
    Tenant,
    TenantIntegration,
    TenantIntegrationSecretEnvelopeEvent,
    TenantIntegrationSecretRevision,
)


TENANT_UUID = UUID("50000000-0000-4000-8000-000000000001")
INTEGRATION_UUID = UUID("50000000-0000-4000-8000-000000000002")
USER_UUID = UUID("50000000-0000-4000-8000-000000000003")
ROOT_KEY_V1 = RootKey(version=1, material=b"a" * 32)
ROOT_KEY_V2 = RootKey(version=2, material=b"b" * 32)
RESULT_OK = hashlib.sha256(b"provider-ok").digest()
RESULT_FAILED = hashlib.sha256(b"provider-failed").digest()
RESULT_UNKNOWN = hashlib.sha256(b"provider-unknown").digest()


@pytest.fixture
def control_database(mysql_control_database):
    with mysql_control_database.transaction() as session:
        session.add(Tenant(id=str(TENANT_UUID), status="active"))
    with mysql_control_database.transaction() as session:
        TenantIntegrationService(session).create_integration(
            integration_uuid=INTEGRATION_UUID,
            tenant_uuid=TENANT_UUID,
            provider="sf",
            name="main-sf",
            config={"region": "cn"},
        )
    return mysql_control_database


def _create_pending(
    database,
    *,
    ordinal: int,
    expected_row: int,
    expected_current: str | None,
    idempotency_key: str | None = None,
    secret: str | None = None,
):
    with database.transaction() as session:
        return TenantIntegrationService(session).create_pending_revision(
            integration_uuid=INTEGRATION_UUID,
            credentials={
                "partner_id": f"partner-{ordinal}",
                "checkword": secret or f"secret-{ordinal}",
            },
            root_key=ROOT_KEY_V1,
            created_by_user_uuid=USER_UUID,
            action_uuid=UUID(f"50000000-0000-4000-8000-{ordinal:012d}"),
            idempotency_key=idempotency_key or f"sf-revision:{ordinal}",
            expected_integration_row_version=expected_row,
            expected_current_secret_revision_uuid=expected_current,
        )


def _begin(database, revision_uuid: str, ordinal: int):
    attempt = UUID(f"51000000-0000-4000-8000-{ordinal:012d}")
    with database.transaction() as session:
        result = TenantIntegrationService(session).begin_provider_validation(
            revision_uuid=revision_uuid,
            attempt_uuid=attempt,
            expected_revision_row_version=1,
        )
    return attempt, result


def _result(database, revision_uuid, attempt, outcome, digest, code):
    with database.transaction() as session:
        return TenantIntegrationService(session).record_provider_validation_result(
            revision_uuid=revision_uuid,
            attempt_uuid=attempt,
            outcome=outcome,
            provider_result_digest=digest,
            safe_code=code,
        )


def _activate_first(database):
    pending = _create_pending(
        database, ordinal=1, expected_row=1, expected_current=None
    )
    attempt, _ = _begin(database, pending.revision_uuid, 1)
    current = _result(
        database,
        pending.revision_uuid,
        attempt,
        ProviderValidationOutcome.SUCCESS,
        RESULT_OK,
        "VALID",
    )
    return current


def test_requires_explicit_caller_transaction(control_database):
    with control_database.new_session() as session:
        with pytest.raises(IntegrationTransactionRequiredError):
            TenantIntegrationService(session).create_integration(
                integration_uuid=UUID("50000000-0000-4000-8000-000000000099"),
                tenant_uuid=TENANT_UUID,
                provider="sf",
                name="blocked",
            )


def test_pending_revision_is_stable_idempotent_and_does_not_overwrite(control_database):
    first = _create_pending(
        control_database,
        ordinal=1,
        expected_row=1,
        expected_current=None,
        secret="credential-never-in-dto",
    )
    replay = _create_pending(
        control_database,
        ordinal=1,
        expected_row=1,
        expected_current=None,
        secret="credential-never-in-dto",
    )

    assert replay.revision_uuid == first.revision_uuid
    assert replay.idempotent_replay is True
    assert "credential-never-in-dto" not in repr(first)
    assert set(asdict(first)).isdisjoint(
        {"credentials_ciphertext", "credentials_nonce", "secret"}
    )
    with pytest.raises(IntegrationIdempotencyConflictError):
        _create_pending(
            control_database,
            ordinal=1,
            expected_row=1,
            expected_current=None,
            secret="different-secret",
        )
    with control_database.new_session() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(TenantIntegrationSecretRevision)
        ) == 1


def test_success_cas_supersedes_previous_and_exact_history_never_falls_forward(
    control_database,
):
    first = _activate_first(control_database)
    with control_database.new_session() as session:
        first_ciphertext = bytes(
            session.get(TenantIntegrationSecretRevision, first.revision_uuid)
            .credentials_ciphertext
        )
    second = _create_pending(
        control_database,
        ordinal=2,
        expected_row=3,
        expected_current=first.revision_uuid,
    )
    second_attempt, _ = _begin(control_database, second.revision_uuid, 2)
    second = _result(
        control_database,
        second.revision_uuid,
        second_attempt,
        ProviderValidationOutcome.SUCCESS,
        RESULT_OK,
        "VALID",
    )

    with control_database.transaction() as session:
        service = TenantIntegrationService(session)
        old_partner = service.use_exact_revision(
            revision_uuid=first.revision_uuid,
            root_key=ROOT_KEY_V1,
            consumer=lambda bundle: bundle._provider_values()["partner_id"],
        )
        new_partner = service.use_exact_revision(
            revision_uuid=second.revision_uuid,
            root_key=ROOT_KEY_V1,
            consumer=lambda bundle: bundle._provider_values()["partner_id"],
        )
        integration = session.get(TenantIntegration, str(INTEGRATION_UUID))
        old = session.get(TenantIntegrationSecretRevision, first.revision_uuid)
        assert old_partner == "partner-1"
        assert new_partner == "partner-2"
        assert old.status == "superseded"
        assert bytes(old.credentials_ciphertext) == first_ciphertext
        assert integration.current_secret_revision_id == second.revision_uuid
        assert session.scalar(
            sa.select(sa.func.count())
            .select_from(TenantIntegrationSecretRevision)
            .where(TenantIntegrationSecretRevision.status == "current")
        ) == 1


def test_failed_revision_keeps_working_current_and_old_ciphertext(control_database):
    first = _activate_first(control_database)
    with control_database.new_session() as session:
        before = bytes(
            session.get(TenantIntegrationSecretRevision, first.revision_uuid)
            .credentials_ciphertext
        )
    second = _create_pending(
        control_database,
        ordinal=2,
        expected_row=3,
        expected_current=first.revision_uuid,
    )
    attempt, _ = _begin(control_database, second.revision_uuid, 2)
    failed = _result(
        control_database,
        second.revision_uuid,
        attempt,
        ProviderValidationOutcome.DEFINITIVE_FAILURE,
        RESULT_FAILED,
        "AUTH_REJECTED",
    )

    with control_database.new_session() as session:
        integration = session.get(TenantIntegration, str(INTEGRATION_UUID))
        old = session.get(TenantIntegrationSecretRevision, first.revision_uuid)
        assert failed.status == "revoked"
        assert integration.current_secret_revision_id == first.revision_uuid
        assert integration.status == "active"
        assert old.status == "current"
        assert bytes(old.credentials_ciphertext) == before


def test_unknown_blocks_blind_resubmit_until_explicit_reconciliation(control_database):
    pending = _create_pending(
        control_database, ordinal=1, expected_row=1, expected_current=None
    )
    attempt, _ = _begin(control_database, pending.revision_uuid, 1)
    unknown = _result(
        control_database,
        pending.revision_uuid,
        attempt,
        ProviderValidationOutcome.UNKNOWN,
        RESULT_UNKNOWN,
        "TIMEOUT",
    )
    assert unknown.requires_reconciliation is True

    with control_database.transaction() as session:
        service = TenantIntegrationService(session)
        with pytest.raises(IntegrationValidationUnknownError):
            service.begin_provider_validation(
                revision_uuid=pending.revision_uuid,
                attempt_uuid=UUID("51000000-0000-4000-8000-000000000002"),
                expected_revision_row_version=3,
            )
        integration = session.get(TenantIntegration, str(INTEGRATION_UUID))
        assert integration.current_secret_revision_id is None

    with control_database.transaction() as session:
        reconciled = TenantIntegrationService(session).reconcile_unknown_validation(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=attempt,
            resolution=ProviderValidationReconciliation.CONFIRMED_SUCCESS,
            provider_result_digest=RESULT_OK,
            safe_code="RECONCILED_VALID",
        )
        assert reconciled.status == "current"
        assert reconciled.verification_status == "succeeded"


def test_stale_expected_pointer_rejects_success_and_caller_rollback_is_atomic(
    control_database,
):
    pending = _create_pending(
        control_database, ordinal=1, expected_row=1, expected_current=None
    )
    attempt, _ = _begin(control_database, pending.revision_uuid, 1)
    with control_database.transaction() as session:
        integration = session.get(TenantIntegration, str(INTEGRATION_UUID))
        integration.row_version += 1

    with pytest.raises(IntegrationStateConflictError):
        with control_database.transaction() as session:
            TenantIntegrationService(session).record_provider_validation_result(
                revision_uuid=pending.revision_uuid,
                attempt_uuid=attempt,
                outcome=ProviderValidationOutcome.SUCCESS,
                provider_result_digest=RESULT_OK,
                safe_code="VALID",
            )
    with control_database.new_session() as session:
        revision = session.get(
            TenantIntegrationSecretRevision, pending.revision_uuid
        )
        assert revision.status == "pending_validation"
        assert revision.verification_status == "submitting"


def test_definitive_failure_is_recorded_even_when_current_snapshot_drifted(
    control_database,
):
    pending = _create_pending(
        control_database, ordinal=1, expected_row=1, expected_current=None
    )
    attempt, _ = _begin(control_database, pending.revision_uuid, 1)
    with control_database.transaction() as session:
        integration = session.get(TenantIntegration, str(INTEGRATION_UUID))
        integration.row_version += 1

    failed = _result(
        control_database,
        pending.revision_uuid,
        attempt,
        ProviderValidationOutcome.DEFINITIVE_FAILURE,
        RESULT_FAILED,
        "AUTH_REJECTED",
    )

    assert failed.status == "revoked"
    assert failed.verification_status == "failed"


def test_rewrap_preserves_business_revision_appends_event_and_is_idempotent(
    control_database,
):
    current = _activate_first(control_database)
    with control_database.new_session() as session:
        before = session.get(
            TenantIntegrationSecretRevision, current.revision_uuid
        )
        before_facts = (
            before.id,
            before.revision_no,
            before.status,
            bytes(before.canonical_semantics_digest),
            bytes(before.credentials_ciphertext),
            bytes(before.credentials_nonce),
        )
    kwargs = {
        "revision_uuid": current.revision_uuid,
        "old_root_key": ROOT_KEY_V1,
        "new_root_key": ROOT_KEY_V2,
        "rotation_run_uuid": UUID("52000000-0000-4000-8000-000000000001"),
        "rotation_action_uuid": UUID("52000000-0000-4000-8000-000000000002"),
        "idempotency_key": "root-rotation:2:revision-1",
        "expected_envelope_row_version": 1,
    }
    with control_database.transaction() as session:
        first = TenantIntegrationService(session).rewrap_exact_revision_envelope(
            **kwargs
        )
    with control_database.transaction() as session:
        replay = TenantIntegrationService(session).rewrap_exact_revision_envelope(
            **kwargs
        )
    assert replay.event_uuid == first.event_uuid
    assert replay.idempotent_replay is True

    with control_database.transaction() as session:
        service = TenantIntegrationService(session)
        assert service.use_exact_revision(
            revision_uuid=current.revision_uuid,
            root_key=ROOT_KEY_V2,
            consumer=lambda bundle: bundle._provider_values()["partner_id"],
        ) == "partner-1"
        with pytest.raises(IntegrationCredentialAuthenticationError):
            service.use_exact_revision(
                revision_uuid=current.revision_uuid,
                root_key=ROOT_KEY_V1,
                consumer=lambda bundle: None,
            )
        after = session.get(
            TenantIntegrationSecretRevision, current.revision_uuid
        )
        assert (after.id, after.revision_no, after.status) == before_facts[:3]
        assert bytes(after.canonical_semantics_digest) == before_facts[3]
        assert bytes(after.credentials_ciphertext) != before_facts[4]
        assert bytes(after.credentials_nonce) != before_facts[5]
        assert after.envelope_generation == 2
        assert after.envelope_row_version == 2
        assert session.scalar(
            sa.select(sa.func.count()).select_from(
                TenantIntegrationSecretEnvelopeEvent
            )
        ) == 1


def test_tampered_historical_revision_never_falls_back_to_current(control_database):
    first = _activate_first(control_database)
    second = _create_pending(
        control_database,
        ordinal=2,
        expected_row=3,
        expected_current=first.revision_uuid,
    )
    attempt, _ = _begin(control_database, second.revision_uuid, 2)
    _result(
        control_database,
        second.revision_uuid,
        attempt,
        ProviderValidationOutcome.SUCCESS,
        RESULT_OK,
        "VALID",
    )
    with control_database.transaction() as session:
        old = session.get(TenantIntegrationSecretRevision, first.revision_uuid)
        tampered = bytearray(old.credentials_ciphertext)
        tampered[-1] ^= 1
        old.credentials_ciphertext = bytes(tampered)
    with control_database.transaction() as session:
        with pytest.raises(IntegrationCredentialAuthenticationError):
            TenantIntegrationService(session).use_exact_revision(
                revision_uuid=first.revision_uuid,
                root_key=ROOT_KEY_V1,
                consumer=lambda bundle: bundle._provider_values()["partner_id"],
            )


def test_provider_default_is_only_an_active_new_account_selector(control_database):
    current = _activate_first(control_database)
    with control_database.transaction() as session:
        service = TenantIntegrationService(session)
        created = service.set_default_for_new_accounts(
            tenant_uuid=TENANT_UUID,
            provider="sf",
            integration_uuid=INTEGRATION_UUID,
            updated_by_user_uuid=USER_UUID,
            expected_row_version=None,
        )
        resolved = service.resolve_default_for_new_account(
            tenant_uuid=TENANT_UUID, provider="sf"
        )
        assert resolved.integration_uuid == created.integration_uuid
        assert resolved.integration_uuid == current.integration_uuid
