"""Post-commit notification from a successful shipment to the relay sink.

The tenant-side capture runs in the same caller-owned transaction that records
the provider result.  The control-side enqueuer must be called only after that
transaction commits.  A crash in between is safe because periodic relay
reconciliation derives the same command from the committed tenant ledger.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.rental_relay_case import RentalRelayCase
from app.models.shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
)
from inventory_control import ControlDatabase
from inventory_control.models.foundation import Tenant
from inventory_control.models.jobs import BackgroundJob
from inventory_control.transactions import require_caller_transaction

from .external_projection import (
    RelayExternalProjectionCommand,
    RelayExternalProjectionCoordinator,
)


_RESULT_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class RelayShipmentResultSignalError(RuntimeError):
    code = "RELAY_SHIPMENT_RESULT_SIGNAL_FAILED"
    public_message = "relay shipment result notification failed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class RelayShipmentResultSignalInputError(RelayShipmentResultSignalError):
    code = "RELAY_SHIPMENT_RESULT_SIGNAL_INPUT_INVALID"


class RelayShipmentResultSignalConflict(RelayShipmentResultSignalError):
    code = "RELAY_SHIPMENT_RESULT_SIGNAL_CONFLICT"


class RelayShipmentResultSignalPersistenceError(RelayShipmentResultSignalError):
    code = "RELAY_SHIPMENT_RESULT_SIGNAL_PERSISTENCE_FAILED"


@dataclass(frozen=True, slots=True)
class RelayShipmentSubmissionSignal:
    shipment_uuid: str
    predecessor_rental_id: int
    successor_rental_id: int
    waybill_no: str
    source_result_digest: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        try:
            shipment_uuid = str(UUID(self.shipment_uuid))
            predecessor_id = _positive(self.predecessor_rental_id)
            successor_id = _positive(self.successor_rental_id)
            waybill_no = _text(self.waybill_no, maximum=50)
            occurred_at = _utc(self.occurred_at)
        except (TypeError, ValueError):
            raise RelayShipmentResultSignalInputError() from None
        if (
            predecessor_id == successor_id
            or not isinstance(self.source_result_digest, str)
            or _RESULT_DIGEST.fullmatch(self.source_result_digest) is None
        ):
            raise RelayShipmentResultSignalInputError()
        object.__setattr__(self, "shipment_uuid", shipment_uuid)
        object.__setattr__(self, "predecessor_rental_id", predecessor_id)
        object.__setattr__(self, "successor_rental_id", successor_id)
        object.__setattr__(self, "waybill_no", waybill_no)
        object.__setattr__(self, "occurred_at", occurred_at)

    def command(self, *, tenant_timezone: str) -> RelayExternalProjectionCommand:
        try:
            return RelayExternalProjectionCommand(
                shipment_uuid=self.shipment_uuid,
                predecessor_rental_id=self.predecessor_rental_id,
                successor_rental_id=self.successor_rental_id,
                stage="shipped",
                waybill_no=self.waybill_no,
                source_result_digest=self.source_result_digest,
                occurred_at=self.occurred_at,
                tenant_timezone=tenant_timezone,
            )
        except Exception:
            raise RelayShipmentResultSignalInputError() from None


class RelayShipmentResultSignalService:
    """Derive an optional relay signal from one successful create attempt."""

    @staticmethod
    def capture(
        *,
        tenant_session: Session,
        attempt_uuid: str | UUID,
    ) -> RelayShipmentSubmissionSignal | None:
        _require_transaction(tenant_session)
        try:
            attempt_id = str(UUID(str(attempt_uuid)))
        except (TypeError, ValueError):
            raise RelayShipmentResultSignalInputError() from None
        try:
            attempt = tenant_session.scalar(
                sa.select(ProviderOperationAttempt)
                .where(ProviderOperationAttempt.id == attempt_id)
                .with_for_update()
            )
            if (
                attempt is None
                or attempt.operation != "create_waybill"
                or attempt.status != "succeeded"
                or attempt.response_hash is None
                or attempt.finished_at is None
            ):
                raise RelayShipmentResultSignalConflict()
            shipment = tenant_session.scalar(
                sa.select(OutboundShipment)
                .where(OutboundShipment.id == attempt.shipment_id)
                .with_for_update()
            )
            succeeded = tuple(
                tenant_session.scalars(
                    sa.select(ProviderOperationAttempt)
                    .where(
                        ProviderOperationAttempt.shipment_id == attempt.shipment_id,
                        ProviderOperationAttempt.operation == "create_waybill",
                        ProviderOperationAttempt.status == "succeeded",
                    )
                    .order_by(ProviderOperationAttempt.attempt_no.asc())
                    .limit(2)
                    .with_for_update()
                )
            )
            if (
                shipment is None
                or shipment.provider != "sf"
                or shipment.status != "submitted"
                or shipment.waybill_no is None
                or shipment.submitted_at is None
                or len(succeeded) != 1
                or succeeded[0].id != attempt.id
                or attempt.integration_secret_revision_uuid
                != shipment.integration_secret_revision_uuid
                or attempt.provider_account_secret_revision_uuid
                != shipment.provider_account_secret_revision_uuid
                or attempt.binding_revision != shipment.binding_revision
            ):
                raise RelayShipmentResultSignalConflict()
            relay_cases = tuple(
                tenant_session.scalars(
                    sa.select(RentalRelayCase)
                    .where(
                        RentalRelayCase.successor_rental_id == shipment.rental_id,
                        RentalRelayCase.status == "agreed",
                    )
                    .order_by(RentalRelayCase.id.asc())
                    .limit(2)
                    .with_for_update()
                )
            )
            if not relay_cases:
                return None
            if len(relay_cases) != 1:
                raise RelayShipmentResultSignalConflict()
            relay_case = relay_cases[0]
            return RelayShipmentSubmissionSignal(
                shipment_uuid=shipment.id,
                predecessor_rental_id=relay_case.predecessor_rental_id,
                successor_rental_id=relay_case.successor_rental_id,
                waybill_no=shipment.waybill_no,
                source_result_digest=attempt.response_hash,
                occurred_at=_as_utc(shipment.submitted_at),
            )
        except RelayShipmentResultSignalError:
            raise
        except SQLAlchemyError:
            raise RelayShipmentResultSignalPersistenceError() from None
        except Exception:
            raise RelayShipmentResultSignalConflict() from None


class RelayCommittedShipmentResultEnqueuer:
    """Write the direct job after tenant result commit using current authority."""

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        coordinator: RelayExternalProjectionCoordinator | None = None,
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise TypeError("control_database must be a ControlDatabase")
        selected = coordinator or RelayExternalProjectionCoordinator()
        if not callable(getattr(selected, "enqueue", None)):
            raise TypeError("relay external projection coordinator is invalid")
        self._database = control_database
        self._coordinator = selected

    def enqueue(
        self,
        *,
        tenant_uuid: str | UUID,
        signal: RelayShipmentSubmissionSignal,
        available_at: datetime,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> BackgroundJob:
        if not isinstance(signal, RelayShipmentSubmissionSignal):
            raise RelayShipmentResultSignalInputError()
        try:
            tenant_id = str(UUID(str(tenant_uuid)))
            current_time = _utc(available_at)
        except (TypeError, ValueError):
            raise RelayShipmentResultSignalInputError() from None
        try:
            with self._database.transaction() as control_session:
                tenant = control_session.scalar(
                    sa.select(Tenant)
                    .where(Tenant.id == tenant_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if (
                    tenant is None
                    or tenant.status != "active"
                    or tenant.access_version < 1
                ):
                    raise RelayShipmentResultSignalConflict()
                command = signal.command(tenant_timezone=tenant.timezone)
                return self._coordinator.enqueue(
                    control_session,
                    tenant_uuid=tenant.id,
                    tenant_access_version=tenant.access_version,
                    command=command,
                    available_at=current_time,
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
        except RelayShipmentResultSignalError:
            raise
        except SQLAlchemyError:
            raise RelayShipmentResultSignalPersistenceError() from None
        except Exception:
            raise RelayShipmentResultSignalConflict() from None


def _require_transaction(session: Session) -> None:
    require_caller_transaction(session, RelayShipmentResultSignalInputError)


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


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "RelayCommittedShipmentResultEnqueuer",
    "RelayShipmentResultSignalConflict",
    "RelayShipmentResultSignalError",
    "RelayShipmentResultSignalInputError",
    "RelayShipmentResultSignalPersistenceError",
    "RelayShipmentResultSignalService",
    "RelayShipmentSubmissionSignal",
]
