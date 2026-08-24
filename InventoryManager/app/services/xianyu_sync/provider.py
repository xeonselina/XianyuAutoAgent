"""Typed provider boundary for one Xianyu connection synchronization."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Protocol
from urllib.parse import urlsplit

from inventory_control.integrations import XianyuSyncProviderRequest

from .contracts import (
    XianyuAlertFact,
    XianyuConnectionSyncResult,
    XianyuSyncInputError,
)


_SAFE_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]{0,63}$")


@dataclass(frozen=True, slots=True)
class XianyuProviderSettings:
    """Deployment-owned provider limits; none may come from a job payload."""

    endpoint: str
    connect_timeout_seconds: int
    read_timeout_seconds: int
    rate_limit_retry_seconds: int
    page_size: int
    max_pages: int

    def __post_init__(self) -> None:
        endpoint = (
            urlsplit(self.endpoint)
            if isinstance(self.endpoint, str)
            else None
        )
        if (
            endpoint is None
            or endpoint.scheme != "https"
            or not endpoint.hostname
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.query
            or endpoint.fragment
            or self.endpoint.endswith("/")
            or len(self.endpoint) > 512
            or any(ord(character) < 32 for character in self.endpoint)
            or not _bounded(self.connect_timeout_seconds, 1, 30)
            or not _bounded(self.read_timeout_seconds, 1, 60)
            or not _bounded(self.rate_limit_retry_seconds, 1, 3600)
            or not _bounded(self.page_size, 1, 100)
            or not _bounded(self.max_pages, 1, 100)
        ):
            raise ValueError("Xianyu provider settings are invalid")


@dataclass(frozen=True, slots=True)
class XianyuProviderSyncResponse:
    alerts: tuple[XianyuAlertFact, ...] = field(repr=False)
    next_cursor: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.alerts, tuple) or any(
            not isinstance(alert, XianyuAlertFact) for alert in self.alerts
        ):
            raise ValueError("Xianyu provider response is invalid")


class XianyuProviderError(RuntimeError):
    """A classified provider failure safe to persist without raw details."""

    def __init__(self, safe_code: str = "PROVIDER_UNAVAILABLE") -> None:
        if not isinstance(safe_code, str) or _SAFE_CODE.fullmatch(safe_code) is None:
            raise ValueError("safe provider code is invalid")
        self.safe_code = safe_code
        super().__init__("Xianyu provider request failed")


class XianyuProviderRateLimited(XianyuProviderError):
    def __init__(self, *, retry_after_at: datetime) -> None:
        if (
            not isinstance(retry_after_at, datetime)
            or retry_after_at.tzinfo is None
            or retry_after_at.utcoffset() is None
        ):
            raise ValueError("rate limit retry time is invalid")
        self.retry_after_at = retry_after_at.astimezone(timezone.utc)
        super().__init__("PROVIDER_RATE_LIMITED")


class XianyuProviderAdapter(Protocol):
    def fetch_alerts(
        self,
        *,
        request: XianyuSyncProviderRequest,
        settings: XianyuProviderSettings,
    ) -> XianyuProviderSyncResponse: ...


class XianyuSyncProviderDispatcher:
    """Execute one already-authorized provider call and normalize its result."""

    @staticmethod
    def dispatch(
        *,
        request: XianyuSyncProviderRequest,
        adapter: XianyuProviderAdapter,
        settings: XianyuProviderSettings,
    ) -> XianyuConnectionSyncResult:
        if (
            not isinstance(request, XianyuSyncProviderRequest)
            or not isinstance(settings, XianyuProviderSettings)
            or not callable(getattr(adapter, "fetch_alerts", None))
        ):
            raise TypeError("Xianyu provider dispatch is invalid")
        context = request.context
        try:
            response = adapter.fetch_alerts(request=request, settings=settings)
            if not isinstance(response, XianyuProviderSyncResponse):
                raise ValueError("provider response type is invalid")
            return XianyuConnectionSyncResult(
                integration_uuid=context.integration_uuid,
                secret_revision_uuid=context.secret_revision_uuid,
                status="succeeded",
                alerts=response.alerts,
                provider_cursor=response.next_cursor,
            )
        except XianyuProviderRateLimited as exc:
            return XianyuConnectionSyncResult(
                integration_uuid=context.integration_uuid,
                secret_revision_uuid=context.secret_revision_uuid,
                status="rate_limited",
                safe_error_code=exc.safe_code,
                retry_after_at=exc.retry_after_at,
            )
        except XianyuProviderError as exc:
            return XianyuConnectionSyncResult(
                integration_uuid=context.integration_uuid,
                secret_revision_uuid=context.secret_revision_uuid,
                status="failed",
                safe_error_code=exc.safe_code,
            )
        except (ValueError, XianyuSyncInputError):
            return XianyuConnectionSyncResult(
                integration_uuid=context.integration_uuid,
                secret_revision_uuid=context.secret_revision_uuid,
                status="failed",
                safe_error_code="PROVIDER_RESPONSE_INVALID",
            )
        except Exception:
            return XianyuConnectionSyncResult(
                integration_uuid=context.integration_uuid,
                secret_revision_uuid=context.secret_revision_uuid,
                status="failed",
                safe_error_code="PROVIDER_UNAVAILABLE",
            )
        finally:
            request.discard_credentials()


def _bounded(value: object, minimum: int, maximum: int) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and minimum <= value <= maximum
    )


__all__ = [
    "XianyuProviderAdapter",
    "XianyuProviderError",
    "XianyuProviderRateLimited",
    "XianyuProviderSettings",
    "XianyuProviderSyncResponse",
    "XianyuSyncProviderDispatcher",
]
