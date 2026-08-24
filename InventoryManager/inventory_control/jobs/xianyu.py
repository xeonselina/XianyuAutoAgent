"""Durable tenant-level scheduling for Xianyu alert synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.database import ControlDatabase
from inventory_control.models.foundation import Tenant
from inventory_control.models.integrations import (
    TenantIntegration,
    TenantIntegrationSecretRevision,
)
from inventory_control.models.jobs import BackgroundJob

from .scheduler import (
    PeriodicJobDefinition,
    ScheduleCycle,
    ScheduleGateVerdict,
    TenantScheduleGate,
)
from .service import ControlJobService


XIAN_YU_SYNC_INTERVAL: Final = timedelta(seconds=180)
XIAN_YU_SCHEDULED_JOB_TYPE: Final = "xianyu_alert_sync"
XIAN_YU_MANUAL_JOB_TYPE: Final = "xianyu_alert_sync_now"
XIAN_YU_RESOURCE_KEY: Final = "xianyu:connection-set"
_IN_FLIGHT_STATUSES: Final = frozenset(
    {"pending", "leased", "provider_submitting"}
)


class XianyuSyncSchedulingError(RuntimeError):
    code = "XIANYU_SYNC_SCHEDULING_UNAVAILABLE"


class XianyuSyncNotConfigured(XianyuSyncSchedulingError):
    code = "XIANYU_SYNC_NOT_CONFIGURED"


class XianyuSyncScheduleDenied(XianyuSyncSchedulingError):
    code = "XIANYU_SYNC_NOT_ALLOWED"


@dataclass(frozen=True, slots=True)
class XianyuConnectionRevision:
    integration_uuid: str
    secret_revision_uuid: str
    integration_row_version: int
    revision_row_version: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "integration_uuid", _uuid(self.integration_uuid)
        )
        object.__setattr__(
            self, "secret_revision_uuid", _uuid(self.secret_revision_uuid)
        )
        for value in (
            self.integration_row_version,
            self.revision_row_version,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("connection row version is invalid")


@dataclass(frozen=True, slots=True)
class ManualXianyuSyncSubmission:
    job_uuid: str
    snapshot_revision: int
    job_status: str
    reused: bool


class XianyuTenantScheduleGate:
    """Add provider eligibility to the shared lifecycle/recovery gate."""

    def __init__(self, delegate: TenantScheduleGate) -> None:
        if not callable(getattr(delegate, "evaluate", None)):
            raise TypeError("delegate must implement TenantScheduleGate")
        self._delegate = delegate

    def evaluate(
        self,
        session: Session,
        *,
        tenant: Tenant,
        now: datetime,
    ) -> ScheduleGateVerdict:
        verdict = self._delegate.evaluate(session, tenant=tenant, now=now)
        if not isinstance(verdict, ScheduleGateVerdict):
            raise TypeError("schedule gate returned an invalid verdict")
        if not verdict.allowed:
            return verdict
        if not current_xianyu_connection_revisions(
            session,
            tenant_uuid=tenant.id,
            lock=True,
        ):
            return ScheduleGateVerdict(False, "xianyu_not_configured")
        return verdict


class XianyuSyncJobCoordinator:
    """Coalesce user refreshes with current scheduled or manual durable work."""

    def __init__(
        self,
        *,
        database: ControlDatabase,
        gate: TenantScheduleGate,
        service: ControlJobService | None = None,
    ) -> None:
        if not isinstance(database, ControlDatabase):
            raise TypeError("database must be a ControlDatabase")
        if not callable(getattr(gate, "evaluate", None)):
            raise TypeError("gate must implement TenantScheduleGate")
        self._database = database
        self._gate = gate
        self._service = service or ControlJobService()

    @property
    def database(self) -> ControlDatabase:
        return self._database

    @property
    def gate(self) -> TenantScheduleGate:
        return self._gate

    def enqueue_manual(
        self,
        *,
        tenant_uuid: str | UUID,
        requested_by_user_uuid: str | UUID,
        snapshot_revision: int,
        now: datetime,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> ManualXianyuSyncSubmission:
        tenant_id = _uuid(tenant_uuid)
        actor_id = _uuid(requested_by_user_uuid)
        current_time = _as_utc(now)
        if (
            isinstance(snapshot_revision, bool)
            or not isinstance(snapshot_revision, int)
            or snapshot_revision < 0
        ):
            raise ValueError("snapshot_revision must be nonnegative")

        with self._database.transaction() as session:
            tenant = session.scalar(
                sa.select(Tenant)
                .where(Tenant.id == tenant_id)
                .with_for_update()
            )
            if tenant is None or tenant.status != "active":
                raise XianyuSyncScheduleDenied()
            verdict = self._gate.evaluate(
                session,
                tenant=tenant,
                now=current_time,
            )
            if not isinstance(verdict, ScheduleGateVerdict) or not verdict.allowed:
                raise XianyuSyncScheduleDenied()

            connections = current_xianyu_connection_revisions(
                session,
                tenant_uuid=tenant.id,
                lock=True,
            )
            if not connections:
                raise XianyuSyncNotConfigured()

            active = session.scalar(
                sa.select(BackgroundJob)
                .where(
                    BackgroundJob.tenant_id == tenant.id,
                    BackgroundJob.tenant_access_version
                    == tenant.access_version,
                    BackgroundJob.job_type.in_(
                        (
                            XIAN_YU_SCHEDULED_JOB_TYPE,
                            XIAN_YU_MANUAL_JOB_TYPE,
                        )
                    ),
                    BackgroundJob.resource_key == XIAN_YU_RESOURCE_KEY,
                    BackgroundJob.status.in_(_IN_FLIGHT_STATUSES),
                )
                .order_by(
                    BackgroundJob.created_at.asc(),
                    BackgroundJob.id.asc(),
                )
                .with_for_update()
            )
            if active is not None:
                active = self._service.promote_pending_job(
                    session,
                    job_id=active.id,
                    priority=100,
                    available_at=current_time,
                    now=current_time,
                )
                return _submission(
                    active,
                    snapshot_revision=snapshot_revision,
                    reused=True,
                )

            bucket = _bucket_started_at(current_time)
            digest = xianyu_connection_set_digest(connections)
            scheduled_key = _scheduled_idempotency_key(
                bucket=bucket,
                connection_digest=digest,
            )
            manual_key = _manual_idempotency_key(
                bucket=bucket,
                connection_digest=digest,
            )
            current_bucket_job = session.scalar(
                sa.select(BackgroundJob)
                .where(
                    BackgroundJob.tenant_id == tenant.id,
                    BackgroundJob.tenant_access_version
                    == tenant.access_version,
                    BackgroundJob.job_type.in_(
                        (
                            XIAN_YU_SCHEDULED_JOB_TYPE,
                            XIAN_YU_MANUAL_JOB_TYPE,
                        )
                    ),
                    BackgroundJob.resource_key == XIAN_YU_RESOURCE_KEY,
                    BackgroundJob.idempotency_key.in_(
                        (scheduled_key, manual_key)
                    ),
                )
                .order_by(
                    BackgroundJob.created_at.asc(),
                    BackgroundJob.id.asc(),
                )
                .with_for_update()
            )
            if current_bucket_job is not None:
                return _submission(
                    current_bucket_job,
                    snapshot_revision=snapshot_revision,
                    reused=True,
                )

            job = self._service.enqueue_job(
                session,
                tenant_id=tenant.id,
                tenant_access_version=tenant.access_version,
                job_type=XIAN_YU_MANUAL_JOB_TYPE,
                resource_key=XIAN_YU_RESOURCE_KEY,
                payload=_payload(connections, bucket=bucket),
                idempotency_key=manual_key,
                requested_by_type="tenant_user",
                requested_by_id=actor_id,
                request_id=request_id,
                correlation_id=correlation_id,
                priority=100,
                available_at=current_time,
                not_after=current_time + XIAN_YU_SYNC_INTERVAL,
            )
            return _submission(
                job,
                snapshot_revision=snapshot_revision,
                reused=False,
            )


def xianyu_periodic_job_definition() -> PeriodicJobDefinition:
    return PeriodicJobDefinition(
        job_type=XIAN_YU_SCHEDULED_JOB_TYPE,
        interval=XIAN_YU_SYNC_INTERVAL,
        not_after_window=XIAN_YU_SYNC_INTERVAL,
        resource_key=XIAN_YU_RESOURCE_KEY,
        payload_builder=_scheduled_payload,
        idempotency_scope_builder=_scheduled_scope,
        priority=10,
    )


def current_xianyu_connection_revisions(
    session: Session,
    *,
    tenant_uuid: str | UUID,
    lock: bool = False,
) -> tuple[XianyuConnectionRevision, ...]:
    tenant_id = _uuid(tenant_uuid)
    statement = (
        sa.select(TenantIntegration, TenantIntegrationSecretRevision)
        .join(
            TenantIntegrationSecretRevision,
            TenantIntegrationSecretRevision.id
            == TenantIntegration.current_secret_revision_id,
        )
        .where(
            TenantIntegration.tenant_id == tenant_id,
            TenantIntegration.provider == "xianyu",
            TenantIntegration.status == "active",
            TenantIntegration.current_secret_revision_id.is_not(None),
            TenantIntegrationSecretRevision.tenant_id == tenant_id,
            TenantIntegrationSecretRevision.provider == "xianyu",
            TenantIntegrationSecretRevision.status == "current",
            TenantIntegrationSecretRevision.verification_status == "succeeded",
        )
        .order_by(TenantIntegration.id.asc())
    )
    if lock:
        statement = statement.with_for_update()
    return tuple(
        XianyuConnectionRevision(
            integration_uuid=integration.id,
            secret_revision_uuid=revision.id,
            integration_row_version=integration.row_version,
            revision_row_version=revision.row_version,
        )
        for integration, revision in session.execute(statement)
    )


def _scheduled_payload(
    session: Session,
    tenant: Tenant,
    cycle: ScheduleCycle,
) -> dict[str, object]:
    connections = current_xianyu_connection_revisions(
        session,
        tenant_uuid=tenant.id,
        lock=True,
    )
    if not connections:
        # Production composition pairs the definition with
        # XianyuTenantScheduleGate.  Keep this second check fail closed so a
        # mis-composed scheduler cannot enqueue an unscoped provider job.
        raise XianyuSyncNotConfigured()
    return _payload(connections, bucket=cycle.bucket_started_at)


def _scheduled_scope(
    _session: Session,
    _tenant: Tenant,
    cycle: ScheduleCycle,
    payload: dict[str, object],
) -> str:
    digest = payload.get("connection_set_digest")
    if not isinstance(digest, str) or len(digest) != 32:
        raise XianyuSyncSchedulingError()
    return f"{cycle.bucket_key}:{digest}"


def _payload(
    connections: tuple[XianyuConnectionRevision, ...],
    *,
    bucket: datetime,
) -> dict[str, object]:
    return {
        "contract_version": 1,
        "bucket_started_at": _as_utc(bucket).isoformat().replace("+00:00", "Z"),
        "connection_set_digest": xianyu_connection_set_digest(connections),
        "connections": [
            {
                "integration_uuid": connection.integration_uuid,
                "secret_revision_uuid": connection.secret_revision_uuid,
                "integration_row_version": connection.integration_row_version,
                "revision_row_version": connection.revision_row_version,
            }
            for connection in connections
        ],
    }


def xianyu_connection_set_digest(
    connections: tuple[XianyuConnectionRevision, ...],
) -> str:
    if (
        not isinstance(connections, tuple)
        or not connections
        or any(
            not isinstance(connection, XianyuConnectionRevision)
            for connection in connections
        )
        or len({connection.integration_uuid for connection in connections})
        != len(connections)
    ):
        raise ValueError("Xianyu connection set is invalid")
    canonical = [
        [
            connection.integration_uuid,
            connection.secret_revision_uuid,
            connection.integration_row_version,
            connection.revision_row_version,
        ]
        for connection in sorted(
            connections,
            key=lambda item: item.integration_uuid,
        )
    ]
    return hashlib.sha256(
        json.dumps(canonical, separators=(",", ":")).encode("ascii")
    ).hexdigest()[:32]


def _bucket_started_at(now: datetime) -> datetime:
    current = _as_utc(now)
    seconds = int(XIAN_YU_SYNC_INTERVAL.total_seconds())
    epoch = int(current.timestamp()) // seconds * seconds
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def _scheduled_idempotency_key(
    *, bucket: datetime, connection_digest: str
) -> str:
    return (
        f"scheduler:{XIAN_YU_SCHEDULED_JOB_TYPE}:"
        f"{int(_as_utc(bucket).timestamp())}:{connection_digest}"
    )


def _manual_idempotency_key(
    *, bucket: datetime, connection_digest: str
) -> str:
    return (
        f"manual:{XIAN_YU_MANUAL_JOB_TYPE}:"
        f"{int(_as_utc(bucket).timestamp())}:{connection_digest}"
    )


def _submission(
    job: BackgroundJob,
    *,
    snapshot_revision: int,
    reused: bool,
) -> ManualXianyuSyncSubmission:
    return ManualXianyuSyncSubmission(
        job_uuid=job.id,
        snapshot_revision=snapshot_revision,
        job_status=job.status,
        reused=reused,
    )


def _uuid(value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("identifier is invalid") from None


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)
