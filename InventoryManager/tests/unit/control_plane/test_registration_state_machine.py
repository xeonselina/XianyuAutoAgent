from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from inventory_control.registration import (
    ORDINARY_REPLACEMENT_ELIGIBLE_STATES,
    PLATFORM_REGISTRATION_ACTIONS,
    REGISTRATION_LOCK_ORDER,
    CodeFenceFacts,
    CommitEvidenceKind,
    CurrentRecoveryRunFacts,
    DatabaseProvisioningProof,
    FreshRegisterOtpProof,
    ImmutableEntitlementTerms,
    ObservedRegistrationAnchors,
    ProvisionalResourceFacts,
    ProvisionalResourceKind,
    RecoveryRunStatus,
    RegistrationCodeStatus,
    RegistrationCommitEvidence,
    RegistrationEffectKind,
    RegistrationOutcome,
    RegistrationPublishPlan,
    RegistrationStatus,
    RegistrationTransitionError,
    RegistrationUserStatus,
    ReplacementPlan,
    RevisionFence,
    WorkerFence,
    WorkerLease,
    begin_final_commit,
    complete_final_commit,
    create_otp_verified_attempt,
    enter_recovery_review,
    mark_database_ready,
    record_identity_conflict,
    record_provisioning_failure,
    record_security_block,
    request_replacement,
    reserve_registration_code,
    retry_failed_registration,
    start_provisioning,
)


NOW = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)
PHONE = "+8613800138000"
OTHER_PHONE = "+8613900139000"


def _uuid(value: int) -> UUID:
    return UUID(int=value)


USER = _uuid(1)
OTHER_USER = _uuid(2)
ATTEMPT = _uuid(10)
TENANT = _uuid(11)
DATABASE = _uuid(12)
CODE = _uuid(13)
RECOVERY_RUN = _uuid(14)
NEXT_RECOVERY_RUN = _uuid(15)
OTP = _uuid(20)
RETRY_OTP = _uuid(21)
LEASE = _uuid(30)
RETRY_LEASE = _uuid(31)
WORKER = _uuid(32)
PROOF = _uuid(40)


def _terms() -> ImmutableEntitlementTerms:
    return ImmutableEntitlementTerms(
        plan_revision_uuid=_uuid(50),
        entitlements_schema_version=3,
        entitlements_digest=b"e" * 32,
        exact_duration_seconds=365 * 24 * 60 * 60,
    )


def _otp(
    *,
    challenge_uuid: UUID = OTP,
    user_uuid: UUID = USER,
    phone: str = PHONE,
    normalization_version: int = 1,
    verified_at: datetime = NOW - timedelta(seconds=5),
    expires_at: datetime = NOW + timedelta(minutes=5),
) -> FreshRegisterOtpProof:
    return FreshRegisterOtpProof(
        challenge_uuid=challenge_uuid,
        user_uuid=user_uuid,
        canonical_phone_e164=phone,
        phone_normalization_version=normalization_version,
        purpose="register",
        verified_at=verified_at,
        expires_at=expires_at,
        consumed_once=True,
    )


def _run(
    *,
    run_uuid: UUID = RECOVERY_RUN,
    status: RecoveryRunStatus = RecoveryRunStatus.COMPLETED,
    expected_revision: int = 1,
    current_revision: int = 1,
    marker_matches: bool = True,
) -> CurrentRecoveryRunFacts:
    return CurrentRecoveryRunFacts(
        run_uuid=run_uuid,
        status=status,
        revision=RevisionFence(expected_revision, current_revision),
        external_marker_matches=marker_matches,
    )


def _attempt(*, database_now: datetime = NOW):
    return create_otp_verified_attempt(
        attempt_uuid=ATTEMPT,
        tenant_uuid=TENANT,
        database_uuid=DATABASE,
        code_uuid=CODE,
        requested_name_digest=b"n" * 32,
        entitlement_terms=_terms(),
        otp_proof=_otp(),
        current_run=_run(),
        user_status=RegistrationUserStatus.ACTIVE,
        user_has_unreleased_membership=False,
        database_now=database_now,
    ).after


def _active_code(state, *, redeem_before=NOW + timedelta(days=1)):
    return CodeFenceFacts(
        code_uuid=state.code_uuid,
        status=RegistrationCodeStatus.ACTIVE,
        created_under_recovery_run_uuid=state.created_under_recovery_run_uuid,
        revision=RevisionFence(1, 1),
        entitlement_terms=state.entitlement_terms,
        redeem_before=redeem_before,
    )


def _reserved_code(
    state,
    *,
    redeem_before=NOW + timedelta(days=1),
    revision=2,
):
    return CodeFenceFacts(
        code_uuid=state.code_uuid,
        status=RegistrationCodeStatus.RESERVED,
        created_under_recovery_run_uuid=state.created_under_recovery_run_uuid,
        revision=RevisionFence(revision, revision),
        entitlement_terms=state.entitlement_terms,
        redeem_before=redeem_before,
        reserved_user_uuid=state.user_uuid,
        reserved_registration_attempt_uuid=state.attempt_uuid,
    )


def _redeemed_code(state, commit_uuid, *, revision=3):
    return CodeFenceFacts(
        code_uuid=state.code_uuid,
        status=RegistrationCodeStatus.REDEEMED,
        created_under_recovery_run_uuid=state.created_under_recovery_run_uuid,
        revision=RevisionFence(revision, revision),
        entitlement_terms=state.entitlement_terms,
        redeem_before=NOW + timedelta(days=1),
        reserved_user_uuid=state.user_uuid,
        reserved_registration_attempt_uuid=state.attempt_uuid,
        registration_commit_uuid=commit_uuid,
    )


def _reserved(*, redeem_before=NOW + timedelta(days=1)):
    initial = _attempt()
    transition = reserve_registration_code(
        initial,
        code=_active_code(initial, redeem_before=redeem_before),
        current_run=_run(),
        database_now=NOW,
    )
    return transition.after, _reserved_code(
        transition.after,
        redeem_before=redeem_before,
    )


def _lease(
    generation: int,
    *,
    lease_uuid: UUID = LEASE,
    fencing_token: int = 700,
    now: datetime = NOW,
) -> WorkerLease:
    return WorkerLease(
        lease_uuid=lease_uuid,
        owner_uuid=WORKER,
        execution_generation=generation,
        fencing_token=fencing_token,
        expires_at=now + timedelta(minutes=10),
    )


def _fence(state) -> WorkerFence:
    lease = state.active_lease
    assert lease is not None
    return WorkerFence(
        lease_uuid=lease.lease_uuid,
        execution_generation=lease.execution_generation,
        fencing_token=lease.fencing_token,
    )


def _provisioning(*, redeem_before=NOW + timedelta(days=1)):
    reserved, code = _reserved(redeem_before=redeem_before)
    transition = start_provisioning(
        reserved,
        lease=_lease(reserved.provisioning_generation),
        database_now=NOW,
    )
    return transition.after, code


def _proof(state) -> DatabaseProvisioningProof:
    fence = _fence(state)
    return DatabaseProvisioningProof(
        proof_uuid=PROOF,
        tenant_uuid=state.tenant_uuid,
        database_uuid=state.database_uuid,
        database_identity_digest=b"i" * 32,
        schema_digest=b"s" * 32,
        schema_generation=1,
        execution_generation=state.provisioning_generation,
        worker_lease_uuid=fence.lease_uuid,
        worker_fencing_token=fence.fencing_token,
        smoke_passed=True,
        backup_ddl_lease_held=True,
        database_advisory_lock_held=True,
        business_route_published=False,
        default_warehouse_created=True,
        contact_phone_prefilled_unconfirmed=True,
    )


def _ready():
    provisioning, code = _provisioning()
    proof = _proof(provisioning)
    transition = mark_database_ready(
        provisioning,
        fence=_fence(provisioning),
        proof=proof,
        database_now=NOW,
    )
    return transition.after, code


def _publish_plan(seed: int = 100) -> RegistrationPublishPlan:
    return RegistrationPublishPlan(
        registration_commit_uuid=_uuid(seed),
        admin_membership_uuid=_uuid(seed + 1),
        subscription_uuid=_uuid(seed + 2),
        subscription_event_uuid=_uuid(seed + 3),
        route_anchor_uuid=_uuid(seed + 4),
        public_name_claim_uuid=_uuid(seed + 5),
        released_hold_uuid=_uuid(seed + 6),
    )


def _absent_commit() -> RegistrationCommitEvidence:
    return RegistrationCommitEvidence(kind=CommitEvidenceKind.ABSENT)


def _begin_commit(ready, code, *, plan=None):
    plan = plan or _publish_plan()
    return begin_final_commit(
        ready,
        fence=_fence(ready),
        code=code,
        current_run=_run(),
        attempt_revision=RevisionFence(
            ready.state_revision,
            ready.state_revision,
        ),
        replacement_revision=RevisionFence(1, 1),
        current_replacement_action_uuid=None,
        commit_evidence=_absent_commit(),
        user_status=RegistrationUserStatus.ACTIVE,
        user_has_unreleased_membership=False,
        current_database_proof=ready.database_proof,
        publish_plan=plan,
        database_now=NOW,
    )


def _observed(state, **overrides) -> ObservedRegistrationAnchors:
    values = {
        "publish_plan": state.commit_plan,
        "code_uuid": state.code_uuid,
        "user_uuid": state.user_uuid,
        "attempt_uuid": state.attempt_uuid,
        "tenant_uuid": state.tenant_uuid,
        "entitlement_terms": state.entitlement_terms,
        "atomic_control_transaction": True,
        "code_redeemed_to_commit": True,
        "first_admin_created": True,
        "subscription_and_event_created": True,
        "route_and_name_published": True,
        "released_hold_created": True,
        "pending_invitations_superseded": True,
        "no_route_was_published_early": True,
    }
    values.update(overrides)
    return ObservedRegistrationAnchors(**values)


def _blocked(status=RegistrationStatus.FAILED):
    ready, code = _ready()
    if status is RegistrationStatus.FAILED:
        transition = record_provisioning_failure(
            ready,
            fence=_fence(ready),
            code=code,
            safe_reason_code="schema_smoke_failed",
            database_now=NOW,
        )
    elif status is RegistrationStatus.IDENTITY_CONFLICT:
        transition = record_identity_conflict(
            ready,
            fence=_fence(ready),
            code=code,
            database_now=NOW,
        )
    elif status is RegistrationStatus.SECURITY_BLOCKED:
        transition = record_security_block(
            ready,
            fence=_fence(ready),
            code=code,
            database_now=NOW,
        )
    else:  # pragma: no cover - helper misuse
        raise AssertionError(status)
    return transition.after, code, transition


def _replacement_plan(seed: int = 200) -> ReplacementPlan:
    return ReplacementPlan(
        replacement_action_uuid=_uuid(seed),
        successor_code_uuid=_uuid(seed + 1),
        successor_batch_uuid=_uuid(seed + 2),
        successor_crypto_context_uuid=_uuid(seed + 3),
        new_redeem_before=NOW + timedelta(days=30),
        idempotency_key=f"replace:{seed}",
    )


def _replace_attempt(
    state,
    code,
    *,
    plan=None,
    commit_evidence=None,
    resources=frozenset(),
    committed_publish_plan=None,
    current_run=None,
    attempt_revision=None,
    resource_facts=None,
):
    database_scoped = bool(
        resources
        & {
            ProvisionalResourceKind.DATABASE,
            ProvisionalResourceKind.SCHEMA,
            ProvisionalResourceKind.DATABASE_ACCOUNT,
            ProvisionalResourceKind.ROUTE,
        }
    )
    return request_replacement(
        state,
        code=code,
        current_run=current_run or _run(),
        attempt_revision=attempt_revision
        or RevisionFence(state.state_revision, state.state_revision),
        replacement_revision=RevisionFence(1, 1),
        current_replacement_action_uuid=None,
        commit_evidence=commit_evidence or _absent_commit(),
        replacement_plan=plan or _replacement_plan(),
        provisional_resources=resource_facts
        or ProvisionalResourceFacts(
            resources=resources,
            observed_generation=state.provisioning_generation,
            observed_active_lease_uuid=(
                state.active_lease.lease_uuid
                if state.active_lease is not None
                else None
            ),
            backup_ddl_lease_held=database_scoped,
            database_advisory_lock_held=database_scoped,
        ),
        database_now=NOW,
        committed_publish_plan=committed_publish_plan,
    )


def test_happy_path_is_fenced_and_publishes_every_anchor_atomically():
    initial = _attempt()
    assert initial.status is RegistrationStatus.OTP_VERIFIED

    reserved_transition = reserve_registration_code(
        initial,
        code=_active_code(initial),
        current_run=_run(),
        database_now=NOW,
    )
    assert reserved_transition.after.status is RegistrationStatus.RESERVED
    assert reserved_transition.effects == (
        RegistrationEffectKind.RESERVE_CODE_TO_ATTEMPT,
    )

    code = _reserved_code(reserved_transition.after)
    lease = _lease(reserved_transition.after.provisioning_generation)
    provisioning_transition = start_provisioning(
        reserved_transition.after,
        lease=lease,
        database_now=NOW,
    )
    assert provisioning_transition.after.status is RegistrationStatus.PROVISIONING

    proof = _proof(provisioning_transition.after)
    ready_transition = mark_database_ready(
        provisioning_transition.after,
        fence=_fence(provisioning_transition.after),
        proof=proof,
        database_now=NOW,
    )
    assert ready_transition.after.status is RegistrationStatus.READY
    assert ready_transition.effect_facts.database_proof == proof

    commit_transition = _begin_commit(ready_transition.after, code)
    committing = commit_transition.after
    assert committing.status is RegistrationStatus.COMMITTING
    assert set(commit_transition.effects) == {
        RegistrationEffectKind.CREATE_REGISTRATION_COMMIT,
        RegistrationEffectKind.CREATE_FIRST_ADMIN_MEMBERSHIP,
        RegistrationEffectKind.CREATE_SUBSCRIPTION,
        RegistrationEffectKind.APPEND_SUBSCRIPTION_EVENT,
        RegistrationEffectKind.CREATE_RELEASED_HOLD_BASELINE,
        RegistrationEffectKind.CLAIM_PUBLIC_NAME,
        RegistrationEffectKind.PUBLISH_INITIAL_ROUTE,
        RegistrationEffectKind.REDEEM_RESERVED_CODE,
        RegistrationEffectKind.SUPERSEDE_PHONE_INVITATIONS,
    }
    assert commit_transition.completion.required_lock_order == REGISTRATION_LOCK_ORDER
    assert commit_transition.completion.require_atomic_control_transaction
    assert commit_transition.completion.no_publish_before_all_fences

    committed_code = _redeemed_code(
        committing,
        committing.commit_plan.registration_commit_uuid,
    )
    active_transition = complete_final_commit(
        committing,
        fence=_fence(committing),
        code=committed_code,
        current_run=_run(),
        attempt_revision=RevisionFence(
            committing.state_revision,
            committing.state_revision,
        ),
        replacement_revision=RevisionFence(1, 1),
        observed_anchors=_observed(committing),
        database_now=NOW,
    )
    assert active_transition.after.status is RegistrationStatus.ACTIVE
    assert active_transition.outcome is RegistrationOutcome.ACTIVATED
    assert active_transition.after.active_lease is None
    assert (
        active_transition.after.registration_commit_uuid
        == committing.commit_plan.registration_commit_uuid
    )
    assert active_transition.after.entitlement_terms == initial.entitlement_terms
    assert active_transition.after.code_uuid == initial.code_uuid
    assert active_transition.after.user_uuid == initial.user_uuid
    assert active_transition.effect_facts.preserve_code_binding


def test_attempt_creation_requires_fresh_canonical_register_otp_and_active_user():
    with pytest.raises(ValueError, match="canonical_phone_e164"):
        _otp(phone="13800138000")
    with pytest.raises(ValueError, match="purpose"):
        replace(_otp(), purpose="login")

    for user_status, membership, error_code in (
        (RegistrationUserStatus.UNVERIFIED, False, "REGISTRATION_USER_NOT_ACTIVE"),
        (RegistrationUserStatus.DISABLED, False, "REGISTRATION_SECURITY_BLOCKED"),
        (RegistrationUserStatus.ACTIVE, True, "REGISTRATION_IDENTITY_CONFLICT"),
    ):
        with pytest.raises(RegistrationTransitionError) as caught:
            create_otp_verified_attempt(
                attempt_uuid=ATTEMPT,
                tenant_uuid=TENANT,
                database_uuid=DATABASE,
                code_uuid=CODE,
                requested_name_digest=b"n" * 32,
                entitlement_terms=_terms(),
                otp_proof=_otp(),
                current_run=_run(),
                user_status=user_status,
                user_has_unreleased_membership=membership,
                database_now=NOW,
            )
        assert caught.value.code == error_code

    with pytest.raises(RegistrationTransitionError) as caught:
        create_otp_verified_attempt(
            attempt_uuid=ATTEMPT,
            tenant_uuid=TENANT,
            database_uuid=DATABASE,
            code_uuid=CODE,
            requested_name_digest=b"n" * 32,
            entitlement_terms=_terms(),
            otp_proof=_otp(
                verified_at=NOW - timedelta(minutes=10),
                expires_at=NOW - timedelta(minutes=5),
            ),
            current_run=_run(),
            user_status=RegistrationUserStatus.ACTIVE,
            user_has_unreleased_membership=False,
            database_now=NOW,
        )
    assert caught.value.code == "REGISTRATION_OTP_STALE"


def test_reservation_rejects_expired_or_noncurrent_code_and_never_rebinds():
    state = _attempt()
    with pytest.raises(RegistrationTransitionError):
        reserve_registration_code(
            state,
            code=_active_code(state, redeem_before=NOW),
            current_run=_run(),
            database_now=NOW,
        )

    wrong_terms = replace(_terms(), exact_duration_seconds=60)
    with pytest.raises(RegistrationTransitionError) as caught:
        reserve_registration_code(
            state,
            code=replace(_active_code(state), entitlement_terms=wrong_terms),
            current_run=_run(),
            database_now=NOW,
        )
    assert caught.value.code == "REGISTRATION_CODE_FENCE_LOST"


def test_failure_preserves_original_code_attempt_user_and_entitlements():
    ready, code = _ready()
    failed, _, transition = _blocked()

    assert failed.status is RegistrationStatus.FAILED
    assert transition.effects == (
        RegistrationEffectKind.INVALIDATE_WORKER_LEASE,
        RegistrationEffectKind.PRESERVE_CODE_RESERVATION,
    )
    assert transition.effect_facts.preserve_code_binding
    for field in (
        "attempt_uuid",
        "user_uuid",
        "canonical_phone_e164",
        "tenant_uuid",
        "database_uuid",
        "code_uuid",
        "requested_name_digest",
        "entitlement_terms",
        "created_under_recovery_run_uuid",
    ):
        assert getattr(failed, field) == getattr(ready, field)
    assert code.reserved_user_uuid == failed.user_uuid
    assert code.reserved_registration_attempt_uuid == failed.attempt_uuid


def test_original_user_can_retry_after_code_deadline_with_fresh_same_phone_otp():
    redeem_before = NOW + timedelta(seconds=30)
    provisioning, code = _provisioning(redeem_before=redeem_before)
    failed = record_provisioning_failure(
        provisioning,
        fence=_fence(provisioning),
        code=code,
        safe_reason_code="provider_timeout",
        database_now=NOW,
    ).after
    retry_now = NOW + timedelta(minutes=1)
    new_lease = _lease(
        failed.provisioning_generation + 1,
        lease_uuid=RETRY_LEASE,
        fencing_token=701,
        now=retry_now,
    )
    fresh_proof = _otp(
        challenge_uuid=RETRY_OTP,
        verified_at=retry_now - timedelta(seconds=1),
        expires_at=retry_now + timedelta(minutes=5),
    )

    transition = retry_failed_registration(
        failed,
        otp_proof=fresh_proof,
        code=code,
        current_run=_run(),
        attempt_revision=RevisionFence(failed.state_revision, failed.state_revision),
        replacement_revision=RevisionFence(1, 1),
        new_lease=new_lease,
        user_status=RegistrationUserStatus.ACTIVE,
        user_has_unreleased_membership=False,
        database_now=retry_now,
    )

    retried = transition.after
    assert retried.status is RegistrationStatus.PROVISIONING
    assert retried.provisioning_generation == failed.provisioning_generation + 1
    assert retried.active_lease == new_lease
    assert retried.last_register_otp_challenge_uuid == RETRY_OTP
    assert transition.effect_facts.preserve_code_binding
    assert transition.completion.required_lock_order == REGISTRATION_LOCK_ORDER
    for field in (
        "attempt_uuid",
        "user_uuid",
        "canonical_phone_e164",
        "tenant_uuid",
        "database_uuid",
        "code_uuid",
        "requested_name_digest",
        "entitlement_terms",
    ):
        assert getattr(retried, field) == getattr(failed, field)


@pytest.mark.parametrize(
    "proof",
    [
        _otp(challenge_uuid=RETRY_OTP, user_uuid=OTHER_USER),
        _otp(challenge_uuid=RETRY_OTP, phone=OTHER_PHONE),
        _otp(challenge_uuid=RETRY_OTP, normalization_version=2),
        _otp(challenge_uuid=OTP),
        _otp(
            challenge_uuid=RETRY_OTP,
            verified_at=NOW - timedelta(minutes=10),
            expires_at=NOW - timedelta(minutes=5),
        ),
    ],
)
def test_retry_rejects_wrong_user_phone_normalizer_old_or_stale_otp(proof):
    failed, code, _ = _blocked()
    with pytest.raises(RegistrationTransitionError) as caught:
        retry_failed_registration(
            failed,
            otp_proof=proof,
            code=code,
            current_run=_run(),
            attempt_revision=RevisionFence(
                failed.state_revision,
                failed.state_revision,
            ),
            replacement_revision=RevisionFence(1, 1),
            new_lease=_lease(
                failed.provisioning_generation + 1,
                lease_uuid=RETRY_LEASE,
            ),
            user_status=RegistrationUserStatus.ACTIVE,
            user_has_unreleased_membership=False,
            database_now=NOW,
        )
    assert caught.value.code == "REGISTRATION_RETRY_OTP_MISMATCH"


def test_retry_rejects_stale_attempt_code_replacement_and_recovery_fences():
    failed, code, _ = _blocked()
    common = {
        "otp_proof": _otp(challenge_uuid=RETRY_OTP),
        "code": code,
        "current_run": _run(),
        "attempt_revision": RevisionFence(
            failed.state_revision,
            failed.state_revision,
        ),
        "replacement_revision": RevisionFence(1, 1),
        "new_lease": _lease(
            failed.provisioning_generation + 1,
            lease_uuid=RETRY_LEASE,
        ),
        "user_status": RegistrationUserStatus.ACTIVE,
        "user_has_unreleased_membership": False,
        "database_now": NOW,
    }

    for changes, expected in (
        (
            {"attempt_revision": RevisionFence(failed.state_revision, 999)},
            "REGISTRATION_ATTEMPT_FENCE_LOST",
        ),
        (
            {"replacement_revision": RevisionFence(1, 2)},
            "REGISTRATION_REPLACEMENT_FENCE_LOST",
        ),
        (
            {"code": replace(code, revision=RevisionFence(2, 3))},
            "REGISTRATION_CODE_FENCE_LOST",
        ),
        (
            {"current_run": _run(run_uuid=NEXT_RECOVERY_RUN)},
            "REGISTRATION_RECOVERY_FENCE_LOST",
        ),
    ):
        with pytest.raises(RegistrationTransitionError) as caught:
            retry_failed_registration(failed, **(common | changes))
        assert caught.value.code == expected


def test_old_worker_is_rejected_after_retry_advances_generation():
    provisioning, code = _provisioning()
    old_fence = _fence(provisioning)
    failed = record_provisioning_failure(
        provisioning,
        fence=old_fence,
        code=code,
        safe_reason_code="provider_timeout",
        database_now=NOW,
    ).after
    retried = retry_failed_registration(
        failed,
        otp_proof=_otp(challenge_uuid=RETRY_OTP),
        code=code,
        current_run=_run(),
        attempt_revision=RevisionFence(failed.state_revision, failed.state_revision),
        replacement_revision=RevisionFence(1, 1),
        new_lease=_lease(
            failed.provisioning_generation + 1,
            lease_uuid=RETRY_LEASE,
            fencing_token=701,
        ),
        user_status=RegistrationUserStatus.ACTIVE,
        user_has_unreleased_membership=False,
        database_now=NOW,
    ).after

    with pytest.raises(RegistrationTransitionError) as caught:
        mark_database_ready(
            retried,
            fence=old_fence,
            proof=_proof(retried),
            database_now=NOW,
        )
    assert caught.value.code == "REGISTRATION_WORKER_FENCE_STALE"


@pytest.mark.parametrize("status", sorted(ORDINARY_REPLACEMENT_ELIGIBLE_STATES))
def test_replacement_is_limited_to_explicit_blocked_states_and_copies_terms(status):
    blocked, code, _ = _blocked(status)
    resources = frozenset(
        {
            ProvisionalResourceKind.DATABASE,
            ProvisionalResourceKind.DATABASE_ACCOUNT,
        }
    )
    transition = _replace_attempt(blocked, code, resources=resources)
    replaced = transition.after

    assert replaced.status is RegistrationStatus.SUPERSEDED_BY_REPLACEMENT
    assert replaced.provisioning_generation == blocked.provisioning_generation + 1
    assert replaced.replacement_lineage.source_code_uuid == blocked.code_uuid
    assert replaced.replacement_lineage.source_attempt_uuid == blocked.attempt_uuid
    assert (
        replaced.replacement_lineage.copied_entitlement_terms
        == blocked.entitlement_terms
    )
    assert not hasattr(replaced.replacement_lineage, "user_uuid")
    assert not hasattr(replaced.replacement_lineage, "canonical_phone_e164")
    assert transition.effect_facts.cleanup_outbox_required
    assert RegistrationEffectKind.REVOKE_SOURCE_CODE_AS_REPLACED in transition.effects
    assert RegistrationEffectKind.CREATE_SUCCESSOR_CODE in transition.effects
    assert RegistrationEffectKind.CREATE_SYSTEM_CLEANUP_OUTBOX in transition.effects
    assert transition.effect_facts.preserve_code_binding
    assert transition.completion.required_lock_order == REGISTRATION_LOCK_ORDER
    assert transition.completion.require_atomic_control_transaction


def test_replacement_without_real_resources_does_not_request_cleanup():
    failed, code, _ = _blocked()
    transition = _replace_attempt(failed, code)
    assert not transition.effect_facts.cleanup_outbox_required
    assert (
        RegistrationEffectKind.CREATE_SYSTEM_CLEANUP_OUTBOX
        not in transition.effects
    )


def test_replacement_requires_current_generation_and_database_resource_locks():
    failed, code, _ = _blocked()
    with pytest.raises(ValueError, match="backup/DDL"):
        ProvisionalResourceFacts(
            resources=frozenset({ProvisionalResourceKind.DATABASE}),
            observed_generation=failed.provisioning_generation,
            observed_active_lease_uuid=None,
            backup_ddl_lease_held=False,
            database_advisory_lock_held=False,
        )

    stale_facts = ProvisionalResourceFacts(
        resources=frozenset(),
        observed_generation=failed.provisioning_generation + 1,
        observed_active_lease_uuid=None,
        backup_ddl_lease_held=False,
        database_advisory_lock_held=False,
    )
    with pytest.raises(RegistrationTransitionError) as caught:
        _replace_attempt(failed, code, resource_facts=stale_facts)
    assert caught.value.code == "REGISTRATION_WORKER_FENCE_STALE"


def test_ready_proof_requires_default_warehouse_and_unconfirmed_phone_prefill():
    provisioning, _ = _provisioning()
    for changes in (
        {"default_warehouse_created": False},
        {"contact_phone_prefilled_unconfirmed": False},
    ):
        with pytest.raises(RegistrationTransitionError) as caught:
            mark_database_ready(
                provisioning,
                fence=_fence(provisioning),
                proof=replace(_proof(provisioning), **changes),
                database_now=NOW,
            )
        assert caught.value.code == "REGISTRATION_DATABASE_PROOF_INVALID"


def test_provisioning_ready_and_committing_cannot_be_replaced():
    provisioning, code = _provisioning()
    ready = mark_database_ready(
        provisioning,
        fence=_fence(provisioning),
        proof=_proof(provisioning),
        database_now=NOW,
    ).after
    committing = _begin_commit(ready, code).after

    for state in (provisioning, ready, committing):
        with pytest.raises(RegistrationTransitionError) as caught:
            _replace_attempt(state, code)
        assert caught.value.code == "REGISTRATION_REPLACEMENT_NOT_ALLOWED"


def test_replacement_replay_returns_same_successor_and_conflict_is_rejected():
    failed, code, _ = _blocked()
    plan = _replacement_plan()
    first = _replace_attempt(failed, code, plan=plan)

    replay = _replace_attempt(first.after, code, plan=plan)
    assert replay.outcome is RegistrationOutcome.REPLACEMENT_REPLAY
    assert replay.after is first.after
    assert replay.effects == ()

    with pytest.raises(RegistrationTransitionError) as caught:
        _replace_attempt(first.after, code, plan=_replacement_plan(300))
    assert caught.value.code == "REGISTRATION_REPLACEMENT_ALREADY_EXISTS"


@pytest.mark.parametrize(
    "kind",
    [CommitEvidenceKind.PARTIAL, CommitEvidenceKind.INCONSISTENT],
)
def test_partial_or_inconsistent_commit_evidence_creates_integrity_block(kind):
    failed, code, _ = _blocked()
    evidence = RegistrationCommitEvidence(
        kind=kind,
        safe_incident_reason="partial_registration_commit",
    )

    transition = _replace_attempt(failed, code, commit_evidence=evidence)
    assert transition.after.status is RegistrationStatus.INTEGRITY_BLOCKED
    assert transition.after.integrity_reason_code == "partial_registration_commit"
    assert transition.effects == (
        RegistrationEffectKind.CREATE_INTEGRITY_INCIDENT,
    )
    assert transition.effect_facts.preserve_code_binding
    assert RegistrationEffectKind.CREATE_SUCCESSOR_CODE not in transition.effects
    assert (
        RegistrationEffectKind.CREATE_SYSTEM_CLEANUP_OUTBOX
        not in transition.effects
    )

    for operation in (
        lambda: _replace_attempt(transition.after, code),
        lambda: retry_failed_registration(
            transition.after,
            otp_proof=_otp(challenge_uuid=RETRY_OTP),
            code=code,
            current_run=_run(),
            attempt_revision=RevisionFence(
                transition.after.state_revision,
                transition.after.state_revision,
            ),
            replacement_revision=RevisionFence(1, 1),
            new_lease=_lease(
                transition.after.provisioning_generation + 1,
                lease_uuid=RETRY_LEASE,
            ),
            user_status=RegistrationUserStatus.ACTIVE,
            user_has_unreleased_membership=False,
            database_now=NOW,
        ),
    ):
        with pytest.raises(RegistrationTransitionError):
            operation()


def test_incomplete_observed_publish_anchors_enter_integrity_block():
    ready, code = _ready()
    committing = _begin_commit(ready, code).after
    redeemed = _redeemed_code(
        committing,
        committing.commit_plan.registration_commit_uuid,
    )
    transition = complete_final_commit(
        committing,
        fence=_fence(committing),
        code=redeemed,
        current_run=_run(),
        attempt_revision=RevisionFence(
            committing.state_revision,
            committing.state_revision,
        ),
        replacement_revision=RevisionFence(1, 1),
        observed_anchors=_observed(
            committing,
            pending_invitations_superseded=False,
        ),
        database_now=NOW,
    )
    assert transition.after.status is RegistrationStatus.INTEGRITY_BLOCKED
    assert transition.effect_facts.integrity_incident_reason == (
        "registration_anchor_mismatch"
    )
    assert RegistrationEffectKind.CREATE_INTEGRITY_INCIDENT in transition.effects


def test_complete_commit_history_wins_over_replacement_without_duplicate_effects():
    failed, _, _ = _blocked()
    plan = _publish_plan(400)
    evidence = RegistrationCommitEvidence(
        kind=CommitEvidenceKind.COMPLETE,
        registration_commit_uuid=plan.registration_commit_uuid,
        anchors_match_immutable_source=True,
    )
    redeemed = _redeemed_code(failed, plan.registration_commit_uuid)

    transition = _replace_attempt(
        failed,
        redeemed,
        commit_evidence=evidence,
        committed_publish_plan=plan,
    )
    assert transition.after.status is RegistrationStatus.ACTIVE
    assert transition.outcome is RegistrationOutcome.COMMITTED_HISTORY_RECONCILED
    assert transition.effects == (
        RegistrationEffectKind.RECONCILE_COMPLETE_COMMIT,
    )
    assert transition.after.registration_commit_uuid == plan.registration_commit_uuid
    assert transition.after.replacement_lineage is None


def test_redeemed_code_anchor_mismatch_is_integrity_blocked_not_repaired():
    failed, _, _ = _blocked()
    plan = _publish_plan(500)
    evidence = RegistrationCommitEvidence(
        kind=CommitEvidenceKind.COMPLETE,
        registration_commit_uuid=plan.registration_commit_uuid,
        anchors_match_immutable_source=True,
    )
    wrong_code = replace(
        _redeemed_code(failed, plan.registration_commit_uuid),
        entitlement_terms=replace(
            failed.entitlement_terms,
            exact_duration_seconds=1,
        ),
    )
    transition = _replace_attempt(
        failed,
        wrong_code,
        commit_evidence=evidence,
        committed_publish_plan=plan,
    )
    assert transition.after.status is RegistrationStatus.INTEGRITY_BLOCKED
    assert RegistrationEffectKind.CREATE_SUCCESSOR_CODE not in transition.effects


def test_retry_replacement_and_final_commit_share_one_canonical_lock_order():
    failed, code, _ = _blocked()
    retried = retry_failed_registration(
        failed,
        otp_proof=_otp(challenge_uuid=RETRY_OTP),
        code=code,
        current_run=_run(),
        attempt_revision=RevisionFence(failed.state_revision, failed.state_revision),
        replacement_revision=RevisionFence(1, 1),
        new_lease=_lease(
            failed.provisioning_generation + 1,
            lease_uuid=RETRY_LEASE,
        ),
        user_status=RegistrationUserStatus.ACTIVE,
        user_has_unreleased_membership=False,
        database_now=NOW,
    )
    replacement = _replace_attempt(failed, code)
    ready, ready_code = _ready()
    commit = _begin_commit(ready, ready_code)

    assert retried.completion.required_lock_order == REGISTRATION_LOCK_ORDER
    assert replacement.completion.required_lock_order == REGISTRATION_LOCK_ORDER
    assert commit.completion.required_lock_order == REGISTRATION_LOCK_ORDER


def test_replacement_and_retry_fences_allow_only_one_competing_winner():
    failed, code, _ = _blocked()
    replacement = _replace_attempt(failed, code)

    with pytest.raises(RegistrationTransitionError):
        retry_failed_registration(
            replacement.after,
            otp_proof=_otp(challenge_uuid=RETRY_OTP),
            code=code,
            current_run=_run(),
            attempt_revision=RevisionFence(
                failed.state_revision,
                replacement.after.state_revision,
            ),
            replacement_revision=RevisionFence(1, 2),
            new_lease=_lease(
                replacement.after.provisioning_generation + 1,
                lease_uuid=RETRY_LEASE,
            ),
            user_status=RegistrationUserStatus.ACTIVE,
            user_has_unreleased_membership=False,
            database_now=NOW,
        )

    ready, ready_code = _ready()
    stale_revision = RevisionFence(ready.state_revision, ready.state_revision + 1)
    with pytest.raises(RegistrationTransitionError) as caught:
        begin_final_commit(
            ready,
            fence=_fence(ready),
            code=ready_code,
            current_run=_run(),
            attempt_revision=stale_revision,
            replacement_revision=RevisionFence(1, 2),
            current_replacement_action_uuid=(
                replacement.after.replacement_lineage.replacement_action_uuid
            ),
            commit_evidence=_absent_commit(),
            user_status=RegistrationUserStatus.ACTIVE,
            user_has_unreleased_membership=False,
            current_database_proof=ready.database_proof,
            publish_plan=_publish_plan(600),
            database_now=NOW,
        )
    assert caught.value.code == "REGISTRATION_ATTEMPT_FENCE_LOST"


def test_recovery_normalizes_every_live_state_and_irrevocably_fences_workers():
    initial = _attempt()
    reserved, code = _reserved()
    provisioning, _ = _provisioning()
    ready, _ = _ready()
    committing = _begin_commit(ready, code).after
    failed, _, _ = _blocked(RegistrationStatus.FAILED)
    identity, _, _ = _blocked(RegistrationStatus.IDENTITY_CONFLICT)
    security, _, _ = _blocked(RegistrationStatus.SECURITY_BLOCKED)
    recovery = _run(
        run_uuid=NEXT_RECOVERY_RUN,
        status=RecoveryRunStatus.REVIEWING,
    )

    for state in (
        initial,
        reserved,
        provisioning,
        ready,
        committing,
        failed,
        identity,
        security,
    ):
        transition = enter_recovery_review(state, current_run=recovery)
        reviewed = transition.after
        assert reviewed.status is RegistrationStatus.RECOVERY_REVIEW
        assert reviewed.status_before_recovery_review is state.status
        assert reviewed.provisioning_generation == state.provisioning_generation + 1
        assert reviewed.active_lease is None
        assert reviewed.database_proof is None
        assert reviewed.commit_plan is None
        assert RegistrationEffectKind.MARK_CODE_RECOVERY_REVOKED in transition.effects
        assert transition.effect_facts.preserve_code_binding
        assert transition.completion.require_atomic_control_transaction

        replay = enter_recovery_review(reviewed, current_run=recovery)
        assert replay.outcome is RegistrationOutcome.IDEMPOTENT_REPLAY
        assert replay.after is reviewed


def test_nonpermitting_run_forces_recovery_review_from_retry_commit_and_replacement():
    recovery = _run(
        run_uuid=NEXT_RECOVERY_RUN,
        status=RecoveryRunStatus.INSTALLING,
    )
    failed, code, _ = _blocked()
    retry_transition = retry_failed_registration(
        failed,
        otp_proof=_otp(challenge_uuid=RETRY_OTP),
        code=code,
        current_run=recovery,
        attempt_revision=RevisionFence(failed.state_revision, failed.state_revision),
        replacement_revision=RevisionFence(1, 1),
        new_lease=_lease(
            failed.provisioning_generation + 1,
            lease_uuid=RETRY_LEASE,
        ),
        user_status=RegistrationUserStatus.ACTIVE,
        user_has_unreleased_membership=False,
        database_now=NOW,
    )
    assert retry_transition.after.status is RegistrationStatus.RECOVERY_REVIEW

    replacement_transition = _replace_attempt(
        failed,
        code,
        current_run=recovery,
    )
    assert replacement_transition.after.status is RegistrationStatus.RECOVERY_REVIEW

    ready, ready_code = _ready()
    commit_transition = begin_final_commit(
        ready,
        fence=_fence(ready),
        code=ready_code,
        current_run=recovery,
        attempt_revision=RevisionFence(ready.state_revision, ready.state_revision),
        replacement_revision=RevisionFence(1, 1),
        current_replacement_action_uuid=None,
        commit_evidence=_absent_commit(),
        user_status=RegistrationUserStatus.ACTIVE,
        user_has_unreleased_membership=False,
        current_database_proof=ready.database_proof,
        publish_plan=_publish_plan(700),
        database_now=NOW,
    )
    assert commit_transition.after.status is RegistrationStatus.RECOVERY_REVIEW


def test_recovery_review_cannot_resume_or_be_replaced_and_terminals_stay_terminal():
    failed, code, _ = _blocked()
    recovery = _run(
        run_uuid=NEXT_RECOVERY_RUN,
        status=RecoveryRunStatus.REVIEWING,
    )
    reviewed = enter_recovery_review(failed, current_run=recovery).after

    with pytest.raises(RegistrationTransitionError):
        _replace_attempt(reviewed, code)
    with pytest.raises(RegistrationTransitionError):
        retry_failed_registration(
            reviewed,
            otp_proof=_otp(challenge_uuid=RETRY_OTP),
            code=code,
            current_run=_run(),
            attempt_revision=RevisionFence(
                reviewed.state_revision,
                reviewed.state_revision,
            ),
            replacement_revision=RevisionFence(1, 1),
            new_lease=_lease(
                reviewed.provisioning_generation + 1,
                lease_uuid=RETRY_LEASE,
            ),
            user_status=RegistrationUserStatus.ACTIVE,
            user_has_unreleased_membership=False,
            database_now=NOW,
        )

    ready, ready_code = _ready()
    committing = _begin_commit(ready, ready_code).after
    active = complete_final_commit(
        committing,
        fence=_fence(committing),
        code=_redeemed_code(
            committing,
            committing.commit_plan.registration_commit_uuid,
        ),
        current_run=_run(),
        attempt_revision=RevisionFence(
            committing.state_revision,
            committing.state_revision,
        ),
        replacement_revision=RevisionFence(1, 1),
        observed_anchors=_observed(committing),
        database_now=NOW,
    ).after
    replaced = _replace_attempt(failed, code).after
    for terminal in (active, replaced):
        with pytest.raises(RegistrationTransitionError) as caught:
            enter_recovery_review(terminal, current_run=recovery)
        assert caught.value.code == "REGISTRATION_TERMINAL"


def test_current_run_marker_or_revision_mismatch_also_forces_recovery_review():
    failed, code, _ = _blocked()
    for recovery in (
        _run(marker_matches=False),
        _run(expected_revision=1, current_revision=2),
    ):
        transition = _replace_attempt(
            failed,
            code,
            current_run=recovery,
        )
        assert transition.after.status is RegistrationStatus.RECOVERY_REVIEW


def test_platform_surface_has_replacement_only_and_no_cleanup_or_retry_commands():
    import inventory_control.registration as registration

    assert PLATFORM_REGISTRATION_ACTIONS == frozenset({"issue_replacement_code"})
    for forbidden in (
        "platform_retry_registration",
        "platform_abandon_registration",
        "platform_cleanup_registration",
        "abandon_registration",
        "cleanup_registration",
    ):
        assert not hasattr(registration, forbidden)


def test_state_effects_and_completion_facts_are_immutable():
    transition = create_otp_verified_attempt(
        attempt_uuid=ATTEMPT,
        tenant_uuid=TENANT,
        database_uuid=DATABASE,
        code_uuid=CODE,
        requested_name_digest=b"n" * 32,
        entitlement_terms=_terms(),
        otp_proof=_otp(),
        current_run=_run(),
        user_status=RegistrationUserStatus.ACTIVE,
        user_has_unreleased_membership=False,
        database_now=NOW,
    )

    with pytest.raises(FrozenInstanceError):
        transition.after.status = RegistrationStatus.ACTIVE
    with pytest.raises(FrozenInstanceError):
        transition.effect_facts.current_generation = 99
    with pytest.raises(FrozenInstanceError):
        transition.completion.required_lock_order = ()
    assert isinstance(transition.effects, tuple)
    assert isinstance(transition.completion.completion_predicates, tuple)


def test_state_constructor_rejects_impossible_lease_proof_and_commit_combinations():
    reserved, _ = _reserved()
    with pytest.raises(ValueError, match="worker lease"):
        replace(reserved, status=RegistrationStatus.READY)

    provisioning, _ = _provisioning()
    with pytest.raises(ValueError, match="generation"):
        replace(
            provisioning,
            provisioning_generation=provisioning.provisioning_generation + 1,
        )

    ready, code = _ready()
    committing = _begin_commit(ready, code).after
    with pytest.raises(TypeError, match="registration_commit_uuid"):
        replace(
            committing,
            status=RegistrationStatus.ACTIVE,
            active_lease=None,
        )
