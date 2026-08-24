from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import select

from inventory_control import ControlBase, ControlDatabase
from inventory_control.jobs import (
    DurableJobWorker,
    RetryBackoffPolicy,
    build_durable_job_process,
)
from inventory_control.models import (
    DisasterRecoveryRun,
    PlanRevision,
    Subscription,
    Tenant,
    TenantRecoveryHold,
)
from inventory_control.models.jobs import BackgroundJob
from inventory_control.models.operations import PlatformOperationalSignal
from inventory_control.operations import (
    OperationalEnvironment,
    OperationalPolicyRegistry,
    OperationalSignalKey,
    OperationalSignalPolicy,
    OperationalSignalService,
)
from inventory_control.subscriptions import (
    SUBSCRIPTION_PROJECTION_JOB_TYPE,
    SubscriptionProjectionEvaluator,
    SubscriptionProjectionJobAuthority,
    SubscriptionProjectionJobHandler,
    SubscriptionProjectionJobScheduler,
    SubscriptionProjectionLifecycleLocks,
    build_subscription_projection_capability,
    parse_core_entitlements,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
TENANT_UUID = UUID("21000000-0000-4000-8000-000000000001")
PLAN_UUID = UUID("21000000-0000-4000-8000-000000000002")
SUBSCRIPTION_UUID = UUID("21000000-0000-4000-8000-000000000003")
RUN_UUID = UUID("21000000-0000-4000-8000-000000000004")
HOLD_UUID = UUID("21000000-0000-4000-8000-000000000005")
DATABASE_UUID = UUID("21000000-0000-4000-8000-000000000006")
ENTITLEMENTS = {
    "features": {"xianyu_sync": True},
    "limits": {"member_seats": 10},
}


@pytest.fixture
def database(mysql_control_database):
    return mysql_control_database


def _seed(
    database,
    *,
    tenant_status="active",
    subscription_status="active",
    expires_at=NOW - timedelta(seconds=1),
):
    snapshot = parse_core_entitlements(
        schema_version=1,
        entitlements=ENTITLEMENTS,
    )
    with database.transaction() as session:
        session.add(
            Tenant(
                id=str(TENANT_UUID),
                status=tenant_status,
                access_version=7,
                row_version=3,
            )
        )
        session.add(
            PlanRevision(
                id=str(PLAN_UUID),
                code="core",
                revision=1,
                name="Core",
                entitlements_schema_version=1,
                entitlements_json=ENTITLEMENTS,
                entitlements_digest=snapshot.digest_sha256,
                active=True,
            )
        )
        session.add(
            Subscription(
                id=str(SUBSCRIPTION_UUID),
                tenant_id=str(TENANT_UUID),
                plan_revision_uuid=str(PLAN_UUID),
                entitlements_schema_version=1,
                entitlements_json=ENTITLEMENTS,
                entitlements_digest=snapshot.digest_sha256,
                status=subscription_status,
                expires_at=expires_at,
                row_version=5,
                provider="manual",
            )
        )


def _fake_lifecycle_locker(_session, _tenant):
    return SubscriptionProjectionLifecycleLocks(
        recovery_run_uuid=str(RUN_UUID),
        recovery_hold_uuid=str(HOLD_UUID),
        deletion_request_uuid=None,
        suspension_uuid=None,
        suspension_action_uuid=None,
    )


def _signal_service():
    policies = OperationalPolicyRegistry(
        OperationalSignalPolicy(
            signal_key=key,
            version=1,
            failure_threshold=2,
            recovery_threshold=1,
            freshness_window=timedelta(minutes=5),
            repeat_interval=timedelta(minutes=10),
        )
        for key in OperationalSignalKey
    )
    return OperationalSignalService(
        environment=OperationalEnvironment.TEST,
        policies=policies,
    )


def _scheduler(database, *, production_locker=False):
    signals = _signal_service()
    return SubscriptionProjectionJobScheduler(
        database=database,
        heartbeat_recorder=signals.record_evaluator_heartbeat,
        lifecycle_locker=(None if production_locker else _fake_lifecycle_locker),
        database_clock=lambda _session: NOW,
    )


def _enqueue(database):
    return _scheduler(database).enqueue_due(
        max_candidates=20,
        priority=30,
        max_attempts=4,
    )


def _worker(database):
    evaluator = SubscriptionProjectionEvaluator(
        lifecycle_locker=_fake_lifecycle_locker,
        database_clock=lambda _session: NOW,
    )
    return DurableJobWorker(
        database=database,
        authority=SubscriptionProjectionJobAuthority(
            lifecycle_locker=_fake_lifecycle_locker
        ),
        handlers={
            SUBSCRIPTION_PROJECTION_JOB_TYPE: (
                SubscriptionProjectionJobHandler(
                    database=database,
                    evaluator=evaluator,
                )
            )
        },
        heartbeat_recorder=_signal_service().record_worker_heartbeat,
        retry_backoff_policy=RetryBackoffPolicy(
            (timedelta(seconds=5), timedelta(seconds=30))
        ),
        worker_id="subscription-projection-test-worker",
        lease_duration=timedelta(minutes=2),
        clock=lambda: NOW,
        allow_sqlite_claim_for_tests=True,
    )


class _UnusedTenantScheduleGate:
    def evaluate(self, _session, *, tenant, now):
        raise AssertionError("projection trigger must not use tenant fan-out")


def test_due_projection_is_durably_enqueued_reused_and_executed(database):
    _seed(database)

    first = _enqueue(database)
    second = _enqueue(database)

    assert first.candidate_tenants == 1
    assert first.enqueued_jobs == 1
    assert second.reused_jobs == 1
    with database.new_session() as session:
        jobs = list(session.scalars(select(BackgroundJob)))
    assert len(jobs) == 1
    assert jobs[0].job_type == SUBSCRIPTION_PROJECTION_JOB_TYPE
    assert jobs[0].priority == 30
    assert jobs[0].max_attempts == 4
    assert jobs[0].not_after is None
    assert set(jobs[0].payload) == {"tenant_uuid", "subscription_uuid"}
    with database.new_session() as session:
        heartbeat = session.get(
            PlatformOperationalSignal,
            OperationalSignalKey.EVALUATOR_HEARTBEAT.value,
        )
        assert heartbeat.effective_status == "healthy"
        assert heartbeat.observed_at.replace(tzinfo=timezone.utc) == NOW

    result = _worker(database).run_once()

    assert result.state == "succeeded"
    with database.new_session() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        subscription = session.get(Subscription, str(SUBSCRIPTION_UUID))
        job = session.get(BackgroundJob, jobs[0].id)
        worker_heartbeat = session.get(
            PlatformOperationalSignal,
            OperationalSignalKey.WORKER_HEARTBEAT.value,
        )
        assert tenant.status == "expired"
        assert tenant.access_version == 7
        assert subscription.status == "expired"
        assert job.status == "succeeded"
        assert job.result == {
            "effective_status": "expired",
            "tenant_changed": True,
            "subscription_changed": True,
            "tenant_row_version": 4,
            "subscription_row_version": 6,
        }
        assert worker_heartbeat.effective_status == "healthy"


def test_capability_trigger_and_worker_share_one_durable_process(database):
    _seed(database)
    signals = _signal_service()
    capability = build_subscription_projection_capability(
        database=database,
        evaluator_heartbeat_recorder=signals.record_evaluator_heartbeat,
        scan_interval=timedelta(seconds=30),
        max_candidates=20,
        priority=30,
        max_attempts=4,
        lifecycle_locker=_fake_lifecycle_locker,
        database_clock=lambda _session: NOW,
    )
    process = build_durable_job_process(
        database=database,
        authority=SubscriptionProjectionJobAuthority(
            lifecycle_locker=_fake_lifecycle_locker
        ),
        heartbeat_recorder=signals.record_worker_heartbeat,
        retry_backoff_policy=RetryBackoffPolicy(
            (timedelta(seconds=5), timedelta(seconds=30))
        ),
        schedule_gate=_UnusedTenantScheduleGate(),
        capabilities=(capability,),
        worker_id="shared-control-worker",
        clock=lambda: NOW,
        allow_sqlite_claim_for_tests=True,
    )

    first = process.run_cycle()
    same_bucket = process.run_cycle()

    assert first.triggered[0].ran is True
    assert first.triggered[0].value.enqueued_jobs == 1
    assert [result.state for result in first.executed] == ["succeeded", "idle"]
    assert same_bucket.triggered[0].ran is False
    assert [result.state for result in same_bucket.executed] == ["idle"]
    with database.new_session() as session:
        assert session.get(Tenant, str(TENANT_UUID)).status == "expired"
        assert session.get(Subscription, str(SUBSCRIPTION_UUID)).status == "expired"
        jobs = list(session.scalars(select(BackgroundJob)))
        assert len(jobs) == 1
        assert jobs[0].status == "succeeded"


def test_system_projection_survives_access_change_and_preserves_suspension(database):
    _seed(database, tenant_status="suspended")
    assert _enqueue(database).enqueued_jobs == 1
    with database.transaction() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        tenant.access_version += 1
        tenant.row_version += 1

    assert _worker(database).run_once().state == "succeeded"

    with database.new_session() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        subscription = session.get(Subscription, str(SUBSCRIPTION_UUID))
        assert tenant.status == "suspended"
        assert tenant.access_version == 8
        assert subscription.status == "expired"


def test_renewal_winning_after_enqueue_is_current_read_and_safe(database):
    _seed(database)
    assert _enqueue(database).enqueued_jobs == 1
    with database.transaction() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        subscription = session.get(Subscription, str(SUBSCRIPTION_UUID))
        tenant.status = "active"
        subscription.status = "active"
        subscription.expires_at = NOW + timedelta(days=30)
        subscription.row_version += 1

    assert _worker(database).run_once().state == "succeeded"

    with database.new_session() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        subscription = session.get(Subscription, str(SUBSCRIPTION_UUID))
        assert tenant.status == "active"
        assert subscription.status == "active"


def test_production_locker_fails_closed_until_current_run_and_hold_exist(database):
    _seed(database)
    scheduler = _scheduler(database, production_locker=True)

    missing = scheduler.enqueue_due(
        max_candidates=1,
        priority=0,
        max_attempts=2,
    )

    assert missing.skipped_authority == 1
    with database.new_session() as session:
        assert session.scalar(select(BackgroundJob.id)) is None

    with database.transaction() as session:
        session.add(
            DisasterRecoveryRun(
                id=str(RUN_UUID),
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
        )
        session.add(
            TenantRecoveryHold(
                id=str(HOLD_UUID),
                recovery_run_id=str(RUN_UUID),
                tenant_id=str(TENANT_UUID),
                database_uuid=str(DATABASE_UUID),
                state="released",
                hold_revision=1,
                snapshot_underlying_status="active",
                snapshot_access_version=7,
                expected_dml_login_state_version=1,
                dml_convergence_status="active",
                held_at=NOW,
                released_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    ready = scheduler.enqueue_due(
        max_candidates=1,
        priority=0,
        max_attempts=2,
    )

    assert ready.enqueued_jobs == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_candidates": 0, "priority": 0, "max_attempts": 1},
        {"max_candidates": 1, "priority": -1, "max_attempts": 1},
        {"max_candidates": 1, "priority": 0, "max_attempts": 0},
    ],
)
def test_scheduler_requires_explicit_bounded_operational_settings(database, kwargs):
    with pytest.raises(ValueError):
        _scheduler(database).enqueue_due(**kwargs)
