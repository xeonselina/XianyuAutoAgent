from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import mysql

from inventory_control import (
    BackgroundJob,
    ControlBase,
    ControlOutboxEvent,
    Tenant,
)
from tests.support.test_database import (
    clear_guarded_mysql_test_rows,
    guarded_mysql_control_database,
)
from inventory_control.jobs import (
    AuthorityVerdict,
    ControlJobService,
    InvalidJobTransition,
    JobIdempotencyConflict,
    LeaseFenceViolation,
)


NOW = datetime(2026, 8, 22, 0, 0, tzinfo=timezone.utc)


class MutableDatabaseClock:
    def __init__(self, current=NOW):
        self.current = current

    def __call__(self, _session):
        return self.current

    def set(self, current):
        self.current = current


class _AllowAllAuthority:
    """Test-only authority that still exercises the mandatory lock protocol."""

    def lock_current_job_authority(self, _session, *, job, phase):
        return (job.tenant_id, job.tenant_access_version, phase)

    def evaluate_locked_job_authority(
        self,
        _session,
        *,
        locked_authority,
        job,
        phase,
        now,
    ):
        del now
        assert locked_authority == (
            job.tenant_id,
            job.tenant_access_version,
            phase,
        )
        return AuthorityVerdict(True)


ALLOW_ALL_AUTHORITY = _AllowAllAuthority()


@pytest.fixture(scope="module")
def control_database_schema():
    with guarded_mysql_control_database(ControlBase.metadata) as database:
        yield database


@pytest.fixture
def control_database(control_database_schema):
    clear_guarded_mysql_test_rows(
        control_database_schema.engine,
        ControlBase.metadata,
    )
    return control_database_schema


@pytest.fixture
def tenant_id(control_database):
    with control_database.transaction() as session:
        tenant = Tenant()
        session.add(tenant)
        session.flush()
        return tenant.id


def _enqueue(
    service,
    session,
    tenant_id,
    *,
    key="sync:2026-08-22T00:00",
    priority=0,
    max_attempts=3,
    not_after=None,
):
    return service.enqueue_job(
        session,
        tenant_id=tenant_id,
        tenant_access_version=1,
        job_type="xianyu_alert_sync",
        resource_key="connection-set:current",
        payload={"connection_revision_ids": ["revision-1"]},
        idempotency_key=key,
        requested_by_type="scheduler",
        priority=priority,
        max_attempts=max_attempts,
        available_at=NOW,
        not_after=not_after,
    )


def test_enqueue_reuses_stable_job_and_outbox_idempotency(
    control_database, tenant_id
):
    service = ControlJobService()
    with control_database.transaction() as session:
        first_job = _enqueue(service, session, tenant_id)
        duplicate_job = _enqueue(service, session, tenant_id)
        first_event = service.enqueue_outbox(
            session,
            tenant_id=tenant_id,
            tenant_access_version=1,
            source_type="registration_attempt",
            source_uuid="00000000-0000-0000-0000-000000000010",
            source_generation=1,
            event_type="provisional_cleanup",
            payload={"database_uuid": "00000000-0000-0000-0000-000000000020"},
            idempotency_key="cleanup:g1",
            available_at=NOW,
        )
        duplicate_event = service.enqueue_outbox(
            session,
            tenant_id=tenant_id,
            tenant_access_version=1,
            source_type="registration_attempt",
            source_uuid="00000000-0000-0000-0000-000000000010",
            source_generation=1,
            event_type="provisional_cleanup",
            payload={"ignored_duplicate_payload": True},
            idempotency_key="cleanup:g1",
            available_at=NOW,
        )

        assert first_job.id == duplicate_job.id
        assert first_job.payload == {"connection_revision_ids": ["revision-1"]}
        assert first_event.id == duplicate_event.id
        assert first_event.payload == {
            "database_uuid": "00000000-0000-0000-0000-000000000020"
        }

    with control_database.new_session() as session:
        assert session.scalar(select(func.count()).select_from(BackgroundJob)) == 1
        assert (
            session.scalar(select(func.count()).select_from(ControlOutboxEvent)) == 1
        )


def test_enqueue_accepts_one_preallocated_job_uuid_and_fences_replays(
    control_database, tenant_id
):
    service = ControlJobService()
    selected_job_id = "11111111-1111-4111-8111-111111111111"
    conflicting_job_id = "22222222-2222-4222-8222-222222222222"

    with control_database.transaction() as session:
        first = service.enqueue_job(
            session,
            tenant_id=tenant_id,
            tenant_access_version=1,
            job_type="xianyu_alert_sync",
            resource_key="connection-set:current",
            payload={"connection_revision_ids": ["revision-1"]},
            idempotency_key="preallocated-job",
            requested_by_type="scheduler",
            job_id=selected_job_id,
            available_at=NOW,
        )
        replay = service.enqueue_job(
            session,
            tenant_id=tenant_id,
            tenant_access_version=1,
            job_type="xianyu_alert_sync",
            resource_key="connection-set:current",
            payload={"connection_revision_ids": ["revision-1"]},
            idempotency_key="preallocated-job",
            requested_by_type="scheduler",
            job_id=selected_job_id,
            available_at=NOW,
        )

        assert first.id == selected_job_id == replay.id
        with pytest.raises(JobIdempotencyConflict, match="immutable facts"):
            service.enqueue_job(
                session,
                tenant_id=tenant_id,
                tenant_access_version=1,
                job_type="xianyu_alert_sync",
                resource_key="connection-set:current",
                payload={"connection_revision_ids": ["revision-1"]},
                idempotency_key="preallocated-job",
                requested_by_type="scheduler",
                job_id=conflicting_job_id,
                available_at=NOW,
            )

    with control_database.transaction() as session:
        with pytest.raises(ValueError, match="job_id is invalid"):
            service.enqueue_job(
                session,
                tenant_id=tenant_id,
                tenant_access_version=1,
                job_type="xianyu_alert_sync",
                resource_key="connection-set:current",
                payload={},
                idempotency_key="invalid-preallocated-job",
                requested_by_type="scheduler",
                job_id="not-a-uuid",
                available_at=NOW,
            )


def test_pending_job_promotion_only_moves_coalesced_work_forward(
    control_database, tenant_id
):
    service = ControlJobService()
    earlier = NOW - timedelta(seconds=5)
    with control_database.transaction() as session:
        job = _enqueue(service, session, tenant_id, priority=10)
        promoted = service.promote_pending_job(
            session,
            job_id=job.id,
            priority=100,
            available_at=earlier,
            now=NOW,
        )
        replay = service.promote_pending_job(
            session,
            job_id=job.id,
            priority=5,
            available_at=NOW,
            now=NOW,
        )

        assert promoted.id == job.id == replay.id
        assert replay.priority == 100
        assert replay.available_at.replace(tzinfo=timezone.utc) == earlier

    with control_database.transaction() as session:
        claimed = service.claim_mysql_skip_locked(
            session,
            worker_id="worker-a",
            lease_duration=timedelta(seconds=30),
            authority=ALLOW_ALL_AUTHORITY,
            now=NOW,
        )
        unchanged = service.promote_pending_job(
            session,
            job_id=claimed.id,
            priority=200,
            available_at=earlier - timedelta(seconds=1),
            now=NOW,
        )
        assert unchanged.status == "leased"
        assert unchanged.priority == 100


def test_job_idempotency_replay_rejects_changed_immutable_payload(
    control_database, tenant_id
):
    service = ControlJobService()
    with control_database.transaction() as session:
        job = _enqueue(service, session, tenant_id)
        with pytest.raises(JobIdempotencyConflict, match="immutable facts"):
            service.enqueue_job(
                session,
                tenant_id=tenant_id,
                tenant_access_version=1,
                job_type=job.job_type,
                resource_key=job.resource_key,
                payload={"connection_revision_ids": ["different-revision"]},
                idempotency_key=job.idempotency_key,
                requested_by_type="scheduler",
                available_at=NOW,
            )

        assert job.payload == {"connection_revision_ids": ["revision-1"]}
        assert job.status == "pending"


def test_claim_heartbeat_reclaim_and_fencing(control_database, tenant_id):
    clock = MutableDatabaseClock()
    service = ControlJobService(database_clock=clock)
    with control_database.transaction() as session:
        low = _enqueue(service, session, tenant_id, key="low", priority=1)
        high = _enqueue(service, session, tenant_id, key="high", priority=50)
        claimed = service.claim_mysql_skip_locked(
            session,
            worker_id="worker-a",
            lease_duration=timedelta(seconds=10),
            authority=ALLOW_ALL_AUTHORITY,
            now=NOW,
        )
        assert claimed.id == high.id
        assert claimed.id != low.id
        first_token = claimed.lease_token
        first_generation = claimed.execution_generation

    clock.set(NOW + timedelta(seconds=5))
    with control_database.transaction() as session:
        heartbeat = service.heartbeat(
            session,
            job_id=high.id,
            worker_id="worker-a",
            lease_token=first_token,
            execution_generation=first_generation,
            lease_duration=timedelta(seconds=10),
            authority=ALLOW_ALL_AUTHORITY,
            now=NOW + timedelta(seconds=5),
        )
        assert heartbeat.lease_expires_at.replace(tzinfo=timezone.utc) == (
            NOW + timedelta(seconds=15)
        )

    clock.set(NOW + timedelta(seconds=16))
    with control_database.transaction() as session:
        reclaimed = service.claim_mysql_skip_locked(
            session,
            worker_id="worker-b",
            lease_duration=timedelta(seconds=10),
            authority=ALLOW_ALL_AUTHORITY,
            now=NOW + timedelta(seconds=16),
        )
        assert reclaimed.id == high.id
        assert reclaimed.execution_generation == first_generation + 1
        assert reclaimed.lease_token != first_token
        second_token = reclaimed.lease_token
        second_generation = reclaimed.execution_generation

    clock.set(NOW + timedelta(seconds=17))
    with control_database.new_session() as session:
        with pytest.raises(LeaseFenceViolation, match="stale"):
            service.complete(
                session,
                job_id=high.id,
                worker_id="worker-a",
                lease_token=first_token,
                execution_generation=first_generation,
                now=NOW + timedelta(seconds=17),
            )

    with control_database.transaction() as session:
        completed = service.complete(
            session,
            job_id=high.id,
            worker_id="worker-b",
            lease_token=second_token,
            execution_generation=second_generation,
            result={"snapshot_revision": 4},
            now=NOW + timedelta(seconds=17),
        )
        assert completed.status == "succeeded"
        assert completed.result == {"snapshot_revision": 4}
        assert completed.lease_token is None


def test_retry_exhaustion_enters_dead_letter(control_database, tenant_id):
    service = ControlJobService()
    with control_database.transaction() as session:
        job = _enqueue(service, session, tenant_id, max_attempts=2)
        first = service.claim_mysql_skip_locked(
            session,
            worker_id="worker-a",
            lease_duration=timedelta(seconds=30),
            authority=ALLOW_ALL_AUTHORITY,
            now=NOW,
        )
        first_token = first.lease_token
        first_generation = first.execution_generation

    with control_database.transaction() as session:
        retried = service.fail(
            session,
            job_id=job.id,
            worker_id="worker-a",
            lease_token=first_token,
            execution_generation=first_generation,
            error_code="provider_busy",
            retryable=True,
            retry_at=NOW + timedelta(seconds=5),
            now=NOW + timedelta(seconds=1),
        )
        assert retried.status == "pending"

    with control_database.transaction() as session:
        second = service.claim_mysql_skip_locked(
            session,
            worker_id="worker-b",
            lease_duration=timedelta(seconds=30),
            authority=ALLOW_ALL_AUTHORITY,
            now=NOW + timedelta(seconds=5),
        )
        second_token = second.lease_token
        second_generation = second.execution_generation
        assert second.attempts == 2

    with control_database.transaction() as session:
        exhausted = service.fail(
            session,
            job_id=job.id,
            worker_id="worker-b",
            lease_token=second_token,
            execution_generation=second_generation,
            error_code="provider_busy",
            retryable=True,
            retry_at=NOW + timedelta(seconds=10),
            now=NOW + timedelta(seconds=6),
        )
        assert exhausted.status == "dead_letter"
        assert exhausted.lease_owner is None


def test_provider_boundary_is_committed_and_expired_lease_is_never_stolen(
    control_database, tenant_id
):
    clock = MutableDatabaseClock()
    service = ControlJobService(database_clock=clock)
    with control_database.transaction() as session:
        job = _enqueue(service, session, tenant_id)
        claimed = service.claim_mysql_skip_locked(
            session,
            worker_id="worker-a",
            lease_duration=timedelta(seconds=5),
            authority=ALLOW_ALL_AUTHORITY,
            now=NOW,
        )
        token = claimed.lease_token
        generation = claimed.execution_generation

    clock.set(NOW + timedelta(seconds=1))
    with control_database.transaction() as session:
        boundary = service.begin_provider_submission(
            session,
            job_id=job.id,
            worker_id="worker-a",
            lease_token=token,
            execution_generation=generation,
            authority=ALLOW_ALL_AUTHORITY,
            now=NOW + timedelta(seconds=1),
        )
        assert boundary.status == "provider_submitting"

    clock.set(NOW + timedelta(seconds=6))
    with control_database.transaction() as session:
        assert service.claim_mysql_skip_locked(
            session,
            worker_id="worker-b",
            lease_duration=timedelta(seconds=5),
            authority=ALLOW_ALL_AUTHORITY,
            now=NOW + timedelta(seconds=6),
        ) is None
        unknown = session.get(BackgroundJob, job.id)
        assert unknown.status == "needs_review"
        assert unknown.review_reason_code == "provider_result_unknown"
        assert unknown.lease_token is None


@pytest.mark.parametrize(
    ("reason_code", "recovery", "expected_status"),
    [
        ("tenant_suspended", False, "suspension_blocked"),
        ("tenant_expired", False, "needs_review"),
        ("tenant_recovery_hold", True, "recovery_review"),
    ],
)
def test_gate_block_finishes_lease_before_any_provider_call(
    control_database, tenant_id, reason_code, recovery, expected_status
):
    service = ControlJobService()
    with control_database.transaction() as session:
        job = _enqueue(service, session, tenant_id, key=reason_code)
        claimed = service.claim_mysql_skip_locked(
            session,
            worker_id="worker-a",
            lease_duration=timedelta(seconds=30),
            authority=ALLOW_ALL_AUTHORITY,
            now=NOW,
        )
        blocked = service.block_for_gate(
            session,
            job_id=job.id,
            worker_id="worker-a",
            lease_token=claimed.lease_token,
            execution_generation=claimed.execution_generation,
            reason_code=reason_code,
            recovery=recovery,
            now=NOW + timedelta(seconds=1),
        )

        assert blocked.status == expected_status
        assert blocked.lease_token is None
        persisted_reason = (
            blocked.blocked_reason_code
            if expected_status == "suspension_blocked"
            else blocked.review_reason_code
        )
        assert persisted_reason == reason_code


def test_review_and_deadline_expiry_are_not_replayed(control_database, tenant_id):
    service = ControlJobService()
    with control_database.transaction() as session:
        review_job = _enqueue(
            service, session, tenant_id, key="review", priority=10
        )
        _enqueue(
            service,
            session,
            tenant_id,
            key="expired",
            not_after=NOW + timedelta(seconds=1),
        )
        claimed = service.claim_mysql_skip_locked(
            session,
            worker_id="worker-a",
            lease_duration=timedelta(seconds=30),
            authority=ALLOW_ALL_AUTHORITY,
            now=NOW,
        )
        assert claimed.id == review_job.id
        token = claimed.lease_token
        generation = claimed.execution_generation

    with control_database.transaction() as session:
        reviewed = service.mark_review(
            session,
            job_id=review_job.id,
            worker_id="worker-a",
            lease_token=token,
            execution_generation=generation,
            reason_code="provider_result_unknown",
            now=NOW + timedelta(seconds=1),
        )
        assert reviewed.status == "needs_review"

    with control_database.transaction() as session:
        assert (
            service.claim_mysql_skip_locked(
                session,
                worker_id="worker-b",
                lease_duration=timedelta(seconds=30),
                authority=ALLOW_ALL_AUTHORITY,
                now=NOW + timedelta(seconds=2),
            )
            is None
        )
        expired = session.scalar(
            select(BackgroundJob).where(BackgroundJob.idempotency_key == "expired")
        )
        assert expired.status == "needs_review"
        assert expired.review_reason_code == "not_after_expired"


def test_expired_last_attempt_lease_enters_dead_letter(control_database, tenant_id):
    clock = MutableDatabaseClock()
    service = ControlJobService(database_clock=clock)
    with control_database.transaction() as session:
        job = _enqueue(service, session, tenant_id, max_attempts=1)
        claimed = service.claim_mysql_skip_locked(
            session,
            worker_id="worker-a",
            lease_duration=timedelta(seconds=5),
            authority=ALLOW_ALL_AUTHORITY,
            now=NOW,
        )
        assert claimed.id == job.id

    clock.set(NOW + timedelta(seconds=6))
    with control_database.transaction() as session:
        assert (
            service.claim_mysql_skip_locked(
                session,
                worker_id="worker-b",
                lease_duration=timedelta(seconds=5),
                authority=ALLOW_ALL_AUTHORITY,
                now=NOW + timedelta(seconds=6),
            )
            is None
        )
        exhausted = session.get(BackgroundJob, job.id)
        assert exhausted.status == "dead_letter"
        assert exhausted.last_error_code == "attempts_exhausted"
        assert exhausted.lease_token is None


def test_invalid_terminal_transition_and_mysql_backend_check_are_explicit(
    control_database, tenant_id
):
    service = ControlJobService()
    with control_database.transaction() as session:
        job = _enqueue(service, session, tenant_id)
        claimed = service.claim_mysql_skip_locked(
            session,
            worker_id="worker-a",
            lease_duration=timedelta(seconds=30),
            authority=ALLOW_ALL_AUTHORITY,
            now=NOW,
        )
        token = claimed.lease_token
        generation = claimed.execution_generation

    with control_database.transaction() as session:
        service.complete(
            session,
            job_id=job.id,
            worker_id="worker-a",
            lease_token=token,
            execution_generation=generation,
            now=NOW + timedelta(seconds=1),
        )

    with control_database.new_session() as session:
        with pytest.raises(InvalidJobTransition, match="does not allow"):
            service.heartbeat(
                session,
                job_id=job.id,
                worker_id="worker-a",
                lease_token=token,
                execution_generation=generation,
                lease_duration=timedelta(seconds=30),
                authority=ALLOW_ALL_AUTHORITY,
                now=NOW + timedelta(seconds=2),
            )
    non_mysql_session = SimpleNamespace(
        bind=SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    )
    with pytest.raises(RuntimeError, match="requires MySQL"):
        service.claim_mysql_skip_locked(
            non_mysql_session,
            worker_id="worker-a",
            lease_duration=timedelta(seconds=30),
            authority=ALLOW_ALL_AUTHORITY,
        )


def test_mysql_claim_discovery_is_nonlocking_and_keeps_fixed_priority_order():
    service = ControlJobService()
    statement = service._mysql_claim_candidate_statement(now=NOW)

    compiled = str(
        statement.compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()

    assert "FOR UPDATE" not in compiled
    assert "ORDER BY BACKGROUND_JOBS.PRIORITY DESC" in compiled
    assert "BACKGROUND_JOBS.AVAILABLE_AT ASC" in compiled
    assert "BACKGROUND_JOBS.CREATED_AT ASC" in compiled
    assert "BACKGROUND_JOBS.ID ASC" in compiled
