"""Process-neutral loop for durable scheduling and job execution."""

from __future__ import annotations

import signal
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Protocol

from apscheduler.schedulers.blocking import BlockingScheduler

from inventory_control.database import ControlDatabase

from .contracts import JobAuthority
from .runtime import (
    DurableJobWorker,
    JobHandler,
    RetryBackoffPolicy,
    WorkerHeartbeatRecorder,
    WorkerRunResult,
)
from .scheduler import (
    FanOutResult,
    PeriodicJobDefinition,
    PeriodicTenantScheduler,
    TenantScheduleGate,
)


class PeriodicScheduler(Protocol):
    def fan_out(
        self,
        definition: PeriodicJobDefinition,
        *,
        now: datetime,
    ) -> FanOutResult:
        ...


class JobWorker(Protocol):
    def run_once(self) -> WorkerRunResult:
        ...


StopWaiter = Callable[[float], bool]


@dataclass(frozen=True, slots=True)
class JobProcessCycleResult:
    scheduled: tuple[FanOutResult, ...]
    triggered: tuple["JobProcessTriggerResult", ...]
    executed: tuple[WorkerRunResult, ...]
    worker_budget_exhausted: bool


@dataclass(frozen=True, slots=True)
class JobProcessTriggerResult:
    name: str
    ran: bool
    value: object = None


class JobProcessTrigger:
    """Run one capability producer at most once per current time bucket."""

    __slots__ = ("_callback", "_interval_microseconds", "_last_bucket", "name")

    def __init__(
        self,
        *,
        name: str,
        interval: timedelta,
        callback: Callable[[datetime], object],
    ) -> None:
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 96
            or any(ord(character) < 32 for character in name)
        ):
            raise ValueError("process trigger name is invalid")
        if not isinstance(interval, timedelta) or interval < timedelta(seconds=1):
            raise ValueError("process trigger interval must be at least one second")
        if not callable(callback):
            raise TypeError("process trigger callback must be callable")
        self.name = name
        self._interval_microseconds = interval // timedelta(microseconds=1)
        self._callback = callback
        self._last_bucket: int | None = None

    def run_due(self, *, now: datetime) -> JobProcessTriggerResult:
        current = _as_utc(now)
        epoch_microseconds = (
            current - datetime(1970, 1, 1, tzinfo=timezone.utc)
        ) // timedelta(microseconds=1)
        bucket = epoch_microseconds // self._interval_microseconds
        if bucket == self._last_bucket:
            return JobProcessTriggerResult(self.name, False)
        value = self._callback(current)
        # Mark the bucket only after the producer returns. An infrastructure
        # failure therefore terminates the host and remains immediately
        # retryable after supervisor restart.
        self._last_bucket = bucket
        return JobProcessTriggerResult(self.name, True, value)

    def __repr__(self) -> str:
        return f"JobProcessTrigger(name={self.name!r})"


@dataclass(frozen=True, slots=True)
class DurableJobCapability:
    """One capability's handlers and scheduler definitions."""

    handlers: Mapping[str, JobHandler]
    schedules: tuple[PeriodicJobDefinition, ...] = ()
    triggers: tuple[JobProcessTrigger, ...] = ()
    authority: JobAuthority | None = None

    def __post_init__(self) -> None:
        handlers = dict(self.handlers)
        schedules = tuple(self.schedules)
        triggers = tuple(self.triggers)
        if any(
            not isinstance(job_type, str)
            or not job_type
            or len(job_type) > 96
            or not callable(getattr(handler, "prepare", None))
            or not callable(getattr(handler, "execute", None))
            for job_type, handler in handlers.items()
        ):
            raise TypeError("capability handlers are invalid")
        if not handlers and not triggers:
            raise ValueError("capability must register a handler or trigger")
        if any(
            not isinstance(definition, PeriodicJobDefinition)
            or definition.job_type not in handlers
            for definition in schedules
        ):
            raise TypeError("capability schedules are invalid")
        if len({definition.job_type for definition in schedules}) != len(schedules):
            raise ValueError("capability schedule job types must be unique")
        if any(not isinstance(trigger, JobProcessTrigger) for trigger in triggers):
            raise TypeError("capability triggers are invalid")
        if len({trigger.name for trigger in triggers}) != len(triggers):
            raise ValueError("capability trigger names must be unique")
        if self.authority is not None and not _implements_authority(self.authority):
            raise TypeError("capability authority must implement JobAuthority")
        object.__setattr__(self, "handlers", MappingProxyType(handlers))
        object.__setattr__(self, "schedules", schedules)
        object.__setattr__(self, "triggers", triggers)


@dataclass(frozen=True, slots=True)
class LockedCapabilityJobAuthority:
    job_type: str
    delegate: JobAuthority
    value: object


class CapabilityJobAuthority:
    """Dispatch current-authority locks by the claimed durable job type."""

    def __init__(self, authorities: Mapping[str, JobAuthority]) -> None:
        selected = dict(authorities)
        if not selected or any(
            not isinstance(job_type, str)
            or not job_type
            or not _implements_authority(authority)
            for job_type, authority in selected.items()
        ):
            raise TypeError("capability authority registry is invalid")
        self._authorities = MappingProxyType(selected)

    def lock_current_job_authority(self, session, *, job, phase):
        authority = self._authorities.get(getattr(job, "job_type", None))
        if authority is None:
            raise RuntimeError("job capability authority is unavailable")
        return LockedCapabilityJobAuthority(
            job_type=job.job_type,
            delegate=authority,
            value=authority.lock_current_job_authority(
                session,
                job=job,
                phase=phase,
            ),
        )

    def evaluate_locked_job_authority(
        self,
        session,
        *,
        locked_authority,
        job,
        phase,
        now,
    ):
        if (
            not isinstance(locked_authority, LockedCapabilityJobAuthority)
            or locked_authority.job_type != getattr(job, "job_type", None)
            or self._authorities.get(locked_authority.job_type)
            is not locked_authority.delegate
        ):
            raise RuntimeError("job capability authority changed")
        return locked_authority.delegate.evaluate_locked_job_authority(
            session,
            locked_authority=locked_authority.value,
            job=job,
            phase=phase,
            now=now,
        )

    def __repr__(self) -> str:
        return f"CapabilityJobAuthority(job_type_count={len(self._authorities)})"


class DurableJobProcess:
    """Drive scheduler fan-out and bounded queue draining in one process.

    This class deliberately does not parse configuration, install signal
    handlers, daemonize, or own database/provider resources.  A host launcher
    supplies those dependencies and a signal-aware ``wait_for_stop`` callable.
    Unexpected scheduler, database, or worker failures propagate so the
    process supervisor can restart the process instead of leaving a half-live
    scheduler behind.
    """

    def __init__(
        self,
        *,
        scheduler: PeriodicScheduler,
        definitions: Iterable[PeriodicJobDefinition],
        triggers: Iterable[JobProcessTrigger] = (),
        worker: JobWorker,
        max_jobs_per_cycle: int = 100,
        idle_poll_interval: timedelta = timedelta(seconds=1),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(getattr(scheduler, "fan_out", None)):
            raise TypeError("scheduler must implement fan_out")
        if not callable(getattr(worker, "run_once", None)):
            raise TypeError("worker must implement run_once")
        selected_definitions = tuple(definitions)
        if any(
            not isinstance(definition, PeriodicJobDefinition)
            for definition in selected_definitions
        ):
            raise TypeError("definitions must contain periodic job definitions")
        selected_triggers = tuple(triggers)
        if any(
            not isinstance(trigger, JobProcessTrigger) for trigger in selected_triggers
        ):
            raise TypeError("triggers must contain process triggers")
        if not selected_definitions and not selected_triggers:
            raise ValueError("at least one schedule or trigger is required")
        if (
            isinstance(max_jobs_per_cycle, bool)
            or not isinstance(max_jobs_per_cycle, int)
            or max_jobs_per_cycle < 1
        ):
            raise ValueError("max_jobs_per_cycle must be positive")
        if not isinstance(idle_poll_interval, timedelta) or (
            idle_poll_interval < timedelta(milliseconds=10)
        ):
            raise ValueError("idle_poll_interval must be at least 10 milliseconds")
        selected_clock = clock or _utc_now
        if not callable(selected_clock):
            raise TypeError("clock must be callable")

        self._scheduler = scheduler
        self._definitions = selected_definitions
        self._triggers = selected_triggers
        self._worker = worker
        self._max_jobs_per_cycle = max_jobs_per_cycle
        self._idle_poll_seconds = idle_poll_interval.total_seconds()
        self._clock = selected_clock

    def run_cycle(self) -> JobProcessCycleResult:
        now = _as_utc(self._clock())
        scheduled = tuple(
            self._validated_fan_out(definition, now=now)
            for definition in self._definitions
        )
        triggered = tuple(trigger.run_due(now=now) for trigger in self._triggers)

        executed: list[WorkerRunResult] = []
        for _ in range(self._max_jobs_per_cycle):
            result = self._worker.run_once()
            if not isinstance(result, WorkerRunResult):
                raise TypeError("worker returned an invalid result")
            executed.append(result)
            if result.state == "idle":
                break

        return JobProcessCycleResult(
            scheduled=scheduled,
            triggered=triggered,
            executed=tuple(executed),
            worker_budget_exhausted=(
                len(executed) == self._max_jobs_per_cycle
                and executed[-1].state != "idle"
            ),
        )

    def run_forever(self, *, wait_for_stop: StopWaiter) -> int:
        """Run until ``wait_for_stop`` reports a requested shutdown.

        The waiter receives zero while work remains and the configured idle
        poll duration after the worker observes an empty queue.  It can be a
        ``threading.Event.wait`` method, which makes shutdown interruptible
        without embedding OS signal policy in this reusable runtime.
        """

        if not callable(wait_for_stop):
            raise TypeError("wait_for_stop must be callable")
        cycles = 0
        while not wait_for_stop(0):
            result = self.run_cycle()
            cycles += 1
            delay = 0.0 if result.worker_budget_exhausted else self._idle_poll_seconds
            if wait_for_stop(delay):
                break
        return cycles

    def _validated_fan_out(
        self,
        definition: PeriodicJobDefinition,
        *,
        now: datetime,
    ) -> FanOutResult:
        result = self._scheduler.fan_out(definition, now=now)
        if not isinstance(result, FanOutResult):
            raise TypeError("scheduler returned an invalid result")
        return result


class ApschedulerJobProcessHost:
    """Run one durable-job cycle from a single blocking APScheduler host."""

    def __init__(
        self,
        *,
        process: DurableJobProcess,
        tick_interval: timedelta = timedelta(seconds=1),
        scheduler: BlockingScheduler | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(process, DurableJobProcess):
            raise TypeError("process must be a DurableJobProcess")
        if not isinstance(tick_interval, timedelta) or (
            tick_interval < timedelta(milliseconds=100)
        ):
            raise ValueError("tick_interval must be at least 100 milliseconds")
        if scheduler is not None and not all(
            callable(getattr(scheduler, method, None))
            for method in ("add_job", "start", "shutdown")
        ):
            raise TypeError("scheduler has an invalid host interface")
        selected_clock = clock or _utc_now
        if not callable(selected_clock):
            raise TypeError("clock must be callable")

        self._process = process
        self._tick_seconds = tick_interval.total_seconds()
        self._scheduler = scheduler or BlockingScheduler(timezone=timezone.utc)
        self._clock = selected_clock
        self._failure: RuntimeError | None = None
        self._stop_requested = Event()

    def run(self) -> None:
        self._failure = None
        if self._stop_requested.is_set():
            return
        self._scheduler.add_job(
            self._run_cycle,
            trigger="interval",
            seconds=self._tick_seconds,
            id="durable-job-process-cycle",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=max(1, int(self._tick_seconds)),
            next_run_time=_as_utc(self._clock()),
        )
        if self._stop_requested.is_set():
            return
        self._scheduler.start()
        if self._failure is not None:
            raise self._failure

    def stop(self, *, wait: bool = False) -> None:
        # Latch the request even when a signal arrives in the small interval
        # between installing handlers and starting APScheduler.
        self._stop_requested.set()
        if bool(getattr(self._scheduler, "running", False)):
            self._scheduler.shutdown(wait=wait)

    def _run_cycle(self) -> None:
        try:
            self._process.run_cycle()
        except Exception:
            # APScheduler normally logs a job exception and keeps running. A
            # durable worker must instead terminate so its supervisor can
            # restart the complete scheduler+worker process.
            self._failure = RuntimeError("durable job process cycle failed")
            self.stop(wait=False)


class SignalAwareJobProcessHost:
    """Install process-local SIGINT/SIGTERM shutdown around one job host."""

    def __init__(
        self,
        *,
        host: ApschedulerJobProcessHost,
        signal_module=signal,
    ) -> None:
        if not callable(getattr(host, "run", None)) or not callable(
            getattr(host, "stop", None)
        ):
            raise TypeError("host has an invalid process interface")
        if not all(
            hasattr(signal_module, name)
            for name in ("SIGINT", "SIGTERM", "getsignal", "signal")
        ):
            raise TypeError("signal module has an invalid interface")
        self._host = host
        self._signals = signal_module

    def run(self) -> None:
        selected = (self._signals.SIGINT, self._signals.SIGTERM)
        previous = {number: self._signals.getsignal(number) for number in selected}

        def request_stop(_number, _frame):
            self._host.stop(wait=False)

        try:
            for number in selected:
                self._signals.signal(number, request_stop)
            self._host.run()
        finally:
            for number, handler in previous.items():
                self._signals.signal(number, handler)


def build_durable_job_process(
    *,
    database: ControlDatabase,
    authority: JobAuthority,
    heartbeat_recorder: WorkerHeartbeatRecorder,
    retry_backoff_policy: RetryBackoffPolicy,
    schedule_gate: TenantScheduleGate,
    capabilities: Iterable[DurableJobCapability],
    worker_id: str,
    lease_duration: timedelta = timedelta(minutes=2),
    max_jobs_per_cycle: int = 100,
    idle_poll_interval: timedelta = timedelta(seconds=1),
    clock: Callable[[], datetime] | None = None,
) -> DurableJobProcess:
    """Merge capability registrations into one scheduler and one worker."""

    if not isinstance(database, ControlDatabase):
        raise TypeError("database must be a ControlDatabase")
    if not _implements_authority(authority):
        raise TypeError("authority must implement JobAuthority")
    if not callable(heartbeat_recorder):
        raise TypeError("heartbeat_recorder is required")
    if not isinstance(retry_backoff_policy, RetryBackoffPolicy):
        raise TypeError("retry_backoff_policy is required")
    if not callable(getattr(schedule_gate, "evaluate", None)):
        raise TypeError("schedule_gate must implement TenantScheduleGate")
    selected_capabilities = tuple(capabilities)
    if not selected_capabilities or any(
        not isinstance(capability, DurableJobCapability)
        for capability in selected_capabilities
    ):
        raise TypeError("capabilities must contain durable job capabilities")

    handlers: dict[str, JobHandler] = {}
    authorities: dict[str, JobAuthority] = {}
    definitions: list[PeriodicJobDefinition] = []
    triggers: list[JobProcessTrigger] = []
    trigger_names: set[str] = set()
    scheduled_types: set[str] = set()
    for capability in selected_capabilities:
        overlap = handlers.keys() & capability.handlers.keys()
        if overlap:
            raise ValueError("capability handler job types overlap")
        handlers.update(capability.handlers)
        selected_authority = capability.authority or authority
        authorities.update(
            (job_type, selected_authority) for job_type in capability.handlers
        )
        for definition in capability.schedules:
            if definition.job_type in scheduled_types:
                raise ValueError("capability schedule job types overlap")
            scheduled_types.add(definition.job_type)
            definitions.append(definition)
        for trigger in capability.triggers:
            if trigger.name in trigger_names:
                raise ValueError("capability trigger names overlap")
            trigger_names.add(trigger.name)
            triggers.append(trigger)
    if not handlers:
        raise ValueError("at least one capability handler is required")
    if not definitions and not triggers:
        raise ValueError("at least one schedule or trigger is required")

    selected_clock = clock or _utc_now
    worker_authority = CapabilityJobAuthority(authorities)
    worker = DurableJobWorker(
        database=database,
        authority=worker_authority,
        handlers=handlers,
        heartbeat_recorder=heartbeat_recorder,
        retry_backoff_policy=retry_backoff_policy,
        worker_id=worker_id,
        lease_duration=lease_duration,
        clock=selected_clock,
        claim_job_types=handlers.keys(),
    )
    return DurableJobProcess(
        scheduler=PeriodicTenantScheduler(database=database, gate=schedule_gate),
        definitions=definitions,
        triggers=triggers,
        worker=worker,
        max_jobs_per_cycle=max_jobs_per_cycle,
        idle_poll_interval=idle_poll_interval,
        clock=selected_clock,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("clock must return a datetime")
    if value.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _implements_authority(value: object) -> bool:
    return callable(getattr(value, "lock_current_job_authority", None)) and callable(
        getattr(value, "evaluate_locked_job_authority", None)
    )


__all__ = [
    "ApschedulerJobProcessHost",
    "CapabilityJobAuthority",
    "DurableJobCapability",
    "DurableJobProcess",
    "JobProcessCycleResult",
    "JobProcessTrigger",
    "JobProcessTriggerResult",
    "LockedCapabilityJobAuthority",
    "SignalAwareJobProcessHost",
    "StopWaiter",
    "build_durable_job_process",
]
