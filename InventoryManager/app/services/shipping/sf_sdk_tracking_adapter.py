"""SF SDK adapter for typed historical tracking requests.

Construction is explicit and performs no network I/O.  Tests inject a fake
client factory; production composition must choose the endpoint mode and
provider timezone rather than inheriting process environment defaults.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from app.utils.sf.sf_sdk_wrapper import SFExpressSDK
from inventory_control.integrations import SfHistoricalTrackingRequest

from .tracking_provider import (
    SfTrackingRouteEvent,
    SfTrackingRouteResult,
    TrackingProviderError,
)


class SfSdkTrackingAdapter:
    """Map one exact-revision request onto SF's bounded route API."""

    __slots__ = ("_test_mode", "_provider_timezone", "_client_factory")

    def __init__(
        self,
        *,
        test_mode: bool,
        provider_timezone: ZoneInfo,
        client_factory: Callable[..., SFExpressSDK] = SFExpressSDK,
    ) -> None:
        if not isinstance(test_mode, bool):
            raise TypeError("test_mode must be a bool")
        if not isinstance(provider_timezone, ZoneInfo):
            raise TypeError("provider_timezone must be a ZoneInfo")
        if not callable(client_factory):
            raise TypeError("client_factory must be callable")
        self._test_mode = test_mode
        self._provider_timezone = provider_timezone
        self._client_factory = client_factory

    def query_routes(
        self,
        request: SfHistoricalTrackingRequest,
    ) -> tuple[SfTrackingRouteResult, ...]:
        if not isinstance(request, SfHistoricalTrackingRequest):
            raise TrackingProviderError()
        credentials, account_secret = request.take_credentials()
        try:
            # The monthly-account revision is an ownership/history fence.  SF's
            # EXP_RECE_SEARCH_ROUTES request authenticates with partner/checkword
            # and phone-last-four and has no monthly-account request field.
            if not account_secret:
                raise TrackingProviderError()
            client = self._client_factory(
                partner_id=credentials["partner_id"],
                checkword=credentials["checkword"],
                test_mode=self._test_mode,
            )
            waybills = [item.waybill_no for item in request.items]
            response = client.batch_search_routes(
                waybills,
                request.phone_last4,
            )
            if (
                not isinstance(response, dict)
                or response.get("apiResultCode") != "A1000"
            ):
                raise TrackingProviderError()
            parsed = client.parse_route_response(response)
            if not isinstance(parsed, dict):
                raise TrackingProviderError()
            item_by_waybill = {item.waybill_no: item for item in request.items}
            results = []
            for waybill_no, route_info in parsed.items():
                item = item_by_waybill.get(waybill_no)
                if item is None or not isinstance(route_info, dict):
                    raise TrackingProviderError()
                raw_routes = route_info.get("routes", ())
                if not isinstance(raw_routes, list):
                    raise TrackingProviderError()
                events = tuple(self._event(route) for route in raw_routes)
                status = route_info.get("status")
                results.append(
                    SfTrackingRouteResult(
                        shipment_uuid=item.shipment_uuid,
                        waybill_no=item.waybill_no,
                        status_code=status,
                        events=events,
                    )
                )
            return tuple(results)
        except TrackingProviderError:
            raise
        except Exception as exc:
            raise TrackingProviderError() from exc
        finally:
            del account_secret

    def _event(self, route) -> SfTrackingRouteEvent:
        if not isinstance(route, dict):
            raise TrackingProviderError()
        try:
            occurred_at = datetime.fromisoformat(str(route["accept_time"]))
        except (KeyError, TypeError, ValueError):
            raise TrackingProviderError() from None
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=self._provider_timezone)
        status, _status_text = SFExpressSDK._resolve_route_status(route)
        summary = str(
            route.get("remark")
            or route.get("secondary_status_name")
            or route.get("first_status_name")
            or "轨迹已更新"
        )
        try:
            return SfTrackingRouteEvent(
                occurred_at=occurred_at,
                status_code=status,
                summary=summary,
            )
        except ValueError:
            raise TrackingProviderError() from None

    def __repr__(self) -> str:
        return (
            "SfSdkTrackingAdapter("
            f"test_mode={self._test_mode!r}, "
            f"provider_timezone={self._provider_timezone.key!r}, "
            "credentials=<request-scoped>)"
        )


__all__ = ["SfSdkTrackingAdapter"]
