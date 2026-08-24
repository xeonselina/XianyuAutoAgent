"""One-shot query reconciliation for uncertain SF waybill submissions."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Final, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
)
from app.services.relay.result_signal import (
    RelayCommittedShipmentResultEnqueuer,
    RelayShipmentResultSignalService,
    RelayShipmentSubmissionSignal,
)
from app.services.shipping.sf_waybill_provider import (
    SfWaybillQueryDispatcher,
    SfWaybillQueryResult,
)
from app.services.shipping_execution_service import (
    ShippingExecutionError,
    ShippingExecutionService,
    UnknownResolution,
)
from app.tenancy import TenantContext, TenantContextSource
from inventory_control import ControlDatabase
from inventory_control.crypto import SqlAlchemyRootKeyRegistry
from inventory_control.integrations import (
    SfWaybillCredentialError,
    SfWaybillCredentialFactory,
    SfWaybillQueryRequest,
)
from inventory_control.jobs import (
    AuthorityVerdict,
    DurableProviderCallAuthorizer,
    JobOutcome,
    OutcomeDisposition,
    PeriodicJobDefinition,
    PreparedJob,
    RecoveryCategory,
    ScheduleCycle,
)
from inventory_control.models.foundation import Tenant
from inventory_control.models.jobs import BackgroundJob
from inventory_control.transactions import require_caller_transaction


SF_WAYBILL_RECONCILIATION_JOB_TYPE: Final = "sf_waybill_reconcile_unknown"
SF_WAYBILL_RECONCILIATION_RESOURCE_KEY: Final = "sf:waybill-unknown-reconciliation"
SF_WAYBILL_RECONCILIATION_INTERVAL: Final = timedelta(seconds=30)


class SfWaybillReconciliationError(RuntimeError):
    code = "SF_WAYBILL_RECONCILIATION_FAILED"
    public_message = "SF waybill reconciliation failed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class SfWaybillReconciliationInputError(SfWaybillReconciliationError):
    code = "SF_WAYBILL_RECONCILIATION_INPUT_INVALID"


class SfWaybillReconciliationConflict(SfWaybillReconciliationError):
    code = "SF_WAYBILL_RECONCILIATION_CONFLICT"


@dataclass(frozen=True, slots=True)
class PreparedSfWaybillReconciliationJob:
    job_uuid: str
    tenant_uuid: str
    tenant_access_version: int
    request_id: str


@dataclass(frozen=True, slots=True)
class SfWaybillReconciliationSnapshot:
    tenant_uuid: str
    shipment_uuid: str
    attempt_uuid: str
    origin_warehouse_uuid: str
    integration_uuid: str
    provider_account_uuid: str
    integration_secret_revision_uuid: str
    provider_account_secret_revision_uuid: str
    binding_revision: int


@dataclass(frozen=True, slots=True)
class StoredSfWaybillReconciliation:
    shipment_uuid: str
    attempt_uuid: str
    resolution: UnknownResolution
    relay_signal: RelayShipmentSubmissionSignal | None


class SfWaybillReconciliationStore(Protocol):
    def claim_one(
        self,
        prepared: PreparedSfWaybillReconciliationJob,
        *,
        started_at: datetime,
    ) -> SfWaybillReconciliationSnapshot | None:
        ...

    def record_result(
        self,
        prepared: PreparedSfWaybillReconciliationJob,
        *,
        snapshot: SfWaybillReconciliationSnapshot,
        result: SfWaybillQueryResult,
        finished_at: datetime,
    ) -> StoredSfWaybillReconciliation:
        ...


class SfWaybillQueryCredentialSource(Protocol):
    def prepare(
        self,
        *,
        job: PreparedSfWaybillReconciliationJob,
        snapshot: SfWaybillReconciliationSnapshot,
    ) -> SfWaybillQueryRequest:
        ...


class SfWaybillQueryProvider(Protocol):
    def dispatch(self, request: SfWaybillQueryRequest) -> SfWaybillQueryResult:
        ...


TenantTransactionProvider = Callable[[TenantContext], AbstractContextManager[Session]]


class SqlAlchemySfWaybillReconciliationStore:
    """Claim and resolve uncertain attempts in short tenant transactions."""

    def __init__(self, transaction_provider: TenantTransactionProvider) -> None:
        if not callable(transaction_provider):
            raise TypeError("tenant transaction provider is required")
        self._transactions = transaction_provider

    def claim_one(
        self,
        prepared: PreparedSfWaybillReconciliationJob,
        *,
        started_at: datetime,
    ) -> SfWaybillReconciliationSnapshot | None:
        _prepared(prepared)
        current_time = _utc(started_at)
        with self._transactions(_tenant_context(prepared)) as session:
            _require_transaction(session)
            attempt = session.scalar(
                sa.select(ProviderOperationAttempt)
                .where(
                    ProviderOperationAttempt.operation == "create_waybill",
                    ProviderOperationAttempt.status.in_(
                        ("provider_submitting", "unknown")
                    ),
                )
                .order_by(
                    ProviderOperationAttempt.created_at.asc(),
                    ProviderOperationAttempt.id.asc(),
                )
                .limit(1)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
            if attempt is None:
                return None
            shipment = session.scalar(
                sa.select(OutboundShipment)
                .where(OutboundShipment.id == attempt.shipment_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                shipment is None
                or shipment.provider != "sf"
                or attempt.integration_secret_revision_uuid
                != shipment.integration_secret_revision_uuid
                or attempt.provider_account_secret_revision_uuid
                != shipment.provider_account_secret_revision_uuid
                or attempt.binding_revision != shipment.binding_revision
            ):
                raise SfWaybillReconciliationConflict()
            ShippingExecutionService(session).begin_unknown_provider_reconciliation(
                attempt_id=attempt.id,
                started_at=current_time,
            )
            return SfWaybillReconciliationSnapshot(
                tenant_uuid=prepared.tenant_uuid,
                shipment_uuid=shipment.id,
                attempt_uuid=attempt.id,
                origin_warehouse_uuid=shipment.origin_warehouse_uuid,
                integration_uuid=shipment.integration_uuid,
                provider_account_uuid=shipment.provider_account_uuid,
                integration_secret_revision_uuid=(
                    shipment.integration_secret_revision_uuid
                ),
                provider_account_secret_revision_uuid=(
                    shipment.provider_account_secret_revision_uuid
                ),
                binding_revision=shipment.binding_revision,
            )

    def record_result(
        self,
        prepared: PreparedSfWaybillReconciliationJob,
        *,
        snapshot: SfWaybillReconciliationSnapshot,
        result: SfWaybillQueryResult,
        finished_at: datetime,
    ) -> StoredSfWaybillReconciliation:
        _prepared(prepared)
        if (
            not isinstance(snapshot, SfWaybillReconciliationSnapshot)
            or snapshot.tenant_uuid != prepared.tenant_uuid
            or not isinstance(result, SfWaybillQueryResult)
        ):
            raise SfWaybillReconciliationInputError()
        with self._transactions(_tenant_context(prepared)) as session:
            _require_transaction(session)
            ShippingExecutionService(session).reconcile_unknown_provider_attempt(
                attempt_id=snapshot.attempt_uuid,
                resolution=result.resolution,
                reconciled_at=_utc(finished_at),
                safe_provider_code=result.safe_provider_code,
                waybill_no=result.waybill_no,
                response_hash=result.response_hash,
            )
            relay_signal = None
            if result.resolution is UnknownResolution.CONFIRMED_SUCCESS:
                relay_signal = RelayShipmentResultSignalService.capture(
                    tenant_session=session,
                    attempt_uuid=snapshot.attempt_uuid,
                )
            return StoredSfWaybillReconciliation(
                shipment_uuid=snapshot.shipment_uuid,
                attempt_uuid=snapshot.attempt_uuid,
                resolution=result.resolution,
                relay_signal=relay_signal,
            )


class SqlAlchemySfWaybillQueryCredentialSource:
    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        root_key_directory: str | Path,
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise TypeError("control database is required")
        directory = Path(root_key_directory)
        if not directory.is_absolute():
            raise ValueError("root key directory must be absolute")
        self._database = control_database
        self._root_key_directory = directory

    def prepare(
        self,
        *,
        job: PreparedSfWaybillReconciliationJob,
        snapshot: SfWaybillReconciliationSnapshot,
    ) -> SfWaybillQueryRequest:
        _prepared(job)
        if (
            not isinstance(snapshot, SfWaybillReconciliationSnapshot)
            or snapshot.tenant_uuid != job.tenant_uuid
        ):
            raise SfWaybillReconciliationInputError()
        with self._database.transaction() as session:
            key_ring = SqlAlchemyRootKeyRegistry(session=session).load(
                self._root_key_directory
            )
            return SfWaybillCredentialFactory(session).prepare_query(
                tenant_uuid=job.tenant_uuid,
                warehouse_uuid=snapshot.origin_warehouse_uuid,
                integration_uuid=snapshot.integration_uuid,
                provider_account_uuid=snapshot.provider_account_uuid,
                integration_secret_revision_uuid=(
                    snapshot.integration_secret_revision_uuid
                ),
                provider_account_secret_revision_uuid=(
                    snapshot.provider_account_secret_revision_uuid
                ),
                binding_revision=snapshot.binding_revision,
                shipment_uuid=snapshot.shipment_uuid,
                root_key_ring=key_ring,
            )


class SfWaybillReconciliationJobHandler:
    crosses_provider_boundary = True
    recovery_category = RecoveryCategory.SF

    def __init__(
        self,
        *,
        store: SfWaybillReconciliationStore,
        credential_source: SfWaybillQueryCredentialSource,
        provider_dispatcher: SfWaybillQueryProvider,
        call_authorizer: DurableProviderCallAuthorizer,
        relay_enqueuer: RelayCommittedShipmentResultEnqueuer,
        clock: Callable[[], datetime],
    ) -> None:
        if (
            not all(
                callable(getattr(store, method, None))
                for method in ("claim_one", "record_result")
            )
            or not callable(getattr(credential_source, "prepare", None))
            or not callable(getattr(provider_dispatcher, "dispatch", None))
            or not callable(getattr(call_authorizer, "authorize", None))
            or not callable(getattr(relay_enqueuer, "enqueue", None))
            or not callable(clock)
        ):
            raise TypeError("SF waybill reconciliation composition is invalid")
        self._store = store
        self._credentials = credential_source
        self._provider = provider_dispatcher
        self._authorizer = call_authorizer
        self._relay = relay_enqueuer
        self._clock = clock

    def prepare(self, job: BackgroundJob) -> PreparedJob:
        return PreparedJob(_parse_job(job))

    def execute(self, job: BackgroundJob, prepared: PreparedJob) -> JobOutcome:
        value = prepared.value
        if not isinstance(value, PreparedSfWaybillReconciliationJob):
            raise SfWaybillReconciliationInputError()
        initial = self._authorizer.authorize(job)
        if not initial.allowed:
            return _review(initial.reason_code or "tenant_gate_denied")
        try:
            snapshot = self._store.claim_one(
                value,
                started_at=_utc(self._clock()),
            )
        except (SfWaybillReconciliationError, ShippingExecutionError):
            return _review("sf_waybill_reconciliation_claim_failed")
        if snapshot is None:
            return JobOutcome(
                OutcomeDisposition.SUCCEEDED,
                safe_result={"reconciled": False},
            )
        try:
            request = self._credentials.prepare(job=value, snapshot=snapshot)
        except (SfWaybillReconciliationError, SfWaybillCredentialError):
            return _review("sf_waybill_query_prepare_failed")

        before_query = self._authorizer.authorize(job)
        if not before_query.allowed:
            request.discard_credentials()
            return _review(before_query.reason_code or "tenant_gate_denied")
        try:
            result = self._provider.dispatch(request)
        finally:
            request.discard_credentials()
        try:
            final_authority = self._authorizer.authorize(job)
        except Exception:
            final_authority = AuthorityVerdict(
                False,
                "tenant_authority_unavailable",
            )
        try:
            stored = self._store.record_result(
                value,
                snapshot=snapshot,
                result=result,
                finished_at=_utc(self._clock()),
            )
        except (SfWaybillReconciliationError, ShippingExecutionError):
            return _review("sf_waybill_reconciliation_result_failed")

        direct_enqueued = False
        if stored.relay_signal is not None and final_authority.allowed:
            try:
                self._relay.enqueue(
                    tenant_uuid=value.tenant_uuid,
                    signal=stored.relay_signal,
                    available_at=_utc(self._clock()),
                    request_id=value.request_id,
                    correlation_id=job.correlation_id,
                )
                direct_enqueued = True
            except Exception:
                direct_enqueued = False
        safe_result = {
            "reconciled": True,
            "shipment_uuid": stored.shipment_uuid,
            "resolution": stored.resolution.value,
            "relay_direct_enqueued": direct_enqueued,
        }
        if not final_authority.allowed:
            return JobOutcome(
                OutcomeDisposition.REVIEW,
                safe_result=safe_result,
                reason_code=(final_authority.reason_code or "tenant_gate_denied"),
            )
        if result.resolution is UnknownResolution.STILL_UNKNOWN:
            return JobOutcome(
                OutcomeDisposition.REVIEW,
                safe_result=safe_result,
                reason_code="sf_waybill_result_still_unknown",
            )
        return JobOutcome(
            OutcomeDisposition.SUCCEEDED,
            safe_result=safe_result,
        )


def sf_waybill_reconciliation_job_definition() -> PeriodicJobDefinition:
    return PeriodicJobDefinition(
        job_type=SF_WAYBILL_RECONCILIATION_JOB_TYPE,
        interval=SF_WAYBILL_RECONCILIATION_INTERVAL,
        not_after_window=SF_WAYBILL_RECONCILIATION_INTERVAL,
        resource_key=SF_WAYBILL_RECONCILIATION_RESOURCE_KEY,
        payload_builder=_scheduled_payload,
        priority=80,
        max_attempts=1,
    )


def _scheduled_payload(
    session: Session,
    tenant: Tenant,
    cycle: ScheduleCycle,
) -> dict[str, object]:
    del session, tenant, cycle
    return {"contract_version": 1}


def _parse_job(job: BackgroundJob) -> PreparedSfWaybillReconciliationJob:
    expected_key_prefix = f"scheduler:{SF_WAYBILL_RECONCILIATION_JOB_TYPE}:"
    if (
        not isinstance(job, BackgroundJob)
        or job.job_type != SF_WAYBILL_RECONCILIATION_JOB_TYPE
        or job.resource_key != SF_WAYBILL_RECONCILIATION_RESOURCE_KEY
        or job.requested_by_type != "scheduler"
        or not isinstance(job.idempotency_key, str)
        or not job.idempotency_key.startswith(expected_key_prefix)
        or job.payload != {"contract_version": 1}
        or job.max_attempts != 1
    ):
        raise SfWaybillReconciliationInputError()
    try:
        return PreparedSfWaybillReconciliationJob(
            job_uuid=str(UUID(job.id)),
            tenant_uuid=str(UUID(job.tenant_id)),
            tenant_access_version=_positive(job.tenant_access_version),
            request_id=job.correlation_id or job.request_id or job.id,
        )
    except (TypeError, ValueError):
        raise SfWaybillReconciliationInputError() from None


def _tenant_context(
    prepared: PreparedSfWaybillReconciliationJob,
) -> TenantContext:
    return TenantContext(
        tenant_id=UUID(prepared.tenant_uuid),
        access_version=prepared.tenant_access_version,
        source=TenantContextSource.WORKER_JOB,
        principal_ref="sf-waybill-reconciliation-worker",
        source_ref=prepared.job_uuid,
        request_id=prepared.request_id,
    )


def _prepared(value: object) -> PreparedSfWaybillReconciliationJob:
    if not isinstance(value, PreparedSfWaybillReconciliationJob):
        raise SfWaybillReconciliationInputError()
    return value


def _require_transaction(session: Session) -> None:
    require_caller_transaction(session, SfWaybillReconciliationInputError)


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError
    return value


def _utc(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("worker clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _review(reason_code: str) -> JobOutcome:
    return JobOutcome(OutcomeDisposition.REVIEW, reason_code=reason_code)


__all__ = [
    "PreparedSfWaybillReconciliationJob",
    "SF_WAYBILL_RECONCILIATION_INTERVAL",
    "SF_WAYBILL_RECONCILIATION_JOB_TYPE",
    "SF_WAYBILL_RECONCILIATION_RESOURCE_KEY",
    "SfWaybillReconciliationConflict",
    "SfWaybillReconciliationError",
    "SfWaybillReconciliationInputError",
    "SfWaybillReconciliationJobHandler",
    "SfWaybillReconciliationSnapshot",
    "SqlAlchemySfWaybillQueryCredentialSource",
    "SqlAlchemySfWaybillReconciliationStore",
    "StoredSfWaybillReconciliation",
    "sf_waybill_reconciliation_job_definition",
]
