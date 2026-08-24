from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from inventory_control.crypto import ProviderAccountFingerprint
from inventory_control.domain import EffectiveTenantGate, TenantRole, TenantStatus
from inventory_control.integrations import (
    SfAdminClaimProof,
    SfClaimOwner,
    SfClaimPersistenceService,
    SfDeletionClaimProof,
)
from inventory_control.lifecycle.deletion import (
    DELETION_COOLING_PERIOD,
    DeletionAction,
    DeletionActionKind,
    DeletionActionOutcome,
    DeletionClaimReleaseEvidence,
    DeletionRequest,
    DeletionRequestStatus,
    DeletionState,
    DeletionTombstone,
    OffsiteTombstoneAck,
    begin_destructive_cleanup,
)
from inventory_control.lifecycle.deletion_adapters import (
    ControlDatabaseDeletionEvidenceAdapter,
    DeletionControlEvidenceError,
)
from inventory_control.lifecycle.deletion_persistence import (
    DeletionEvidenceCurrentRead,
    deletion_evidence_digest,
)
from inventory_control.lifecycle.suspension import DmlLoginState
from inventory_control.models import (
    ControlBase,
    DisasterRecoveryRun,
    ProviderAccountClaim,
    ProviderAccountClaimEvent,
    TenantRecoveryHold,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
CLAIM_TIME = NOW - timedelta(hours=1)
TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
NEW_TENANT_ID = UUID("10000000-0000-4000-8000-000000000002")
DATABASE_ID = UUID("20000000-0000-4000-8000-000000000001")
REQUEST_ID = UUID("30000000-0000-4000-8000-000000000001")
COMMIT_ACTION_ID = UUID("40000000-0000-4000-8000-000000000001")
WRONG_RELEASE_ACTION_ID = UUID("40000000-0000-4000-8000-000000000002")
RUN_ID = UUID("50000000-0000-4000-8000-000000000001")
HOLD_ID = UUID("60000000-0000-4000-8000-000000000001")
REQUESTOR_ID = UUID("70000000-0000-4000-8000-000000000001")
RECORD_HASH = hashlib.sha256(b"deletion-record").digest()
HEAD_HASH = hashlib.sha256(b"deletion-head").digest()
COMMIT_DIGEST = hashlib.sha256(b"delete-commit").digest()


@pytest.fixture
def session_factory(mysql_control_database):
    engine = mysql_control_database.engine
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    _seed_recovery(factory)
    yield factory


def test_current_read_proves_d58_hold_and_sf_claim_subset_without_writes(
    session_factory,
):
    _seed_claim(
        session_factory,
        claim_id=UUID("80000000-0000-4000-8000-000000000001"),
        fingerprint_byte=b"a",
        release_target=True,
    )
    _seed_claim(
        session_factory,
        claim_id=UUID("80000000-0000-4000-8000-000000000002"),
        fingerprint_byte=b"b",
        release_target=True,
        reassign_to_new_owner=True,
    )
    prior, transition, evidence = _transition()
    digest = deletion_evidence_digest(evidence)
    adapter = ControlDatabaseDeletionEvidenceAdapter()
    protocol_reader: DeletionEvidenceCurrentRead = adapter
    assert protocol_reader is adapter

    statements: list[str] = []
    engine = session_factory.kw["bind"]

    @event.listens_for(engine, "before_cursor_execute")
    def _capture(connection, cursor, statement, parameters, context, executemany):
        del connection, cursor, parameters, context, executemany
        statements.append(statement)

    try:
        with session_factory.begin() as session:
            facts = adapter.inspect_current(
                session,
                receipt_kind="claim_release",
                evidence=evidence,
                evidence_digest=digest,
                prior_state=prior,
                transition=transition,
                database_now_utc=NOW,
            )
            verification = adapter(
                session,
                receipt_kind="claim_release",
                evidence=evidence,
                evidence_digest=digest,
                prior_state=prior,
                transition=transition,
                database_now_utc=NOW,
            )
            assert not session.new and not session.dirty and not session.deleted
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    assert facts.provable_subset_verified
    assert not facts.complete_deletion_evidence_verified
    assert facts.recovery_run_id == str(RUN_ID)
    assert facts.recovery_hold_id == str(HOLD_ID)
    assert facts.recovery_hold_revision == 2
    assert facts.claims_scanned == 2
    assert facts.tenant_related_claims == 2
    assert facts.released_claims == 1
    assert facts.valid_new_owner_claims == 1
    assert facts.no_current_old_owner
    assert not facts.bidirectional_binding_inventory_verified
    assert not facts.reserved_operations_inventory_verified
    assert not facts.recovery_normalization_inventory_verified
    assert verification.verifier_kind == "provider_claim_current_read"
    assert verification.evidence_digest == digest
    assert verification.verified_at_utc == NOW
    assert verification.verified is False
    assert verification.recovery_disposition is not None
    assert not verification.recovery_disposition.all_required_dispositions_complete
    assert statements
    assert all(
        statement.lstrip().upper().startswith("SELECT")
        for statement in statements
    )


def test_current_old_owner_fails_closed(session_factory):
    _seed_claim(
        session_factory,
        claim_id=UUID("80000000-0000-4000-8000-000000000003"),
        fingerprint_byte=b"c",
        release_target=False,
    )
    prior, transition, evidence = _transition()
    with session_factory.begin() as session:
        with pytest.raises(DeletionControlEvidenceError) as captured:
            ControlDatabaseDeletionEvidenceAdapter().inspect_current(
                session,
                receipt_kind="claim_release",
                evidence=evidence,
                evidence_digest=deletion_evidence_digest(evidence),
                prior_state=prior,
                transition=transition,
                database_now_utc=NOW,
            )
    assert captured.value.code == "DELETION_SF_CLAIM_OLD_OWNER_REMAINS"


def test_claim_head_or_owner_drift_fails_closed(session_factory):
    claim_id = UUID("80000000-0000-4000-8000-000000000004")
    _seed_claim(
        session_factory,
        claim_id=claim_id,
        fingerprint_byte=b"d",
        release_target=True,
    )
    with session_factory.begin() as session:
        claim = session.get(ProviderAccountClaim, str(claim_id))
        assert claim is not None
        claim.event_head_hash = b"x" * 32

    prior, transition, evidence = _transition()
    with session_factory.begin() as session:
        with pytest.raises(DeletionControlEvidenceError) as captured:
            ControlDatabaseDeletionEvidenceAdapter().inspect_current(
                session,
                receipt_kind="claim_release",
                evidence=evidence,
                evidence_digest=deletion_evidence_digest(evidence),
                prior_state=prior,
                transition=transition,
                database_now_utc=NOW,
            )
    assert captured.value.code == "DELETION_SF_CLAIM_OWNER_DRIFT"


def test_orphaned_claim_event_history_fails_closed(session_factory):
    claim_id = UUID("80000000-0000-4000-8000-000000000005")
    _seed_claim(
        session_factory,
        claim_id=claim_id,
        fingerprint_byte=b"e",
        release_target=True,
    )
    engine = session_factory.kw["bind"]
    with engine.begin() as connection:
        connection.execute(
            sa.delete(ProviderAccountClaimEvent).where(
                ProviderAccountClaimEvent.provider_account_claim_id
                == str(claim_id),
                ProviderAccountClaimEvent.event_sequence == 1,
            )
        )

    prior, transition, evidence = _transition()
    with session_factory.begin() as session:
        with pytest.raises(DeletionControlEvidenceError) as captured:
            ControlDatabaseDeletionEvidenceAdapter().inspect_current(
                session,
                receipt_kind="claim_release",
                evidence=evidence,
                evidence_digest=deletion_evidence_digest(evidence),
                prior_state=prior,
                transition=transition,
                database_now_utc=NOW,
            )
    assert captured.value.code == "DELETION_SF_CLAIM_CHAIN_INVALID"


def test_release_from_another_deletion_action_fails_closed(session_factory):
    _seed_claim(
        session_factory,
        claim_id=UUID("80000000-0000-4000-8000-000000000006"),
        fingerprint_byte=b"f",
        release_target=True,
        release_action_id=WRONG_RELEASE_ACTION_ID,
    )
    prior, transition, evidence = _transition()
    with session_factory.begin() as session:
        with pytest.raises(DeletionControlEvidenceError) as captured:
            ControlDatabaseDeletionEvidenceAdapter().inspect_current(
                session,
                receipt_kind="claim_release",
                evidence=evidence,
                evidence_digest=deletion_evidence_digest(evidence),
                prior_state=prior,
                transition=transition,
                database_now_utc=NOW,
            )
    assert captured.value.code == "DELETION_SF_CLAIM_RELEASE_PROVENANCE_INVALID"


def test_current_hold_disposition_drift_fails_before_claim_acceptance(
    session_factory,
):
    with session_factory.begin() as session:
        hold = session.get(TenantRecoveryHold, str(HOLD_ID))
        assert hold is not None
        hold.tombstone_record_hash = b"z" * 32

    prior, transition, evidence = _transition()
    with session_factory.begin() as session:
        with pytest.raises(DeletionControlEvidenceError) as captured:
            ControlDatabaseDeletionEvidenceAdapter().inspect_current(
                session,
                receipt_kind="claim_release",
                evidence=evidence,
                evidence_digest=deletion_evidence_digest(evidence),
                prior_state=prior,
                transition=transition,
                database_now_utc=NOW,
            )
    assert captured.value.code == "DELETION_RECOVERY_DISPOSITION_MISMATCH"


def test_adapter_requires_explicit_clean_caller_transaction(session_factory):
    prior, transition, evidence = _transition()
    adapter = ControlDatabaseDeletionEvidenceAdapter()
    session = session_factory()
    try:
        with pytest.raises(DeletionControlEvidenceError) as captured:
            adapter.inspect_current(
                session,
                receipt_kind="claim_release",
                evidence=evidence,
                evidence_digest=deletion_evidence_digest(evidence),
                prior_state=prior,
                transition=transition,
                database_now_utc=NOW,
            )
    finally:
        session.close()
    assert captured.value.code == "DELETION_CONTROL_EVIDENCE_TRANSACTION_REQUIRED"


def _seed_recovery(factory: sessionmaker) -> None:
    with factory.begin() as session:
        session.add_all(
            [
                DisasterRecoveryRun(
                    id=str(RUN_ID),
                    kind="host_restore",
                    source_manifest_digest=b"m" * 32,
                    source_snapshot_at=NOW - timedelta(days=1),
                    applied_tombstone_head_digest=HEAD_HASH,
                    policy_version=1,
                    status="completed",
                    expected_survivor_count=1,
                    actual_survivor_count=1,
                    sealed_coverage_digest=b"s" * 32,
                    final_coverage_digest=b"f" * 32,
                    accepted_smoke_evidence_uuid=str(
                        UUID("90000000-0000-4000-8000-000000000001")
                    ),
                    host_installation_fingerprint="h" * 64,
                    deployment_marker_fingerprint="d" * 64,
                    row_version=1,
                    started_at=NOW - timedelta(hours=2),
                    reviewing_at=NOW - timedelta(hours=1),
                    completed_at=NOW - timedelta(minutes=30),
                ),
                TenantRecoveryHold(
                    id=str(HOLD_ID),
                    recovery_run_id=str(RUN_ID),
                    tenant_id=str(TENANT_ID),
                    database_uuid=str(DATABASE_ID),
                    state="tombstoned",
                    terminal_reason_code="superseded_by_deletion",
                    hold_revision=2,
                    snapshot_underlying_status="active",
                    snapshot_access_version=1,
                    expected_dml_login_state_version=1,
                    dml_convergence_status="locked",
                    deletion_request_uuid=str(REQUEST_ID),
                    tombstone_ledger_sequence=1,
                    tombstone_record_hash=RECORD_HASH,
                    held_at=NOW - timedelta(hours=2),
                    tombstoned_at=NOW - timedelta(seconds=30),
                    row_version=2,
                ),
            ]
        )


def _seed_claim(
    factory: sessionmaker,
    *,
    claim_id: UUID,
    fingerprint_byte: bytes,
    release_target: bool,
    reassign_to_new_owner: bool = False,
    release_action_id: UUID = COMMIT_ACTION_ID,
) -> None:
    fingerprint = ProviderAccountFingerprint(
        provider="sf",
        fingerprint_version=1,
        root_key_version=1,
        digest=fingerprint_byte * 32,
    )
    owner = _owner(TENANT_ID, seed=claim_id.int & 0xFFFF)
    reserve_action = UUID(int=(claim_id.int + 1) % (1 << 128))
    reserve_digest = hashlib.sha256(f"reserve:{claim_id}".encode("ascii")).digest()
    with factory.begin() as session:
        reserved = _claim_service(session).reserve_claim(
            fingerprint=fingerprint,
            owner=owner,
            proof=_admin_proof(
                tenant_id=TENANT_ID,
                action_id=reserve_action,
                request_digest=reserve_digest,
            ),
            expected_generation=1,
            expected_row_version=1,
            action_uuid=reserve_action,
            request_digest=reserve_digest,
            reservation_expires_at=CLAIM_TIME + timedelta(hours=2),
            claim_uuid=claim_id,
        )
    with factory.begin() as session:
        active = _claim_service(session).activate_claim(
            claim_uuid=claim_id,
            owner=owner,
            proof=_admin_proof(
                tenant_id=TENANT_ID,
                action_id=reserve_action,
                request_digest=reserve_digest,
            ),
            expected_generation=reserved.generation,
            expected_row_version=reserved.row_version,
            action_uuid=reserve_action,
            request_digest=reserve_digest,
            binding_revision=1,
        )
    if not release_target:
        return

    release_digest = hashlib.sha256(f"release:{claim_id}".encode("ascii")).digest()
    with factory.begin() as session:
        released = _claim_service(session).release_claim_by_deletion(
            claim_uuid=claim_id,
            proof=SfDeletionClaimProof(
                tenant_uuid=TENANT_ID,
                deletion_request_uuid=REQUEST_ID,
                action_uuid=release_action_id,
                execution_generation=4,
                fencing_token=11,
                tombstone_sequence=1,
                tombstone_record_hash=RECORD_HASH,
                offsite_acknowledged=True,
                irreversible_deletion=True,
            ),
            expected_generation=active.generation,
            expected_row_version=active.row_version,
            action_uuid=release_action_id,
            request_digest=release_digest,
        )
    if not reassign_to_new_owner:
        return

    new_owner = _owner(NEW_TENANT_ID, seed=(claim_id.int & 0xFFFF) + 100)
    rebound_action = UUID(int=(claim_id.int + 3) % (1 << 128))
    rebound_digest = hashlib.sha256(f"rebound:{claim_id}".encode("ascii")).digest()
    with factory.begin() as session:
        rebound = _claim_service(session).reserve_claim(
            fingerprint=fingerprint,
            owner=new_owner,
            proof=_admin_proof(
                tenant_id=NEW_TENANT_ID,
                action_id=rebound_action,
                request_digest=rebound_digest,
            ),
            expected_generation=released.generation,
            expected_row_version=released.row_version,
            action_uuid=rebound_action,
            request_digest=rebound_digest,
            reservation_expires_at=CLAIM_TIME + timedelta(hours=2),
        )
    with factory.begin() as session:
        _claim_service(session).activate_claim(
            claim_uuid=claim_id,
            owner=new_owner,
            proof=_admin_proof(
                tenant_id=NEW_TENANT_ID,
                action_id=rebound_action,
                request_digest=rebound_digest,
            ),
            expected_generation=rebound.generation,
            expected_row_version=rebound.row_version,
            action_uuid=rebound_action,
            request_digest=rebound_digest,
            binding_revision=1,
        )


def _claim_service(session: Session) -> SfClaimPersistenceService:
    return SfClaimPersistenceService(session, database_clock=lambda _: CLAIM_TIME)


def _owner(tenant_id: UUID, *, seed: int) -> SfClaimOwner:
    return SfClaimOwner(
        tenant_uuid=tenant_id,
        provider_account_uuid=UUID(int=0xA0000000000040008000000000000000 + seed),
        warehouse_uuid=UUID(int=0xB0000000000040008000000000000000 + seed),
    )


def _admin_proof(
    *,
    tenant_id: UUID,
    action_id: UUID,
    request_digest: bytes,
) -> SfAdminClaimProof:
    offset = action_id.int & 0xFFFF
    return SfAdminClaimProof(
        tenant_uuid=tenant_id,
        actor_user_uuid=UUID(int=0xC0000000000040008000000000000000 + offset),
        actor_session_uuid=UUID(int=0xD0000000000040008000000000000000 + offset),
        role=TenantRole.ADMIN,
        effective_gate=EffectiveTenantGate.ACTIVE,
        tenant_access_version=2,
        otp_challenge_uuid=UUID(int=0xE0000000000040008000000000000000 + offset),
        otp_purpose="sf_account_bind",
        otp_action_uuid=action_id,
        otp_request_digest=request_digest,
        otp_consumed=True,
    )


def _transition():
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
        recorded_at_utc=NOW - timedelta(minutes=2),
    )
    action = DeletionAction(
        action_id=COMMIT_ACTION_ID,
        kind=DeletionActionKind.COMMIT,
        execution_generation=4,
        executor_fencing_token=11,
        idempotency_key="commit-delete",
        request_digest=COMMIT_DIGEST,
        outcome=DeletionActionOutcome.RUNNING,
    )
    request = DeletionRequest(
        request_id=REQUEST_ID,
        requested_by_user_id=REQUESTOR_ID,
        status=DeletionRequestStatus.RELEASING_CLAIMS,
        revision=8,
        execution_generation=4,
        executor_fencing_token=11,
        current_action=action,
        requested_at_utc=NOW - timedelta(days=31),
        reviewed_at_utc=NOW - timedelta(days=30),
        execute_not_before_utc=(NOW - timedelta(days=30))
        + DELETION_COOLING_PERIOD,
        tombstone=tombstone,
        offsite_ack=OffsiteTombstoneAck(
            sequence=1,
            head_hash=HEAD_HASH,
            artifact_checksum=b"a" * 32,
            acknowledged_at_utc=NOW - timedelta(minutes=1),
            authenticated=True,
            durably_persisted=True,
            checksum_verified=True,
            chain_verified=True,
        ),
    )
    prior = DeletionState(
        tenant_id=TENANT_ID,
        database_id=DATABASE_ID,
        tenant_status=TenantStatus.DELETION_COMMITTING,
        tenant_access_version=2,
        desired_dml_login_state=DmlLoginState.LOCKED,
        published_dml_generation=1,
        latest_dml_generation=1,
        candidate_dml_generation=None,
        request=request,
        recovery_dispositions_required=True,
    )
    evidence = DeletionClaimReleaseEvidence(
        action_id=COMMIT_ACTION_ID,
        execution_generation=4,
        executor_fencing_token=11,
        tenant_access_version=2,
        lease_fence_verified=True,
        tombstone_sequence=1,
        tombstone_head_hash=HEAD_HASH,
        reserved_binding_operations_fenced=True,
        bidirectional_bindings_verified=True,
        provider_operations_isolated=True,
        claims_released_or_valid_new_owner=True,
        valid_new_owner_claims_untouched=True,
        claim_release_events_appended=True,
        no_orphan_claims=True,
        recovery_dispositions_complete=True,
    )
    transition = begin_destructive_cleanup(
        prior,
        evidence=evidence,
        expected_request_revision=8,
        expected_access_version=2,
        expected_execution_generation=4,
        expected_executor_fencing_token=11,
        lease_fence_verified=True,
    )
    return prior, transition, evidence
