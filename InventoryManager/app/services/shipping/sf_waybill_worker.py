"""Durable SF create-waybill worker over control and tenant ledgers."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session, SessionTransactionOrigin

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
    SfWaybillProviderResult,
)
from app.services.shipping_execution_service import (
    ProviderOutcome,
    ShippingExecutionError,
    ShippingExecutionService,
)
from inventory_control import ControlDatabase
from inventory_control.crypto import SqlAlchemyRootKeyRegistry
from inventory_control.integrations import (
    SfCreateWaybillRequest,
    SfWaybillCredentialError,
    SfWaybillCredentialFactory,
)
from inventory_control.jobs import (
    DurableProviderCallAuthorizer,
    AuthorityVerdict,
    JobOutcome,
    OutcomeDisposition,
    PreparedJob,
    RecoveryCategory,
)
from inventory_control.jobs.service import ControlJobService
from inventory_control.models.foundation import Tenant
from inventory_control.models.jobs import BackgroundJob


SF_CREATE_WAYBILL_JOB_TYPE = "sf_create_waybill"


class SfWaybillWorkerError(RuntimeError):
    code = "SF_WAYBILL_WORKER_FAILED"
    public_message = "SF waybill execution failed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class SfWaybillWorkerInputError(SfWaybillWorkerError):
    code = "SF_WAYBILL_WORKER_INPUT_INVALID"


class SfWaybillWorkerConflict(SfWaybillWorkerError):
    code = "SF_WAYBILL_WORKER_CONFLICT"


@dataclass(frozen=True, slots=True)
class PreparedSfWaybillJob:
    job_uuid: str
    tenant_uuid: str
    tenant_access_version: int
    shipment_uuid: str
    attempt_uuid: str
    request_id: str


@dataclass(frozen=True, slots=True, repr=False)
class SfWaybillSubmissionSnapshot:
    tenant_uuid: str
    shipment_uuid: str
    attempt_uuid: str
    origin_warehouse_uuid: str
    integration_uuid: str
    provider_account_uuid: str
    integration_secret_revision_uuid: str
    provider_account_secret_revision_uuid: str
    binding_revision: int
    sender_snapshot: Mapping[str, object]
    receiver_snapshot: Mapping[str, object]
    cargo_snapshot: Mapping[str, object]
    express_type_id: int
    scheduled_dispatch_at: datetime

    def __repr__(self) -> str:
        return (
            "SfWaybillSubmissionSnapshot("
            f"shipment_uuid={self.shipment_uuid!r}, "
            f"attempt_uuid={self.attempt_uuid!r}, "
            "sender=<redacted>, receiver=<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class StoredSfWaybillResult:
    shipment_uuid: str
    attempt_uuid: str
    outcome: ProviderOutcome
    relay_signal: RelayShipmentSubmissionSignal | None


class SfWaybillTenantStore(Protocol):
    def load_snapshot(
        self,
        prepared: PreparedSfWaybillJob,
    ) -> SfWaybillSubmissionSnapshot: ...

    def mark_submitting(
        self,
        prepared: PreparedSfWaybillJob,
        *,
        started_at: datetime,
    ) -> None: ...

    def record_result(
        self,
        prepared: PreparedSfWaybillJob,
        *,
        result: SfWaybillProviderResult,
        finished_at: datetime,
    ) -> StoredSfWaybillResult: ...


class SfWaybillCredentialSource(Protocol):
    def prepare(
        self,
        *,
        job: PreparedSfWaybillJob,
        snapshot: SfWaybillSubmissionSnapshot,
    ) -> SfCreateWaybillRequest: ...


class SfWaybillDispatcher(Protocol):
    def dispatch(
        self,
        request: SfCreateWaybillRequest,
    ) -> SfWaybillProviderResult: ...


TenantTransactionProvider = Callable[
    [PreparedSfWaybillJob], AbstractContextManager[Session]
]


class SqlAlchemySfWaybillTenantStore:
    """Own the three short tenant transactions around provider I/O."""

    def __init__(self, transaction_provider: TenantTransactionProvider) -> None:
        if not callable(transaction_provider):
            raise TypeError("tenant transaction provider is required")
        self._transactions = transaction_provider

    def load_snapshot(
        self,
        prepared: PreparedSfWaybillJob,
    ) -> SfWaybillSubmissionSnapshot:
        _prepared(prepared)
        with self._transactions(prepared) as session:
            _require_transaction(session)
            attempt = session.scalar(
                sa.select(ProviderOperationAttempt)
                .where(ProviderOperationAttempt.id == prepared.attempt_uuid)
                .with_for_update()
            )
            shipment = session.scalar(
                sa.select(OutboundShipment)
                .where(OutboundShipment.id == prepared.shipment_uuid)
                .with_for_update()
            )
            if (
                attempt is None
                or shipment is None
                or attempt.shipment_id != shipment.id
                or attempt.operation != "create_waybill"
                or attempt.status != "prepared"
                or shipment.status not in {"prepared", "failed"}
                or attempt.background_job_uuid not in {None, prepared.job_uuid}
                or attempt.integration_secret_revision_uuid
                != shipment.integration_secret_revision_uuid
                or attempt.provider_account_secret_revision_uuid
                != shipment.provider_account_secret_revision_uuid
                or attempt.binding_revision != shipment.binding_revision
            ):
                raise SfWaybillWorkerConflict()
            return SfWaybillSubmissionSnapshot(
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
                sender_snapshot=dict(shipment.sender_snapshot),
                receiver_snapshot=dict(shipment.receiver_snapshot),
                cargo_snapshot=dict(shipment.cargo_snapshot),
                express_type_id=shipment.express_type_id,
                scheduled_dispatch_at=shipment.scheduled_dispatch_at,
            )

    def mark_submitting(
        self,
        prepared: PreparedSfWaybillJob,
        *,
        started_at: datetime,
    ) -> None:
        _prepared(prepared)
        with self._transactions(prepared) as session:
            ShippingExecutionService(session).mark_provider_submitting(
                attempt_id=prepared.attempt_uuid,
                expected_status="prepared",
                started_at=_utc(started_at),
            )

    def record_result(
        self,
        prepared: PreparedSfWaybillJob,
        *,
        result: SfWaybillProviderResult,
        finished_at: datetime,
    ) -> StoredSfWaybillResult:
        _prepared(prepared)
        if not isinstance(result, SfWaybillProviderResult):
            raise SfWaybillWorkerInputError()
        with self._transactions(prepared) as session:
            ShippingExecutionService(session).record_provider_result(
                attempt_id=prepared.attempt_uuid,
                expected_status="provider_submitting",
                outcome=result.outcome,
                finished_at=_utc(finished_at),
                waybill_no=result.waybill_no,
                safe_provider_code=result.safe_provider_code,
                response_hash=result.response_hash,
                latency_ms=result.latency_ms,
            )
            signal = None
            if result.outcome is ProviderOutcome.SUCCESS:
                signal = RelayShipmentResultSignalService.capture(
                    tenant_session=session,
                    attempt_uuid=prepared.attempt_uuid,
                )
            return StoredSfWaybillResult(
                shipment_uuid=prepared.shipment_uuid,
                attempt_uuid=prepared.attempt_uuid,
                outcome=result.outcome,
                relay_signal=signal,
            )


class SqlAlchemySfWaybillCredentialSource:
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
        job: PreparedSfWaybillJob,
        snapshot: SfWaybillSubmissionSnapshot,
    ) -> SfCreateWaybillRequest:
        _prepared(job)
        if (
            not isinstance(snapshot, SfWaybillSubmissionSnapshot)
            or snapshot.tenant_uuid != job.tenant_uuid
            or snapshot.shipment_uuid != job.shipment_uuid
            or snapshot.attempt_uuid != job.attempt_uuid
        ):
            raise SfWaybillWorkerInputError()
        with self._database.transaction() as session:
            key_ring = SqlAlchemyRootKeyRegistry(session=session).load(
                self._root_key_directory
            )
            return SfWaybillCredentialFactory(session).prepare_create(
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
                sender_snapshot=snapshot.sender_snapshot,
                receiver_snapshot=snapshot.receiver_snapshot,
                cargo_snapshot=snapshot.cargo_snapshot,
                express_type_id=snapshot.express_type_id,
                scheduled_dispatch_at=snapshot.scheduled_dispatch_at,
                root_key_ring=key_ring,
            )


class SfCreateWaybillJobHandler:
    crosses_provider_boundary = True
    recovery_category = RecoveryCategory.SF

    def __init__(
        self,
        *,
        tenant_store: SfWaybillTenantStore,
        credential_source: SfWaybillCredentialSource,
        provider_dispatcher: SfWaybillDispatcher,
        call_authorizer: DurableProviderCallAuthorizer,
        relay_enqueuer: RelayCommittedShipmentResultEnqueuer,
        clock: Callable[[], datetime],
    ) -> None:
        if (
            not all(
                callable(getattr(tenant_store, method, None))
                for method in ("load_snapshot", "mark_submitting", "record_result")
            )
            or not callable(getattr(credential_source, "prepare", None))
            or not callable(getattr(provider_dispatcher, "dispatch", None))
            or not callable(getattr(call_authorizer, "authorize", None))
            or not callable(getattr(relay_enqueuer, "enqueue", None))
            or not callable(clock)
        ):
            raise TypeError("SF create-waybill job composition is invalid")
        self._tenant = tenant_store
        self._credentials = credential_source
        self._provider = provider_dispatcher
        self._authorizer = call_authorizer
        self._relay = relay_enqueuer
        self._clock = clock

    def prepare(self, job: BackgroundJob) -> PreparedJob:
        return PreparedJob(_parse_job(job))

    def execute(self, job: BackgroundJob, prepared: PreparedJob) -> JobOutcome:
        value = prepared.value
        if not isinstance(value, PreparedSfWaybillJob):
            raise SfWaybillWorkerInputError()
        initial = self._authorizer.authorize(job)
        if not initial.allowed:
            return _review(initial.reason_code or "tenant_gate_denied")
        try:
            snapshot = self._tenant.load_snapshot(value)
            request = self._credentials.prepare(job=value, snapshot=snapshot)
        except (SfWaybillWorkerError, SfWaybillCredentialError):
            return _review("sf_waybill_prepare_failed")

        try:
            self._tenant.mark_submitting(
                value,
                started_at=_utc(self._clock()),
            )
        except (SfWaybillWorkerError, ShippingExecutionError):
            request.discard_credentials()
            return _review("sf_waybill_submission_fence_failed")

        before_call = self._authorizer.authorize(job)
        if not before_call.allowed:
            request.discard_credentials()
            stored = self._tenant.record_result(
                value,
                result=SfWaybillProviderResult(
                    outcome=ProviderOutcome.DEFINITIVE_FAILURE,
                    safe_provider_code="TENANT_AUTHORITY_DENIED",
                ),
                finished_at=_utc(self._clock()),
            )
            del stored
            return _review(before_call.reason_code or "tenant_gate_denied")

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
        stored = self._tenant.record_result(
            value,
            result=result,
            finished_at=_utc(self._clock()),
        )
        direct_enqueued = False
        if (
            result.outcome is ProviderOutcome.SUCCESS
            and stored.relay_signal is not None
            and final_authority.allowed
        ):
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
                # The committed tenant ledger is authoritative.  Periodic
                # reconciliation will derive the identical signal.
                direct_enqueued = False

        safe_result = {
            "shipment_uuid": value.shipment_uuid,
            "provider_outcome": result.outcome.value,
            "relay_direct_enqueued": direct_enqueued,
        }
        if not final_authority.allowed:
            return JobOutcome(
                OutcomeDisposition.REVIEW,
                safe_result=safe_result,
                reason_code=(
                    final_authority.reason_code or "tenant_gate_denied"
                ),
            )
        if result.outcome is ProviderOutcome.UNKNOWN:
            return JobOutcome(
                OutcomeDisposition.REVIEW,
                safe_result=safe_result,
                reason_code="sf_provider_result_unknown",
            )
        return JobOutcome(OutcomeDisposition.SUCCEEDED, safe_result=safe_result)


class SfCreateWaybillJobCoordinator:
    """Enqueue one current-tenant job after the tenant intent is committed."""

    def __init__(self, service: ControlJobService | None = None) -> None:
        self._service = service or ControlJobService()

    def enqueue(
        self,
        control_session: Session,
        *,
        tenant_uuid: str | UUID,
        tenant_access_version: int,
        shipment_uuid: str | UUID,
        attempt_uuid: str | UUID,
        requested_by_user_uuid: str | UUID,
        available_at: datetime,
        job_uuid: str | UUID | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> BackgroundJob:
        _require_transaction(control_session)
        try:
            tenant_id = _uuid(tenant_uuid)
            shipment_id = _uuid(shipment_uuid)
            attempt_id = _uuid(attempt_uuid)
            actor_id = _uuid(requested_by_user_uuid)
            selected_job_id = _uuid(job_uuid) if job_uuid is not None else None
            access_version = _positive(tenant_access_version)
            current_time = _utc(available_at)
        except (TypeError, ValueError):
            raise SfWaybillWorkerInputError() from None
        tenant = control_session.scalar(
            sa.select(Tenant)
            .where(Tenant.id == tenant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            tenant is None
            or tenant.status != "active"
            or tenant.access_version != access_version
        ):
            raise SfWaybillWorkerConflict()
        return self._service.enqueue_job(
            control_session,
            tenant_id=tenant_id,
            tenant_access_version=access_version,
            job_type=SF_CREATE_WAYBILL_JOB_TYPE,
            resource_key=f"sf-shipment:{shipment_id}",
            payload={
                "contract_version": 1,
                "shipment_uuid": shipment_id,
                "attempt_uuid": attempt_id,
            },
            idempotency_key=f"sf-create:{attempt_id}",
            requested_by_type="tenant_user",
            requested_by_id=actor_id,
            request_id=request_id,
            correlation_id=correlation_id,
            job_id=selected_job_id,
            priority=90,
            max_attempts=1,
            available_at=current_time,
        )


def _parse_job(job: BackgroundJob) -> PreparedSfWaybillJob:
    expected = {"contract_version", "shipment_uuid", "attempt_uuid"}
    if (
        not isinstance(job, BackgroundJob)
        or job.job_type != SF_CREATE_WAYBILL_JOB_TYPE
        or job.requested_by_type != "tenant_user"
        or not isinstance(job.payload, dict)
        or set(job.payload) != expected
        or job.payload.get("contract_version") != 1
    ):
        raise SfWaybillWorkerInputError()
    try:
        tenant_id = _uuid(job.tenant_id)
        shipment_id = _uuid(job.payload["shipment_uuid"])
        attempt_id = _uuid(job.payload["attempt_uuid"])
        if (
            job.resource_key != f"sf-shipment:{shipment_id}"
            or job.idempotency_key != f"sf-create:{attempt_id}"
        ):
            raise SfWaybillWorkerInputError()
        return PreparedSfWaybillJob(
            job_uuid=_uuid(job.id),
            tenant_uuid=tenant_id,
            tenant_access_version=_positive(job.tenant_access_version),
            shipment_uuid=shipment_id,
            attempt_uuid=attempt_id,
            request_id=job.correlation_id or job.request_id or job.id,
        )
    except (KeyError, TypeError, ValueError):
        raise SfWaybillWorkerInputError() from None


def _review(reason_code: str) -> JobOutcome:
    return JobOutcome(OutcomeDisposition.REVIEW, reason_code=reason_code)


def _prepared(value: object) -> PreparedSfWaybillJob:
    if not isinstance(value, PreparedSfWaybillJob):
        raise SfWaybillWorkerInputError()
    return value


def _require_transaction(session: Session) -> None:
    transaction = session.get_transaction() if isinstance(session, Session) else None
    if (
        transaction is None
        or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
    ):
        raise SfWaybillWorkerInputError()


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError
    return value


def _uuid(value: str | UUID) -> str:
    parsed = value if isinstance(value, UUID) else UUID(str(value))
    if parsed.int == 0:
        raise ValueError
    return str(parsed)


def _utc(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("worker clock must be timezone-aware")
    return value.astimezone(timezone.utc)


__all__ = [
    "PreparedSfWaybillJob",
    "SF_CREATE_WAYBILL_JOB_TYPE",
    "SfCreateWaybillJobCoordinator",
    "SfCreateWaybillJobHandler",
    "SfWaybillCredentialSource",
    "SfWaybillDispatcher",
    "SfWaybillSubmissionSnapshot",
    "SfWaybillTenantStore",
    "SfWaybillWorkerConflict",
    "SfWaybillWorkerError",
    "SfWaybillWorkerInputError",
    "SqlAlchemySfWaybillCredentialSource",
    "SqlAlchemySfWaybillTenantStore",
    "StoredSfWaybillResult",
]
