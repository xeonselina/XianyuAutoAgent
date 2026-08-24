"""Typed, provider-neutral facts accepted by the Xianyu tenant store."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Final
from uuid import UUID


_RESULT_STATUSES: Final = frozenset({"succeeded", "failed", "rate_limited"})


class XianyuSyncInputError(ValueError):
    """A worker attempted to persist a malformed or untrusted provider result."""


@dataclass(frozen=True, slots=True, repr=False)
class XianyuAlertFact:
    """Normalized order fact; repr is redacted because fields contain PII."""

    order_no: str
    pay_amount: int
    buyer_nick: str | None = None
    receiver_name: str | None = None
    receiver_mobile: str | None = None
    address: str | None = None
    goods_title: str | None = None
    goods_sku_text: str | None = None
    order_time: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "order_no", _text(self.order_no, 50, required=True))
        if (
            isinstance(self.pay_amount, bool)
            or not isinstance(self.pay_amount, int)
            or self.pay_amount < 0
        ):
            raise XianyuSyncInputError("pay_amount is invalid")
        for name, maximum in (
            ("buyer_nick", 100),
            ("receiver_name", 100),
            ("receiver_mobile", 20),
            ("address", 500),
            ("goods_title", 500),
            ("goods_sku_text", 500),
        ):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), maximum, required=False),
            )
        if self.order_time is not None and not isinstance(
            self.order_time, datetime
        ):
            raise XianyuSyncInputError("order_time is invalid")

    def __repr__(self) -> str:
        return "XianyuAlertFact(<redacted>)"


@dataclass(frozen=True, slots=True)
class XianyuConnectionRef:
    integration_uuid: str
    secret_revision_uuid: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "integration_uuid", _uuid(self.integration_uuid)
        )
        object.__setattr__(
            self, "secret_revision_uuid", _uuid(self.secret_revision_uuid)
        )


@dataclass(frozen=True, slots=True)
class XianyuConnectionSyncResult:
    integration_uuid: str
    secret_revision_uuid: str
    status: str
    alerts: tuple[XianyuAlertFact, ...] = field(default=(), repr=False)
    safe_error_code: str | None = None
    retry_after_at: datetime | None = None
    provider_cursor: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "integration_uuid", _uuid(self.integration_uuid)
        )
        object.__setattr__(
            self, "secret_revision_uuid", _uuid(self.secret_revision_uuid)
        )
        if self.status not in _RESULT_STATUSES:
            raise XianyuSyncInputError("status is invalid")
        if not isinstance(self.alerts, tuple) or any(
            not isinstance(alert, XianyuAlertFact) for alert in self.alerts
        ):
            raise XianyuSyncInputError("alerts are invalid")
        order_numbers = [alert.order_no for alert in self.alerts]
        if len(order_numbers) != len(set(order_numbers)):
            raise XianyuSyncInputError("alerts contain duplicate order numbers")
        if self.status != "succeeded" and self.alerts:
            raise XianyuSyncInputError("failed results cannot replace alerts")
        if self.status == "succeeded":
            if self.safe_error_code is not None or self.retry_after_at is not None:
                raise XianyuSyncInputError("successful result contains error facts")
            object.__setattr__(
                self,
                "provider_cursor",
                _text(self.provider_cursor, 512, required=False),
            )
        else:
            if self.provider_cursor is not None:
                raise XianyuSyncInputError("failed result cannot advance cursor")
            object.__setattr__(
                self,
                "safe_error_code",
                _text(self.safe_error_code, 64, required=True),
            )
            if self.status == "rate_limited":
                if not isinstance(self.retry_after_at, datetime):
                    raise XianyuSyncInputError(
                        "rate-limited result requires retry_after_at"
                    )
            elif self.retry_after_at is not None:
                raise XianyuSyncInputError(
                    "retry_after_at is only valid for rate limiting"
                )


def _uuid(value: object) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise XianyuSyncInputError("identifier is invalid") from None


def _text(value: object, maximum: int, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise XianyuSyncInputError("text value is invalid")
    normalized = value.strip()
    if (required and not normalized) or len(normalized) > maximum:
        raise XianyuSyncInputError("text value is invalid")
    if not normalized:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise XianyuSyncInputError("text value is invalid")
    return normalized
