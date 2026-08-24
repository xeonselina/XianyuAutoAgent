"""Provider-free read API for D68 legacy-unattributed history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.legacy_unattributed_history import (
    LEGACY_UNATTRIBUTED_KIND,
    LegacyUnattributedPrintSnapshot,
    LegacyUnattributedShipmentSnapshot,
)


class LegacyHistoryQueryError(RuntimeError):
    code = "LEGACY_HISTORY_QUERY_FAILED"


class LegacyHistoryQueryInputError(LegacyHistoryQueryError):
    code = "LEGACY_HISTORY_QUERY_INPUT_INVALID"


@dataclass(frozen=True, slots=True)
class LegacyShipmentHistorySummary:
    snapshot_id: str
    record_kind: str
    rental_id: int
    lifecycle_status: str
    ship_out_tracking_no: str | None
    ship_in_tracking_no: str | None
    shipped_at: datetime | None
    returned_at: datetime | None
    actionable: bool = False
    available_actions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LegacyPrintHistorySummary:
    snapshot_id: str
    record_kind: str
    rental_id: int | None
    shipment_snapshot_id: str | None
    occurred_at: datetime | None
    actionable: bool = False
    available_actions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LegacyHistoryPage:
    shipment_items: tuple[LegacyShipmentHistorySummary, ...]
    print_items: tuple[LegacyPrintHistorySummary, ...]


class LegacyUnattributedHistoryQueryService:
    """Return bounded display DTOs and expose no provider action method."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise LegacyHistoryQueryInputError()
        self._session = session

    def list_history(self, *, limit: int = 50) -> LegacyHistoryPage:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise LegacyHistoryQueryInputError()
        shipments = tuple(
            self._session.scalars(
                sa.select(LegacyUnattributedShipmentSnapshot)
                .order_by(
                    LegacyUnattributedShipmentSnapshot.created_at.desc(),
                    LegacyUnattributedShipmentSnapshot.id.desc(),
                )
                .limit(limit)
                .execution_options(autoflush=False)
            )
        )
        prints = tuple(
            self._session.scalars(
                sa.select(LegacyUnattributedPrintSnapshot)
                .order_by(
                    LegacyUnattributedPrintSnapshot.occurred_at.desc(),
                    LegacyUnattributedPrintSnapshot.id.desc(),
                )
                .limit(limit)
                .execution_options(autoflush=False)
            )
        )
        return LegacyHistoryPage(
            shipment_items=tuple(
                LegacyShipmentHistorySummary(
                    snapshot_id=row.id,
                    record_kind=LEGACY_UNATTRIBUTED_KIND,
                    rental_id=row.rental_id,
                    lifecycle_status=row.lifecycle_status,
                    ship_out_tracking_no=row.ship_out_tracking_no,
                    ship_in_tracking_no=row.ship_in_tracking_no,
                    shipped_at=row.shipped_at,
                    returned_at=row.returned_at,
                )
                for row in shipments
            ),
            print_items=tuple(
                LegacyPrintHistorySummary(
                    snapshot_id=row.id,
                    record_kind=LEGACY_UNATTRIBUTED_KIND,
                    rental_id=row.rental_id,
                    shipment_snapshot_id=row.shipment_snapshot_id,
                    occurred_at=row.occurred_at,
                )
                for row in prints
            ),
        )


__all__ = [
    "LegacyHistoryPage",
    "LegacyHistoryQueryError",
    "LegacyHistoryQueryInputError",
    "LegacyPrintHistorySummary",
    "LegacyShipmentHistorySummary",
    "LegacyUnattributedHistoryQueryService",
]
