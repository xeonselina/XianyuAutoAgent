"""Typed, single-dispatch boundary for provider-backed SF tracking reads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence

from inventory_control.integrations import (
    SfHistoricalTrackingRequest,
    SfTrackingQueryItem,
)


_SAFE_STATUS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_MAX_EVENTS_PER_SHIPMENT = 200


class TrackingProviderError(RuntimeError):
    code = "SF_TRACKING_PROVIDER_UNAVAILABLE"
    public_message = "shipment tracking is temporarily unavailable"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class TrackingProviderResponseError(TrackingProviderError):
    code = "SF_TRACKING_PROVIDER_RESPONSE_INVALID"


@dataclass(frozen=True, slots=True)
class SfTrackingRouteEvent:
    occurred_at: datetime
    status_code: str
    summary: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.occurred_at, datetime)
            or self.occurred_at.tzinfo is None
            or self.occurred_at.utcoffset() is None
            or not isinstance(self.status_code, str)
            or _SAFE_STATUS.fullmatch(self.status_code) is None
            or not isinstance(self.summary, str)
            or not self.summary
            or len(self.summary) > 500
            or any(ord(character) < 0x20 for character in self.summary)
        ):
            raise ValueError("tracking route event is invalid")


@dataclass(frozen=True, slots=True)
class SfTrackingRouteResult:
    shipment_uuid: str
    waybill_no: str
    status_code: str
    events: tuple[SfTrackingRouteEvent, ...]

    def __post_init__(self) -> None:
        item = SfTrackingQueryItem(
            shipment_uuid=self.shipment_uuid,
            waybill_no=self.waybill_no,
        )
        selected_events = tuple(self.events)
        if (
            not isinstance(self.status_code, str)
            or _SAFE_STATUS.fullmatch(self.status_code) is None
            or len(selected_events) > _MAX_EVENTS_PER_SHIPMENT
            or any(
                not isinstance(event, SfTrackingRouteEvent)
                for event in selected_events
            )
        ):
            raise ValueError("tracking route result is invalid")
        object.__setattr__(self, "shipment_uuid", item.shipment_uuid)
        object.__setattr__(self, "waybill_no", item.waybill_no)
        object.__setattr__(self, "events", selected_events)


@dataclass(frozen=True, slots=True)
class ShipmentTrackingResult:
    shipment_uuid: str
    waybill_no: str
    found: bool
    status_code: str
    events: tuple[SfTrackingRouteEvent, ...]
    last_update: datetime | None


class SfTrackingProviderAdapter(Protocol):
    """Adapter must consume credentials from the request inside this call."""

    def query_routes(
        self,
        request: SfHistoricalTrackingRequest,
    ) -> Sequence[SfTrackingRouteResult]: ...


class SfHistoricalTrackingDispatcher:
    """Invoke one injected read-only adapter and sanitize its typed result."""

    @staticmethod
    def dispatch(
        *,
        request: SfHistoricalTrackingRequest,
        adapter: SfTrackingProviderAdapter,
    ) -> tuple[ShipmentTrackingResult, ...]:
        if not isinstance(request, SfHistoricalTrackingRequest) or not callable(
            getattr(adapter, "query_routes", None)
        ):
            raise TrackingProviderError()
        requested = {item.shipment_uuid: item for item in request.items}
        try:
            raw_results = adapter.query_routes(request)
            if isinstance(raw_results, (str, bytes)) or not isinstance(
                raw_results, Sequence
            ):
                raise TrackingProviderResponseError()
            by_shipment: dict[str, SfTrackingRouteResult] = {}
            for result in raw_results:
                if not isinstance(result, SfTrackingRouteResult):
                    raise TrackingProviderResponseError()
                expected = requested.get(result.shipment_uuid)
                if (
                    expected is None
                    or expected.waybill_no != result.waybill_no
                    or result.shipment_uuid in by_shipment
                ):
                    raise TrackingProviderResponseError()
                by_shipment[result.shipment_uuid] = result
            return tuple(
                _public_result(item, by_shipment.get(item.shipment_uuid))
                for item in request.items
            )
        except TrackingProviderError:
            raise
        except Exception as exc:
            raise TrackingProviderError() from exc
        finally:
            request.discard_credentials()


def _public_result(
    item: SfTrackingQueryItem,
    result: SfTrackingRouteResult | None,
) -> ShipmentTrackingResult:
    if result is None:
        return ShipmentTrackingResult(
            shipment_uuid=item.shipment_uuid,
            waybill_no=item.waybill_no,
            found=False,
            status_code="not_found",
            events=(),
            last_update=None,
        )
    events = tuple(
        sorted(result.events, key=lambda event: event.occurred_at)
    )
    return ShipmentTrackingResult(
        shipment_uuid=result.shipment_uuid,
        waybill_no=result.waybill_no,
        found=True,
        status_code=result.status_code,
        events=events,
        last_update=(events[-1].occurred_at if events else None),
    )


__all__ = [
    "SfHistoricalTrackingDispatcher",
    "SfTrackingProviderAdapter",
    "SfTrackingRouteEvent",
    "SfTrackingRouteResult",
    "ShipmentTrackingResult",
    "TrackingProviderError",
    "TrackingProviderResponseError",
]
