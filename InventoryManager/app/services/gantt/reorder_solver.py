"""按设备型号运行的纯 OR-Tools 档期求解器。"""

from dataclasses import dataclass

from ortools.sat.python import cp_model


@dataclass(frozen=True)
class SolverResult:
    status: str
    assignments: dict[int, int]
    used_devices: int
    total_gap_days: int
    changed_rentals: int


class GanttReorderSolver:
    STATUS_NAMES = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.UNKNOWN: "UNKNOWN",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
    }

    @classmethod
    def solve(cls, blocks, device_ids, time_limit_seconds=3.0):
        if not blocks:
            return SolverResult("OPTIMAL", {}, 0, 0, 0)

        model_ids = {block.model_id for block in blocks}
        if len(model_ids) != 1:
            raise ValueError("每次求解只能包含单一型号")

        device_ids = tuple(sorted(set(device_ids)))
        known_devices = set(device_ids)
        for block in blocks:
            if block.end_day <= block.start_day:
                raise ValueError(f"档期块 {block.key} 的日期范围无效")
            if not block.allowed_device_ids:
                raise ValueError(f"档期块 {block.key} 没有候选设备")
            if not set(block.allowed_device_ids).issubset(known_devices):
                raise ValueError(f"档期块 {block.key} 引用了未知设备")
            if block.fixed and block.current_device_id not in block.allowed_device_ids:
                raise ValueError(f"固定档期块 {block.key} 缺少当前设备")

        model = cp_model.CpModel()
        horizon_end = max(block.end_day for block in blocks) + 1
        assignment_vars = {}
        intervals_by_device = {device_id: [] for device_id in device_ids}

        for block in blocks:
            choices = []
            for device_id in block.allowed_device_ids:
                chosen = model.new_bool_var(
                    f"block_{block.key}_device_{device_id}"
                )
                assignment_vars[(block.key, device_id)] = chosen
                choices.append(chosen)
                intervals_by_device[device_id].append(
                    model.new_optional_interval_var(
                        block.start_day,
                        block.end_day - block.start_day,
                        block.end_day,
                        chosen,
                        f"interval_{block.key}_{device_id}",
                    )
                )
                if block.fixed:
                    model.add(
                        chosen == int(device_id == block.current_device_id)
                    )
            model.add_exactly_one(choices)

        for intervals in intervals_by_device.values():
            if intervals:
                model.add_no_overlap(intervals)

        used_vars = {}
        gap_vars = {}
        for device_id in device_ids:
            movable_choices = [
                assignment_vars[(block.key, device_id)]
                for block in blocks
                if not block.fixed
                and (block.key, device_id) in assignment_vars
            ]
            used = model.new_bool_var(f"used_by_movable_{device_id}")
            if movable_choices:
                model.add_max_equality(used, movable_choices)
            else:
                model.add(used == 0)
            used_vars[device_id] = used

            choices = [
                (block, assignment_vars[(block.key, device_id)])
                for block in blocks
                if (block.key, device_id) in assignment_vars
            ]
            if not choices:
                continue

            any_assigned = model.new_bool_var(f"any_assigned_{device_id}")
            model.add_max_equality(
                any_assigned, [chosen for _, chosen in choices]
            )
            min_start = model.new_int_var(
                0, horizon_end, f"min_start_{device_id}"
            )
            max_end = model.new_int_var(
                0, horizon_end, f"max_end_{device_id}"
            )
            model.add_min_equality(
                min_start,
                [
                    block.start_day * chosen
                    + horizon_end * (1 - chosen)
                    for block, chosen in choices
                ],
            )
            model.add_max_equality(
                max_end,
                [block.end_day * chosen for block, chosen in choices],
            )
            assigned_duration = cp_model.LinearExpr.sum([
                (block.end_day - block.start_day) * chosen
                for block, chosen in choices
            ])
            gap = model.new_int_var(0, horizon_end, f"gap_{device_id}")
            model.add(
                gap == max_end - min_start - assigned_duration
            ).only_enforce_if(any_assigned)
            model.add(gap == 0).only_enforce_if(any_assigned.Not())
            gap_vars[device_id] = gap

        move_terms = []
        for block in blocks:
            if block.fixed:
                continue
            for device_id in block.allowed_device_ids:
                if device_id != block.current_device_id:
                    move_terms.append(
                        len(block.rental_ids)
                        * assignment_vars[(block.key, device_id)]
                    )

        objectives = [
            cp_model.LinearExpr.sum(list(used_vars.values())),
            cp_model.LinearExpr.sum(list(gap_vars.values())),
            cp_model.LinearExpr.sum(move_terms),
        ]

        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 20260711
        solver.parameters.max_time_in_seconds = max(
            0.05, time_limit_seconds / len(objectives)
        )

        status = cp_model.UNKNOWN
        for objective in objectives:
            model.minimize(objective)
            status = solver.solve(model)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return SolverResult(
                    cls.STATUS_NAMES.get(status, "UNKNOWN"), {}, 0, 0, 0
                )
            model.add(objective == int(round(solver.objective_value)))

        assignments = {}
        for block in blocks:
            target_device_id = next(
                device_id
                for device_id in block.allowed_device_ids
                if solver.boolean_value(
                    assignment_vars[(block.key, device_id)]
                )
            )
            for rental_id in block.rental_ids:
                assignments[rental_id] = target_device_id

        cls.validate_assignment(blocks, assignments)
        return SolverResult(
            cls.STATUS_NAMES.get(status, "UNKNOWN"),
            assignments,
            sum(solver.value(value) for value in used_vars.values()),
            sum(solver.value(value) for value in gap_vars.values()),
            sum(
                len(block.rental_ids)
                for block in blocks
                if not block.fixed
                and assignments[block.rental_ids[0]]
                != block.current_device_id
            ),
        )

    @staticmethod
    def validate_assignment(blocks, assignments):
        expected = {
            rental_id
            for block in blocks
            for rental_id in block.rental_ids
        }
        if set(assignments) != expected:
            raise ValueError("每个 rental 必须恰好映射一次")

        assigned_blocks = {}
        for block in blocks:
            targets = {
                assignments[rental_id] for rental_id in block.rental_ids
            }
            if len(targets) != 1:
                raise ValueError(f"档期块 {block.key} 被拆分")
            target = next(iter(targets))
            if target not in block.allowed_device_ids:
                raise ValueError(f"档期块 {block.key} 的设备映射非法")
            if block.fixed and target != block.current_device_id:
                raise ValueError(f"固定档期块 {block.key} 被移动")
            assigned_blocks.setdefault(target, []).append(block)

        for device_blocks in assigned_blocks.values():
            ordered = sorted(
                device_blocks, key=lambda item: (item.start_day, item.end_day)
            )
            for previous, following in zip(ordered, ordered[1:]):
                if following.start_day < previous.end_day:
                    raise ValueError("普通档期存在超过同日衔接的重叠")
