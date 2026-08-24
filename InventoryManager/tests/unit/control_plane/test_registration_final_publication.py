from __future__ import annotations

import ast
import hashlib
import inspect
from dataclasses import dataclass, replace
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

import inventory_control.registration.publication as publication_module
from inventory_control.registration.persistence import (
    ProvisionedRegistrationFacts,
    RegistrationFinalCommitPlan,
    RegistrationFinalizationResult,
    RegistrationSchemaOperationFence,
)
from inventory_control.registration.publication import (
    DatabaseAdvisoryLockHandle,
    GlobalSchemaPublicationFenceHandle,
    PersistedTenantReadyProof,
    ProvisionalTenantEndpoint,
    PublicationObservationState,
    ReadyPublicationState,
    RegistrationFinalPublicationAuthority,
    RegistrationFinalPublicationFenceError,
    RegistrationFinalPublicationInvariantError,
    RegistrationFinalPublicationReleaseError,
    RegistrationFinalPublicationRequest,
    RegistrationFinalPublicationService,
    RegistrationFinalPublicationUnpublished,
    RegistrationPublicationObservation,
    registration_publication_lock_binding_digest,
)


def _id(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"registration-final-publication/{label}")


ATTEMPT_UUID = _id("attempt")
TENANT_UUID = _id("tenant")
DATABASE_UUID = _id("database")
RUN_UUID = _id("run")
READY_PROOF_UUID = _id("ready-proof")
SCHEMA_CLAIM_UUID = _id("recorded-schema-claim")
PUBLICATION_CLAIM_UUID = _id("publication-schema-claim")
COMMIT_UUID = _id("commit")
MEMBERSHIP_UUID = _id("membership")
SUBSCRIPTION_UUID = _id("subscription")
EVENT_UUID = _id("event")
WAREHOUSE_UUID = _id("warehouse")


def _digest(label: str) -> bytes:
    return hashlib.sha256(label.encode("ascii")).digest()


READY_REQUEST_DIGEST = _digest("ready-request")
IDENTITY_DIGEST = _digest("database-identity")
SCHEMA_DIGEST = _digest("schema")
SMOKE_DIGEST = _digest("smoke")
ADVISORY_PROOF_DIGEST = _digest("ready-advisory-proof")


def _plan() -> RegistrationFinalCommitPlan:
    return RegistrationFinalCommitPlan(
        registration_commit_uuid=COMMIT_UUID,
        membership_uuid=MEMBERSHIP_UUID,
        subscription_uuid=SUBSCRIPTION_UUID,
        subscription_event_uuid=EVENT_UUID,
        published_tenant_name="Offline Fixture Tenant",
        published_slug="offline-fixture-tenant",
        idempotency_key="registration-final-v1",
    )


def _request() -> RegistrationFinalPublicationRequest:
    return RegistrationFinalPublicationRequest(
        attempt_uuid=ATTEMPT_UUID,
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        current_recovery_run_uuid=RUN_UUID,
        provisioning_generation=3,
        expected_attempt_row_version=8,
        expected_code_row_version=2,
        ready_proof_uuid=READY_PROOF_UUID,
        ready_proof_request_digest=READY_REQUEST_DIGEST,
        lock_idempotency_key="registration-final-lock-v1",
        plan=_plan(),
    )


def _current_schema_fence(*, row_version: int = 10) -> RegistrationSchemaOperationFence:
    return RegistrationSchemaOperationFence(
        claim_uuid=PUBLICATION_CLAIM_UUID,
        owner_id="provisioning-worker-1",
        generation=5,
        fencing_token=8,
        row_version=row_version,
    )


def _recorded_fence() -> RegistrationSchemaOperationFence:
    return _current_schema_fence()


def _publication_fence(
    request: RegistrationFinalPublicationRequest | None = None,
    *,
    row_version: int = 10,
) -> GlobalSchemaPublicationFenceHandle:
    selected_request = request or _request()
    return GlobalSchemaPublicationFenceHandle(
        schema_operation_fence=_current_schema_fence(row_version=row_version),
        purpose="provisioning",
        request_binding_digest=registration_publication_lock_binding_digest(
            selected_request
        ),
    )


def _provisioned() -> ProvisionedRegistrationFacts:
    return ProvisionedRegistrationFacts(
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        provisioning_generation=3,
        lease_owner="provisioning-worker-1",
        lease_token="worker-token-1",
        schema_generation=1,
        schema_digest=SCHEMA_DIGEST,
        database_identity_digest=IDENTITY_DIGEST,
        route_version=1,
        initial_credential_generation=1,
        dml_login_state_version=1,
        default_warehouse_uuid=WAREHOUSE_UUID,
        default_warehouse_digest=_digest("warehouse"),
        smoke_proof_digest=SMOKE_DIGEST,
        advisory_lock_proof_digest=ADVISORY_PROOF_DIGEST,
        backup_ddl_lease_held=True,
        database_advisory_lock_held=True,
        smoke_passed=True,
        business_route_unpublished=True,
    )


def _ready_proof(*, identity_digest: bytes = IDENTITY_DIGEST):
    return PersistedTenantReadyProof(
        proof_uuid=READY_PROOF_UUID,
        request_digest=READY_REQUEST_DIGEST,
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        provisioning_generation=3,
        schema_generation=1,
        schema_digest=SCHEMA_DIGEST,
        database_identity_digest=identity_digest,
        smoke_proof_digest=SMOKE_DIGEST,
        advisory_lock_proof_digest=ADVISORY_PROOF_DIGEST,
        recorded_schema_fence=_recorded_fence(),
        proof_policy_version=1,
    )


@dataclass
class Harness:
    events: list[str]
    route_status: str = "provisional"
    tenant_status: str = "provisioning"
    attempt_status: str = "ready"
    commit_uuid: UUID | None = None
    final_mode: str = "success"
    identity_ready: bool = True
    partial: bool = False
    fail_global_require_at: int | None = None
    global_require_count: int = 0
    fail_advisory_acquire: bool = False
    fail_advisory_release: bool = False
    fail_global_release: bool = False
    wrong_global_binding: bool = False
    wrong_advisory_binding: bool = False
    wrong_recorded_fence: bool = False
    fail_final_transaction_fence: bool = False
    omit_final_transaction_fence_read: bool = False
    current_fence_row_version: int = 10
    commit_during_global_acquire: bool = False


class FakeGlobalFences:
    def __init__(self, harness: Harness):
        self.harness = harness

    def acquire(self, *, request):
        self.harness.events.append("global.acquire")
        assert request.database_uuid == DATABASE_UUID
        if self.harness.commit_during_global_acquire:
            self.harness.route_status = "ready"
            self.harness.tenant_status = "active"
            self.harness.attempt_status = "active"
            self.harness.commit_uuid = COMMIT_UUID
            raise RuntimeError("concurrent-winner-released-schema-fence")
        fence = _publication_fence(
            request,
            row_version=self.harness.current_fence_row_version,
        )
        if self.harness.wrong_global_binding:
            return replace(fence, request_binding_digest=_digest("wrong-work"))
        return fence

    def require_current(self, *, request, fence):
        self.harness.global_require_count += 1
        self.harness.events.append("global.require")
        assert request.attempt_uuid == ATTEMPT_UUID
        assert fence == _publication_fence(
            request,
            row_version=self.harness.current_fence_row_version,
        )
        if (
            self.harness.fail_global_require_at
            == self.harness.global_require_count
        ):
            raise RuntimeError("stale-global-fence-with-private-detail")

    def require_current_in_transaction(
        self,
        *,
        control_transaction,
        request,
        fence,
    ):
        self.harness.events.append("global.require_in_final_transaction")
        assert control_transaction is self.harness
        assert request.attempt_uuid == ATTEMPT_UUID
        assert fence == _publication_fence(
            request,
            row_version=self.harness.current_fence_row_version,
        )
        if self.harness.fail_final_transaction_fence:
            raise RuntimeError("stale-final-transaction-fence-private-detail")

    def release(self, *, request, fence):
        self.harness.events.append("global.release")
        if self.harness.fail_global_release:
            raise RuntimeError("global-release-private-detail")


class FakeAdvisoryLocks:
    def __init__(self, harness: Harness):
        self.harness = harness

    def acquire(self, *, request, schema_fence):
        self.harness.events.append("advisory.acquire")
        if self.harness.fail_advisory_acquire:
            raise RuntimeError("advisory-private-detail")
        return DatabaseAdvisoryLockHandle(
            database_uuid=(
                _id("wrong-advisory-database")
                if self.harness.wrong_advisory_binding
                else request.database_uuid
            ),
            owner_id="registration-final-worker-1",
            lock_key_sha256=_digest("advisory-key"),
            acquisition_proof_digest=_digest("advisory-acquisition"),
            schema_claim_uuid=schema_fence.claim_uuid,
            schema_fencing_token=schema_fence.fencing_token,
        )

    def require_current(self, *, request, schema_fence, advisory_lock):
        self.harness.events.append("advisory.require")
        assert advisory_lock.database_uuid == request.database_uuid
        assert advisory_lock.schema_claim_uuid == schema_fence.claim_uuid

    def release(self, *, request, schema_fence, advisory_lock):
        self.harness.events.append("advisory.release")
        if self.harness.fail_advisory_release:
            raise RuntimeError("advisory-release-private-detail")


def _authority(harness: Harness) -> RegistrationFinalPublicationAuthority:
    committed = harness.commit_uuid is not None
    ready_proof = _ready_proof(
        identity_digest=(
            IDENTITY_DIGEST
            if harness.identity_ready
            else _digest("wrong-identity")
        )
    )
    if harness.wrong_recorded_fence:
        ready_proof = replace(
            ready_proof,
            recorded_schema_fence=RegistrationSchemaOperationFence(
                claim_uuid=SCHEMA_CLAIM_UUID,
                owner_id="superseded-provisioning-worker",
                generation=4,
                fencing_token=7,
                row_version=9,
            ),
        )
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
        provisioning_generation=3,
        attempt_row_version=8,
        code_row_version=2,
        tenant_status=harness.tenant_status,
        attempt_status=harness.attempt_status,
        endpoint=ProvisionalTenantEndpoint(
            tenant_uuid=TENANT_UUID,
            database_uuid=DATABASE_UUID,
            endpoint_identity_digest=_digest("provisional-endpoint"),
            route_version=1,
            initial_credential_generation=1,
            dml_login_state_version=1,
            status=harness.route_status,
            activated_by_registration_commit_uuid=harness.commit_uuid,
        ),
        ready_proof=ready_proof,
        provisioned=_provisioned(),
        existing_registration_commit_uuid=harness.commit_uuid,
    )


class FakeReadyCurrentRead:
    def __init__(self, harness: Harness):
        self.harness = harness

    def __call__(self, *, request, schema_fence, advisory_lock):
        self.harness.events.append("ready.current_read")
        return _authority(self.harness)


class FakeCommittedCurrentRead:
    def __init__(self, harness: Harness):
        self.harness = harness

    def __call__(self, *, request):
        self.harness.events.append("committed.current_read")
        assert request.attempt_uuid == ATTEMPT_UUID
        if self.harness.commit_uuid is None:
            return None
        if self.harness.partial:
            raise RegistrationFinalPublicationInvariantError()
        if not self.harness.identity_ready:
            raise RegistrationFinalPublicationInvariantError()
        return _finalization(status="active", created=False)


def _finalization(
    *,
    status: str,
    created: bool,
    integrity_incident_uuid: UUID | None = None,
):
    committed = status == "active"
    return RegistrationFinalizationResult(
        attempt_uuid=ATTEMPT_UUID,
        status=status,
        registration_commit_uuid=COMMIT_UUID if committed else None,
        membership_uuid=MEMBERSHIP_UUID if committed else None,
        subscription_uuid=SUBSCRIPTION_UUID if committed else None,
        subscription_event_uuid=EVENT_UUID if committed else None,
        resulting_attempt_row_version=10,
        created=created,
        integrity_incident_uuid=integrity_incident_uuid,
    )


class FakeFinalCommit:
    def __init__(self, harness: Harness):
        self.harness = harness

    def finalize(
        self,
        *,
        request,
        authority,
        schema_fence,
        advisory_lock,
        fence_current_read,
    ):
        self.harness.events.append("final.commit")
        if not self.harness.omit_final_transaction_fence_read:
            fence_current_read(control_transaction=self.harness)
        assert self.harness.identity_ready
        assert authority.ready_proof.database_identity_digest == IDENTITY_DIGEST
        assert authority.ready_proof.request_digest == READY_REQUEST_DIGEST
        if self.harness.final_mode == "fail_before":
            raise RuntimeError("unknown-before-commit-with-private-detail")
        if self.harness.final_mode == "identity_conflict":
            self.harness.attempt_status = "identity_conflict"
            return _finalization(status="identity_conflict", created=False)
        if self.harness.final_mode == "security_blocked":
            self.harness.attempt_status = "security_blocked"
            return _finalization(status="security_blocked", created=False)
        if self.harness.final_mode == "integrity_blocked":
            self.harness.attempt_status = "integrity_blocked"
            return _finalization(
                status="integrity_blocked",
                created=False,
                integrity_incident_uuid=_id("integrity-incident"),
            )

        self.harness.route_status = "ready"
        self.harness.tenant_status = "active"
        self.harness.attempt_status = "active"
        self.harness.commit_uuid = COMMIT_UUID
        if self.harness.final_mode == "fail_after":
            raise RuntimeError("response-lost-with-private-detail")
        return _finalization(
            status="active",
            created=authority.state is ReadyPublicationState.PROVISIONAL_READY,
        )


class FakeObservation:
    def __init__(self, harness: Harness):
        self.harness = harness

    def __call__(
        self,
        *,
        request,
        authority,
        schema_fence,
        advisory_lock,
    ):
        self.harness.events.append("publication.observe")
        if self.harness.partial:
            return RegistrationPublicationObservation(
                state=PublicationObservationState.INCONSISTENT,
                attempt_uuid=ATTEMPT_UUID,
                tenant_uuid=TENANT_UUID,
                database_uuid=DATABASE_UUID,
                ready_proof_uuid=READY_PROOF_UUID,
                ready_proof_request_digest=READY_REQUEST_DIGEST,
                route_status="ready",
                tenant_status="provisioning",
                attempt_status="committing",
                registration_commit_uuid=None,
                route_activation_commit_uuid=COMMIT_UUID,
            )
        committed = self.harness.commit_uuid is not None
        return RegistrationPublicationObservation(
            state=(
                PublicationObservationState.COMMITTED
                if committed
                else PublicationObservationState.UNPUBLISHED
            ),
            attempt_uuid=ATTEMPT_UUID,
            tenant_uuid=TENANT_UUID,
            database_uuid=DATABASE_UUID,
            ready_proof_uuid=READY_PROOF_UUID,
            ready_proof_request_digest=READY_REQUEST_DIGEST,
            route_status=self.harness.route_status,
            tenant_status=self.harness.tenant_status,
            attempt_status=self.harness.attempt_status,
            registration_commit_uuid=self.harness.commit_uuid,
            route_activation_commit_uuid=self.harness.commit_uuid,
        )


def _service(harness: Harness) -> RegistrationFinalPublicationService:
    return RegistrationFinalPublicationService(
        global_fences=FakeGlobalFences(harness),
        advisory_locks=FakeAdvisoryLocks(harness),
        committed_current_read=FakeCommittedCurrentRead(harness),
        ready_current_read=FakeReadyCurrentRead(harness),
        final_commit=FakeFinalCommit(harness),
        current_observation=FakeObservation(harness),
    )


def test_ready_identity_is_current_read_under_both_locks_before_atomic_publish():
    harness = Harness(events=[])

    result = _service(harness).publish(_request())

    assert result.route_published is True
    assert result.status == "active"
    assert result.registration_commit_uuid == COMMIT_UUID
    assert result.finalization_created is True
    assert result.reconciled_after_unknown is False
    assert harness.events == [
        "committed.current_read",
        "global.acquire",
        "global.require",
        "advisory.acquire",
        "advisory.require",
        "global.require",
        "ready.current_read",
        "advisory.require",
        "global.require",
        "final.commit",
        "global.require_in_final_transaction",
        "advisory.require",
        "global.require",
        "publication.observe",
        "advisory.release",
        "global.release",
    ]


def test_exact_committed_replay_returns_existing_registration_anchors():
    harness = Harness(
        events=[],
        route_status="ready",
        tenant_status="active",
        attempt_status="active",
        commit_uuid=COMMIT_UUID,
    )

    result = _service(harness).publish(_request())

    assert result.route_published is True
    assert result.finalization_created is False
    assert result.reconciled_after_unknown is False
    assert harness.events == ["committed.current_read"]


def test_committed_control_state_never_substitutes_for_existing_ready_proof():
    harness = Harness(
        events=[],
        route_status="ready",
        tenant_status="active",
        attempt_status="active",
        commit_uuid=COMMIT_UUID,
        identity_ready=False,
    )

    with pytest.raises(RegistrationFinalPublicationInvariantError):
        _service(harness).publish(_request())

    assert "final.commit" not in harness.events
    assert "publication.observe" not in harness.events
    assert harness.events == ["committed.current_read"]


def test_partial_committed_fast_path_never_acquires_live_fences():
    harness = Harness(
        events=[],
        route_status="ready",
        tenant_status="active",
        attempt_status="active",
        commit_uuid=COMMIT_UUID,
        partial=True,
    )

    with pytest.raises(RegistrationFinalPublicationInvariantError):
        _service(harness).publish(_request())

    assert harness.events == ["committed.current_read"]


def test_response_loss_reconciles_exact_commit_as_success():
    harness = Harness(events=[], final_mode="fail_after")

    result = _service(harness).publish(_request())

    assert result.route_published is True
    assert result.registration_commit_uuid == COMMIT_UUID
    assert result.finalization_created is False
    assert result.reconciled_after_unknown is True
    assert harness.events[-2:] == ["advisory.release", "global.release"]


def test_failure_before_commit_is_compensated_by_unpublished_observation():
    harness = Harness(events=[], final_mode="fail_before")

    with pytest.raises(RegistrationFinalPublicationUnpublished) as caught:
        _service(harness).publish(_request())

    assert str(caught.value) == (
        "REGISTRATION_FINAL_PUBLICATION_REMAINED_UNPUBLISHED"
    )
    assert harness.route_status == "provisional"
    assert harness.tenant_status == "provisioning"
    assert harness.commit_uuid is None
    assert harness.events[-3:] == [
        "advisory.release",
        "global.release",
        "committed.current_read",
    ]


@pytest.mark.parametrize(
    "mode",
    ("identity_conflict", "security_blocked", "integrity_blocked"),
)
def test_confirmed_registration_block_never_publishes_route(mode):
    harness = Harness(events=[], final_mode=mode)

    result = _service(harness).publish(_request())

    assert result.status == mode
    assert result.route_published is False
    assert result.registration_commit_uuid is None
    assert harness.route_status == "provisional"
    assert (result.integrity_incident_uuid is not None) == (
        mode == "integrity_blocked"
    )


def test_persisted_identity_proof_mismatch_rejects_before_final_commit():
    harness = Harness(events=[], identity_ready=False)

    with pytest.raises(RegistrationFinalPublicationFenceError):
        _service(harness).publish(_request())

    assert "final.commit" not in harness.events
    assert "publication.observe" not in harness.events
    assert harness.events[-3:] == [
        "advisory.release",
        "global.release",
        "committed.current_read",
    ]


def test_stale_global_fence_after_current_read_rejects_before_commit():
    harness = Harness(events=[], fail_global_require_at=3)

    with pytest.raises(RegistrationFinalPublicationFenceError) as caught:
        _service(harness).publish(_request())

    assert "private" not in str(caught.value)
    assert "final.commit" not in harness.events
    assert harness.events[-3:] == [
        "advisory.release",
        "global.release",
        "committed.current_read",
    ]


def test_ready_proof_requires_the_same_uninterrupted_schema_fence():
    harness = Harness(events=[], wrong_recorded_fence=True)

    with pytest.raises(RegistrationFinalPublicationFenceError):
        _service(harness).publish(_request())

    assert "final.commit" not in harness.events
    assert "publication.observe" not in harness.events
    assert harness.events[-3:] == [
        "advisory.release",
        "global.release",
        "committed.current_read",
    ]


def test_ready_proof_allows_same_claim_renewal_row_version_advance():
    harness = Harness(events=[], current_fence_row_version=11)

    result = _service(harness).publish(_request())

    assert result.route_published is True
    assert result.status == "active"


def test_committed_replay_survives_historical_ready_fence_turnover():
    harness = Harness(
        events=[],
        route_status="ready",
        tenant_status="active",
        attempt_status="active",
        commit_uuid=COMMIT_UUID,
        wrong_recorded_fence=True,
    )

    result = _service(harness).publish(_request())

    assert result.route_published is True
    assert result.finalization_created is False


def test_final_transaction_rechecks_fence_before_any_publication_mutation():
    harness = Harness(events=[], fail_final_transaction_fence=True)

    with pytest.raises(RegistrationFinalPublicationUnpublished) as caught:
        _service(harness).publish(_request())

    assert "private-detail" not in str(caught.value)
    assert harness.route_status == "provisional"
    assert harness.tenant_status == "provisioning"
    assert harness.commit_uuid is None
    assert harness.events.index("global.require_in_final_transaction") > (
        harness.events.index("final.commit")
    )


def test_finalizer_cannot_report_success_without_transactional_fence_read():
    harness = Harness(events=[], omit_final_transaction_fence_read=True)

    with pytest.raises(RegistrationFinalPublicationInvariantError):
        _service(harness).publish(_request())

    assert harness.route_status == "ready"
    assert "global.require_in_final_transaction" not in harness.events


def test_fence_loss_after_commit_reconciles_from_exact_current_anchors():
    harness = Harness(events=[], fail_global_require_at=4)

    result = _service(harness).publish(_request())

    assert result.route_published is True
    assert result.finalization_created is False
    assert result.reconciled_after_unknown is True
    assert harness.commit_uuid == COMMIT_UUID
    assert harness.route_status == "ready"
    assert "publication.observe" not in harness.events
    assert harness.events[-3:] == [
        "advisory.release",
        "global.release",
        "committed.current_read",
    ]


def test_advisory_acquisition_failure_releases_global_without_current_read():
    harness = Harness(events=[], fail_advisory_acquire=True)

    with pytest.raises(RegistrationFinalPublicationFenceError):
        _service(harness).publish(_request())

    assert harness.events == [
        "committed.current_read",
        "global.acquire",
        "global.require",
        "advisory.acquire",
        "global.release",
        "committed.current_read",
    ]


def test_concurrent_winner_between_precheck_and_fence_is_exactly_reconciled():
    harness = Harness(events=[], commit_during_global_acquire=True)

    result = _service(harness).publish(_request())

    assert result.route_published is True
    assert result.finalization_created is False
    assert result.reconciled_after_unknown is True
    assert harness.events == [
        "committed.current_read",
        "global.acquire",
        "committed.current_read",
    ]


def test_global_fence_must_be_bound_to_exact_attempt_proof_and_commit():
    harness = Harness(events=[], wrong_global_binding=True)

    with pytest.raises(RegistrationFinalPublicationFenceError):
        _service(harness).publish(_request())

    assert harness.events == [
        "committed.current_read",
        "global.acquire",
        "global.release",
        "committed.current_read",
    ]


def test_lock_binding_is_deterministic_and_covers_entire_final_plan():
    request = _request()
    replay = replace(request)
    changed_plan = replace(
        request,
        plan=replace(request.plan, membership_uuid=_id("other-membership")),
    )

    assert registration_publication_lock_binding_digest(replay) == (
        registration_publication_lock_binding_digest(request)
    )
    assert registration_publication_lock_binding_digest(changed_plan) != (
        registration_publication_lock_binding_digest(request)
    )


def test_wrong_advisory_binding_releases_both_acquired_locks():
    harness = Harness(events=[], wrong_advisory_binding=True)

    with pytest.raises(RegistrationFinalPublicationFenceError):
        _service(harness).publish(_request())

    assert harness.events == [
        "committed.current_read",
        "global.acquire",
        "global.require",
        "advisory.acquire",
        "advisory.release",
        "global.release",
        "committed.current_read",
    ]


def test_partial_publication_observation_is_fail_closed():
    harness = Harness(events=[], final_mode="fail_before", partial=True)

    with pytest.raises(RegistrationFinalPublicationInvariantError):
        _service(harness).publish(_request())

    assert harness.events[-2:] == ["advisory.release", "global.release"]


@pytest.mark.parametrize(
    ("advisory_failure", "global_failure"),
    ((True, False), (False, True), (True, True)),
)
def test_lock_release_failure_is_stable_and_attempts_both_releases(
    advisory_failure,
    global_failure,
):
    harness = Harness(
        events=[],
        fail_advisory_release=advisory_failure,
        fail_global_release=global_failure,
    )

    with pytest.raises(RegistrationFinalPublicationReleaseError) as caught:
        _service(harness).publish(_request())

    assert str(caught.value) == (
        "REGISTRATION_FINAL_PUBLICATION_LOCK_RELEASE_FAILED"
    )
    assert harness.events[-2:] == ["advisory.release", "global.release"]


def test_request_authority_and_errors_redact_worker_and_endpoint_details():
    harness = Harness(events=[])
    request = _request()
    authority = _authority(harness)
    rendered = repr(request) + repr(authority) + repr(authority.endpoint)

    assert "worker-token-1" not in rendered
    assert "password" not in rendered.lower()
    assert "dsn" not in rendered.lower()
    assert "database_name" not in rendered
    assert "<redacted>" in rendered

    harness.final_mode = "fail_before"
    with pytest.raises(RegistrationFinalPublicationUnpublished) as caught:
        _service(harness).publish(request)
    assert "private-detail" not in str(caught.value)


def test_publication_module_has_no_tenant_bootstrap_or_network_dependency():
    tree = ast.parse(inspect.getsource(publication_module))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)

    assert not any("schema_bootstrap" in name for name in imported)
    assert not any(
        name.startswith(prefix)
        for name in imported
        # The concrete adapter owns a ControlDatabase transaction indirectly;
        # tenant SQL/driver clients and network/provider clients stay excluded.
        for prefix in ("sqlalchemy", "requests", "pymysql", "flask")
    )
