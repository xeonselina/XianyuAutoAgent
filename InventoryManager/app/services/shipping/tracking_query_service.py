"""Provider-free shipment tracking pagination and historical batch planning.

The public page DTO intentionally excludes credential references and receiver
PII.  Historical revision UUIDs are present only in the internal batch plan
consumed by the control-plane credential resolver before provider I/O.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.shipping_execution import OutboundShipment
from inventory_control.integrations import SfProviderExecutionContext


_MAX_PAGE_SIZE = 100
_MAX_BATCH_SELECTION = 500
_PROVIDER_BATCH_SIZE = 100
_PHONE_LAST4 = re.compile(r"^\d{4}$")
_TRACKABLE_STATUSES = frozenset(
    {
        "submitted",
        "cancel_requested",
        "cancel_unknown",
        "cancelled",
        "needs_review",
    }
)


class TrackingQueryError(RuntimeError):
    code = "TRACKING_QUERY_ERROR"
    public_message = "shipment tracking query failed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class TrackingQueryInputError(TrackingQueryError):
    code = "TRACKING_QUERY_INPUT_INVALID"
    public_message = "shipment tracking query input is invalid"


class TrackingShipmentUnavailableError(TrackingQueryError):
    code = "TRACKING_SHIPMENT_UNAVAILABLE"
    public_message = "one or more shipments are unavailable for tracking"


class TrackingCredentialContextError(TrackingQueryError):
    code = "TRACKING_CREDENTIAL_CONTEXT_INVALID"
    public_message = "historical shipment credentials are unavailable"


@dataclass(frozen=True, slots=True)
class ShipmentTrackingSummary:
    shipment_id: str
    rental_id: int
    waybill_no: str
    shipment_status: str
    origin_warehouse_uuid: str
    submitted_at: datetime


@dataclass(frozen=True, slots=True)
class ShipmentTrackingPage:
    items: tuple[ShipmentTrackingSummary, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class HistoricalTrackingShipment:
    shipment_id: str
    waybill_no: str


@dataclass(frozen=True, slots=True)
class HistoricalTrackingBatch:
    """Internal-only exact-revision provider query plan."""

    integration_uuid: str
    provider_account_uuid: str
    integration_secret_revision_uuid: str
    provider_account_secret_revision_uuid: str
    origin_warehouse_uuid: str
    binding_revision: int
    phone_last4: str
    shipments: tuple[HistoricalTrackingShipment, ...]


@dataclass(frozen=True, slots=True)
class ResolvedHistoricalTrackingBatch:
    provider_context: SfProviderExecutionContext
    phone_last4: str
    shipments: tuple[HistoricalTrackingShipment, ...]


class ShipmentTrackingQueryService:
    """Read tenant snapshots and prepare bounded historical SF query batches."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session")
        self._session = session

    def list_shipments(
        self,
        *,
        page_size: int = 50,
        after_cursor: str | None = None,
    ) -> ShipmentTrackingPage:
        """Return one keyset page without a table-wide count or PII join."""

        selected_size = _page_size(page_size)
        cursor = _decode_cursor(after_cursor)
        conditions = [
            OutboundShipment.provider == "sf",
            OutboundShipment.status.in_(_TRACKABLE_STATUSES),
            OutboundShipment.waybill_no.is_not(None),
            OutboundShipment.waybill_no != "",
            OutboundShipment.submitted_at.is_not(None),
        ]
        if cursor is not None:
            submitted_at, shipment_id = cursor
            conditions.append(
                or_(
                    OutboundShipment.submitted_at < submitted_at,
                    and_(
                        OutboundShipment.submitted_at == submitted_at,
                        OutboundShipment.id < shipment_id,
                    ),
                )
            )
        rows = tuple(
            self._session.execute(
                select(OutboundShipment)
                .where(*conditions)
                .order_by(
                    OutboundShipment.submitted_at.desc(),
                    OutboundShipment.id.desc(),
                )
                .limit(selected_size + 1)
            )
            .scalars()
            .all()
        )
        visible = rows[:selected_size]
        next_cursor = None
        if len(rows) > selected_size and visible:
            last = visible[-1]
            next_cursor = _encode_cursor(last.submitted_at, last.id)
        return ShipmentTrackingPage(
            items=tuple(_summary(row) for row in visible),
            next_cursor=next_cursor,
        )

    def plan_historical_batches(
        self,
        *,
        shipment_ids: Sequence[str | UUID],
    ) -> tuple[HistoricalTrackingBatch, ...]:
        """Group trusted snapshots by exact context and SF phone verifier.

        A group is capped at the provider's 100-waybill request limit.  The
        extra warehouse/account fields are deliberate fail-closed fences: a
        tampered shipment cannot borrow a valid revision pair from another
        historical context.
        """

        selected_ids = _shipment_ids(shipment_ids)
        rows = tuple(
            self._session.execute(
                select(OutboundShipment).where(
                    OutboundShipment.id.in_(selected_ids)
                )
            )
            .scalars()
            .all()
        )
        by_id = {row.id: row for row in rows}
        if len(by_id) != len(selected_ids):
            raise TrackingShipmentUnavailableError()

        grouped: OrderedDict[tuple[object, ...], list[HistoricalTrackingShipment]]
        grouped = OrderedDict()
        for shipment_id in selected_ids:
            row = by_id[shipment_id]
            facts = _historical_facts(row)
            key = facts[:-1]
            grouped.setdefault(key, []).append(facts[-1])

        batches: list[HistoricalTrackingBatch] = []
        for key, shipments in grouped.items():
            (
                integration_uuid,
                account_uuid,
                integration_revision_uuid,
                account_revision_uuid,
                warehouse_uuid,
                binding_revision,
                phone_last4,
            ) = key
            for offset in range(0, len(shipments), _PROVIDER_BATCH_SIZE):
                batches.append(
                    HistoricalTrackingBatch(
                        integration_uuid=integration_uuid,
                        provider_account_uuid=account_uuid,
                        integration_secret_revision_uuid=(
                            integration_revision_uuid
                        ),
                        provider_account_secret_revision_uuid=(
                            account_revision_uuid
                        ),
                        origin_warehouse_uuid=warehouse_uuid,
                        binding_revision=binding_revision,
                        phone_last4=phone_last4,
                        shipments=tuple(
                            shipments[offset : offset + _PROVIDER_BATCH_SIZE]
                        ),
                    )
                )
        return tuple(batches)

    @staticmethod
    def resolve_historical_batches(
        *,
        tenant_uuid: str | UUID,
        batches: Sequence[HistoricalTrackingBatch],
        context_loader: Callable[..., SfProviderExecutionContext],
    ) -> tuple[ResolvedHistoricalTrackingBatch, ...]:
        """Resolve every batch via exact historical pointers, never current ones."""

        tenant_id = _uuid(tenant_uuid)
        if not callable(context_loader):
            raise TrackingCredentialContextError()
        resolved: list[ResolvedHistoricalTrackingBatch] = []
        for batch in batches:
            if not isinstance(batch, HistoricalTrackingBatch):
                raise TrackingCredentialContextError()
            try:
                context = context_loader(
                    tenant_uuid=tenant_id,
                    warehouse_uuid=batch.origin_warehouse_uuid,
                    binding_revision=batch.binding_revision,
                    integration_secret_revision_uuid=(
                        batch.integration_secret_revision_uuid
                    ),
                    provider_account_secret_revision_uuid=(
                        batch.provider_account_secret_revision_uuid
                    ),
                )
            except Exception as exc:
                raise TrackingCredentialContextError() from exc
            if not _context_matches(
                context,
                tenant_uuid=tenant_id,
                batch=batch,
            ):
                raise TrackingCredentialContextError()
            resolved.append(
                ResolvedHistoricalTrackingBatch(
                    provider_context=context,
                    phone_last4=batch.phone_last4,
                    shipments=batch.shipments,
                )
            )
        return tuple(resolved)


def _historical_facts(row: OutboundShipment) -> tuple[object, ...]:
    if (
        row.provider != "sf"
        or row.status not in _TRACKABLE_STATUSES
        or row.submitted_at is None
        or not isinstance(row.waybill_no, str)
        or not row.waybill_no.strip()
        or len(row.waybill_no.strip()) > 64
        or not isinstance(row.binding_revision, int)
        or isinstance(row.binding_revision, bool)
        or row.binding_revision < 1
        or not isinstance(row.tracking_check_phone_last4, str)
        or _PHONE_LAST4.fullmatch(row.tracking_check_phone_last4) is None
    ):
        raise TrackingShipmentUnavailableError()
    return (
        _uuid(row.integration_uuid),
        _uuid(row.provider_account_uuid),
        _uuid(row.integration_secret_revision_uuid),
        _uuid(row.provider_account_secret_revision_uuid),
        _uuid(row.origin_warehouse_uuid),
        row.binding_revision,
        row.tracking_check_phone_last4,
        HistoricalTrackingShipment(
            shipment_id=_uuid(row.id),
            waybill_no=row.waybill_no.strip(),
        ),
    )


def _context_matches(
    context: object,
    *,
    tenant_uuid: str,
    batch: HistoricalTrackingBatch,
) -> bool:
    return bool(
        isinstance(context, SfProviderExecutionContext)
        and context.historical is True
        and context.tenant_uuid == tenant_uuid
        and context.warehouse_uuid == batch.origin_warehouse_uuid
        and context.integration_uuid == batch.integration_uuid
        and context.provider_account_uuid == batch.provider_account_uuid
        and context.integration_secret_revision_uuid
        == batch.integration_secret_revision_uuid
        and context.provider_account_secret_revision_uuid
        == batch.provider_account_secret_revision_uuid
        and context.binding_revision == batch.binding_revision
    )


def _summary(row: OutboundShipment) -> ShipmentTrackingSummary:
    if row.submitted_at is None or row.waybill_no is None:
        raise TrackingShipmentUnavailableError()
    return ShipmentTrackingSummary(
        shipment_id=_uuid(row.id),
        rental_id=row.rental_id,
        waybill_no=row.waybill_no,
        shipment_status=row.status,
        origin_warehouse_uuid=_uuid(row.origin_warehouse_uuid),
        submitted_at=row.submitted_at,
    )


def _shipment_ids(values: Sequence[str | UUID]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TrackingQueryInputError()
    if not values or len(values) > _MAX_BATCH_SELECTION:
        raise TrackingQueryInputError()
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        selected = _uuid(value)
        if selected not in seen:
            seen.add(selected)
            normalized.append(selected)
    return tuple(normalized)


def _page_size(value: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > _MAX_PAGE_SIZE
    ):
        raise TrackingQueryInputError()
    return value


def _encode_cursor(submitted_at: datetime, shipment_id: str) -> str:
    payload = json.dumps(
        [1, submitted_at.isoformat(timespec="microseconds"), _uuid(shipment_id)],
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _decode_cursor(value: str | None) -> tuple[datetime, str] | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 512:
        raise TrackingQueryInputError()
    try:
        encoded = value.encode("ascii")
        raw = base64.b64decode(
            encoded + b"=" * (-len(encoded) % 4),
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(payload, list)
            or len(payload) != 3
            or payload[0] != 1
            or not isinstance(payload[1], str)
        ):
            raise ValueError
        submitted_at = datetime.fromisoformat(payload[1])
        if submitted_at.tzinfo is not None:
            raise ValueError
        return submitted_at, _uuid(payload[2])
    except (
        binascii.Error,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        raise TrackingQueryInputError() from exc


def _uuid(value: str | UUID) -> str:
    try:
        return str(value if isinstance(value, UUID) else UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise TrackingQueryInputError() from exc
