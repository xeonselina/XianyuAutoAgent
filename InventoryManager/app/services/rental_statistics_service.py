"""Pure calculations shared by rental statistics endpoints."""

from datetime import date, timedelta
import math
from typing import Optional


INACTIVE_LIFECYCLE_STATUSES = frozenset(
    {"sold", "decommissioned", "damaged", "retired"}
)


def lifecycle_end_date(device) -> Optional[date]:
    """Return the exclusive service end date for a device, when known."""
    if device.lifecycle_status not in INACTIVE_LIFECYCLE_STATUSES:
        return None
    if device.lifecycle_date is None:
        return None
    return device.lifecycle_date.date()


def service_overlap_days(
    first_order: date,
    service_end: Optional[date],
    period_start: date,
    period_end: date,
) -> int:
    """Count calendar days in the service/period intersection."""
    overlap_start = max(first_order, period_start)
    overlap_end = period_end + timedelta(days=1)
    if service_end is not None:
        overlap_end = min(overlap_end, service_end)
    return max(0, (overlap_end - overlap_start).days)


def is_order_within_service(
    start_date: date,
    first_order: date,
    service_end: Optional[date],
) -> bool:
    """Return whether an order starts inside a device's service window."""
    return start_date >= first_order and (
        service_end is None or start_date < service_end
    )


def calculate_period_depreciation(
    purchase_price: float,
    purchase_date: date,
    period_start: date,
    period_end: date,
    service_end: Optional[date] = None,
) -> float:
    """Calculate half-life depreciation over a clipped calendar interval."""
    active_start = max(purchase_date, period_start)
    active_end = period_end + timedelta(days=1)
    if service_end is not None:
        active_end = min(active_end, service_end)
    if active_end <= active_start:
        return 0.0

    weeks_start = (active_start - purchase_date).days / 7.0
    weeks_end = (active_end - purchase_date).days / 7.0
    residual_start = purchase_price * math.pow(0.5, weeks_start / 52.0)
    residual_end = purchase_price * math.pow(0.5, weeks_end / 52.0)
    return residual_start - residual_end
