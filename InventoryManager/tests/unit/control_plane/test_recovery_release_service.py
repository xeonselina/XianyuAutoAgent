from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa

from inventory_control import ControlBase, ControlDatabase
from inventory_control.models.deletion import TenantDeletionRequest
from inventory_control.models.foundation import Tenant, TenantDatabase
from inventory_control.models.platform_identity import (
    PlatformAdmin,
    PlatformAdminSession,
    PlatformAdminTotpCredential,
)
from inventory_control.models.recovery import (
    DisasterRecoveryReleaseAction,
    DisasterRecoveryRun,
    TenantRecoveryHold,
)
from inventory_control.recovery import (
    DmlRoutePublication,
    RecoveryDecision,
    RecoveryReleaseAdapterError,
    RecoveryReleaseAuthenticationError,
    RecoveryReleaseConflictError,
    RecoveryReleaseGateError,
    RecoveryReleaseRequest,
    RecoveryReleaseService,
    RecoveryReleaseTransactionError,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
MFA_AT = NOW - timedelta(minutes=2)
RUN_ID = UUID("10000000-0000-4000-8000-000000000058")
OTHER_RUN_ID = UUID("10000000-0000-4000-8000-000000000059")
TENANT_ID = UUID("20000000-0000-4000-8000-000000000058")
DATABASE_ID = UUID("30000000-0000-4000-8000-000000000058")
HOLD_ID = UUID("40000000-0000-4000-8000-000000000058")
ADMIN_ID = UUID("50000000-0000-4000-8000-000000000058")
TOTP_ID = UUID("60000000-0000-4000-8000-000000000058")
SESSION_ID = UUID("70000000-0000-4000-8000-000000000058")
DELETION_ID = UUID("a0000000-0000-4000-8000-000000000058")
DELETION_ACTION_ID = UUID("a1000000-0000-4000-8000-000000000058")
DELETION_USER_ID = UUID("a2000000-0000-4000-8000-000000000058")
DELETION_CHALLENGE_ID = UUID("a3000000-0000-4000-8000-000000000058")


class RecordingRouteAdapter:
    def __init__(self, *, fail: bool = False, invalid_receipt: bool = False):
        self.fail = fail
        self.invalid_receipt = invalid_receipt
        self.commands = []

    def verify_and_publish(self, command):
        self.commands.append(command)
        if self.fail:
            raise RuntimeError("provider detail must not escape")
        return DmlRoutePublication(
            recovery_run_uuid=command.recovery_run_uuid,
            tenant_uuid=command.tenant_uuid,
            hold_uuid=command.hold_uuid,
            database_uuid=command.database_uuid,
            candidate_generation=command.candidate_generation,
            published_dml_username="tenant_58_g23",
            published_dml_credential_generation=command.candidate_generation,
            published_dml_root_key_version=command.current_dml_root_key_version,
            published_dml_derivation_version=(
                command.current_dml_derivation_version
            ),
            previous_dml_login_state_version=(
                command.expected_dml_login_state_version
            ),
            published_dml_login_state_version=(
                command.expected_dml_login_state_version + 1
            ),
            previous_route_version=command.expected_published_route_version,
            published_route_version=command.expected_published_route_version + 1,
            request_digest=command.request_digest,
            database_identity_verified=True,
            least_privilege_verified=True,
            cross_schema_denial_verified=True,
            other_generations_locked=True,
            candidate_published=not self.invalid_receipt,
        )


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


def _run(*, run_id=RUN_ID, status="completed", row_version=5):
    reviewing_at = NOW if status in {"reviewing", "completed"} else None
    completed_at = NOW if status == "completed" else None
    superseded_at = NOW if status == "superseded" else None
    return DisasterRecoveryRun(
        id=str(run_id),
        kind="host_restore",
        policy_version=1,
        status=status,
        expected_survivor_count=1,
        actual_survivor_count=1,
        sealed_coverage_digest=b"s" * 32,
        final_coverage_digest=b"f" * 32,
        accepted_smoke_evidence_uuid=(
            "80000000-0000-4000-8000-000000000058"
            if status == "completed"
            else None
        ),
        host_installation_fingerprint="a" * 64,
        deployment_marker_fingerprint="b" * 64,
        row_version=row_version,
        started_at=NOW - timedelta(hours=1),
        reviewing_at=reviewing_at,
        completed_at=completed_at,
        superseded_at=superseded_at,
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW,
    )


def _seed(
    database,
    *,
    tenant_status="active",
    hold_state="held",
    dml_convergence_status="locked",
    mfa_at=MFA_AT,
):
    with database.transaction() as session:
        session.add(_run())
        session.add(
            Tenant(
                id=str(TENANT_ID),
                name="Tenant",
                slug="tenant",
                status=tenant_status,
                access_version=7,
                row_version=3,
                created_at=NOW - timedelta(days=1),
                updated_at=NOW,
            )
        )
        session.add(
            TenantDatabase(
                tenant_id=str(TENANT_ID),
                database_uuid=str(DATABASE_ID),
                database_instance_key="local",
                database_name="inventory_tenant_58",
                status="ready",
                schema_version="head",
                activated_by_registration_commit_uuid=(
                    "90000000-0000-4000-8000-000000000058"
                ),
                activation_route_version=1,
                activation_credential_generation=1,
                dml_username="tenant_58_g22",
                dml_credential_generation=22,
                dml_root_key_version=1,
                dml_derivation_version=1,
                route_version=11,
                dml_desired_login_state="locked",
                dml_observed_login_state="locked",
                dml_login_state_version=17,
                dml_desired_state_recovery_run_id=str(RUN_ID),
                platform_read_username="platform_read_58_g3",
                platform_read_credential_generation=3,
                platform_read_root_key_version=1,
                platform_read_derivation_version=1,
                platform_read_route_version=5,
                row_version=9,
                created_at=NOW - timedelta(days=1),
                updated_at=NOW,
            )
        )
        session.add(
            TenantRecoveryHold(
                id=str(HOLD_ID),
                recovery_run_id=str(RUN_ID),
                tenant_id=str(TENANT_ID),
                database_uuid=str(DATABASE_ID),
                state=hold_state,
                hold_revision=3,
                snapshot_underlying_status=tenant_status,
                snapshot_access_version=6,
                expected_dml_login_state_version=17,
                dml_convergence_status=dml_convergence_status,
                held_at=NOW - timedelta(minutes=30),
                released_at=NOW if hold_state == "released" else None,
                row_version=4,
                created_at=NOW - timedelta(minutes=30),
                updated_at=NOW,
            )
        )
        session.add(
            PlatformAdmin(
                id=str(ADMIN_ID),
                username_canonical="admin58",
                status="active",
                password_hash_encoded="$argon2id$test",
                password_hash_algorithm="argon2id",
                password_hash_version=1,
                auth_version=4,
                setup_version=3,
                totp_generation=2,
                recovery_code_generation=1,
                row_version=1,
                created_at=NOW - timedelta(days=2),
                updated_at=NOW,
            )
        )
        session.add(
            PlatformAdminTotpCredential(
                id=str(TOTP_ID),
                platform_admin_id=str(ADMIN_ID),
                generation=2,
                secret_revision=1,
                status="confirmed",
                seed_nonce=b"n" * 12,
                seed_ciphertext=b"c" * 32,
                root_key_version=1,
                crypto_version=1,
                aad_version=1,
                totp_algorithm="SHA1",
                totp_digits=6,
                totp_period_seconds=30,
                last_accepted_time_step=123,
                row_version=1,
                created_at=NOW - timedelta(days=1),
                confirmed_at=NOW - timedelta(days=1),
            )
        )
        session.flush()
        session.add(
            PlatformAdminSession(
                id=str(SESSION_ID),
                platform_admin_id=str(ADMIN_ID),
                token_digest_sha256=b"t" * 32,
                csrf_digest_sha256=b"x" * 32,
                auth_version_at_issue=4,
                setup_version_at_issue=3,
                mfa_method="totp",
                mfa_verified_at=mfa_at,
                totp_credential_id=str(TOTP_ID),
                totp_time_step=123,
                recovery_code_id=None,
                policy_version=1,
                csrf_generation=1,
                idle_timeout_seconds=1800,
                created_at=mfa_at,
                last_seen_at=mfa_at,
                idle_expires_at=NOW + timedelta(minutes=20),
                absolute_expires_at=NOW + timedelta(hours=2),
            )
        )


def _request(**changes):
    request = RecoveryReleaseRequest(
        recovery_run_uuid=RUN_ID,
        expected_recovery_run_row_version=5,
        tenant_uuid=TENANT_ID,
        hold_uuid=HOLD_ID,
        decision=RecoveryDecision.RELEASE,
        expected_hold_revision=3,
        expected_tenant_row_version=3,
        expected_access_version=7,
        expected_dml_login_state_version=17,
        expected_published_route_version=11,
        candidate_generation=23,
        platform_admin_uuid=ADMIN_ID,
        platform_session_uuid=SESSION_ID,
        recent_mfa_method="totp",
        recent_mfa_at=MFA_AT,
        reason_code="restore_review_passed",
        evidence_type="ops_ticket",
        evidence_reference="DR/2026-08-22/58",
        idempotency_key="release-tenant-58",
    )
    return replace(request, **changes)


def _seed_pending_deletion(database):
    with database.transaction() as session:
        session.add(
            TenantDeletionRequest(
                id=str(DELETION_ID),
                tenant_id=str(TENANT_ID),
                database_uuid=str(DATABASE_ID),
                requested_by_user_id=str(DELETION_USER_ID),
                request_challenge_id=str(DELETION_CHALLENGE_ID),
                status="pending_review",
                request_revision=1,
                execution_generation=1,
                executor_fencing_token=1,
                current_action_id=str(DELETION_ACTION_ID),
                committed_tenant_access_version=7,
                desired_dml_login_state="active",
                published_dml_generation=22,
                latest_dml_generation=22,
                candidate_dml_generation=None,
                recovery_dispositions_required=False,
                requested_at=NOW - timedelta(minutes=5),
                row_version=1,
                created_at=NOW - timedelta(minutes=5),
                updated_at=NOW - timedelta(minutes=5),
            )
        )


def _service(adapter):
    return RecoveryReleaseService(
        dml_route_adapter=adapter,
        recent_mfa_window=timedelta(minutes=10),
        database_clock=lambda _session: NOW,
    )


def _snapshot(database):
    with database.new_session() as session:
        tenant = session.get(Tenant, str(TENANT_ID))
        hold = session.get(TenantRecoveryHold, str(HOLD_ID))
        route = session.get(TenantDatabase, str(TENANT_ID))
        platform_session = session.get(PlatformAdminSession, str(SESSION_ID))
        actions = list(session.scalars(sa.select(DisasterRecoveryReleaseAction)))
        return {
            "tenant_status": tenant.status,
            "tenant_row_version": tenant.row_version,
            "access_version": tenant.access_version,
            "hold_state": hold.state,
            "hold_revision": hold.hold_revision,
            "hold_row_version": hold.row_version,
            "dml_version": hold.expected_dml_login_state_version,
            "dml_convergence": hold.dml_convergence_status,
            "released_by": hold.released_by_action_uuid,
            "route_version": route.route_version,
            "route_row_version": route.row_version,
            "route_dml_username": route.dml_username,
            "route_dml_generation": route.dml_credential_generation,
            "route_dml_desired": route.dml_desired_login_state,
            "route_dml_observed": route.dml_observed_login_state,
            "route_dml_version": route.dml_login_state_version,
            "session_revoked_at": platform_session.revoked_at,
            "actions": actions,
        }


def test_release_publishes_exact_candidate_then_atomically_releases_hold(
    control_database,
):
    _seed(control_database)
    adapter = RecordingRouteAdapter()
    service = _service(adapter)

    with control_database.transaction() as session:
        result = service.decide(session, _request())

    assert result.replayed is False
    assert result.decision is RecoveryDecision.RELEASE
    assert result.resulting_hold_revision == 4
    assert result.resulting_access_version == 8
    assert result.resulting_dml_login_state_version == 18
    assert result.resulting_published_route_version == 12
    assert len(result.request_digest) == 32
    assert len(adapter.commands) == 1
    assert adapter.commands[0].candidate_generation == 23

    state = _snapshot(control_database)
    assert state["tenant_row_version"] == 4
    assert state["access_version"] == 8
    assert state["hold_state"] == "released"
    assert state["hold_revision"] == 4
    assert state["dml_version"] == 18
    assert state["dml_convergence"] == "active"
    assert state["released_by"] == result.action_uuid
    assert state["route_version"] == 12
    assert state["route_row_version"] == 10
    assert state["route_dml_username"] == "tenant_58_g23"
    assert state["route_dml_generation"] == 23
    assert state["route_dml_desired"] == "active"
    assert state["route_dml_observed"] == "active"
    assert state["route_dml_version"] == 18
    assert state["session_revoked_at"] is not None
    assert len(state["actions"]) == 1
    assert state["actions"][0].state == "succeeded"
    assert state["actions"][0].safe_outcome_code == "RECOVERY_TENANT_RELEASED"


def test_same_key_same_request_replays_original_without_republishing(
    control_database,
):
    _seed(control_database)
    adapter = RecordingRouteAdapter()
    service = _service(adapter)
    request = _request()

    with control_database.transaction() as session:
        first = service.decide(session, request)
    with control_database.transaction() as session:
        replay = service.decide(session, request)

    assert replay.replayed is True
    assert replay.action_uuid == first.action_uuid
    assert replay.request_digest == first.request_digest
    assert len(adapter.commands) == 1
    assert len(_snapshot(control_database)["actions"]) == 1


def test_release_removes_only_the_overlay_and_preserves_expired_status(
    control_database,
):
    _seed(control_database, tenant_status="expired")
    adapter = RecordingRouteAdapter()

    with control_database.transaction() as session:
        result = _service(adapter).decide(session, _request())

    state = _snapshot(control_database)
    assert result.safe_outcome_code == "RECOVERY_TENANT_RELEASED"
    assert state["tenant_status"] == "expired"
    assert state["hold_state"] == "released"
    assert state["route_dml_desired"] == "active"
    assert len(adapter.commands) == 1


def test_same_key_different_request_is_rejected_without_adapter_call(
    control_database,
):
    _seed(control_database)
    adapter = RecordingRouteAdapter()
    service = _service(adapter)
    with control_database.transaction() as session:
        service.decide(session, _request())

    with control_database.transaction() as session:
        with pytest.raises(RecoveryReleaseConflictError) as caught:
            service.decide(
                session,
                _request(reason_code="different_review_reason"),
            )

    assert caught.value.code == "RECOVERY_IDEMPOTENCY_CONFLICT"
    assert len(adapter.commands) == 1
    assert len(_snapshot(control_database)["actions"]) == 1


def test_keep_closed_finishes_in_one_transaction_without_dml_publication(
    control_database,
):
    _seed(control_database)
    adapter = RecordingRouteAdapter()
    service = _service(adapter)
    request = _request(
        decision=RecoveryDecision.KEEP_CLOSED,
        candidate_generation=None,
        idempotency_key="keep-closed-tenant-58",
        reason_code="evidence_incomplete",
    )

    with control_database.transaction() as session:
        result = service.decide(session, request)

    assert result.decision is RecoveryDecision.KEEP_CLOSED
    assert result.safe_outcome_code == "RECOVERY_TENANT_KEPT_CLOSED"
    assert result.resulting_dml_login_state_version == 17
    assert result.resulting_published_route_version == 11
    assert adapter.commands == []
    state = _snapshot(control_database)
    assert state["hold_state"] == "kept_closed"
    assert state["hold_revision"] == 4
    assert state["access_version"] == 8
    assert state["dml_convergence"] == "locked"
    assert state["route_version"] == 11
    assert state["session_revoked_at"] is not None
    assert state["actions"][0].candidate_generation is None


def test_keep_closed_refuses_to_claim_success_when_dml_is_not_proven_locked(
    control_database,
):
    _seed(control_database)
    with control_database.transaction() as session:
        route = session.get(TenantDatabase, str(TENANT_ID))
        route.dml_desired_login_state = "active"
        route.dml_observed_login_state = "active"
    adapter = RecordingRouteAdapter()

    with control_database.transaction() as session:
        with pytest.raises(RecoveryReleaseGateError) as caught:
            _service(adapter).decide(
                session,
                _request(
                    decision=RecoveryDecision.KEEP_CLOSED,
                    candidate_generation=None,
                    idempotency_key="keep-closed-not-locked",
                ),
            )

    assert caught.value.code == "RECOVERY_DML_NOT_LOCKED"
    assert adapter.commands == []
    state = _snapshot(control_database)
    assert state["hold_state"] == "held"
    assert state["actions"] == []


def test_caller_rollback_removes_the_complete_keep_closed_decision(control_database):
    _seed(control_database)
    adapter = RecordingRouteAdapter()
    service = _service(adapter)
    session = control_database.new_session()
    transaction = session.begin()
    try:
        service.decide(
            session,
            _request(
                decision=RecoveryDecision.KEEP_CLOSED,
                candidate_generation=None,
            ),
        )
        transaction.rollback()
    finally:
        session.close()

    state = _snapshot(control_database)
    assert state["hold_state"] == "held"
    assert state["hold_revision"] == 3
    assert state["access_version"] == 7
    assert state["session_revoked_at"] is None
    assert state["actions"] == []


def test_caller_rollback_after_publication_keeps_control_route_fail_closed(
    control_database,
):
    _seed(control_database)
    adapter = RecordingRouteAdapter()
    service = _service(adapter)
    session = control_database.new_session()
    transaction = session.begin()
    try:
        service.decide(session, _request())
        transaction.rollback()
    finally:
        session.close()

    assert len(adapter.commands) == 1
    state = _snapshot(control_database)
    assert state["hold_state"] == "held"
    assert state["access_version"] == 7
    assert state["route_version"] == 11
    assert state["route_dml_username"] == "tenant_58_g22"
    assert state["route_dml_generation"] == 22
    assert state["route_dml_desired"] == "locked"
    assert state["route_dml_observed"] == "locked"
    assert state["session_revoked_at"] is None
    assert state["actions"] == []


@pytest.mark.parametrize(
    ("changed_field", "changed_value", "expected_code"),
    [
        (
            "expected_recovery_run_row_version",
            6,
            "RECOVERY_RUN_REVISION_CHANGED",
        ),
        ("expected_hold_revision", 4, "RECOVERY_HOLD_REVISION_CHANGED"),
        ("expected_tenant_row_version", 4, "RECOVERY_TENANT_REVISION_CHANGED"),
        ("expected_access_version", 8, "RECOVERY_ACCESS_VERSION_CHANGED"),
        (
            "expected_dml_login_state_version",
            18,
            "RECOVERY_DML_VERSION_CHANGED",
        ),
        (
            "expected_published_route_version",
            12,
            "RECOVERY_ROUTE_VERSION_CHANGED",
        ),
    ],
)
def test_expected_revision_competition_fails_without_side_effects(
    control_database,
    changed_field,
    changed_value,
    expected_code,
):
    _seed(control_database)
    adapter = RecordingRouteAdapter()
    service = _service(adapter)

    with control_database.transaction() as session:
        with pytest.raises(RecoveryReleaseConflictError) as caught:
            service.decide(session, _request(**{changed_field: changed_value}))

    assert caught.value.code == expected_code
    assert adapter.commands == []
    state = _snapshot(control_database)
    assert state["hold_state"] == "held"
    assert state["hold_revision"] == 3
    assert state["access_version"] == 7
    assert state["session_revoked_at"] is None
    assert state["actions"] == []


def test_current_run_change_rejects_the_stale_action(control_database):
    _seed(control_database)
    with control_database.transaction() as session:
        old_run = session.get(DisasterRecoveryRun, str(RUN_ID))
        old_run.status = "superseded"
        old_run.superseded_at = NOW
        old_run.row_version += 1
        session.add(_run(run_id=OTHER_RUN_ID, row_version=1))

    adapter = RecordingRouteAdapter()
    with control_database.transaction() as session:
        with pytest.raises(RecoveryReleaseGateError) as caught:
            _service(adapter).decide(session, _request())

    assert caught.value.code == "RECOVERY_RUN_CHANGED"
    assert adapter.commands == []
    assert _snapshot(control_database)["actions"] == []


def test_hold_state_change_rejects_a_new_action(control_database):
    _seed(control_database, hold_state="released", dml_convergence_status="active")
    adapter = RecordingRouteAdapter()

    with control_database.transaction() as session:
        with pytest.raises(RecoveryReleaseGateError) as caught:
            _service(adapter).decide(session, _request())

    assert caught.value.code == "RECOVERY_HOLD_NOT_REVIEWABLE"
    assert adapter.commands == []
    state = _snapshot(control_database)
    assert state["hold_state"] == "released"
    assert state["actions"] == []


@pytest.mark.parametrize(
    "tenant_status",
    [
        "suspending",
        "suspended",
        "resuming",
        "deletion_cooling_off",
        "deletion_committing",
        "deleted",
    ],
)
def test_suspension_and_deletion_gates_cannot_be_overridden_by_release(
    control_database,
    tenant_status,
):
    _seed(control_database, tenant_status=tenant_status)
    adapter = RecordingRouteAdapter()

    with control_database.transaction() as session:
        with pytest.raises(RecoveryReleaseGateError) as caught:
            _service(adapter).decide(session, _request())

    assert caught.value.code == "RECOVERY_UNDERLYING_GATE_CLOSED"
    assert adapter.commands == []
    state = _snapshot(control_database)
    assert state["tenant_status"] == tenant_status
    assert state["hold_state"] == "held"
    assert state["dml_convergence"] == "locked"
    assert state["session_revoked_at"] is None
    assert state["actions"] == []


def test_pending_deletion_request_blocks_release_before_candidate_publication(
    control_database,
):
    _seed(control_database, tenant_status="active")
    _seed_pending_deletion(control_database)
    adapter = RecordingRouteAdapter()

    with control_database.transaction() as session:
        with pytest.raises(RecoveryReleaseGateError) as caught:
            _service(adapter).decide(session, _request())

    assert caught.value.code == "RECOVERY_DELETION_IN_PROGRESS"
    assert adapter.commands == []
    state = _snapshot(control_database)
    assert state["tenant_status"] == "active"
    assert state["hold_state"] == "held"
    assert state["route_dml_desired"] == "locked"
    assert state["session_revoked_at"] is None
    assert state["actions"] == []


@pytest.mark.parametrize("invalid_receipt", [False, True])
def test_adapter_failure_or_invalid_receipt_leaves_control_state_held(
    control_database,
    invalid_receipt,
):
    _seed(control_database)
    adapter = RecordingRouteAdapter(
        fail=not invalid_receipt,
        invalid_receipt=invalid_receipt,
    )

    with control_database.transaction() as session:
        with pytest.raises(RecoveryReleaseAdapterError) as caught:
            _service(adapter).decide(session, _request())

    assert caught.value.code in {
        "RECOVERY_DML_PUBLICATION_FAILED",
        "RECOVERY_DML_PUBLICATION_INVALID",
    }
    assert len(adapter.commands) == 1
    state = _snapshot(control_database)
    assert state["tenant_row_version"] == 3
    assert state["access_version"] == 7
    assert state["hold_state"] == "held"
    assert state["hold_revision"] == 3
    assert state["dml_version"] == 17
    assert state["route_version"] == 11
    assert state["session_revoked_at"] is None
    assert state["actions"] == []


def test_expired_platform_mfa_fails_before_adapter_and_persistence(control_database):
    old_mfa_at = NOW - timedelta(minutes=11)
    _seed(control_database, mfa_at=old_mfa_at)
    adapter = RecordingRouteAdapter()

    with control_database.transaction() as session:
        with pytest.raises(RecoveryReleaseAuthenticationError) as caught:
            _service(adapter).decide(
                session,
                _request(recent_mfa_at=old_mfa_at),
            )

    assert caught.value.code == "RECOVERY_RECENT_MFA_REQUIRED"
    assert adapter.commands == []
    assert _snapshot(control_database)["actions"] == []


def test_service_requires_an_explicit_clean_caller_transaction(control_database):
    _seed(control_database)
    service = _service(RecordingRouteAdapter())

    with control_database.new_session() as session:
        with pytest.raises(RecoveryReleaseTransactionError) as caught:
            service.decide(session, _request())
    assert caught.value.code == "CALLER_TRANSACTION_REQUIRED"

    session = control_database.new_session()
    transaction = session.begin()
    try:
        tenant = session.get(Tenant, str(TENANT_ID))
        tenant.name = "dirty caller mutation"
        with pytest.raises(RecoveryReleaseTransactionError) as caught:
            service.decide(session, _request())
        assert caught.value.code == "CLEAN_CALLER_UNIT_OF_WORK_REQUIRED"
        transaction.rollback()
    finally:
        session.close()


def test_invalid_request_fails_before_any_adapter_or_persistent_change(
    control_database,
):
    _seed(control_database)
    adapter = RecordingRouteAdapter()

    with control_database.transaction() as session:
        with pytest.raises(ValueError):
            _service(adapter).decide(
                session,
                _request(
                    decision=RecoveryDecision.KEEP_CLOSED,
                    candidate_generation=23,
                ),
            )

    assert adapter.commands == []
    state = _snapshot(control_database)
    assert state["hold_state"] == "held"
    assert state["actions"] == []
