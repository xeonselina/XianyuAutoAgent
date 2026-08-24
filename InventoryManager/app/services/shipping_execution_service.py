"""Caller-transaction-owned shipping and paired-label execution state.

This module persists immutable provider context before any external side
effect.  It never commits, rolls back, resolves current credentials, or calls a
provider.  Callers must enter an explicit tenant-database transaction and must
roll it back if a mutation raises.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, SessionTransactionOrigin

from app.models.accessory_inventory import (
    AccessoryUnit,
    RentalAccessoryRequest,
    RentalAccessoryUnitLink,
)
from app.models.device import Device
from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding
from app.models.shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
    WaybillPrintJob,
)
from app.models.warehouse import Warehouse
from app.services.warehouse.printer_binding_service import (
    WarehousePrinterBindingRef,
    WarehousePrinterBindingService,
    WarehousePrinterBindingUnavailableError,
)
from app.services.warehouse.provider_binding_service import (
    WarehouseProviderBindingService,
    WarehouseProviderBindingUnavailableError,
)
from inventory_control.integrations import SfProviderExecutionContext


_TECHNICAL_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/-]*$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_SAFE_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]{0,63}$")
_PRINT_SNAPSHOT_FIELDS = (
    "shipment_id",
    "rental_id",
    "waybill_no_snapshot",
    "first_label_warehouse_uuid",
    "integration_uuid",
    "provider_account_uuid",
    "integration_secret_revision_uuid",
    "provider_account_secret_revision_uuid",
    "binding_revision",
    "return_warehouse_id",
    "return_warehouse_uuid",
    "return_contact_snapshot",
    "printer_sn_snapshot",
    "operator_user_uuid",
)


class ShippingExecutionError(RuntimeError):
    code = "SHIPPING_EXECUTION_ERROR"
    public_message = "shipping execution operation failed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class ShippingTransactionRequiredError(ShippingExecutionError):
    code = "SHIPPING_TRANSACTION_REQUIRED"
    public_message = "an explicit caller-owned transaction is required"


class ShippingInputError(ShippingExecutionError):
    code = "SHIPPING_INPUT_INVALID"
    public_message = "shipping execution input is invalid"


class ShippingNotFoundError(ShippingExecutionError):
    code = "SHIPPING_EXECUTION_NOT_FOUND"
    public_message = "shipping execution was not found"


class ShippingSnapshotMismatchError(ShippingExecutionError):
    code = "SHIPPING_SNAPSHOT_MISMATCH"
    public_message = "shipping execution snapshot is no longer valid"


class ShippingAccessoryUnfulfilledError(ShippingExecutionError):
    code = "SHIPPING_ACCESSORY_UNFULFILLED"
    public_message = "required accessory fulfillment is incomplete"


class ShippingPrinterUnavailableError(ShippingExecutionError):
    code = "SHIPPING_PRINTER_UNAVAILABLE"
    public_message = "the shipment warehouse has no active verified printer"


class ShippingIdempotencyConflictError(ShippingExecutionError):
    code = "SHIPPING_IDEMPOTENCY_CONFLICT"
    public_message = "shipping execution idempotency key conflicts"


class ShippingStateConflictError(ShippingExecutionError):
    code = "SHIPPING_STATE_CONFLICT"
    public_message = "shipping execution state changed"


class ShippingUnknownOutcomeError(ShippingExecutionError):
    code = "SHIPPING_OUTCOME_UNKNOWN"
    public_message = "shipping execution requires explicit reconciliation"


class ShippingPersistenceError(ShippingExecutionError):
    code = "SHIPPING_PERSISTENCE_FAILED"
    public_message = "shipping execution could not be persisted"


class ProviderOutcome(str, Enum):
    SUCCESS = "success"
    DEFINITIVE_FAILURE = "definitive_failure"
    UNKNOWN = "unknown"


class UnknownResolution(str, Enum):
    CONFIRMED_SUCCESS = "confirmed_success"
    CONFIRMED_NO_EFFECT = "confirmed_no_effect"
    STILL_UNKNOWN = "still_unknown"


class PrintLabelKind(str, Enum):
    FIRST = "first"
    SECOND = "second"


class PrintOutcome(str, Enum):
    PRINTED = "printed"
    DEFINITIVE_FAILURE = "definitive_failure"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ShipmentExecutionRef:
    shipment_id: str
    status: str
    provider_order_id: str
    request_hash: str
    waybill_no: Optional[str]
    idempotent_replay: bool = False


@dataclass(frozen=True, slots=True)
class ProviderAttemptRef:
    attempt_id: str
    shipment_id: str
    operation: str
    attempt_no: int
    idempotency_key: str
    status: str
    idempotent_replay: bool = False


@dataclass(frozen=True, slots=True)
class ShippingJobProvenance:
    job_uuid: str
    tenant_access_version: int
    requested_by_user_uuid: str
    request_id: str
    correlation_id: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_uuid", _uuid_string(self.job_uuid))
        object.__setattr__(
            self,
            "tenant_access_version",
            _positive_integer(self.tenant_access_version),
        )
        object.__setattr__(
            self,
            "requested_by_user_uuid",
            _uuid_string(self.requested_by_user_uuid),
        )
        object.__setattr__(
            self,
            "request_id",
            _bounded_text(self.request_id, maximum=64),
        )
        object.__setattr__(
            self,
            "correlation_id",
            _optional_bounded_text(self.correlation_id, maximum=64),
        )


@dataclass(frozen=True, slots=True)
class PrintJobRef:
    print_job_id: str
    shipment_id: str
    label_kind: PrintLabelKind
    status: str
    provider_task_id: Optional[str]
    idempotent_replay: bool = False


@dataclass(frozen=True, slots=True)
class PairedPrintJobsRef:
    first_label: PrintJobRef
    second_label: PrintJobRef
    idempotent_replay: bool = False


class ShippingExecutionService:
    """Persist and compare-and-swap one tenant's execution ledgers."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session")
        self._session = session

    def prepare_shipment(
        self,
        *,
        shipment_uuid: str | UUID,
        rental_id: int,
        device_id: int,
        provider_context: SfProviderExecutionContext,
        receiver_snapshot: Mapping[str, Any],
        express_type_id: int,
        scheduled_dispatch_at: datetime,
    ) -> ShipmentExecutionRef:
        self._require_transaction()
        shipment_id = _uuid_string(shipment_uuid)
        rental_id = _positive_integer(rental_id)
        device_id = _positive_integer(device_id)
        express_type_id = _positive_integer(express_type_id)
        scheduled_dispatch_at = _naive_utc_datetime(scheduled_dispatch_at)
        if not isinstance(provider_context, SfProviderExecutionContext):
            raise ShippingInputError()
        tenant_uuid = _uuid_string(provider_context.tenant_uuid)
        origin_uuid = _uuid_string(provider_context.warehouse_uuid)
        integration_uuid = _uuid_string(provider_context.integration_uuid)
        account_uuid = _uuid_string(provider_context.provider_account_uuid)
        integration_revision_uuid = _uuid_string(
            provider_context.integration_secret_revision_uuid
        )
        account_revision_uuid = _uuid_string(
            provider_context.provider_account_secret_revision_uuid
        )
        binding_revision = _positive_integer(provider_context.binding_revision)
        account_masked_hint = _bounded_text(
            provider_context.masked_account_hint,
            maximum=64,
        )
        if "*" not in account_masked_hint:
            raise ShippingInputError()
        provider_order_id = _technical_key(
            f"sf:{tenant_uuid}:{shipment_id}",
            maximum=128,
        )
        receiver = _json_snapshot(receiver_snapshot)
        tracking_check_phone_last4 = _tracking_phone_last4(receiver)
        existing = self._session.execute(
            select(OutboundShipment)
            .where(OutboundShipment.id == shipment_id)
            .with_for_update()
        ).scalar_one_or_none()
        supplied_facts = {
            "provider_order_id": provider_order_id,
            "rental_id": rental_id,
            "origin_warehouse_uuid": origin_uuid,
            "integration_uuid": integration_uuid,
            "provider_account_uuid": account_uuid,
            "integration_secret_revision_uuid": integration_revision_uuid,
            "provider_account_secret_revision_uuid": account_revision_uuid,
            "binding_revision": binding_revision,
            "account_masked_hint": account_masked_hint,
            "receiver_snapshot": receiver,
            "tracking_check_phone_last4": tracking_check_phone_last4,
            "express_type_id": express_type_id,
            "scheduled_dispatch_at": scheduled_dispatch_at,
        }
        if existing is not None:
            if not _entity_matches(existing, supplied_facts):
                raise ShippingIdempotencyConflictError()
            return _shipment_ref(existing, replay=True)
        if provider_context.historical is not False:
            raise ShippingSnapshotMismatchError()

        rental, device, warehouse = self._lock_fulfillment_context(
            rental_id=rental_id,
            expected_device_id=device_id,
            expected_warehouse_id=None,
            expected_warehouse_uuid=origin_uuid,
        )
        if receiver != _rental_receiver_snapshot(rental):
            raise ShippingSnapshotMismatchError()
        if rental.express_type_id != express_type_id:
            raise ShippingSnapshotMismatchError()
        if (
            rental.status != "not_shipped"
            or rental.ship_out_tracking_no is not None
            or self._session.scalar(
                select(RentalRelayBinding.id).where(
                    RentalRelayBinding.successor_rental_id == rental.id
                )
            )
            is not None
        ):
            raise ShippingStateConflictError()
        try:
            binding = WarehouseProviderBindingService(
                self._session
            ).resolve_active_sf_binding(warehouse_uuid=warehouse.warehouse_uuid)
        except WarehouseProviderBindingUnavailableError:
            raise ShippingSnapshotMismatchError() from None
        if (
            binding.provider_account_uuid != account_uuid
            or binding.binding_revision != binding_revision
        ):
            raise ShippingSnapshotMismatchError()
        self._require_no_open_shipment(
            rental_id=rental.id,
            excluding_shipment_id=shipment_id,
        )
        self._require_accessories_fulfilled(
            rental.id,
            warehouse_id=device.warehouse_id,
        )
        sender = _warehouse_sender_snapshot(warehouse)
        cargo = _device_cargo_snapshot(device)
        expected = {
            **supplied_facts,
            "origin_warehouse_id": warehouse.id,
            "sender_snapshot": sender,
            "cargo_snapshot": cargo,
        }
        hash_facts = {
            **expected,
            "scheduled_dispatch_at": (
                f"{scheduled_dispatch_at.isoformat(timespec='seconds')}Z"
            ),
        }
        request_hash = _request_hash({
            "provider": "sf",
            "device_id": device_id,
            "provider_order_id": provider_order_id,
            **hash_facts,
        })
        expected["request_hash"] = request_hash

        shipment = OutboundShipment(
            id=shipment_id,
            provider="sf",
            **expected,
        )
        self._session.add(shipment)
        self._flush()
        return _shipment_ref(shipment)

    def prepare_provider_attempt(
        self,
        *,
        shipment_id: str | UUID,
        operation: str,
        idempotency_key: str,
        background_job_uuid: str | UUID | None = None,
        job_provenance: ShippingJobProvenance | None = None,
    ) -> ProviderAttemptRef:
        self._require_transaction()
        shipment_id = _uuid_string(shipment_id)
        if operation not in {"create_waybill", "cancel_waybill"}:
            raise ShippingInputError()
        idempotency_key = _technical_key(idempotency_key, maximum=128)
        if job_provenance is not None and not isinstance(
            job_provenance,
            ShippingJobProvenance,
        ):
            raise ShippingInputError()
        if job_provenance is not None:
            if background_job_uuid is not None and _uuid_string(
                background_job_uuid
            ) != job_provenance.job_uuid:
                raise ShippingInputError()
            background_job = job_provenance.job_uuid
        else:
            background_job = (
                _uuid_string(background_job_uuid)
                if background_job_uuid is not None
                else None
            )
        provenance_facts = {
            "tenant_access_version": (
                job_provenance.tenant_access_version
                if job_provenance is not None
                else None
            ),
            "requested_by_user_uuid": (
                job_provenance.requested_by_user_uuid
                if job_provenance is not None
                else None
            ),
            "request_id": (
                job_provenance.request_id
                if job_provenance is not None
                else None
            ),
            "correlation_id": (
                job_provenance.correlation_id
                if job_provenance is not None
                else None
            ),
        }
        existing = self._session.execute(
            select(ProviderOperationAttempt)
            .where(ProviderOperationAttempt.idempotency_key == idempotency_key)
            .with_for_update()
        ).scalar_one_or_none()
        if existing is not None:
            shipment = self._lock(OutboundShipment, shipment_id)
            if (
                shipment is None
                or existing.shipment_id != shipment_id
                or existing.operation != operation
                or existing.background_job_uuid != background_job
                or not _entity_matches(existing, provenance_facts)
                or existing.integration_secret_revision_uuid
                != shipment.integration_secret_revision_uuid
                or existing.provider_account_secret_revision_uuid
                != shipment.provider_account_secret_revision_uuid
                or existing.binding_revision != shipment.binding_revision
            ):
                raise ShippingIdempotencyConflictError()
            return _attempt_ref(existing, replay=True)

        shipment = self._lock(OutboundShipment, shipment_id)
        if shipment is None:
            raise ShippingNotFoundError()
        if operation == "create_waybill":
            if shipment.status == "needs_review":
                raise ShippingUnknownOutcomeError()
            if shipment.status not in {"prepared", "failed"}:
                raise ShippingStateConflictError()
        else:
            if shipment.status == "cancel_unknown":
                raise ShippingUnknownOutcomeError()
            if shipment.status != "cancel_requested":
                raise ShippingStateConflictError()

        attempts = tuple(
            self._session.execute(
                select(ProviderOperationAttempt)
                .where(
                    ProviderOperationAttempt.shipment_id == shipment_id,
                    ProviderOperationAttempt.operation == operation,
                )
                .order_by(ProviderOperationAttempt.attempt_no.asc())
                .with_for_update()
            )
            .scalars()
            .all()
        )
        if any(attempt.status in {"unknown", "needs_review"} for attempt in attempts):
            raise ShippingUnknownOutcomeError()
        attempt = ProviderOperationAttempt(
            shipment_id=shipment.id,
            background_job_uuid=background_job,
            **provenance_facts,
            operation=operation,
            idempotency_key=idempotency_key,
            attempt_no=(attempts[-1].attempt_no + 1) if attempts else 1,
            integration_secret_revision_uuid=(
                shipment.integration_secret_revision_uuid
            ),
            provider_account_secret_revision_uuid=(
                shipment.provider_account_secret_revision_uuid
            ),
            binding_revision=shipment.binding_revision,
            status="prepared",
        )
        self._session.add(attempt)
        self._flush()
        return _attempt_ref(attempt)

    def acknowledge_provider_job_enqueued(
        self,
        *,
        attempt_id: str | UUID,
        shipment_id: str | UUID,
        provenance: ShippingJobProvenance,
        enqueued_at: datetime,
    ) -> bool:
        """Acknowledge one exact control job without rewriting its intent."""

        self._require_transaction()
        attempt_id = _uuid_string(attempt_id)
        shipment_id = _uuid_string(shipment_id)
        if not isinstance(provenance, ShippingJobProvenance) or not isinstance(
            enqueued_at,
            datetime,
        ):
            raise ShippingInputError()
        attempt = self._lock(ProviderOperationAttempt, attempt_id)
        if (
            attempt is None
            or attempt.operation != "create_waybill"
            or attempt.shipment_id != shipment_id
            or attempt.background_job_uuid != provenance.job_uuid
            or attempt.tenant_access_version
            != provenance.tenant_access_version
            or attempt.requested_by_user_uuid
            != provenance.requested_by_user_uuid
            or attempt.request_id != provenance.request_id
            or attempt.correlation_id != provenance.correlation_id
        ):
            raise ShippingIdempotencyConflictError()
        if attempt.job_enqueued_at is not None:
            return False
        attempt.job_enqueued_at = enqueued_at
        self._flush()
        return True

    def mark_provider_submitting(
        self,
        *,
        attempt_id: str | UUID,
        expected_status: str,
        started_at: datetime,
    ) -> ProviderAttemptRef:
        self._require_transaction()
        attempt_id = _uuid_string(attempt_id)
        if expected_status != "prepared" or not isinstance(started_at, datetime):
            raise ShippingInputError()
        attempt = self._lock(ProviderOperationAttempt, attempt_id)
        if attempt is None:
            raise ShippingNotFoundError()
        if attempt.status != expected_status:
            if attempt.status in {"unknown", "needs_review"}:
                raise ShippingUnknownOutcomeError()
            raise ShippingStateConflictError()
        shipment = self._lock(OutboundShipment, attempt.shipment_id)
        if shipment is None:
            raise ShippingNotFoundError()
        if (
            attempt.integration_secret_revision_uuid
            != shipment.integration_secret_revision_uuid
            or attempt.provider_account_secret_revision_uuid
            != shipment.provider_account_secret_revision_uuid
            or attempt.binding_revision != shipment.binding_revision
        ):
            raise ShippingSnapshotMismatchError()

        if attempt.operation == "create_waybill":
            rental, device, _warehouse = self._lock_fulfillment_context(
                rental_id=shipment.rental_id,
                expected_device_id=None,
                expected_warehouse_id=shipment.origin_warehouse_id,
                expected_warehouse_uuid=shipment.origin_warehouse_uuid,
            )
            self._require_accessories_fulfilled(
                rental.id,
                warehouse_id=device.warehouse_id,
            )
            if shipment.status not in {"prepared", "failed"}:
                if shipment.status == "needs_review":
                    raise ShippingUnknownOutcomeError()
                raise ShippingStateConflictError()
            self._cas(
                OutboundShipment,
                shipment.id,
                shipment.status,
                status="provider_submitting",
                safe_error_code=None,
                updated_at=started_at,
            )
        elif attempt.operation == "cancel_waybill":
            if shipment.status != "cancel_requested":
                if shipment.status == "cancel_unknown":
                    raise ShippingUnknownOutcomeError()
                raise ShippingStateConflictError()
        else:
            raise ShippingStateConflictError()

        updated = self._cas(
            ProviderOperationAttempt,
            attempt.id,
            expected_status,
            status="provider_submitting",
            started_at=started_at,
        )
        return _attempt_ref(updated)

    def record_provider_result(
        self,
        *,
        attempt_id: str | UUID,
        expected_status: str,
        outcome: ProviderOutcome | str,
        finished_at: datetime,
        waybill_no: Optional[str] = None,
        safe_provider_code: Optional[str] = None,
        response_hash: Optional[str] = None,
        latency_ms: Optional[int] = None,
    ) -> ProviderAttemptRef:
        self._require_transaction()
        attempt_id = _uuid_string(attempt_id)
        if expected_status != "provider_submitting" or not isinstance(
            finished_at, datetime
        ):
            raise ShippingInputError()
        outcome = _enum_value(ProviderOutcome, outcome)
        response_hash = _optional_hash(response_hash)
        latency_ms = _optional_nonnegative_integer(latency_ms)
        attempt = self._lock(ProviderOperationAttempt, attempt_id)
        if attempt is None:
            raise ShippingNotFoundError()
        if attempt.status != expected_status:
            if attempt.status in {"unknown", "needs_review"}:
                raise ShippingUnknownOutcomeError()
            raise ShippingStateConflictError()
        shipment = self._lock(OutboundShipment, attempt.shipment_id)
        if shipment is None:
            raise ShippingNotFoundError()

        code = None
        if outcome is ProviderOutcome.SUCCESS:
            if safe_provider_code is not None:
                raise ShippingInputError()
        elif outcome is ProviderOutcome.DEFINITIVE_FAILURE:
            code = _safe_code(safe_provider_code)
        else:
            code = (
                _safe_code(safe_provider_code)
                if safe_provider_code is not None
                else "PROVIDER_RESULT_UNKNOWN"
            )

        if attempt.operation == "create_waybill":
            if shipment.status != "provider_submitting":
                raise ShippingStateConflictError()
            if outcome is ProviderOutcome.SUCCESS:
                waybill = _bounded_text(waybill_no, maximum=64)
                shipment_status = "submitted"
                shipment_values = {
                    "waybill_no": waybill,
                    "submitted_at": finished_at,
                    "safe_error_code": None,
                }
            elif outcome is ProviderOutcome.DEFINITIVE_FAILURE:
                if waybill_no is not None:
                    raise ShippingInputError()
                shipment_status = "failed"
                shipment_values = {"safe_error_code": code}
            else:
                if waybill_no is not None:
                    raise ShippingInputError()
                shipment_status = "needs_review"
                shipment_values = {"safe_error_code": code}
        elif attempt.operation == "cancel_waybill":
            if shipment.status != "cancel_requested" or waybill_no is not None:
                raise ShippingStateConflictError()
            if outcome is ProviderOutcome.SUCCESS:
                shipment_status = "cancelled"
                shipment_values = {
                    "cancelled_at": finished_at,
                    "safe_error_code": None,
                }
            elif outcome is ProviderOutcome.DEFINITIVE_FAILURE:
                shipment_status = "submitted"
                shipment_values = {"safe_error_code": code}
            else:
                shipment_status = "cancel_unknown"
                shipment_values = {"safe_error_code": code}
        else:
            raise ShippingStateConflictError()

        self._cas(
            OutboundShipment,
            shipment.id,
            shipment.status,
            status=shipment_status,
            updated_at=finished_at,
            **shipment_values,
        )
        attempt_status = {
            ProviderOutcome.SUCCESS: "succeeded",
            ProviderOutcome.DEFINITIVE_FAILURE: "definitive_failure",
            ProviderOutcome.UNKNOWN: "unknown",
        }[outcome]
        updated = self._cas(
            ProviderOperationAttempt,
            attempt.id,
            expected_status,
            status=attempt_status,
            safe_provider_code=code,
            response_hash=response_hash,
            latency_ms=latency_ms,
            finished_at=finished_at,
        )
        return _attempt_ref(updated)

    def request_cancellation(
        self,
        *,
        shipment_id: str | UUID,
        expected_status: str,
        requested_at: datetime,
    ) -> ShipmentExecutionRef:
        self._require_transaction()
        shipment_id = _uuid_string(shipment_id)
        if expected_status != "submitted" or not isinstance(requested_at, datetime):
            raise ShippingInputError()
        shipment = self._lock(OutboundShipment, shipment_id)
        if shipment is None:
            raise ShippingNotFoundError()
        if shipment.status != expected_status:
            if shipment.status == "cancel_requested":
                return _shipment_ref(shipment, replay=True)
            if shipment.status in {"cancel_unknown", "needs_review"}:
                raise ShippingUnknownOutcomeError()
            raise ShippingStateConflictError()
        updated = self._cas(
            OutboundShipment,
            shipment.id,
            expected_status,
            status="cancel_requested",
            safe_error_code=None,
            updated_at=requested_at,
        )
        return _shipment_ref(updated)

    def begin_unknown_provider_reconciliation(
        self,
        *,
        attempt_id: str | UUID,
        started_at: datetime,
    ) -> ProviderAttemptRef:
        """Fence one automatic query before crossing the provider boundary."""

        self._require_transaction()
        attempt_id = _uuid_string(attempt_id)
        if not isinstance(started_at, datetime):
            raise ShippingInputError()
        attempt = self._lock(ProviderOperationAttempt, attempt_id)
        if attempt is None:
            raise ShippingNotFoundError()
        if attempt.status not in {"provider_submitting", "unknown"}:
            if attempt.status == "needs_review":
                raise ShippingUnknownOutcomeError()
            raise ShippingStateConflictError()
        shipment = self._lock(OutboundShipment, attempt.shipment_id)
        if shipment is None:
            raise ShippingNotFoundError()

        if attempt.operation == "create_waybill":
            expected_shipment_status = (
                "provider_submitting"
                if attempt.status == "provider_submitting"
                else "needs_review"
            )
            target_shipment_status = "needs_review"
        elif attempt.operation == "cancel_waybill":
            expected_shipment_status = (
                "cancel_requested"
                if attempt.status == "provider_submitting"
                else "cancel_unknown"
            )
            target_shipment_status = "cancel_unknown"
        else:
            raise ShippingStateConflictError()
        if shipment.status != expected_shipment_status:
            raise ShippingStateConflictError()

        if shipment.status != target_shipment_status:
            self._cas(
                OutboundShipment,
                shipment.id,
                shipment.status,
                status=target_shipment_status,
                safe_error_code=(
                    shipment.safe_error_code
                    or "PROVIDER_RECONCILIATION_STARTED"
                ),
                updated_at=started_at,
            )
        updated = self._cas(
            ProviderOperationAttempt,
            attempt.id,
            attempt.status,
            status="needs_review",
            safe_provider_code=(
                attempt.safe_provider_code
                or "PROVIDER_RECONCILIATION_STARTED"
            ),
        )
        return _attempt_ref(updated)

    def reconcile_unknown_provider_attempt(
        self,
        *,
        attempt_id: str | UUID,
        resolution: UnknownResolution | str,
        reconciled_at: datetime,
        safe_provider_code: str,
        waybill_no: Optional[str] = None,
        response_hash: Optional[str] = None,
    ) -> ProviderAttemptRef:
        self._require_transaction()
        attempt_id = _uuid_string(attempt_id)
        resolution = _enum_value(UnknownResolution, resolution)
        if not isinstance(reconciled_at, datetime):
            raise ShippingInputError()
        code = _safe_code(safe_provider_code)
        response_hash = _optional_hash(response_hash)
        attempt = self._lock(ProviderOperationAttempt, attempt_id)
        if attempt is None:
            raise ShippingNotFoundError()
        if attempt.status not in {"unknown", "needs_review"}:
            raise ShippingStateConflictError()
        shipment = self._lock(OutboundShipment, attempt.shipment_id)
        if shipment is None:
            raise ShippingNotFoundError()

        if resolution is UnknownResolution.CONFIRMED_SUCCESS:
            attempt_status = "succeeded"
            if attempt.operation == "create_waybill":
                if shipment.status != "needs_review":
                    raise ShippingStateConflictError()
                shipment_status = "submitted"
                shipment_values = {
                    "waybill_no": _bounded_text(waybill_no, maximum=64),
                    "submitted_at": reconciled_at,
                    "safe_error_code": None,
                }
            elif attempt.operation == "cancel_waybill":
                if shipment.status != "cancel_unknown" or waybill_no is not None:
                    raise ShippingStateConflictError()
                shipment_status = "cancelled"
                shipment_values = {
                    "cancelled_at": reconciled_at,
                    "safe_error_code": None,
                }
            else:
                raise ShippingStateConflictError()
        elif resolution is UnknownResolution.CONFIRMED_NO_EFFECT:
            if waybill_no is not None:
                raise ShippingInputError()
            attempt_status = "definitive_failure"
            if attempt.operation == "create_waybill":
                if shipment.status != "needs_review":
                    raise ShippingStateConflictError()
                shipment_status = "failed"
            elif attempt.operation == "cancel_waybill":
                if shipment.status != "cancel_unknown":
                    raise ShippingStateConflictError()
                shipment_status = "submitted"
            else:
                raise ShippingStateConflictError()
            shipment_values = {"safe_error_code": code}
        else:
            if waybill_no is not None:
                raise ShippingInputError()
            attempt_status = "needs_review"
            if attempt.operation == "create_waybill":
                if shipment.status != "needs_review":
                    raise ShippingStateConflictError()
                shipment_status = "needs_review"
            elif attempt.operation == "cancel_waybill":
                if shipment.status != "cancel_unknown":
                    raise ShippingStateConflictError()
                shipment_status = "cancel_unknown"
            else:
                raise ShippingStateConflictError()
            shipment_values = {"safe_error_code": code}

        self._cas(
            OutboundShipment,
            shipment.id,
            shipment.status,
            status=shipment_status,
            updated_at=reconciled_at,
            **shipment_values,
        )
        updated = self._cas(
            ProviderOperationAttempt,
            attempt.id,
            attempt.status,
            status=attempt_status,
            safe_provider_code=code,
            response_hash=response_hash,
            finished_at=reconciled_at,
        )
        return _attempt_ref(updated)

    def prepare_paired_print_jobs(
        self,
        *,
        shipment_id: str | UUID,
        rental_id: int,
        first_label_warehouse_uuid: str | UUID,
        return_warehouse_id: int,
        return_warehouse_uuid: str | UUID,
        return_contact_snapshot: Mapping[str, Any],
        operator_user_uuid: str | UUID,
        idempotency_key: str,
    ) -> PairedPrintJobsRef:
        self._require_transaction()
        shipment_id = _uuid_string(shipment_id)
        rental_id = _positive_integer(rental_id)
        return_warehouse_id = _positive_integer(return_warehouse_id)
        first_warehouse_uuid = _uuid_string(first_label_warehouse_uuid)
        return_warehouse_uuid = _uuid_string(return_warehouse_uuid)
        return_contact = _json_snapshot(
            return_contact_snapshot,
            forbid_internal_accessories=True,
        )
        operator_uuid = _uuid_string(operator_user_uuid)
        base_key = _technical_key(idempotency_key, maximum=120)
        first_key = _print_key(base_key, PrintLabelKind.FIRST)
        second_key = _print_key(base_key, PrintLabelKind.SECOND)

        existing = tuple(
            self._session.execute(
                select(WaybillPrintJob)
                .where(WaybillPrintJob.idempotency_key.in_((first_key, second_key)))
                .order_by(WaybillPrintJob.idempotency_key.asc())
                .with_for_update()
            )
            .scalars()
            .all()
        )
        shipment = self._lock(OutboundShipment, shipment_id)
        if shipment is None:
            raise ShippingNotFoundError()
        expected = {
            "shipment_id": shipment_id,
            "rental_id": rental_id,
            "waybill_no_snapshot": shipment.waybill_no,
            "first_label_warehouse_uuid": first_warehouse_uuid,
            "integration_uuid": shipment.integration_uuid,
            "provider_account_uuid": shipment.provider_account_uuid,
            "integration_secret_revision_uuid": (
                shipment.integration_secret_revision_uuid
            ),
            "provider_account_secret_revision_uuid": (
                shipment.provider_account_secret_revision_uuid
            ),
            "binding_revision": shipment.binding_revision,
            "return_warehouse_id": return_warehouse_id,
            "return_warehouse_uuid": return_warehouse_uuid,
            "return_contact_snapshot": return_contact,
            "operator_user_uuid": operator_uuid,
        }
        if existing:
            by_key = {job.idempotency_key: job for job in existing}
            if (
                set(by_key) != {first_key, second_key}
                or any(
                    not _entity_matches(job, expected) for job in existing
                )
                or not _same_print_snapshot(
                    by_key[first_key],
                    by_key[second_key],
                )
            ):
                raise ShippingIdempotencyConflictError()
            return _paired_print_ref(
                by_key[first_key],
                by_key[second_key],
                replay=True,
            )

        if shipment.status != "submitted" or not shipment.waybill_no:
            raise ShippingStateConflictError()
        rental, device, warehouse = self._lock_fulfillment_context(
            rental_id=rental_id,
            expected_device_id=None,
            expected_warehouse_id=return_warehouse_id,
            expected_warehouse_uuid=return_warehouse_uuid,
        )
        if (
            shipment.rental_id != rental_id
            or shipment.origin_warehouse_id != return_warehouse_id
            or shipment.origin_warehouse_uuid != first_warehouse_uuid
            or first_warehouse_uuid != return_warehouse_uuid
        ):
            raise ShippingSnapshotMismatchError()
        self._require_accessories_fulfilled(
            rental.id,
            warehouse_id=device.warehouse_id,
        )
        printer = self._lock_active_printer(warehouse.id)
        expected["printer_sn_snapshot"] = _bounded_text(
            printer.printer_sn,
            maximum=128,
        )

        first_job = WaybillPrintJob(idempotency_key=first_key, **expected)
        second_job = WaybillPrintJob(idempotency_key=second_key, **expected)
        self._session.add_all((first_job, second_job))
        self._flush()
        return _paired_print_ref(first_job, second_job)

    def mark_print_submitting(
        self,
        *,
        print_job_id: str | UUID,
        label_kind: PrintLabelKind | str,
        expected_status: str,
        submitted_at: datetime,
    ) -> PrintJobRef:
        self._require_transaction()
        print_job_id = _uuid_string(print_job_id)
        label_kind = _enum_value(PrintLabelKind, label_kind)
        if expected_status not in {"prepared", "failed"} or not isinstance(
            submitted_at, datetime
        ):
            raise ShippingInputError()
        job = self._lock(WaybillPrintJob, print_job_id)
        if job is None:
            raise ShippingNotFoundError()
        self._require_job_kind(job, label_kind)
        if job.status != expected_status:
            if job.status in {"unknown", "needs_review"}:
                raise ShippingUnknownOutcomeError()
            raise ShippingStateConflictError()

        base_key = _print_base_key(job.idempotency_key, label_kind)
        first_job = self._lock_print_key(
            _print_key(base_key, PrintLabelKind.FIRST)
        )
        second_job = self._lock_print_key(
            _print_key(base_key, PrintLabelKind.SECOND)
        )
        if first_job is None or second_job is None:
            raise ShippingStateConflictError()
        if not _same_print_snapshot(first_job, second_job):
            raise ShippingSnapshotMismatchError()
        if label_kind is PrintLabelKind.SECOND and first_job.status != "printed":
            if first_job.status in {"unknown", "needs_review"}:
                raise ShippingUnknownOutcomeError()
            raise ShippingStateConflictError()

        shipment = self._lock(OutboundShipment, job.shipment_id)
        if shipment is None:
            raise ShippingSnapshotMismatchError()
        rental, device, warehouse = self._lock_fulfillment_context(
            rental_id=job.rental_id,
            expected_device_id=None,
            expected_warehouse_id=job.return_warehouse_id,
            expected_warehouse_uuid=job.return_warehouse_uuid,
        )
        if (
            shipment.status != "submitted"
            or shipment.waybill_no != job.waybill_no_snapshot
            or shipment.origin_warehouse_uuid != job.first_label_warehouse_uuid
            or shipment.origin_warehouse_id != job.return_warehouse_id
            or job.first_label_warehouse_uuid != job.return_warehouse_uuid
        ):
            raise ShippingSnapshotMismatchError()
        self._require_accessories_fulfilled(
            rental.id,
            warehouse_id=device.warehouse_id,
        )
        self._lock_active_printer(
            warehouse.id,
            expected_printer_sn=job.printer_sn_snapshot,
        )

        updated = self._cas(
            WaybillPrintJob,
            job.id,
            expected_status,
            status="provider_submitting",
            provider_task_id=None,
            safe_error_code=None,
            submitted_at=submitted_at,
            completed_at=None,
            updated_at=submitted_at,
        )
        return _print_ref(updated, label_kind)

    def record_print_result(
        self,
        *,
        print_job_id: str | UUID,
        label_kind: PrintLabelKind | str,
        expected_status: str,
        outcome: PrintOutcome | str,
        completed_at: datetime,
        provider_task_id: Optional[str] = None,
        safe_error_code: Optional[str] = None,
    ) -> PrintJobRef:
        self._require_transaction()
        print_job_id = _uuid_string(print_job_id)
        label_kind = _enum_value(PrintLabelKind, label_kind)
        outcome = _enum_value(PrintOutcome, outcome)
        if expected_status != "provider_submitting" or not isinstance(
            completed_at, datetime
        ):
            raise ShippingInputError()
        job = self._lock(WaybillPrintJob, print_job_id)
        if job is None:
            raise ShippingNotFoundError()
        self._require_job_kind(job, label_kind)
        if job.status != expected_status:
            if job.status in {"unknown", "needs_review"}:
                raise ShippingUnknownOutcomeError()
            raise ShippingStateConflictError()

        if outcome is PrintOutcome.PRINTED:
            status = "printed"
            task_id = _bounded_text(provider_task_id, maximum=128)
            code = None
        elif outcome is PrintOutcome.DEFINITIVE_FAILURE:
            status = "failed"
            task_id = (
                _bounded_text(provider_task_id, maximum=128)
                if provider_task_id is not None
                else None
            )
            code = _safe_code(safe_error_code)
        else:
            status = "unknown"
            task_id = (
                _bounded_text(provider_task_id, maximum=128)
                if provider_task_id is not None
                else None
            )
            code = (
                _safe_code(safe_error_code)
                if safe_error_code is not None
                else "PRINT_RESULT_UNKNOWN"
            )
        updated = self._cas(
            WaybillPrintJob,
            job.id,
            expected_status,
            status=status,
            provider_task_id=task_id,
            safe_error_code=code,
            completed_at=completed_at if status == "printed" else None,
            updated_at=completed_at,
        )
        return _print_ref(updated, label_kind)

    def reconcile_unknown_print(
        self,
        *,
        print_job_id: str | UUID,
        label_kind: PrintLabelKind | str,
        resolution: UnknownResolution | str,
        reconciled_at: datetime,
        safe_error_code: str,
        provider_task_id: Optional[str] = None,
    ) -> PrintJobRef:
        self._require_transaction()
        print_job_id = _uuid_string(print_job_id)
        label_kind = _enum_value(PrintLabelKind, label_kind)
        resolution = _enum_value(UnknownResolution, resolution)
        if not isinstance(reconciled_at, datetime):
            raise ShippingInputError()
        code = _safe_code(safe_error_code)
        job = self._lock(WaybillPrintJob, print_job_id)
        if job is None:
            raise ShippingNotFoundError()
        self._require_job_kind(job, label_kind)
        if job.status not in {"unknown", "needs_review"}:
            raise ShippingStateConflictError()

        if resolution is UnknownResolution.CONFIRMED_SUCCESS:
            status = "printed"
            task_id = _bounded_text(provider_task_id, maximum=128)
            stored_code = None
            completed_at = reconciled_at
        elif resolution is UnknownResolution.CONFIRMED_NO_EFFECT:
            status = "failed"
            task_id = (
                _bounded_text(provider_task_id, maximum=128)
                if provider_task_id is not None
                else None
            )
            stored_code = code
            completed_at = None
        else:
            status = "needs_review"
            task_id = (
                _bounded_text(provider_task_id, maximum=128)
                if provider_task_id is not None
                else job.provider_task_id
            )
            stored_code = code
            completed_at = None
        updated = self._cas(
            WaybillPrintJob,
            job.id,
            job.status,
            status=status,
            provider_task_id=task_id,
            safe_error_code=stored_code,
            completed_at=completed_at,
            updated_at=reconciled_at,
        )
        return _print_ref(updated, label_kind)

    def _lock(self, model, entity_id):
        return self._session.execute(
            select(model).where(model.id == entity_id).with_for_update()
        ).scalar_one_or_none()

    def _lock_print_key(self, idempotency_key: str) -> Optional[WaybillPrintJob]:
        return self._session.execute(
            select(WaybillPrintJob)
            .where(WaybillPrintJob.idempotency_key == idempotency_key)
            .with_for_update()
        ).scalar_one_or_none()

    def _lock_active_printer(
        self,
        warehouse_id: int,
        *,
        expected_printer_sn: str | None = None,
    ) -> WarehousePrinterBindingRef:
        try:
            return WarehousePrinterBindingService(
                self._session
            ).resolve_active_kuaimai_printer(
                warehouse_id=warehouse_id,
                expected_printer_sn=expected_printer_sn,
            )
        except WarehousePrinterBindingUnavailableError:
            raise ShippingPrinterUnavailableError()

    def _require_no_open_shipment(
        self,
        *,
        rental_id: int,
        excluding_shipment_id: str,
    ) -> None:
        shipments = tuple(
            self._session.execute(
                select(OutboundShipment)
                .where(
                    OutboundShipment.rental_id == rental_id,
                    OutboundShipment.id != excluding_shipment_id,
                )
                .order_by(OutboundShipment.id.asc())
                .with_for_update()
            ).scalars()
        )
        open_shipments = tuple(
            shipment for shipment in shipments if shipment.status != "cancelled"
        )
        if any(
            shipment.status in {"needs_review", "cancel_unknown"}
            for shipment in open_shipments
        ):
            raise ShippingUnknownOutcomeError()
        if open_shipments:
            raise ShippingStateConflictError()

    def _require_accessories_fulfilled(
        self,
        rental_id: int,
        *,
        warehouse_id: int,
    ) -> None:
        """Lock request/link facts and reject every unsatisfied request.

        A neutral link without a request is valid for an agreed relay chain;
        only request types missing a same-type link block ordinary waybill and
        print submission.
        """

        peeked_links = tuple(
            self._session.execute(
                select(
                    RentalAccessoryUnitLink.accessory_unit_id,
                    RentalAccessoryUnitLink.accessory_type_id,
                )
                .where(RentalAccessoryUnitLink.rental_id == rental_id)
                .order_by(
                    RentalAccessoryUnitLink.accessory_type_id.asc(),
                    RentalAccessoryUnitLink.accessory_unit_id.asc(),
                )
            ).all()
        )
        unit_ids = tuple(sorted({row.accessory_unit_id for row in peeked_links}))
        units = (
            tuple(
                self._session.execute(
                    select(AccessoryUnit)
                    .where(AccessoryUnit.id.in_(unit_ids))
                    .order_by(
                        AccessoryUnit.accessory_type_id.asc(),
                        AccessoryUnit.id.asc(),
                    )
                    .with_for_update()
                )
                .scalars()
                .all()
            )
            if unit_ids
            else ()
        )
        links = tuple(
            self._session.execute(
                select(RentalAccessoryUnitLink)
                .where(RentalAccessoryUnitLink.rental_id == rental_id)
                .order_by(
                    RentalAccessoryUnitLink.accessory_type_id.asc(),
                    RentalAccessoryUnitLink.accessory_unit_id.asc(),
                )
                .with_for_update()
            )
            .scalars()
            .all()
        )
        requested_types = tuple(
            self._session.execute(
                select(RentalAccessoryRequest.accessory_type_id)
                .where(RentalAccessoryRequest.rental_id == rental_id)
                .order_by(RentalAccessoryRequest.accessory_type_id.asc())
                .with_for_update()
            ).scalars()
        )
        units_by_id = {unit.id: unit for unit in units}
        linked_types = frozenset(
            link.accessory_type_id
            for link in links
            if (
                (unit := units_by_id.get(link.accessory_unit_id)) is not None
                and unit.accessory_type_id == link.accessory_type_id
                and unit.warehouse_id == warehouse_id
                and unit.condition_status == "active"
                and unit.current_holder_rental_id in {None, rental_id}
            )
        )
        if not set(requested_types).issubset(linked_types):
            raise ShippingAccessoryUnfulfilledError()

    def _lock_fulfillment_context(
        self,
        *,
        rental_id: int,
        expected_device_id: Optional[int],
        expected_warehouse_id: Optional[int],
        expected_warehouse_uuid: str,
    ) -> tuple[Rental, Device, Warehouse]:
        """Lock device -> rental -> warehouse and validate current facts."""

        peeked_device_id = self._session.execute(
            select(Rental.device_id).where(Rental.id == rental_id)
        ).scalar_one_or_none()
        if peeked_device_id is None or (
            expected_device_id is not None
            and peeked_device_id != expected_device_id
        ):
            raise ShippingSnapshotMismatchError()
        device = self._lock(Device, peeked_device_id)
        rental = self._lock(Rental, rental_id)
        if device is None or rental is None or device.warehouse_id is None:
            raise ShippingSnapshotMismatchError()
        warehouse = self._lock(Warehouse, device.warehouse_id)
        if (
            rental.parent_rental_id is not None
            or rental.device_id != device.id
            or device.is_accessory is True
            or (
                expected_warehouse_id is not None
                and device.warehouse_id != expected_warehouse_id
            )
            or warehouse is None
            or warehouse.warehouse_uuid != expected_warehouse_uuid
            or warehouse.status != "active"
            or warehouse.setup_state != "ready"
        ):
            raise ShippingSnapshotMismatchError()
        return rental, device, warehouse

    def _cas(self, model, entity_id, expected_status: str, **values):
        persistence_failed = False
        try:
            result = self._session.execute(
                update(model)
                .where(model.id == entity_id, model.status == expected_status)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
        except IntegrityError:
            persistence_failed = True
        if persistence_failed:
            raise ShippingPersistenceError()
        if result.rowcount != 1:
            raise ShippingStateConflictError()
        return self._session.execute(
            select(model)
            .where(model.id == entity_id)
            .execution_options(populate_existing=True)
        ).scalar_one()

    def _require_job_kind(
        self,
        job: WaybillPrintJob,
        label_kind: PrintLabelKind,
    ) -> None:
        if job.idempotency_key != _print_key(
            _print_base_key(job.idempotency_key, label_kind), label_kind
        ):
            raise ShippingStateConflictError()

    def _flush(self) -> None:
        persistence_failed = False
        try:
            self._session.flush()
        except IntegrityError:
            persistence_failed = True
        if persistence_failed:
            raise ShippingPersistenceError()

    def _require_transaction(self) -> None:
        transaction = self._session.get_transaction()
        if (
            transaction is None
            or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
        ):
            raise ShippingTransactionRequiredError()


def _shipment_ref(
    shipment: OutboundShipment,
    *,
    replay: bool = False,
) -> ShipmentExecutionRef:
    return ShipmentExecutionRef(
        shipment_id=shipment.id,
        status=shipment.status,
        provider_order_id=shipment.provider_order_id,
        request_hash=shipment.request_hash,
        waybill_no=shipment.waybill_no,
        idempotent_replay=replay,
    )


def _attempt_ref(
    attempt: ProviderOperationAttempt,
    *,
    replay: bool = False,
) -> ProviderAttemptRef:
    return ProviderAttemptRef(
        attempt_id=attempt.id,
        shipment_id=attempt.shipment_id,
        operation=attempt.operation,
        attempt_no=attempt.attempt_no,
        idempotency_key=attempt.idempotency_key,
        status=attempt.status,
        idempotent_replay=replay,
    )


def _print_ref(
    job: WaybillPrintJob,
    label_kind: PrintLabelKind,
    *,
    replay: bool = False,
) -> PrintJobRef:
    return PrintJobRef(
        print_job_id=job.id,
        shipment_id=job.shipment_id,
        label_kind=label_kind,
        status=job.status,
        provider_task_id=job.provider_task_id,
        idempotent_replay=replay,
    )


def _paired_print_ref(
    first: WaybillPrintJob,
    second: WaybillPrintJob,
    *,
    replay: bool = False,
) -> PairedPrintJobsRef:
    return PairedPrintJobsRef(
        first_label=_print_ref(first, PrintLabelKind.FIRST, replay=replay),
        second_label=_print_ref(second, PrintLabelKind.SECOND, replay=replay),
        idempotent_replay=replay,
    )


def _request_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _warehouse_sender_snapshot(warehouse: Warehouse) -> dict[str, str]:
    values = {
        "contact_name": warehouse.contact_name,
        "contact_phone": warehouse.contact_phone,
        "province": warehouse.province,
        "city": warehouse.city,
        "district": warehouse.district,
        "address_detail": warehouse.address_detail,
    }
    if any(
        not isinstance(value, str) or not value.strip()
        for value in values.values()
    ):
        raise ShippingSnapshotMismatchError()
    return {name: value.strip() for name, value in values.items()}


def _device_cargo_snapshot(device: Device) -> dict[str, list[dict[str, object]]]:
    model = getattr(device, "device_model", None)
    selected_name = getattr(model, "name", None) or device.model or "租赁设备"
    if not isinstance(selected_name, str):
        raise ShippingSnapshotMismatchError()
    name = selected_name.strip()
    if not name or len(name) > 64 or any(ord(char) < 32 for char in name):
        raise ShippingSnapshotMismatchError()
    return {"items": [{"name": name, "count": 1}]}


def _rental_receiver_snapshot(rental: Rental) -> dict[str, str]:
    values = {
        "contact_name": rental.customer_name,
        "contact_phone": rental.customer_phone,
        "province": rental.customer_province,
        "city": rental.customer_city,
        "district": rental.customer_district,
        "address_detail": rental.customer_address_detail,
    }
    if any(
        not isinstance(value, str) or not value.strip()
        for value in values.values()
    ):
        raise ShippingSnapshotMismatchError()
    return {name: value.strip() for name, value in values.items()}


def _tracking_phone_last4(receiver: Mapping[str, Any]) -> str:
    phone = receiver.get("contact_phone", receiver.get("phone"))
    if not isinstance(phone, str):
        raise ShippingInputError()
    digits = "".join(char for char in phone if char.isdigit())
    if len(digits) < 4:
        raise ShippingInputError()
    return digits[-4:]


def _naive_utc_datetime(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ShippingInputError()
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _json_snapshot(
    value: Mapping[str, Any],
    *,
    forbid_internal_accessories: bool = False,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ShippingInputError()
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(encoded.encode("utf-8")) > 32768:
            raise ValueError
        snapshot = json.loads(encoded)
    except (TypeError, ValueError, OverflowError):
        raise ShippingInputError() from None
    if forbid_internal_accessories and _contains_internal_accessory_key(snapshot):
        raise ShippingInputError()
    return snapshot


def _contains_internal_accessory_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower().replace("-", "_")
            if "accessory" in normalized or "logical_unit" in normalized:
                return True
            if _contains_internal_accessory_key(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_internal_accessory_key(item) for item in value)
    return False


def _entity_matches(entity: Any, expected: Mapping[str, Any]) -> bool:
    return all(getattr(entity, name) == value for name, value in expected.items())


def _same_print_snapshot(
    first_job: WaybillPrintJob,
    second_job: WaybillPrintJob,
) -> bool:
    return all(
        getattr(first_job, field_name) == getattr(second_job, field_name)
        for field_name in _PRINT_SNAPSHOT_FIELDS
    )


def _uuid_string(value: str | UUID | None) -> str:
    try:
        parsed = value if isinstance(value, UUID) else UUID(value)
    except (TypeError, ValueError, AttributeError):
        raise ShippingInputError() from None
    if parsed.int == 0:
        raise ShippingInputError()
    return str(parsed)


def _positive_integer(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ShippingInputError()
    return value


def _optional_nonnegative_integer(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ShippingInputError()
    return value


def _bounded_text(value: Any, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise ShippingInputError()
    return value


def _optional_bounded_text(value: Any, *, maximum: int) -> Optional[str]:
    if value is None:
        return None
    return _bounded_text(value, maximum=maximum)


def _technical_key(value: Any, *, maximum: int) -> str:
    value = _bounded_text(value, maximum=maximum)
    if not _TECHNICAL_KEY.fullmatch(value):
        raise ShippingInputError()
    return value


def _safe_code(value: Any) -> str:
    if not isinstance(value, str) or not _SAFE_CODE.fullmatch(value):
        raise ShippingInputError()
    return value


def _optional_hash(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ShippingInputError()
    return value


def _enum_value(enum_type, value):
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        raise ShippingInputError() from None


def _print_key(base_key: str, kind: PrintLabelKind) -> str:
    value = f"{base_key}:{kind.value}"
    if len(value) > 128:
        raise ShippingInputError()
    return value


def _print_base_key(idempotency_key: str, kind: PrintLabelKind) -> str:
    suffix = f":{kind.value}"
    if not idempotency_key.endswith(suffix):
        raise ShippingStateConflictError()
    return idempotency_key[: -len(suffix)]
