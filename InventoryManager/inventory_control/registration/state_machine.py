"""Pure reducers for D54's fenced registration and replacement workflow."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from .types import (
    REGISTRATION_LOCK_ORDER,
    CodeFenceFacts,
    CommitEvidenceKind,
    CurrentRecoveryRunFacts,
    DatabaseProvisioningProof,
    FreshRegisterOtpProof,
    ImmutableEntitlementTerms,
    ObservedRegistrationAnchors,
    ProvisionalResourceFacts,
    RecoveryRunStatus,
    RegistrationAttemptState,
    RegistrationCodeStatus,
    RegistrationCommitEvidence,
    RegistrationCompletionConditions,
    RegistrationEffectFacts,
    RegistrationEffectKind,
    RegistrationOutcome,
    RegistrationPublishPlan,
    RegistrationStatus,
    RegistrationTransition,
    RegistrationTransitionError,
    RegistrationUserStatus,
    ReplacementLineage,
    ReplacementPlan,
    RevisionFence,
    WorkerFence,
    WorkerLease,
)


PLATFORM_REGISTRATION_ACTIONS = frozenset({"issue_replacement_code"})
ORDINARY_REPLACEMENT_ELIGIBLE_STATES = frozenset(
    {
        RegistrationStatus.FAILED,
        RegistrationStatus.IDENTITY_CONFLICT,
        RegistrationStatus.SECURITY_BLOCKED,
    }
)
_RECOVERY_NONTERMINAL_STATES = frozenset(
    {
        RegistrationStatus.OTP_VERIFIED,
        RegistrationStatus.RESERVED,
        RegistrationStatus.PROVISIONING,
        RegistrationStatus.READY,
        RegistrationStatus.COMMITTING,
        RegistrationStatus.FAILED,
        RegistrationStatus.IDENTITY_CONFLICT,
        RegistrationStatus.SECURITY_BLOCKED,
    }
)
_SAFE_REASON = re.compile(r"[a-z0-9_.:-]{1,64}", re.ASCII)


def create_otp_verified_attempt(
    *,
    attempt_uuid: UUID,
    tenant_uuid: UUID,
    database_uuid: UUID,
    code_uuid: UUID,
    requested_name_digest: bytes,
    entitlement_terms: ImmutableEntitlementTerms,
    otp_proof: FreshRegisterOtpProof,
    current_run: CurrentRecoveryRunFacts,
    user_status: RegistrationUserStatus,
    user_has_unreleased_membership: bool,
    database_now: datetime,
) -> RegistrationTransition:
    """Create no durable capability until a fresh register OTP is current."""

    if not isinstance(otp_proof, FreshRegisterOtpProof):
        raise TypeError("otp_proof is invalid")
    if not otp_proof.is_current_at(database_now):
        raise RegistrationTransitionError("REGISTRATION_OTP_STALE")
    _require_registration_user_available(
        user_status=user_status,
        has_unreleased_membership=user_has_unreleased_membership,
    )
    _require_permitting_run(current_run)
    state = RegistrationAttemptState(
        attempt_uuid=attempt_uuid,
        user_uuid=otp_proof.user_uuid,
        canonical_phone_e164=otp_proof.canonical_phone_e164,
        phone_normalization_version=otp_proof.phone_normalization_version,
        tenant_uuid=tenant_uuid,
        database_uuid=database_uuid,
        code_uuid=code_uuid,
        requested_name_digest=requested_name_digest,
        entitlement_terms=entitlement_terms,
        created_under_recovery_run_uuid=current_run.run_uuid,
        status=RegistrationStatus.OTP_VERIFIED,
        provisioning_generation=1,
        state_revision=1,
        last_register_otp_challenge_uuid=otp_proof.challenge_uuid,
    )
    return _transition(
        before=None,
        after=state,
        outcome=RegistrationOutcome.OTP_VERIFIED,
        effects=(),
        effect_facts=_effect_facts(state, state, preserve=False),
        completion=_completion(
            "fresh register OTP consumed",
            "current recovery run completed",
            "user has no unreleased membership",
        ),
    )


def reserve_registration_code(
    state: RegistrationAttemptState,
    *,
    code: CodeFenceFacts,
    current_run: CurrentRecoveryRunFacts,
    database_now: datetime,
) -> RegistrationTransition:
    """Bind one current-run active code permanently to this user and attempt."""

    _require_state(state, RegistrationStatus.OTP_VERIFIED)
    if not current_run.permits_registration:
        return enter_recovery_review(state, current_run=current_run)
    _require_permitting_run_for_attempt(state, current_run)
    _require_code_identity_and_terms(state, code)
    _require_time_compatible(code.redeem_before, database_now)
    if (
        code.status is not RegistrationCodeStatus.ACTIVE
        or not code.revision.matches
        or code.created_under_recovery_run_uuid != current_run.run_uuid
        or code.redeem_before <= database_now
    ):
        raise RegistrationTransitionError("REGISTRATION_CODE_NOT_RESERVABLE")
    after = replace(
        state,
        status=RegistrationStatus.RESERVED,
        state_revision=state.state_revision + 1,
    )
    return _transition(
        before=state,
        after=after,
        outcome=RegistrationOutcome.CODE_RESERVED,
        effects=(RegistrationEffectKind.RESERVE_CODE_TO_ATTEMPT,),
        effect_facts=_effect_facts(state, after, preserve=True),
        completion=_completion(
            "code is reserved to immutable user and attempt UUIDs",
            "code entitlement snapshot remains unchanged",
            "reservation and attempt transition commit atomically",
        ),
    )


def start_provisioning(
    state: RegistrationAttemptState,
    *,
    lease: WorkerLease,
    database_now: datetime,
) -> RegistrationTransition:
    """Start one fenced execution without changing the code reservation."""

    if state.status is RegistrationStatus.PROVISIONING:
        if state.active_lease == lease and _lease_is_current(lease, database_now):
            return _idempotent(state)
        raise RegistrationTransitionError("REGISTRATION_WORKER_FENCE_STALE")
    _require_state(state, RegistrationStatus.RESERVED)
    _require_new_lease(lease, state.provisioning_generation, database_now)
    after = replace(
        state,
        status=RegistrationStatus.PROVISIONING,
        state_revision=state.state_revision + 1,
        active_lease=lease,
    )
    return _transition(
        before=state,
        after=after,
        outcome=RegistrationOutcome.PROVISIONING_STARTED,
        effects=(RegistrationEffectKind.ISSUE_WORKER_LEASE,),
        effect_facts=_effect_facts(
            state, after, preserve=True, issued_lease=lease
        ),
        completion=_worker_completion(
            "worker lease generation and fencing token persisted"
        ),
    )


def mark_database_ready(
    state: RegistrationAttemptState,
    *,
    fence: WorkerFence,
    proof: DatabaseProvisioningProof,
    database_now: datetime,
) -> RegistrationTransition:
    """Accept smoke evidence only from the current fenced worker."""

    if state.status is RegistrationStatus.READY:
        _require_worker_fence(state, fence, database_now)
        if state.database_proof == proof:
            return _idempotent(state)
        raise RegistrationTransitionError("REGISTRATION_DATABASE_PROOF_CONFLICT")
    _require_state(state, RegistrationStatus.PROVISIONING)
    _require_worker_fence(state, fence, database_now)
    _require_database_proof(state, proof, fence)
    after = replace(
        state,
        status=RegistrationStatus.READY,
        state_revision=state.state_revision + 1,
        database_proof=proof,
    )
    return _transition(
        before=state,
        after=after,
        outcome=RegistrationOutcome.DATABASE_READY,
        effects=(RegistrationEffectKind.RECORD_DATABASE_PROOF,),
        effect_facts=_effect_facts(
            state, after, preserve=True, database_proof=proof
        ),
        completion=_worker_completion(
            "database_identity and schema digest match immutable UUIDs",
            "smoke passed under backup/DDL lease and advisory lock",
            "business route remains unpublished",
        ),
    )


def record_provisioning_failure(
    state: RegistrationAttemptState,
    *,
    fence: WorkerFence,
    code: CodeFenceFacts,
    safe_reason_code: str,
    database_now: datetime,
) -> RegistrationTransition:
    """Fail the execution while retaining the permanent source reservation."""

    if state.status not in {RegistrationStatus.PROVISIONING, RegistrationStatus.READY}:
        raise RegistrationTransitionError("REGISTRATION_TRANSITION_REJECTED")
    _require_safe_reason(safe_reason_code)
    _require_worker_fence(state, fence, database_now)
    _require_reserved_code_binding(state, code)
    invalidated = state.active_lease.lease_uuid
    after = replace(
        state,
        status=RegistrationStatus.FAILED,
        state_revision=state.state_revision + 1,
        active_lease=None,
        database_proof=None,
    )
    return _blocked_reservation_transition(
        before=state,
        after=after,
        outcome=RegistrationOutcome.FAILED_RETAINING_RESERVATION,
        invalidated_lease_uuid=invalidated,
        predicate="source code remains reserved to original user and attempt",
    )


def record_identity_conflict(
    state: RegistrationAttemptState,
    *,
    fence: WorkerFence,
    code: CodeFenceFacts,
    database_now: datetime,
) -> RegistrationTransition:
    return _record_final_fence_block(
        state,
        fence=fence,
        code=code,
        database_now=database_now,
        status=RegistrationStatus.IDENTITY_CONFLICT,
        outcome=RegistrationOutcome.IDENTITY_BLOCKED_RETAINING_RESERVATION,
    )


def record_security_block(
    state: RegistrationAttemptState,
    *,
    fence: WorkerFence,
    code: CodeFenceFacts,
    database_now: datetime,
) -> RegistrationTransition:
    return _record_final_fence_block(
        state,
        fence=fence,
        code=code,
        database_now=database_now,
        status=RegistrationStatus.SECURITY_BLOCKED,
        outcome=RegistrationOutcome.SECURITY_BLOCKED_RETAINING_RESERVATION,
    )


def retry_failed_registration(
    state: RegistrationAttemptState,
    *,
    otp_proof: FreshRegisterOtpProof,
    code: CodeFenceFacts,
    current_run: CurrentRecoveryRunFacts,
    attempt_revision: RevisionFence,
    replacement_revision: RevisionFence,
    new_lease: WorkerLease,
    user_status: RegistrationUserStatus,
    user_has_unreleased_membership: bool,
    database_now: datetime,
) -> RegistrationTransition:
    """Only the original user with a new same-phone OTP may advance generation."""

    if state.status not in ORDINARY_REPLACEMENT_ELIGIBLE_STATES:
        raise RegistrationTransitionError("REGISTRATION_RETRY_NOT_ALLOWED")
    _require_attempt_revision(state, attempt_revision)
    _require_matching_revision(replacement_revision, "replacement")
    if not current_run.permits_registration:
        return enter_recovery_review(state, current_run=current_run)
    _require_permitting_run_for_attempt(state, current_run)
    _require_reserved_code_binding(state, code)
    _require_registration_user_available(
        user_status=user_status,
        has_unreleased_membership=user_has_unreleased_membership,
    )
    if (
        not otp_proof.is_current_at(database_now)
        or otp_proof.user_uuid != state.user_uuid
        or otp_proof.canonical_phone_e164 != state.canonical_phone_e164
        or otp_proof.phone_normalization_version
        != state.phone_normalization_version
        or otp_proof.challenge_uuid == state.last_register_otp_challenge_uuid
    ):
        raise RegistrationTransitionError("REGISTRATION_RETRY_OTP_MISMATCH")
    next_generation = state.provisioning_generation + 1
    _require_new_lease(new_lease, next_generation, database_now)
    after = replace(
        state,
        status=RegistrationStatus.PROVISIONING,
        provisioning_generation=next_generation,
        state_revision=state.state_revision + 1,
        last_register_otp_challenge_uuid=otp_proof.challenge_uuid,
        active_lease=new_lease,
        database_proof=None,
        commit_plan=None,
    )
    return _transition(
        before=state,
        after=after,
        outcome=RegistrationOutcome.USER_RETRY_STARTED,
        effects=(
            RegistrationEffectKind.PRESERVE_CODE_RESERVATION,
            RegistrationEffectKind.ISSUE_WORKER_LEASE,
        ),
        effect_facts=_effect_facts(
            state, after, preserve=True, issued_lease=new_lease
        ),
        completion=_completion(
            "same original user consumed a fresh register OTP",
            "canonical phone and immutable attempt inputs match",
            "generation advanced exactly once with a new worker lease",
            "code remains reserved and is never released or rebound",
        ),
    )


def begin_final_commit(
    state: RegistrationAttemptState,
    *,
    fence: WorkerFence,
    code: CodeFenceFacts,
    current_run: CurrentRecoveryRunFacts,
    attempt_revision: RevisionFence,
    replacement_revision: RevisionFence,
    current_replacement_action_uuid: UUID | None,
    commit_evidence: RegistrationCommitEvidence,
    user_status: RegistrationUserStatus,
    user_has_unreleased_membership: bool,
    current_database_proof: DatabaseProvisioningProof,
    publish_plan: RegistrationPublishPlan,
    database_now: datetime,
) -> RegistrationTransition:
    """Plan the one atomic publish transaction after every current-read fence."""

    if state.status is RegistrationStatus.COMMITTING:
        _require_worker_fence(state, fence, database_now)
        if state.commit_plan == publish_plan:
            return _idempotent(state)
        raise RegistrationTransitionError("REGISTRATION_COMMIT_INTENT_CONFLICT")
    _require_state(state, RegistrationStatus.READY)
    _require_worker_fence(state, fence, database_now)
    _require_attempt_revision(state, attempt_revision)
    _require_matching_revision(replacement_revision, "replacement")

    evidence_transition = _handle_commit_evidence(
        state,
        evidence=commit_evidence,
        publish_plan=publish_plan,
        code=code,
    )
    if evidence_transition is not None:
        return evidence_transition
    if not current_run.permits_registration:
        return enter_recovery_review(state, current_run=current_run)
    _require_permitting_run_for_attempt(state, current_run)
    if current_replacement_action_uuid is not None:
        raise RegistrationTransitionError("REGISTRATION_REPLACEMENT_FENCE_LOST")
    if user_status is RegistrationUserStatus.DISABLED:
        return record_security_block(
            state, fence=fence, code=code, database_now=database_now
        )
    if user_has_unreleased_membership:
        return record_identity_conflict(
            state, fence=fence, code=code, database_now=database_now
        )
    if user_status is not RegistrationUserStatus.ACTIVE:
        raise RegistrationTransitionError("REGISTRATION_USER_NOT_ACTIVE")
    _require_reserved_code_binding(state, code)
    if state.database_proof != current_database_proof:
        raise RegistrationTransitionError("REGISTRATION_DATABASE_FENCE_LOST")
    _require_database_proof(state, current_database_proof, fence)

    after = replace(
        state,
        status=RegistrationStatus.COMMITTING,
        state_revision=state.state_revision + 1,
        commit_plan=publish_plan,
    )
    effects = (
        RegistrationEffectKind.CREATE_REGISTRATION_COMMIT,
        RegistrationEffectKind.CREATE_FIRST_ADMIN_MEMBERSHIP,
        RegistrationEffectKind.CREATE_SUBSCRIPTION,
        RegistrationEffectKind.APPEND_SUBSCRIPTION_EVENT,
        RegistrationEffectKind.CREATE_RELEASED_HOLD_BASELINE,
        RegistrationEffectKind.CLAIM_PUBLIC_NAME,
        RegistrationEffectKind.PUBLISH_INITIAL_ROUTE,
        RegistrationEffectKind.REDEEM_RESERVED_CODE,
        RegistrationEffectKind.SUPERSEDE_PHONE_INVITATIONS,
    )
    return _transition(
        before=state,
        after=after,
        outcome=RegistrationOutcome.COMMIT_STARTED,
        effects=effects,
        effect_facts=_effect_facts(
            state,
            after,
            preserve=True,
            database_proof=current_database_proof,
            publish_plan=publish_plan,
        ),
        completion=_completion(
            "generation and worker lease still match",
            "code remains reserved to exact user and attempt",
            "replacement lineage is absent at current revision",
            "current recovery run and external marker remain completed",
            "database proof matches immutable tenant/database UUIDs",
            "all publish anchors and invitation releases commit atomically",
            atomic=True,
        ),
    )


def complete_final_commit(
    state: RegistrationAttemptState,
    *,
    fence: WorkerFence,
    code: CodeFenceFacts,
    current_run: CurrentRecoveryRunFacts,
    attempt_revision: RevisionFence,
    replacement_revision: RevisionFence,
    observed_anchors: ObservedRegistrationAnchors,
    database_now: datetime,
) -> RegistrationTransition:
    """Confirm active only when every immutable publish anchor agrees."""

    _require_state(state, RegistrationStatus.COMMITTING)
    _require_worker_fence(state, fence, database_now)
    _require_attempt_revision(state, attempt_revision)
    _require_matching_revision(replacement_revision, "replacement")
    if not current_run.permits_registration:
        return enter_recovery_review(state, current_run=current_run)
    _require_permitting_run_for_attempt(state, current_run)
    if not _redeemed_code_matches_state(
        state,
        code,
        commit_uuid=state.commit_plan.registration_commit_uuid,
    ):
        return _integrity_block(
            state,
            reason="registration_code_anchor_mismatch",
            preserve_code=True,
        )
    if not _anchors_match_state(state, observed_anchors):
        return _integrity_block(
            state,
            reason="registration_anchor_mismatch",
            preserve_code=True,
        )
    invalidated = state.active_lease.lease_uuid
    after = replace(
        state,
        status=RegistrationStatus.ACTIVE,
        state_revision=state.state_revision + 1,
        active_lease=None,
        registration_commit_uuid=state.commit_plan.registration_commit_uuid,
    )
    return _transition(
        before=state,
        after=after,
        outcome=RegistrationOutcome.ACTIVATED,
        effects=(RegistrationEffectKind.INVALIDATE_WORKER_LEASE,),
        effect_facts=_effect_facts(
            state,
            after,
            preserve=True,
            invalidated_lease_uuid=invalidated,
            database_proof=state.database_proof,
            publish_plan=state.commit_plan,
        ),
        completion=_completion(
            "immutable registration commit and all source anchors agree",
            "code is redeemed to the same commit UUID",
            "route was not published before the atomic control transaction",
            atomic=True,
        ),
    )


def request_replacement(
    state: RegistrationAttemptState,
    *,
    code: CodeFenceFacts,
    current_run: CurrentRecoveryRunFacts,
    attempt_revision: RevisionFence,
    replacement_revision: RevisionFence,
    current_replacement_action_uuid: UUID | None,
    commit_evidence: RegistrationCommitEvidence,
    replacement_plan: ReplacementPlan,
    provisional_resources: ProvisionalResourceFacts,
    database_now: datetime,
    committed_publish_plan: RegistrationPublishPlan | None = None,
) -> RegistrationTransition:
    """Fence one eligible source and issue exactly one copied successor."""

    if state.status is RegistrationStatus.SUPERSEDED_BY_REPLACEMENT:
        if _replacement_is_replay(state.replacement_lineage, replacement_plan):
            return _transition(
                before=state,
                after=state,
                outcome=RegistrationOutcome.REPLACEMENT_REPLAY,
                effects=(),
                effect_facts=_effect_facts(state, state, preserve=True),
                completion=_completion(
                    "caller returns the already persisted successor metadata"
                ),
            )
        raise RegistrationTransitionError("REGISTRATION_REPLACEMENT_ALREADY_EXISTS")
    if state.status not in ORDINARY_REPLACEMENT_ELIGIBLE_STATES:
        raise RegistrationTransitionError("REGISTRATION_REPLACEMENT_NOT_ALLOWED")
    _require_attempt_revision(state, attempt_revision)
    _require_matching_revision(replacement_revision, "replacement")
    _require_replacement_resource_fence(state, provisional_resources)

    if commit_evidence.kind in {
        CommitEvidenceKind.PARTIAL,
        CommitEvidenceKind.INCONSISTENT,
    }:
        return _integrity_block(
            state,
            reason=commit_evidence.safe_incident_reason,
            preserve_code=True,
        )
    if commit_evidence.kind is CommitEvidenceKind.COMPLETE:
        if committed_publish_plan is None:
            raise RegistrationTransitionError(
                "REGISTRATION_COMMIT_ANCHORS_REQUIRED"
            )
        if (
            committed_publish_plan.registration_commit_uuid
            != commit_evidence.registration_commit_uuid
        ):
            return _integrity_block(
                state,
                reason="registration_commit_uuid_mismatch",
                preserve_code=True,
            )
        if not _redeemed_code_matches_state(
            state,
            code,
            commit_uuid=commit_evidence.registration_commit_uuid,
        ):
            return _integrity_block(
                state,
                reason="registration_code_anchor_mismatch",
                preserve_code=True,
            )
        after = replace(
            state,
            status=RegistrationStatus.ACTIVE,
            state_revision=state.state_revision + 1,
            active_lease=None,
            database_proof=None,
            commit_plan=committed_publish_plan,
            registration_commit_uuid=commit_evidence.registration_commit_uuid,
        )
        return _transition(
            before=state,
            after=after,
            outcome=RegistrationOutcome.COMMITTED_HISTORY_RECONCILED,
            effects=(RegistrationEffectKind.RECONCILE_COMPLETE_COMMIT,),
            effect_facts=_effect_facts(state, after, preserve=True),
            completion=_completion(
                "complete immutable commit history is authoritative",
                "no replacement code is created",
                atomic=True,
            ),
        )

    if not current_run.permits_registration:
        return enter_recovery_review(state, current_run=current_run)
    _require_permitting_run_for_attempt(state, current_run)
    _require_reserved_code_binding(state, code)
    if current_replacement_action_uuid is not None:
        raise RegistrationTransitionError("REGISTRATION_REPLACEMENT_ALREADY_EXISTS")
    _require_time_compatible(replacement_plan.new_redeem_before, database_now)
    if replacement_plan.new_redeem_before <= database_now:
        raise RegistrationTransitionError("REGISTRATION_REPLACEMENT_DEADLINE_INVALID")

    lineage = ReplacementLineage(
        source_code_uuid=state.code_uuid,
        source_attempt_uuid=state.attempt_uuid,
        replacement_action_uuid=replacement_plan.replacement_action_uuid,
        successor_code_uuid=replacement_plan.successor_code_uuid,
        successor_batch_uuid=replacement_plan.successor_batch_uuid,
        successor_crypto_context_uuid=(
            replacement_plan.successor_crypto_context_uuid
        ),
        created_under_recovery_run_uuid=current_run.run_uuid,
        new_redeem_before=replacement_plan.new_redeem_before,
        idempotency_key=replacement_plan.idempotency_key,
        copied_entitlement_terms=state.entitlement_terms,
    )
    next_generation = state.provisioning_generation + 1
    invalidated = (
        state.active_lease.lease_uuid if state.active_lease is not None else None
    )
    after = replace(
        state,
        status=RegistrationStatus.SUPERSEDED_BY_REPLACEMENT,
        provisioning_generation=next_generation,
        state_revision=state.state_revision + 1,
        active_lease=None,
        database_proof=None,
        commit_plan=None,
        replacement_lineage=lineage,
    )
    effects = [
        RegistrationEffectKind.INVALIDATE_WORKER_LEASE,
        RegistrationEffectKind.REVOKE_SOURCE_CODE_AS_REPLACED,
        RegistrationEffectKind.CREATE_REPLACEMENT_LINEAGE,
        RegistrationEffectKind.CREATE_SUCCESSOR_CODE,
    ]
    if provisional_resources.has_any:
        effects.append(RegistrationEffectKind.CREATE_SYSTEM_CLEANUP_OUTBOX)
    return _transition(
        before=state,
        after=after,
        outcome=RegistrationOutcome.REPLACEMENT_ISSUED,
        effects=tuple(effects),
        effect_facts=_effect_facts(
            state,
            after,
            preserve=True,
            invalidated_lease_uuid=invalidated,
            replacement_lineage=lineage,
            cleanup_outbox_required=provisional_resources.has_any,
        ),
        completion=_completion(
            "complete commit and every source-linked anchor are absent",
            "attempt generation advances and old lease is invalidated",
            "source code becomes permanently revoked as replaced",
            "successor copies exact plan revision, entitlement digest and duration",
            "one source code and attempt have at most one lineage",
            "cleanup outbox exists only when provisional resources exist",
            atomic=True,
        ),
    )


def enter_recovery_review(
    state: RegistrationAttemptState,
    *,
    current_run: CurrentRecoveryRunFacts,
) -> RegistrationTransition:
    """Monotonically isolate every nonterminal attempt during host recovery."""

    if current_run.permits_registration:
        raise RegistrationTransitionError("REGISTRATION_RECOVERY_REVIEW_NOT_REQUIRED")
    if state.status is RegistrationStatus.RECOVERY_REVIEW:
        if state.recovery_review_run_uuid == current_run.run_uuid:
            return _idempotent(state)
        raise RegistrationTransitionError("REGISTRATION_RECOVERY_RUN_MISMATCH")
    if state.status not in _RECOVERY_NONTERMINAL_STATES:
        raise RegistrationTransitionError("REGISTRATION_TERMINAL")
    invalidated = (
        state.active_lease.lease_uuid if state.active_lease is not None else None
    )
    after = replace(
        state,
        status=RegistrationStatus.RECOVERY_REVIEW,
        provisioning_generation=state.provisioning_generation + 1,
        state_revision=state.state_revision + 1,
        active_lease=None,
        database_proof=None,
        commit_plan=None,
        recovery_review_run_uuid=current_run.run_uuid,
        status_before_recovery_review=state.status,
    )
    effects = [RegistrationEffectKind.MARK_CODE_RECOVERY_REVOKED]
    if invalidated is not None:
        effects.insert(0, RegistrationEffectKind.INVALIDATE_WORKER_LEASE)
    return _transition(
        before=state,
        after=after,
        outcome=RegistrationOutcome.RECOVERY_REVIEW,
        effects=tuple(effects),
        effect_facts=_effect_facts(
            state,
            after,
            preserve=True,
            invalidated_lease_uuid=invalidated,
        ),
        completion=_completion(
            "old worker generation and lease can never resume",
            "live source code is irreversibly recovery-revoked",
            "ordinary retry, final commit and replacement stay disabled",
            atomic=True,
        ),
    )


def _record_final_fence_block(
    state: RegistrationAttemptState,
    *,
    fence: WorkerFence,
    code: CodeFenceFacts,
    database_now: datetime,
    status: RegistrationStatus,
    outcome: RegistrationOutcome,
) -> RegistrationTransition:
    if state.status not in {RegistrationStatus.READY, RegistrationStatus.COMMITTING}:
        raise RegistrationTransitionError("REGISTRATION_TRANSITION_REJECTED")
    _require_worker_fence(state, fence, database_now)
    _require_reserved_code_binding(state, code)
    invalidated = state.active_lease.lease_uuid
    after = replace(
        state,
        status=status,
        state_revision=state.state_revision + 1,
        active_lease=None,
        database_proof=None,
        commit_plan=None,
    )
    return _blocked_reservation_transition(
        before=state,
        after=after,
        outcome=outcome,
        invalidated_lease_uuid=invalidated,
        predicate="security or identity block cannot consume the reserved code",
    )


def _handle_commit_evidence(
    state: RegistrationAttemptState,
    *,
    evidence: RegistrationCommitEvidence,
    publish_plan: RegistrationPublishPlan,
    code: CodeFenceFacts,
) -> RegistrationTransition | None:
    if evidence.kind is CommitEvidenceKind.ABSENT:
        return None
    if evidence.kind in {
        CommitEvidenceKind.PARTIAL,
        CommitEvidenceKind.INCONSISTENT,
    }:
        return _integrity_block(
            state,
            reason=evidence.safe_incident_reason,
            preserve_code=True,
        )
    if (
        evidence.registration_commit_uuid
        != publish_plan.registration_commit_uuid
        or not _redeemed_code_matches_state(
            state,
            code,
            commit_uuid=evidence.registration_commit_uuid,
        )
    ):
        return _integrity_block(
            state,
            reason="registration_commit_anchor_mismatch",
            preserve_code=True,
        )
    invalidated = state.active_lease.lease_uuid
    after = replace(
        state,
        status=RegistrationStatus.ACTIVE,
        state_revision=state.state_revision + 1,
        active_lease=None,
        database_proof=None,
        commit_plan=publish_plan,
        registration_commit_uuid=evidence.registration_commit_uuid,
    )
    return _transition(
        before=state,
        after=after,
        outcome=RegistrationOutcome.COMMITTED_HISTORY_RECONCILED,
        effects=(
            RegistrationEffectKind.INVALIDATE_WORKER_LEASE,
            RegistrationEffectKind.RECONCILE_COMPLETE_COMMIT,
        ),
        effect_facts=_effect_facts(
            state,
            after,
            preserve=True,
            invalidated_lease_uuid=invalidated,
            publish_plan=publish_plan,
        ),
        completion=_completion(
            "complete immutable commit history is authoritative",
            "no duplicate membership, subscription, route, or code effect occurs",
            atomic=True,
        ),
    )


def _integrity_block(
    state: RegistrationAttemptState,
    *,
    reason: str,
    preserve_code: bool,
) -> RegistrationTransition:
    _require_safe_reason(reason)
    invalidated = (
        state.active_lease.lease_uuid if state.active_lease is not None else None
    )
    after = replace(
        state,
        status=RegistrationStatus.INTEGRITY_BLOCKED,
        provisioning_generation=state.provisioning_generation + 1,
        state_revision=state.state_revision + 1,
        active_lease=None,
        database_proof=None,
        commit_plan=None,
        integrity_reason_code=reason,
    )
    effects = [RegistrationEffectKind.CREATE_INTEGRITY_INCIDENT]
    if invalidated is not None:
        effects.insert(0, RegistrationEffectKind.INVALIDATE_WORKER_LEASE)
    return _transition(
        before=state,
        after=after,
        outcome=RegistrationOutcome.INTEGRITY_BLOCKED,
        effects=tuple(effects),
        effect_facts=_effect_facts(
            state,
            after,
            preserve=preserve_code,
            invalidated_lease_uuid=invalidated,
            integrity_incident_reason=reason,
        ),
        completion=_completion(
            "unique internal integrity incident is persisted",
            "ordinary retry, replacement, commit and cleanup remain blocked",
            "source code and anchors are not repaired or released",
            atomic=True,
        ),
    )


def _blocked_reservation_transition(
    *,
    before: RegistrationAttemptState,
    after: RegistrationAttemptState,
    outcome: RegistrationOutcome,
    invalidated_lease_uuid: UUID,
    predicate: str,
) -> RegistrationTransition:
    return _transition(
        before=before,
        after=after,
        outcome=outcome,
        effects=(
            RegistrationEffectKind.INVALIDATE_WORKER_LEASE,
            RegistrationEffectKind.PRESERVE_CODE_RESERVATION,
        ),
        effect_facts=_effect_facts(
            before,
            after,
            preserve=True,
            invalidated_lease_uuid=invalidated_lease_uuid,
        ),
        completion=_completion(
            predicate,
            (
                "attempt, user, code, entitlement and requested-name snapshot "
                "stay immutable"
            ),
            atomic=True,
        ),
    )


def _require_database_proof(
    state: RegistrationAttemptState,
    proof: DatabaseProvisioningProof,
    fence: WorkerFence,
) -> None:
    if (
        proof.tenant_uuid != state.tenant_uuid
        or proof.database_uuid != state.database_uuid
        or proof.execution_generation != state.provisioning_generation
        or proof.worker_lease_uuid != fence.lease_uuid
        or proof.worker_fencing_token != fence.fencing_token
        or not proof.smoke_passed
        or not proof.backup_ddl_lease_held
        or not proof.database_advisory_lock_held
        or proof.business_route_published
        or not proof.default_warehouse_created
        or not proof.contact_phone_prefilled_unconfirmed
    ):
        raise RegistrationTransitionError("REGISTRATION_DATABASE_PROOF_INVALID")


def _require_replacement_resource_fence(
    state: RegistrationAttemptState,
    resources: ProvisionalResourceFacts,
) -> None:
    if not isinstance(resources, ProvisionalResourceFacts):
        raise TypeError("provisional_resources are invalid")
    active_lease_uuid = (
        state.active_lease.lease_uuid if state.active_lease is not None else None
    )
    if (
        resources.observed_generation != state.provisioning_generation
        or resources.observed_active_lease_uuid != active_lease_uuid
    ):
        raise RegistrationTransitionError("REGISTRATION_WORKER_FENCE_STALE")


def _require_worker_fence(
    state: RegistrationAttemptState,
    fence: WorkerFence,
    database_now: datetime,
) -> None:
    lease = state.active_lease
    if (
        lease is None
        or lease.lease_uuid != fence.lease_uuid
        or lease.execution_generation != fence.execution_generation
        or lease.fencing_token != fence.fencing_token
        or fence.execution_generation != state.provisioning_generation
        or not _lease_is_current(lease, database_now)
    ):
        raise RegistrationTransitionError("REGISTRATION_WORKER_FENCE_STALE")


def _require_new_lease(
    lease: WorkerLease, generation: int, database_now: datetime
) -> None:
    if lease.execution_generation != generation or not _lease_is_current(
        lease, database_now
    ):
        raise RegistrationTransitionError("REGISTRATION_WORKER_LEASE_INVALID")


def _lease_is_current(lease: WorkerLease, database_now: datetime) -> bool:
    _require_time_compatible(lease.expires_at, database_now)
    return lease.expires_at > database_now


def _require_reserved_code_binding(
    state: RegistrationAttemptState, code: CodeFenceFacts
) -> None:
    _require_code_identity_and_terms(state, code)
    if (
        code.status is not RegistrationCodeStatus.RESERVED
        or code.reserved_user_uuid != state.user_uuid
        or code.reserved_registration_attempt_uuid != state.attempt_uuid
        or code.created_under_recovery_run_uuid
        != state.created_under_recovery_run_uuid
        or not code.revision.matches
    ):
        raise RegistrationTransitionError("REGISTRATION_CODE_FENCE_LOST")


def _require_code_identity_and_terms(
    state: RegistrationAttemptState, code: CodeFenceFacts
) -> None:
    if (
        code.code_uuid != state.code_uuid
        or code.entitlement_terms != state.entitlement_terms
    ):
        raise RegistrationTransitionError("REGISTRATION_CODE_FENCE_LOST")


def _redeemed_code_matches_state(
    state: RegistrationAttemptState,
    code: CodeFenceFacts,
    *,
    commit_uuid: UUID,
) -> bool:
    return bool(
        code.status is RegistrationCodeStatus.REDEEMED
        and code.code_uuid == state.code_uuid
        and code.registration_commit_uuid == commit_uuid
        and code.reserved_user_uuid == state.user_uuid
        and code.reserved_registration_attempt_uuid == state.attempt_uuid
        and code.created_under_recovery_run_uuid
        == state.created_under_recovery_run_uuid
        and code.entitlement_terms == state.entitlement_terms
        and code.revision.matches
    )


def _require_permitting_run_for_attempt(
    state: RegistrationAttemptState, current_run: CurrentRecoveryRunFacts
) -> None:
    _require_permitting_run(current_run)
    if current_run.run_uuid != state.created_under_recovery_run_uuid:
        raise RegistrationTransitionError("REGISTRATION_RECOVERY_FENCE_LOST")


def _require_permitting_run(current_run: CurrentRecoveryRunFacts) -> None:
    if not current_run.permits_registration:
        raise RegistrationTransitionError("REGISTRATION_RECOVERY_NOT_COMPLETED")


def _require_attempt_revision(
    state: RegistrationAttemptState, fence: RevisionFence
) -> None:
    if not fence.matches or fence.current != state.state_revision:
        raise RegistrationTransitionError("REGISTRATION_ATTEMPT_FENCE_LOST")


def _require_matching_revision(fence: RevisionFence, subject: str) -> None:
    if not fence.matches:
        raise RegistrationTransitionError(
            f"REGISTRATION_{subject.upper()}_FENCE_LOST"
        )


def _require_registration_user_available(
    *,
    user_status: RegistrationUserStatus,
    has_unreleased_membership: bool,
) -> None:
    if not isinstance(user_status, RegistrationUserStatus):
        raise TypeError("user_status is invalid")
    if not isinstance(has_unreleased_membership, bool):
        raise TypeError("has_unreleased_membership must be a bool")
    if user_status is RegistrationUserStatus.DISABLED:
        raise RegistrationTransitionError("REGISTRATION_SECURITY_BLOCKED")
    if user_status is not RegistrationUserStatus.ACTIVE:
        raise RegistrationTransitionError("REGISTRATION_USER_NOT_ACTIVE")
    if has_unreleased_membership:
        raise RegistrationTransitionError("REGISTRATION_IDENTITY_CONFLICT")


def _anchors_match_state(
    state: RegistrationAttemptState,
    observed: ObservedRegistrationAnchors,
) -> bool:
    return bool(
        observed.is_complete
        and observed.publish_plan == state.commit_plan
        and observed.code_uuid == state.code_uuid
        and observed.user_uuid == state.user_uuid
        and observed.attempt_uuid == state.attempt_uuid
        and observed.tenant_uuid == state.tenant_uuid
        and observed.entitlement_terms == state.entitlement_terms
    )


def _replacement_is_replay(
    lineage: ReplacementLineage, plan: ReplacementPlan
) -> bool:
    return bool(
        lineage.replacement_action_uuid == plan.replacement_action_uuid
        and lineage.successor_code_uuid == plan.successor_code_uuid
        and lineage.successor_batch_uuid == plan.successor_batch_uuid
        and lineage.successor_crypto_context_uuid
        == plan.successor_crypto_context_uuid
        and lineage.new_redeem_before == plan.new_redeem_before
        and lineage.idempotency_key == plan.idempotency_key
    )


def _require_state(
    state: RegistrationAttemptState, required: RegistrationStatus
) -> None:
    if not isinstance(state, RegistrationAttemptState):
        raise TypeError("state is invalid")
    if state.status is not required:
        raise RegistrationTransitionError("REGISTRATION_TRANSITION_REJECTED")


def _require_safe_reason(reason: str) -> None:
    if not isinstance(reason, str) or _SAFE_REASON.fullmatch(reason) is None:
        raise ValueError("safe reason code is invalid")


def _require_time_compatible(first: datetime, second: datetime) -> None:
    if not isinstance(first, datetime) or not isinstance(second, datetime):
        raise TypeError("registration times must be datetimes")
    if first.tzinfo != second.tzinfo:
        raise ValueError("registration times must use one timezone form")


def _effect_facts(
    before: RegistrationAttemptState,
    after: RegistrationAttemptState,
    *,
    preserve: bool,
    invalidated_lease_uuid: UUID | None = None,
    issued_lease: WorkerLease | None = None,
    database_proof: DatabaseProvisioningProof | None = None,
    publish_plan: RegistrationPublishPlan | None = None,
    replacement_lineage: ReplacementLineage | None = None,
    cleanup_outbox_required: bool = False,
    integrity_incident_reason: str | None = None,
) -> RegistrationEffectFacts:
    return RegistrationEffectFacts(
        previous_generation=before.provisioning_generation,
        current_generation=after.provisioning_generation,
        preserve_code_binding=preserve,
        invalidated_lease_uuid=invalidated_lease_uuid,
        issued_lease=issued_lease,
        database_proof=database_proof,
        publish_plan=publish_plan,
        replacement_lineage=replacement_lineage,
        cleanup_outbox_required=cleanup_outbox_required,
        integrity_incident_reason=integrity_incident_reason,
    )


def _completion(
    *predicates: str,
    atomic: bool = False,
) -> RegistrationCompletionConditions:
    return RegistrationCompletionConditions(
        required_lock_order=REGISTRATION_LOCK_ORDER,
        require_atomic_control_transaction=atomic,
        no_publish_before_all_fences=True,
        code_binding_must_match=True,
        completion_predicates=tuple(predicates),
    )


def _worker_completion(*predicates: str) -> RegistrationCompletionConditions:
    return RegistrationCompletionConditions(
        required_lock_order=(
            "global_backup_ddl_lease",
            "database_advisory_lock",
            "registration_attempt",
        ),
        require_atomic_control_transaction=False,
        no_publish_before_all_fences=True,
        code_binding_must_match=True,
        completion_predicates=tuple(predicates),
    )


def _transition(
    *,
    before: RegistrationAttemptState | None,
    after: RegistrationAttemptState,
    outcome: RegistrationOutcome,
    effects: tuple[RegistrationEffectKind, ...],
    effect_facts: RegistrationEffectFacts,
    completion: RegistrationCompletionConditions,
) -> RegistrationTransition:
    return RegistrationTransition(
        before=before,
        after=after,
        outcome=outcome,
        effects=effects,
        effect_facts=effect_facts,
        completion=completion,
    )


def _idempotent(state: RegistrationAttemptState) -> RegistrationTransition:
    return _transition(
        before=state,
        after=state,
        outcome=RegistrationOutcome.IDEMPOTENT_REPLAY,
        effects=(),
        effect_facts=_effect_facts(state, state, preserve=True),
        completion=_completion("previous identical transition is authoritative"),
    )
