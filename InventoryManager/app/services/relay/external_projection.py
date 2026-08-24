"""Durable, provider-free relay projection from committed shipment facts."""

from __future__ import annotations

import re
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Callable, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, SessionTransactionOrigin

from app.models.audit_log import AuditLog
from app.models.rental_relay_case import RentalRelayCase
from app.models.shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
)
from app.services.relay.mutation_service import (
    RelayManualMutationResult,
    RelayStatusMutationConflict,
    RelayStatusMutationError,
    RelayStatusMutationPersistenceError,
    RelayStatusMutationService,
)
from app.services.shipping.tracking_ledger import (
    ShipmentTrackingLedgerError,
    ShipmentTrackingLedgerService,
)
from app.tenancy import TenantContext, TenantContextSource
from inventory_control.jobs import (
    JobOutcome,
    OutcomeDisposition,
    PreparedJob,
)
from inventory_control.jobs.service import ControlJobService
from inventory_control.models.jobs import BackgroundJob


RELAY_EXTERNAL_PROJECTION_JOB_TYPE = "relay_external_stage_projection"
_RESULT_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_AUDITS_PER_STAGE = 32


class RelayExternalStage(str, Enum):
    SHIPPED = "shipped"
    COMPLETED = "completed"


class RelayExternalProjectionError(RuntimeError):
    code = "RELAY_EXTERNAL_PROJECTION_FAILED"
    public_message = "relay external stage projection failed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class RelayExternalProjectionInputError(RelayExternalProjectionError):
    code = "RELAY_EXTERNAL_PROJECTION_INPUT_INVALID"


class RelayExternalProjectionConflict(RelayExternalProjectionError):
    code = "RELAY_EXTERNAL_PROJECTION_CONFLICT"


class RelayExternalProjectionPersistenceError(RelayExternalProjectionError):
    code = "RELAY_EXTERNAL_PROJECTION_PERSISTENCE_FAILED"


@dataclass(frozen=True, slots=True)
class RelayExternalProjectionCommand:
    shipment_uuid: str
    predecessor_rental_id: int
    successor_rental_id: int
    stage: RelayExternalStage
    waybill_no: str
    source_result_digest: str
    occurred_at: datetime
    tenant_timezone: str

    def __post_init__(self) -> None:
        try:
            shipment_uuid = str(UUID(self.shipment_uuid))
            stage = RelayExternalStage(self.stage)
            predecessor_id = _positive(self.predecessor_rental_id)
            successor_id = _positive(self.successor_rental_id)
            waybill_no = _text(self.waybill_no, maximum=50)
            source_digest = self.source_result_digest
            occurred_at = _utc(self.occurred_at)
            tenant_timezone = _timezone_name(self.tenant_timezone)
        except (TypeError, ValueError, ZoneInfoNotFoundError):
            raise RelayExternalProjectionInputError() from None
        if (
            predecessor_id == successor_id
            or not isinstance(source_digest, str)
            or _RESULT_DIGEST.fullmatch(source_digest) is None
        ):
            raise RelayExternalProjectionInputError()
        object.__setattr__(self, "shipment_uuid", shipment_uuid)
        object.__setattr__(self, "predecessor_rental_id", predecessor_id)
        object.__setattr__(self, "successor_rental_id", successor_id)
        object.__setattr__(self, "stage", stage)
        object.__setattr__(self, "waybill_no", waybill_no)
        object.__setattr__(self, "occurred_at", occurred_at)
        object.__setattr__(self, "tenant_timezone", tenant_timezone)

    @property
    def resource_key(self) -> str:
        return f"relay-shipment:{self.shipment_uuid}"

    @property
    def idempotency_key(self) -> str:
        return (
            f"relay-external:{self.stage.value}:"
            f"{self.source_result_digest}"
        )

    @property
    def operation_key(self) -> str:
        digest = sha256(self.idempotency_key.encode("ascii")).hexdigest()
        return f"relay-ext:{digest[:32]}"

    def payload(self) -> dict[str, object]:
        return {
            "contract_version": 1,
            "shipment_uuid": self.shipment_uuid,
            "predecessor_rental_id": self.predecessor_rental_id,
            "successor_rental_id": self.successor_rental_id,
            "stage": self.stage.value,
            "waybill_no": self.waybill_no,
            "source_result_digest": self.source_result_digest,
            "occurred_at": self.occurred_at.isoformat(timespec="microseconds"),
            "tenant_timezone": self.tenant_timezone,
        }


@dataclass(frozen=True, slots=True)
class RelayExternalProjectionReceipt:
    shipment_uuid: str
    relay_case_id: int
    status: str
    source_result_digest: str


@dataclass(frozen=True, slots=True)
class PreparedRelayExternalProjectionJob:
    job_uuid: str
    tenant_uuid: str
    tenant_access_version: int
    request_id: str
    command: RelayExternalProjectionCommand


class RelayExternalProjectionService:
    """Verify committed shipping authority, then reuse the relay solver."""

    @classmethod
    def apply(
        cls,
        *,
        tenant_session: Session,
        command: RelayExternalProjectionCommand,
    ) -> RelayExternalProjectionReceipt:
        _require_explicit_transaction(tenant_session)
        if not isinstance(command, RelayExternalProjectionCommand):
            raise RelayExternalProjectionInputError()
        try:
            cls._lock_and_verify_shipping_source(tenant_session, command)
            result = RelayStatusMutationService.project_external_stage(
                tenant_session=tenant_session,
                predecessor_id=command.predecessor_rental_id,
                successor_id=command.successor_rental_id,
                status=command.stage.value,
                sf_tracking_number=command.waybill_no,
                database_now=command.occurred_at,
                actor_id="relay-external-projection-worker",
                operation_key=command.operation_key,
                tenant_timezone=command.tenant_timezone,
                source_result_digest=command.source_result_digest,
            )
            cls._verify_projection_audit(
                tenant_session,
                result=result,
                command=command,
            )
            if command.stage is RelayExternalStage.COMPLETED:
                result.relay_case.sf_tracking_status = "delivered"
                result.relay_case.sf_tracking_summary = "已签收"
                result.relay_case.sf_last_checked_at = (
                    command.occurred_at.replace(tzinfo=None)
                )
                tenant_session.flush()
            return RelayExternalProjectionReceipt(
                shipment_uuid=command.shipment_uuid,
                relay_case_id=result.relay_case.id,
                status=result.relay_case.status,
                source_result_digest=command.source_result_digest,
            )
        except RelayExternalProjectionError:
            raise
        except RelayStatusMutationConflict:
            raise RelayExternalProjectionConflict() from None
        except RelayStatusMutationPersistenceError:
            raise RelayExternalProjectionPersistenceError() from None
        except RelayStatusMutationError:
            raise RelayExternalProjectionInputError() from None
        except SQLAlchemyError:
            raise RelayExternalProjectionPersistenceError() from None

    @staticmethod
    def _lock_and_verify_shipping_source(
        tenant_session: Session,
        command: RelayExternalProjectionCommand,
    ) -> None:
        attempts = tuple(
            tenant_session.scalars(
                sa.select(ProviderOperationAttempt)
                .where(
                    ProviderOperationAttempt.shipment_id
                    == command.shipment_uuid,
                    ProviderOperationAttempt.operation == "create_waybill",
                )
                .order_by(ProviderOperationAttempt.attempt_no.asc())
                .with_for_update()
            )
        )
        shipment = tenant_session.scalar(
            sa.select(OutboundShipment)
            .where(OutboundShipment.id == command.shipment_uuid)
            .with_for_update()
        )
        succeeded = tuple(
            attempt for attempt in attempts if attempt.status == "succeeded"
        )
        if (
            shipment is None
            or shipment.provider != "sf"
            or shipment.status != "submitted"
            or shipment.rental_id != command.successor_rental_id
            or shipment.waybill_no != command.waybill_no
            or shipment.submitted_at is None
            or len(succeeded) != 1
        ):
            raise RelayExternalProjectionConflict()
        attempt = succeeded[0]
        if (
            attempt.finished_at is None
            or attempt.integration_secret_revision_uuid
            != shipment.integration_secret_revision_uuid
            or attempt.provider_account_secret_revision_uuid
            != shipment.provider_account_secret_revision_uuid
            or attempt.binding_revision != shipment.binding_revision
            or _naive_utc(command.occurred_at) < shipment.submitted_at
            or (
                command.stage is RelayExternalStage.SHIPPED
                and attempt.response_hash != command.source_result_digest
            )
        ):
            raise RelayExternalProjectionConflict()
        if command.stage is RelayExternalStage.COMPLETED:
            try:
                ShipmentTrackingLedgerService.require_delivered(
                    tenant_session=tenant_session,
                    shipment_uuid=command.shipment_uuid,
                    waybill_no=command.waybill_no,
                    result_digest=command.source_result_digest,
                    occurred_at=command.occurred_at,
                )
            except ShipmentTrackingLedgerError:
                raise RelayExternalProjectionConflict() from None

    @staticmethod
    def _verify_projection_audit(
        tenant_session: Session,
        *,
        result: RelayManualMutationResult,
        command: RelayExternalProjectionCommand,
    ) -> None:
        audits = tuple(
            tenant_session.scalars(
                sa.select(AuditLog)
                .where(
                    AuditLog.action == "relay_case_status_changed",
                    AuditLog.resource_type == "rental_relay_case",
                    AuditLog.resource_id == str(result.relay_case.id),
                )
                .order_by(AuditLog.id.desc())
                .limit(_MAX_AUDITS_PER_STAGE)
                .with_for_update()
            )
        )
        matches = tuple(
            audit
            for audit in audits
            if isinstance(audit.details, dict)
            and audit.details.get("external_projection") is True
            and audit.details.get("new_status") == command.stage.value
        )
        if (
            len(matches) != 1
            or matches[0].details.get("source_result_digest")
            != command.source_result_digest
            or matches[0].details.get("operation_key")
            != command.operation_key
        ):
            raise RelayExternalProjectionConflict()


class RelayExternalProjectionStore(Protocol):
    def apply(
        self,
        prepared: PreparedRelayExternalProjectionJob,
    ) -> RelayExternalProjectionReceipt: ...


TenantTransactionProvider = Callable[
    [TenantContext], AbstractContextManager[Session]
]


class SqlAlchemyRelayExternalProjectionStore:
    def __init__(self, transaction_provider: TenantTransactionProvider) -> None:
        if not callable(transaction_provider):
            raise TypeError("tenant transaction provider is required")
        self._transaction_provider = transaction_provider

    def apply(
        self,
        prepared: PreparedRelayExternalProjectionJob,
    ) -> RelayExternalProjectionReceipt:
        if not isinstance(prepared, PreparedRelayExternalProjectionJob):
            raise TypeError("prepared relay projection job is invalid")
        context = TenantContext(
            tenant_id=UUID(prepared.tenant_uuid),
            access_version=prepared.tenant_access_version,
            source=TenantContextSource.WORKER_JOB,
            principal_ref="relay-external-projection-worker",
            source_ref=prepared.job_uuid,
            request_id=prepared.request_id,
        )
        with self._transaction_provider(context) as tenant_session:
            return RelayExternalProjectionService.apply(
                tenant_session=tenant_session,
                command=prepared.command,
            )


class RelayExternalProjectionJobHandler:
    crosses_provider_boundary = False
    recovery_category = None

    def __init__(self, *, store: RelayExternalProjectionStore) -> None:
        if not callable(getattr(store, "apply", None)):
            raise TypeError("relay external projection store is required")
        self._store = store

    def prepare(self, job: BackgroundJob) -> PreparedJob:
        return PreparedJob(_parse_job(job))

    def execute(self, job: BackgroundJob, prepared: PreparedJob) -> JobOutcome:
        value = prepared.value
        if not isinstance(value, PreparedRelayExternalProjectionJob):
            raise TypeError("prepared relay projection job is invalid")
        try:
            receipt = self._store.apply(value)
        except RelayExternalProjectionConflict:
            return JobOutcome(
                OutcomeDisposition.REVIEW,
                reason_code="relay_projection_conflict",
            )
        return JobOutcome(
            OutcomeDisposition.SUCCEEDED,
            safe_result={
                "stage": value.command.stage.value,
                "relay_status": receipt.status,
            },
        )


class RelayExternalProjectionCoordinator:
    """Idempotently enqueue an already-persisted safe external result."""

    def __init__(self, service: ControlJobService | None = None) -> None:
        self._service = service or ControlJobService()

    def enqueue(
        self,
        control_session: Session,
        *,
        tenant_uuid: str | UUID,
        tenant_access_version: int,
        command: RelayExternalProjectionCommand,
        available_at: datetime,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> BackgroundJob:
        _require_explicit_transaction(control_session)
        if not isinstance(command, RelayExternalProjectionCommand):
            raise RelayExternalProjectionInputError()
        try:
            tenant_id = str(UUID(str(tenant_uuid)))
            access_version = _positive(tenant_access_version)
            current_time = _utc(available_at)
        except (TypeError, ValueError):
            raise RelayExternalProjectionInputError() from None
        return self._service.enqueue_job(
            control_session,
            tenant_id=tenant_id,
            tenant_access_version=access_version,
            job_type=RELAY_EXTERNAL_PROJECTION_JOB_TYPE,
            resource_key=command.resource_key,
            payload=command.payload(),
            idempotency_key=command.idempotency_key,
            requested_by_type="worker",
            request_id=request_id,
            correlation_id=correlation_id,
            priority=80,
            max_attempts=3,
            available_at=current_time,
        )


def _parse_job(job: BackgroundJob) -> PreparedRelayExternalProjectionJob:
    expected = {
        "contract_version",
        "shipment_uuid",
        "predecessor_rental_id",
        "successor_rental_id",
        "stage",
        "waybill_no",
        "source_result_digest",
        "occurred_at",
        "tenant_timezone",
    }
    if (
        not isinstance(job, BackgroundJob)
        or job.job_type != RELAY_EXTERNAL_PROJECTION_JOB_TYPE
        or job.requested_by_type != "worker"
        or not isinstance(job.payload, dict)
        or set(job.payload) != expected
        or job.payload.get("contract_version") != 1
    ):
        raise RelayExternalProjectionInputError()
    try:
        occurred_at = datetime.fromisoformat(job.payload["occurred_at"])
        command = RelayExternalProjectionCommand(
            shipment_uuid=job.payload["shipment_uuid"],
            predecessor_rental_id=job.payload["predecessor_rental_id"],
            successor_rental_id=job.payload["successor_rental_id"],
            stage=job.payload["stage"],
            waybill_no=job.payload["waybill_no"],
            source_result_digest=job.payload["source_result_digest"],
            occurred_at=occurred_at,
            tenant_timezone=job.payload["tenant_timezone"],
        )
        if (
            job.resource_key != command.resource_key
            or job.idempotency_key != command.idempotency_key
        ):
            raise RelayExternalProjectionInputError()
        return PreparedRelayExternalProjectionJob(
            job_uuid=str(UUID(job.id)),
            tenant_uuid=str(UUID(job.tenant_id)),
            tenant_access_version=_positive(job.tenant_access_version),
            request_id=job.correlation_id or job.request_id or job.id,
            command=command,
        )
    except (TypeError, ValueError, KeyError):
        raise RelayExternalProjectionInputError() from None


def _require_explicit_transaction(session: Session) -> None:
    transaction = session.get_transaction() if isinstance(session, Session) else None
    if (
        transaction is None
        or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
    ):
        raise RelayExternalProjectionInputError()


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError
    return value


def _text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError
    selected = value.strip()
    if (
        not selected
        or len(selected) > maximum
        or any(ord(character) < 0x20 for character in selected)
    ):
        raise ValueError
    return selected


def _utc(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError
    return value.astimezone(timezone.utc)


def _naive_utc(value: datetime) -> datetime:
    return _utc(value).replace(tzinfo=None)


def _timezone_name(value: object) -> str:
    selected = _text(value, maximum=64)
    ZoneInfo(selected)
    return selected


__all__ = [
    "PreparedRelayExternalProjectionJob",
    "RELAY_EXTERNAL_PROJECTION_JOB_TYPE",
    "RelayExternalProjectionCommand",
    "RelayExternalProjectionConflict",
    "RelayExternalProjectionCoordinator",
    "RelayExternalProjectionError",
    "RelayExternalProjectionInputError",
    "RelayExternalProjectionJobHandler",
    "RelayExternalProjectionPersistenceError",
    "RelayExternalProjectionReceipt",
    "RelayExternalProjectionService",
    "RelayExternalProjectionStore",
    "RelayExternalStage",
    "SqlAlchemyRelayExternalProjectionStore",
]
