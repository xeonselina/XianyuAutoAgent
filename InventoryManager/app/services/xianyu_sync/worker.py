"""Durable multi-connection Xianyu synchronization job composition."""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.xianyu_order_alert import XianyuConnectionSyncState
from app.tenancy import TenantContext, TenantContextSource
from app.tenancy.routed_transaction import SqlAlchemyTenantTransactionProvider
from inventory_control import ControlDatabase
from inventory_control.crypto import SqlAlchemyRootKeyRegistry
from inventory_control.integrations import (
    XianyuSyncCredentialError,
    XianyuSyncCredentialFactory,
    XianyuSyncProviderRequest,
)
from inventory_control.jobs import (
    DurableProviderCallAuthorizer,
    JobOutcome,
    OutcomeDisposition,
    PreparedJob,
    RecoveryCategory,
    XIAN_YU_MANUAL_JOB_TYPE,
    XIAN_YU_RESOURCE_KEY,
    XIAN_YU_SCHEDULED_JOB_TYPE,
    XianyuConnectionRevision,
    xianyu_connection_set_digest,
)
from inventory_control.models.jobs import BackgroundJob
from inventory_control.routing import SqlAlchemyTenantRouterScope

from .contracts import (
    XianyuConnectionRef,
    XianyuConnectionSyncResult,
)
from .persistence import XianyuSyncApplyResult, XianyuSyncPersistenceService
from .provider import (
    XianyuProviderAdapter,
    XianyuProviderSettings,
    XianyuSyncProviderDispatcher,
)


TenantTransactionProvider = Callable[
    ["PreparedXianyuSyncJob"], AbstractContextManager[Session]
]
WorkerClock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class PreparedXianyuSyncJob:
    job_uuid: str
    tenant_uuid: str
    tenant_access_version: int
    connections: tuple[XianyuConnectionRevision, ...]
    request_id: str


@dataclass(frozen=True, slots=True, repr=False)
class XianyuSyncStart:
    already_applied: bool
    provider_cursors: Mapping[str, str | None]

    def __repr__(self) -> str:
        return (
            "XianyuSyncStart("
            f"already_applied={self.already_applied}, "
            f"connection_count={len(self.provider_cursors)}, "
            "provider_cursors=<redacted>)"
        )


class XianyuTenantSyncStore(Protocol):
    def mark_started(
        self,
        *,
        prepared: PreparedXianyuSyncJob,
        attempted_at: datetime,
    ) -> XianyuSyncStart: ...

    def apply_results(
        self,
        *,
        prepared: PreparedXianyuSyncJob,
        results: tuple[XianyuConnectionSyncResult, ...],
        completed_at: datetime,
    ) -> XianyuSyncApplyResult: ...


class XianyuCredentialRequestSource(Protocol):
    def prepare(
        self,
        *,
        job: PreparedXianyuSyncJob,
        connection: XianyuConnectionRevision,
        provider_cursor: str | None,
    ) -> XianyuSyncProviderRequest: ...


class SqlAlchemyXianyuTenantSyncStore:
    """Short tenant transactions supplied by a trusted routed factory."""

    def __init__(self, transaction_provider: TenantTransactionProvider) -> None:
        if not callable(transaction_provider):
            raise TypeError("tenant transaction provider is required")
        self._transaction_provider = transaction_provider

    def mark_started(
        self,
        *,
        prepared: PreparedXianyuSyncJob,
        attempted_at: datetime,
    ) -> XianyuSyncStart:
        connection_ids = tuple(
            connection.integration_uuid for connection in prepared.connections
        )
        with self._transaction_provider(prepared) as session:
            states = {
                state.integration_uuid: state
                for state in session.scalars(
                    sa.select(XianyuConnectionSyncState)
                    .where(
                        XianyuConnectionSyncState.integration_uuid.in_(
                            connection_ids
                        )
                    )
                    .order_by(XianyuConnectionSyncState.integration_uuid.asc())
                    .with_for_update()
                )
            }
            cursors = {
                connection.integration_uuid: (
                    states[connection.integration_uuid].provider_cursor
                    if connection.integration_uuid in states
                    and states[connection.integration_uuid].secret_revision_uuid
                    == connection.secret_revision_uuid
                    else None
                )
                for connection in prepared.connections
            }
            started = XianyuSyncPersistenceService(session).mark_started(
                job_uuid=prepared.job_uuid,
                connections=tuple(
                    XianyuConnectionRef(
                        connection.integration_uuid,
                        connection.secret_revision_uuid,
                    )
                    for connection in prepared.connections
                ),
                attempted_at=attempted_at,
            )
        return XianyuSyncStart(
            already_applied=not started.applied,
            provider_cursors=MappingProxyType(cursors),
        )

    def apply_results(
        self,
        *,
        prepared: PreparedXianyuSyncJob,
        results: tuple[XianyuConnectionSyncResult, ...],
        completed_at: datetime,
    ) -> XianyuSyncApplyResult:
        with self._transaction_provider(prepared) as session:
            return XianyuSyncPersistenceService(session).apply_results(
                job_uuid=prepared.job_uuid,
                results=results,
                completed_at=completed_at,
            )


class SqlAlchemyRoutedTenantTransactionProvider:
    """Open one verified tenant DML transaction for a claimed worker job."""

    def __init__(
        self,
        *,
        database: ControlDatabase,
        router_scope: SqlAlchemyTenantRouterScope,
    ) -> None:
        if not isinstance(database, ControlDatabase) or not isinstance(
            router_scope, SqlAlchemyTenantRouterScope
        ):
            raise TypeError("routed tenant transaction composition is invalid")
        self._transactions = SqlAlchemyTenantTransactionProvider(
            database=database,
            router_scope=router_scope,
        )

    @contextmanager
    def __call__(self, prepared: PreparedXianyuSyncJob):
        if not isinstance(prepared, PreparedXianyuSyncJob):
            raise TypeError("prepared Xianyu sync job is invalid")
        context = TenantContext(
            tenant_id=UUID(prepared.tenant_uuid),
            access_version=prepared.tenant_access_version,
            source=TenantContextSource.WORKER_JOB,
            principal_ref="xianyu-sync-worker",
            source_ref=prepared.job_uuid,
            request_id=prepared.request_id,
        )
        with self._transactions(context) as tenant_session:
            yield tenant_session


class SqlAlchemyXianyuCredentialRequestSource:
    """Load registered root keys and prepare one exact control-plane revision."""

    def __init__(
        self,
        *,
        database: ControlDatabase,
        root_key_directory: str | Path,
    ) -> None:
        if not isinstance(database, ControlDatabase):
            raise TypeError("control database is required")
        directory = Path(root_key_directory)
        if not directory.is_absolute():
            raise ValueError("root key directory must be absolute")
        self._database = database
        self._root_key_directory = directory

    def prepare(
        self,
        *,
        job: PreparedXianyuSyncJob,
        connection: XianyuConnectionRevision,
        provider_cursor: str | None,
    ) -> XianyuSyncProviderRequest:
        with self._database.transaction() as session:
            key_ring = SqlAlchemyRootKeyRegistry(session=session).load(
                self._root_key_directory
            )
            return XianyuSyncCredentialFactory(session).prepare(
                tenant_uuid=job.tenant_uuid,
                integration_uuid=connection.integration_uuid,
                secret_revision_uuid=connection.secret_revision_uuid,
                integration_row_version=connection.integration_row_version,
                revision_row_version=connection.revision_row_version,
                provider_cursor=provider_cursor,
                root_key_ring=key_ring,
            )


class XianyuSyncJobHandler:
    """Run one tenant job with independent, authority-checked connections."""

    crosses_provider_boundary = True
    recovery_category = RecoveryCategory.XIANYU_KUAIMAI_SYNC

    def __init__(
        self,
        *,
        tenant_store: XianyuTenantSyncStore,
        credential_source: XianyuCredentialRequestSource,
        provider_adapter: XianyuProviderAdapter,
        provider_settings: XianyuProviderSettings,
        call_authorizer: DurableProviderCallAuthorizer,
        clock: WorkerClock,
    ) -> None:
        if (
            not callable(getattr(tenant_store, "mark_started", None))
            or not callable(getattr(tenant_store, "apply_results", None))
            or not callable(getattr(credential_source, "prepare", None))
            or not callable(getattr(provider_adapter, "fetch_alerts", None))
            or not isinstance(provider_settings, XianyuProviderSettings)
            or not callable(getattr(call_authorizer, "authorize", None))
            or not callable(clock)
        ):
            raise TypeError("Xianyu sync job composition is invalid")
        self._tenant_store = tenant_store
        self._credential_source = credential_source
        self._provider_adapter = provider_adapter
        self._provider_settings = provider_settings
        self._call_authorizer = call_authorizer
        self._clock = clock

    def prepare(self, job: BackgroundJob) -> PreparedJob:
        return PreparedJob(_parse_job(job))

    def execute(self, job: BackgroundJob, prepared: PreparedJob) -> JobOutcome:
        value = prepared.value
        if not isinstance(value, PreparedXianyuSyncJob):
            raise TypeError("prepared Xianyu sync job is invalid")
        started = self._tenant_store.mark_started(
            prepared=value,
            attempted_at=_utc(self._clock()),
        )
        if started.already_applied:
            return JobOutcome(
                OutcomeDisposition.SUCCEEDED,
                safe_result={"idempotent_replay": True},
            )

        results: list[XianyuConnectionSyncResult] = []
        denied_reason: str | None = None
        for offset, connection in enumerate(value.connections):
            verdict = self._call_authorizer.authorize(job)
            if not verdict.allowed:
                denied_reason = verdict.reason_code or "tenant_gate_denied"
                results.extend(
                    _denied_result(item)
                    for item in value.connections[offset:]
                )
                break
            try:
                request = self._credential_source.prepare(
                    job=value,
                    connection=connection,
                    provider_cursor=started.provider_cursors.get(
                        connection.integration_uuid
                    ),
                )
            except XianyuSyncCredentialError:
                results.append(
                    XianyuConnectionSyncResult(
                        integration_uuid=connection.integration_uuid,
                        secret_revision_uuid=connection.secret_revision_uuid,
                        status="failed",
                        safe_error_code="CREDENTIAL_UNAVAILABLE",
                    )
                )
                continue
            results.append(
                XianyuSyncProviderDispatcher.dispatch(
                    request=request,
                    adapter=self._provider_adapter,
                    settings=self._provider_settings,
                )
            )

        applied = self._tenant_store.apply_results(
            prepared=value,
            results=tuple(results),
            completed_at=_utc(self._clock()),
        )
        safe_result = {
            "snapshot_revision": applied.snapshot_revision,
            "connection_count": len(results),
            "succeeded_connections": sum(
                result.status == "succeeded" for result in results
            ),
            "failed_connections": sum(
                result.status != "succeeded" for result in results
            ),
        }
        if denied_reason is not None:
            return JobOutcome(
                OutcomeDisposition.REVIEW,
                safe_result=safe_result,
                reason_code=denied_reason,
            )
        return JobOutcome(
            OutcomeDisposition.SUCCEEDED,
            safe_result=safe_result,
        )


def _parse_job(job: BackgroundJob) -> PreparedXianyuSyncJob:
    if (
        not isinstance(job, BackgroundJob)
        or job.job_type
        not in {XIAN_YU_SCHEDULED_JOB_TYPE, XIAN_YU_MANUAL_JOB_TYPE}
        or job.resource_key != XIAN_YU_RESOURCE_KEY
        or not isinstance(job.payload, dict)
        or job.payload.get("contract_version") != 1
        or not isinstance(job.payload.get("connections"), list)
        or not job.payload["connections"]
    ):
        raise ValueError("Xianyu sync job payload is invalid")
    tenant_id = str(UUID(job.tenant_id))
    connections = tuple(
        _parse_connection(item) for item in job.payload["connections"]
    )
    expected_digest = xianyu_connection_set_digest(connections)
    if job.payload.get("connection_set_digest") != expected_digest:
        raise ValueError("Xianyu sync job connection digest is invalid")
    return PreparedXianyuSyncJob(
        job_uuid=str(UUID(job.id)),
        tenant_uuid=tenant_id,
        tenant_access_version=_positive(job.tenant_access_version),
        connections=connections,
        request_id=job.correlation_id or job.request_id or job.id,
    )


def _parse_connection(value: object) -> XianyuConnectionRevision:
    expected = {
        "integration_uuid",
        "secret_revision_uuid",
        "integration_row_version",
        "revision_row_version",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("Xianyu sync connection payload is invalid")
    return XianyuConnectionRevision(**value)


def _denied_result(
    connection: XianyuConnectionRevision,
) -> XianyuConnectionSyncResult:
    return XianyuConnectionSyncResult(
        integration_uuid=connection.integration_uuid,
        secret_revision_uuid=connection.secret_revision_uuid,
        status="failed",
        safe_error_code="TENANT_AUTHORITY_DENIED",
    )


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("positive integer is required")
    return value


def _utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("worker clock must be timezone-aware")
    return value.astimezone(timezone.utc)


__all__ = [
    "PreparedXianyuSyncJob",
    "SqlAlchemyRoutedTenantTransactionProvider",
    "SqlAlchemyXianyuCredentialRequestSource",
    "SqlAlchemyXianyuTenantSyncStore",
    "XianyuCredentialRequestSource",
    "XianyuSyncJobHandler",
    "XianyuSyncStart",
    "XianyuTenantSyncStore",
]
