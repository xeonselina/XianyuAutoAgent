import pytest

from app.services.gantt.reorder_solver import GanttReorderSolver
from app.services.gantt.reorder_types import ScheduleBlock


def block(
    key,
    rental_ids,
    start,
    end,
    current,
    allowed,
    fixed=False,
    model_id=1,
):
    return ScheduleBlock(
        key=key,
        rental_ids=tuple(rental_ids),
        model_id=model_id,
        start_day=start,
        end_day=end,
        current_device_id=current,
        allowed_device_ids=tuple(allowed),
        fixed=fixed,
    )


def test_solver_compacts_touching_blocks_on_one_device():
    blocks = [
        block("1", [1], 10, 15, 1, [1, 2]),
        block("2", [2], 15, 20, 2, [1, 2]),
        block("3", [3], 20, 25, 2, [1, 2]),
    ]

    result = GanttReorderSolver.solve(blocks, [1, 2])

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert len(set(result.assignments.values())) == 1
    assert result.used_devices == 1
    assert result.total_gap_days == 0


def test_solver_keeps_fixed_block_and_avoids_overlap():
    blocks = [
        block("fixed", [1], 10, 20, 1, [1], fixed=True),
        block("move", [2], 15, 25, 2, [1, 2]),
    ]

    result = GanttReorderSolver.solve(blocks, [1, 2])

    assert result.assignments == {1: 1, 2: 2}


def test_solver_reports_infeasible_for_unavoidable_overlap():
    blocks = [
        block("1", [1], 10, 20, 1, [1]),
        block("2", [2], 15, 25, 1, [1]),
    ]

    result = GanttReorderSolver.solve(blocks, [1])

    assert result.status == "INFEASIBLE"
    assert result.assignments == {}


def test_relay_block_members_stay_on_same_device():
    relay = block("relay:1:2", [1, 2], 10, 25, 1, [1, 2])

    result = GanttReorderSolver.solve([relay], [1, 2])

    assert result.assignments[1] == result.assignments[2]


def test_validator_rejects_missing_rental():
    blocks = [block("1", [1], 10, 15, 1, [1, 2])]

    with pytest.raises(ValueError, match="恰好映射一次"):
        GanttReorderSolver.validate_assignment(blocks, {})


def test_solver_rejects_cross_model_input():
    blocks = [
        block("1", [1], 10, 15, 1, [1], model_id=1),
        block("2", [2], 15, 20, 2, [2], model_id=2),
    ]

    with pytest.raises(ValueError, match="单一型号"):
        GanttReorderSolver.solve(blocks, [1, 2])


def test_solver_finds_feasible_dense_schedule_within_three_seconds():
    """回归测试：脱敏后的真实 55 档期结构不能返回 UNKNOWN。"""
    device_ids = tuple(range(1, 20))
    base_day = 739800
    specs = [
        (27, 33, 3, False),
        (11, 20, 19, True),
        (27, 34, 7, False),
        (51, 63, 19, False),
        (28, 33, 8, False),
        (29, 33, 18, False),
        (0, 30, 17, True),
        (29, 35, 6, False),
        (11, 20, 6, True),
        (11, 19, 3, True),
        (2, 22, 7, True),
        (20, 26, 5, False),
        (21, 27, 3, False),
        (13, 20, 10, True),
        (26, 35, 5, False),
        (26, 34, 1, False),
        (27, 38, 10, False),
        (13, 19, 2, True),
        (25, 35, 16, False),
        (14, 19, 16, True),
        (13, 20, 9, True),
        (21, 26, 9, False),
        (21, 26, 10, False),
        (34, 40, 19, False),
        (14, 18, 12, True),
        (28, 33, 9, False),
        (13, 20, 4, True),
        (13, 20, 13, True),
        (15, 19, 1, True),
        (26, 35, 11, False),
        (13, 19, 11, True),
        (11, 20, 18, True),
        (19, 26, 11, False),
        (10, 19, 8, True),
        (20, 25, 6, False),
        (20, 27, 19, False),
        (15, 20, 15, True),
        (38, 54, 1, False),
        (29, 33, 15, False),
        (22, 26, 14, False),
        (13, 19, 5, True),
        (14, 22, 14, True),
        (21, 25, 16, False),
        (22, 27, 15, False),
        (27, 33, 14, False),
        (28, 33, 19, False),
        (22, 26, 7, False),
        (54, 61, 1, False),
        (52, 63, 2, False),
        (52, 63, 3, False),
        (22, 26, 18, False),
        (21, 27, 4, False),
        (19, 25, 1, False),
        (20, 27, 8, False),
        (19, 31, 2, False),
    ]
    blocks = [
        block(
            f"dense-{index}",
            [index],
            base_day + start,
            base_day + end,
            current,
            [current] if fixed else device_ids,
            fixed=fixed,
            model_id=11,
        )
        for index, (start, end, current, fixed) in enumerate(specs, 1)
    ]

    result = GanttReorderSolver.solve(
        blocks, device_ids, time_limit_seconds=0.3
    )

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    GanttReorderSolver.validate_assignment(blocks, result.assignments)
