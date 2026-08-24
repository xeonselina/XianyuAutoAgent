from datetime import datetime, timedelta, timezone
import hashlib
from uuid import UUID

import pytest
import sqlalchemy as sa

from inventory_control import ControlBase, ControlDatabase, Tenant
from inventory_control.crypto import RootKey
from inventory_control.integrations import (
    ProviderValidationOutcome,
    TenantIntegrationService,
)
from inventory_control.jobs import (
    PeriodicTenantScheduler,
    ScheduleGateVerdict,
    XIAN_YU_MANUAL_JOB_TYPE,
    XIAN_YU_SCHEDULED_JOB_TYPE,
    XianyuSyncJobCoordinator,
    XianyuSyncNotConfigured,
    XianyuTenantScheduleGate,
    xianyu_periodic_job_definition,
)
from inventory_control.jobs.scheduler import _current_cycle
from inventory_control.models.jobs import BackgroundJob


TENANT = UUID("61000000-0000-4000-8000-000000000001")
USER = UUID("61000000-0000-4000-8000-000000000002")
ROOT_KEY = RootKey(version=1, material=b"x" * 32)
BUCKET = datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc)


class AllowGate:
    def evaluate(self, _session, *, tenant, now):
        assert tenant.id == str(TENANT)
        assert now.tzinfo is not None
        return ScheduleGateVerdict(True)


@pytest.fixture
def database(mysql_control_database):
    with mysql_control_database.transaction() as session:
        session.add(Tenant(id=str(TENANT), status="active", access_version=7))
    return mysql_control_database


def _activate_connection(database, ordinal):
    integration = UUID(f"62000000-0000-4000-8000-{ordinal:012d}")
    action = UUID(f"63000000-0000-4000-8000-{ordinal:012d}")
    attempt = UUID(f"64000000-0000-4000-8000-{ordinal:012d}")
    with database.transaction() as session:
        TenantIntegrationService(session).create_integration(
            integration_uuid=integration,
            tenant_uuid=TENANT,
            provider="xianyu",
            name=f"xianyu-{ordinal}",
        )
    with database.transaction() as session:
        pending = TenantIntegrationService(session).create_pending_revision(
            integration_uuid=integration,
            credentials={
                "app_key": f"app-{ordinal}",
                "app_secret": f"secret-{ordinal}",
            },
            root_key=ROOT_KEY,
            created_by_user_uuid=USER,
            action_uuid=action,
            idempotency_key=f"xianyu-revision:{ordinal}",
            expected_integration_row_version=1,
            expected_current_secret_revision_uuid=None,
        )
    with database.transaction() as session:
        TenantIntegrationService(session).begin_provider_validation(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=attempt,
            expected_revision_row_version=1,
        )
    with database.transaction() as session:
        TenantIntegrationService(session).record_provider_validation_result(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=attempt,
            outcome=ProviderValidationOutcome.SUCCESS,
            provider_result_digest=hashlib.sha256(
                f"valid-{ordinal}".encode("ascii")
            ).digest(),
            safe_code="VALID",
        )
    return str(integration), pending.revision_uuid


def _due_time():
    cycle = _current_cycle(
        tenant_id=str(TENANT),
        job_type=XIAN_YU_SCHEDULED_JOB_TYPE,
        interval=timedelta(seconds=180),
        not_after_window=timedelta(seconds=180),
        now=BUCKET,
    )
    return cycle.trigger_at


def test_periodic_job_freezes_every_active_connection_and_is_stable(database):
    first = _activate_connection(database, 1)
    second = _activate_connection(database, 2)
    scheduler = PeriodicTenantScheduler(
        database=database,
        gate=XianyuTenantScheduleGate(AllowGate()),
    )

    first_run = scheduler.fan_out(
        xianyu_periodic_job_definition(),
        now=_due_time(),
    )
    second_run = scheduler.fan_out(
        xianyu_periodic_job_definition(),
        now=_due_time(),
    )

    assert first_run.enqueued_jobs == 1
    assert second_run.reused_jobs == 1
    with database.new_session() as session:
        job = session.scalar(sa.select(BackgroundJob))
    assert job.job_type == XIAN_YU_SCHEDULED_JOB_TYPE
    assert job.tenant_access_version == 7
    assert [
        (item["integration_uuid"], item["secret_revision_uuid"])
        for item in job.payload["connections"]
    ] == sorted((first, second))
    assert job.payload["connection_set_digest"] in job.idempotency_key
    assert "app-1" not in repr(job.payload)
    assert "secret-1" not in repr(job.payload)


def test_periodic_job_skips_tenant_without_current_connection(database):
    result = PeriodicTenantScheduler(
        database=database,
        gate=XianyuTenantScheduleGate(AllowGate()),
    ).fan_out(xianyu_periodic_job_definition(), now=_due_time())

    assert result.enqueued_jobs == 0
    assert result.skipped_gate == 1


def test_manual_refresh_reuses_scheduled_job_in_flight(database):
    _activate_connection(database, 1)
    scheduler = PeriodicTenantScheduler(
        database=database,
        gate=XianyuTenantScheduleGate(AllowGate()),
    )
    scheduler.fan_out(xianyu_periodic_job_definition(), now=_due_time())
    with database.new_session() as session:
        scheduled = session.scalar(sa.select(BackgroundJob))

    submission = XianyuSyncJobCoordinator(
        database=database,
        gate=AllowGate(),
    ).enqueue_manual(
        tenant_uuid=TENANT,
        requested_by_user_uuid=USER,
        snapshot_revision=12,
        now=_due_time() + timedelta(seconds=1),
    )

    assert submission.job_uuid == scheduled.id
    assert submission.snapshot_revision == 12
    assert submission.job_status == "pending"
    assert submission.reused is True
    with database.new_session() as session:
        jobs = list(session.scalars(sa.select(BackgroundJob)))
        assert len(jobs) == 1
        assert jobs[0].priority == 100


def test_manual_refresh_is_deduplicated_for_completed_current_bucket(database):
    _activate_connection(database, 1)
    coordinator = XianyuSyncJobCoordinator(
        database=database,
        gate=AllowGate(),
    )
    first = coordinator.enqueue_manual(
        tenant_uuid=TENANT,
        requested_by_user_uuid=USER,
        snapshot_revision=3,
        now=BUCKET + timedelta(seconds=1),
    )
    with database.transaction() as session:
        job = session.get(BackgroundJob, first.job_uuid)
        job.status = "succeeded"
        job.completed_at = BUCKET + timedelta(seconds=2)
    second = coordinator.enqueue_manual(
        tenant_uuid=TENANT,
        requested_by_user_uuid=USER,
        snapshot_revision=4,
        now=BUCKET + timedelta(seconds=20),
    )

    assert first.reused is False
    assert second.reused is True
    assert second.job_uuid == first.job_uuid
    assert second.snapshot_revision == 4
    assert second.job_status == "succeeded"


def test_manual_refresh_creates_high_priority_exact_revision_job(database):
    connection = _activate_connection(database, 1)
    submission = XianyuSyncJobCoordinator(
        database=database,
        gate=AllowGate(),
    ).enqueue_manual(
        tenant_uuid=TENANT,
        requested_by_user_uuid=USER,
        snapshot_revision=0,
        now=BUCKET + timedelta(seconds=1),
        request_id="request-1",
    )

    with database.new_session() as session:
        job = session.get(BackgroundJob, submission.job_uuid)
    assert job.job_type == XIAN_YU_MANUAL_JOB_TYPE
    assert job.priority == 100
    assert job.requested_by_id == str(USER)
    assert job.payload["connections"][0]["integration_uuid"] == connection[0]
    assert job.payload["connections"][0]["secret_revision_uuid"] == connection[1]
    assert job.not_after - job.available_at == timedelta(seconds=180)


def test_manual_refresh_fails_closed_without_configuration(database):
    with pytest.raises(XianyuSyncNotConfigured):
        XianyuSyncJobCoordinator(
            database=database,
            gate=AllowGate(),
        ).enqueue_manual(
            tenant_uuid=TENANT,
            requested_by_user_uuid=USER,
            snapshot_revision=0,
            now=BUCKET,
        )
