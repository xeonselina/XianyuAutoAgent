from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from inventory_control import ControlBase, Tenant
from inventory_control.jobs import (
    AuthorityVerdict,
    ControlJobService,
    DurableJobWorker,
    DurableProviderCallAuthorizer,
    JobOutcome,
    OutcomeDisposition,
    PreparedJob,
    RecoveryCategory,
    RetryBackoffPolicy,
)
from inventory_control.models.jobs import BackgroundJob
from tests.support.test_database import (
    clear_guarded_mysql_test_rows,
    guarded_mysql_control_database,
)


NOW = datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc)
BACKOFF = RetryBackoffPolicy(
    (timedelta(seconds=5), timedelta(seconds=30), timedelta(minutes=2))
)


class FixedClock:
    def __call__(self):
        return NOW


def record_test_worker_heartbeat(_session, *, observed_at):
    assert isinstance(observed_at, datetime)


class RecordingHeartbeats:
    def __init__(self):
        self.observed_at = []

    def __call__(self, _session, *, observed_at):
        self.observed_at.append(observed_at)


class RecordingAuthority:
    def __init__(self, deny_phase=None):
        self.phases = []
        self.deny_phase = deny_phase

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
        assert locked_authority == (
            job.tenant_id,
            job.tenant_access_version,
            phase,
        )
        self.phases.append((phase, job.status, now))
        if phase == self.deny_phase:
            return AuthorityVerdict(False, "tenant_suspended")
        return AuthorityVerdict(True)


class RecordingHandler:
    def __init__(
        self,
        *,
        provider,
        outcome=None,
        fail_prepare=False,
        fail_execute=False,
        recovery_category=None,
    ):
        self.crosses_provider_boundary = provider
        self.recovery_category = recovery_category
        self.outcome = outcome or JobOutcome(
            OutcomeDisposition.SUCCEEDED, safe_result={"safe": True}
        )
        self.fail_prepare = fail_prepare
        self.fail_execute = fail_execute
        self.calls = []

    def prepare(self, job):
        self.calls.append(("prepare", job.status))
        if self.fail_prepare:
            raise RuntimeError("sensitive prepare failure")
        return PreparedJob({"request_digest": "digest-1"})

    def execute(self, job, prepared):
        self.calls.append(("execute", job.status, prepared.value))
        if self.fail_execute:
            raise RuntimeError("unknown provider response")
        return self.outcome


@pytest.fixture(scope="module")
def database_schema():
    with guarded_mysql_control_database(ControlBase.metadata) as database:
        yield database


@pytest.fixture
def database(database_schema):
    clear_guarded_mysql_test_rows(database_schema.engine, ControlBase.metadata)
    return database_schema


def enqueue(database, *, job_type="test_job", max_attempts=3, priority=0):
    service = ControlJobService()
    with database.transaction() as session:
        tenant = Tenant(status="active")
        session.add(tenant)
        session.flush()
        job = service.enqueue_job(
            session,
            tenant_id=tenant.id,
            tenant_access_version=tenant.access_version,
            job_type=job_type,
            resource_key="resource-1",
            payload={"revision_id": "revision-1"},
            idempotency_key="test-job:bucket-1",
            requested_by_type="scheduler",
            max_attempts=max_attempts,
            priority=priority,
            available_at=NOW,
        )
        return job.id


def build_worker(database, authority, handler):
    return DurableJobWorker(
        database=database,
        authority=authority,
        handlers={"test_job": handler},
        heartbeat_recorder=record_test_worker_heartbeat,
        retry_backoff_policy=BACKOFF,
        worker_id="worker-1",
        lease_duration=timedelta(minutes=5),
        clock=FixedClock(),
    )


def load_job(database, job_id):
    with database.new_session() as session:
        return session.get(BackgroundJob, job_id)


def test_retry_backoff_policy_is_positive_nondecreasing_and_capped() -> None:
    assert BACKOFF.retry_at(attempts=1, now=NOW) == NOW + timedelta(seconds=5)
    assert BACKOFF.retry_at(attempts=2, now=NOW) == NOW + timedelta(seconds=30)
    assert BACKOFF.retry_at(attempts=99, now=NOW) == NOW + timedelta(minutes=2)

    with pytest.raises(ValueError, match="positive"):
        RetryBackoffPolicy(())
    with pytest.raises(ValueError, match="nondecreasing"):
        RetryBackoffPolicy((timedelta(seconds=2), timedelta(seconds=1)))


def test_job_outcome_rejects_unpersistable_or_ambiguous_shapes() -> None:
    with pytest.raises(ValueError, match="safe result"):
        JobOutcome(OutcomeDisposition.SUCCEEDED, safe_result="private response")
    with pytest.raises(ValueError, match="reason code"):
        JobOutcome(OutcomeDisposition.RETRY, reason_code="bad\ncode")
    with pytest.raises(ValueError, match="timezone-aware"):
        JobOutcome(
            OutcomeDisposition.RETRY,
            reason_code="retry",
            retry_at=NOW.replace(tzinfo=None),
        )


def test_provider_handler_runs_only_after_three_authority_checks_and_boundary(database):
    job_id = enqueue(database)
    authority = RecordingAuthority()
    handler = RecordingHandler(provider=True)

    result = build_worker(database, authority, handler).run_once()

    assert result.state == "succeeded"
    assert [phase for phase, _status, _now in authority.phases] == [
        "claim",
        "after_claim",
        "before_tenant_context",
        "before_provider_boundary",
    ]
    assert handler.calls == [
        ("prepare", "leased"),
        ("execute", "leased", {"request_digest": "digest-1"}),
    ]
    persisted = load_job(database, job_id)
    assert persisted.status == "succeeded"
    assert persisted.result == {"safe": True}


def test_each_provider_call_rechecks_authority_and_renews_lease(database):
    job_id = enqueue(database)
    authority = RecordingAuthority()
    service = ControlJobService()
    with database.transaction() as session:
        claimed = service.claim_mysql_skip_locked(
            session,
            worker_id="worker-1",
            lease_duration=timedelta(seconds=30),
            authority=authority,
            now=NOW,
        )
    with database.transaction() as session:
        service.begin_provider_submission(
            session,
            job_id=job_id,
            worker_id="worker-1",
            lease_token=claimed.lease_token,
            execution_generation=claimed.execution_generation,
            authority=authority,
            now=NOW,
        )

    verdict = DurableProviderCallAuthorizer(
        database=database,
        authority=authority,
        lease_duration=timedelta(minutes=5),
        clock=FixedClock(),
        service=ControlJobService(database_clock=lambda _session: NOW),
    ).authorize(claimed)

    assert verdict.allowed is True
    assert authority.phases[-1][0] == "before_provider_call"
    persisted = load_job(database, job_id)
    assert persisted.status == "provider_submitting"
    assert persisted.lease_expires_at.replace(tzinfo=timezone.utc) == (
        NOW + timedelta(minutes=5)
    )


def test_provider_call_denial_does_not_invoke_or_finish_for_handler(database):
    job_id = enqueue(database)
    authority = RecordingAuthority(deny_phase="before_provider_call")
    service = ControlJobService()
    with database.transaction() as session:
        claimed = service.claim_mysql_skip_locked(
            session,
            worker_id="worker-1",
            lease_duration=timedelta(minutes=5),
            authority=authority,
            now=NOW,
        )
    with database.transaction() as session:
        service.begin_provider_submission(
            session,
            job_id=job_id,
            worker_id="worker-1",
            lease_token=claimed.lease_token,
            execution_generation=claimed.execution_generation,
            authority=authority,
            now=NOW,
        )

    verdict = DurableProviderCallAuthorizer(
        database=database,
        authority=authority,
        clock=FixedClock(),
    ).authorize(claimed)

    assert verdict.allowed is False
    assert verdict.reason_code == "tenant_suspended"
    assert load_job(database, job_id).status == "provider_submitting"


def test_gate_winning_before_boundary_blocks_without_execute(database):
    job_id = enqueue(database)
    authority = RecordingAuthority(deny_phase="before_provider_boundary")
    handler = RecordingHandler(provider=True)

    result = build_worker(database, authority, handler).run_once()

    assert result.state == "blocked"
    assert handler.calls == [("prepare", "leased")]
    persisted = load_job(database, job_id)
    assert persisted.status == "suspension_blocked"
    assert persisted.blocked_reason_code == "tenant_suspended"


def test_exception_after_provider_boundary_never_auto_retries(database):
    job_id = enqueue(database)
    handler = RecordingHandler(provider=True, fail_execute=True)

    result = build_worker(database, RecordingAuthority(), handler).run_once()

    assert result.state == "review"
    persisted = load_job(database, job_id)
    assert persisted.status == "needs_review"
    assert persisted.review_reason_code == "provider_result_unknown"


def test_registered_safe_retry_policy_requeues_unknown_read_only_provider(database):
    job_id = enqueue(database)
    handler = RecordingHandler(
        provider=True,
        fail_execute=True,
        recovery_category=RecoveryCategory.XIANYU_KUAIMAI_SYNC,
    )

    result = build_worker(database, RecordingAuthority(), handler).run_once()

    assert result.state == "retry"
    persisted = load_job(database, job_id)
    assert persisted.status == "pending"
    assert persisted.last_error_code == "provider_result_unknown_safe_retry"


def test_injected_job_service_must_register_handler_recovery_category(database):
    handler = RecordingHandler(
        provider=True,
        recovery_category=RecoveryCategory.XIANYU_KUAIMAI_SYNC,
    )

    with pytest.raises(TypeError, match="recovery policy composition"):
        DurableJobWorker(
            database=database,
            authority=RecordingAuthority(),
            handlers={"test_job": handler},
            heartbeat_recorder=record_test_worker_heartbeat,
            retry_backoff_policy=BACKOFF,
            worker_id="worker-1",
            clock=FixedClock(),
            service=ControlJobService(),
        )


def test_expired_provider_lease_is_reclaimed_only_for_registered_safe_policy(
    database,
):
    job_id = enqueue(database)
    authority = RecordingAuthority()
    service = ControlJobService(
        recovery_categories={
            "test_job": RecoveryCategory.XIANYU_KUAIMAI_SYNC,
        }
    )
    with database.transaction() as session:
        first = service.claim_mysql_skip_locked(
            session,
            worker_id="worker-1",
            lease_duration=timedelta(minutes=5),
            authority=authority,
            now=NOW,
        )
    with database.transaction() as session:
        service.begin_provider_submission(
            session,
            job_id=job_id,
            worker_id="worker-1",
            lease_token=first.lease_token,
            execution_generation=first.execution_generation,
            authority=authority,
            now=NOW,
        )
    with database.transaction() as session:
        job = session.get(BackgroundJob, job_id)
        job.lease_expires_at = NOW - timedelta(seconds=1)

    with database.transaction() as session:
        reclaimed = service.claim_mysql_skip_locked(
            session,
            worker_id="worker-2",
            lease_duration=timedelta(minutes=5),
            authority=authority,
            now=NOW,
        )

    assert reclaimed is not None
    assert reclaimed.status == "leased"
    assert reclaimed.lease_owner == "worker-2"
    assert reclaimed.attempts == 2
    assert reclaimed.execution_generation == 2


def test_unproved_retry_after_provider_boundary_becomes_review(database):
    job_id = enqueue(database)
    handler = RecordingHandler(
        provider=True,
        outcome=JobOutcome(
            OutcomeDisposition.RETRY,
            reason_code="timeout",
        ),
    )

    build_worker(database, RecordingAuthority(), handler).run_once()

    persisted = load_job(database, job_id)
    assert persisted.status == "needs_review"
    assert persisted.review_reason_code == "provider_result_unknown"


def test_provider_explicit_non_submission_can_retry(database):
    job_id = enqueue(database)
    handler = RecordingHandler(
        provider=True,
        outcome=JobOutcome(
            OutcomeDisposition.RETRY,
            reason_code="provider_rejected_before_submit",
            provider_proved_not_submitted=True,
        ),
    )

    result = build_worker(database, RecordingAuthority(), handler).run_once()

    assert result.state == "retry"
    persisted = load_job(database, job_id)
    assert persisted.status == "pending"
    assert persisted.last_error_code == "provider_rejected_before_submit"


def test_prepare_failure_is_bounded_retry_before_boundary(database):
    job_id = enqueue(database)
    handler = RecordingHandler(provider=True, fail_prepare=True)

    result = build_worker(database, RecordingAuthority(), handler).run_once()

    assert result.state == "retry"
    persisted = load_job(database, job_id)
    assert persisted.status == "pending"
    assert persisted.last_error_code == "handler_prepare_failed"
    assert persisted.available_at.replace(tzinfo=timezone.utc) == (
        NOW + timedelta(seconds=5)
    )


def test_provider_retry_deadline_overrides_shared_backoff(database):
    job_id = enqueue(database)
    deadline = NOW + timedelta(minutes=7)
    handler = RecordingHandler(
        provider=False,
        outcome=JobOutcome(
            OutcomeDisposition.RETRY,
            reason_code="provider_rate_limited",
            retry_at=deadline,
        ),
    )

    result = build_worker(database, RecordingAuthority(), handler).run_once()

    assert result.state == "retry"
    persisted = load_job(database, job_id)
    assert persisted.available_at.replace(tzinfo=timezone.utc) == deadline


@pytest.mark.parametrize(
    ("provider", "expected_status"),
    ((False, "pending"), (True, "needs_review")),
)
def test_invalid_handler_outcome_uses_the_correct_side_effect_recovery(
    database, provider, expected_status
):
    job_id = enqueue(database)
    handler = RecordingHandler(provider=provider, outcome=object())

    result = build_worker(database, RecordingAuthority(), handler).run_once()

    persisted = load_job(database, job_id)
    assert persisted.status == expected_status
    assert result.state == ("review" if provider else "retry")


def test_unknown_handler_enters_review_on_mysql(database):
    job_id = enqueue(database, job_type="unknown")
    worker = DurableJobWorker(
        database=database,
        authority=RecordingAuthority(),
        handlers={},
        heartbeat_recorder=record_test_worker_heartbeat,
        retry_backoff_policy=BACKOFF,
        worker_id="worker-1",
        clock=FixedClock(),
    )
    assert worker.run_once().state == "review"
    assert load_job(database, job_id).review_reason_code == "handler_not_registered"


def test_worker_rejects_non_mysql_dialect_without_opening_a_database():
    class NonMySqlDatabaseStub:
        @contextmanager
        def transaction(self):
            yield SimpleNamespace(
                bind=SimpleNamespace(
                    dialect=SimpleNamespace(name="sqlite")
                )
            )

    failed_heartbeats = RecordingHeartbeats()
    with pytest.raises(RuntimeError, match="requires MySQL"):
        DurableJobWorker(
            database=NonMySqlDatabaseStub(),
            authority=RecordingAuthority(),
            handlers={},
            heartbeat_recorder=failed_heartbeats,
            retry_backoff_policy=BACKOFF,
            worker_id="worker-2",
            clock=FixedClock(),
        ).run_once()
    assert failed_heartbeats.observed_at == []


def test_dedicated_worker_claim_scope_leaves_other_job_types_untouched(database):
    unrelated_id = enqueue(database, job_type="unrelated", priority=100)
    expected_id = enqueue(database, job_type="test_job", priority=1)
    worker = DurableJobWorker(
        database=database,
        authority=RecordingAuthority(),
        handlers={"test_job": RecordingHandler(provider=False)},
        heartbeat_recorder=record_test_worker_heartbeat,
        retry_backoff_policy=BACKOFF,
        worker_id="dedicated-worker",
        clock=FixedClock(),
        claim_job_types={"test_job"},
    )

    result = worker.run_once()

    assert result.state == "succeeded"
    assert result.job_id == expected_id
    assert load_job(database, unrelated_id).status == "pending"


def test_worker_claim_scope_must_be_a_nonempty_registered_subset(database):
    with pytest.raises(ValueError, match="handler subset"):
        DurableJobWorker(
            database=database,
            authority=RecordingAuthority(),
            handlers={"test_job": RecordingHandler(provider=False)},
            heartbeat_recorder=record_test_worker_heartbeat,
            retry_backoff_policy=BACKOFF,
            worker_id="dedicated-worker",
            clock=FixedClock(),
            claim_job_types={"unregistered"},
        )


def test_idle_loop_records_worker_heartbeat_after_returning_to_control_boundary(
    database,
):
    heartbeats = RecordingHeartbeats()
    worker = DurableJobWorker(
        database=database,
        authority=RecordingAuthority(),
        handlers={},
        heartbeat_recorder=heartbeats,
        retry_backoff_policy=BACKOFF,
        worker_id="idle-worker",
        clock=FixedClock(),
    )

    assert worker.run_once().state == "idle"
    assert len(heartbeats.observed_at) == 1
    assert heartbeats.observed_at[0].tzinfo is not None
