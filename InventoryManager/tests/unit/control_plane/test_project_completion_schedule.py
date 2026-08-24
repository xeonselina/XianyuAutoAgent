import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from inventory_control.default_migration import (
    PROJECT_REHEARSAL_LEAD,
    ProjectCompletionIdentity,
    ProjectScheduleError,
    record_project_completion,
    refresh_project_completion,
    select_rehearsal_window,
)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _identity(**overrides) -> ProjectCompletionIdentity:
    values = {
        "implementation_digest": _digest("implementation-a"),
        "image_digest": _digest("image-a"),
        "migration_bundle_digest": _digest("bundle-a"),
        "runtime_configuration_digest": _digest("config-a"),
        "control_schema_head": "202608220026",
        "tenant_schema_head": "20260824_legacy_history",
    }
    values.update(overrides)
    return ProjectCompletionIdentity(**values)


def test_project_completion_schedules_exactly_seven_24_hour_days():
    completed_at = datetime(2026, 8, 22, 3, 4, 5, 678901, tzinfo=timezone.utc)

    schedule = record_project_completion(
        _identity(),
        completed_at=completed_at,
    )

    assert PROJECT_REHEARSAL_LEAD == timedelta(hours=168)
    assert schedule.project_complete_at == completed_at
    assert schedule.earliest_rehearsal_at == completed_at + timedelta(hours=168)


def test_equivalent_offset_time_is_normalized_to_utc():
    china = timezone(timedelta(hours=8))
    completed_at = datetime(2026, 8, 22, 11, 4, 5, tzinfo=china)

    schedule = record_project_completion(_identity(), completed_at=completed_at)

    assert schedule.project_complete_at == datetime(
        2026, 8, 22, 3, 4, 5, tzinfo=timezone.utc
    )
    assert schedule.project_complete_at.tzinfo is timezone.utc
    assert schedule.earliest_rehearsal_at.tzinfo is timezone.utc


def test_same_identity_is_an_exact_replay_and_does_not_move_t():
    first_at = datetime(2026, 8, 22, tzinfo=timezone.utc)
    schedule = record_project_completion(_identity(), completed_at=first_at)

    replay = refresh_project_completion(
        schedule,
        _identity(),
        completed_at=first_at + timedelta(days=2),
        affected_tests_rerun=False,
    )

    assert replay is schedule


def test_changed_identity_requires_tests_and_restarts_full_168_hours():
    first_at = datetime(2026, 8, 22, tzinfo=timezone.utc)
    schedule = record_project_completion(_identity(), completed_at=first_at)
    changed = _identity(migration_bundle_digest=_digest("bundle-b"))

    with pytest.raises(ProjectScheduleError, match="require related tests"):
        refresh_project_completion(
            schedule,
            changed,
            completed_at=first_at + timedelta(days=1),
            affected_tests_rerun=False,
        )

    refreshed_at = first_at + timedelta(days=1)
    refreshed = refresh_project_completion(
        schedule,
        changed,
        completed_at=refreshed_at,
        affected_tests_rerun=True,
    )
    assert refreshed.project_complete_at == refreshed_at
    assert refreshed.earliest_rehearsal_at == refreshed_at + timedelta(hours=168)


def test_refreshed_completion_time_must_advance():
    first_at = datetime(2026, 8, 22, tzinfo=timezone.utc)
    schedule = record_project_completion(_identity(), completed_at=first_at)

    with pytest.raises(ProjectScheduleError, match="must advance"):
        refresh_project_completion(
            schedule,
            _identity(image_digest=_digest("image-b")),
            completed_at=first_at,
            affected_tests_rerun=True,
        )


def test_rehearsal_window_rejects_early_and_accepts_later_availability():
    completed_at = datetime(2026, 8, 22, tzinfo=timezone.utc)
    schedule = record_project_completion(_identity(), completed_at=completed_at)

    with pytest.raises(ProjectScheduleError, match=r"T \+ 168h"):
        select_rehearsal_window(
            schedule,
            selected_window_at=schedule.earliest_rehearsal_at
            - timedelta(microseconds=1),
        )

    selected = schedule.earliest_rehearsal_at + timedelta(hours=9)
    window = select_rehearsal_window(
        schedule,
        selected_window_at=selected,
    )
    assert window.selected_window_at == selected
    assert window.lead_seconds == 604_800 + 9 * 3_600


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 8, 22),
        "2026-08-22T00:00:00Z",
    ],
)
def test_schedule_rejects_non_aware_datetime(value):
    with pytest.raises(ProjectScheduleError, match="timezone-aware"):
        record_project_completion(_identity(), completed_at=value)
