from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from inventory_control.domain import TenantStatus
from inventory_control.lifecycle import (
    DmlLoginState,
    FreezeBarrierEvidence,
    ResumeCandidateEvidence,
    SuspensionActionOutcome,
    SuspensionEffectKind,
    SuspensionPhase,
    SuspensionState,
    SuspensionTransitionError,
    complete_resume,
    complete_suspend,
    fail_current_barrier,
    request_resume,
    request_suspend,
)


FREEZE_ACTION_ID = UUID("10000000-0000-4000-8000-000000000001")
RESUME_ACTION_ID = UUID("10000000-0000-4000-8000-000000000002")
OTHER_ACTION_ID = UUID("10000000-0000-4000-8000-000000000003")
FREEZE_DIGEST = b"f" * 32
RESUME_DIGEST = b"r" * 32
DATABASE_NOW = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)


def _eligible(status=TenantStatus.ACTIVE):
    return SuspensionState.eligible(
        tenant_status=status,
        tenant_access_version=7,
        published_dml_generation=3,
    )


def _request_freeze(state=None):
    state = state or _eligible()
    return request_suspend(
        state,
        action_id=FREEZE_ACTION_ID,
        idempotency_key="freeze:tenant-1:v1",
        request_digest=FREEZE_DIGEST,
        expected_access_version=state.tenant_access_version,
        expected_barrier_generation=state.barrier_generation,
    )


def _freeze_evidence(state, **overrides):
    values = {
        "action_id": state.current_action.action_id,
        "barrier_generation": state.barrier_generation,
        "tenant_access_version": state.tenant_access_version,
        "sessions_revoked": True,
        "engines_disposed": True,
        "job_leases_blocked": True,
        "provider_submissions_blocked": True,
        "desired_dml_locked": True,
        "all_dml_identities_locked": True,
    }
    values.update(overrides)
    return FreezeBarrierEvidence(**values)


def _fully_suspended(status=TenantStatus.ACTIVE):
    freezing = _request_freeze(_eligible(status)).state
    return complete_suspend(
        freezing,
        evidence=_freeze_evidence(freezing),
    ).state


def _request_resolution(state=None):
    state = state or _fully_suspended()
    return request_resume(
        state,
        action_id=RESUME_ACTION_ID,
        idempotency_key="resume:tenant-1:v1",
        request_digest=RESUME_DIGEST,
        expected_access_version=state.tenant_access_version,
        expected_barrier_generation=state.barrier_generation,
    )


def _resume_evidence(state, **overrides):
    values = {
        "action_id": state.current_action.action_id,
        "barrier_generation": state.barrier_generation,
        "tenant_access_version": state.tenant_access_version,
        "candidate_dml_generation": state.candidate_dml_generation,
        "candidate_started_locked": True,
        "candidate_unpublished": True,
        "database_identity_verified": True,
        "required_permissions_verified": True,
        "cross_schema_access_denied": True,
        "old_dml_generations_locked": True,
    }
    values.update(overrides)
    return ResumeCandidateEvidence(**values)


@pytest.mark.parametrize("starting_status", [TenantStatus.ACTIVE, TenantStatus.EXPIRED])
def test_freeze_first_transaction_immediately_denies_and_increments_version(
    starting_status,
):
    initial = _eligible(starting_status)

    transition = _request_freeze(initial)

    assert transition.state.tenant_status is TenantStatus.SUSPENDING
    assert transition.state.phase is SuspensionPhase.FREEZING
    assert transition.state.tenant_access_version == 8
    assert transition.state.barrier_generation == 1
    assert transition.state.desired_dml_login_state is DmlLoginState.LOCKED
    assert transition.state.published_dml_generation == 3
    assert transition.state.candidate_dml_generation is None
    assert {effect.kind for effect in transition.effects} == {
        SuspensionEffectKind.REVOKE_ALL_SESSIONS,
        SuspensionEffectKind.DISPOSE_TENANT_ENGINES,
        SuspensionEffectKind.BLOCK_JOB_LEASES,
        SuspensionEffectKind.BLOCK_PROVIDER_SUBMISSIONS,
        SuspensionEffectKind.SET_DESIRED_DML_LOCKED,
        SuspensionEffectKind.LOCK_ALL_DML_IDENTITIES,
    }
    assert all(
        effect.action_id == FREEZE_ACTION_ID
        and effect.barrier_generation == 1
        and effect.tenant_access_version == 8
        for effect in transition.effects
    )
    assert transition.subscription_expiry_changed is False
    assert transition.service_time_compensated is False
    assert transition.redemption_code_consumed is False
    assert all("unbind" not in effect.kind.value for effect in transition.effects)


def test_tenant_is_not_suspended_until_every_barrier_is_confirmed():
    freezing = _request_freeze().state
    incomplete = _freeze_evidence(freezing, engines_disposed=False)

    with pytest.raises(SuspensionTransitionError) as error:
        complete_suspend(freezing, evidence=incomplete)

    assert error.value.code == "SUSPENSION_BARRIER_INCOMPLETE"
    assert freezing.tenant_status is TenantStatus.SUSPENDING
    assert freezing.phase is SuspensionPhase.FREEZING

    completed = complete_suspend(
        freezing,
        evidence=_freeze_evidence(freezing),
    )
    assert completed.state.tenant_status is TenantStatus.SUSPENDED
    assert completed.state.phase is SuspensionPhase.ACTIVE
    assert (
        completed.state.current_action.outcome
        is SuspensionActionOutcome.SUCCEEDED
    )


def test_freeze_failure_remains_deny_and_can_retry_same_barrier():
    freezing = _request_freeze().state

    failed = fail_current_barrier(
        freezing,
        action_id=FREEZE_ACTION_ID,
        barrier_generation=freezing.barrier_generation,
        tenant_access_version=freezing.tenant_access_version,
        failure_code="ENGINE_DRAIN_TIMEOUT",
    )

    assert failed.state.tenant_status is TenantStatus.SUSPENDING
    assert failed.state.phase is SuspensionPhase.FAILED
    assert failed.state.desired_dml_login_state is DmlLoginState.LOCKED
    assert (
        failed.state.current_action.outcome is SuspensionActionOutcome.FAILED
    )
    assert SuspensionEffectKind.BLOCK_PROVIDER_SUBMISSIONS in {
        effect.kind for effect in failed.effects
    }

    retry = fail_current_barrier(
        failed.state,
        action_id=FREEZE_ACTION_ID,
        barrier_generation=freezing.barrier_generation,
        tenant_access_version=freezing.tenant_access_version,
        failure_code="ENGINE_DRAIN_TIMEOUT",
    )
    assert retry.idempotent
    assert retry.state == failed.state

    completed = complete_suspend(
        failed.state,
        evidence=_freeze_evidence(failed.state),
    )
    assert completed.state.tenant_status is TenantStatus.SUSPENDED


def test_same_action_is_idempotent_but_payload_change_and_competitor_conflict():
    first = _request_freeze()

    retry = request_suspend(
        first.state,
        action_id=FREEZE_ACTION_ID,
        idempotency_key="freeze:tenant-1:v1",
        request_digest=FREEZE_DIGEST,
        expected_access_version=7,
        expected_barrier_generation=0,
    )
    assert retry.idempotent
    assert retry.state == first.state

    with pytest.raises(SuspensionTransitionError) as replay_error:
        request_suspend(
            first.state,
            action_id=FREEZE_ACTION_ID,
            idempotency_key="freeze:tenant-1:v1",
            request_digest=b"x" * 32,
            expected_access_version=8,
            expected_barrier_generation=1,
        )
    assert replay_error.value.code == "SUSPENSION_ACTION_REPLAY_MISMATCH"

    with pytest.raises(SuspensionTransitionError) as conflict_error:
        request_suspend(
            first.state,
            action_id=OTHER_ACTION_ID,
            idempotency_key="freeze:tenant-1:v2",
            request_digest=b"o" * 32,
            expected_access_version=8,
            expected_barrier_generation=1,
        )
    assert conflict_error.value.code == "SUSPENSION_ACTION_CONFLICT"


@pytest.mark.parametrize(
    ("expected_access_version", "expected_barrier_generation", "code"),
    [
        (6, 0, "STALE_TENANT_ACCESS_VERSION"),
        (7, 1, "STALE_SUSPENSION_GENERATION"),
    ],
)
def test_request_rejects_stale_access_or_barrier_version(
    expected_access_version,
    expected_barrier_generation,
    code,
):
    state = _eligible()

    with pytest.raises(SuspensionTransitionError) as error:
        request_suspend(
            state,
            action_id=FREEZE_ACTION_ID,
            idempotency_key="freeze:stale",
            request_digest=FREEZE_DIGEST,
            expected_access_version=expected_access_version,
            expected_barrier_generation=expected_barrier_generation,
        )

    assert error.value.code == code


def test_resume_starts_only_from_fully_suspended_with_new_candidate_generation():
    suspended = _fully_suspended()

    transition = _request_resolution(suspended)

    assert transition.state.tenant_status is TenantStatus.RESUMING
    assert transition.state.phase is SuspensionPhase.RESOLVING
    assert transition.state.tenant_access_version == 9
    assert transition.state.barrier_generation == 2
    assert transition.state.desired_dml_login_state is DmlLoginState.LOCKED
    assert transition.state.published_dml_generation == 3
    assert transition.state.candidate_dml_generation == 4
    assert transition.state.latest_dml_generation == 4
    assert SuspensionEffectKind.CREATE_LOCKED_UNPUBLISHED_DML_CANDIDATE in {
        effect.kind for effect in transition.effects
    }
    assert SuspensionEffectKind.PUBLISH_VALIDATED_DML_CANDIDATE not in {
        effect.kind for effect in transition.effects
    }

    freezing = _request_freeze().state
    with pytest.raises(SuspensionTransitionError) as error:
        request_resume(
            freezing,
            action_id=RESUME_ACTION_ID,
            idempotency_key="resume:too-early",
            request_digest=RESUME_DIGEST,
            expected_access_version=freezing.tenant_access_version,
            expected_barrier_generation=freezing.barrier_generation,
        )
    assert error.value.code == "SUSPENSION_ACTION_CONFLICT"


@pytest.mark.parametrize(
    ("expires_at", "expected_status"),
    [
        (DATABASE_NOW + timedelta(microseconds=1), TenantStatus.ACTIVE),
        (DATABASE_NOW, TenantStatus.EXPIRED),
        (DATABASE_NOW - timedelta(days=30), TenantStatus.EXPIRED),
    ],
)
def test_resume_final_cas_reduces_from_realtime_subscription_expiry(
    expires_at,
    expected_status,
):
    resuming = _request_resolution().state

    transition = complete_resume(
        resuming,
        evidence=_resume_evidence(resuming),
        subscription_expires_at=expires_at,
        database_now=DATABASE_NOW,
    )

    assert transition.state.tenant_status is expected_status
    assert transition.state.phase is SuspensionPhase.RESOLVED
    assert transition.state.desired_dml_login_state is DmlLoginState.ACTIVE
    assert transition.state.published_dml_generation == 4
    assert transition.state.candidate_dml_generation is None
    assert (
        transition.state.last_resume_resolution.resulting_tenant_status
        is expected_status
    )
    assert {effect.kind for effect in transition.effects} == {
        SuspensionEffectKind.REVOKE_ALL_SESSIONS,
        SuspensionEffectKind.PUBLISH_VALIDATED_DML_CANDIDATE,
    }
    assert transition.subscription_expiry_changed is False
    assert transition.service_time_compensated is False
    assert transition.redemption_code_consumed is False


def test_adjusted_expiry_during_suspension_does_not_resume_until_final_cas():
    suspended = _fully_suspended(TenantStatus.EXPIRED)
    adjusted_expiry = DATABASE_NOW + timedelta(days=5)

    assert suspended.tenant_status is TenantStatus.SUSPENDED
    assert suspended.desired_dml_login_state is DmlLoginState.LOCKED

    resuming = _request_resolution(suspended).state
    assert resuming.tenant_status is TenantStatus.RESUMING
    assert resuming.desired_dml_login_state is DmlLoginState.LOCKED

    completed = complete_resume(
        resuming,
        evidence=_resume_evidence(resuming),
        subscription_expires_at=adjusted_expiry,
        database_now=DATABASE_NOW,
    )
    assert completed.state.tenant_status is TenantStatus.ACTIVE
    assert completed.state.last_resume_resolution.subscription_expires_at_utc == (
        adjusted_expiry
    )


def test_resume_failure_keeps_old_route_and_unpublished_candidate_denied():
    resuming = _request_resolution().state

    failed = fail_current_barrier(
        resuming,
        action_id=RESUME_ACTION_ID,
        barrier_generation=resuming.barrier_generation,
        tenant_access_version=resuming.tenant_access_version,
        failure_code="CROSS_SCHEMA_PROBE_FAILED",
    )

    assert failed.state.tenant_status is TenantStatus.RESUMING
    assert failed.state.phase is SuspensionPhase.RESOLVING
    assert failed.state.desired_dml_login_state is DmlLoginState.LOCKED
    assert failed.state.published_dml_generation == 3
    assert failed.state.candidate_dml_generation == 4
    assert SuspensionEffectKind.LOCK_UNPUBLISHED_DML_CANDIDATE in {
        effect.kind for effect in failed.effects
    }

    recovered = complete_resume(
        failed.state,
        evidence=_resume_evidence(failed.state),
        subscription_expires_at=DATABASE_NOW + timedelta(days=1),
        database_now=DATABASE_NOW,
    )
    assert recovered.state.tenant_status is TenantStatus.ACTIVE
    assert recovered.state.published_dml_generation == 4


@pytest.mark.parametrize(
    "missing_proof",
    [
        "candidate_started_locked",
        "candidate_unpublished",
        "database_identity_verified",
        "required_permissions_verified",
        "cross_schema_access_denied",
        "old_dml_generations_locked",
    ],
)
def test_resume_never_publishes_with_an_incomplete_candidate_proof(missing_proof):
    resuming = _request_resolution().state

    with pytest.raises(SuspensionTransitionError) as error:
        complete_resume(
            resuming,
            evidence=_resume_evidence(resuming, **{missing_proof: False}),
            subscription_expires_at=DATABASE_NOW + timedelta(days=1),
            database_now=DATABASE_NOW,
        )

    assert error.value.code == "RESUME_CANDIDATE_VERIFICATION_INCOMPLETE"
    assert resuming.tenant_status is TenantStatus.RESUMING
    assert resuming.published_dml_generation == 3


def test_stale_candidate_and_stale_freeze_completion_cannot_win_races():
    suspended = _fully_suspended()
    resuming = _request_resolution(suspended).state

    stale_candidate = _resume_evidence(
        resuming,
        candidate_dml_generation=resuming.candidate_dml_generation + 1,
    )
    with pytest.raises(SuspensionTransitionError) as candidate_error:
        complete_resume(
            resuming,
            evidence=stale_candidate,
            subscription_expires_at=DATABASE_NOW + timedelta(days=1),
            database_now=DATABASE_NOW,
        )
    assert candidate_error.value.code == "STALE_DML_CANDIDATE_GENERATION"

    with pytest.raises(SuspensionTransitionError) as action_error:
        complete_suspend(
            resuming,
            evidence=_freeze_evidence(suspended),
        )
    assert action_error.value.code == "STALE_SUSPENSION_ACTION"


def test_resume_compares_absolute_instants_and_records_normalized_utc():
    resuming = _request_resolution().state
    expires_at_shanghai = datetime(
        2026,
        8,
        22,
        20,
        1,
        tzinfo=timezone(timedelta(hours=8)),
    )

    completed = complete_resume(
        resuming,
        evidence=_resume_evidence(resuming),
        subscription_expires_at=expires_at_shanghai,
        database_now=DATABASE_NOW,
    )

    resolution = completed.state.last_resume_resolution
    assert completed.state.tenant_status is TenantStatus.ACTIVE
    assert resolution.subscription_expires_at_utc == datetime(
        2026, 8, 22, 12, 1, tzinfo=timezone.utc
    )
    assert resolution.database_now_utc == DATABASE_NOW


@pytest.mark.parametrize(
    ("expires_at", "database_now"),
    [
        (DATABASE_NOW.replace(tzinfo=None), DATABASE_NOW),
        (DATABASE_NOW, DATABASE_NOW.replace(tzinfo=None)),
    ],
)
def test_resume_requires_timezone_aware_database_facts(expires_at, database_now):
    resuming = _request_resolution().state

    with pytest.raises(SuspensionTransitionError) as error:
        complete_resume(
            resuming,
            evidence=_resume_evidence(resuming),
            subscription_expires_at=expires_at,
            database_now=database_now,
        )

    assert error.value.code == "SUSPENSION_TIME_MUST_BE_TIMEZONE_AWARE"
    assert resuming.tenant_status is TenantStatus.RESUMING


def test_completed_resume_retry_returns_the_original_database_time_result():
    resuming = _request_resolution().state
    completed = complete_resume(
        resuming,
        evidence=_resume_evidence(resuming),
        subscription_expires_at=DATABASE_NOW + timedelta(days=1),
        database_now=DATABASE_NOW,
    )

    retry = complete_resume(
        completed.state,
        evidence=_resume_evidence(resuming),
        subscription_expires_at=DATABASE_NOW - timedelta(days=1),
        database_now=DATABASE_NOW + timedelta(hours=1),
    )

    assert retry.idempotent
    assert retry.state == completed.state
    assert retry.state.tenant_status is TenantStatus.ACTIVE
    assert retry.state.last_resume_resolution.database_now_utc == DATABASE_NOW


def test_unknown_and_unrelated_tenant_states_fail_closed():
    unrelated = SuspensionState(
        tenant_status=TenantStatus.DELETED,
        tenant_access_version=7,
        barrier_generation=0,
        phase=None,
        current_action=None,
        desired_dml_login_state=DmlLoginState.LOCKED,
        published_dml_generation=3,
        latest_dml_generation=3,
    )

    with pytest.raises(SuspensionTransitionError) as error:
        _request_freeze(unrelated)
    assert error.value.code == "SUSPEND_STATE_INELIGIBLE"

    with pytest.raises(TypeError, match="TenantStatus"):
        SuspensionState(
            tenant_status="closed",
            tenant_access_version=7,
            barrier_generation=0,
            phase=None,
            current_action=None,
            desired_dml_login_state=DmlLoginState.LOCKED,
            published_dml_generation=3,
            latest_dml_generation=3,
        )


def test_state_effects_and_results_are_immutable():
    transition = _request_freeze()

    with pytest.raises(FrozenInstanceError):
        transition.state.tenant_status = TenantStatus.ACTIVE
    with pytest.raises(FrozenInstanceError):
        transition.effects[0].kind = SuspensionEffectKind.BLOCK_JOB_LEASES
    with pytest.raises(FrozenInstanceError):
        transition.idempotent = True
