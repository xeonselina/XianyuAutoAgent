"""Pure expiry calculations for renewal and platform adjustments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from .errors import (
    InvalidServicePeriodInputError,
    ServicePeriodAlreadyExpiredError,
    ServicePeriodReductionRejectedError,
)


class ServicePeriodAction(str, Enum):
    ADD_DAYS = "add_days"
    SUBTRACT_DAYS = "subtract_days"
    EXPIRE_NOW = "expire_now"


def _require_datetime(field_name: str, value: object) -> None:
    if not isinstance(value, datetime):
        raise InvalidServicePeriodInputError(
            f"{field_name} must be a datetime"
        )


def _require_same_timezone_form(
    current_expires_at: datetime,
    database_now: datetime,
) -> None:
    if current_expires_at.tzinfo != database_now.tzinfo:
        raise InvalidServicePeriodInputError(
            "subscription and database times must use one timezone form"
        )


def _validate_times(
    current_expires_at: object,
    database_now: object,
) -> None:
    _require_datetime("current_expires_at", current_expires_at)
    _require_datetime("database_now", database_now)
    _require_same_timezone_form(current_expires_at, database_now)


def _require_positive_days(field_name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidServicePeriodInputError(
            f"{field_name} must be a positive integer"
        )


def _duration_for_days(days: int) -> timedelta:
    try:
        return timedelta(days=days)
    except OverflowError:
        raise InvalidServicePeriodInputError(
            "service-period days are outside the supported datetime range"
        ) from None


def _apply_duration(base: datetime, duration: timedelta, *, subtract: bool) -> datetime:
    try:
        return base - duration if subtract else base + duration
    except OverflowError:
        raise InvalidServicePeriodInputError(
            "service-period result is outside the supported datetime range"
        ) from None


@dataclass(frozen=True, slots=True)
class RenewalCalculation:
    current_expires_at: datetime
    database_now: datetime
    service_duration: timedelta
    calculation_base: datetime
    new_expires_at: datetime


def calculate_renewal(
    *,
    current_expires_at: datetime,
    database_now: datetime,
    service_duration: timedelta,
) -> RenewalCalculation:
    """Calculate ``max(current expiry, database now) + exact duration``."""

    _validate_times(current_expires_at, database_now)
    if not isinstance(service_duration, timedelta) or service_duration <= timedelta(0):
        raise InvalidServicePeriodInputError(
            "service_duration must be a positive timedelta"
        )

    calculation_base = max(current_expires_at, database_now)
    new_expires_at = _apply_duration(
        calculation_base, service_duration, subtract=False
    )
    return RenewalCalculation(
        current_expires_at=current_expires_at,
        database_now=database_now,
        service_duration=service_duration,
        calculation_base=calculation_base,
        new_expires_at=new_expires_at,
    )


@dataclass(frozen=True, slots=True)
class ServicePeriodAdjustment:
    """Exactly one D53 adjustment input."""

    add_days: Optional[int] = None
    subtract_days: Optional[int] = None
    expire_now: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.expire_now, bool):
            raise InvalidServicePeriodInputError("expire_now must be a boolean")

        selected_actions = sum(
            (
                self.add_days is not None,
                self.subtract_days is not None,
                self.expire_now,
            )
        )
        if selected_actions != 1:
            raise InvalidServicePeriodInputError(
                "exactly one service-period action is required"
            )

        if self.add_days is not None:
            _require_positive_days("add_days", self.add_days)
        if self.subtract_days is not None:
            _require_positive_days("subtract_days", self.subtract_days)

    @property
    def action(self) -> ServicePeriodAction:
        if self.add_days is not None:
            return ServicePeriodAction.ADD_DAYS
        if self.subtract_days is not None:
            return ServicePeriodAction.SUBTRACT_DAYS
        return ServicePeriodAction.EXPIRE_NOW


@dataclass(frozen=True, slots=True)
class ServicePeriodCalculation:
    action: ServicePeriodAction
    current_expires_at: datetime
    database_now: datetime
    new_expires_at: datetime


def service_period_effective_status(
    expires_at: datetime,
    database_now: datetime,
) -> str:
    """Return the shared active/expired projection at database time."""

    _validate_times(expires_at, database_now)
    return "active" if expires_at > database_now else "expired"


def service_period_calculation_base(
    *,
    adjustment: ServicePeriodAdjustment,
    current_expires_at: datetime,
    database_now: datetime,
) -> datetime:
    """Return the human-visible base used by a D53 preview and ledger."""

    if not isinstance(adjustment, ServicePeriodAdjustment):
        raise TypeError("adjustment must be a ServicePeriodAdjustment")
    _validate_times(current_expires_at, database_now)
    if adjustment.action is ServicePeriodAction.ADD_DAYS:
        return max(current_expires_at, database_now)
    if adjustment.action is ServicePeriodAction.SUBTRACT_DAYS:
        return current_expires_at
    return database_now


def calculate_service_period_adjustment(
    *,
    adjustment: ServicePeriodAdjustment,
    current_expires_at: datetime,
    database_now: datetime,
) -> ServicePeriodCalculation:
    """Recalculate one D53 action from authoritative database time."""

    if not isinstance(adjustment, ServicePeriodAdjustment):
        raise TypeError("adjustment must be a ServicePeriodAdjustment")
    _validate_times(current_expires_at, database_now)

    if adjustment.action is ServicePeriodAction.ADD_DAYS:
        duration = _duration_for_days(adjustment.add_days)
        base = max(current_expires_at, database_now)
        new_expires_at = _apply_duration(base, duration, subtract=False)
    elif adjustment.action is ServicePeriodAction.SUBTRACT_DAYS:
        duration = _duration_for_days(adjustment.subtract_days)
        new_expires_at = _apply_duration(
            current_expires_at, duration, subtract=True
        )
        if current_expires_at <= database_now or new_expires_at <= database_now:
            raise ServicePeriodReductionRejectedError(
                "service-period reduction requires an explicit expire-now action"
            )
    else:
        if current_expires_at <= database_now:
            raise ServicePeriodAlreadyExpiredError(
                "service period is already expired"
            )
        new_expires_at = database_now

    return ServicePeriodCalculation(
        action=adjustment.action,
        current_expires_at=current_expires_at,
        database_now=database_now,
        new_expires_at=new_expires_at,
    )
