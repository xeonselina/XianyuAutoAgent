from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from inventory_control.subscriptions import (
    CORE_MEMBER_SEAT_CAP,
    InvalidSeatCountError,
    InvalidServicePeriodInputError,
    SeatLimitExceededError,
    SeatUsage,
    ServicePeriodAction,
    ServicePeriodAdjustment,
    ServicePeriodAlreadyExpiredError,
    ServicePeriodReductionRejectedError,
    calculate_renewal,
    calculate_service_period_adjustment,
    has_seat_capacity,
    require_seat_capacity,
)


DATABASE_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def test_core_seat_usage_counts_only_the_two_approved_sources():
    usage = SeatUsage(
        active_memberships=7,
        unexpired_pending_invitations=2,
    )

    assert CORE_MEMBER_SEAT_CAP == 10
    assert usage.occupied_seats == 9
    assert usage.remaining_seats == 1
    assert usage.is_within_cap
    assert has_seat_capacity(usage)


def test_tenth_seat_is_allowed_but_eleventh_is_rejected():
    nine_occupied = SeatUsage(9, 0)
    ten_occupied = SeatUsage(9, 1)

    require_seat_capacity(nine_occupied)
    assert has_seat_capacity(ten_occupied) is False
    with pytest.raises(SeatLimitExceededError):
        require_seat_capacity(ten_occupied)


def test_pending_invitation_to_membership_conversion_does_not_add_a_seat():
    full_usage = SeatUsage(9, 1)

    assert has_seat_capacity(full_usage, additional_seats=0)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("active_memberships", -1),
        ("active_memberships", True),
        ("active_memberships", 1.0),
        ("unexpired_pending_invitations", -1),
        ("unexpired_pending_invitations", "1"),
    ],
)
def test_seat_counts_must_be_non_negative_integers(field_name, value):
    values = {
        "active_memberships": 1,
        "unexpired_pending_invitations": 1,
    }
    values[field_name] = value

    with pytest.raises(InvalidSeatCountError):
        SeatUsage(**values)


def test_seat_usage_is_immutable():
    usage = SeatUsage(1, 2)

    with pytest.raises(FrozenInstanceError):
        usage.active_memberships = 2


def test_active_renewal_extends_from_current_expiry():
    current_expiry = DATABASE_NOW + timedelta(days=5)

    calculation = calculate_renewal(
        current_expires_at=current_expiry,
        database_now=DATABASE_NOW,
        service_duration=timedelta(days=30, hours=6),
    )

    assert calculation.calculation_base == current_expiry
    assert calculation.new_expires_at == current_expiry + timedelta(
        days=30, hours=6
    )


@pytest.mark.parametrize(
    "current_expiry",
    [
        DATABASE_NOW - timedelta(microseconds=1),
        DATABASE_NOW,
    ],
)
def test_expired_or_boundary_renewal_extends_from_database_time(current_expiry):
    calculation = calculate_renewal(
        current_expires_at=current_expiry,
        database_now=DATABASE_NOW,
        service_duration=timedelta(days=30),
    )

    assert calculation.calculation_base == DATABASE_NOW
    assert calculation.new_expires_at == DATABASE_NOW + timedelta(days=30)


@pytest.mark.parametrize(
    "service_duration",
    [
        timedelta(0),
        timedelta(microseconds=-1),
        30,
        "30 days",
        None,
    ],
)
def test_renewal_requires_an_exact_positive_timedelta(service_duration):
    with pytest.raises(InvalidServicePeriodInputError):
        calculate_renewal(
            current_expires_at=DATABASE_NOW,
            database_now=DATABASE_NOW,
            service_duration=service_duration,
        )


def test_renewal_result_is_immutable():
    calculation = calculate_renewal(
        current_expires_at=DATABASE_NOW,
        database_now=DATABASE_NOW,
        service_duration=timedelta(microseconds=1),
    )

    with pytest.raises(FrozenInstanceError):
        calculation.new_expires_at = DATABASE_NOW


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"add_days": 1, "subtract_days": 1},
        {"add_days": 1, "expire_now": True},
        {"subtract_days": 1, "expire_now": True},
        {"add_days": 1, "subtract_days": 1, "expire_now": True},
    ],
)
def test_adjustment_actions_are_strictly_mutually_exclusive(kwargs):
    with pytest.raises(InvalidServicePeriodInputError):
        ServicePeriodAdjustment(**kwargs)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("add_days", 0),
        ("add_days", -1),
        ("add_days", True),
        ("add_days", 1.0),
        ("add_days", "1"),
        ("subtract_days", 0),
        ("subtract_days", -1),
        ("subtract_days", False),
        ("subtract_days", "1"),
    ],
)
def test_add_and_subtract_accept_only_positive_integer_days(field_name, value):
    with pytest.raises(InvalidServicePeriodInputError):
        ServicePeriodAdjustment(**{field_name: value})


def test_add_days_uses_later_of_expiry_and_database_time():
    active = calculate_service_period_adjustment(
        adjustment=ServicePeriodAdjustment(add_days=2),
        current_expires_at=DATABASE_NOW + timedelta(days=4),
        database_now=DATABASE_NOW,
    )
    expired = calculate_service_period_adjustment(
        adjustment=ServicePeriodAdjustment(add_days=2),
        current_expires_at=DATABASE_NOW - timedelta(days=4),
        database_now=DATABASE_NOW,
    )

    assert active.action is ServicePeriodAction.ADD_DAYS
    assert active.new_expires_at == DATABASE_NOW + timedelta(days=6)
    assert expired.new_expires_at == DATABASE_NOW + timedelta(days=2)


def test_subtract_days_succeeds_only_when_result_remains_in_future():
    calculation = calculate_service_period_adjustment(
        adjustment=ServicePeriodAdjustment(subtract_days=2),
        current_expires_at=DATABASE_NOW + timedelta(days=2, microseconds=1),
        database_now=DATABASE_NOW,
    )

    assert calculation.action is ServicePeriodAction.SUBTRACT_DAYS
    assert calculation.new_expires_at == DATABASE_NOW + timedelta(microseconds=1)


@pytest.mark.parametrize(
    "current_expiry",
    [
        DATABASE_NOW + timedelta(days=2),
        DATABASE_NOW + timedelta(days=2, microseconds=-1),
        DATABASE_NOW,
        DATABASE_NOW - timedelta(microseconds=1),
    ],
)
def test_subtract_days_crossing_database_now_is_rejected_without_clamping(
    current_expiry,
):
    with pytest.raises(ServicePeriodReductionRejectedError):
        calculate_service_period_adjustment(
            adjustment=ServicePeriodAdjustment(subtract_days=2),
            current_expires_at=current_expiry,
            database_now=DATABASE_NOW,
        )


def test_expire_now_sets_an_active_period_to_exact_database_time():
    calculation = calculate_service_period_adjustment(
        adjustment=ServicePeriodAdjustment(expire_now=True),
        current_expires_at=DATABASE_NOW + timedelta(microseconds=1),
        database_now=DATABASE_NOW,
    )

    assert calculation.action is ServicePeriodAction.EXPIRE_NOW
    assert calculation.new_expires_at == DATABASE_NOW


@pytest.mark.parametrize(
    "current_expiry",
    [DATABASE_NOW, DATABASE_NOW - timedelta(microseconds=1)],
)
def test_expire_now_rejects_an_already_expired_period(current_expiry):
    with pytest.raises(ServicePeriodAlreadyExpiredError):
        calculate_service_period_adjustment(
            adjustment=ServicePeriodAdjustment(expire_now=True),
            current_expires_at=current_expiry,
            database_now=DATABASE_NOW,
        )


@pytest.mark.parametrize(
    "calculator",
    [
        lambda current, now: calculate_renewal(
            current_expires_at=current,
            database_now=now,
            service_duration=timedelta(days=1),
        ),
        lambda current, now: calculate_service_period_adjustment(
            adjustment=ServicePeriodAdjustment(add_days=1),
            current_expires_at=current,
            database_now=now,
        ),
    ],
)
def test_datetime_inputs_must_use_the_same_timezone_form(calculator):
    naive_now = DATABASE_NOW.replace(tzinfo=None)

    with pytest.raises(InvalidServicePeriodInputError, match="timezone"):
        calculator(naive_now, DATABASE_NOW)
    with pytest.raises(InvalidServicePeriodInputError, match="timezone"):
        calculator(DATABASE_NOW, naive_now)


def test_matching_naive_datetime_inputs_remain_naive():
    naive_now = DATABASE_NOW.replace(tzinfo=None)

    calculation = calculate_service_period_adjustment(
        adjustment=ServicePeriodAdjustment(add_days=1),
        current_expires_at=naive_now,
        database_now=naive_now,
    )

    assert calculation.new_expires_at == naive_now + timedelta(days=1)
    assert calculation.new_expires_at.tzinfo is None


def test_service_period_calculation_is_immutable():
    calculation = calculate_service_period_adjustment(
        adjustment=ServicePeriodAdjustment(add_days=1),
        current_expires_at=DATABASE_NOW,
        database_now=DATABASE_NOW,
    )

    with pytest.raises(FrozenInstanceError):
        calculation.new_expires_at = DATABASE_NOW
