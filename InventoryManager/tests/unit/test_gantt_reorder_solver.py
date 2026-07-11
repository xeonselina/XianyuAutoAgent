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
