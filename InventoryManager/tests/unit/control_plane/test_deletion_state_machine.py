from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from inventory_control.domain.tenant_gate import (
    EffectiveTenantGate,
    TenantGateFacts,
    TenantStatus,
    reduce_tenant_gate,
)
from inventory_control.lifecycle.deletion import (
    DELETION_COOLING_PERIOD,
    CancellationEvidence,
    DeletionActionKind,
    DeletionActionOutcome,
    DeletionClaimReleaseEvidence,
    DeletionEffectKind,
    DeletionExecutorFenceEvidence,
    DeletionIsolationEvidence,
    DeletionLifecycleContext,
    DeletionLockdownEvidence,
    DeletionRequestStatus,
    DeletionReviewDecision,
    DeletionState,
    DeletionTombstone,
    DeletionTransitionError,
    DestructiveCleanupEvidence,
    OffsiteTombstoneAck,
    begin_deletion_commit,
    begin_destructive_cleanup,
    begin_provider_claim_release,
    complete_approval_lockdown,
    complete_deletion,
    complete_deletion_cancellation,
    confirm_offsite_tombstone,
    fail_cooling_action,
    fail_irreversible_deletion_step,
    record_permanent_tombstone,
    request_deletion,
    request_deletion_cancellation,
    retry_failed_deletion,
    review_deletion,
)
from inventory_control.lifecycle.suspension import DmlLoginState, SuspensionPhase


TENANT_ID = UUID("10000000-0000-0000-0000-000000000001")
DATABASE_ID = UUID("20000000-0000-0000-0000-000000000002")
ADMIN_ID = UUID("30000000-0000-0000-0000-000000000003")
REVIEWER_ID = UUID("40000000-0000-0000-0000-000000000004")
REQUEST_ID = UUID("50000000-0000-0000-0000-000000000005")
REQUEST_ACTION = UUID("60000000-0000-0000-0000-000000000006")
REVIEW_ACTION = UUID("70000000-0000-0000-0000-000000000007")
CANCEL_ACTION = UUID("80000000-0000-0000-0000-000000000008")
COMMIT_ACTION = UUID("90000000-0000-0000-0000-000000000009")
NOW = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)
REQUEST_DIGEST = b"r" * 32
REVIEW_DIGEST = b"v" * 32
CANCEL_DIGEST = b"c" * 32
COMMIT_DIGEST = b"m" * 32
HEAD_HASH = b"h" * 32
RECORD_HASH = b"t" * 32


def _context(
    *,
    now: datetime = NOW,
    expires: datetime | None = None,
    status: TenantStatus = TenantStatus.ACTIVE,
    phase: SuspensionPhase | None = None,
    hold_released: bool = True,
) -> DeletionLifecycleContext:
    return DeletionLifecycleContext(
        tenant_status=status,
        suspension_phase=phase,
        recovery_hold_released=hold_released,
        subscription_expires_at_utc=expires or now + timedelta(days=90),
        database_now_utc=now,
    )


def _initial(*, recovery_required: bool = False) -> DeletionState:
    return DeletionState.eligible(
        tenant_id=TENANT_ID,
        database_id=DATABASE_ID,
        recovery_dispositions_required=recovery_required,
    )


def _requested() -> DeletionState:
    return request_deletion(
        _initial(),
        context=_context(),
        request_id=REQUEST_ID,
        action_id=REQUEST_ACTION,
        requested_by_user_id=ADMIN_ID,
        idempotency_key="delete-request",
        request_digest=REQUEST_DIGEST,
        requested_at_utc=NOW,
        actor_is_active_admin=True,
        purpose_bound_otp_verified=True,
        expected_access_version=1,
    ).state


def _cooling(*, recovery_required: bool = False) -> DeletionState:
    initial = _initial(recovery_required=recovery_required)
    requested = request_deletion(
        initial,
        context=_context(),
        request_id=REQUEST_ID,
        action_id=REQUEST_ACTION,
        requested_by_user_id=ADMIN_ID,
        idempotency_key="delete-request",
        request_digest=REQUEST_DIGEST,
        requested_at_utc=NOW,
        actor_is_active_admin=True,
        purpose_bound_otp_verified=True,
        expected_access_version=1,
    ).state
    approved = review_deletion(
        requested,
        context=_context(),
        decision=DeletionReviewDecision.APPROVE,
        action_id=REVIEW_ACTION,
        platform_reviewer_id=REVIEWER_ID,
        reviewer_is_active_platform_admin=True,
        idempotency_key="approve-request",
        request_digest=REVIEW_DIGEST,
        reviewed_at_utc=NOW + timedelta(hours=1),
        expected_request_revision=1,
        expected_access_version=1,
        expected_execution_generation=1,
        expected_executor_fencing_token=1,
    ).state
    return complete_approval_lockdown(
        approved,
        evidence=_lockdown(approved),
        expected_request_revision=2,
    ).state


def _committing(*, recovery_required: bool = False) -> DeletionState:
    cooling = _cooling(recovery_required=recovery_required)
    assert cooling.request is not None
    return begin_deletion_commit(
        cooling,
        action_id=COMMIT_ACTION,
        idempotency_key="commit-delete",
        request_digest=COMMIT_DIGEST,
        database_now_utc=cooling.request.execute_not_before_utc,
        expected_request_revision=cooling.request.revision,
        expected_access_version=cooling.tenant_access_version,
        expected_execution_generation=cooling.request.execution_generation,
        expected_executor_fencing_token=cooling.request.executor_fencing_token,
        lease_fence_verified=True,
    ).state


def _awaiting_ack(*, recovery_required: bool = False) -> DeletionState:
    committing = _committing(recovery_required=recovery_required)
    assert committing.request is not None
    return record_permanent_tombstone(
        committing,
        tombstone=_tombstone(),
        evidence=_isolation(committing),
        expected_request_revision=committing.request.revision,
    ).state


def _acked(*, recovery_required: bool = False) -> DeletionState:
    awaiting = _awaiting_ack(recovery_required=recovery_required)
    assert awaiting.request is not None
    return confirm_offsite_tombstone(
        awaiting,
        acknowledgment=_ack(),
        executor_fence=_fence(awaiting),
        expected_request_revision=awaiting.request.revision,
    ).state


def _claim_releasing(*, recovery_required: bool = False) -> DeletionState:
    acked = _acked(recovery_required=recovery_required)
    assert acked.request is not None
    return begin_provider_claim_release(
        acked,
        expected_request_revision=acked.request.revision,
        expected_access_version=acked.tenant_access_version,
        expected_execution_generation=acked.request.execution_generation,
        expected_executor_fencing_token=acked.request.executor_fencing_token,
        lease_fence_verified=True,
    ).state


def _dropping(*, recovery_required: bool = False) -> DeletionState:
    releasing = _claim_releasing(recovery_required=recovery_required)
    assert releasing.request is not None
    return begin_destructive_cleanup(
        releasing,
        evidence=_claim_release(releasing),
        expected_request_revision=releasing.request.revision,
        expected_access_version=releasing.tenant_access_version,
        expected_execution_generation=releasing.request.execution_generation,
        expected_executor_fencing_token=releasing.request.executor_fencing_token,
        lease_fence_verified=True,
    ).state


def _lockdown(state: DeletionState, **changes: object) -> DeletionLockdownEvidence:
    assert state.request is not None
    values: dict[str, object] = {
        "action_id": state.request.current_action.action_id,
        "execution_generation": state.request.execution_generation,
        "executor_fencing_token": state.request.executor_fencing_token,
        "tenant_access_version": state.tenant_access_version,
        "lease_fence_verified": True,
        "sessions_revoked": True,
        "tenant_engines_disposed": True,
        "job_leases_blocked": True,
        "provider_submissions_blocked": True,
        "desired_dml_locked": True,
        "all_dml_identities_locked": True,
    }
    values.update(changes)
    return DeletionLockdownEvidence(**values)  # type: ignore[arg-type]


def _isolation(state: DeletionState, **changes: object) -> DeletionIsolationEvidence:
    assert state.request is not None
    values: dict[str, object] = {
        "action_id": state.request.current_action.action_id,
        "execution_generation": state.request.execution_generation,
        "executor_fencing_token": state.request.executor_fencing_token,
        "tenant_access_version": state.tenant_access_version,
        "lease_fence_verified": True,
        "deletion_lockdown_complete": True,
        "job_leases_reclaimed": True,
        "provider_operations_isolated": True,
        "all_dml_identities_locked": True,
    }
    values.update(changes)
    return DeletionIsolationEvidence(**values)  # type: ignore[arg-type]


def _tombstone(**changes: object) -> DeletionTombstone:
    values: dict[str, object] = {
        "request_id": REQUEST_ID,
        "tenant_id": TENANT_ID,
        "database_id": DATABASE_ID,
        "sequence": 41,
        "previous_hash": b"p" * 32,
        "record_hash": RECORD_HASH,
        "head_hash": HEAD_HASH,
        "checkpoint_root_key_version": 7,
        "checkpoint_mac": b"k" * 32,
        "recorded_at_utc": NOW + timedelta(days=31),
    }
    values.update(changes)
    return DeletionTombstone(**values)  # type: ignore[arg-type]


def _ack(**changes: object) -> OffsiteTombstoneAck:
    values: dict[str, object] = {
        "sequence": 41,
        "head_hash": HEAD_HASH,
        "artifact_checksum": b"a" * 32,
        "acknowledged_at_utc": NOW + timedelta(days=31, minutes=1),
        "authenticated": True,
        "durably_persisted": True,
        "checksum_verified": True,
        "chain_verified": True,
    }
    values.update(changes)
    return OffsiteTombstoneAck(**values)  # type: ignore[arg-type]


def _fence(state: DeletionState, **changes: object) -> DeletionExecutorFenceEvidence:
    assert state.request is not None
    values: dict[str, object] = {
        "action_id": state.request.current_action.action_id,
        "execution_generation": state.request.execution_generation,
        "executor_fencing_token": state.request.executor_fencing_token,
        "tenant_access_version": state.tenant_access_version,
        "lease_fence_verified": True,
    }
    values.update(changes)
    return DeletionExecutorFenceEvidence(**values)  # type: ignore[arg-type]


def _cleanup(state: DeletionState, **changes: object) -> DestructiveCleanupEvidence:
    assert state.request is not None and state.request.tombstone is not None
    values: dict[str, object] = {
        "action_id": state.request.current_action.action_id,
        "execution_generation": state.request.execution_generation,
        "executor_fencing_token": state.request.executor_fencing_token,
        "tenant_access_version": state.tenant_access_version,
        "lease_fence_verified": True,
        "tombstone_sequence": state.request.tombstone.sequence,
        "tombstone_head_hash": state.request.tombstone.head_hash,
        "schema_absent": True,
        "dml_identities_absent": True,
        "platform_read_identities_absent": True,
        "database_routes_absent": True,
        "provider_accounts_and_bindings_absent": True,
        "integration_secrets_absent": True,
        "tenant_control_data_minimized": True,
        "provider_operations_isolated": True,
        "claims_released_or_valid_new_owner": True,
        "no_orphan_claims": True,
        "tenant_identity_removal_ready": True,
        "phone_release_ready": True,
        "cross_tenant_negative_checks_passed": True,
        "recovery_dispositions_complete": True,
    }
    values.update(changes)
    return DestructiveCleanupEvidence(**values)  # type: ignore[arg-type]


def _claim_release(
    state: DeletionState,
    **changes: object,
) -> DeletionClaimReleaseEvidence:
    assert state.request is not None and state.request.tombstone is not None
    values: dict[str, object] = {
        "action_id": state.request.current_action.action_id,
        "execution_generation": state.request.execution_generation,
        "executor_fencing_token": state.request.executor_fencing_token,
        "tenant_access_version": state.tenant_access_version,
        "lease_fence_verified": True,
        "tombstone_sequence": state.request.tombstone.sequence,
        "tombstone_head_hash": state.request.tombstone.head_hash,
        "reserved_binding_operations_fenced": True,
        "bidirectional_bindings_verified": True,
        "provider_operations_isolated": True,
        "claims_released_or_valid_new_owner": True,
        "valid_new_owner_claims_untouched": True,
        "claim_release_events_appended": True,
        "no_orphan_claims": True,
        "recovery_dispositions_complete": state.recovery_dispositions_required,
    }
    values.update(changes)
    return DeletionClaimReleaseEvidence(**values)  # type: ignore[arg-type]


def _assert_error(code: str, callable_: object) -> None:
    with pytest.raises(DeletionTransitionError) as captured:
        callable_()  # type: ignore[operator]
    assert captured.value.code == code


def test_request_requires_active_admin_otp_and_preserves_access() -> None:
    result = request_deletion(
        _initial(),
        context=_context(),
        request_id=REQUEST_ID,
        action_id=REQUEST_ACTION,
        requested_by_user_id=ADMIN_ID,
        idempotency_key="delete-request",
        request_digest=REQUEST_DIGEST,
        requested_at_utc=NOW,
        actor_is_active_admin=True,
        purpose_bound_otp_verified=True,
        expected_access_version=1,
    )
    assert result.state.request is not None
    assert result.state.request.status is DeletionRequestStatus.PENDING_REVIEW
    assert result.state.tenant_status is TenantStatus.ACTIVE
    assert result.state.tenant_access_version == 1
    assert result.effects == ()
    assert not result.subscription_expiry_changed
    assert not result.redemption_code_consumed


@pytest.mark.parametrize(
    ("admin", "otp", "context", "code"),
    [
        (False, True, _context(), "DELETION_ACTIVE_ADMIN_REQUIRED"),
        (True, False, _context(), "DELETION_PURPOSE_BOUND_OTP_REQUIRED"),
        (
            True,
            True,
            _context(status=TenantStatus.EXPIRED, expires=NOW),
            "TENANT_DELETION_REQUEST_NOT_ALLOWED",
        ),
        (
            True,
            True,
            _context(
                status=TenantStatus.SUSPENDED,
                phase=SuspensionPhase.ACTIVE,
            ),
            "TENANT_DELETION_REQUEST_NOT_ALLOWED",
        ),
        (
            True,
            True,
            _context(hold_released=False),
            "TENANT_DELETION_REQUEST_NOT_ALLOWED",
        ),
    ],
)
def test_request_fails_closed_for_ineligible_context(
    admin: bool,
    otp: bool,
    context: DeletionLifecycleContext,
    code: str,
) -> None:
    _assert_error(
        code,
        lambda: request_deletion(
            _initial(),
            context=context,
            request_id=REQUEST_ID,
            action_id=REQUEST_ACTION,
            requested_by_user_id=ADMIN_ID,
            idempotency_key="delete-request",
            request_digest=REQUEST_DIGEST,
            requested_at_utc=NOW,
            actor_is_active_admin=admin,
            purpose_bound_otp_verified=otp,
            expected_access_version=1,
        ),
    )


def test_request_same_action_is_idempotent_and_different_action_conflicts() -> None:
    requested = _requested()
    replay = request_deletion(
        requested,
        context=_context(),
        request_id=REQUEST_ID,
        action_id=REQUEST_ACTION,
        requested_by_user_id=ADMIN_ID,
        idempotency_key="delete-request",
        request_digest=REQUEST_DIGEST,
        requested_at_utc=NOW,
        actor_is_active_admin=True,
        purpose_bound_otp_verified=True,
        expected_access_version=999,
    )
    assert replay.idempotent_replay
    assert replay.state is requested
    _assert_error(
        "ACTIVE_DELETION_REQUEST_EXISTS",
        lambda: request_deletion(
            requested,
            context=_context(),
            request_id=uuid4(),
            action_id=uuid4(),
            requested_by_user_id=ADMIN_ID,
            idempotency_key="another-request",
            request_digest=b"x" * 32,
            requested_at_utc=NOW,
            actor_is_active_admin=True,
            purpose_bound_otp_verified=True,
            expected_access_version=1,
        ),
    )


def test_rejection_is_terminal_without_locking_tenant() -> None:
    requested = _requested()
    result = review_deletion(
        requested,
        context=_context(),
        decision=DeletionReviewDecision.REJECT,
        action_id=REVIEW_ACTION,
        platform_reviewer_id=REVIEWER_ID,
        reviewer_is_active_platform_admin=True,
        idempotency_key="reject-request",
        request_digest=REVIEW_DIGEST,
        reviewed_at_utc=NOW,
        expected_request_revision=1,
        expected_access_version=1,
        expected_execution_generation=1,
        expected_executor_fencing_token=1,
    )
    assert result.state.request is not None
    assert result.state.request.status is DeletionRequestStatus.REJECTED
    assert result.state.tenant_status is TenantStatus.ACTIVE
    assert result.state.desired_dml_login_state is DmlLoginState.ACTIVE
    assert result.effects == ()


def test_review_requires_current_platform_admin_authority_and_typed_decision() -> None:
    requested = _requested()
    common: dict[str, object] = {
        "context": _context(),
        "action_id": REVIEW_ACTION,
        "platform_reviewer_id": REVIEWER_ID,
        "reviewer_is_active_platform_admin": True,
        "idempotency_key": "approve-request",
        "request_digest": REVIEW_DIGEST,
        "reviewed_at_utc": NOW,
        "expected_request_revision": 1,
        "expected_access_version": 1,
        "expected_execution_generation": 1,
        "expected_executor_fencing_token": 1,
    }
    unauthorized = dict(common)
    unauthorized.update(
        decision=DeletionReviewDecision.APPROVE,
        reviewer_is_active_platform_admin=False,
    )
    _assert_error(
        "DELETION_PLATFORM_REVIEWER_REQUIRED",
        lambda: review_deletion(requested, **unauthorized),  # type: ignore[arg-type]
    )
    untyped = dict(common)
    untyped["decision"] = "approve"
    _assert_error(
        "INVALID_DELETION_REVIEW_DECISION",
        lambda: review_deletion(requested, **untyped),  # type: ignore[arg-type]
    )


def test_rejected_request_allows_a_new_request() -> None:
    requested = _requested()
    rejected = review_deletion(
        requested,
        context=_context(),
        decision=DeletionReviewDecision.REJECT,
        action_id=REVIEW_ACTION,
        platform_reviewer_id=REVIEWER_ID,
        reviewer_is_active_platform_admin=True,
        idempotency_key="reject-request",
        request_digest=REVIEW_DIGEST,
        reviewed_at_utc=NOW,
        expected_request_revision=1,
        expected_access_version=1,
        expected_execution_generation=1,
        expected_executor_fencing_token=1,
    ).state
    new_request_id = uuid4()
    result = request_deletion(
        rejected,
        context=_context(now=NOW + timedelta(hours=1)),
        request_id=new_request_id,
        action_id=uuid4(),
        requested_by_user_id=ADMIN_ID,
        idempotency_key="delete-request-two",
        request_digest=b"2" * 32,
        requested_at_utc=NOW + timedelta(hours=1),
        actor_is_active_admin=True,
        purpose_bound_otp_verified=True,
        expected_access_version=1,
    )
    assert result.state.request is not None
    assert result.state.request.request_id == new_request_id
    assert result.state.request.revision == 1


def test_approval_installs_high_priority_deny_and_exact_thirty_day_deadline() -> None:
    requested = _requested()
    reviewed_at = NOW + timedelta(hours=3)
    result = review_deletion(
        requested,
        context=_context(
            status=TenantStatus.SUSPENDING,
            phase=SuspensionPhase.FREEZING,
        ),
        decision=DeletionReviewDecision.APPROVE,
        action_id=REVIEW_ACTION,
        platform_reviewer_id=REVIEWER_ID,
        reviewer_is_active_platform_admin=True,
        idempotency_key="approve-request",
        request_digest=REVIEW_DIGEST,
        reviewed_at_utc=reviewed_at,
        expected_request_revision=1,
        expected_access_version=1,
        expected_execution_generation=1,
        expected_executor_fencing_token=1,
    )
    assert result.state.request is not None
    assert result.state.request.status is DeletionRequestStatus.COOLING_OFF
    assert result.state.request.execute_not_before_utc == reviewed_at + timedelta(days=30)
    assert result.state.request.pre_freeze_suspension_phase is SuspensionPhase.FREEZING
    assert result.state.tenant_status is TenantStatus.DELETION_COOLING_OFF
    assert result.state.tenant_access_version == 2
    assert result.state.desired_dml_login_state is DmlLoginState.LOCKED
    kinds = {fact.kind for fact in result.effects}
    assert DeletionEffectKind.REVOKE_ALL_SESSIONS in kinds
    assert DeletionEffectKind.BLOCK_PROVIDER_SUBMISSIONS in kinds
    assert DeletionEffectKind.SUPERSEDE_LOWER_PRIORITY_LIFECYCLE_ACTIONS in kinds
    assert all(fact.tenant_access_version == 2 for fact in result.effects)


def test_lockdown_requires_all_barrier_evidence() -> None:
    requested = _requested()
    approved = review_deletion(
        requested,
        context=_context(),
        decision=DeletionReviewDecision.APPROVE,
        action_id=REVIEW_ACTION,
        platform_reviewer_id=REVIEWER_ID,
        reviewer_is_active_platform_admin=True,
        idempotency_key="approve-request",
        request_digest=REVIEW_DIGEST,
        reviewed_at_utc=NOW,
        expected_request_revision=1,
        expected_access_version=1,
        expected_execution_generation=1,
        expected_executor_fencing_token=1,
    ).state
    _assert_error(
        "DELETION_LOCKDOWN_BARRIER_INCOMPLETE",
        lambda: complete_approval_lockdown(
            approved,
            evidence=_lockdown(approved, tenant_engines_disposed=False),
            expected_request_revision=2,
        ),
    )
    assert approved.request is not None
    assert approved.request.current_action.outcome is DeletionActionOutcome.RUNNING


def test_cooling_failure_and_evidence_retry_never_reopens_access() -> None:
    requested = _requested()
    approved = review_deletion(
        requested,
        context=_context(),
        decision=DeletionReviewDecision.APPROVE,
        action_id=REVIEW_ACTION,
        platform_reviewer_id=REVIEWER_ID,
        reviewer_is_active_platform_admin=True,
        idempotency_key="approve-request",
        request_digest=REVIEW_DIGEST,
        reviewed_at_utc=NOW,
        expected_request_revision=1,
        expected_access_version=1,
        expected_execution_generation=1,
        expected_executor_fencing_token=1,
    ).state
    assert approved.request is not None
    failed = fail_cooling_action(
        approved,
        failure_code="DML_BARRIER_TIMEOUT",
        action_id=REVIEW_ACTION,
        expected_request_revision=2,
        expected_access_version=2,
        expected_execution_generation=2,
        expected_executor_fencing_token=2,
    ).state
    assert failed.request is not None
    assert failed.request.status is DeletionRequestStatus.COOLING_OFF
    assert failed.request.current_action.outcome is DeletionActionOutcome.FAILED
    assert failed.tenant_status is TenantStatus.DELETION_COOLING_OFF
    assert failed.desired_dml_login_state is DmlLoginState.LOCKED
    completed = complete_approval_lockdown(
        failed,
        evidence=_lockdown(failed),
        expected_request_revision=3,
    )
    assert completed.state.request is not None
    assert completed.state.request.current_action.outcome is DeletionActionOutcome.SUCCEEDED


def test_commit_rejects_before_deadline_and_accepts_exact_boundary() -> None:
    cooling = _cooling()
    assert cooling.request is not None
    deadline = cooling.request.execute_not_before_utc
    assert deadline is not None
    _assert_error(
        "DELETION_COOLING_PERIOD_NOT_ELAPSED",
        lambda: begin_deletion_commit(
            cooling,
            action_id=COMMIT_ACTION,
            idempotency_key="commit-delete",
            request_digest=COMMIT_DIGEST,
            database_now_utc=deadline - timedelta(microseconds=1),
            expected_request_revision=3,
            expected_access_version=2,
            expected_execution_generation=2,
            expected_executor_fencing_token=2,
            lease_fence_verified=True,
        ),
    )
    result = begin_deletion_commit(
        cooling,
        action_id=COMMIT_ACTION,
        idempotency_key="commit-delete",
        request_digest=COMMIT_DIGEST,
        database_now_utc=deadline,
        expected_request_revision=3,
        expected_access_version=2,
        expected_execution_generation=2,
        expected_executor_fencing_token=2,
        lease_fence_verified=True,
    )
    assert result.state.request is not None
    assert result.state.request.status is DeletionRequestStatus.COMMITTING
    assert result.state.tenant_status is TenantStatus.DELETION_COMMITTING
    assert result.state.tenant_access_version == 3
    assert result.state.request.execution_generation == 3
    assert result.state.request.executor_fencing_token == 3


def test_commit_is_monotonic_and_does_not_require_recovery_hold_release() -> None:
    cooling = _cooling()
    assert cooling.request is not None
    deadline = cooling.request.execute_not_before_utc
    result = begin_deletion_commit(
        cooling,
        action_id=COMMIT_ACTION,
        idempotency_key="commit-delete",
        request_digest=COMMIT_DIGEST,
        database_now_utc=deadline,
        expected_request_revision=3,
        expected_access_version=2,
        expected_execution_generation=2,
        expected_executor_fencing_token=2,
        lease_fence_verified=True,
    )
    kinds = {fact.kind for fact in result.effects}
    assert DeletionEffectKind.RECLAIM_TENANT_JOB_LEASES in kinds
    assert DeletionEffectKind.ISOLATE_PROVIDER_OPERATIONS in kinds


@pytest.mark.parametrize(
    ("state_factory", "expected_gate"),
    [
        (_cooling, EffectiveTenantGate.DELETION_COOLING_OFF),
        (_committing, EffectiveTenantGate.DELETED),
    ],
)
def test_recovery_suspension_and_expiry_cannot_mask_deletion_gate(
    state_factory: object,
    expected_gate: EffectiveTenantGate,
) -> None:
    state = state_factory()  # type: ignore[operator]
    decision = reduce_tenant_gate(
        TenantGateFacts(
            tenant_status=state.tenant_status,
            current_access_version=state.tenant_access_version,
            presented_access_version=state.tenant_access_version,
            recovery_hold_released=False,
            unresolved_suspension=True,
            subscription_expires_at=NOW - timedelta(days=1),
            evaluated_at=NOW,
        )
    )
    assert decision.gate is expected_gate
    assert not decision.allows_business_route


def test_cancellation_stays_locked_until_fresh_candidate_is_verified() -> None:
    cooling = _cooling()
    assert cooling.request is not None
    now = cooling.request.reviewed_at_utc + timedelta(days=1)  # type: ignore[operator]
    requested = request_deletion_cancellation(
        cooling,
        context=_context(now=now),
        action_id=CANCEL_ACTION,
        idempotency_key="cancel-delete",
        request_digest=CANCEL_DIGEST,
        cancelled_by_user_id=ADMIN_ID,
        actor_is_active_admin=True,
        purpose_bound_otp_verified=True,
        expected_request_revision=3,
        expected_access_version=2,
        expected_execution_generation=2,
        expected_executor_fencing_token=2,
    )
    assert requested.state.request is not None
    assert requested.state.request.status is DeletionRequestStatus.COOLING_OFF
    assert requested.state.tenant_status is TenantStatus.DELETION_COOLING_OFF
    assert requested.state.desired_dml_login_state is DmlLoginState.LOCKED
    assert requested.state.candidate_dml_generation == 2
    assert DeletionEffectKind.CREATE_LOCKED_UNPUBLISHED_DML_CANDIDATE in {
        effect.kind for effect in requested.effects
    }
    _assert_error(
        "CANCELLATION_CANDIDATE_VALIDATION_INCOMPLETE",
        lambda: complete_deletion_cancellation(
            requested.state,
            context=_context(now=now),
            evidence=CancellationEvidence(
                action_id=CANCEL_ACTION,
                execution_generation=3,
                executor_fencing_token=3,
                tenant_access_version=2,
                lease_fence_verified=True,
                deletion_lockdown_complete=True,
                candidate_generation=2,
            ),
            expected_request_revision=4,
        ),
    )


def test_cancellation_uses_realtime_expiry_and_publishes_only_valid_candidate() -> None:
    cooling = _cooling()
    assert cooling.request is not None
    now = cooling.request.reviewed_at_utc + timedelta(days=2)  # type: ignore[operator]
    cancellation = request_deletion_cancellation(
        cooling,
        context=_context(now=now),
        action_id=CANCEL_ACTION,
        idempotency_key="cancel-delete",
        request_digest=CANCEL_DIGEST,
        cancelled_by_user_id=ADMIN_ID,
        actor_is_active_admin=True,
        purpose_bound_otp_verified=True,
        expected_request_revision=3,
        expected_access_version=2,
        expected_execution_generation=2,
        expected_executor_fencing_token=2,
    ).state
    result = complete_deletion_cancellation(
        cancellation,
        context=_context(now=now, expires=now),
        evidence=CancellationEvidence(
            action_id=CANCEL_ACTION,
            execution_generation=3,
            executor_fencing_token=3,
            tenant_access_version=2,
            lease_fence_verified=True,
            deletion_lockdown_complete=True,
            candidate_generation=2,
            candidate_identity_verified=True,
            candidate_positive_permissions_verified=True,
            candidate_negative_permissions_verified=True,
            candidate_unpublished=True,
        ),
        expected_request_revision=4,
    )
    assert result.state.request is not None
    assert result.state.request.status is DeletionRequestStatus.CANCELLED
    assert result.state.tenant_status is TenantStatus.EXPIRED
    assert result.state.desired_dml_login_state is DmlLoginState.ACTIVE
    assert result.state.published_dml_generation == 2
    assert result.state.candidate_dml_generation is None
    assert DeletionEffectKind.PUBLISH_VALIDATED_DML_CANDIDATE in {
        effect.kind for effect in result.effects
    }
    assert not result.service_time_compensated


@pytest.mark.parametrize(
    ("status", "phase", "expected"),
    [
        (TenantStatus.SUSPENDING, SuspensionPhase.FREEZING, TenantStatus.SUSPENDING),
        (TenantStatus.SUSPENDING, SuspensionPhase.FAILED, TenantStatus.SUSPENDING),
        (TenantStatus.RESUMING, SuspensionPhase.RESOLVING, TenantStatus.SUSPENDING),
        (TenantStatus.SUSPENDED, SuspensionPhase.ACTIVE, TenantStatus.SUSPENDED),
    ],
)
def test_cancellation_restores_suspension_priority_but_never_dml(
    status: TenantStatus,
    phase: SuspensionPhase,
    expected: TenantStatus,
) -> None:
    cooling = _cooling()
    assert cooling.request is not None
    now = cooling.request.reviewed_at_utc + timedelta(days=1)  # type: ignore[operator]
    context = _context(now=now, status=status, phase=phase)
    cancellation = request_deletion_cancellation(
        cooling,
        context=context,
        action_id=CANCEL_ACTION,
        idempotency_key="cancel-delete",
        request_digest=CANCEL_DIGEST,
        cancelled_by_user_id=ADMIN_ID,
        actor_is_active_admin=True,
        purpose_bound_otp_verified=True,
        expected_request_revision=3,
        expected_access_version=2,
        expected_execution_generation=2,
        expected_executor_fencing_token=2,
    ).state
    assert cancellation.candidate_dml_generation is None
    result = complete_deletion_cancellation(
        cancellation,
        context=context,
        evidence=CancellationEvidence(
            action_id=CANCEL_ACTION,
            execution_generation=3,
            executor_fencing_token=3,
            tenant_access_version=2,
            lease_fence_verified=True,
            deletion_lockdown_complete=True,
        ),
        expected_request_revision=4,
    )
    assert result.state.tenant_status is expected
    assert result.state.desired_dml_login_state is DmlLoginState.LOCKED
    assert DeletionEffectKind.PUBLISH_VALIDATED_DML_CANDIDATE not in {
        effect.kind for effect in result.effects
    }


def test_cancellation_under_recovery_hold_removes_overlay_but_keeps_deny() -> None:
    cooling = _cooling()
    assert cooling.request is not None
    now = cooling.request.reviewed_at_utc + timedelta(days=1)  # type: ignore[operator]
    context = _context(now=now, hold_released=False)
    cancellation = request_deletion_cancellation(
        cooling,
        context=context,
        action_id=CANCEL_ACTION,
        idempotency_key="cancel-delete",
        request_digest=CANCEL_DIGEST,
        cancelled_by_user_id=ADMIN_ID,
        actor_is_active_admin=True,
        purpose_bound_otp_verified=True,
        expected_request_revision=3,
        expected_access_version=2,
        expected_execution_generation=2,
        expected_executor_fencing_token=2,
    ).state
    result = complete_deletion_cancellation(
        cancellation,
        context=context,
        evidence=CancellationEvidence(
            action_id=CANCEL_ACTION,
            execution_generation=3,
            executor_fencing_token=3,
            tenant_access_version=2,
            lease_fence_verified=True,
            deletion_lockdown_complete=True,
        ),
        expected_request_revision=4,
    )
    assert result.state.tenant_status is TenantStatus.ACTIVE
    assert result.state.desired_dml_login_state is DmlLoginState.LOCKED


def test_cancellation_closes_at_exact_deadline_and_loses_after_commit() -> None:
    cooling = _cooling()
    assert cooling.request is not None
    deadline = cooling.request.execute_not_before_utc
    _assert_error(
        "DELETION_CANCELLATION_WINDOW_CLOSED",
        lambda: request_deletion_cancellation(
            cooling,
            context=_context(now=deadline),
            action_id=CANCEL_ACTION,
            idempotency_key="cancel-delete",
            request_digest=CANCEL_DIGEST,
            cancelled_by_user_id=ADMIN_ID,
            actor_is_active_admin=True,
            purpose_bound_otp_verified=True,
            expected_request_revision=3,
            expected_access_version=2,
            expected_execution_generation=2,
            expected_executor_fencing_token=2,
        ),
    )
    committing = _committing()
    assert committing.request is not None
    _assert_error(
        "DELETION_NOT_IN_COOLING_OFF",
        lambda: request_deletion_cancellation(
            committing,
            context=_context(now=deadline),
            action_id=CANCEL_ACTION,
            idempotency_key="cancel-delete",
            request_digest=CANCEL_DIGEST,
            cancelled_by_user_id=ADMIN_ID,
            actor_is_active_admin=True,
            purpose_bound_otp_verified=True,
            expected_request_revision=committing.request.revision,
            expected_access_version=committing.tenant_access_version,
            expected_execution_generation=committing.request.execution_generation,
            expected_executor_fencing_token=committing.request.executor_fencing_token,
        ),
    )


def test_tombstone_requires_completed_isolation_barrier() -> None:
    committing = _committing()
    assert committing.request is not None
    _assert_error(
        "DELETION_ISOLATION_BARRIER_INCOMPLETE",
        lambda: record_permanent_tombstone(
            committing,
            tombstone=_tombstone(),
            evidence=_isolation(committing, provider_operations_isolated=False),
            expected_request_revision=committing.request.revision,
        ),
    )
    assert committing.request.tombstone is None


def test_tombstone_is_privacy_minimized_and_precedes_cleanup_effects() -> None:
    committing = _committing()
    assert committing.request is not None
    result = record_permanent_tombstone(
        committing,
        tombstone=_tombstone(),
        evidence=_isolation(committing),
        expected_request_revision=committing.request.revision,
    )
    assert result.state.request is not None
    assert result.state.request.status is DeletionRequestStatus.AWAITING_OFFSITE_ACK
    kinds = {effect.kind for effect in result.effects}
    assert kinds == {
        DeletionEffectKind.APPEND_PERMANENT_TOMBSTONE,
        DeletionEffectKind.REPLICATE_TOMBSTONE_OFFSITE,
    }
    assert DeletionEffectKind.DROP_TENANT_SCHEMA not in kinds
    assert DeletionEffectKind.RELEASE_TENANT_PROVIDER_CLAIMS not in kinds
    assert not result.external_side_effect_performed
    assert set(result.state.request.tombstone.__dataclass_fields__) == {
        "request_id",
        "tenant_id",
        "database_id",
        "sequence",
        "previous_hash",
        "record_hash",
        "head_hash",
        "checkpoint_root_key_version",
        "checkpoint_mac",
        "recorded_at_utc",
    }


@pytest.mark.parametrize(
    ("ack_changes", "code"),
    [
        ({"authenticated": False}, "OFFSITE_TOMBSTONE_ACK_NOT_VERIFIED"),
        ({"durably_persisted": False}, "OFFSITE_TOMBSTONE_ACK_NOT_VERIFIED"),
        ({"checksum_verified": False}, "OFFSITE_TOMBSTONE_ACK_NOT_VERIFIED"),
        ({"chain_verified": False}, "OFFSITE_TOMBSTONE_ACK_NOT_VERIFIED"),
        ({"sequence": 42}, "OFFSITE_TOMBSTONE_ACK_MISMATCH"),
        ({"head_hash": b"x" * 32}, "OFFSITE_TOMBSTONE_ACK_MISMATCH"),
    ],
)
def test_bad_offsite_ack_fails_closed_without_cleanup(
    ack_changes: dict[str, object],
    code: str,
) -> None:
    awaiting = _awaiting_ack()
    assert awaiting.request is not None
    _assert_error(
        code,
        lambda: confirm_offsite_tombstone(
            awaiting,
            acknowledgment=_ack(**ack_changes),
            executor_fence=_fence(awaiting),
            expected_request_revision=awaiting.request.revision,
        ),
    )
    assert awaiting.request.status is DeletionRequestStatus.AWAITING_OFFSITE_ACK
    assert awaiting.request.offsite_ack is None


def test_verified_ack_is_recorded_but_does_not_start_cleanup() -> None:
    awaiting = _awaiting_ack()
    assert awaiting.request is not None
    result = confirm_offsite_tombstone(
        awaiting,
        acknowledgment=_ack(),
        executor_fence=_fence(awaiting),
        expected_request_revision=awaiting.request.revision,
    )
    assert result.state.request is not None
    assert result.state.request.status is DeletionRequestStatus.AWAITING_OFFSITE_ACK
    assert result.state.request.offsite_ack == _ack()
    assert {effect.kind for effect in result.effects} == {
        DeletionEffectKind.RECORD_VERIFIED_OFFSITE_ACK
    }
    assert DeletionEffectKind.DROP_TENANT_SCHEMA not in {
        effect.kind for effect in result.effects
    }


def test_cleanup_cannot_begin_without_matching_offsite_ack() -> None:
    awaiting = _awaiting_ack()
    assert awaiting.request is not None
    _assert_error(
        "VERIFIED_OFFSITE_TOMBSTONE_REQUIRED",
        lambda: begin_provider_claim_release(
            awaiting,
            expected_request_revision=awaiting.request.revision,
            expected_access_version=awaiting.tenant_access_version,
            expected_execution_generation=awaiting.request.execution_generation,
            expected_executor_fencing_token=awaiting.request.executor_fencing_token,
            lease_fence_verified=True,
        ),
    )


def test_cleanup_only_emits_system_work_facts_after_ack() -> None:
    acked = _acked(recovery_required=True)
    assert acked.request is not None
    result = begin_provider_claim_release(
        acked,
        expected_request_revision=acked.request.revision,
        expected_access_version=acked.tenant_access_version,
        expected_execution_generation=acked.request.execution_generation,
        expected_executor_fencing_token=acked.request.executor_fencing_token,
        lease_fence_verified=True,
    )
    kinds = {effect.kind for effect in result.effects}
    assert result.state.request is not None
    assert result.state.request.status is DeletionRequestStatus.RELEASING_CLAIMS
    assert DeletionEffectKind.DROP_TENANT_SCHEMA not in kinds
    assert DeletionEffectKind.REMOVE_TENANT_DATABASE_ROUTES not in kinds
    assert DeletionEffectKind.REMOVE_TENANT_PROVIDER_ACCOUNTS_AND_BINDINGS not in kinds
    assert DeletionEffectKind.RELEASE_TENANT_PROVIDER_CLAIMS in kinds
    assert DeletionEffectKind.APPEND_PROVIDER_CLAIM_RELEASE_EVENTS in kinds
    assert DeletionEffectKind.REMOVE_TENANT_IDENTITIES_AND_RELEASE_PHONES not in kinds
    assert DeletionEffectKind.RECORD_RECOVERY_TOMBSTONED_DISPOSITIONS in kinds
    assert not result.external_side_effect_performed


@pytest.mark.parametrize(
    "missing_field",
    [
        "reserved_binding_operations_fenced",
        "bidirectional_bindings_verified",
        "provider_operations_isolated",
        "claims_released_or_valid_new_owner",
        "valid_new_owner_claims_untouched",
        "claim_release_events_appended",
        "no_orphan_claims",
    ],
)
def test_destructive_cleanup_waits_for_complete_claim_release_barrier(
    missing_field: str,
) -> None:
    releasing = _claim_releasing(recovery_required=True)
    assert releasing.request is not None
    _assert_error(
        "DELETION_CLAIM_RELEASE_BARRIER_INCOMPLETE",
        lambda: begin_destructive_cleanup(
            releasing,
            evidence=_claim_release(releasing, **{missing_field: False}),
            expected_request_revision=releasing.request.revision,
            expected_access_version=releasing.tenant_access_version,
            expected_execution_generation=releasing.request.execution_generation,
            expected_executor_fencing_token=releasing.request.executor_fencing_token,
            lease_fence_verified=True,
        ),
    )
    assert releasing.request.status is DeletionRequestStatus.RELEASING_CLAIMS


def test_destructive_cleanup_starts_only_after_claim_release_evidence() -> None:
    releasing = _claim_releasing(recovery_required=True)
    assert releasing.request is not None
    result = begin_destructive_cleanup(
        releasing,
        evidence=_claim_release(releasing),
        expected_request_revision=releasing.request.revision,
        expected_access_version=releasing.tenant_access_version,
        expected_execution_generation=releasing.request.execution_generation,
        expected_executor_fencing_token=releasing.request.executor_fencing_token,
        lease_fence_verified=True,
    )
    kinds = {effect.kind for effect in result.effects}
    assert result.state.request is not None
    assert result.state.request.status is DeletionRequestStatus.DROPPING
    assert DeletionEffectKind.RELEASE_TENANT_PROVIDER_CLAIMS not in kinds
    assert DeletionEffectKind.APPEND_PROVIDER_CLAIM_RELEASE_EVENTS not in kinds
    assert DeletionEffectKind.REMOVE_TENANT_PROVIDER_ACCOUNTS_AND_BINDINGS in kinds
    assert DeletionEffectKind.DROP_TENANT_SCHEMA in kinds
    assert DeletionEffectKind.RECORD_RECOVERY_TOMBSTONED_DISPOSITIONS not in kinds


def test_recovery_disposition_and_tombstone_proof_precede_destructive_cleanup() -> None:
    releasing = _claim_releasing(recovery_required=True)
    assert releasing.request is not None
    for changes, code in (
        (
            {"recovery_dispositions_complete": False},
            "DELETION_RECOVERY_DISPOSITIONS_INCOMPLETE",
        ),
        (
            {"tombstone_sequence": 42},
            "DELETION_CLAIM_RELEASE_TOMBSTONE_MISMATCH",
        ),
        (
            {"tombstone_head_hash": b"z" * 32},
            "DELETION_CLAIM_RELEASE_TOMBSTONE_MISMATCH",
        ),
    ):
        _assert_error(
            code,
            lambda changes=changes: begin_destructive_cleanup(
                releasing,
                evidence=_claim_release(releasing, **changes),
                expected_request_revision=releasing.request.revision,
                expected_access_version=releasing.tenant_access_version,
                expected_execution_generation=releasing.request.execution_generation,
                expected_executor_fencing_token=releasing.request.executor_fencing_token,
                lease_fence_verified=True,
            ),
        )
    assert releasing.request.status is DeletionRequestStatus.RELEASING_CLAIMS


def test_completion_requires_every_cleanup_and_negative_proof() -> None:
    dropping = _dropping()
    assert dropping.request is not None
    _assert_error(
        "DELETION_CLEANUP_EVIDENCE_INCOMPLETE",
        lambda: complete_deletion(
            dropping,
            evidence=_cleanup(dropping, no_orphan_claims=False),
            expected_request_revision=dropping.request.revision,
        ),
    )
    assert dropping.tenant_status is TenantStatus.DELETION_COMMITTING


def test_recovery_inventory_requires_run_scoped_tombstoned_dispositions() -> None:
    dropping = _dropping(recovery_required=True)
    assert dropping.request is not None
    _assert_error(
        "DELETION_RECOVERY_DISPOSITIONS_INCOMPLETE",
        lambda: complete_deletion(
            dropping,
            evidence=_cleanup(dropping, recovery_dispositions_complete=False),
            expected_request_revision=dropping.request.revision,
        ),
    )


def test_completion_is_permanent_and_idempotent() -> None:
    dropping = _dropping()
    assert dropping.request is not None
    result = complete_deletion(
        dropping,
        evidence=_cleanup(dropping),
        expected_request_revision=dropping.request.revision,
    )
    assert result.state.request is not None
    assert result.state.request.status is DeletionRequestStatus.COMPLETED
    assert result.state.tenant_status is TenantStatus.DELETED
    assert result.state.desired_dml_login_state is DmlLoginState.LOCKED
    assert result.state.request.current_action.outcome is DeletionActionOutcome.SUCCEEDED
    assert {effect.kind for effect in result.effects} == {
        DeletionEffectKind.REMOVE_TENANT_IDENTITIES_AND_RELEASE_PHONES,
        DeletionEffectKind.MARK_TENANT_AND_DATABASE_UUIDS_PERMANENTLY_UNREUSABLE,
    }
    replay = complete_deletion(
        result.state,
        evidence=_cleanup(result.state),
        expected_request_revision=0,
    )
    assert replay.idempotent_replay
    assert replay.state is result.state


@pytest.mark.parametrize(
    ("factory", "resume_status"),
    [
        (_committing, DeletionRequestStatus.COMMITTING),
        (_awaiting_ack, DeletionRequestStatus.AWAITING_OFFSITE_ACK),
        (_claim_releasing, DeletionRequestStatus.RELEASING_CLAIMS),
        (_dropping, DeletionRequestStatus.DROPPING),
    ],
)
def test_irreversible_failure_keeps_high_priority_deny_and_retry_boundary(
    factory: object,
    resume_status: DeletionRequestStatus,
) -> None:
    state = factory()  # type: ignore[operator]
    assert state.request is not None
    failed = fail_irreversible_deletion_step(
        state,
        failure_code="EXECUTOR_TIMEOUT",
        action_id=COMMIT_ACTION,
        expected_request_revision=state.request.revision,
        expected_access_version=state.tenant_access_version,
        expected_execution_generation=state.request.execution_generation,
        expected_executor_fencing_token=state.request.executor_fencing_token,
        lease_fence_verified=True,
    ).state
    assert failed.request is not None
    assert failed.request.status is DeletionRequestStatus.FAILED
    assert failed.request.failure_resume_status is resume_status
    assert failed.tenant_status is TenantStatus.DELETION_COMMITTING
    assert failed.desired_dml_login_state is DmlLoginState.LOCKED
    old_generation = failed.request.execution_generation
    old_fencing_token = failed.request.executor_fencing_token
    retry = retry_failed_deletion(
        failed,
        action_id=COMMIT_ACTION,
        idempotency_key="commit-delete",
        request_digest=COMMIT_DIGEST,
        expected_request_revision=failed.request.revision,
        expected_access_version=failed.tenant_access_version,
        expected_execution_generation=old_generation,
        expected_executor_fencing_token=old_fencing_token,
        lease_fence_verified=True,
    )
    assert retry.state.request is not None
    assert retry.state.request.status is resume_status
    assert retry.state.request.execution_generation == old_generation + 1
    assert retry.state.request.executor_fencing_token == old_fencing_token + 1
    assert retry.state.request.current_action.outcome is DeletionActionOutcome.RUNNING
    assert retry.state.tenant_status is TenantStatus.DELETION_COMMITTING
    assert all(
        effect.execution_generation == old_generation + 1 for effect in retry.effects
    )
    assert all(
        effect.executor_fencing_token == old_fencing_token + 1
        for effect in retry.effects
    )


def test_claim_release_crash_retry_fences_old_evidence_and_never_emits_drop() -> None:
    releasing = _claim_releasing()
    assert releasing.request is not None
    stale_evidence = _claim_release(releasing)
    failed = fail_irreversible_deletion_step(
        releasing,
        failure_code="CLAIM_RELEASE_TIMEOUT",
        action_id=COMMIT_ACTION,
        expected_request_revision=releasing.request.revision,
        expected_access_version=releasing.tenant_access_version,
        expected_execution_generation=releasing.request.execution_generation,
        expected_executor_fencing_token=releasing.request.executor_fencing_token,
        lease_fence_verified=True,
    ).state
    assert failed.request is not None
    retry = retry_failed_deletion(
        failed,
        action_id=COMMIT_ACTION,
        idempotency_key="commit-delete",
        request_digest=COMMIT_DIGEST,
        expected_request_revision=failed.request.revision,
        expected_access_version=failed.tenant_access_version,
        expected_execution_generation=failed.request.execution_generation,
        expected_executor_fencing_token=failed.request.executor_fencing_token,
        lease_fence_verified=True,
    )
    assert retry.state.request is not None
    assert retry.state.request.status is DeletionRequestStatus.RELEASING_CLAIMS
    kinds = {effect.kind for effect in retry.effects}
    assert kinds == {
        DeletionEffectKind.RELEASE_TENANT_PROVIDER_CLAIMS,
        DeletionEffectKind.APPEND_PROVIDER_CLAIM_RELEASE_EVENTS,
        DeletionEffectKind.ISOLATE_PROVIDER_OPERATIONS,
    }
    assert DeletionEffectKind.DROP_TENANT_SCHEMA not in kinds
    _assert_error(
        "STALE_DELETION_GENERATION_EVIDENCE",
        lambda: begin_destructive_cleanup(
            retry.state,
            evidence=stale_evidence,
            expected_request_revision=retry.state.request.revision,
            expected_access_version=retry.state.tenant_access_version,
            expected_execution_generation=retry.state.request.execution_generation,
            expected_executor_fencing_token=retry.state.request.executor_fencing_token,
            lease_fence_verified=True,
        ),
    )


def test_old_claim_and_cleanup_replays_do_not_repeat_or_reverse_effects() -> None:
    dropping = _dropping()
    assert dropping.request is not None
    claim_replay = begin_provider_claim_release(
        dropping,
        expected_request_revision=0,
        expected_access_version=0,
        expected_execution_generation=0,
        expected_executor_fencing_token=0,
        lease_fence_verified=False,
    )
    assert claim_replay.idempotent_replay
    assert claim_replay.effects == ()
    cleanup_replay = begin_destructive_cleanup(
        dropping,
        evidence=_claim_release(dropping, lease_fence_verified=False),
        expected_request_revision=0,
        expected_access_version=0,
        expected_execution_generation=0,
        expected_executor_fencing_token=0,
        lease_fence_verified=False,
    )
    assert cleanup_replay.idempotent_replay
    assert cleanup_replay.effects == ()


def test_failed_irreversible_action_rejects_cancellation_and_wrong_retry_action() -> None:
    committing = _committing()
    assert committing.request is not None
    failed = fail_irreversible_deletion_step(
        committing,
        failure_code="EXECUTOR_TIMEOUT",
        action_id=COMMIT_ACTION,
        expected_request_revision=committing.request.revision,
        expected_access_version=committing.tenant_access_version,
        expected_execution_generation=committing.request.execution_generation,
        expected_executor_fencing_token=committing.request.executor_fencing_token,
        lease_fence_verified=True,
    ).state
    assert failed.request is not None
    _assert_error(
        "DELETION_NOT_IN_COOLING_OFF",
        lambda: request_deletion_cancellation(
            failed,
            context=_context(now=NOW + timedelta(days=31)),
            action_id=CANCEL_ACTION,
            idempotency_key="cancel-delete",
            request_digest=CANCEL_DIGEST,
            cancelled_by_user_id=ADMIN_ID,
            actor_is_active_admin=True,
            purpose_bound_otp_verified=True,
            expected_request_revision=failed.request.revision,
            expected_access_version=failed.tenant_access_version,
            expected_execution_generation=failed.request.execution_generation,
            expected_executor_fencing_token=failed.request.executor_fencing_token,
        ),
    )
    _assert_error(
        "DELETION_RETRY_ACTION_MISMATCH",
        lambda: retry_failed_deletion(
            failed,
            action_id=uuid4(),
            idempotency_key="commit-delete",
            request_digest=COMMIT_DIGEST,
            expected_request_revision=failed.request.revision,
            expected_access_version=failed.tenant_access_version,
            expected_execution_generation=failed.request.execution_generation,
            expected_executor_fencing_token=failed.request.executor_fencing_token,
            lease_fence_verified=True,
        ),
    )


def test_all_transitions_are_immutable_and_never_mutate_subscription_facts() -> None:
    state = _cooling()
    with pytest.raises(FrozenInstanceError):
        state.tenant_access_version = 99  # type: ignore[misc]
    assert state.request is not None
    with pytest.raises(FrozenInstanceError):
        state.request.status = DeletionRequestStatus.COMPLETED  # type: ignore[misc]
    assert DELETION_COOLING_PERIOD == timedelta(days=30)


def test_times_are_normalized_to_utc_and_naive_time_fails_closed() -> None:
    china = timezone(timedelta(hours=8))
    context = _context(now=NOW.astimezone(china))
    assert context.database_now_utc.tzinfo is timezone.utc
    assert context.database_now_utc == NOW
    _assert_error(
        "INVALID_DATABASE_TIME",
        lambda: _context(
            now=datetime(2026, 8, 22, 10, 0),
            expires=NOW + timedelta(days=90),
        ),
    )


def test_stale_request_access_generation_and_evidence_are_rejected() -> None:
    cooling = _cooling()
    assert cooling.request is not None
    deadline = cooling.request.execute_not_before_utc
    for changes, code in (
        ({"expected_request_revision": 2}, "STALE_DELETION_REQUEST_REVISION"),
        ({"expected_access_version": 1}, "STALE_TENANT_ACCESS_VERSION"),
        (
            {"expected_execution_generation": 1},
            "STALE_DELETION_EXECUTION_GENERATION",
        ),
        (
            {"expected_executor_fencing_token": 1},
            "STALE_DELETION_EXECUTOR_FENCING_TOKEN",
        ),
        (
            {"lease_fence_verified": False},
            "DELETION_EXECUTOR_LEASE_FENCE_NOT_VERIFIED",
        ),
    ):
        arguments = {
            "action_id": COMMIT_ACTION,
            "idempotency_key": "commit-delete",
            "request_digest": COMMIT_DIGEST,
            "database_now_utc": deadline,
            "expected_request_revision": 3,
            "expected_access_version": 2,
            "expected_execution_generation": 2,
            "expected_executor_fencing_token": 2,
            "lease_fence_verified": True,
        }
        arguments.update(changes)
        _assert_error(code, lambda arguments=arguments: begin_deletion_commit(cooling, **arguments))
    committing = _committing()
    assert committing.request is not None
    _assert_error(
        "STALE_DELETION_GENERATION_EVIDENCE",
        lambda: record_permanent_tombstone(
            committing,
            tombstone=_tombstone(),
            evidence=_isolation(
                committing,
                execution_generation=committing.request.execution_generation - 1,
            ),
            expected_request_revision=committing.request.revision,
        ),
    )
    _assert_error(
        "STALE_DELETION_EXECUTOR_FENCE_EVIDENCE",
        lambda: record_permanent_tombstone(
            committing,
            tombstone=_tombstone(),
            evidence=_isolation(
                committing,
                executor_fencing_token=committing.request.executor_fencing_token - 1,
            ),
            expected_request_revision=committing.request.revision,
        ),
    )


def test_offsite_ack_requires_current_verified_executor_fence() -> None:
    awaiting = _awaiting_ack()
    assert awaiting.request is not None
    _assert_error(
        "STALE_DELETION_EXECUTOR_FENCE_EVIDENCE",
        lambda: confirm_offsite_tombstone(
            awaiting,
            acknowledgment=_ack(),
            executor_fence=_fence(
                awaiting,
                executor_fencing_token=awaiting.request.executor_fencing_token - 1,
            ),
            expected_request_revision=awaiting.request.revision,
        ),
    )
    _assert_error(
        "DELETION_EXECUTOR_LEASE_FENCE_NOT_VERIFIED",
        lambda: confirm_offsite_tombstone(
            awaiting,
            acknowledgment=_ack(),
            executor_fence=_fence(awaiting, lease_fence_verified=False),
            expected_request_revision=awaiting.request.revision,
        ),
    )


def test_action_digest_conflict_is_not_treated_as_idempotent() -> None:
    requested = _requested()
    _assert_error(
        "DELETION_ACTION_CONFLICT",
        lambda: request_deletion(
            requested,
            context=_context(),
            request_id=REQUEST_ID,
            action_id=REQUEST_ACTION,
            requested_by_user_id=ADMIN_ID,
            idempotency_key="delete-request",
            request_digest=b"z" * 32,
            requested_at_utc=NOW,
            actor_is_active_admin=True,
            purpose_bound_otp_verified=True,
            expected_access_version=1,
        ),
    )


@pytest.mark.parametrize(
    "failure_code",
    [
        "contains secret detail",
        "provider:error",
        "token=ABC123",
        "lowercase_detail",
        "/tmp/provider-response",
    ],
)
def test_invalid_hash_and_failure_code_are_rejected_without_sensitive_payloads(
    failure_code: str,
) -> None:
    _assert_error(
        "INVALID_TOMBSTONE_RECORD_HASH",
        lambda: _tombstone(record_hash=b"short"),
    )
    committing = _committing()
    assert committing.request is not None
    _assert_error(
        "INVALID_DELETION_FAILURE_CODE",
        lambda: fail_irreversible_deletion_step(
            committing,
            failure_code=failure_code,
            action_id=COMMIT_ACTION,
            expected_request_revision=committing.request.revision,
            expected_access_version=committing.tenant_access_version,
            expected_execution_generation=committing.request.execution_generation,
            expected_executor_fencing_token=committing.request.executor_fencing_token,
            lease_fence_verified=True,
        ),
    )


def test_unknown_or_inconsistent_lower_state_is_rejected() -> None:
    _assert_error(
        "INCONSISTENT_SUSPENSION_CONTEXT",
        lambda: _context(status=TenantStatus.ACTIVE, phase=SuspensionPhase.FREEZING),
    )
    _assert_error(
        "INVALID_DELETION_LOWER_PRIORITY_STATE",
        lambda: _context(status=TenantStatus.DELETION_COMMITTING),
    )


def test_tombstone_scope_and_completion_hash_are_fenced() -> None:
    committing = _committing()
    assert committing.request is not None
    _assert_error(
        "TOMBSTONE_SCOPE_MISMATCH",
        lambda: record_permanent_tombstone(
            committing,
            tombstone=_tombstone(tenant_id=uuid4()),
            evidence=_isolation(committing),
            expected_request_revision=committing.request.revision,
        ),
    )
    dropping = _dropping()
    assert dropping.request is not None
    _assert_error(
        "DELETION_COMPLETION_TOMBSTONE_MISMATCH",
        lambda: complete_deletion(
            dropping,
            evidence=_cleanup(dropping, tombstone_head_hash=b"x" * 32),
            expected_request_revision=dropping.request.revision,
        ),
    )


def test_idempotent_replays_do_not_repeat_effects() -> None:
    committing = _committing()
    replay = begin_deletion_commit(
        committing,
        action_id=COMMIT_ACTION,
        idempotency_key="commit-delete",
        request_digest=COMMIT_DIGEST,
        database_now_utc=NOW,
        expected_request_revision=0,
        expected_access_version=0,
        expected_execution_generation=0,
        expected_executor_fencing_token=0,
        lease_fence_verified=False,
    )
    assert replay.idempotent_replay
    assert replay.effects == ()
    awaiting = _awaiting_ack()
    assert awaiting.request is not None
    replay_tombstone = record_permanent_tombstone(
        awaiting,
        tombstone=_tombstone(),
        evidence=_isolation(awaiting),
        expected_request_revision=0,
    )
    assert replay_tombstone.idempotent_replay
    assert replay_tombstone.effects == ()
