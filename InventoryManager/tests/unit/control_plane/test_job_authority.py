import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from inventory_control import (
    ControlBase,
    DisasterRecoveryRun,
    Tenant,
    TenantDatabase,
    TenantDeletionRequest,
    TenantRecoveryHold,
    TenantSuspension,
)
from inventory_control.jobs import (
    ControlLifecycleGateProbes,
    ControlTenantGateReader,
    DurableScheduleGate,
    DurableWorkerAuthority,
)
from inventory_control.models.jobs import BackgroundJob
from inventory_control.models.subscriptions import PlanRevision, Subscription
from inventory_control.recovery import RecoveryAuthorityService
from tests.support.test_database import (
    clear_guarded_mysql_test_rows,
    guarded_mysql_control_database,
)


NOW = datetime(2026, 8, 22, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def database_schema():
    with guarded_mysql_control_database(ControlBase.metadata) as database:
        yield database


@pytest.fixture
def database(database_schema):
    clear_guarded_mysql_test_rows(database_schema.engine, ControlBase.metadata)
    return database_schema


def seed(database, *, access_version=1, tenant_status="active", route_status="ready"):
    entitlements = {"features": {}, "limits": {"member_seats": 10}}
    digest = hashlib.sha256(b"entitlements").digest()
    with database.transaction() as session:
        plan = PlanRevision(
            code="core",
            revision=1,
            name="Core",
            entitlements_schema_version=1,
            entitlements_json=entitlements,
            entitlements_digest=digest,
        )
        tenant = Tenant(status=tenant_status, access_version=access_version)
        session.add_all((plan, tenant))
        session.flush()
        session.add(
            TenantDatabase(
                tenant_id=tenant.id,
                database_instance_key="primary",
                database_name=f"tenant_{tenant.id.replace('-', '')}",
                status=route_status,
                schema_version="test-head",
                activated_by_registration_commit_uuid=(
                    "10000000-0000-4000-8000-000000000099"
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
            )
        )
        subscription = Subscription(
            tenant_id=tenant.id,
            plan_revision_uuid=plan.id,
            entitlements_schema_version=1,
            entitlements_json=entitlements,
            entitlements_digest=digest,
            status="active",
            expires_at=NOW + timedelta(days=30),
        )
        session.add(subscription)
        session.flush()
        job = BackgroundJob(
            tenant_id=tenant.id,
            tenant_access_version=access_version,
            job_type="sync",
            resource_key="current",
            payload={},
            idempotency_key="sync:1",
            requested_by_type="scheduler",
            available_at=NOW,
        )
        session.add(job)
        session.flush()
        return tenant.id, job.id


def reader(*, recovery=True, deletion=False, suspension=False):
    return ControlTenantGateReader(
        recovery_hold_released=lambda _session, **_kwargs: recovery,
        unresolved_deletion=lambda _session, **_kwargs: deletion,
        unresolved_suspension=lambda _session, **_kwargs: suspension,
        database_clock=lambda _session: NOW,
    )


def test_worker_and_scheduler_share_current_active_authority(database):
    tenant_id, job_id = seed(database)
    gate_reader = reader()
    with database.transaction() as session:
        job = session.get(BackgroundJob, job_id)
        tenant = session.get(Tenant, tenant_id)
        worker = DurableWorkerAuthority(gate_reader).evaluate(
            session,
            job=job,
            phase="before_provider_boundary",
            now=NOW,
        )
        schedule = DurableScheduleGate(gate_reader).evaluate(
            session,
            tenant=tenant,
            now=NOW,
        )

    assert worker.allowed
    assert schedule.allowed


@pytest.mark.parametrize(
    "mutation, expected_reason",
    [
        (lambda tenant, route, subscription, job: setattr(job, "tenant_access_version", 2), "STALE_TENANT_ACCESS_VERSION"),
        (lambda tenant, route, subscription, job: setattr(route, "status", "failed"), "tenant_route_not_ready"),
        (lambda tenant, route, subscription, job: setattr(subscription, "expires_at", NOW), "TENANT_EXPIRED"),
        (lambda tenant, route, subscription, job: setattr(tenant, "status", "suspended"), "TENANT_SUSPENDED"),
    ],
)
def test_worker_fails_closed_on_stale_or_ineligible_control_facts(
    database, mutation, expected_reason
):
    tenant_id, job_id = seed(database)
    with database.transaction() as session:
        tenant = session.get(Tenant, tenant_id)
        route = session.get(TenantDatabase, tenant_id)
        subscription = session.query(Subscription).filter_by(tenant_id=tenant_id).one()
        job = session.get(BackgroundJob, job_id)
        mutation(tenant, route, subscription, job)

    with database.transaction() as session:
        verdict = DurableWorkerAuthority(reader()).evaluate(
            session,
            job=session.get(BackgroundJob, job_id),
            phase="after_claim",
            now=NOW,
        )
    assert not verdict.allowed
    assert verdict.reason_code == expected_reason


def test_recovery_hold_is_distinct_recovery_review(database):
    _tenant_id, job_id = seed(database)
    with database.transaction() as session:
        verdict = DurableWorkerAuthority(reader(recovery=False)).evaluate(
            session,
            job=session.get(BackgroundJob, job_id),
            phase="after_claim",
            now=NOW,
        )
    assert not verdict.allowed
    assert verdict.reason_code == "TENANT_RECOVERY_IN_PROGRESS"
    assert verdict.recovery_review


def test_pending_review_deletion_does_not_freeze_normal_jobs_before_approval(
    database,
):
    tenant_id, job_id = seed(database)
    with database.transaction() as session:
        session.add(
            TenantDeletionRequest(
                id="31000000-0000-4000-8000-000000000001",
                tenant_id=tenant_id,
                database_uuid="31000000-0000-4000-8000-000000000002",
                requested_by_user_id="31000000-0000-4000-8000-000000000003",
                request_challenge_id="31000000-0000-4000-8000-000000000004",
                status="pending_review",
                request_revision=1,
                execution_generation=1,
                executor_fencing_token=1,
                current_action_id="31000000-0000-4000-8000-000000000005",
                committed_tenant_access_version=1,
                desired_dml_login_state="active",
                published_dml_generation=1,
                latest_dml_generation=1,
                recovery_dispositions_required=False,
                requested_at=NOW,
            )
        )

    probes = ControlLifecycleGateProbes()
    gate = ControlTenantGateReader(
        recovery_hold_released=lambda _session, **_kwargs: True,
        unresolved_deletion=probes.unresolved_deletion,
        unresolved_suspension=probes.unresolved_suspension,
        database_clock=lambda _session: NOW,
    )
    with database.transaction() as session:
        verdict = DurableWorkerAuthority(gate).evaluate(
            session,
            job=session.get(BackgroundJob, job_id),
            phase="after_claim",
            now=NOW,
        )

    assert verdict.allowed


def test_blocking_deletion_aggregate_denies_drifted_active_projection(database):
    tenant_id, job_id = seed(database)
    with database.transaction() as session:
        session.add(
            TenantDeletionRequest(
                id="31000000-0000-4000-8000-000000000011",
                tenant_id=tenant_id,
                database_uuid="31000000-0000-4000-8000-000000000012",
                requested_by_user_id="31000000-0000-4000-8000-000000000013",
                request_challenge_id="31000000-0000-4000-8000-000000000014",
                status="cooling_off",
                request_revision=2,
                execution_generation=1,
                executor_fencing_token=1,
                current_action_id="31000000-0000-4000-8000-000000000015",
                committed_tenant_access_version=1,
                desired_dml_login_state="locked",
                published_dml_generation=1,
                latest_dml_generation=1,
                recovery_dispositions_required=False,
                reviewed_by_platform_admin_id=(
                    "31000000-0000-4000-8000-000000000016"
                ),
                pre_freeze_tenant_status="active",
                requested_at=NOW,
                reviewed_at=NOW,
                execute_not_before=NOW + timedelta(days=30),
            )
        )

    probes = ControlLifecycleGateProbes()
    gate = ControlTenantGateReader(
        recovery_hold_released=lambda _session, **_kwargs: True,
        unresolved_deletion=probes.unresolved_deletion,
        unresolved_suspension=probes.unresolved_suspension,
        database_clock=lambda _session: NOW,
    )
    with database.transaction() as session:
        verdict = DurableWorkerAuthority(gate).evaluate(
            session,
            job=session.get(BackgroundJob, job_id),
            phase="after_claim",
            now=NOW,
        )

    assert not verdict.allowed
    assert verdict.reason_code == "TENANT_DELETION_IN_PROGRESS"


def test_persisted_suspension_aggregate_denies_active_status_drift(database):
    tenant_id, job_id = seed(database)
    with database.transaction() as session:
        tenant = session.get(Tenant, tenant_id)
        session.add(
            TenantSuspension(
                tenant_id=tenant_id,
                state="freezing",
                initial_reason_code="manual_platform_suspension",
                barrier_generation=1,
                committed_tenant_row_version=tenant.row_version,
                committed_access_version=tenant.access_version,
                requested_at=NOW,
            )
        )

    probes = ControlLifecycleGateProbes()
    gate = ControlTenantGateReader(
        recovery_hold_released=lambda _session, **_kwargs: True,
        unresolved_deletion=probes.unresolved_deletion,
        unresolved_suspension=probes.unresolved_suspension,
        database_clock=lambda _session: NOW,
    )
    with database.transaction() as session:
        verdict = DurableWorkerAuthority(gate).evaluate(
            session,
            job=session.get(BackgroundJob, job_id),
            phase="before_provider_boundary",
            now=NOW,
        )

    assert not verdict.allowed
    assert verdict.reason_code == "TENANT_SUSPENDED"


def test_missing_probes_cannot_default_to_fail_open():
    with pytest.raises(TypeError, match="probe"):
        ControlTenantGateReader(
            recovery_hold_released=None,
            unresolved_deletion=lambda *_args, **_kwargs: False,
            unresolved_suspension=lambda *_args, **_kwargs: False,
        )


@pytest.mark.parametrize(
    ("tenant_status", "expected_reason"),
    [
        ("suspended", "TENANT_SUSPENDED"),
        ("deletion_cooling_off", "TENANT_DELETION_COOLING_OFF"),
        ("deletion_committing", "TENANT_DELETED"),
        ("deleted", "TENANT_DELETED"),
    ],
)
def test_higher_lifecycle_state_wins_over_expired_subscription_projection(
    database, tenant_status, expected_reason
):
    tenant_id, job_id = seed(database, tenant_status=tenant_status)
    with database.transaction() as session:
        subscription = session.query(Subscription).filter_by(
            tenant_id=tenant_id
        ).one()
        subscription.status = "expired"
        subscription.expires_at = NOW

    with database.transaction() as session:
        verdict = DurableWorkerAuthority(reader()).evaluate(
            session,
            job=session.get(BackgroundJob, job_id),
            phase="before_provider_boundary",
            now=NOW + timedelta(days=100),
        )

    assert not verdict.allowed
    assert verdict.reason_code == expected_reason


def test_gate_uses_database_clock_not_the_worker_supplied_clock(database):
    _tenant_id, job_id = seed(database)

    with database.transaction() as session:
        verdict = DurableWorkerAuthority(reader()).evaluate(
            session,
            job=session.get(BackgroundJob, job_id),
            phase="after_claim",
            now=NOW + timedelta(days=365),
        )

    assert verdict.allowed


def test_worker_can_use_the_persisted_current_recovery_hold_probe(database):
    tenant_id, job_id = seed(database)
    with database.transaction() as session:
        tenant = session.get(Tenant, tenant_id)
        route = session.get(TenantDatabase, tenant_id)
        run = DisasterRecoveryRun(
                kind="initial_baseline",
                policy_version=1,
                status="completed",
                expected_survivor_count=1,
                actual_survivor_count=1,
                sealed_coverage_digest=b"s" * 32,
                final_coverage_digest=b"f" * 32,
                host_installation_fingerprint="a" * 64,
                deployment_marker_fingerprint="b" * 64,
                started_at=NOW,
                reviewing_at=NOW,
                completed_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        session.add(run)
        session.flush()
        session.add(
            TenantRecoveryHold(
                recovery_run_id=run.id,
                tenant_id=tenant.id,
                database_uuid=route.database_uuid,
                state="released",
                hold_revision=1,
                snapshot_underlying_status=tenant.status,
                snapshot_access_version=tenant.access_version,
                expected_dml_login_state_version=1,
                dml_convergence_status="active",
                held_at=NOW,
                released_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    recovery = RecoveryAuthorityService(database_clock=lambda _session: NOW)
    gate = ControlTenantGateReader(
        recovery_hold_released=recovery.is_current_hold_released,
        unresolved_deletion=lambda _session, **_kwargs: False,
        unresolved_suspension=lambda _session, **_kwargs: False,
        database_clock=lambda _session: NOW,
    )
    with database.transaction() as session:
        allowed = DurableWorkerAuthority(gate).evaluate(
            session,
            job=session.get(BackgroundJob, job_id),
            phase="after_claim",
            now=NOW,
        )
        hold = session.query(TenantRecoveryHold).filter_by(
            tenant_id=tenant_id
        ).one()
        hold.state = "held"
    with database.transaction() as session:
        denied = DurableWorkerAuthority(gate).evaluate(
            session,
            job=session.get(BackgroundJob, job_id),
            phase="after_claim",
            now=NOW,
        )

    assert allowed.allowed
    assert not denied.allowed
    assert denied.reason_code == "TENANT_RECOVERY_IN_PROGRESS"
