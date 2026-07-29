from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.services.rental_statistics_service import (
    calculate_period_depreciation,
    is_order_within_service,
    lifecycle_end_date,
    service_overlap_days,
)


@pytest.mark.parametrize(
    ("lifecycle_status", "lifecycle_date", "expected"),
    [
        ("active", datetime(2026, 7, 15, 12, 30), None),
        ("sold", datetime(2026, 7, 15, 12, 30), date(2026, 7, 15)),
        ("decommissioned", datetime(2026, 7, 15), date(2026, 7, 15)),
        ("damaged", None, None),
        ("retired", datetime(2026, 7, 20), date(2026, 7, 20)),
    ],
)
def test_lifecycle_end_date_uses_only_dated_inactive_statuses(
    lifecycle_status, lifecycle_date, expected
):
    device = SimpleNamespace(
        id=7,
        lifecycle_status=lifecycle_status,
        lifecycle_date=lifecycle_date,
    )

    assert lifecycle_end_date(device) == expected


@pytest.mark.parametrize(
    ("first_order", "service_end", "period_start", "period_end", "expected"),
    [
        (date(2026, 7, 1), None, date(2026, 7, 1), date(2026, 7, 31), 31),
        (date(2026, 7, 1), date(2026, 7, 15), date(2026, 7, 1), date(2026, 7, 31), 14),
        (date(2026, 7, 10), None, date(2026, 7, 1), date(2026, 7, 31), 22),
        (date(2026, 8, 1), None, date(2026, 7, 1), date(2026, 7, 31), 0),
        (date(2026, 7, 1), date(2026, 7, 1), date(2026, 7, 1), date(2026, 7, 31), 0),
    ],
)
def test_service_overlap_days_uses_half_open_service_window(
    first_order, service_end, period_start, period_end, expected
):
    assert (
        service_overlap_days(first_order, service_end, period_start, period_end)
        == expected
    )


def test_order_on_lifecycle_date_is_outside_service():
    first_order = date(2026, 7, 1)
    service_end = date(2026, 7, 15)

    assert is_order_within_service(date(2026, 7, 14), first_order, service_end)
    assert not is_order_within_service(date(2026, 7, 15), first_order, service_end)


def test_depreciation_stops_at_lifecycle_date():
    actual = calculate_period_depreciation(
        purchase_price=7000.0,
        purchase_date=date(2026, 7, 1),
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        service_end=date(2026, 7, 15),
    )
    expected = 7000.0 * (1 - 0.5 ** (14 / 7 / 52))

    assert actual == pytest.approx(expected)
