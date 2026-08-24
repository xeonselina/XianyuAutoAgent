from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from inventory_control import ControlDatabase
from inventory_control.jobs import (
    ApschedulerJobProcessHost,
    AuthorityVerdict,
    CapabilityJobAuthority,
    DurableJobCapability,
    DurableJobProcess,
    FanOutResult,
    JobProcessTrigger,
    PeriodicJobDefinition,
    RetryBackoffPolicy,
    SignalAwareJobProcessHost,
    WorkerRunResult,
    build_durable_job_process,
)


NOW = datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc)
BACKOFF = RetryBackoffPolicy(
    (timedelta(seconds=5), timedelta(seconds=30))
)


def _definition(job_type: str = "periodic") -> PeriodicJobDefinition:
    return PeriodicJobDefinition(
        job_type=job_type,
        interval=timedelta(minutes=3),
        not_after_window=timedelta(minutes=3),
        resource_key=f"{job_type}:current",
        payload_builder=lambda *_args: {},
    )


class Scheduler:
    def __init__(self) -> None:
        self.calls = []

    def fan_out(self, definition, *, now):
        self.calls.append((definition.job_type, now))
        return FanOutResult(1, 1, 0, 0, 0)


class Worker:
    def __init__(self, states) -> None:
        self.states = list(states)
        self.calls = 0

    def run_once(self):
        self.calls += 1
        state = self.states.pop(0) if self.states else "idle"
        return WorkerRunResult(state)


class Handler:
    crosses_provider_boundary = False
    recovery_category = None

    def prepare(self, job):
        return job

    def execute(self, job, prepared):
        return None


class Authority:
    def lock_current_job_authority(self, _session, *, job, phase):
        return job.id, phase

    def evaluate_locked_job_authority(
        self, _session, *, locked_authority, job, phase, now
    ):
        return AuthorityVerdict(True)


class NamedAuthority:
    def __init__(self, name, *, allowed):
        self.name = name
        self.allowed = allowed

    def lock_current_job_authority(self, _session, *, job, phase):
        return self.name, job.id, phase

    def evaluate_locked_job_authority(
        self, _session, *, locked_authority, job, phase, now
    ):
        assert locked_authority == (self.name, job.id, phase)
        return AuthorityVerdict(self.allowed, None if self.allowed else self.name)


class Gate:
    def evaluate(self, _session, *, tenant, now):
        raise AssertionError("composition must not evaluate tenant authority")


def _process(*, scheduler=None, worker=None, **overrides):
    arguments = {
        "scheduler": scheduler or Scheduler(),
        "definitions": (_definition(),),
        "worker": worker or Worker(("idle",)),
        "max_jobs_per_cycle": 3,
        "idle_poll_interval": timedelta(seconds=2),
        "clock": lambda: NOW,
    }
    arguments.update(overrides)
    return DurableJobProcess(**arguments)


def _disconnected_control_database() -> ControlDatabase:
    return ControlDatabase(
        engine=SimpleNamespace(dispose=lambda: None),
        session_factory=object(),
    )


def test_cycle_uses_one_clock_snapshot_and_drains_until_idle() -> None:
    scheduler = Scheduler()
    worker = Worker(("succeeded", "retry", "idle", "succeeded"))

    result = _process(scheduler=scheduler, worker=worker).run_cycle()

    assert scheduler.calls == [("periodic", NOW)]
    assert [item.state for item in result.executed] == [
        "succeeded",
        "retry",
        "idle",
    ]
    assert result.worker_budget_exhausted is False
    assert worker.calls == 3


def test_cycle_bounds_queue_work_before_rescheduling() -> None:
    worker = Worker(("succeeded",) * 4)

    result = _process(worker=worker).run_cycle()

    assert len(result.executed) == 3
    assert result.worker_budget_exhausted is True
    assert worker.calls == 3


def test_forever_wait_is_interruptible_and_skips_idle_delay_for_backlog() -> None:
    worker = Worker(("succeeded",) * 3 + ("idle",))
    waits = []

    def wait_for_stop(delay):
        waits.append(delay)
        return len(waits) == 4

    cycles = _process(worker=worker).run_forever(wait_for_stop=wait_for_stop)

    assert cycles == 2
    assert waits == [0, 0, 0, 2.0]


def test_scheduler_or_worker_failure_propagates_to_process_supervisor() -> None:
    class FailedScheduler:
        def fan_out(self, _definition, *, now):
            raise RuntimeError("control database unavailable")

    with pytest.raises(RuntimeError, match="control database unavailable"):
        _process(scheduler=FailedScheduler()).run_cycle()


def test_capability_trigger_runs_once_per_bucket_with_the_cycle_clock() -> None:
    calls = []
    trigger = JobProcessTrigger(
        name="subscription-projection-scan",
        interval=timedelta(seconds=30),
        callback=lambda now: calls.append(now) or "scanned",
    )
    process = _process(triggers=(trigger,))

    first = process.run_cycle()
    replay = process.run_cycle()

    assert first.triggered[0].ran is True
    assert first.triggered[0].value == "scanned"
    assert replay.triggered[0].ran is False
    assert calls == [NOW]


def test_failed_capability_trigger_is_not_marked_as_executed() -> None:
    calls = []

    def fail_once(now):
        calls.append(now)
        if len(calls) == 1:
            raise RuntimeError("database unavailable")
        return "recovered"

    process = _process(
        triggers=(
            JobProcessTrigger(
                name="retrying-scan",
                interval=timedelta(minutes=1),
                callback=fail_once,
            ),
        )
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        process.run_cycle()
    assert process.run_cycle().triggered[0].value == "recovered"
    assert calls == [NOW, NOW]


@pytest.mark.parametrize(
    ("override", "expected"),
    (
        ({"scheduler": object()}, TypeError),
        ({"definitions": ()}, ValueError),
        ({"definitions": (object(),)}, TypeError),
        ({"worker": object()}, TypeError),
        ({"max_jobs_per_cycle": 0}, ValueError),
        ({"idle_poll_interval": timedelta(0)}, ValueError),
        ({"clock": object()}, TypeError),
    ),
)
def test_invalid_runtime_composition_is_rejected(override, expected) -> None:
    with pytest.raises(expected):
        _process(**override)


def test_runtime_rejects_invalid_results_and_naive_clock() -> None:
    class InvalidScheduler:
        def fan_out(self, _definition, *, now):
            return object()

    with pytest.raises(TypeError, match="scheduler returned"):
        _process(scheduler=InvalidScheduler()).run_cycle()
    with pytest.raises(ValueError, match="timezone-aware"):
        _process(clock=lambda: NOW.replace(tzinfo=None)).run_cycle()


class HostScheduler:
    def __init__(self, *, execute=True) -> None:
        self.running = False
        self.execute = execute
        self.job = None
        self.job_options = None
        self.shutdown_wait = None

    def add_job(self, job, **options):
        self.job = job
        self.job_options = options

    def start(self):
        self.running = True
        if self.execute:
            self.job()
        self.running = False

    def shutdown(self, *, wait):
        self.shutdown_wait = wait
        self.running = False


def test_apscheduler_host_owns_one_nonoverlapping_immediate_cycle() -> None:
    scheduler = HostScheduler()
    process = _process()

    ApschedulerJobProcessHost(
        process=process,
        tick_interval=timedelta(seconds=2),
        scheduler=scheduler,
        clock=lambda: NOW,
    ).run()

    assert scheduler.job_options == {
        "trigger": "interval",
        "seconds": 2.0,
        "id": "durable-job-process-cycle",
        "replace_existing": True,
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": 2,
        "next_run_time": NOW,
    }


def test_apscheduler_host_stops_and_surfaces_cycle_failure() -> None:
    class FailedWorker:
        def run_once(self):
            raise RuntimeError("private infrastructure detail")

    scheduler = HostScheduler()
    host = ApschedulerJobProcessHost(
        process=_process(worker=FailedWorker()),
        scheduler=scheduler,
    )

    with pytest.raises(RuntimeError, match="durable job process cycle failed"):
        host.run()

    assert scheduler.shutdown_wait is False


def test_apscheduler_host_latches_stop_before_scheduler_start() -> None:
    scheduler = HostScheduler(execute=False)
    host = ApschedulerJobProcessHost(
        process=_process(),
        scheduler=scheduler,
    )

    host.stop(wait=False)
    host.run()

    assert scheduler.job is None
    assert scheduler.running is False


@pytest.mark.parametrize(
    ("override", "expected"),
    (
        ({"process": object()}, TypeError),
        ({"tick_interval": timedelta(0)}, ValueError),
        ({"scheduler": object()}, TypeError),
        ({"clock": object()}, TypeError),
    ),
)
def test_apscheduler_host_rejects_partial_composition(override, expected) -> None:
    arguments = {
        "process": _process(),
        "scheduler": HostScheduler(execute=False),
    }
    arguments.update(override)
    with pytest.raises(expected):
        ApschedulerJobProcessHost(**arguments)


def test_capability_composer_builds_one_scoped_worker_without_database_io() -> None:
    database = _disconnected_control_database()
    first = Handler()
    second = Handler()
    try:
        process = build_durable_job_process(
            database=database,
            authority=Authority(),
            heartbeat_recorder=lambda _session, *, observed_at: None,
            retry_backoff_policy=BACKOFF,
            schedule_gate=Gate(),
            capabilities=(
                DurableJobCapability(
                    handlers={"first": first},
                    schedules=(_definition("first"),),
                ),
                DurableJobCapability(handlers={"second": second}),
                DurableJobCapability(
                    handlers={},
                    triggers=(
                        JobProcessTrigger(
                            name="cleanup",
                            interval=timedelta(minutes=1),
                            callback=lambda _now: None,
                        ),
                    ),
                ),
            ),
            worker_id="shared-worker",
            clock=lambda: NOW,
            allow_sqlite_claim_for_tests=True,
        )
    finally:
        database.dispose()

    assert process._worker._handlers == {"first": first, "second": second}
    assert process._worker._claim_job_types == {"first", "second"}
    assert [item.job_type for item in process._definitions] == ["first"]
    assert [item.name for item in process._triggers] == ["cleanup"]


def test_capability_composer_rejects_handler_overlap() -> None:
    database = _disconnected_control_database()
    capability = DurableJobCapability(
        handlers={"same": Handler()},
        schedules=(_definition("same"),),
    )
    try:
        with pytest.raises(ValueError, match="handler job types overlap"):
            build_durable_job_process(
                database=database,
                authority=Authority(),
                heartbeat_recorder=lambda _session, *, observed_at: None,
                retry_backoff_policy=BACKOFF,
                schedule_gate=Gate(),
                capabilities=(capability, capability),
                worker_id="shared-worker",
            )
    finally:
        database.dispose()


def test_capability_rejects_schedule_without_a_matching_handler() -> None:
    with pytest.raises(TypeError, match="schedules"):
        DurableJobCapability(
            handlers={"handler": Handler()},
            schedules=(_definition("different"),),
        )


def test_capability_rejects_empty_registration() -> None:
    with pytest.raises(ValueError, match="handler or trigger"):
        DurableJobCapability(handlers={})


def test_capability_authority_dispatches_by_job_type_and_fences_wrapper_reuse() -> None:
    authority = CapabilityJobAuthority(
        {
            "ordinary": NamedAuthority("ordinary_denied", allowed=False),
            "system": NamedAuthority("system", allowed=True),
        }
    )
    ordinary = SimpleNamespace(id="job-1", job_type="ordinary")
    system = SimpleNamespace(id="job-2", job_type="system")

    locked = authority.lock_current_job_authority(
        object(),
        job=ordinary,
        phase="claim",
    )
    verdict = authority.evaluate_locked_job_authority(
        object(),
        locked_authority=locked,
        job=ordinary,
        phase="claim",
        now=NOW,
    )

    assert not verdict.allowed
    assert verdict.reason_code == "ordinary_denied"
    with pytest.raises(RuntimeError, match="authority changed"):
        authority.evaluate_locked_job_authority(
            object(),
            locked_authority=locked,
            job=system,
            phase="claim",
            now=NOW,
        )


class Signals:
    SIGINT = 2
    SIGTERM = 15

    def __init__(self) -> None:
        self.handlers = {self.SIGINT: "old-int", self.SIGTERM: "old-term"}

    def getsignal(self, number):
        return self.handlers[number]

    def signal(self, number, handler):
        self.handlers[number] = handler


class SignalHost:
    def __init__(self, signals) -> None:
        self.signals = signals
        self.stop_calls = []

    def run(self):
        self.signals.handlers[self.signals.SIGTERM](self.signals.SIGTERM, None)

    def stop(self, *, wait):
        self.stop_calls.append(wait)


def test_signal_host_requests_nonblocking_stop_and_restores_handlers() -> None:
    signals = Signals()
    host = SignalHost(signals)

    SignalAwareJobProcessHost(host=host, signal_module=signals).run()

    assert host.stop_calls == [False]
    assert signals.handlers == {signals.SIGINT: "old-int", signals.SIGTERM: "old-term"}
