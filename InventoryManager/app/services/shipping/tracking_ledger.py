"""Immutable, provider-free shipment tracking result authority.

The provider adapter is responsible for normalizing its response into one of
the closed statuses below.  This service accepts no credential or provider
client and owns no transaction; it records only a canonical digest and safe
technical facts in the existing tenant audit ledger.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.shipping_execution import OutboundShipment
from inventory_control.transactions import require_caller_transaction


SHIPMENT_TRACKING_RESULT_ACTION = "shipment_tracking_result_recorded"
SHIPMENT_TRACKING_RESOURCE_TYPE = "outbound_shipment"
_RESULT_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_DETAIL_KEYS = {
    "contract_version",
    "shipment_uuid",
    "waybill_no",
    "status",
    "occurred_at",
    "result_digest",
}


class ShipmentTrackingLedgerError(RuntimeError):
    code = "SHIPMENT_TRACKING_LEDGER_FAILED"
    public_message = "shipment tracking result could not be recorded"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class ShipmentTrackingLedgerInputError(ShipmentTrackingLedgerError):
    code = "SHIPMENT_TRACKING_LEDGER_INPUT_INVALID"


class ShipmentTrackingLedgerConflict(ShipmentTrackingLedgerError):
    code = "SHIPMENT_TRACKING_LEDGER_CONFLICT"


class ShipmentTrackingLedgerPersistenceError(ShipmentTrackingLedgerError):
    code = "SHIPMENT_TRACKING_LEDGER_PERSISTENCE_FAILED"


class ShipmentTrackingStatus(str, Enum):
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    EXCEPTION = "exception"


@dataclass(frozen=True, slots=True)
class ShipmentTrackingObservation:
    shipment_uuid: str
    waybill_no: str
    status: ShipmentTrackingStatus
    occurred_at: datetime

    def __post_init__(self) -> None:
        try:
            shipment_uuid = str(UUID(self.shipment_uuid))
            waybill_no = _text(self.waybill_no, maximum=64)
            status = ShipmentTrackingStatus(self.status)
            occurred_at = _utc(self.occurred_at)
        except (TypeError, ValueError):
            raise ShipmentTrackingLedgerInputError() from None
        object.__setattr__(self, "shipment_uuid", shipment_uuid)
        object.__setattr__(self, "waybill_no", waybill_no)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "occurred_at", occurred_at)

    @property
    def result_digest(self) -> str:
        document = {
            "contract_version": 1,
            "occurred_at": self.occurred_at.isoformat(timespec="microseconds"),
            "shipment_uuid": self.shipment_uuid,
            "status": self.status.value,
            "waybill_no": self.waybill_no,
        }
        return hashlib.sha256(
            json.dumps(
                document,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
        ).hexdigest()

    def audit_details(self) -> dict[str, object]:
        return {
            "contract_version": 1,
            "shipment_uuid": self.shipment_uuid,
            "waybill_no": self.waybill_no,
            "status": self.status.value,
            "occurred_at": self.occurred_at.isoformat(timespec="microseconds"),
            "result_digest": self.result_digest,
        }


@dataclass(frozen=True, slots=True)
class ShipmentTrackingLedgerReceipt:
    audit_id: int
    observation: ShipmentTrackingObservation
    idempotent_replay: bool = False


class ShipmentTrackingLedgerService:
    """Persist and verify canonical tracking observations in one transaction."""

    @classmethod
    def record(
        cls,
        *,
        tenant_session: Session,
        observation: ShipmentTrackingObservation,
    ) -> ShipmentTrackingLedgerReceipt:
        _require_transaction(tenant_session)
        if not isinstance(observation, ShipmentTrackingObservation):
            raise ShipmentTrackingLedgerInputError()
        try:
            shipment = tenant_session.scalar(
                sa.select(OutboundShipment)
                .where(OutboundShipment.id == observation.shipment_uuid)
                .with_for_update()
            )
            if (
                shipment is None
                or shipment.provider != "sf"
                or shipment.status != "submitted"
                or shipment.waybill_no != observation.waybill_no
                or shipment.submitted_at is None
                or _naive_utc(observation.occurred_at) < shipment.submitted_at
            ):
                raise ShipmentTrackingLedgerConflict()
            existing = cls._observations(
                tenant_session,
                shipment_uuid=observation.shipment_uuid,
                result_digest=observation.result_digest,
            )
            matches = tuple(
                receipt
                for receipt in existing
                if receipt.observation.result_digest == observation.result_digest
            )
            if len(matches) > 1:
                raise ShipmentTrackingLedgerConflict()
            if matches:
                if matches[0].observation != observation:
                    raise ShipmentTrackingLedgerConflict()
                return ShipmentTrackingLedgerReceipt(
                    audit_id=matches[0].audit_id,
                    observation=observation,
                    idempotent_replay=True,
                )
            audit = AuditLog(
                rental_id=shipment.rental_id,
                action=SHIPMENT_TRACKING_RESULT_ACTION,
                resource_type=SHIPMENT_TRACKING_RESOURCE_TYPE,
                resource_id=observation.shipment_uuid,
                description="shipment tracking result recorded",
                details=observation.audit_details(),
                created_at=_naive_utc(observation.occurred_at),
            )
            tenant_session.add(audit)
            tenant_session.flush()
            return ShipmentTrackingLedgerReceipt(
                audit_id=audit.id,
                observation=observation,
            )
        except ShipmentTrackingLedgerError:
            raise
        except SQLAlchemyError:
            raise ShipmentTrackingLedgerPersistenceError() from None

    @classmethod
    def require_delivered(
        cls,
        *,
        tenant_session: Session,
        shipment_uuid: str,
        waybill_no: str,
        result_digest: str,
        occurred_at: datetime,
    ) -> ShipmentTrackingLedgerReceipt:
        _require_transaction(tenant_session)
        try:
            selected_uuid = str(UUID(shipment_uuid))
            selected_waybill = _text(waybill_no, maximum=64)
            selected_time = _utc(occurred_at)
        except (TypeError, ValueError):
            raise ShipmentTrackingLedgerInputError() from None
        if (
            not isinstance(result_digest, str)
            or _RESULT_DIGEST.fullmatch(result_digest) is None
        ):
            raise ShipmentTrackingLedgerInputError()
        matches = tuple(
            receipt
            for receipt in cls._observations(
                tenant_session,
                shipment_uuid=selected_uuid,
                result_digest=result_digest,
            )
            if receipt.observation.result_digest == result_digest
        )
        if (
            len(matches) != 1
            or matches[0].observation.status is not ShipmentTrackingStatus.DELIVERED
            or matches[0].observation.waybill_no != selected_waybill
            or matches[0].observation.occurred_at != selected_time
        ):
            raise ShipmentTrackingLedgerConflict()
        return matches[0]

    @staticmethod
    def _observations(
        tenant_session: Session,
        *,
        shipment_uuid: str,
        result_digest: str,
    ) -> tuple[ShipmentTrackingLedgerReceipt, ...]:
        audits = tuple(
            tenant_session.scalars(
                sa.select(AuditLog)
                .where(
                    AuditLog.action == SHIPMENT_TRACKING_RESULT_ACTION,
                    AuditLog.resource_type == SHIPMENT_TRACKING_RESOURCE_TYPE,
                    AuditLog.resource_id == shipment_uuid,
                    AuditLog.details["result_digest"].as_string() == result_digest,
                )
                .order_by(AuditLog.id.desc())
                .limit(2)
                .with_for_update()
            )
        )
        receipts: list[ShipmentTrackingLedgerReceipt] = []
        for audit in audits:
            details = audit.details
            if not isinstance(details, dict) or set(details) != _DETAIL_KEYS:
                raise ShipmentTrackingLedgerConflict()
            try:
                observation = ShipmentTrackingObservation(
                    shipment_uuid=details["shipment_uuid"],
                    waybill_no=details["waybill_no"],
                    status=details["status"],
                    occurred_at=datetime.fromisoformat(details["occurred_at"]),
                )
            except (KeyError, TypeError, ValueError):
                raise ShipmentTrackingLedgerConflict() from None
            if (
                details["contract_version"] != 1
                or details["result_digest"] != observation.result_digest
                or observation.shipment_uuid != shipment_uuid
            ):
                raise ShipmentTrackingLedgerConflict()
            receipts.append(
                ShipmentTrackingLedgerReceipt(
                    audit_id=audit.id,
                    observation=observation,
                    idempotent_replay=True,
                )
            )
        return tuple(receipts)


def _require_transaction(session: Session) -> None:
    require_caller_transaction(session, ShipmentTrackingLedgerInputError)


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


__all__ = [
    "SHIPMENT_TRACKING_RESOURCE_TYPE",
    "SHIPMENT_TRACKING_RESULT_ACTION",
    "ShipmentTrackingLedgerConflict",
    "ShipmentTrackingLedgerError",
    "ShipmentTrackingLedgerInputError",
    "ShipmentTrackingLedgerPersistenceError",
    "ShipmentTrackingLedgerReceipt",
    "ShipmentTrackingLedgerService",
    "ShipmentTrackingObservation",
    "ShipmentTrackingStatus",
]
