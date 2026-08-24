from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from app.services.tenant_integrations import (
    CredentialValidationDecision,
    CredentialValidationResult,
    INTEGRATION_REVISION_SOURCE_TYPE,
    INTEGRATION_VALIDATION_EVENT_TYPE,
    TenantIntegrationCredentialValidationHandler,
    TenantIntegrationOutboxAuthority,
)
from inventory_control import (
    ControlBase,
    ControlDatabase,
    PlatformRootKeyVersion,
    TenantDatabase,
)
from inventory_control.crypto import RootKey
from inventory_control.integrations import TenantIntegrationService
from inventory_control.jobs import (
    ControlJobService,
    ControlOutboxService,
    ControlTenantGateReader,
    DurableOrdinaryOutboxWorker,
    OutboxAuthorityVerdict,
)
from inventory_control.models import (
    ControlOutboxEvent,
    Tenant,
    TenantIntegration,
    TenantIntegrationSecretRevision,
)
from inventory_control.models.subscriptions import PlanRevision, Subscription


NOW = datetime(2026, 8, 23, 3, 0, tzinfo=timezone.utc)
TENANT_ID = UUID("6b000000-0000-4000-8000-000000000001")
INTEGRATION_ID = UUID("6b000000-0000-4000-8000-000000000002")
USER_ID = UUID("6b000000-0000-4000-8000-000000000003")
ACTION_ID = UUID("6b000000-0000-4000-8000-000000000004")
ROOT_KEY = RootKey(version=7, material=b"v" * 32)
MAC_KEY = b"integration-validation-result-key!"


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
        self.credentials = None
        self.request_repr = None
        self.calls = 0

    def validate_credentials(self, request):
        self.calls += 1
        self.request_repr = repr(request)
        credentials = request.take_credentials()
        self.credentials = dict(credentials)
        if self.raises:
            raise RuntimeError("provider response was lost")
        return CredentialValidationResult(
            self.decision,
            safe_code={
                CredentialValidationDecision.VALID: "CREDENTIAL_VALID",
                CredentialValidationDecision.INVALID: "AUTH_REJECTED",
                CredentialValidationDecision.UNKNOWN: "PROVIDER_TIMEOUT",
            }[self.decision],
            safe_facts_digest=hashlib.sha256(
                f"safe:{self.decision.value}".encode("ascii")
            ).digest(),
        )


@pytest.fixture
def harness(tmp_path, mysql_control_database):
    database = mysql_control_database
    key_file = tmp_path / "v7"
    key_file.write_bytes(base64.b64encode(ROOT_KEY._material_bytes()) + b"\n")
    key_file.chmod(0o400)
    try:
        with database.transaction() as session:
            entitlements = {"features": {}, "limits": {"member_seats": 10}}
            entitlements_digest = hashlib.sha256(b"core-entitlements").digest()
            plan = PlanRevision(
                code="core",
                revision=1,
                name="Core",
                entitlements_schema_version=1,
                entitlements_json=entitlements,
                entitlements_digest=entitlements_digest,
            )
            tenant = Tenant(
                id=str(TENANT_ID),
                status="active",
                access_version=1,
            )
            session.add_all((
                plan,
                tenant,
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
                    database_name="tenant_6b000000000040008000000000000001",
                    status="ready",
                    schema_version="test-head",
                    activated_by_registration_commit_uuid=(
                        "6b000000-0000-4000-8000-000000000099"
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
                    entitlements_digest=entitlements_digest,
                    status="active",
                    expires_at=NOW + timedelta(days=30),
                ),
            ))
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
                credentials={
                    "partner_id": "partner-never-in-event",
                    "checkword": "secret-never-in-event",
                },
                root_key=ROOT_KEY,
                created_by_user_uuid=USER_ID,
                action_uuid=ACTION_ID,
                idempotency_key="integration-credential:action-1",
                expected_integration_row_version=1,
                expected_current_secret_revision_uuid=None,
            )
            event = ControlJobService().enqueue_outbox(
                session,
                tenant_id=str(TENANT_ID),
                tenant_access_version=1,
                source_type=INTEGRATION_REVISION_SOURCE_TYPE,
                source_uuid=pending.revision_uuid,
                source_generation=pending.revision_no,
                event_type=INTEGRATION_VALIDATION_EVENT_TYPE,
                payload={
                    "integration_uuid": str(INTEGRATION_ID),
                    "revision_uuid": pending.revision_uuid,
                    "revision_row_version": pending.row_version,
                    "provider": "sf",
                },
                idempotency_key="integration-credential:action-1",
                max_attempts=1,
                available_at=NOW,
            )
            event_id = event.id
            revision_id = pending.revision_uuid
        yield database, tmp_path, event_id, revision_id
    finally:
        pass


def _run(harness, validator, *, authority=None):
    database, key_directory, _event_id, _revision_id = harness
    handler = TenantIntegrationCredentialValidationHandler(
        root_key_directory=key_directory,
        validators={"sf": validator},
    )
    worker = DurableOrdinaryOutboxWorker(
        database=database,
        authority=authority or _Authority(),
        handlers={INTEGRATION_VALIDATION_EVENT_TYPE: handler},
        heartbeat_recorder=None,
        worker_id="integration-validator-1",
        result_mac_key=MAC_KEY,
        lease_duration=timedelta(minutes=2),
        clock=lambda: NOW,
        allow_sqlite_claim_for_tests=True,
        service=ControlOutboxService(database_clock=lambda _session: NOW),
    )
    return worker.run_once()


def _current_gate_reader():
    return ControlTenantGateReader(
        recovery_hold_released=lambda _session, **_kwargs: True,
        unresolved_deletion=lambda _session, **_kwargs: False,
        unresolved_suspension=lambda _session, **_kwargs: False,
        database_clock=lambda _session: NOW,
    )


@pytest.mark.parametrize(
    ("decision", "revision_status", "verification_status", "integration_status"),
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
def test_known_validation_atomically_finishes_outbox_and_revision(
    harness,
    decision,
    revision_status,
    verification_status,
    integration_status,
):
    database, _keys, event_id, revision_id = harness
    validator = _Validator(decision)

    result = _run(harness, validator)

    assert result.state == "succeeded"
    assert validator.calls == 1
    assert validator.credentials == {
        "partner_id": "partner-never-in-event",
        "checkword": "secret-never-in-event",
    }
    assert "partner-never-in-event" not in validator.request_repr
    assert "secret-never-in-event" not in validator.request_repr
    with database.new_session() as session:
        event = session.get(ControlOutboxEvent, event_id)
        revision = session.get(TenantIntegrationSecretRevision, revision_id)
        integration = session.get(TenantIntegration, str(INTEGRATION_ID))
        assert event.state == "succeeded"
        assert revision.status == revision_status
        assert revision.verification_status == verification_status
        assert integration.status == integration_status
        assert integration.current_secret_revision_id == (
            revision_id if decision is CredentialValidationDecision.VALID else None
        )
        assert "secret-never-in-event" not in str(event.payload)


@pytest.mark.parametrize("raises", [False, True])
def test_unknown_validation_never_retries_or_activates_credentials(harness, raises):
    database, _keys, event_id, revision_id = harness
    validator = _Validator(CredentialValidationDecision.UNKNOWN, raises=raises)

    result = _run(harness, validator)

    assert result.state == "recovery_quarantined"
    assert result.reason_code == "provider_result_unknown"
    with database.new_session() as session:
        event = session.get(ControlOutboxEvent, event_id)
        revision = session.get(TenantIntegrationSecretRevision, revision_id)
        integration = session.get(TenantIntegration, str(INTEGRATION_ID))
        assert event.state == "recovery_quarantined"
        assert event.attempts == 1
        assert revision.status == "pending_validation"
        assert revision.verification_status == "unknown"
        assert integration.current_secret_revision_id is None


def test_current_d56_authority_blocks_suspended_tenant_before_provider(harness):
    database, _keys, event_id, revision_id = harness
    with database.transaction() as session:
        session.get(Tenant, str(TENANT_ID)).status = "suspended"
    validator = _Validator(CredentialValidationDecision.VALID)

    result = _run(
        harness,
        validator,
        authority=TenantIntegrationOutboxAuthority(_current_gate_reader()),
    )

    assert result.state == "idle"
    assert validator.calls == 0
    with database.new_session() as session:
        event = session.get(ControlOutboxEvent, event_id)
        revision = session.get(TenantIntegrationSecretRevision, revision_id)
        assert event.state == "recovery_quarantined"
        assert event.last_error_code == "tenant_suspended"
        assert revision.verification_status == "not_attempted"
