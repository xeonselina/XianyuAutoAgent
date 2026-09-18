from datetime import datetime, timezone

from app.utils.business_time import as_business_naive, parse_business_datetime


def test_offset_free_business_time_remains_china_local_wall_time():
    assert parse_business_datetime("2026-09-02T10:30:00") == datetime(
        2026, 9, 2, 10, 30,
    )


def test_utc_business_time_converts_to_china_local_wall_time():
    assert parse_business_datetime("2026-09-02T02:30:00Z") == datetime(
        2026, 9, 2, 10, 30,
    )
    assert as_business_naive(
        datetime(2026, 9, 2, 2, 30, tzinfo=timezone.utc)
    ) == datetime(2026, 9, 2, 10, 30)
