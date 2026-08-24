"""D33 schedule overlap rules without ORM or request dependencies."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Final
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

USAGE_PERIOD_CONFLICT: Final = "USAGE_PERIOD_CONFLICT"
LOGISTICS_OVERLAP_RELAY_WARNING: Final = "LOGISTICS_OVERLAP_RELAY_WARNING"

ACTIVE_RENTAL_STATUSES: Final = frozenset(
    {"not_shipped", "scheduled_for_shipping", "shipped", "returned"}
)
TERMINAL_RENTAL_STATUSES: Final = frozenset({"completed", "cancelled"})
VALID_RENTAL_STATUSES: Final = ACTIVE_RENTAL_STATUSES | TERMINAL_RENTAL_STATUSES

Identifier = int | str | UUID
DateValue = date | datetime


class ScheduleValidationError(ValueError):
    """Stable validation failure raised before schedule analysis."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class RentalSchedule:
    """Minimal rental fact required by the overlap policy."""

    rental_id: Identifier | None
    device_id: Identifier
    start_date: DateValue
    end_date: DateValue
    logistics_days: int
    status: str
    planned_ship_out_date: DateValue | None = None
    planned_return_date: DateValue | None = None


@dataclass(frozen=True, slots=True)
class PlannedLogisticsWindow:
    planned_ship_out_date: date
    planned_return_date: date


@dataclass(frozen=True, slots=True)
class UsagePeriodConflict:
    device_id: Identifier
    predecessor_rental_id: Identifier | None
    successor_rental_id: Identifier | None
    code: str = field(default=USAGE_PERIOD_CONFLICT, init=False)
    blocking: bool = field(default=True, init=False)


@dataclass(frozen=True, slots=True)
class LogisticsOverlapWarning:
    device_id: Identifier
    predecessor_rental_id: Identifier | None
    successor_rental_id: Identifier | None
    overlap_days: int
    code: str = field(default=LOGISTICS_OVERLAP_RELAY_WARNING, init=False)
    blocking: bool = field(default=False, init=False)
    relay_candidate: bool = field(default=True, init=False)


@dataclass(frozen=True, slots=True)
class ScheduleEvaluation:
    hard_conflicts: tuple[UsagePeriodConflict, ...]
    warnings: tuple[LogisticsOverlapWarning, ...]

    @property
    def can_submit(self) -> bool:
        return not self.hard_conflicts

    @property
    def relay_candidates(self) -> tuple[LogisticsOverlapWarning, ...]:
        """Gantt and relay consumers intentionally share the same facts."""

        return self.warnings


@dataclass(frozen=True, slots=True)
class _NormalizedRental:
    rental_id: Identifier | None
    device_id: Identifier
    start_date: date
    end_date: date
    logistics_days: int
    planned_window: PlannedLogisticsWindow


class ScheduleOverlapPolicy:
    """Own the D17/D33 hard-conflict and logistics-warning calculations.

    Existing rows that match ``exclude_rental_id`` are removed before an optional
    replacement ``candidate`` is added. This lets edit validation exclude the
    persisted version while still evaluating the proposed version with the same ID.
    """

    def evaluate(
        self,
        rentals: Iterable[RentalSchedule],
        *,
        candidate: RentalSchedule | None = None,
        exclude_rental_id: Identifier | None = None,
        tenant_timezone: str = "Asia/Shanghai",
        require_planned_facts: bool = False,
    ) -> ScheduleEvaluation:
        zone = self._resolve_timezone(tenant_timezone)
        if not isinstance(require_planned_facts, bool):
            raise ScheduleValidationError(
                "INVALID_PLANNED_FACT_POLICY",
                "require_planned_facts must be a bool",
            )
        if exclude_rental_id is not None:
            self._validate_identifier(exclude_rental_id, "exclude_rental_id")

        included: list[tuple[RentalSchedule, bool]] = []
        for rental in rentals:
            self._validate_rental_type(rental)
            if (
                exclude_rental_id is not None
                and rental.rental_id == exclude_rental_id
            ):
                continue
            included.append((rental, False))

        if candidate is not None:
            self._validate_rental_type(candidate)
            included.append((candidate, True))

        by_device: dict[Identifier, list[_NormalizedRental]] = defaultdict(list)
        seen_ids: set[Hashable] = set()
        for rental, is_candidate in included:
            normalized = self._normalize(
                rental,
                zone=zone,
                allow_missing_id=is_candidate,
                require_planned_facts=require_planned_facts,
            )
            if normalized is None:
                continue
            if normalized.rental_id is not None:
                if normalized.rental_id in seen_ids:
                    raise ScheduleValidationError(
                        "DUPLICATE_RENTAL_ID",
                        f"duplicate rental_id: {normalized.rental_id!r}",
                    )
                seen_ids.add(normalized.rental_id)
            by_device[normalized.device_id].append(normalized)

        hard_conflicts: list[UsagePeriodConflict] = []
        warnings: list[LogisticsOverlapWarning] = []
        for device_id in sorted(by_device, key=self._identifier_sort_key):
            ordered = sorted(by_device[device_id], key=self._rental_sort_key)
            device_conflicts = self._usage_conflicts(ordered)
            hard_conflicts.extend(device_conflicts)
            if device_conflicts:
                continue
            warnings.extend(self._logistics_warnings(ordered))

        return ScheduleEvaluation(
            hard_conflicts=tuple(hard_conflicts),
            warnings=tuple(warnings),
        )

    def calculate_planned_window(
        self,
        *,
        start_date: DateValue,
        end_date: DateValue,
        logistics_days: int,
        tenant_timezone: str = "Asia/Shanghai",
    ) -> PlannedLogisticsWindow:
        zone = self._resolve_timezone(tenant_timezone)
        normalized_start = self._normalize_date(start_date, "start_date", zone)
        normalized_end = self._normalize_date(end_date, "end_date", zone)
        self._validate_period(normalized_start, normalized_end)
        self._validate_logistics_days(logistics_days)
        return self._calculate_planned_window_normalized(
            start_date=normalized_start,
            end_date=normalized_end,
            logistics_days=logistics_days,
        )

    def _normalize(
        self,
        rental: RentalSchedule,
        *,
        zone: ZoneInfo,
        allow_missing_id: bool,
        require_planned_facts: bool,
    ) -> _NormalizedRental | None:
        if rental.rental_id is None:
            if not allow_missing_id:
                raise ScheduleValidationError(
                    "INVALID_RENTAL_ID", "rental_id is required for persisted rows"
                )
        else:
            self._validate_identifier(rental.rental_id, "rental_id")
        self._validate_identifier(rental.device_id, "device_id")
        self._validate_status(rental.status)

        # Terminal history is outside future availability and may predate planned
        # logistics fields, so it is intentionally ignored before date validation.
        if rental.status in TERMINAL_RENTAL_STATUSES:
            return None

        start = self._normalize_date(rental.start_date, "start_date", zone)
        end = self._normalize_date(rental.end_date, "end_date", zone)
        self._validate_period(start, end)
        self._validate_logistics_days(rental.logistics_days)
        calculated_window = self._calculate_planned_window_normalized(
            start_date=start,
            end_date=end,
            logistics_days=rental.logistics_days,
        )
        supplied_planned_facts = (
            rental.planned_ship_out_date is not None,
            rental.planned_return_date is not None,
        )
        if supplied_planned_facts == (False, False):
            if require_planned_facts:
                raise ScheduleValidationError(
                    "MISSING_PLANNED_LOGISTICS",
                    "persisted schedule rows require both planned logistics dates",
                )
            planned_window = calculated_window
        elif supplied_planned_facts != (True, True):
            raise ScheduleValidationError(
                "INCOMPLETE_PLANNED_LOGISTICS",
                "planned logistics dates must be supplied together",
            )
        else:
            planned_window = PlannedLogisticsWindow(
                planned_ship_out_date=self._normalize_date(
                    rental.planned_ship_out_date,
                    "planned_ship_out_date",
                    zone,
                ),
                planned_return_date=self._normalize_date(
                    rental.planned_return_date,
                    "planned_return_date",
                    zone,
                ),
            )
            if planned_window != calculated_window:
                raise ScheduleValidationError(
                    "PLANNED_LOGISTICS_MISMATCH",
                    "planned logistics dates do not match usage dates and logistics_days",
                )
        return _NormalizedRental(
            rental_id=rental.rental_id,
            device_id=rental.device_id,
            start_date=start,
            end_date=end,
            logistics_days=rental.logistics_days,
            planned_window=planned_window,
        )

    @staticmethod
    def _calculate_planned_window_normalized(
        *, start_date: date, end_date: date, logistics_days: int
    ) -> PlannedLogisticsWindow:
        buffer = timedelta(days=logistics_days + 1)
        return PlannedLogisticsWindow(
            planned_ship_out_date=start_date - buffer,
            planned_return_date=end_date + buffer,
        )

    @staticmethod
    def _usage_conflicts(
        ordered: list[_NormalizedRental],
    ) -> list[UsagePeriodConflict]:
        conflicts: list[UsagePeriodConflict] = []
        for index, predecessor in enumerate(ordered):
            for successor in ordered[index + 1 :]:
                if successor.start_date > predecessor.end_date:
                    break
                conflicts.append(
                    UsagePeriodConflict(
                        device_id=predecessor.device_id,
                        predecessor_rental_id=predecessor.rental_id,
                        successor_rental_id=successor.rental_id,
                    )
                )
        return conflicts

    @staticmethod
    def _logistics_warnings(
        ordered: list[_NormalizedRental],
    ) -> list[LogisticsOverlapWarning]:
        warnings: list[LogisticsOverlapWarning] = []
        for predecessor, successor in zip(ordered, ordered[1:]):
            overlap_days = (
                predecessor.planned_window.planned_return_date
                - successor.planned_window.planned_ship_out_date
            ).days
            if overlap_days <= 1:
                continue
            warnings.append(
                LogisticsOverlapWarning(
                    device_id=predecessor.device_id,
                    predecessor_rental_id=predecessor.rental_id,
                    successor_rental_id=successor.rental_id,
                    overlap_days=overlap_days,
                )
            )
        return warnings

    @staticmethod
    def _resolve_timezone(tenant_timezone: str) -> ZoneInfo:
        if not isinstance(tenant_timezone, str) or not tenant_timezone.strip():
            raise ScheduleValidationError(
                "INVALID_TENANT_TIMEZONE",
                "tenant_timezone must be a non-empty IANA timezone name",
            )
        try:
            return ZoneInfo(tenant_timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ScheduleValidationError(
                "INVALID_TENANT_TIMEZONE",
                f"unknown tenant timezone: {tenant_timezone!r}",
            ) from exc

    @staticmethod
    def _normalize_date(value: DateValue, field_name: str, zone: ZoneInfo) -> date:
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ScheduleValidationError(
                    "NAIVE_DATETIME",
                    f"{field_name} datetime must include an offset",
                )
            try:
                return value.astimezone(zone).date()
            except (OverflowError, ValueError) as exc:
                raise ScheduleValidationError(
                    "INVALID_DATE", f"{field_name} is outside the supported range"
                ) from exc
        if isinstance(value, date):
            return value
        raise ScheduleValidationError(
            "INVALID_DATE",
            f"{field_name} must be a date or timezone-aware datetime",
        )

    @staticmethod
    def _validate_period(start: date, end: date) -> None:
        if start > end:
            raise ScheduleValidationError(
                "INVALID_USAGE_PERIOD", "start_date must be on or before end_date"
            )

    @staticmethod
    def _validate_logistics_days(logistics_days: int) -> None:
        if (
            not isinstance(logistics_days, int)
            or isinstance(logistics_days, bool)
            or not 0 <= logistics_days <= 7
        ):
            raise ScheduleValidationError(
                "INVALID_LOGISTICS_DAYS",
                "logistics_days must be an integer from zero through seven",
            )

    @staticmethod
    def _validate_status(status: str) -> None:
        if not isinstance(status, str) or status not in VALID_RENTAL_STATUSES:
            raise ScheduleValidationError(
                "INVALID_RENTAL_STATUS", f"unsupported rental status: {status!r}"
            )

    @staticmethod
    def _validate_rental_type(rental: RentalSchedule) -> None:
        if not isinstance(rental, RentalSchedule):
            raise ScheduleValidationError(
                "INVALID_RENTAL", "schedule rows must be RentalSchedule instances"
            )

    @staticmethod
    def _validate_identifier(value: object, field_name: str) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, str, UUID))
            or (isinstance(value, str) and not value.strip())
        ):
            raise ScheduleValidationError(
                "INVALID_IDENTIFIER",
                f"{field_name} must be a non-empty integer, string, or UUID",
            )

    @classmethod
    def _rental_sort_key(
        cls, rental: _NormalizedRental
    ) -> tuple[date, tuple[int, object]]:
        return rental.start_date, cls._identifier_sort_key(rental.rental_id)

    @staticmethod
    def _identifier_sort_key(value: Identifier | None) -> tuple[int, object]:
        if isinstance(value, int) and not isinstance(value, bool):
            return 0, value
        if isinstance(value, UUID):
            return 1, value.hex
        if isinstance(value, str):
            return 2, value
        # A create candidate may not have a database ID yet. It sorts after
        # persisted rows; equal-start rows are hard conflicts in any case.
        return 3, ""
