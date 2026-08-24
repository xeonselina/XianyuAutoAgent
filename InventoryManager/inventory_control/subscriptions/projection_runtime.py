"""Durable scheduling and worker adapters for subscription projections.

Expiry reconciliation is a control-plane system operation, not an ordinary
tenant business job.  It must remain runnable when the subscription is already
expired or a higher lifecycle overlay is active, while still taking the same
tenant-first lifecycle locks before the durable job row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.database import ControlDatabase, read_database_utc_value
from inventory_control.jobs import (
    AuthorityVerdict,
    ControlJobService,
    DurableJobCapability,
    JobOutcome,
    JobProcessTrigger,
    OutcomeDisposition,
    PreparedJob,
)
from inventory_control.models.foundation import Tenant
from inventory_control.models.jobs import BackgroundJob
from inventory_control.models.subscriptions import Subscription

from .evaluator import (
    SqlAlchemySubscriptionProjectionLifecycleLocker,
    SubscriptionProjectionAuthorityError,
    SubscriptionProjectionConflictError,
    SubscriptionProjectionEvaluator,
    SubscriptionProjectionLifecycleLocker,
    SubscriptionProjectionLifecycleLocks,
)


SUBSCRIPTION_PROJECTION_JOB_TYPE = "subscription_projection_evaluate"
DatabaseClock = Callable[[Session], datetime]


class EvaluatorHeartbeatRecorder(Protocol):
    def __call__(
        self,
        session: Session,
        *,
        observed_at: datetime,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class SubscriptionProjectionEnqueueResult:
    candidate_tenants: int
    enqueued_jobs: int
    reused_jobs: int
    skipped_current: int
    skipped_authority: int


@dataclass(frozen=True, slots=True)
class LockedSubscriptionProjectionAuthority:
    tenant: Tenant | None
    subscription: Subscription | None
    lifecycle: SubscriptionProjectionLifecycleLocks | None
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class PreparedSubscriptionProjection:
    tenant_uuid: str
    subscription_uuid: str


class SubscriptionProjectionJobScheduler:
    """Enqueue current due projections in bounded per-tenant transactions."""

    def __init__(
        self,
        *,
        database: ControlDatabase,
        heartbeat_recorder: EvaluatorHeartbeatRecorder,
        lifecycle_locker: SubscriptionProjectionLifecycleLocker | None = None,
        database_clock: DatabaseClock | None = None,
        service: ControlJobService | None = None,
    ) -> None:
        if not isinstance(database, ControlDatabase):
            raise TypeError("control database is required")
        if not callable(heartbeat_recorder):
            raise TypeError("heartbeat_recorder is required")
        if lifecycle_locker is not None and not callable(lifecycle_locker):
            raise TypeError("lifecycle_locker must be callable")
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._database = database
        self._heartbeat_recorder = heartbeat_recorder
        self._lifecycle_locker = (
            lifecycle_locker
            or SqlAlchemySubscriptionProjectionLifecycleLocker()
        )
        self._database_clock = database_clock or _read_database_utc_now
        self._service = service or ControlJobService(
            database_clock=self._database_clock
        )

    def enqueue_due(
        self,
        *,
        max_candidates: int,
        priority: int,
        max_attempts: int,
    ) -> SubscriptionProjectionEnqueueResult:
        _validate_enqueue_settings(
            max_candidates=max_candidates,
            priority=priority,
            max_attempts=max_attempts,
        )

        with self._database.transaction() as session:
            scan_time = _as_utc(self._database_clock(session))
            candidate_ids = list(
                session.scalars(
                    sa.select(Subscription.tenant_id)
                    .join(Tenant, Tenant.id == Subscription.tenant_id)
                    .where(
                        Subscription.expires_at <= scan_time,
                        sa.or_(
                            Subscription.status != "expired",
                            Tenant.status == "active",
                        ),
                    )
                    .order_by(
                        Subscription.expires_at.asc(),
                        Subscription.tenant_id.asc(),
                    )
                    .limit(max_candidates)
                )
            )

        enqueued = reused = skipped_current = skipped_authority = 0
        for tenant_id in candidate_ids:
            try:
                with self._database.transaction() as session:
                    tenant = session.scalar(
                        sa.select(Tenant)
                        .where(Tenant.id == tenant_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                    if tenant is None:
                        skipped_current += 1
                        continue
                    self._lifecycle_locker(session, tenant)
                    subscription = session.scalar(
                        sa.select(Subscription)
                        .where(Subscription.tenant_id == tenant.id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                    if subscription is None:
                        skipped_current += 1
                        continue
                    current_time = _as_utc(self._database_clock(session))
                    if _as_utc(subscription.expires_at) > current_time or (
                        subscription.status == "expired"
                        and tenant.status != "active"
                    ):
                        skipped_current += 1
                        continue

                    idempotency_key = (
                        "subscription-projection:"
                        f"{subscription.id}:v{subscription.row_version}"
                    )
                    resource_key = f"subscription:{subscription.id}"
                    lookup = sa.select(BackgroundJob.id).where(
                        BackgroundJob.tenant_id == tenant.id,
                        BackgroundJob.job_type
                        == SUBSCRIPTION_PROJECTION_JOB_TYPE,
                        BackgroundJob.resource_key == resource_key,
                        BackgroundJob.idempotency_key == idempotency_key,
                    )
                    existing_id = session.scalar(lookup)
                    self._service.enqueue_job(
                        session,
                        tenant_id=tenant.id,
                        tenant_access_version=tenant.access_version,
                        job_type=SUBSCRIPTION_PROJECTION_JOB_TYPE,
                        resource_key=resource_key,
                        payload={
                            "tenant_uuid": tenant.id,
                            "subscription_uuid": subscription.id,
                        },
                        idempotency_key=idempotency_key,
                        requested_by_type="scheduler",
                        priority=priority,
                        max_attempts=max_attempts,
                        available_at=current_time,
                    )
                    if existing_id is None:
                        enqueued += 1
                    else:
                        reused += 1
            except SubscriptionProjectionAuthorityError:
                skipped_authority += 1

        # The heartbeat proves the complete sweep returned to its durable
        # control boundary.  A database/queue failure above emits no green
        # observation; authority-skipped tenants remain visible in the result
        # while the evaluator process itself is still alive.
        with self._database.transaction() as session:
            heartbeat_at = _as_utc(self._database_clock(session))
            self._heartbeat_recorder(session, observed_at=heartbeat_at)

        return SubscriptionProjectionEnqueueResult(
            candidate_tenants=len(candidate_ids),
            enqueued_jobs=enqueued,
            reused_jobs=reused,
            skipped_current=skipped_current,
            skipped_authority=skipped_authority,
        )


def build_subscription_projection_capability(
    *,
    database: ControlDatabase,
    evaluator_heartbeat_recorder: EvaluatorHeartbeatRecorder,
    scan_interval: timedelta,
    max_candidates: int,
    priority: int,
    max_attempts: int,
    lifecycle_locker: SubscriptionProjectionLifecycleLocker | None = None,
    database_clock: DatabaseClock | None = None,
) -> DurableJobCapability:
    """Compose the projection producer, authority, and handler as one unit."""

    if not isinstance(scan_interval, timedelta) or scan_interval < timedelta(
        seconds=1
    ):
        raise ValueError("scan_interval must be at least one second")
    _validate_enqueue_settings(
        max_candidates=max_candidates,
        priority=priority,
        max_attempts=max_attempts,
    )
    selected_locker = (
        lifecycle_locker
        or SqlAlchemySubscriptionProjectionLifecycleLocker()
    )
    scheduler = SubscriptionProjectionJobScheduler(
        database=database,
        heartbeat_recorder=evaluator_heartbeat_recorder,
        lifecycle_locker=selected_locker,
        database_clock=database_clock,
    )
    evaluator = SubscriptionProjectionEvaluator(
        lifecycle_locker=selected_locker,
        database_clock=database_clock,
    )
    handler = SubscriptionProjectionJobHandler(
        database=database,
        evaluator=evaluator,
    )
    trigger = JobProcessTrigger(
        name="subscription-projection-due-scan",
        interval=scan_interval,
        callback=lambda _now: scheduler.enqueue_due(
            max_candidates=max_candidates,
            priority=priority,
            max_attempts=max_attempts,
        ),
    )
    return DurableJobCapability(
        handlers={SUBSCRIPTION_PROJECTION_JOB_TYPE: handler},
        triggers=(trigger,),
        authority=SubscriptionProjectionJobAuthority(
            lifecycle_locker=selected_locker
        ),
    )


class SubscriptionProjectionJobAuthority:
    """Authorize only current-read, provider-free projection reconciliation."""

    _PHASES = {
        "claim",
        "after_claim",
        "before_tenant_context",
        "heartbeat",
        "before_provider_boundary",
    }

    def __init__(
        self,
        *,
        lifecycle_locker: SubscriptionProjectionLifecycleLocker | None = None,
    ) -> None:
        if lifecycle_locker is not None and not callable(lifecycle_locker):
            raise TypeError("lifecycle_locker must be callable")
        self._lifecycle_locker = (
            lifecycle_locker
            or SqlAlchemySubscriptionProjectionLifecycleLocker()
        )

    def lock_current_job_authority(
        self,
        session: Session,
        *,
        job: BackgroundJob,
        phase: str,
    ) -> LockedSubscriptionProjectionAuthority:
        if phase not in self._PHASES:
            raise ValueError("worker phase is invalid")
        tenant = session.scalar(
            sa.select(Tenant)
            .where(Tenant.id == job.tenant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if tenant is None:
            return LockedSubscriptionProjectionAuthority(
                tenant=None,
                subscription=None,
                lifecycle=None,
                reason_code="subscription_projection_tenant_unavailable",
            )
        try:
            lifecycle = self._lifecycle_locker(session, tenant)
        except SubscriptionProjectionAuthorityError:
            return LockedSubscriptionProjectionAuthority(
                tenant=tenant,
                subscription=None,
                lifecycle=None,
                reason_code="subscription_projection_authority_unavailable",
            )
        subscription = session.scalar(
            sa.select(Subscription)
            .where(Subscription.tenant_id == tenant.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return LockedSubscriptionProjectionAuthority(
            tenant=tenant,
            subscription=subscription,
            lifecycle=lifecycle,
            reason_code=(
                None
                if subscription is not None
                else "subscription_projection_subscription_unavailable"
            ),
        )

    def evaluate_locked_job_authority(
        self,
        session: Session,
        *,
        locked_authority: LockedSubscriptionProjectionAuthority,
        job: BackgroundJob,
        phase: str,
        now: datetime,
    ) -> AuthorityVerdict:
        del session, now
        if phase not in self._PHASES:
            return AuthorityVerdict(False, "worker_phase_invalid")
        if job.job_type != SUBSCRIPTION_PROJECTION_JOB_TYPE:
            return AuthorityVerdict(False, "subscription_projection_job_invalid")
        if locked_authority.reason_code is not None:
            return AuthorityVerdict(False, locked_authority.reason_code)
        tenant = locked_authority.tenant
        subscription = locked_authority.subscription
        payload = job.payload
        if (
            tenant is None
            or subscription is None
            or locked_authority.lifecycle is None
            or not isinstance(payload, dict)
            or payload.get("tenant_uuid") != tenant.id
            or payload.get("subscription_uuid") != subscription.id
            or subscription.tenant_id != tenant.id
        ):
            return AuthorityVerdict(False, "subscription_projection_job_invalid")
        return AuthorityVerdict(True)


class SubscriptionProjectionJobHandler:
    """Idempotently reconcile one projection without crossing a provider boundary."""

    crosses_provider_boundary = False

    def __init__(
        self,
        *,
        database: ControlDatabase,
        evaluator: SubscriptionProjectionEvaluator | None = None,
    ) -> None:
        if not isinstance(database, ControlDatabase):
            raise TypeError("control database is required")
        self._database = database
        self._evaluator = evaluator or SubscriptionProjectionEvaluator(
            lifecycle_locker=SqlAlchemySubscriptionProjectionLifecycleLocker()
        )

    def prepare(self, job: BackgroundJob) -> PreparedJob:
        payload = job.payload
        if not isinstance(payload, dict):
            raise ValueError("subscription projection payload is invalid")
        prepared = PreparedSubscriptionProjection(
            tenant_uuid=str(_uuid(payload.get("tenant_uuid"))),
            subscription_uuid=str(_uuid(payload.get("subscription_uuid"))),
        )
        if prepared.tenant_uuid != job.tenant_id:
            raise ValueError("subscription projection payload is invalid")
        return PreparedJob(prepared)

    def execute(
        self,
        job: BackgroundJob,
        prepared: PreparedJob,
    ) -> JobOutcome:
        del job
        value = prepared.value
        if not isinstance(value, PreparedSubscriptionProjection):
            raise TypeError("prepared subscription projection is invalid")
        with self._database.transaction() as session:
            result = self._evaluator.evaluate(
                session,
                tenant_uuid=value.tenant_uuid,
            )
            if result.subscription_uuid != value.subscription_uuid:
                raise SubscriptionProjectionConflictError(
                    "subscription identity changed"
                )
        return JobOutcome(
            OutcomeDisposition.SUCCEEDED,
            safe_result={
                "effective_status": result.effective_status,
                "tenant_changed": result.tenant_changed,
                "subscription_changed": result.subscription_changed,
                "tenant_row_version": result.tenant_row_version_after,
                "subscription_row_version": (
                    result.subscription_row_version_after
                ),
            },
        )


def _read_database_utc_now(session: Session) -> datetime:
    return _as_utc(read_database_utc_value(session))


def _validate_enqueue_settings(
    *,
    max_candidates: int,
    priority: int,
    max_attempts: int,
) -> None:
    if (
        isinstance(max_candidates, bool)
        or not isinstance(max_candidates, int)
        or not 1 <= max_candidates <= 1000
    ):
        raise ValueError("max_candidates must be between 1 and 1000")
    if (
        isinstance(priority, bool)
        or not isinstance(priority, int)
        or priority < 0
    ):
        raise ValueError("priority must be nonnegative")
    if (
        isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or max_attempts < 1
    ):
        raise ValueError("max_attempts must be positive")


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError("control database did not return a timestamp")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            pass
    raise ValueError("subscription projection UUID is invalid")


__all__ = [
    "SUBSCRIPTION_PROJECTION_JOB_TYPE",
    "EvaluatorHeartbeatRecorder",
    "LockedSubscriptionProjectionAuthority",
    "PreparedSubscriptionProjection",
    "SubscriptionProjectionEnqueueResult",
    "SubscriptionProjectionJobAuthority",
    "SubscriptionProjectionJobHandler",
    "SubscriptionProjectionJobScheduler",
    "build_subscription_projection_capability",
]
