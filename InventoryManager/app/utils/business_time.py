"""Business-clock helpers for China-local operational timestamps.

The legacy rental schema stores operational wall-clock values as naive
``DATETIME`` columns.  Keep those values explicitly tied to Asia/Shanghai so
workers behave consistently even when containers run in UTC.
"""

from datetime import datetime
from zoneinfo import ZoneInfo


BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")


def as_business_naive(value: datetime) -> datetime:
    """Return an Asia/Shanghai wall-clock datetime without tzinfo."""
    if value.tzinfo is not None:
        value = value.astimezone(BUSINESS_TIMEZONE)
    return value.replace(tzinfo=None)


def parse_business_datetime(value: str) -> datetime:
    """Parse ISO input, treating offset-free values as China-local time."""
    return as_business_naive(
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    )


def business_now_naive() -> datetime:
    """Return the current China-local wall-clock time for legacy columns."""
    return datetime.now(BUSINESS_TIMEZONE).replace(tzinfo=None)
