from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from inventory_control import ControlBase, ControlDatabase
from inventory_control.domain.tenant_gate import EffectiveTenantGate
from inventory_control.models import (
    DisasterRecoveryRun,
    PlanRevision,
    Subscription,
    Tenant,
    TenantDeletionRequest,
    TenantMembership,
    TenantRecoveryHold,
    TenantSuspension,
    User,
)
from inventory_control.identity import (
    CN_MOBILE_METADATA_VERSION,
    PHONE_NORMALIZATION_VERSION,
    SessionAuthenticationError,
    SessionService,
)
from inventory_control.recovery import (
    RecoveryAuthorityError,
    RecoveryAuthorityService,
    RecoveryAuthorityTransactionError,
)
from tests.support.test_database import clear_guarded_mysql_test_rows


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
RUN_ID = UUID("10000000-0000-4000-8000-000000000001")
TENANT_ID = UUID("20000000-0000-4000-8000-000000000001")
DATABASE_ID = UUID("30000000-0000-4000-8000-000000000001")
PLAN_ID = UUID("40000000-0000-4000-8000-000000000001")
SUBSCRIPTION_ID = UUID("50000000-0000-4000-8000-000000000001")
COMMIT_ID = UUID("60000000-0000-4000-8000-000000000001")
ENTITLEMENTS = {
    "features": {"xianyu_sync": True},
    "limits": {"member_seats": 10},
}
ENTITLEMENTS_DIGEST = b"e" * 32


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


def _run(*, status="completed", run_id=RUN_ID):
    reviewing_time = NOW if status in {"reviewing", "completed"} else None
    completed_time = NOW if status == "completed" else None
    return DisasterRecoveryRun(
        id=str(run_id),
        kind="initial_baseline",
        policy_version=1,
        status=status,
        expected_survivor_count=1,
        actual_survivor_count=1 if status == "completed" else 0,
        sealed_coverage_digest=b"s" * 32,
        final_coverage_digest=b"f" * 32 if status == "completed" else None,
        host_installation_fingerprint="a" * 64,
        deployment_marker_fingerprint="b" * 64,
        row_version=1,
        started_at=NOW,
        reviewing_at=reviewing_time,
        completed_at=completed_time,
        created_at=NOW,
        updated_at=NOW,
    )


def _seed_tenant(
    database,
    *,
    run_status="completed",
    hold_state="released",
    tenant_status="active",
    expires_at=NOW + timedelta(days=1),
    include_run=True,
    include_hold=True,
    include_subscription=True,
):
    with database.transaction() as session:
        tenant = Tenant(
            id=str(TENANT_ID),
            status=tenant_status,
            access_version=7,
            row_version=3,
        )
        session.add(tenant)
        if include_run:
            session.add(_run(status=run_status))
        if include_subscription:
            session.add(
                PlanRevision(
                    id=str(PLAN_ID),
                    code="core",
                    revision=1,
                    name="Core",
                    entitlements_schema_version=1,
                    entitlements_json=ENTITLEMENTS,
                    entitlements_digest=ENTITLEMENTS_DIGEST,
                    active=True,
                )
            )
            session.add(
                Subscription(
                    id=str(SUBSCRIPTION_ID),
                    tenant_id=str(TENANT_ID),
                    plan_revision_uuid=str(PLAN_ID),
                    entitlements_schema_version=1,
                    entitlements_json=ENTITLEMENTS,
                    entitlements_digest=ENTITLEMENTS_DIGEST,
                    status=("active" if expires_at > NOW else "expired"),
                    expires_at=expires_at,
                    row_version=1,
                    provider="manual",
                )
            )
        if include_run and include_hold:
            session.add(
                TenantRecoveryHold(
                    recovery_run_id=str(RUN_ID),
                    tenant_id=str(TENANT_ID),
                    database_uuid=str(DATABASE_ID),
                    state=hold_state,
                    hold_revision=1,
                    snapshot_underlying_status=tenant_status,
                    snapshot_access_version=7,
                    expected_dml_login_state_version=1,
                    dml_convergence_status=(
                        "active" if hold_state == "released" else "locked"
                    ),
                    held_at=NOW,
                    released_at=NOW if hold_state == "released" else None,
                    row_version=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )


def _read_gate(database, *, presented_access_version=None):
    authority = RecoveryAuthorityService(database_clock=lambda _session: NOW)
    with database.transaction() as session:
        tenant = session.scalar(
            sa.select(Tenant)
            .where(Tenant.id == str(TENANT_ID))
            .with_for_update()
        )
        return authority.read_tenant_gate(
            session,
            tenant=tenant,
            presented_access_version=presented_access_version,
        )


def test_completed_current_run_and_released_hold_allow_active_gate(control_database):
    _seed_tenant(control_database)

    decision = _read_gate(control_database)

    assert decision.gate is EffectiveTenantGate.ACTIVE
    assert decision.error_code is None
    service = RecoveryAuthorityService(database_clock=lambda _session: NOW)
    with control_database.transaction() as session:
        authority = service.read_current_completed(session)
    assert authority.recovery_run_uuid == str(RUN_ID)
    assert authority.status == "completed"
    assert authority.host_installation_fingerprint == "a" * 64


@pytest.mark.parametrize(
    ("run_status", "include_run", "include_hold"),
    [
        ("completed", False, False),
        ("installing", True, True),
        ("reviewing", True, True),
        ("failed_closed", True, True),
        ("completed", True, False),
    ],
)
def test_missing_or_incomplete_recovery_authority_fails_to_hold_gate(
    control_database, run_status, include_run, include_hold
):
    _seed_tenant(
        control_database,
        run_status=run_status,
        include_run=include_run,
        include_hold=include_hold,
    )

    decision = _read_gate(control_database)

    assert decision.gate is EffectiveTenantGate.RECOVERY_HOLD
    assert decision.error_code == "TENANT_RECOVERY_IN_PROGRESS"


@pytest.mark.parametrize("hold_state", ["held", "reviewing", "kept_closed"])
def test_nonreleased_hold_denies_even_after_run_completed(
    control_database, hold_state
):
    _seed_tenant(control_database, hold_state=hold_state)

    assert _read_gate(control_database).gate is EffectiveTenantGate.RECOVERY_HOLD


@pytest.mark.parametrize(
    ("expires_at", "expected_gate"),
    [
        (NOW + timedelta(microseconds=1), EffectiveTenantGate.ACTIVE),
        (NOW, EffectiveTenantGate.EXPIRED),
        (NOW - timedelta(days=1), EffectiveTenantGate.EXPIRED),
    ],
)
def test_subscription_uses_database_time_at_exact_boundary(
    control_database, expires_at, expected_gate
):
    _seed_tenant(control_database, expires_at=expires_at)

    assert _read_gate(control_database).gate is expected_gate


@pytest.mark.parametrize(
    ("tenant_status", "expected_gate"),
    [
        ("suspending", EffectiveTenantGate.SUSPENDED),
        ("suspended", EffectiveTenantGate.SUSPENDED),
        ("resuming", EffectiveTenantGate.SUSPENDED),
        ("deletion_cooling_off", EffectiveTenantGate.DELETION_COOLING_OFF),
        ("deletion_committing", EffectiveTenantGate.DELETED),
        ("deleted", EffectiveTenantGate.DELETED),
    ],
)
def test_released_hold_exposes_but_never_overrides_higher_lifecycle_gate(
    control_database, tenant_status, expected_gate
):
    _seed_tenant(control_database, tenant_status=tenant_status)

    assert _read_gate(control_database).gate is expected_gate


def test_persisted_suspension_aggregate_overrides_drifted_active_projection(
    control_database,
):
    _seed_tenant(control_database)
    with control_database.transaction() as session:
        session.add(
            TenantSuspension(
                id="71000000-0000-4000-8000-000000000001",
                tenant_id=str(TENANT_ID),
                state="active",
                initial_reason_code="security_review",
                initial_safe_note=None,
                barrier_generation=1,
                committed_tenant_row_version=3,
                committed_access_version=7,
                requested_at=NOW,
                frozen_at=NOW,
                resolving_at=None,
                resolved_at=None,
                safe_failure_code=None,
                row_version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    decision = _read_gate(control_database)

    assert decision.gate is EffectiveTenantGate.SUSPENDED
    assert decision.error_code == "TENANT_SUSPENDED"


@pytest.mark.parametrize(
    ("deletion_status", "expected_gate"),
    [
        ("cooling_off", EffectiveTenantGate.DELETION_COOLING_OFF),
        ("committing", EffectiveTenantGate.DELETED),
    ],
)
def test_persisted_deletion_aggregate_overrides_projection_and_recovery(
    control_database,
    deletion_status,
    expected_gate,
):
    _seed_tenant(control_database, hold_state="held")
    with control_database.transaction() as session:
        session.add(
            TenantDeletionRequest(
                id="72000000-0000-4000-8000-000000000001",
                tenant_id=str(TENANT_ID),
                database_uuid=str(DATABASE_ID),
                requested_by_user_id="72000000-0000-4000-8000-000000000002",
                request_challenge_id="72000000-0000-4000-8000-000000000003",
                status=deletion_status,
                request_revision=2,
                execution_generation=1,
                executor_fencing_token=1,
                current_action_id="72000000-0000-4000-8000-000000000004",
                committed_tenant_access_version=7,
                desired_dml_login_state="locked",
                published_dml_generation=1,
                latest_dml_generation=1,
                candidate_dml_generation=None,
                recovery_dispositions_required=False,
                reviewed_by_platform_admin_id=(
                    "72000000-0000-4000-8000-000000000005"
                ),
                pre_freeze_tenant_status="active",
                requested_at=NOW,
                reviewed_at=NOW,
                execute_not_before=NOW + timedelta(days=30),
                row_version=2,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    decision = _read_gate(control_database)

    assert decision.gate is expected_gate


def test_missing_subscription_is_invalid_after_recovery_release(control_database):
    _seed_tenant(control_database, include_subscription=False)

    decision = _read_gate(control_database)

    assert decision.gate is EffectiveTenantGate.INVALID_STATE
    assert decision.error_code == "TENANT_STATE_INVALID"


def test_presented_access_version_is_checked_with_current_facts(control_database):
    _seed_tenant(control_database)

    assert (
        _read_gate(control_database, presented_access_version=6).gate
        is EffectiveTenantGate.STALE_ACCESS
    )


def test_create_released_baseline_hold_is_idempotent_and_anchors_commit(
    control_database,
):
    _seed_tenant(control_database, include_hold=False)
    service = RecoveryAuthorityService(database_clock=lambda _session: NOW)

    with control_database.transaction() as session:
        tenant = session.scalar(
            sa.select(Tenant)
            .where(Tenant.id == str(TENANT_ID))
            .with_for_update()
        )
        first = service.create_released_baseline_hold(
            session,
            tenant=tenant,
            database_uuid=DATABASE_ID,
            expected_dml_login_state_version=1,
            dml_convergence_status="active",
            registration_commit_uuid=COMMIT_ID,
        )
    with control_database.transaction() as session:
        tenant = session.scalar(
            sa.select(Tenant)
            .where(Tenant.id == str(TENANT_ID))
            .with_for_update()
        )
        retry = service.create_released_baseline_hold(
            session,
            tenant=tenant,
            database_uuid=DATABASE_ID,
            expected_dml_login_state_version=1,
            dml_convergence_status="active",
            registration_commit_uuid=COMMIT_ID,
        )

    assert first.idempotent is False
    assert retry.idempotent is True
    assert retry.hold_uuid == first.hold_uuid
    assert retry.hold_revision == 1
    with control_database.new_session() as session:
        hold = session.get(TenantRecoveryHold, first.hold_uuid)
        tenant = session.get(Tenant, str(TENANT_ID))
        assert hold.created_from_registration_commit_uuid == str(COMMIT_ID)
        assert hold.initial_hold_revision == 1
        assert tenant.access_version == 7


def test_baseline_hold_conflict_and_incomplete_run_fail_closed(control_database):
    _seed_tenant(control_database)
    service = RecoveryAuthorityService(database_clock=lambda _session: NOW)
    with control_database.transaction() as session:
        tenant = session.scalar(
            sa.select(Tenant)
            .where(Tenant.id == str(TENANT_ID))
            .with_for_update()
        )
        with pytest.raises(RecoveryAuthorityError) as caught:
            service.create_released_baseline_hold(
                session,
                tenant=tenant,
                database_uuid=UUID("30000000-0000-4000-8000-000000000002"),
                expected_dml_login_state_version=1,
                dml_convergence_status="active",
            )
    assert caught.value.code == "RECOVERY_HOLD_ANCHOR_CONFLICT"

    clear_guarded_mysql_test_rows(
        control_database.engine,
        ControlBase.metadata,
    )
    _seed_tenant(
        control_database,
        run_status="installing",
        include_hold=False,
    )
    with control_database.transaction() as session:
        tenant = session.scalar(
            sa.select(Tenant)
            .where(Tenant.id == str(TENANT_ID))
            .with_for_update()
        )
        with pytest.raises(RecoveryAuthorityError) as caught:
            service.create_released_baseline_hold(
                session,
                tenant=tenant,
                database_uuid=DATABASE_ID,
                expected_dml_login_state_version=1,
                dml_convergence_status="active",
            )
    assert caught.value.code == "RECOVERY_RUN_NOT_COMPLETED"


def test_database_enforces_only_one_current_recovery_run(control_database):
    with control_database.transaction() as session:
        session.add(_run())
    with pytest.raises(IntegrityError):
        with control_database.transaction() as session:
            session.add(
                _run(
                    status="installing",
                    run_id=UUID("10000000-0000-4000-8000-000000000002"),
                )
            )


def test_service_requires_a_caller_owned_transaction(control_database):
    service = RecoveryAuthorityService(database_clock=lambda _session: NOW)
    with control_database.new_session() as session:
        with pytest.raises(RecoveryAuthorityTransactionError) as caught:
            service.read_current_completed(session)
    assert caught.value.code == "CALLER_TRANSACTION_REQUIRED"


def test_session_service_consumes_the_persisted_recovery_authority(
    control_database,
):
    _seed_tenant(control_database)
    with control_database.transaction() as session:
        user = User(
            phone_e164="+8613800138000",
            phone_normalization_version=PHONE_NORMALIZATION_VERSION,
            phone_metadata_version=CN_MOBILE_METADATA_VERSION,
            phone_verified_at=NOW,
            status="active",
        )
        session.add(user)
        session.flush()
        session.add(
            TenantMembership(
                tenant_id=str(TENANT_ID),
                user_id=user.id,
                role_key="admin",
                status="active",
                source_type="migration",
            )
        )
        session.flush()
        user_id = user.id

    authority = RecoveryAuthorityService(database_clock=lambda _session: NOW)
    sessions = SessionService(gate_current_read=authority)
    with control_database.transaction() as session:
        issued = sessions.issue(
            session,
            user_id=user_id,
            idle_timeout=timedelta(minutes=30),
            absolute_timeout=timedelta(hours=8),
            now=NOW,
        )
    assert issued.auth.effective_gate is EffectiveTenantGate.ACTIVE

    with control_database.transaction() as session:
        session.scalar(
            sa.select(TenantRecoveryHold).where(
                TenantRecoveryHold.tenant_id == str(TENANT_ID)
            )
        ).state = "held"

    with control_database.new_session() as session:
        with pytest.raises(SessionAuthenticationError):
            sessions.resolve(
                session,
                issued.session_token,
                now=NOW + timedelta(minutes=1),
            )
