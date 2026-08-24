"""Minimal durable job transitions with explicit lease fencing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from types import MappingProxyType
from typing import Any, Callable, Collection, Mapping
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from inventory_control.database import read_database_utc_datetime
from inventory_control.models.jobs import BackgroundJob, ControlOutboxEvent

from .contracts import AuthorityVerdict, JobAuthority
from .recovery_policy import RecoveryCategory, recovery_policy


class LeaseFenceViolation(RuntimeError):
    """The caller no longer owns the current persisted execution lease."""


class InvalidJobTransition(RuntimeError):
    """The requested state transition is not valid from the persisted state."""


class JobIdempotencyConflict(InvalidJobTransition):
    """A stable job identity was replayed with different immutable facts."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _same_optional_time(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return left is right
    return _as_utc(left) == _as_utc(right)


def _optional_uuid(value: object) -> str | None:
    if value is None:
        return None
    try:
        selected = str(UUID(str(value)))
    except (TypeError, ValueError):
        raise ValueError("job_id is invalid") from None
    if UUID(selected).int == 0:
        raise ValueError("job_id is invalid")
    return selected


def _claim_job_types(
    values: Collection[str] | None,
) -> tuple[str, ...] | None:
    if values is None:
        return None
    if isinstance(values, (str, bytes)):
        raise ValueError("claim job types are invalid")
    try:
        selected = set(values)
    except TypeError:
        raise ValueError("claim job types are invalid") from None
    if not selected or any(
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or any(ord(character) < 32 for character in value)
        for value in selected
    ):
        raise ValueError("claim job types are invalid")
    return tuple(sorted(selected))


class ControlJobService:
    """Queue operations that participate in the caller-owned transaction."""

    def __init__(
        self,
        *,
        database_clock: Callable[[Session], datetime] | None = None,
        recovery_categories: Mapping[str, RecoveryCategory] | None = None,
    ) -> None:
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        categories = dict(recovery_categories or {})
        if any(
            not isinstance(job_type, str)
            or not job_type
            or not isinstance(category, RecoveryCategory)
            for job_type, category in categories.items()
        ):
            raise TypeError("job recovery category registry is invalid")
        self._database_clock = database_clock or read_database_utc_datetime
        self._recovery_categories = MappingProxyType(categories)

    def has_recovery_category(
        self,
        *,
        job_type: str,
        category: RecoveryCategory,
    ) -> bool:
        return self._recovery_categories.get(job_type) is category

    def enqueue_job(
        self,
        session: Session,
        *,
        tenant_id: str,
        tenant_access_version: int,
        job_type: str,
        resource_key: str,
        payload: dict[str, Any],
        idempotency_key: str,
        requested_by_type: str,
        requested_by_id: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        job_id: str | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        available_at: datetime | None = None,
        not_after: datetime | None = None,
    ) -> BackgroundJob:
        available_at = available_at or _utc_now()
        if not_after is not None and _as_utc(not_after) < _as_utc(available_at):
            raise ValueError("not_after must not precede available_at")
        if tenant_access_version < 1:
            raise ValueError("tenant_access_version must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if priority < 0:
            raise ValueError("priority must be nonnegative")
        selected_job_id = _optional_uuid(job_id)

        lookup = (
            sa.select(BackgroundJob)
            .where(
                BackgroundJob.tenant_id == tenant_id,
                BackgroundJob.job_type == job_type,
                BackgroundJob.resource_key == resource_key,
                BackgroundJob.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )
        existing = session.scalar(lookup)
        if existing is not None:
            self._require_exact_job_replay(
                existing,
                tenant_access_version=tenant_access_version,
                payload=payload,
                requested_by_type=requested_by_type,
                requested_by_id=requested_by_id,
                max_attempts=max_attempts,
                not_after=not_after,
                job_id=selected_job_id,
            )
            return self.promote_pending_job(
                session,
                job_id=existing.id,
                priority=priority,
                available_at=available_at,
                now=available_at,
            )

        job_values = {
            "tenant_id": tenant_id,
            "tenant_access_version": tenant_access_version,
            "job_type": job_type,
            "resource_key": resource_key,
            "payload": payload,
            "idempotency_key": idempotency_key,
            "requested_by_type": requested_by_type,
            "requested_by_id": requested_by_id,
            "request_id": request_id,
            "correlation_id": correlation_id,
            "priority": priority,
            "max_attempts": max_attempts,
            "available_at": available_at,
            "not_after": not_after,
        }
        if selected_job_id is not None:
            job_values["id"] = selected_job_id
        job = BackgroundJob(
            **job_values,
        )
        try:
            with session.begin_nested():
                session.add(job)
                session.flush()
        except IntegrityError:
            existing = session.scalar(lookup)
            if existing is None:
                raise
            self._require_exact_job_replay(
                existing,
                tenant_access_version=tenant_access_version,
                payload=payload,
                requested_by_type=requested_by_type,
                requested_by_id=requested_by_id,
                max_attempts=max_attempts,
                not_after=not_after,
                job_id=selected_job_id,
            )
            return self.promote_pending_job(
                session,
                job_id=existing.id,
                priority=priority,
                available_at=available_at,
                now=available_at,
            )
        return job

    @staticmethod
    def _require_exact_job_replay(
        job: BackgroundJob,
        *,
        tenant_access_version: int,
        payload: dict[str, Any],
        requested_by_type: str,
        requested_by_id: str | None,
        max_attempts: int,
        not_after: datetime | None,
        job_id: str | None,
    ) -> None:
        if (
            (job_id is not None and job.id != job_id)
            or job.tenant_access_version != tenant_access_version
            or job.payload != payload
            or job.requested_by_type != requested_by_type
            or job.requested_by_id != requested_by_id
            or job.max_attempts != max_attempts
            or not _same_optional_time(job.not_after, not_after)
        ):
            raise JobIdempotencyConflict(
                "job idempotency identity conflicts with immutable facts"
            )

    def promote_pending_job(
        self,
        session: Session,
        *,
        job_id: str,
        priority: int,
        available_at: datetime,
        now: datetime | None = None,
    ) -> BackgroundJob:
        """Move existing coalesced work forward without changing its identity.

        Only an unclaimed pending row can be promoted. The immutable payload,
        idempotency key, requester and attempt budget remain untouched; leased
        or terminal work is returned unchanged because it is already executing
        or has a durable outcome.
        """

        if (
            not isinstance(job_id, str)
            or not job_id
            or isinstance(priority, bool)
            or not isinstance(priority, int)
            or priority < 0
            or not isinstance(available_at, datetime)
        ):
            raise ValueError("pending job promotion is invalid")
        job = session.scalar(
            sa.select(BackgroundJob)
            .where(BackgroundJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None:
            raise InvalidJobTransition("job does not exist")
        if job.status != "pending":
            return job

        selected_available_at = _as_utc(available_at)
        changed = False
        if priority > job.priority:
            job.priority = priority
            changed = True
        if selected_available_at < _as_utc(job.available_at):
            job.available_at = selected_available_at
            changed = True
        if changed:
            job.updated_at = self._database_now(session, test_now=now)
            session.flush()
        return job

    def enqueue_outbox(
        self,
        session: Session,
        *,
        source_type: str,
        source_uuid: str,
        source_generation: int,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        tenant_id: str | None = None,
        tenant_access_version: int | None = None,
        max_attempts: int = 10,
        available_at: datetime | None = None,
        not_after: datetime | None = None,
    ) -> ControlOutboxEvent:
        available_at = available_at or _utc_now()
        if not_after is not None and _as_utc(not_after) < _as_utc(available_at):
            raise ValueError("not_after must not precede available_at")
        if source_generation < 1:
            raise ValueError("source_generation must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")

        lookup = sa.select(ControlOutboxEvent).where(
            ControlOutboxEvent.source_type == source_type,
            ControlOutboxEvent.source_uuid == source_uuid,
            ControlOutboxEvent.source_generation == source_generation,
            ControlOutboxEvent.event_type == event_type,
            ControlOutboxEvent.idempotency_key == idempotency_key,
        )
        existing = session.scalar(lookup)
        if existing is not None:
            return existing

        event = ControlOutboxEvent(
            tenant_id=tenant_id,
            tenant_access_version=tenant_access_version,
            source_type=source_type,
            source_uuid=source_uuid,
            source_generation=source_generation,
            event_type=event_type,
            payload=payload,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
            available_at=available_at,
            not_after=not_after,
        )
        try:
            with session.begin_nested():
                session.add(event)
                session.flush()
        except IntegrityError:
            existing = session.scalar(lookup)
            if existing is None:
                raise
            return existing
        return event

    def claim_mysql_skip_locked(
        self,
        session: Session,
        *,
        worker_id: str,
        lease_duration: timedelta,
        authority: JobAuthority,
        job_types: Collection[str] | None = None,
        now: datetime | None = None,
    ) -> BackgroundJob | None:
        """Claim one due job with a MySQL 8 ``FOR UPDATE SKIP LOCKED`` lease.

        The caller owns the surrounding transaction.  A provider call must
        never be made until that transaction has committed.
        """

        if session.bind is None or session.bind.dialect.name not in {
            "mysql",
            "mariadb",
        }:
            raise RuntimeError("claim_mysql_skip_locked requires MySQL or MariaDB")
        return self._claim(
            session,
            worker_id=worker_id,
            lease_duration=lease_duration,
            authority=authority,
            job_types=job_types,
            now=now,
        )

    def _claim(
        self,
        session: Session,
        *,
        worker_id: str,
        lease_duration: timedelta,
        authority: JobAuthority,
        job_types: Collection[str] | None,
        now: datetime | None,
    ) -> BackgroundJob | None:
        if (
            not isinstance(worker_id, str)
            or not worker_id
            or len(worker_id) > 128
            or any(ord(character) < 32 for character in worker_id)
        ):
            raise ValueError("worker_id is invalid")
        if not isinstance(lease_duration, timedelta) or lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self._require_authority(authority)
        claim_job_types = _claim_job_types(job_types)

        discovery_time = self._database_now(session, test_now=now)
        snapshot = session.scalar(
            self._claim_candidate_statement(
                now=discovery_time,
                job_types=claim_job_types,
            )
        )
        if snapshot is None:
            return None

        locked_authority = authority.lock_current_job_authority(
            session,
            job=snapshot,
            phase="claim",
        )
        candidate = session.scalar(
            sa.select(BackgroundJob)
            .where(BackgroundJob.id == snapshot.id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if candidate is None:
            return None
        current_time = self._database_now(session, test_now=now)
        action = self._claim_action(candidate, now=current_time)
        if action is None:
            return None
        if action == "provider_review":
            if not self._allows_automatic_provider_retry(
                candidate,
                now=current_time,
            ):
                self._finish_locked_job(
                    candidate,
                    status="needs_review",
                    reason_code="provider_result_unknown",
                    now=current_time,
                )
                session.flush()
                return None
            action = "claim"
        if action == "deadline_review":
            self._finish_locked_job(
                candidate,
                status="needs_review",
                reason_code="not_after_expired",
                now=current_time,
            )
            session.flush()
            return None
        if action == "dead_letter":
            self._finish_locked_job(
                candidate,
                status="dead_letter",
                reason_code="attempts_exhausted",
                now=current_time,
            )
            session.flush()
            return None

        verdict = self._evaluate_authority(
            authority,
            session,
            locked_authority=locked_authority,
            job=candidate,
            phase="claim",
            now=current_time,
        )
        if not verdict.allowed:
            self._block_locked_job(candidate, verdict=verdict, now=current_time)
            session.flush()
            return None

        candidate.status = "leased"
        candidate.attempts += 1
        candidate.execution_generation += 1
        candidate.lease_owner = worker_id
        candidate.lease_token = token_urlsafe(32)
        candidate.lease_expires_at = current_time + lease_duration
        candidate.last_heartbeat_at = current_time
        candidate.started_at = candidate.started_at or current_time
        candidate.updated_at = current_time
        session.flush()
        return candidate

    def _allows_automatic_provider_retry(
        self,
        job: BackgroundJob,
        *,
        now: datetime,
    ) -> bool:
        category = self._recovery_categories.get(job.job_type)
        if category is None:
            return False
        policy = recovery_policy(category)
        return (
            policy.automatic_resubmission_allowed
            and policy.immutable_snapshot_required
            and policy.stable_idempotency_required
            and bool(job.payload)
            and bool(job.idempotency_key)
            and job.attempts < job.max_attempts
            and (job.not_after is None or _as_utc(job.not_after) >= _as_utc(now))
        )

    @staticmethod
    def _claim_candidate_statement(
        *,
        now: datetime,
        job_types: tuple[str, ...] | None = None,
    ) -> Any:
        """Read one candidate identity without acquiring the job-row lock."""

        filters: list[Any] = [
            sa.or_(
                sa.and_(
                    BackgroundJob.status == "pending",
                    sa.or_(
                        BackgroundJob.available_at <= now,
                        BackgroundJob.not_after < now,
                        BackgroundJob.attempts >= BackgroundJob.max_attempts,
                    ),
                ),
                sa.and_(
                    BackgroundJob.status == "leased",
                    sa.or_(
                        BackgroundJob.lease_expires_at <= now,
                        BackgroundJob.not_after < now,
                    ),
                ),
                sa.and_(
                    BackgroundJob.status == "provider_submitting",
                    BackgroundJob.lease_expires_at <= now,
                ),
            )
        ]
        if job_types is not None:
            filters.append(BackgroundJob.job_type.in_(job_types))
        return (
            sa.select(BackgroundJob)
            .where(*filters)
            .order_by(
                BackgroundJob.priority.desc(),
                BackgroundJob.available_at.asc(),
                BackgroundJob.created_at.asc(),
                BackgroundJob.id.asc(),
            )
            .limit(1)
        )

    # Compatibility alias retained for existing dialect-level callers.  The
    # statement is deliberately non-locking; the exact row is locked only
    # after current tenant authority has been acquired.
    _mysql_claim_candidate_statement = _claim_candidate_statement

    def heartbeat(
        self,
        session: Session,
        *,
        job_id: str,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        lease_duration: timedelta,
        authority: JobAuthority,
        now: datetime | None = None,
    ) -> BackgroundJob:
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        job, current_time, verdict = self._lock_authorized_job(
            session,
            job_id=job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            execution_generation=execution_generation,
            allowed_statuses=("leased", "provider_submitting"),
            authority=authority,
            phase="heartbeat",
            test_now=now,
        )
        if not verdict.allowed:
            self._block_locked_job(job, verdict=verdict, now=current_time)
        else:
            job.lease_expires_at = current_time + lease_duration
            job.last_heartbeat_at = current_time
            job.updated_at = current_time
        session.flush()
        return job

    def begin_provider_submission(
        self,
        session: Session,
        *,
        job_id: str,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        authority: JobAuthority,
        now: datetime | None = None,
    ) -> BackgroundJob:
        """Persist the side-effect boundary before the network call starts."""

        job, current_time, verdict = self._lock_authorized_job(
            session,
            job_id=job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            execution_generation=execution_generation,
            allowed_statuses=("leased",),
            authority=authority,
            phase="before_provider_boundary",
            test_now=now,
        )
        if not verdict.allowed:
            self._block_locked_job(job, verdict=verdict, now=current_time)
        else:
            job.status = "provider_submitting"
            job.updated_at = current_time
        session.flush()
        return job

    def revalidate_or_block(
        self,
        session: Session,
        *,
        job_id: str,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        authority: JobAuthority,
        phase: str,
        now: datetime | None = None,
    ) -> BackgroundJob:
        job, current_time, verdict = self._lock_authorized_job(
            session,
            job_id=job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            execution_generation=execution_generation,
            allowed_statuses=("leased",),
            authority=authority,
            phase=phase,
            test_now=now,
        )
        if not verdict.allowed:
            self._block_locked_job(job, verdict=verdict, now=current_time)
            session.flush()
        return job

    def authorize_provider_call(
        self,
        session: Session,
        *,
        job_id: str,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        lease_duration: timedelta,
        authority: JobAuthority,
        now: datetime | None = None,
    ) -> AuthorityVerdict:
        """Recheck current authority and renew the lease before one call.

        A multi-call handler invokes this immediately before every provider
        request.  Denial is returned without finishing the job so the handler
        can persist already obtained independent results and choose the
        correct review outcome.
        """

        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        job, current_time, verdict = self._lock_authorized_job(
            session,
            job_id=job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            execution_generation=execution_generation,
            allowed_statuses=("provider_submitting",),
            authority=authority,
            phase="before_provider_call",
            test_now=now,
        )
        if verdict.allowed:
            job.lease_expires_at = current_time + lease_duration
            job.last_heartbeat_at = current_time
            job.updated_at = current_time
            session.flush()
        return verdict

    def block_for_gate(
        self,
        session: Session,
        *,
        job_id: str,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        reason_code: str,
        recovery: bool = False,
        now: datetime | None = None,
    ) -> BackgroundJob:
        """Finish a leased job without invoking a tenant/provider side effect."""

        if not isinstance(reason_code, str) or not reason_code or len(reason_code) > 64:
            raise ValueError("reason_code is invalid")
        status = (
            "recovery_review"
            if recovery
            else (
                "suspension_blocked"
                if reason_code == "tenant_suspended"
                else "needs_review"
            )
        )
        job, current_time = self._lock_fenced_job(
            session,
            job_id=job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            execution_generation=execution_generation,
            allowed_statuses=("leased",),
            test_now=now,
        )
        self._finish_locked_job(
            job,
            status=status,
            reason_code=reason_code,
            now=current_time,
        )
        session.flush()
        return job

    def complete(
        self,
        session: Session,
        *,
        job_id: str,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        result: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> BackgroundJob:
        job, current_time = self._lock_fenced_job(
            session,
            job_id=job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            execution_generation=execution_generation,
            allowed_statuses=("leased", "provider_submitting"),
            test_now=now,
        )
        job.status = "succeeded"
        job.result = result
        job.lease_owner = None
        job.lease_token = None
        job.lease_expires_at = None
        job.completed_at = current_time
        job.updated_at = current_time
        session.flush()
        return job

    def fail(
        self,
        session: Session,
        *,
        job_id: str,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        error_code: str,
        retryable: bool,
        retry_at: datetime | None = None,
        now: datetime | None = None,
    ) -> BackgroundJob:
        job, current_time = self._lock_fenced_job(
            session,
            job_id=job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            execution_generation=execution_generation,
            allowed_statuses=("leased", "provider_submitting"),
            test_now=now,
        )
        can_retry = (
            retryable
            and job.attempts < job.max_attempts
            and (
                job.not_after is None
                or _as_utc(job.not_after) >= _as_utc(retry_at or current_time)
            )
        )
        job.status = "pending" if can_retry else "dead_letter"
        job.last_error_code = error_code
        job.lease_owner = None
        job.lease_token = None
        job.lease_expires_at = None
        job.updated_at = current_time
        if can_retry:
            job.available_at = retry_at or current_time
        else:
            job.completed_at = current_time
        session.flush()
        return job

    def mark_review(
        self,
        session: Session,
        *,
        job_id: str,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        reason_code: str,
        recovery: bool = False,
        now: datetime | None = None,
    ) -> BackgroundJob:
        job, current_time = self._lock_fenced_job(
            session,
            job_id=job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            execution_generation=execution_generation,
            allowed_statuses=("leased", "provider_submitting"),
            test_now=now,
        )
        self._finish_locked_job(
            job,
            status="recovery_review" if recovery else "needs_review",
            reason_code=reason_code,
            now=current_time,
        )
        session.flush()
        return job

    @staticmethod
    def _require_authority(authority: JobAuthority) -> None:
        if not callable(getattr(authority, "lock_current_job_authority", None)):
            raise TypeError("authority must lock current job authority")
        if not callable(getattr(authority, "evaluate_locked_job_authority", None)):
            raise TypeError("authority must evaluate locked job authority")

    def _database_now(
        self,
        session: Session,
        *,
        test_now: datetime | None,
    ) -> datetime:
        # Caller-provided time is never authoritative for SQL-backed work.
        return _as_utc(self._database_clock(session))

    @staticmethod
    def _claim_action(job: BackgroundJob, *, now: datetime) -> str | None:
        current_time = _as_utc(now)
        deadline_expired = (
            job.not_after is not None and _as_utc(job.not_after) < current_time
        )
        lease_expired = (
            job.lease_expires_at is not None
            and _as_utc(job.lease_expires_at) <= current_time
        )
        if job.status == "provider_submitting" and lease_expired:
            return "provider_review"
        if job.status in ("pending", "leased") and deadline_expired:
            return "deadline_review"
        if (
            job.status == "pending" or (job.status == "leased" and lease_expired)
        ) and job.attempts >= job.max_attempts:
            return "dead_letter"
        if (
            job.status == "pending"
            and _as_utc(job.available_at) <= current_time
            and job.attempts < job.max_attempts
        ):
            return "claim"
        if job.status == "leased" and lease_expired and job.attempts < job.max_attempts:
            return "claim"
        return None

    @staticmethod
    def _finish_locked_job(
        job: BackgroundJob,
        *,
        status: str,
        reason_code: str,
        now: datetime,
    ) -> None:
        job.status = status
        job.lease_owner = None
        job.lease_token = None
        job.lease_expires_at = None
        job.completed_at = now
        job.updated_at = now
        if status == "suspension_blocked":
            job.blocked_reason_code = reason_code
            job.blocked_at = now
        elif status in ("needs_review", "recovery_review"):
            job.review_reason_code = reason_code
        elif status == "dead_letter":
            job.last_error_code = reason_code

    def _block_locked_job(
        self,
        job: BackgroundJob,
        *,
        verdict: AuthorityVerdict,
        now: datetime,
    ) -> None:
        reason = verdict.reason_code or "tenant_gate_denied"
        normalized = reason.lower()
        status = (
            "recovery_review"
            if verdict.recovery_review
            else (
                "suspension_blocked"
                if normalized in {"tenant_suspended", "tenant_suspending"}
                else "needs_review"
            )
        )
        self._finish_locked_job(
            job,
            status=status,
            reason_code=reason,
            now=now,
        )

    @staticmethod
    def _evaluate_authority(
        authority: JobAuthority,
        session: Session,
        *,
        locked_authority: Any,
        job: BackgroundJob,
        phase: str,
        now: datetime,
    ) -> AuthorityVerdict:
        try:
            verdict = authority.evaluate_locked_job_authority(
                session,
                locked_authority=locked_authority,
                job=job,
                phase=phase,
                now=now,
            )
        except Exception:
            return AuthorityVerdict(False, "tenant_authority_unavailable")
        if not isinstance(verdict, AuthorityVerdict):
            return AuthorityVerdict(False, "tenant_authority_unavailable")
        return verdict

    @staticmethod
    def _validate_fence(
        job: BackgroundJob,
        *,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        allowed_statuses: tuple[str, ...],
        now: datetime,
    ) -> None:
        if job.status not in allowed_statuses:
            raise InvalidJobTransition(
                f"job status {job.status!r} does not allow this transition"
            )
        if (
            job.lease_owner != worker_id
            or job.lease_token != lease_token
            or job.execution_generation != execution_generation
            or job.lease_expires_at is None
            or _as_utc(job.lease_expires_at) <= _as_utc(now)
        ):
            raise LeaseFenceViolation("job lease is stale")

    def _lock_fenced_job(
        self,
        session: Session,
        *,
        job_id: str,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        allowed_statuses: tuple[str, ...],
        test_now: datetime | None,
    ) -> tuple[BackgroundJob, datetime]:
        job = session.scalar(
            sa.select(BackgroundJob)
            .where(BackgroundJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None:
            raise LeaseFenceViolation("job does not exist")
        current_time = self._database_now(session, test_now=test_now)
        self._validate_fence(
            job,
            worker_id=worker_id,
            lease_token=lease_token,
            execution_generation=execution_generation,
            allowed_statuses=allowed_statuses,
            now=current_time,
        )
        return job, current_time

    def _lock_authorized_job(
        self,
        session: Session,
        *,
        job_id: str,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        allowed_statuses: tuple[str, ...],
        authority: JobAuthority,
        phase: str,
        test_now: datetime | None,
    ) -> tuple[BackgroundJob, datetime, AuthorityVerdict]:
        self._require_authority(authority)
        snapshot = session.scalar(
            sa.select(BackgroundJob).where(BackgroundJob.id == job_id)
        )
        if snapshot is None:
            raise LeaseFenceViolation("job does not exist")
        locked_authority = authority.lock_current_job_authority(
            session,
            job=snapshot,
            phase=phase,
        )
        job = session.scalar(
            sa.select(BackgroundJob)
            .where(BackgroundJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None:
            raise LeaseFenceViolation("job does not exist")
        current_time = self._database_now(session, test_now=test_now)
        self._validate_fence(
            job,
            worker_id=worker_id,
            lease_token=lease_token,
            execution_generation=execution_generation,
            allowed_statuses=allowed_statuses,
            now=current_time,
        )
        if (
            job.tenant_id != snapshot.tenant_id
            or job.tenant_access_version != snapshot.tenant_access_version
        ):
            verdict = AuthorityVerdict(False, "tenant_authority_unavailable")
        else:
            verdict = self._evaluate_authority(
                authority,
                session,
                locked_authority=locked_authority,
                job=job,
                phase=phase,
                now=current_time,
            )
        return job, current_time, verdict
