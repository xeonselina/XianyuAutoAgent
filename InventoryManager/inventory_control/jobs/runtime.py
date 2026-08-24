"""Independent durable worker orchestration.

The runtime deliberately owns the transaction boundaries around a handler.  A
handler may prepare an immutable provider request, but the runtime does not let
it execute that request until the control database has committed the
``provider_submitting`` boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Collection, Mapping, Protocol

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.database import ControlDatabase, read_database_utc_datetime
from inventory_control.models.jobs import BackgroundJob

from .contracts import AuthorityVerdict, JobAuthority
from .recovery_policy import RecoveryCategory, recovery_policy
from .service import ControlJobService, LeaseFenceViolation


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OutcomeDisposition(str, Enum):
    SUCCEEDED = "succeeded"
    RETRY = "retry"
    REVIEW = "review"
    RECOVERY_REVIEW = "recovery_review"


@dataclass(frozen=True, slots=True)
class JobOutcome:
    disposition: OutcomeDisposition
    safe_result: dict[str, Any] | None = None
    reason_code: str | None = None
    retry_at: datetime | None = None
    provider_proved_not_submitted: bool = False

    def __post_init__(self) -> None:
        disposition = OutcomeDisposition(self.disposition)
        object.__setattr__(self, "disposition", disposition)
        if self.safe_result is not None and not isinstance(self.safe_result, dict):
            raise ValueError("safe result must be a mapping")
        if self.reason_code is not None and (
            not isinstance(self.reason_code, str)
            or not self.reason_code
            or self.reason_code != self.reason_code.strip()
            or len(self.reason_code) > 64
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in self.reason_code
            )
        ):
            raise ValueError("reason code is invalid")
        if not isinstance(self.provider_proved_not_submitted, bool):
            raise ValueError("provider submission proof flag is invalid")
        if self.retry_at is not None and (
            not isinstance(self.retry_at, datetime)
            or self.retry_at.tzinfo is None
            or self.retry_at.utcoffset() is None
        ):
            raise ValueError("retry_at must be timezone-aware")
        if disposition is OutcomeDisposition.SUCCEEDED:
            if self.reason_code is not None or self.retry_at is not None:
                raise ValueError("successful outcome cannot contain failure fields")
        elif not self.reason_code:
            raise ValueError("non-success outcome requires a reason code")
        if disposition is not OutcomeDisposition.RETRY and self.retry_at is not None:
            raise ValueError("retry_at is valid only for a retry outcome")


@dataclass(frozen=True, slots=True)
class PreparedJob:
    """Opaque, handler-owned request prepared without provider I/O."""

    value: Any = None


class JobHandler(Protocol):
    """A handler split so the runtime can place the durable side-effect fence."""

    @property
    def crosses_provider_boundary(self) -> bool:
        ...

    @property
    def recovery_category(self) -> RecoveryCategory | None:
        ...

    def prepare(self, job: BackgroundJob) -> PreparedJob:
        ...

    def execute(self, job: BackgroundJob, prepared: PreparedJob) -> JobOutcome:
        ...


class WorkerHeartbeatRecorder(Protocol):
    def __call__(
        self,
        session: Session,
        *,
        observed_at: datetime,
    ) -> object:
        ...


@dataclass(frozen=True, slots=True)
class WorkerRunResult:
    state: str
    job_id: str | None = None
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class RetryBackoffPolicy:
    """Explicit retry delays shared by every durable-job capability.

    The delay at index zero follows the first failed attempt. Later failures
    advance through the schedule and remain capped at the final delay. Provider
    handlers may still return an exact ``retry_at`` (for example, a provider
    rate-limit deadline), which takes precedence over this infrastructure
    fallback.
    """

    delays: tuple[timedelta, ...]

    def __post_init__(self) -> None:
        selected = tuple(self.delays)
        if not selected or any(
            not isinstance(delay, timedelta) or delay <= timedelta(0)
            for delay in selected
        ):
            raise ValueError("retry backoff delays must be positive")
        if any(later < earlier for earlier, later in zip(selected, selected[1:])):
            raise ValueError("retry backoff delays must be nondecreasing")
        object.__setattr__(self, "delays", selected)

    def retry_at(self, *, attempts: int, now: datetime) -> datetime:
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
            raise ValueError("retry attempts must be positive")
        current = _as_utc(now)
        return current + self.delays[min(attempts - 1, len(self.delays) - 1)]


class DurableProviderCallAuthorizer:
    """Reusable short-transaction recheck for each provider request."""

    def __init__(
        self,
        *,
        database: ControlDatabase,
        authority: JobAuthority,
        lease_duration: timedelta = timedelta(minutes=2),
        clock: Callable[[], datetime] = _utc_now,
        service: ControlJobService | None = None,
    ) -> None:
        if not isinstance(database, ControlDatabase):
            raise TypeError("database must be a ControlDatabase")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self._database = database
        self._authority = authority
        self._lease_duration = lease_duration
        self._clock = clock
        self._service = service or ControlJobService()

    def authorize(self, job: BackgroundJob) -> AuthorityVerdict:
        if (
            not isinstance(job, BackgroundJob)
            or not job.lease_owner
            or not job.lease_token
            or job.execution_generation < 1
        ):
            raise ValueError("claimed provider job is invalid")
        with self._database.transaction() as session:
            return self._service.authorize_provider_call(
                session,
                job_id=job.id,
                worker_id=job.lease_owner,
                lease_token=job.lease_token,
                execution_generation=job.execution_generation,
                lease_duration=self._lease_duration,
                authority=self._authority,
                now=self._clock(),
            )


class DurableJobWorker:
    """Claim and execute at most one job using short control transactions."""

    def __init__(
        self,
        *,
        database: ControlDatabase,
        authority: JobAuthority,
        handlers: Mapping[str, JobHandler],
        heartbeat_recorder: WorkerHeartbeatRecorder,
        retry_backoff_policy: RetryBackoffPolicy,
        worker_id: str,
        lease_duration: timedelta = timedelta(minutes=2),
        clock: Callable[[], datetime] = _utc_now,
        claim_job_types: Collection[str] | None = None,
        service: ControlJobService | None = None,
    ) -> None:
        if not worker_id or len(worker_id) > 128:
            raise ValueError("worker_id is invalid")
        if not callable(heartbeat_recorder):
            raise TypeError("heartbeat_recorder is required")
        if not isinstance(retry_backoff_policy, RetryBackoffPolicy):
            raise TypeError("retry_backoff_policy is required")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self._database = database
        self._authority = authority
        self._handlers = dict(handlers)
        self._heartbeat_recorder = heartbeat_recorder
        self._retry_backoff_policy = retry_backoff_policy
        self._worker_id = worker_id
        self._lease_duration = lease_duration
        self._clock = clock
        if claim_job_types is None:
            self._claim_job_types = None
        else:
            if isinstance(claim_job_types, (str, bytes)):
                raise TypeError("claim_job_types must be a collection")
            selected_job_types = frozenset(claim_job_types)
            if not selected_job_types or not selected_job_types.issubset(
                self._handlers
            ):
                raise ValueError("claim_job_types must be a nonempty handler subset")
            self._claim_job_types = selected_job_types
        recovery_categories = {
            job_type: category
            for job_type, handler in self._handlers.items()
            if isinstance(
                category := getattr(handler, "recovery_category", None),
                RecoveryCategory,
            )
        }
        self._service = service or ControlJobService(
            recovery_categories=recovery_categories
        )
        if service is not None and any(
            not service.has_recovery_category(
                job_type=job_type,
                category=category,
            )
            for job_type, category in recovery_categories.items()
        ):
            raise TypeError("job service recovery policy composition is incomplete")

    def run_once(self) -> WorkerRunResult:
        result = self._run_once()
        with self._database.transaction() as session:
            heartbeat_at = read_database_utc_datetime(session)
            self._heartbeat_recorder(session, observed_at=heartbeat_at)
        return result

    def _run_once(self) -> WorkerRunResult:
        claimed = self._claim()
        if claimed is None:
            return WorkerRunResult("idle")

        job_id = claimed.id
        lease_token = claimed.lease_token
        generation = claimed.execution_generation
        attempts = claimed.attempts
        if lease_token is None:
            raise RuntimeError("claimed job is missing its lease token")

        handler = self._handlers.get(claimed.job_type)
        if handler is None:
            self._review(
                job_id=job_id,
                lease_token=lease_token,
                generation=generation,
                reason_code="handler_not_registered",
            )
            return WorkerRunResult("review", job_id, "handler_not_registered")

        denied = self._revalidate(
            job_id=job_id,
            lease_token=lease_token,
            generation=generation,
            phase="after_claim",
        )
        if denied is not None:
            return denied

        denied = self._revalidate(
            job_id=job_id,
            lease_token=lease_token,
            generation=generation,
            phase="before_tenant_context",
        )
        if denied is not None:
            return denied

        try:
            prepared = handler.prepare(claimed)
        except Exception:
            # Preparation is before the provider boundary, so an ordinary
            # bounded retry is safe.  Exception text is intentionally omitted.
            self._retry_job(
                job_id=job_id,
                lease_token=lease_token,
                generation=generation,
                attempts=attempts,
                reason_code="handler_prepare_failed",
            )
            return WorkerRunResult("retry", job_id, "handler_prepare_failed")

        crossed_boundary = bool(handler.crosses_provider_boundary)
        if crossed_boundary:
            denied = self._commit_provider_boundary(
                job_id=job_id,
                lease_token=lease_token,
                generation=generation,
            )
            if denied is not None:
                return denied

        try:
            outcome = handler.execute(claimed, prepared)
            if not isinstance(outcome, JobOutcome):
                raise TypeError("handler returned an invalid outcome")
        except Exception:
            if crossed_boundary and self._allows_safe_provider_retry(handler):
                self._retry_job(
                    job_id=job_id,
                    lease_token=lease_token,
                    generation=generation,
                    attempts=attempts,
                    reason_code="provider_result_unknown_safe_retry",
                )
                return WorkerRunResult(
                    "retry", job_id, "provider_result_unknown_safe_retry"
                )
            if crossed_boundary:
                self._review(
                    job_id=job_id,
                    lease_token=lease_token,
                    generation=generation,
                    reason_code="provider_result_unknown",
                )
                return WorkerRunResult("review", job_id, "provider_result_unknown")
            self._retry_job(
                job_id=job_id,
                lease_token=lease_token,
                generation=generation,
                attempts=attempts,
                reason_code="handler_execution_failed",
            )
            return WorkerRunResult("retry", job_id, "handler_execution_failed")

        if (
            crossed_boundary
            and outcome.disposition is OutcomeDisposition.RETRY
            and not outcome.provider_proved_not_submitted
            and not self._allows_safe_provider_retry(handler)
        ):
            outcome = JobOutcome(
                OutcomeDisposition.REVIEW,
                reason_code="provider_result_unknown",
            )
        return self._persist_outcome(
            job_id=job_id,
            lease_token=lease_token,
            generation=generation,
            attempts=attempts,
            outcome=outcome,
        )

    @staticmethod
    def _allows_safe_provider_retry(handler: JobHandler) -> bool:
        category = getattr(handler, "recovery_category", None)
        if not isinstance(category, RecoveryCategory):
            return False
        policy = recovery_policy(category)
        return (
            policy.automatic_resubmission_allowed
            and policy.immutable_snapshot_required
            and policy.stable_idempotency_required
        )

    def _claim(self) -> BackgroundJob | None:
        now = self._clock()
        with self._database.transaction() as session:
            if session.bind is not None and session.bind.dialect.name in {
                "mysql",
                "mariadb",
            }:
                return self._service.claim_mysql_skip_locked(
                    session,
                    worker_id=self._worker_id,
                    lease_duration=self._lease_duration,
                    authority=self._authority,
                    job_types=self._claim_job_types,
                    now=now,
                )
            raise RuntimeError("durable worker requires MySQL or MariaDB")

    def _load_leased(
        self,
        session: Session,
        *,
        job_id: str,
        lease_token: str,
        generation: int,
        now: datetime,
    ) -> BackgroundJob:
        # This is intentionally a non-locking snapshot.  The authority
        # implementation acquires the tenant/recovery/lifecycle locks first;
        # the fenced UPDATE then locks the job row last.  Locking the job here
        # would invert the required tenant-first order against a freeze.
        job = session.scalar(sa.select(BackgroundJob).where(BackgroundJob.id == job_id))
        if job is None:
            raise LeaseFenceViolation("job does not exist")
        if (
            job.status not in ("leased", "provider_submitting")
            or job.lease_owner != self._worker_id
            or job.lease_token != lease_token
            or job.execution_generation != generation
            or job.lease_expires_at is None
            or _as_utc(job.lease_expires_at) <= _as_utc(now)
        ):
            raise LeaseFenceViolation("job lease is stale")
        return job

    def _revalidate(
        self,
        *,
        job_id: str,
        lease_token: str,
        generation: int,
        phase: str,
    ) -> WorkerRunResult | None:
        now = self._clock()
        with self._database.transaction() as session:
            job = self._service.revalidate_or_block(
                session,
                job_id=job_id,
                worker_id=self._worker_id,
                lease_token=lease_token,
                execution_generation=generation,
                authority=self._authority,
                phase=phase,
                now=now,
            )
            if job.status == "leased":
                return None
            return WorkerRunResult(
                "blocked", job_id, job.blocked_reason_code or job.review_reason_code
            )

    def _commit_provider_boundary(
        self,
        *,
        job_id: str,
        lease_token: str,
        generation: int,
    ) -> WorkerRunResult | None:
        now = self._clock()
        with self._database.transaction() as session:
            job = self._service.begin_provider_submission(
                session,
                job_id=job_id,
                worker_id=self._worker_id,
                lease_token=lease_token,
                execution_generation=generation,
                authority=self._authority,
                now=now,
            )
            if job.status != "provider_submitting":
                return WorkerRunResult(
                    "blocked",
                    job_id,
                    job.blocked_reason_code or job.review_reason_code,
                )
        return None

    def _retry_job(
        self,
        *,
        job_id: str,
        lease_token: str,
        generation: int,
        attempts: int,
        reason_code: str,
    ) -> None:
        now = self._clock()
        with self._database.transaction() as session:
            self._service.fail(
                session,
                job_id=job_id,
                worker_id=self._worker_id,
                lease_token=lease_token,
                execution_generation=generation,
                error_code=reason_code,
                retryable=True,
                retry_at=self._next_retry_at(
                    attempts=attempts,
                    now=now,
                ),
                now=now,
            )

    def _review(
        self,
        *,
        job_id: str,
        lease_token: str,
        generation: int,
        reason_code: str,
        recovery: bool = False,
    ) -> None:
        now = self._clock()
        with self._database.transaction() as session:
            self._service.mark_review(
                session,
                job_id=job_id,
                worker_id=self._worker_id,
                lease_token=lease_token,
                execution_generation=generation,
                reason_code=reason_code,
                recovery=recovery,
                now=now,
            )

    def _persist_outcome(
        self,
        *,
        job_id: str,
        lease_token: str,
        generation: int,
        attempts: int,
        outcome: JobOutcome,
    ) -> WorkerRunResult:
        now = self._clock()
        with self._database.transaction() as session:
            if outcome.disposition is OutcomeDisposition.SUCCEEDED:
                self._service.complete(
                    session,
                    job_id=job_id,
                    worker_id=self._worker_id,
                    lease_token=lease_token,
                    execution_generation=generation,
                    result=outcome.safe_result,
                    now=now,
                )
                return WorkerRunResult("succeeded", job_id)
            if outcome.disposition is OutcomeDisposition.RETRY:
                self._service.fail(
                    session,
                    job_id=job_id,
                    worker_id=self._worker_id,
                    lease_token=lease_token,
                    execution_generation=generation,
                    error_code=outcome.reason_code or "retryable_failure",
                    retryable=True,
                    retry_at=self._next_retry_at(
                        attempts=attempts,
                        now=now,
                        provider_deadline=outcome.retry_at,
                    ),
                    now=now,
                )
                return WorkerRunResult("retry", job_id, outcome.reason_code)
            recovery = outcome.disposition is OutcomeDisposition.RECOVERY_REVIEW
            self._service.mark_review(
                session,
                job_id=job_id,
                worker_id=self._worker_id,
                lease_token=lease_token,
                execution_generation=generation,
                reason_code=outcome.reason_code or "review_required",
                recovery=recovery,
                now=now,
            )
            return WorkerRunResult("review", job_id, outcome.reason_code)

    def _next_retry_at(
        self,
        *,
        attempts: int,
        now: datetime,
        provider_deadline: datetime | None = None,
    ) -> datetime:
        current = _as_utc(now)
        fallback = self._retry_backoff_policy.retry_at(
            attempts=attempts,
            now=current,
        )
        if provider_deadline is None:
            return fallback
        selected = _as_utc(provider_deadline)
        return selected if selected > current else fallback


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
