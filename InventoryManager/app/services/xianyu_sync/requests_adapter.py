"""Production-shaped HTTP adapter for the current Xianyu order-list API."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import time
from typing import Any, Callable, Mapping, Protocol

import requests

from inventory_control.integrations import XianyuSyncProviderRequest

from .contracts import XianyuAlertFact
from .provider import (
    XianyuProviderError,
    XianyuProviderRateLimited,
    XianyuProviderSettings,
    XianyuProviderSyncResponse,
)


class XianyuHttpResponse(Protocol):
    status_code: int

    def json(self) -> object: ...


class XianyuHttpClient(Protocol):
    def post(self, url: str, **kwargs: Any) -> XianyuHttpResponse: ...


class RequestsXianyuProviderAdapter:
    """Fetch a complete status-12 snapshot without environment fallbacks."""

    def __init__(
        self,
        *,
        http_client: XianyuHttpClient | None = None,
        epoch_seconds: Callable[[], int] | None = None,
    ) -> None:
        client = http_client or requests.Session()
        if not callable(getattr(client, "post", None)):
            raise TypeError("Xianyu HTTP client is invalid")
        if epoch_seconds is not None and not callable(epoch_seconds):
            raise TypeError("Xianyu clock is invalid")
        self._http_client = client
        self._epoch_seconds = epoch_seconds or (lambda: int(time.time()))

    def fetch_alerts(
        self,
        *,
        request: XianyuSyncProviderRequest,
        settings: XianyuProviderSettings,
    ) -> XianyuProviderSyncResponse:
        if not isinstance(request, XianyuSyncProviderRequest) or not isinstance(
            settings, XianyuProviderSettings
        ):
            raise TypeError("Xianyu provider request is invalid")
        credentials = request.take_credentials()
        app_key = credentials["app_key"]
        app_secret = credentials["app_secret"]
        orders: list[Mapping[str, object]] = []
        expected_total: int | None = None

        for page_no in range(1, settings.max_pages + 1):
            body = {
                "order_status": 12,
                "page_no": page_no,
                "page_size": settings.page_size,
            }
            payload = json.dumps(body, separators=(",", ":"), sort_keys=False)
            timestamp = self._timestamp()
            sign = _body_sign(
                app_key=app_key,
                app_secret=app_secret,
                body=payload,
                timestamp=timestamp,
            )
            response = self._post(
                settings=settings,
                payload=payload,
                provider_timestamp=timestamp,
                params={
                    "appid": app_key,
                    "timestamp": timestamp,
                    "sign": sign,
                },
            )
            envelope = self._envelope(response)
            data = envelope.get("data")
            if not isinstance(data, Mapping) or not isinstance(
                data.get("list"), list
            ):
                raise XianyuProviderError("PROVIDER_RESPONSE_INVALID")
            total = _nonnegative_int(data.get("count"))
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise XianyuProviderError("PROVIDER_RESPONSE_INCONSISTENT")
            orders.extend(_order_mapping(item) for item in data["list"])
            if len(orders) > expected_total:
                raise XianyuProviderError("PROVIDER_RESPONSE_INCONSISTENT")
            if len(orders) == expected_total:
                return XianyuProviderSyncResponse(
                    alerts=_normalize_alerts(orders),
                    # The current provider contract is page-number based and
                    # publishes no opaque incremental cursor.  Do not invent
                    # or submit an undocumented one; the tenant column remains
                    # ready for a future provider-supported cursor contract.
                    next_cursor=None,
                )
            if not data["list"]:
                raise XianyuProviderError("PROVIDER_RESPONSE_INCOMPLETE")
        raise XianyuProviderError("PROVIDER_RESPONSE_INCOMPLETE")

    def _post(
        self,
        *,
        settings: XianyuProviderSettings,
        payload: str,
        provider_timestamp: int,
        params: dict[str, object],
    ) -> XianyuHttpResponse:
        try:
            response = self._http_client.post(
                f"{settings.endpoint}/api/open/order/list",
                params=params,
                data=payload,
                headers={"Content-Type": "application/json"},
                timeout=(
                    settings.connect_timeout_seconds,
                    settings.read_timeout_seconds,
                ),
                allow_redirects=False,
            )
        except Exception as exc:
            raise XianyuProviderError("PROVIDER_UNAVAILABLE") from exc
        if not isinstance(getattr(response, "status_code", None), int):
            raise XianyuProviderError("PROVIDER_RESPONSE_INVALID")
        if response.status_code == 429:
            raise XianyuProviderRateLimited(
                retry_after_at=datetime.fromtimestamp(
                    provider_timestamp + settings.rate_limit_retry_seconds,
                    tz=timezone.utc,
                )
            )
        if not 200 <= response.status_code < 300:
            raise XianyuProviderError("PROVIDER_HTTP_ERROR")
        return response

    @staticmethod
    def _envelope(response: XianyuHttpResponse) -> Mapping[str, object]:
        try:
            value = response.json()
        except Exception as exc:
            raise XianyuProviderError("PROVIDER_RESPONSE_INVALID") from exc
        if not isinstance(value, Mapping):
            raise XianyuProviderError("PROVIDER_RESPONSE_INVALID")
        if value.get("code") != 0:
            raise XianyuProviderError("PROVIDER_REJECTED")
        return value

    def _timestamp(self) -> int:
        value = self._epoch_seconds()
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise XianyuProviderError("PROVIDER_CLOCK_INVALID")
        return value


def _body_sign(*, app_key: str, app_secret: str, body: str, timestamp: int) -> str:
    body_digest = hashlib.md5(body.encode("utf-8")).hexdigest()
    canonical = f"{app_key},{body_digest},{timestamp},{app_secret}"
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool):
        raise XianyuProviderError("PROVIDER_RESPONSE_INVALID")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise XianyuProviderError("PROVIDER_RESPONSE_INVALID") from None
    if parsed < 0 or str(parsed) != str(value):
        raise XianyuProviderError("PROVIDER_RESPONSE_INVALID")
    return parsed


def _order_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise XianyuProviderError("PROVIDER_RESPONSE_INVALID")
    return value


def _normalize_alerts(
    orders: list[Mapping[str, object]],
) -> tuple[XianyuAlertFact, ...]:
    alerts: list[XianyuAlertFact] = []
    seen: set[str] = set()
    for order in orders:
        order_no = _required_text(order.get("order_no"))
        pay_amount = _nonnegative_int(order.get("pay_amount"))
        if order_no in seen:
            raise XianyuProviderError("PROVIDER_RESPONSE_INCONSISTENT")
        seen.add(order_no)
        if pay_amount <= 5000:
            continue
        goods = order.get("goods")
        if goods is None:
            goods = {}
        if not isinstance(goods, Mapping):
            raise XianyuProviderError("PROVIDER_RESPONSE_INVALID")
        alerts.append(
            XianyuAlertFact(
                order_no=order_no,
                pay_amount=pay_amount,
                buyer_nick=_optional_text(order.get("buyer_nick")),
                receiver_name=_optional_text(order.get("receiver_name")),
                receiver_mobile=_optional_text(order.get("receiver_mobile")),
                address="".join(
                    _optional_text(order.get(field)) or ""
                    for field in (
                        "prov_name",
                        "city_name",
                        "area_name",
                        "town_name",
                        "address",
                    )
                )
                or None,
                goods_title=_optional_text(goods.get("title")),
                goods_sku_text=_optional_text(goods.get("sku_text")),
                order_time=_unix_time(order.get("order_time")),
            )
        )
    return tuple(alerts)


def _required_text(value: object) -> str:
    selected = _optional_text(value)
    if selected is None:
        raise XianyuProviderError("PROVIDER_RESPONSE_INVALID")
    return selected


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise XianyuProviderError("PROVIDER_RESPONSE_INVALID")
    selected = value.strip()
    return selected or None


def _unix_time(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise XianyuProviderError("PROVIDER_RESPONSE_INVALID")
    try:
        seconds = int(value)
        if str(seconds) != str(value):
            raise ValueError
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (ValueError, TypeError, OSError, OverflowError):
        raise XianyuProviderError("PROVIDER_RESPONSE_INVALID") from None


__all__ = ["RequestsXianyuProviderAdapter"]
