from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from inventory_control.domain.tenant_gate import TenantStatus
from inventory_control.lifecycle.deletion import (
    DELETION_COOLING_PERIOD,
    DeletionActionKind,
    DeletionClaimReleaseEvidence,
    DeletionEffectKind,
    DeletionExecutorFenceEvidence,
    DeletionIsolationEvidence,
    DeletionLifecycleContext,
    DeletionLockdownEvidence,
    DeletionReviewDecision,
    DeletionTombstone,
    DestructiveCleanupEvidence,
    OffsiteTombstoneAck,
    begin_deletion_commit,
    begin_destructive_cleanup,
    begin_provider_claim_release,
    complete_approval_lockdown,
    complete_deletion,
    confirm_offsite_tombstone,
    record_permanent_tombstone,
    request_deletion,
    review_deletion,
)
from inventory_control.lifecycle.deletion_persistence import (
    DeletionActionIdentity,
    DeletionEvidenceVerification,
    DeletionExecutorLease,
    DeletionPersistenceAuthorityError,
    DeletionPersistenceConflictError,
    DeletionPersistenceEvidenceError,
    DeletionPersistenceLeaseError,
    DeletionPersistenceTransactionError,
    RecoveryDispositionVerification,
    TenantDeletionPersistenceCoordinator,
)
from inventory_control.models import (
    ControlBase,
    DisasterRecoveryRun,
    Tenant,
    TenantDatabase,
    TenantDeletionAction,
    TenantDeletionEffect,
    TenantDeletionEvidenceReceipt,
    TenantDeletionRequest,
    TenantDeletionTombstone,
    TenantRecoveryHold,
)


TENANT_ID = UUID("10000000-0000-0000-0000-000000000001")
DATABASE_ID = UUID("20000000-0000-0000-0000-000000000002")
ADMIN_ID = UUID("30000000-0000-0000-0000-000000000003")
REVIEWER_ID = UUID("40000000-0000-0000-0000-000000000004")
REQUEST_ID = UUID("50000000-0000-0000-0000-000000000005")
REQUEST_ACTION_ID = UUID("60000000-0000-0000-0000-000000000006")
REVIEW_ACTION_ID = UUID("70000000-0000-0000-0000-000000000007")
COMMIT_ACTION_ID = UUID("80000000-0000-0000-0000-000000000008")
REQUEST_CHALLENGE_ID = UUID("90000000-0000-0000-0000-000000000009")
RECOVERY_RUN_ID = UUID("a0000000-0000-0000-0000-00000000000a")
RECOVERY_HOLD_ID = UUID("b0000000-0000-0000-0000-00000000000b")
REGISTRATION_COMMIT_ID = UUID("c0000000-0000-0000-0000-00000000000c")
NOW = datetime(2026, 8, 22, 3, 0, tzinfo=timezone.utc)
REQUEST_DIGEST = b"r" * 32
REVIEW_DIGEST = b"v" * 32
COMMIT_DIGEST = b"m" * 32
LEASE_DIGEST = b"l" * 32
HEAD_HASH = b"h" * 32
RECORD_HASH = b"t" * 32


@dataclass
class _Clock:
    now: datetime

    def __call__(self, session: Session) -> datetime:
        del session
        return self.now


class _TrustedEvidenceReader:
    def __call__(
        self,
        session: Session,
        *,
        receipt_kind: str,
        evidence: object,
        evidence_digest: bytes,
        prior_state,
        transition,
        database_now_utc: datetime,
    ) -> DeletionEvidenceVerification:
        del evidence, prior_state, transition
        verifier = {
            "lockdown": "control_current_read",
            "isolation": "control_current_read",
            "executor_fence": "control_current_read",
            "offsite_ack": "nas_authenticated_ack",
            "claim_release": "provider_claim_current_read",
            "destructive_cleanup": "destructive_current_read",
            "cancellation": "control_current_read",
        }[receipt_kind]
        recovery = None
        if receipt_kind in {"claim_release", "destructive_cleanup"}:
            hold = session.get(TenantRecoveryHold, str(RECOVERY_HOLD_ID))
            assert hold is not None
            recovery = RecoveryDispositionVerification(
                recovery_run_id=RECOVERY_RUN_ID,
                recovery_hold_id=RECOVERY_HOLD_ID,
                recovery_hold_revision=hold.hold_revision,
                disposition_digest=b"d" * 32,
                all_required_dispositions_complete=True,
            )
        return DeletionEvidenceVerification(
            verifier_kind=verifier,
            evidence_digest=evidence_digest,
            verified_at_utc=database_now_utc,
            verified=True,
            recovery_disposition=recovery,
        )


@pytest.fixture
def session_factory(mysql_control_database):
    factory = sessionmaker(
        bind=mysql_control_database.engine,
        expire_on_commit=False,
    )
    _seed_authority(factory)
    return factory


def _seed_authority(factory: sessionmaker) -> None:
    with factory.begin() as session:
        run = DisasterRecoveryRun(
            id=str(RECOVERY_RUN_ID),
            kind="initial_baseline",
            policy_version=1,
            status="completed",
            expected_survivor_count=1,
            actual_survivor_count=1,
            host_installation_fingerprint="h" * 64,
            deployment_marker_fingerprint="m" * 64,
            row_version=1,
            started_at=NOW,
            reviewing_at=NOW,
            completed_at=NOW,
        )
        tenant = Tenant(
            id=str(TENANT_ID),
            name="tenant",
            slug="tenant",
            status="active",
            access_version=1,
            row_version=1,
            timezone="Asia/Shanghai",
            locale="zh-CN",
        )
        session.add_all([run, tenant])
        session.flush()
        session.add_all(
            [
                TenantRecoveryHold(
                    id=str(RECOVERY_HOLD_ID),
                    recovery_run_id=str(RECOVERY_RUN_ID),
                    tenant_id=str(TENANT_ID),
                    database_uuid=str(DATABASE_ID),
                    created_from_registration_commit_uuid=str(
                        REGISTRATION_COMMIT_ID
                    ),
                    initial_hold_revision=1,
                    state="released",
                    hold_revision=1,
                    snapshot_underlying_status="active",
                    snapshot_access_version=1,
                    expected_dml_login_state_version=1,
                    dml_convergence_status="active",
                    held_at=NOW,
                    released_at=NOW,
                    row_version=1,
                ),
                TenantDatabase(
                    tenant_id=str(TENANT_ID),
                    database_uuid=str(DATABASE_ID),
                    database_instance_key="primary",
                    database_name="tenant_0001",
                    status="ready",
                    schema_version="1",
                    activated_by_registration_commit_uuid=str(
                        REGISTRATION_COMMIT_ID
                    ),
                    activation_route_version=1,
                    activation_credential_generation=1,
                    dml_username="tenant_dml_1",
                    dml_credential_generation=1,
                    dml_root_key_version=1,
                    dml_derivation_version=1,
                    route_version=1,
                    dml_desired_login_state="active",
                    dml_observed_login_state="active",
                    dml_login_state_version=1,
                    dml_desired_state_recovery_run_id=str(RECOVERY_RUN_ID),
                    platform_read_username="tenant_read_1",
                    platform_read_credential_generation=1,
                    platform_read_root_key_version=1,
                    platform_read_derivation_version=1,
                    platform_read_route_version=1,
                    row_version=1,
                ),
            ]
        )


def _context(now: datetime) -> DeletionLifecycleContext:
    return DeletionLifecycleContext(
        tenant_status=TenantStatus.ACTIVE,
        suspension_phase=None,
        recovery_hold_released=True,
        subscription_expires_at_utc=now + timedelta(days=365),
        database_now_utc=now,
    )


def _request_identity(digest: bytes = REQUEST_DIGEST) -> DeletionActionIdentity:
    return DeletionActionIdentity(
        action_id=REQUEST_ACTION_ID,
        kind=DeletionActionKind.REQUEST,
        idempotency_key="delete-request",
        request_digest=digest,
    )


def _request_reducer(state):
    return request_deletion(
        state,
        context=_context(NOW),
        request_id=REQUEST_ID,
        action_id=REQUEST_ACTION_ID,
        requested_by_user_id=ADMIN_ID,
        idempotency_key="delete-request",
        request_digest=REQUEST_DIGEST,
        requested_at_utc=NOW,
        actor_is_active_admin=True,
        purpose_bound_otp_verified=True,
        expected_access_version=1,
    )


def _tenant_version(session: Session) -> int:
    tenant = session.get(Tenant, str(TENANT_ID))
    assert tenant is not None
    return tenant.row_version


def test_requires_explicit_transaction_and_rolls_back_with_caller(session_factory):
    clock = _Clock(NOW)
    coordinator = TenantDeletionPersistenceCoordinator(database_clock=clock)
    session = session_factory()
    try:
        with pytest.raises(DeletionPersistenceTransactionError) as captured:
            coordinator.apply(
                session,
                tenant_uuid=TENANT_ID,
                expected_tenant_row_version=1,
                reduce=_request_reducer,
                action_identity=_request_identity(),
                request_challenge_uuid=REQUEST_CHALLENGE_ID,
            )
        assert captured.value.code == "DELETION_CALLER_TRANSACTION_REQUIRED"

        transaction = session.begin()
        result = coordinator.apply(
            session,
            tenant_uuid=TENANT_ID,
            expected_tenant_row_version=1,
            reduce=_request_reducer,
            action_identity=_request_identity(),
            request_challenge_uuid=REQUEST_CHALLENGE_ID,
        )
        assert result.state.request is not None
        assert result.effects == ()
        assert session.get(TenantDeletionRequest, str(REQUEST_ID)) is not None
        transaction.rollback()
    finally:
        session.close()

    with session_factory() as check:
        assert check.get(TenantDeletionRequest, str(REQUEST_ID)) is None
        assert check.get(TenantDeletionAction, str(REQUEST_ACTION_ID)) is None


def test_roundtrip_and_historical_action_idempotency_are_fail_closed(
    session_factory,
):
    coordinator = TenantDeletionPersistenceCoordinator(database_clock=_Clock(NOW))
    with session_factory.begin() as session:
        created = coordinator.apply(
            session,
            tenant_uuid=TENANT_ID,
            expected_tenant_row_version=1,
            reduce=_request_reducer,
            action_identity=_request_identity(),
            request_challenge_uuid=REQUEST_CHALLENGE_ID,
        )
        assert created.state.request is not None
        assert created.state.request.request_id == REQUEST_ID

    with session_factory.begin() as session:
        replay = coordinator.apply(
            session,
            tenant_uuid=TENANT_ID,
            expected_tenant_row_version=1,
            reduce=lambda state: pytest.fail("historical replay reached reducer"),
            action_identity=_request_identity(),
        )
        assert replay.replayed
        assert replay.state.request is not None
        assert replay.state.request.request_id == REQUEST_ID

    with session_factory.begin() as session:
        with pytest.raises(DeletionPersistenceConflictError) as captured:
            coordinator.apply(
                session,
                tenant_uuid=TENANT_ID,
                expected_tenant_row_version=1,
                reduce=lambda state: pytest.fail("conflict reached reducer"),
                action_identity=_request_identity(b"x" * 32),
            )
        assert captured.value.code == "DELETION_ACTION_IDEMPOTENCY_CONFLICT"


def test_new_request_uses_current_recovery_authority_and_fails_closed(
    session_factory,
):
    coordinator = TenantDeletionPersistenceCoordinator(database_clock=_Clock(NOW))
    with session_factory.begin() as session:
        hold = session.get(TenantRecoveryHold, str(RECOVERY_HOLD_ID))
        assert hold is not None
        hold.state = "held"
        hold.hold_revision += 1
        hold.row_version += 1

    with session_factory.begin() as session:
        with pytest.raises(DeletionPersistenceAuthorityError) as captured:
            coordinator.apply(
                session,
                tenant_uuid=TENANT_ID,
                expected_tenant_row_version=1,
                reduce=_request_reducer,
                action_identity=_request_identity(),
                request_challenge_uuid=REQUEST_CHALLENGE_ID,
            )
        assert captured.value.code == "DELETION_RECOVERY_GATE_NOT_RELEASED"

    with session_factory.begin() as session:
        assert session.get(TenantDeletionRequest, str(REQUEST_ID)) is None


def test_persists_full_irreversible_barrier_without_external_calls(
    session_factory,
):
    clock = _Clock(NOW)
    reader = _TrustedEvidenceReader()
    coordinator = TenantDeletionPersistenceCoordinator(
        evidence_current_read=reader,
        database_clock=clock,
    )

    with session_factory.begin() as session:
        requested = coordinator.apply(
            session,
            tenant_uuid=TENANT_ID,
            expected_tenant_row_version=1,
            reduce=_request_reducer,
            action_identity=_request_identity(),
            request_challenge_uuid=REQUEST_CHALLENGE_ID,
        )

    reviewed_at = NOW + timedelta(minutes=1)
    clock.now = reviewed_at
    with session_factory.begin() as session:
        requested_state = requested.state
        reviewed = coordinator.apply(
            session,
            tenant_uuid=TENANT_ID,
            expected_tenant_row_version=_tenant_version(session),
            reduce=lambda state: review_deletion(
                state,
                context=_context(reviewed_at),
                decision=DeletionReviewDecision.APPROVE,
                action_id=REVIEW_ACTION_ID,
                platform_reviewer_id=REVIEWER_ID,
                reviewer_is_active_platform_admin=True,
                idempotency_key="approve-delete",
                request_digest=REVIEW_DIGEST,
                reviewed_at_utc=reviewed_at,
                expected_request_revision=(
                    requested_state.request.revision  # type: ignore[union-attr]
                ),
                expected_access_version=requested_state.tenant_access_version,
                expected_execution_generation=(
                    requested_state.request.execution_generation  # type: ignore[union-attr]
                ),
                expected_executor_fencing_token=(
                    requested_state.request.executor_fencing_token  # type: ignore[union-attr]
                ),
            ),
            action_identity=DeletionActionIdentity(
                action_id=REVIEW_ACTION_ID,
                kind=DeletionActionKind.REVIEW_APPROVE,
                idempotency_key="approve-delete",
                request_digest=REVIEW_DIGEST,
            ),
        )
        assert {effect.fact.kind for effect in reviewed.effects} == {
            DeletionEffectKind.REVOKE_ALL_SESSIONS,
            DeletionEffectKind.DISPOSE_TENANT_ENGINES,
            DeletionEffectKind.BLOCK_JOB_LEASES,
            DeletionEffectKind.BLOCK_PROVIDER_SUBMISSIONS,
            DeletionEffectKind.SET_DESIRED_DML_LOCKED,
            DeletionEffectKind.LOCK_ALL_DML_IDENTITIES,
            DeletionEffectKind.CREATE_DELETION_ENFORCE_LOCKED_ACTION,
            DeletionEffectKind.SUPERSEDE_LOWER_PRIORITY_LIFECYCLE_ACTIONS,
        }

    # A lost success response must replay by immutable action identity even
    # though the successful approval already advanced the tenant row version.
    with session_factory.begin() as session:
        replay = coordinator.apply(
            session,
            tenant_uuid=TENANT_ID,
            expected_tenant_row_version=1,
            reduce=lambda state: pytest.fail("approval replay reached reducer"),
            action_identity=DeletionActionIdentity(
                action_id=REVIEW_ACTION_ID,
                kind=DeletionActionKind.REVIEW_APPROVE,
                idempotency_key="approve-delete",
                request_digest=REVIEW_DIGEST,
            ),
        )
        assert replay.replayed
        assert replay.state.request is not None
        assert replay.state.request.status.value == "cooling_off"

    lease = _acquire_lease(coordinator, session_factory)
    _complete_effects(coordinator, session_factory, reviewed.effects, lease)
    approved = _complete_lockdown(
        coordinator,
        session_factory,
        lease,
    )

    # The 30-day boundary necessarily outlives a short worker lease.  Reusing
    # the expired opaque token still creates a new generation/fence and resets
    # the lockdown barrier instead of letting the old proof pass.
    assert approved.state.request is not None
    clock.now = approved.state.request.execute_not_before_utc
    takeover = _acquire_lease(coordinator, session_factory)
    assert takeover.execution_generation > lease.execution_generation
    with session_factory.begin() as session:
        with pytest.raises(DeletionPersistenceLeaseError) as captured:
            coordinator.complete_effect(
                session,
                tenant_uuid=TENANT_ID,
                effect_uuid=reviewed.effects[0].effect_id,
                executor_lease=lease,
                result_digest=b"x" * 32,
                safe_outcome_code="EFFECT_VERIFIED",
                succeeded=True,
            )
        assert captured.value.code == "STALE_DELETION_EXECUTOR_LEASE"
    with session_factory.begin() as session:
        action = session.get(TenantDeletionAction, str(REVIEW_ACTION_ID))
        assert action is not None
        assert action.outcome == "running"
    with session_factory.begin() as session:
        takeover_effects = tuple(
            session.scalars(
                sa.select(TenantDeletionEffect).where(
                    TenantDeletionEffect.action_id == str(REVIEW_ACTION_ID),
                    TenantDeletionEffect.execution_generation
                    == takeover.execution_generation,
                )
            )
        )
    _complete_effect_rows(
        coordinator,
        session_factory,
        takeover_effects,
        takeover,
    )
    approved = _complete_lockdown(
        coordinator,
        session_factory,
        takeover,
    )

    with session_factory.begin() as session:
        state = coordinator.load_for_update(session, tenant_uuid=TENANT_ID)
        assert state.request is not None
        committing = coordinator.apply(
            session,
            tenant_uuid=TENANT_ID,
            expected_tenant_row_version=_tenant_version(session),
            reduce=lambda current: begin_deletion_commit(
                current,
                action_id=COMMIT_ACTION_ID,
                idempotency_key="commit-delete",
                request_digest=COMMIT_DIGEST,
                database_now_utc=clock.now,
                expected_request_revision=current.request.revision,  # type: ignore[union-attr]
                expected_access_version=current.tenant_access_version,
                expected_execution_generation=current.request.execution_generation,  # type: ignore[union-attr]
                expected_executor_fencing_token=current.request.executor_fencing_token,  # type: ignore[union-attr]
                lease_fence_verified=True,
            ),
            action_identity=DeletionActionIdentity(
                action_id=COMMIT_ACTION_ID,
                kind=DeletionActionKind.COMMIT,
                idempotency_key="commit-delete",
                request_digest=COMMIT_DIGEST,
            ),
            executor_lease=takeover,
        )
        assert committing.state.request is not None
        assert committing.state.request.status.value == "committing"

    lease = _acquire_lease(coordinator, session_factory)
    _complete_effects(coordinator, session_factory, committing.effects, lease)

    tombstone = DeletionTombstone(
        request_id=REQUEST_ID,
        tenant_id=TENANT_ID,
        database_id=DATABASE_ID,
        sequence=1,
        previous_hash=None,
        record_hash=RECORD_HASH,
        head_hash=HEAD_HASH,
        checkpoint_root_key_version=1,
        checkpoint_mac=b"k" * 32,
        recorded_at_utc=clock.now,
    )
    with session_factory.begin() as session:
        state = coordinator.load_for_update(session, tenant_uuid=TENANT_ID)
        assert state.request is not None
        isolation = _isolation(state)
        awaiting = coordinator.apply(
            session,
            tenant_uuid=TENANT_ID,
            expected_tenant_row_version=_tenant_version(session),
            reduce=lambda current: record_permanent_tombstone(
                current,
                tombstone=tombstone,
                evidence=isolation,
                expected_request_revision=current.request.revision,  # type: ignore[union-attr]
            ),
            executor_lease=lease,
            evidence=isolation,
        )
        assert awaiting.state.request is not None
        assert awaiting.state.request.status.value == "awaiting_offsite_ack"
        persisted = session.get(TenantDeletionTombstone, str(REQUEST_ID))
        assert persisted is not None
        assert persisted.offsite_acknowledged_at is None

    _complete_effects(coordinator, session_factory, awaiting.effects, lease)
    clock.now += timedelta(seconds=1)
    acknowledgment = OffsiteTombstoneAck(
        sequence=1,
        head_hash=HEAD_HASH,
        artifact_checksum=b"a" * 32,
        acknowledged_at_utc=clock.now,
        authenticated=True,
        durably_persisted=True,
        checksum_verified=True,
        chain_verified=True,
    )
    with session_factory.begin() as session:
        state = coordinator.load_for_update(session, tenant_uuid=TENANT_ID)
        fence = _executor_fence(state)
        acked = coordinator.apply(
            session,
            tenant_uuid=TENANT_ID,
            expected_tenant_row_version=_tenant_version(session),
            reduce=lambda current: confirm_offsite_tombstone(
                current,
                acknowledgment=acknowledgment,
                executor_fence=fence,
                expected_request_revision=current.request.revision,  # type: ignore[union-attr]
            ),
            executor_lease=lease,
            evidence=fence,
        )
        assert acked.state.request is not None
        assert acked.state.request.offsite_ack == acknowledgment

    with session_factory.begin() as session:
        state = coordinator.load_for_update(session, tenant_uuid=TENANT_ID)
        releasing = coordinator.apply(
            session,
            tenant_uuid=TENANT_ID,
            expected_tenant_row_version=_tenant_version(session),
            reduce=lambda current: begin_provider_claim_release(
                current,
                expected_request_revision=current.request.revision,  # type: ignore[union-attr]
                expected_access_version=current.tenant_access_version,
                expected_execution_generation=current.request.execution_generation,  # type: ignore[union-attr]
                expected_executor_fencing_token=current.request.executor_fencing_token,  # type: ignore[union-attr]
                lease_fence_verified=True,
            ),
            executor_lease=lease,
        )
        assert releasing.state.request is not None
        assert releasing.state.request.status.value == "releasing_claims"
        assert DeletionEffectKind.DROP_TENANT_SCHEMA not in {
            effect.fact.kind for effect in releasing.effects
        }

    claim_isolation_effects = tuple(
        effect
        for effect in releasing.effects
        if effect.fact.kind is DeletionEffectKind.ISOLATE_PROVIDER_OPERATIONS
    )
    assert len(claim_isolation_effects) == 1
    assert claim_isolation_effects[0].fact.tombstone_sequence == 1
    with session_factory.begin() as session:
        isolation_rows = tuple(
            session.scalars(
                sa.select(TenantDeletionEffect).where(
                    TenantDeletionEffect.action_id == str(COMMIT_ACTION_ID),
                    TenantDeletionEffect.effect_kind
                    == DeletionEffectKind.ISOLATE_PROVIDER_OPERATIONS.value,
                )
            )
        )
        assert {row.tombstone_sequence for row in isolation_rows} == {None, 1}

    # The commit-stage isolation receipt cannot satisfy the later claim-stage
    # operation fence merely because both facts share one action/generation.
    _complete_effects(
        coordinator,
        session_factory,
        tuple(
            effect
            for effect in releasing.effects
            if effect.fact.kind
            is not DeletionEffectKind.ISOLATE_PROVIDER_OPERATIONS
        ),
        lease,
    )
    with session_factory.begin() as session:
        state = coordinator.load_for_update(session, tenant_uuid=TENANT_ID)
        evidence = _claim_release(state)
        with pytest.raises(DeletionPersistenceEvidenceError) as captured:
            coordinator.apply(
                session,
                tenant_uuid=TENANT_ID,
                expected_tenant_row_version=_tenant_version(session),
                reduce=lambda current: begin_destructive_cleanup(
                    current,
                    evidence=evidence,
                    expected_request_revision=current.request.revision,  # type: ignore[union-attr]
                    expected_access_version=current.tenant_access_version,
                    expected_execution_generation=current.request.execution_generation,  # type: ignore[union-attr]
                    expected_executor_fencing_token=current.request.executor_fencing_token,  # type: ignore[union-attr]
                    lease_fence_verified=True,
                ),
                executor_lease=lease,
                evidence=evidence,
            )
        assert captured.value.code == "DELETION_EFFECT_BARRIER_INCOMPLETE"

    _complete_effects(
        coordinator,
        session_factory,
        claim_isolation_effects,
        lease,
    )
    with session_factory.begin() as session:
        state = coordinator.load_for_update(session, tenant_uuid=TENANT_ID)
        evidence = _claim_release(state)
        with pytest.raises(DeletionPersistenceEvidenceError) as captured:
            coordinator.apply(
                session,
                tenant_uuid=TENANT_ID,
                expected_tenant_row_version=_tenant_version(session),
                reduce=lambda current: begin_destructive_cleanup(
                    current,
                    evidence=evidence,
                    expected_request_revision=current.request.revision,  # type: ignore[union-attr]
                    expected_access_version=current.tenant_access_version,
                    expected_execution_generation=current.request.execution_generation,  # type: ignore[union-attr]
                    expected_executor_fencing_token=current.request.executor_fencing_token,  # type: ignore[union-attr]
                    lease_fence_verified=True,
                ),
                executor_lease=lease,
                evidence=evidence,
            )
        assert captured.value.code == "DELETION_RECOVERY_DISPOSITION_INCOMPLETE"

    with session_factory.begin() as session:
        hold = session.get(TenantRecoveryHold, str(RECOVERY_HOLD_ID))
        assert hold is not None
        hold.state = "tombstoned"
        hold.terminal_reason_code = "superseded_by_deletion"
        hold.deletion_request_uuid = str(REQUEST_ID)
        hold.tombstone_ledger_sequence = 1
        hold.tombstone_record_hash = RECORD_HASH
        hold.tombstoned_at = clock.now
        hold.hold_revision += 1
        hold.row_version += 1

    with session_factory.begin() as session:
        state = coordinator.load_for_update(session, tenant_uuid=TENANT_ID)
        evidence = _claim_release(state)
        dropping = coordinator.apply(
            session,
            tenant_uuid=TENANT_ID,
            expected_tenant_row_version=_tenant_version(session),
            reduce=lambda current: begin_destructive_cleanup(
                current,
                evidence=evidence,
                expected_request_revision=current.request.revision,  # type: ignore[union-attr]
                expected_access_version=current.tenant_access_version,
                expected_execution_generation=current.request.execution_generation,  # type: ignore[union-attr]
                expected_executor_fencing_token=current.request.executor_fencing_token,  # type: ignore[union-attr]
                lease_fence_verified=True,
            ),
            executor_lease=lease,
            evidence=evidence,
        )
        assert dropping.state.request is not None
        assert dropping.state.request.status.value == "dropping"
        assert DeletionEffectKind.DROP_TENANT_SCHEMA in {
            effect.fact.kind for effect in dropping.effects
        }
        receipt = session.scalar(
            sa.select(TenantDeletionEvidenceReceipt).where(
                TenantDeletionEvidenceReceipt.receipt_kind == "claim_release"
            )
        )
        assert receipt is not None
        assert receipt.recovery_run_id == str(RECOVERY_RUN_ID)
        assert receipt.recovery_hold_revision == 2

    _complete_effects(coordinator, session_factory, dropping.effects, lease)

    # A crash after route/account cleanup but before the final control CAS is
    # recoverable from the request snapshot; the route is no longer required.
    with session_factory.begin() as session:
        route = session.get(TenantDatabase, str(TENANT_ID))
        assert route is not None
        session.delete(route)

    # Keep the tenant row as the first lock through completion, then let the
    # caller minimize the request and tenant together at the end of this same
    # transaction.  The no-FK tombstone and recovery disposition survive.
    with session_factory.begin() as session:
        state = coordinator.load_for_update(session, tenant_uuid=TENANT_ID)
        assert state.request is not None
        cleanup = _cleanup(state)
        completed = coordinator.apply(
            session,
            tenant_uuid=TENANT_ID,
            expected_tenant_row_version=_tenant_version(session),
            reduce=lambda current: complete_deletion(
                current,
                evidence=cleanup,
                expected_request_revision=current.request.revision,  # type: ignore[union-attr]
            ),
            executor_lease=lease,
            evidence=cleanup,
        )
        assert completed.state.request is not None
        assert completed.state.request.status.value == "completed"
        assert completed.state.tenant_status is TenantStatus.DELETED
        for effect in completed.effects:
            coordinator.complete_effect(
                session,
                tenant_uuid=TENANT_ID,
                effect_uuid=effect.effect_id,
                executor_lease=lease,
                result_digest=hashlib.sha256(
                    effect.fact.kind.value.encode("ascii")
                ).digest(),
                safe_outcome_code="EFFECT_VERIFIED",
                succeeded=True,
            )
        request_row = session.get(TenantDeletionRequest, str(REQUEST_ID))
        tenant_row = session.get(Tenant, str(TENANT_ID))
        assert request_row is not None and tenant_row is not None
        session.delete(request_row)
        session.delete(tenant_row)

    with session_factory.begin() as session:
        assert session.get(Tenant, str(TENANT_ID)) is None
        assert session.get(TenantDatabase, str(TENANT_ID)) is None
        assert session.get(TenantDeletionRequest, str(REQUEST_ID)) is None
        assert session.get(TenantDeletionTombstone, str(REQUEST_ID)) is not None
        hold = session.get(TenantRecoveryHold, str(RECOVERY_HOLD_ID))
        assert hold is not None and hold.state == "tombstoned"


def _acquire_lease(
    coordinator: TenantDeletionPersistenceCoordinator,
    factory: sessionmaker,
) -> DeletionExecutorLease:
    with factory.begin() as session:
        state = coordinator.load_for_update(session, tenant_uuid=TENANT_ID)
        assert state.request is not None
        result = coordinator.acquire_executor_lease(
            session,
            tenant_uuid=TENANT_ID,
            request_uuid=state.request.request_id,
            expected_request_revision=state.request.revision,
            expected_execution_generation=state.request.execution_generation,
            expected_executor_fencing_token=state.request.executor_fencing_token,
            lease_owner="worker-1",
            lease_token_digest=LEASE_DIGEST,
            lease_duration=timedelta(minutes=30),
        )
        return result.lease


def _complete_effects(
    coordinator: TenantDeletionPersistenceCoordinator,
    factory: sessionmaker,
    effects,
    lease: DeletionExecutorLease,
) -> None:
    for effect in effects:
        if effect.state != "pending":
            continue
        with factory.begin() as session:
            coordinator.complete_effect(
                session,
                tenant_uuid=TENANT_ID,
                effect_uuid=effect.effect_id,
                executor_lease=lease,
                result_digest=hashlib.sha256(
                    effect.fact.kind.value.encode("ascii")
                ).digest(),
                safe_outcome_code="EFFECT_VERIFIED",
                succeeded=True,
            )


def _complete_effect_rows(
    coordinator: TenantDeletionPersistenceCoordinator,
    factory: sessionmaker,
    effects,
    lease: DeletionExecutorLease,
) -> None:
    for effect in effects:
        if effect.state != "pending":
            continue
        with factory.begin() as session:
            coordinator.complete_effect(
                session,
                tenant_uuid=TENANT_ID,
                effect_uuid=effect.id,
                executor_lease=lease,
                result_digest=hashlib.sha256(
                    effect.effect_kind.encode("ascii")
                ).digest(),
                safe_outcome_code="EFFECT_VERIFIED",
                succeeded=True,
            )


def _complete_lockdown(
    coordinator: TenantDeletionPersistenceCoordinator,
    factory: sessionmaker,
    lease: DeletionExecutorLease,
):
    with factory.begin() as session:
        state = coordinator.load_for_update(session, tenant_uuid=TENANT_ID)
        assert state.request is not None
        evidence = _lockdown(state)
        return coordinator.apply(
            session,
            tenant_uuid=TENANT_ID,
            expected_tenant_row_version=_tenant_version(session),
            reduce=lambda current: complete_approval_lockdown(
                current,
                evidence=evidence,
                expected_request_revision=current.request.revision,  # type: ignore[union-attr]
            ),
            executor_lease=lease,
            evidence=evidence,
        )


def _lockdown(state) -> DeletionLockdownEvidence:
    assert state.request is not None
    return DeletionLockdownEvidence(
        action_id=state.request.current_action.action_id,
        execution_generation=state.request.execution_generation,
        executor_fencing_token=state.request.executor_fencing_token,
        tenant_access_version=state.tenant_access_version,
        lease_fence_verified=True,
        sessions_revoked=True,
        tenant_engines_disposed=True,
        job_leases_blocked=True,
        provider_submissions_blocked=True,
        desired_dml_locked=True,
        all_dml_identities_locked=True,
    )


def _isolation(state) -> DeletionIsolationEvidence:
    assert state.request is not None
    return DeletionIsolationEvidence(
        action_id=state.request.current_action.action_id,
        execution_generation=state.request.execution_generation,
        executor_fencing_token=state.request.executor_fencing_token,
        tenant_access_version=state.tenant_access_version,
        lease_fence_verified=True,
        deletion_lockdown_complete=True,
        job_leases_reclaimed=True,
        provider_operations_isolated=True,
        all_dml_identities_locked=True,
    )


def _executor_fence(state) -> DeletionExecutorFenceEvidence:
    assert state.request is not None
    return DeletionExecutorFenceEvidence(
        action_id=state.request.current_action.action_id,
        execution_generation=state.request.execution_generation,
        executor_fencing_token=state.request.executor_fencing_token,
        tenant_access_version=state.tenant_access_version,
        lease_fence_verified=True,
    )


def _claim_release(state) -> DeletionClaimReleaseEvidence:
    assert state.request is not None and state.request.tombstone is not None
    return DeletionClaimReleaseEvidence(
        action_id=state.request.current_action.action_id,
        execution_generation=state.request.execution_generation,
        executor_fencing_token=state.request.executor_fencing_token,
        tenant_access_version=state.tenant_access_version,
        lease_fence_verified=True,
        tombstone_sequence=state.request.tombstone.sequence,
        tombstone_head_hash=state.request.tombstone.head_hash,
        reserved_binding_operations_fenced=True,
        bidirectional_bindings_verified=True,
        provider_operations_isolated=True,
        claims_released_or_valid_new_owner=True,
        valid_new_owner_claims_untouched=True,
        claim_release_events_appended=True,
        no_orphan_claims=True,
        recovery_dispositions_complete=True,
    )


def _cleanup(state) -> DestructiveCleanupEvidence:
    assert state.request is not None and state.request.tombstone is not None
    return DestructiveCleanupEvidence(
        action_id=state.request.current_action.action_id,
        execution_generation=state.request.execution_generation,
        executor_fencing_token=state.request.executor_fencing_token,
        tenant_access_version=state.tenant_access_version,
        lease_fence_verified=True,
        tombstone_sequence=state.request.tombstone.sequence,
        tombstone_head_hash=state.request.tombstone.head_hash,
        schema_absent=True,
        dml_identities_absent=True,
        platform_read_identities_absent=True,
        database_routes_absent=True,
        provider_accounts_and_bindings_absent=True,
        integration_secrets_absent=True,
        tenant_control_data_minimized=True,
        provider_operations_isolated=True,
        claims_released_or_valid_new_owner=True,
        no_orphan_claims=True,
        tenant_identity_removal_ready=True,
        phone_release_ready=True,
        cross_tenant_negative_checks_passed=True,
        recovery_dispositions_complete=True,
    )
