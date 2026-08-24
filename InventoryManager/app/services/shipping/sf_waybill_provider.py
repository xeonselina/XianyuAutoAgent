"""Typed SF create-waybill provider boundary.

Only an injected adapter may perform network I/O.  The dispatcher converts
every adapter return or exception into a closed result that the tenant
execution ledger can persist without raw response text or credentials.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from inventory_control.integrations import (
    SfCreateWaybillRequest,
    SfWaybillQueryRequest,
)

from app.services.shipping_execution_service import (
    ProviderOutcome,
    UnknownResolution,
)


_SAFE_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]{0,63}$")
_RESULT_DIGEST = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class SfWaybillProviderSettings:
    test_mode: bool
    connect_timeout_seconds: int
    read_timeout_seconds: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.test_mode, bool)
            or not _bounded(self.connect_timeout_seconds, 1, 30)
            or not _bounded(self.read_timeout_seconds, 1, 60)
        ):
            raise ValueError("SF waybill provider settings are invalid")


@dataclass(frozen=True, slots=True)
class SfWaybillProviderResult:
    outcome: ProviderOutcome
    waybill_no: str | None = None
    safe_provider_code: str | None = None
    response_hash: str | None = None
    latency_ms: int | None = None

    def __post_init__(self) -> None:
        try:
            outcome = ProviderOutcome(self.outcome)
        except (TypeError, ValueError):
            raise ValueError("SF waybill provider result is invalid") from None
        object.__setattr__(self, "outcome", outcome)
        valid_waybill = (
            isinstance(self.waybill_no, str)
            and self.waybill_no == self.waybill_no.strip()
            and 1 <= len(self.waybill_no) <= 64
            and not any(ord(character) < 0x20 for character in self.waybill_no)
        )
        valid_code = (
            isinstance(self.safe_provider_code, str)
            and _SAFE_CODE.fullmatch(self.safe_provider_code) is not None
        )
        valid_hash = (
            isinstance(self.response_hash, str)
            and _RESULT_DIGEST.fullmatch(self.response_hash) is not None
        )
        valid_latency = (
            self.latency_ms is None
            or (
                isinstance(self.latency_ms, int)
                and not isinstance(self.latency_ms, bool)
                and 0 <= self.latency_ms <= 3_600_000
            )
        )
        if not valid_latency:
            raise ValueError("SF waybill provider result is invalid")
        if outcome is ProviderOutcome.SUCCESS:
            valid = valid_waybill and self.safe_provider_code is None and valid_hash
        elif outcome is ProviderOutcome.DEFINITIVE_FAILURE:
            valid = (
                self.waybill_no is None
                and valid_code
                and (self.response_hash is None or valid_hash)
            )
        else:
            valid = (
                self.waybill_no is None
                and valid_code
                and (self.response_hash is None or valid_hash)
            )
        if not valid:
            raise ValueError("SF waybill provider result is invalid")


@dataclass(frozen=True, slots=True)
class SfWaybillQueryResult:
    resolution: UnknownResolution
    safe_provider_code: str
    waybill_no: str | None = None
    response_hash: str | None = None
    latency_ms: int | None = None

    def __post_init__(self) -> None:
        try:
            resolution = UnknownResolution(self.resolution)
        except (TypeError, ValueError):
            raise ValueError("SF waybill query result is invalid") from None
        object.__setattr__(self, "resolution", resolution)
        valid_waybill = (
            isinstance(self.waybill_no, str)
            and self.waybill_no == self.waybill_no.strip()
            and 1 <= len(self.waybill_no) <= 64
            and not any(ord(character) < 0x20 for character in self.waybill_no)
        )
        valid_code = (
            isinstance(self.safe_provider_code, str)
            and _SAFE_CODE.fullmatch(self.safe_provider_code) is not None
        )
        valid_hash = (
            isinstance(self.response_hash, str)
            and _RESULT_DIGEST.fullmatch(self.response_hash) is not None
        )
        valid_latency = (
            self.latency_ms is None
            or (
                isinstance(self.latency_ms, int)
                and not isinstance(self.latency_ms, bool)
                and 0 <= self.latency_ms <= 3_600_000
            )
        )
        if resolution is UnknownResolution.CONFIRMED_SUCCESS:
            valid = valid_waybill and valid_hash
        else:
            valid = self.waybill_no is None and (
                self.response_hash is None or valid_hash
            )
        if not (valid and valid_code and valid_latency):
            raise ValueError("SF waybill query result is invalid")


class SfWaybillProviderAdapter:
    def create_waybill(
        self,
        *,
        request: SfCreateWaybillRequest,
        settings: SfWaybillProviderSettings,
    ) -> SfWaybillProviderResult:
        raise NotImplementedError

    def query_waybill(
        self,
        *,
        request: SfWaybillQueryRequest,
        settings: SfWaybillProviderSettings,
    ) -> SfWaybillQueryResult:
        raise NotImplementedError


class SfWaybillProviderDispatcher:
    """Dispatch exactly once and classify every unexpected result as unknown."""

    def __init__(
        self,
        *,
        adapter: SfWaybillProviderAdapter,
        settings: SfWaybillProviderSettings,
    ) -> None:
        if not callable(getattr(adapter, "create_waybill", None)):
            raise TypeError("SF waybill provider adapter is invalid")
        if not isinstance(settings, SfWaybillProviderSettings):
            raise TypeError("SF waybill provider settings are invalid")
        self._adapter = adapter
        self._settings = settings

    def dispatch(
        self,
        request: SfCreateWaybillRequest,
    ) -> SfWaybillProviderResult:
        if not isinstance(request, SfCreateWaybillRequest):
            raise TypeError("SF create-waybill request is invalid")
        try:
            result = self._adapter.create_waybill(
                request=request,
                settings=self._settings,
            )
            if not isinstance(result, SfWaybillProviderResult):
                raise ValueError
            return result
        except Exception:
            return SfWaybillProviderResult(
                outcome=ProviderOutcome.UNKNOWN,
                safe_provider_code="SF_PROVIDER_RESULT_UNKNOWN",
            )
        finally:
            request.discard_credentials()

    def __repr__(self) -> str:
        return "SfWaybillProviderDispatcher(adapter='<bound>')"


class SfWaybillQueryDispatcher:
    """Query one frozen provider order and collapse failures to unknown."""

    def __init__(
        self,
        *,
        adapter: SfWaybillProviderAdapter,
        settings: SfWaybillProviderSettings,
    ) -> None:
        if not callable(getattr(adapter, "query_waybill", None)):
            raise TypeError("SF waybill query adapter is invalid")
        if not isinstance(settings, SfWaybillProviderSettings):
            raise TypeError("SF waybill provider settings are invalid")
        self._adapter = adapter
        self._settings = settings

    def dispatch(
        self,
        request: SfWaybillQueryRequest,
    ) -> SfWaybillQueryResult:
        if not isinstance(request, SfWaybillQueryRequest):
            raise TypeError("SF waybill query request is invalid")
        try:
            result = self._adapter.query_waybill(
                request=request,
                settings=self._settings,
            )
            if not isinstance(result, SfWaybillQueryResult):
                raise ValueError
            return result
        except Exception:
            return SfWaybillQueryResult(
                resolution=UnknownResolution.STILL_UNKNOWN,
                safe_provider_code="SF_QUERY_RESULT_UNKNOWN",
            )
        finally:
            request.discard_credentials()

    def __repr__(self) -> str:
        return "SfWaybillQueryDispatcher(adapter='<bound>')"


def _bounded(value: object, minimum: int, maximum: int) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and minimum <= value <= maximum
    )


__all__ = [
    "SfWaybillProviderAdapter",
    "SfWaybillProviderDispatcher",
    "SfWaybillProviderResult",
    "SfWaybillProviderSettings",
    "SfWaybillQueryDispatcher",
    "SfWaybillQueryResult",
]
