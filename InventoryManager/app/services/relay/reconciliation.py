"""Periodic, provider-free reconciliation of committed relay shipments."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable, Final, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.rental_relay_case import RentalRelayCase
from app.models.shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
)
from app.services.relay.external_projection import (
    RelayExternalProjectionError,
    RelayExternalProjectionReceipt,
    RelayExternalProjectionService,
)
from app.services.relay.result_signal import (
    RelayShipmentResultSignalError,
    RelayShipmentResultSignalService,
)
from app.tenancy import TenantContext, TenantContextSource
from inventory_control.jobs import (
    JobOutcome,
    OutcomeDisposition,
    PeriodicJobDefinition,
    PreparedJob,
    ScheduleCycle,
)
from inventory_control.models.foundation import Tenant
from inventory_control.models.jobs import BackgroundJob
from inventory_control.transactions import require_caller_transaction


RELAY_EXTERNAL_RECONCILIATION_JOB_TYPE: Final = "relay_external_stage_reconcile"
RELAY_EXTERNAL_RECONCILIATION_RESOURCE_KEY: Final = (
    "relay:external-stage-reconciliation"
)
RELAY_EXTERNAL_RECONCILIATION_INTERVAL: Final = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class PreparedRelayExternalReconciliationJob:
    job_uuid: str
    tenant_uuid: str
    tenant_access_version: int
    request_id: str
    tenant_timezone: str


class RelayExternalReconciliationService:
    """Project the oldest eligible relay shipment in one tenant transaction."""

    @classmethod
    def reconcile_one(
        cls,
        *,
        tenant_session: Session,
        tenant_timezone: str,
    ) -> RelayExternalProjectionReceipt | None:
        _require_explicit_transaction(tenant_session)
        selected_timezone = _timezone_name(tenant_timezone)
        try:
            candidate = tenant_session.execute(
                sa.select(ProviderOperationAttempt.id)
                .join(
                    OutboundShipment,
                    OutboundShipment.id == ProviderOperationAttempt.shipment_id,
                )
                .join(
                    RentalRelayCase,
                    RentalRelayCase.successor_rental_id == OutboundShipment.rental_id,
                )
                .where(
                    OutboundShipment.provider == "sf",
                    OutboundShipment.status == "submitted",
                    OutboundShipment.waybill_no.is_not(None),
                    OutboundShipment.submitted_at.is_not(None),
                    RentalRelayCase.status == "agreed",
                    ProviderOperationAttempt.operation == "create_waybill",
                    ProviderOperationAttempt.status == "succeeded",
                    ProviderOperationAttempt.response_hash.is_not(None),
                )
                .order_by(
                    OutboundShipment.submitted_at.asc(),
                    OutboundShipment.id.asc(),
                    ProviderOperationAttempt.attempt_no.asc(),
                )
                .limit(1)
                .execution_options(autoflush=False)
            ).scalar_one_or_none()
        except SQLAlchemyError:
            raise RelayExternalProjectionError() from None
        if candidate is None:
            return None

        try:
            signal = RelayShipmentResultSignalService.capture(
                tenant_session=tenant_session,
                attempt_uuid=candidate,
            )
            if signal is None:
                return None
            command = signal.command(tenant_timezone=selected_timezone)
        except RelayShipmentResultSignalError:
            raise RelayExternalProjectionError() from None
        return RelayExternalProjectionService.apply(
            tenant_session=tenant_session,
            command=command,
        )


class RelayExternalReconciliationStore(Protocol):
    def reconcile(
        self,
        prepared: PreparedRelayExternalReconciliationJob,
    ) -> RelayExternalProjectionReceipt | None:
        ...


TenantTransactionProvider = Callable[[TenantContext], AbstractContextManager[Session]]


class SqlAlchemyRelayExternalReconciliationStore:
    def __init__(self, transaction_provider: TenantTransactionProvider) -> None:
        if not callable(transaction_provider):
            raise TypeError("tenant transaction provider is required")
        self._transaction_provider = transaction_provider

    def reconcile(
        self,
        prepared: PreparedRelayExternalReconciliationJob,
    ) -> RelayExternalProjectionReceipt | None:
        if not isinstance(prepared, PreparedRelayExternalReconciliationJob):
            raise TypeError("prepared relay reconciliation job is invalid")
        context = TenantContext(
            tenant_id=UUID(prepared.tenant_uuid),
            access_version=prepared.tenant_access_version,
            source=TenantContextSource.WORKER_JOB,
            principal_ref="relay-external-reconciliation-worker",
            source_ref=prepared.job_uuid,
            request_id=prepared.request_id,
        )
        with self._transaction_provider(context) as tenant_session:
            return RelayExternalReconciliationService.reconcile_one(
                tenant_session=tenant_session,
                tenant_timezone=prepared.tenant_timezone,
            )


class RelayExternalReconciliationJobHandler:
    crosses_provider_boundary = False
    recovery_category = None

    def __init__(self, *, store: RelayExternalReconciliationStore) -> None:
        if not callable(getattr(store, "reconcile", None)):
            raise TypeError("relay external reconciliation store is required")
        self._store = store

    def prepare(self, job: BackgroundJob) -> PreparedJob:
        return PreparedJob(_parse_job(job))

    def execute(self, job: BackgroundJob, prepared: PreparedJob) -> JobOutcome:
        del job
        value = prepared.value
        if not isinstance(value, PreparedRelayExternalReconciliationJob):
            raise TypeError("prepared relay reconciliation job is invalid")
        try:
            receipt = self._store.reconcile(value)
        except RelayExternalProjectionError:
            return JobOutcome(
                OutcomeDisposition.REVIEW,
                reason_code="relay_reconciliation_conflict",
            )
        if receipt is None:
            return JobOutcome(
                OutcomeDisposition.SUCCEEDED,
                safe_result={"projected": False},
            )
        return JobOutcome(
            OutcomeDisposition.SUCCEEDED,
            safe_result={
                "projected": True,
                "stage": "shipped",
                "relay_status": receipt.status,
            },
        )


def relay_external_reconciliation_job_definition() -> PeriodicJobDefinition:
    return PeriodicJobDefinition(
        job_type=RELAY_EXTERNAL_RECONCILIATION_JOB_TYPE,
        interval=RELAY_EXTERNAL_RECONCILIATION_INTERVAL,
        not_after_window=RELAY_EXTERNAL_RECONCILIATION_INTERVAL,
        resource_key=RELAY_EXTERNAL_RECONCILIATION_RESOURCE_KEY,
        payload_builder=_scheduled_payload,
        priority=70,
        max_attempts=3,
    )


def _scheduled_payload(
    session: Session,
    tenant: Tenant,
    cycle: ScheduleCycle,
) -> dict[str, object]:
    del session, cycle
    return {
        "contract_version": 1,
        "tenant_timezone": _timezone_name(tenant.timezone),
    }


def _parse_job(job: BackgroundJob) -> PreparedRelayExternalReconciliationJob:
    expected_payload = {"contract_version", "tenant_timezone"}
    expected_key_prefix = f"scheduler:{RELAY_EXTERNAL_RECONCILIATION_JOB_TYPE}:"
    if (
        not isinstance(job, BackgroundJob)
        or job.job_type != RELAY_EXTERNAL_RECONCILIATION_JOB_TYPE
        or job.resource_key != RELAY_EXTERNAL_RECONCILIATION_RESOURCE_KEY
        or job.requested_by_type != "scheduler"
        or not isinstance(job.idempotency_key, str)
        or not job.idempotency_key.startswith(expected_key_prefix)
        or not isinstance(job.payload, dict)
        or set(job.payload) != expected_payload
        or job.payload.get("contract_version") != 1
    ):
        raise RelayExternalProjectionError()
    try:
        return PreparedRelayExternalReconciliationJob(
            job_uuid=str(UUID(job.id)),
            tenant_uuid=str(UUID(job.tenant_id)),
            tenant_access_version=_positive(job.tenant_access_version),
            request_id=job.correlation_id or job.request_id or job.id,
            tenant_timezone=_timezone_name(job.payload["tenant_timezone"]),
        )
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        raise RelayExternalProjectionError() from None


def _require_explicit_transaction(session: Session) -> None:
    require_caller_transaction(session, RelayExternalProjectionError)


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError
    return value


def _timezone_name(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 64
    ):
        raise ValueError
    ZoneInfo(value)
    return value


__all__ = [
    "PreparedRelayExternalReconciliationJob",
    "RELAY_EXTERNAL_RECONCILIATION_INTERVAL",
    "RELAY_EXTERNAL_RECONCILIATION_JOB_TYPE",
    "RELAY_EXTERNAL_RECONCILIATION_RESOURCE_KEY",
    "RelayExternalReconciliationJobHandler",
    "RelayExternalReconciliationService",
    "RelayExternalReconciliationStore",
    "SqlAlchemyRelayExternalReconciliationStore",
    "relay_external_reconciliation_job_definition",
]
