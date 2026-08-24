from datetime import date, datetime, timezone

import pytest

from app.services.scheduling.overlap_policy import (
    LOGISTICS_OVERLAP_RELAY_WARNING,
    USAGE_PERIOD_CONFLICT,
    RentalSchedule,
    ScheduleOverlapPolicy,
    ScheduleValidationError,
)


def rental(
    rental_id,
    start_date,
    end_date=None,
    *,
    device_id=1,
    logistics_days=0,
    status="not_shipped",
):
    return RentalSchedule(
        rental_id=rental_id,
        device_id=device_id,
        start_date=start_date,
        end_date=end_date if end_date is not None else start_date,
        logistics_days=logistics_days,
        status=status,
    )


def test_zero_day_logistics_preserves_one_day_operational_buffers():
    window = ScheduleOverlapPolicy().calculate_planned_window(
        start_date=date(2026, 1, 10),
        end_date=date(2026, 1, 12),
        logistics_days=0,
    )

    assert window.planned_ship_out_date == date(2026, 1, 9)
    assert window.planned_return_date == date(2026, 1, 13)


def test_persisted_projection_requires_complete_matching_planned_facts():
    policy = ScheduleOverlapPolicy()
    missing = rental(10, date(2026, 1, 1))
    with pytest.raises(ScheduleValidationError) as raised:
        policy.evaluate([missing], require_planned_facts=True)
    assert raised.value.code == "MISSING_PLANNED_LOGISTICS"

    incomplete = RentalSchedule(
        rental_id=10,
        device_id=1,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
        logistics_days=0,
        status="not_shipped",
        planned_ship_out_date=date(2025, 12, 31),
    )
    with pytest.raises(ScheduleValidationError) as raised:
        policy.evaluate([incomplete], require_planned_facts=True)
    assert raised.value.code == "INCOMPLETE_PLANNED_LOGISTICS"

    drifted = RentalSchedule(
        rental_id=10,
        device_id=1,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
        logistics_days=0,
        status="not_shipped",
        planned_ship_out_date=date(2025, 12, 30),
        planned_return_date=date(2026, 1, 2),
    )
    with pytest.raises(ScheduleValidationError) as raised:
        policy.evaluate([drifted], require_planned_facts=True)
    assert raised.value.code == "PLANNED_LOGISTICS_MISMATCH"


@pytest.mark.parametrize("logistics_days", [-1, 8, True, 1.5, "1"])
def test_logistics_days_must_be_an_integer_from_zero_through_seven(logistics_days):
    with pytest.raises(ScheduleValidationError) as raised:
        ScheduleOverlapPolicy().calculate_planned_window(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 1),
            logistics_days=logistics_days,
        )

    assert raised.value.code == "INVALID_LOGISTICS_DAYS"


def test_inclusive_customer_use_overlap_is_a_blocking_conflict():
    evaluation = ScheduleOverlapPolicy().evaluate(
        [
            rental(10, date(2026, 1, 1), date(2026, 1, 3)),
            rental(20, date(2026, 1, 3), date(2026, 1, 5)),
        ]
    )

    assert not evaluation.can_submit
    assert evaluation.warnings == ()
    assert len(evaluation.hard_conflicts) == 1
    conflict = evaluation.hard_conflicts[0]
    assert conflict.code == USAGE_PERIOD_CONFLICT
    assert conflict.blocking
    assert (conflict.predecessor_rental_id, conflict.successor_rental_id) == (10, 20)


@pytest.mark.parametrize(
    ("predecessor_logistics_days", "successor_start", "expected_overlap"),
    [
        (0, date(2026, 1, 5), -1),
        (0, date(2026, 1, 4), 0),
        (0, date(2026, 1, 3), 1),
        (1, date(2026, 1, 3), 2),
    ],
)
def test_logistics_warning_threshold_is_strictly_greater_than_one(
    predecessor_logistics_days,
    successor_start,
    expected_overlap,
):
    evaluation = ScheduleOverlapPolicy().evaluate(
        [
            rental(
                10,
                date(2026, 1, 1),
                date(2026, 1, 2),
                logistics_days=predecessor_logistics_days,
            ),
            rental(20, successor_start),
        ]
    )

    assert evaluation.can_submit
    if expected_overlap <= 1:
        assert evaluation.warnings == ()
        assert evaluation.relay_candidates == ()
    else:
        assert len(evaluation.warnings) == 1
        warning = evaluation.warnings[0]
        assert warning.code == LOGISTICS_OVERLAP_RELAY_WARNING
        assert warning.overlap_days == expected_overlap
        assert not warning.blocking
        assert warning.relay_candidate
        assert evaluation.relay_candidates is evaluation.warnings


def test_only_adjacent_active_rentals_create_warning_pairs():
    evaluation = ScheduleOverlapPolicy().evaluate(
        [
            rental(30, date(2026, 1, 5), logistics_days=2),
            rental(10, date(2026, 1, 1), logistics_days=2),
            rental(20, date(2026, 1, 3), logistics_days=2),
        ]
    )

    pairs = [
        (warning.predecessor_rental_id, warning.successor_rental_id)
        for warning in evaluation.warnings
    ]
    assert pairs == [(10, 20), (20, 30)]
    assert (10, 30) not in pairs


@pytest.mark.parametrize("terminal_status", ["cancelled", "completed"])
def test_terminal_rentals_are_ignored_before_adjacency_and_field_validation(
    terminal_status,
):
    terminal = rental(
        20,
        "legacy-invalid-date",
        None,
        logistics_days=-999,
        status=terminal_status,
    )
    evaluation = ScheduleOverlapPolicy().evaluate(
        [
            rental(10, date(2026, 1, 1), logistics_days=2),
            terminal,
            rental(30, date(2026, 1, 5), logistics_days=2),
        ]
    )

    assert evaluation.can_submit
    assert [warning.predecessor_rental_id for warning in evaluation.warnings] == [10]
    assert [warning.successor_rental_id for warning in evaluation.warnings] == [30]


def test_edit_exclusion_removes_persisted_self_but_keeps_replacement_candidate():
    original = rental(20, date(2026, 1, 1), date(2026, 1, 10))
    replacement = rental(20, date(2026, 1, 1), date(2026, 1, 2))
    neighbor = rental(30, date(2026, 1, 3), logistics_days=1)

    evaluation = ScheduleOverlapPolicy().evaluate(
        [original, neighbor],
        candidate=replacement,
        exclude_rental_id=20,
    )

    assert evaluation.can_submit
    assert evaluation.hard_conflicts == ()
    assert [
        (
            warning.predecessor_rental_id,
            warning.successor_rental_id,
            warning.overlap_days,
        )
        for warning in evaluation.warnings
    ] == [(20, 30, 2)]


def test_create_candidate_without_database_id_can_be_evaluated():
    evaluation = ScheduleOverlapPolicy().evaluate(
        [rental(10, date(2026, 1, 1), logistics_days=2)],
        candidate=rental(None, date(2026, 1, 3)),
    )

    assert evaluation.can_submit
    assert evaluation.warnings[0].successor_rental_id is None
    assert evaluation.warnings[0].overlap_days == 2


def test_hard_conflict_scan_finds_non_adjacent_nested_overlap():
    evaluation = ScheduleOverlapPolicy().evaluate(
        [
            rental(10, date(2026, 1, 1), date(2026, 1, 10)),
            rental(20, date(2026, 1, 2)),
            rental(30, date(2026, 1, 5)),
        ]
    )

    pairs = {
        (conflict.predecessor_rental_id, conflict.successor_rental_id)
        for conflict in evaluation.hard_conflicts
    }
    assert pairs == {(10, 20), (10, 30)}
    assert evaluation.warnings == ()


def test_analysis_is_scoped_to_each_device():
    evaluation = ScheduleOverlapPolicy().evaluate(
        [
            rental(10, date(2026, 1, 1), date(2026, 1, 3), device_id=1),
            rental(20, date(2026, 1, 3), date(2026, 1, 5), device_id=2),
        ]
    )

    assert evaluation.can_submit
    assert evaluation.hard_conflicts == ()


def test_aware_datetimes_are_converted_to_tenant_natural_dates():
    first = rental(
        10,
        datetime(2026, 1, 1, 16, 30, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 17, 30, tzinfo=timezone.utc),
    )
    second = rental(
        20,
        datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 2, 1, 0, tzinfo=timezone.utc),
    )

    evaluation = ScheduleOverlapPolicy().evaluate(
        [first, second], tenant_timezone="Asia/Shanghai"
    )

    # Both UTC timestamps fall on January 2 in Shanghai, so inclusive use overlaps.
    assert not evaluation.can_submit
    assert evaluation.hard_conflicts[0].code == USAGE_PERIOD_CONFLICT


@pytest.mark.parametrize(
    ("kwargs", "expected_code"),
    [
        ({"tenant_timezone": "Not/A_Timezone"}, "INVALID_TENANT_TIMEZONE"),
        (
            {
                "rentals": [
                    rental(10, datetime(2026, 1, 1, 12), datetime(2026, 1, 2, 12))
                ]
            },
            "NAIVE_DATETIME",
        ),
        (
            {"rentals": [rental(10, "2026-01-01", date(2026, 1, 2))]},
            "INVALID_DATE",
        ),
        (
            {
                "rentals": [rental(10, date(2026, 1, 2), date(2026, 1, 1))]
            },
            "INVALID_USAGE_PERIOD",
        ),
        (
            {"rentals": [rental(10, date(2026, 1, 1), status="mystery")]},
            "INVALID_RENTAL_STATUS",
        ),
    ],
)
def test_invalid_date_timezone_period_and_status_inputs(kwargs, expected_code):
    rentals = kwargs.pop("rentals", [rental(10, date(2026, 1, 1))])

    with pytest.raises(ScheduleValidationError) as raised:
        ScheduleOverlapPolicy().evaluate(rentals, **kwargs)

    assert raised.value.code == expected_code


def test_duplicate_active_rental_ids_are_rejected():
    with pytest.raises(ScheduleValidationError) as raised:
        ScheduleOverlapPolicy().evaluate(
            [
                rental(10, date(2026, 1, 1), device_id=1),
                rental(10, date(2026, 1, 3), device_id=2),
            ]
        )

    assert raised.value.code == "DUPLICATE_RENTAL_ID"
