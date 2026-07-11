"""甘特图档期重排数据库编排服务。"""

from datetime import date, datetime, time
from dataclasses import replace
import hashlib
import json
import uuid

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import db
from app.models.device import Device
from app.models.audit_log import AuditLog
from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding
from app.services.gantt.reorder_solver import GanttReorderSolver
from app.services.gantt.reorder_types import ScheduleBlock


class StalePreviewError(ValueError):
    """预览令牌过期或快照已经变化。"""


class GanttReorderService:
    """分析、预览并执行主设备档期重排。"""

    TOKEN_SALT = "gantt-schedule-reorder-v1"
    TOKEN_MAX_AGE_SECONDS = 600
    SOLVER_VERSION = "cp-sat-v1"

    @staticmethod
    def _customer(rental):
        return {
            "id": rental.id,
            "customer_name": rental.customer_name,
            "customer_phone": rental.customer_phone,
            "destination": rental.destination,
            "ship_out_time": rental.ship_out_time.isoformat(),
            "ship_in_time": rental.ship_in_time.isoformat(),
        }

    @staticmethod
    def _is_movable(rental, today):
        return (
            rental.parent_rental_id is None
            and rental.status == "not_shipped"
            and rental.ship_out_time is not None
            and rental.ship_out_time.date() >= today
            and rental.device is not None
            and rental.device.model_id is not None
        )

    @classmethod
    def analyze(cls, today=None):
        today = today or date.today()
        day_start = datetime.combine(today, time.min)
        bindings = {
            (item.predecessor_rental_id, item.successor_rental_id): item
            for item in RentalRelayBinding.query.all()
        }
        rentals = Rental.query.filter(
            Rental.parent_rental_id.is_(None),
            Rental.status != "cancelled",
            Rental.ship_out_time.isnot(None),
            Rental.ship_in_time.isnot(None),
            Rental.ship_in_time >= day_start,
        ).order_by(
            Rental.device_id,
            Rental.ship_out_time,
            Rental.id,
        ).all()

        by_device = {}
        for rental in rentals:
            by_device.setdefault(rental.device_id, []).append(rental)

        overlaps = []
        for device_rentals in by_device.values():
            for predecessor, successor in zip(
                device_rentals, device_rentals[1:]
            ):
                overlap_days = (
                    predecessor.ship_in_time.date()
                    - successor.ship_out_time.date()
                ).days
                if overlap_days <= 0:
                    continue

                binding = bindings.get((predecessor.id, successor.id))
                overlaps.append({
                    "pair_key": f"{predecessor.id}:{successor.id}",
                    "status": "bound" if binding else "needs_confirmation",
                    "binding_id": binding.id if binding else None,
                    "overlap_days": overlap_days,
                    "can_separate": (
                        cls._is_movable(predecessor, today)
                        or cls._is_movable(successor, today)
                    ),
                    "device": {
                        "id": predecessor.device.id,
                        "name": predecessor.device.name,
                        "model_id": predecessor.device.model_id,
                    },
                    "predecessor": cls._customer(predecessor),
                    "successor": cls._customer(successor),
                })

        return {"today": today.isoformat(), "overlaps": overlaps}

    @staticmethod
    def _validate_decisions(decisions):
        normalized = []
        seen = set()
        for raw in decisions or []:
            try:
                predecessor_id = int(raw["predecessor_rental_id"])
                successor_id = int(raw["successor_rental_id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("接力选择缺少有效的 rental ID") from exc
            action = raw.get("action")
            if action not in {"keep", "separate"}:
                raise ValueError("接力选择 action 必须是 keep 或 separate")
            pair = (predecessor_id, successor_id)
            if pair in seen:
                raise ValueError("接力选择包含重复 rental 对")
            seen.add(pair)
            normalized.append({
                "predecessor_rental_id": predecessor_id,
                "successor_rental_id": successor_id,
                "action": action,
            })
        return sorted(
            normalized,
            key=lambda item: (
                item["predecessor_rental_id"],
                item["successor_rental_id"],
            ),
        )

    @classmethod
    def _validate_overlap_decisions(cls, decisions, today):
        analysis = cls.analyze(today=today)
        overlap_by_pair = {
            (
                item["predecessor"]["id"],
                item["successor"]["id"],
            ): item
            for item in analysis["overlaps"]
        }
        decision_by_pair = {
            (
                item["predecessor_rental_id"],
                item["successor_rental_id"],
            ): item
            for item in decisions
        }

        unknown_pairs = set(decision_by_pair) - set(overlap_by_pair)
        if unknown_pairs:
            raise ValueError("接力选择包含不存在的重叠 rental 对")

        unresolved = [
            item
            for pair, item in overlap_by_pair.items()
            if item["status"] == "needs_confirmation"
            and pair not in decision_by_pair
        ]
        if unresolved:
            raise ValueError("仍有未确认的重叠档期")

        for pair, decision in decision_by_pair.items():
            overlap = overlap_by_pair[pair]
            if decision["action"] == "separate" and not overlap["can_separate"]:
                raise ValueError("两笔固定 rental 无法拆分，只能保持接力")

        return analysis

    @staticmethod
    def _query_with_optional_lock(query, lock):
        return query.with_for_update() if lock else query

    @classmethod
    def _load_reorder_graph(cls, today, lock=False):
        day_start = datetime.combine(today, time.min)
        main_query = Rental.query.filter(
            Rental.parent_rental_id.is_(None),
            Rental.status != "cancelled",
            db.or_(
                Rental.status == "not_shipped",
                Rental.ship_in_time >= day_start,
            ),
        ).order_by(Rental.id)
        main_rentals = cls._query_with_optional_lock(
            main_query, lock
        ).all()
        main_ids = [rental.id for rental in main_rentals]

        child_rentals = []
        bindings = []
        if main_ids:
            child_query = Rental.query.filter(
                Rental.parent_rental_id.in_(main_ids)
            ).order_by(Rental.id)
            child_rentals = cls._query_with_optional_lock(
                child_query, lock
            ).all()
            binding_query = RentalRelayBinding.query.filter(
                db.or_(
                    RentalRelayBinding.predecessor_rental_id.in_(main_ids),
                    RentalRelayBinding.successor_rental_id.in_(main_ids),
                )
            ).order_by(RentalRelayBinding.id)
            bindings = cls._query_with_optional_lock(
                binding_query, lock
            ).all()

        model_ids = {
            rental.device.model_id
            for rental in main_rentals
            if rental.device and rental.device.model_id is not None
        }
        referenced_device_ids = {
            rental.device_id for rental in main_rentals + child_rentals
        }
        device_query = Device.query.filter(
            db.or_(
                Device.id.in_(referenced_device_ids or {-1}),
                db.and_(
                    Device.model_id.in_(model_ids or {-1}),
                    Device.is_accessory.is_(False),
                    Device.status == "online",
                    Device.lifecycle_status == "active",
                ),
            )
        ).order_by(Device.id)
        devices = cls._query_with_optional_lock(device_query, lock).all()
        return main_rentals + child_rentals, devices, bindings

    @staticmethod
    def _iso(value):
        return value.isoformat() if value is not None else None

    @classmethod
    def _snapshot(cls, rentals, devices, bindings, decisions, today):
        rental_rows = []
        for rental in sorted(rentals, key=lambda item: item.id):
            rental_rows.append({
                "id": rental.id,
                "device_id": rental.device_id,
                "model_id": rental.device.model_id if rental.device else None,
                "parent_rental_id": rental.parent_rental_id,
                "start_date": cls._iso(rental.start_date),
                "end_date": cls._iso(rental.end_date),
                "ship_out_time": cls._iso(rental.ship_out_time),
                "ship_in_time": cls._iso(rental.ship_in_time),
                "status": rental.status,
                "customer_name": rental.customer_name,
                "customer_phone": rental.customer_phone,
                "destination": rental.destination,
                "updated_at": cls._iso(rental.updated_at),
            })
        device_rows = [
            {
                "id": device.id,
                "model_id": device.model_id,
                "is_accessory": device.is_accessory,
                "status": device.status,
                "lifecycle_status": device.lifecycle_status,
                "updated_at": cls._iso(device.updated_at),
            }
            for device in sorted(devices, key=lambda item: item.id)
        ]
        binding_rows = [
            {
                "id": binding.id,
                "predecessor_rental_id": binding.predecessor_rental_id,
                "successor_rental_id": binding.successor_rental_id,
                "updated_at": cls._iso(binding.updated_at),
            }
            for binding in sorted(bindings, key=lambda item: item.id)
        ]
        return {
            "today": today.isoformat(),
            "rentals": rental_rows,
            "devices": device_rows,
            "bindings": binding_rows,
            "decisions": decisions,
        }

    @staticmethod
    def _hash_snapshot(snapshot):
        encoded = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @classmethod
    def _serializer(cls):
        return URLSafeTimedSerializer(
            current_app.config["SECRET_KEY"], salt=cls.TOKEN_SALT
        )

    @classmethod
    def _sign_preview(
        cls, snapshot_hash, decisions, assignments, today
    ):
        return cls._serializer().dumps({
            "snapshot_hash": snapshot_hash,
            "decisions": decisions,
            "assignments": {
                str(key): value for key, value in assignments.items()
            },
            "today": today.isoformat(),
            "solver_version": cls.SOLVER_VERSION,
        })

    @classmethod
    def _load_preview(cls, token):
        try:
            return cls._serializer().loads(
                token, max_age=cls.TOKEN_MAX_AGE_SECONDS
            )
        except SignatureExpired as exc:
            raise StalePreviewError("预览已过期，请重新预览") from exc
        except BadSignature as exc:
            raise StalePreviewError("预览令牌无效") from exc

    @staticmethod
    def _union_components(ids, edges):
        parent = {item_id: item_id for item_id in ids}

        def find(item_id):
            while parent[item_id] != item_id:
                parent[item_id] = parent[parent[item_id]]
                item_id = parent[item_id]
            return item_id

        def union(left, right):
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        for left, right in edges:
            if left in parent and right in parent:
                union(left, right)

        components = {}
        for item_id in ids:
            components.setdefault(find(item_id), []).append(item_id)
        return list(components.values())

    @classmethod
    def _build_blocks(
        cls, rentals, devices, bindings, decisions, today
    ):
        main_rentals = {
            rental.id: rental
            for rental in rentals
            if rental.parent_rental_id is None
        }
        effective_edges = {
            (
                binding.predecessor_rental_id,
                binding.successor_rental_id,
            )
            for binding in bindings
        }
        for decision in decisions:
            pair = (
                decision["predecessor_rental_id"],
                decision["successor_rental_id"],
            )
            if decision["action"] == "keep":
                predecessor = main_rentals[pair[0]]
                successor = main_rentals[pair[1]]
                RentalRelayBinding.validate_pair(predecessor, successor)
                effective_edges.add(pair)
            else:
                effective_edges.discard(pair)

        components = cls._union_components(
            main_rentals.keys(), effective_edges
        )
        active_candidates = {}
        for device in devices:
            if (
                not device.is_accessory
                and device.status == "online"
                and device.lifecycle_status == "active"
                and device.model_id is not None
            ):
                active_candidates.setdefault(device.model_id, []).append(
                    device.id
                )

        skipped = []
        models = {}
        for component_ids in components:
            component = [main_rentals[item_id] for item_id in component_ids]
            if any(
                rental.ship_out_time is None
                or rental.ship_in_time is None
                or rental.device is None
                or rental.device.model_id is None
                for rental in component
            ):
                for rental in component:
                    if cls._is_movable(rental, today) or rental.status == "not_shipped":
                        skipped.append({
                            "rental_id": rental.id,
                            "reason": "缺少物流时间或设备型号",
                        })
                continue

            model_ids = {rental.device.model_id for rental in component}
            current_device_ids = {rental.device_id for rental in component}
            if len(model_ids) != 1 or len(current_device_ids) != 1:
                raise ValueError("接力链必须属于同型号且位于同一设备")
            model_id = next(iter(model_ids))
            current_device_id = next(iter(current_device_ids))
            fixed = any(
                not cls._is_movable(rental, today) for rental in component
            )
            allowed_device_ids = (
                (current_device_id,)
                if fixed
                else tuple(sorted(active_candidates.get(model_id, [])))
            )
            if not allowed_device_ids:
                for rental in component:
                    skipped.append({
                        "rental_id": rental.id,
                        "reason": "同型号没有在线且使用中的目标设备",
                    })
                continue

            ordered = sorted(
                component,
                key=lambda item: (item.ship_out_time, item.id),
            )
            block = ScheduleBlock(
                key="relay:" + ":".join(
                    str(rental.id) for rental in ordered
                ),
                rental_ids=tuple(rental.id for rental in ordered),
                model_id=model_id,
                start_day=min(
                    rental.ship_out_time.date().toordinal()
                    for rental in component
                ),
                end_day=max(
                    rental.ship_in_time.date().toordinal()
                    for rental in component
                ),
                current_device_id=current_device_id,
                allowed_device_ids=allowed_device_ids,
                fixed=fixed,
            )
            model_data = models.setdefault(model_id, {
                "blocks": [],
                "device_ids": set(),
            })
            model_data["blocks"].append(block)
            model_data["device_ids"].update(allowed_device_ids)

        for model_id in list(models):
            model_data = models[model_id]
            has_movable = any(
                not block.fixed for block in model_data["blocks"]
            )
            if not has_movable:
                del models[model_id]
                continue
            model_data["blocks"].sort(key=lambda block: block.key)
            model_data["device_ids"] = tuple(
                sorted(model_data["device_ids"])
            )
        return models, skipped

    @staticmethod
    def _model_summary(model_id, model_data, result):
        movable_ids = {
            rental_id
            for block in model_data["blocks"]
            if not block.fixed
            for rental_id in block.rental_ids
        }
        before_devices = {
            block.current_device_id
            for block in model_data["blocks"]
            if not block.fixed
        }
        after_devices = {
            result.assignments[rental_id]
            for rental_id in movable_ids
            if rental_id in result.assignments
        }
        return {
            "model_id": model_id,
            "status": result.status,
            "before_devices": len(before_devices),
            "after_devices": len(after_devices),
            "movable_rentals": len(movable_ids),
            "changed_rentals": result.changed_rentals,
            "total_gap_days": result.total_gap_days,
        }

    @classmethod
    def _changes(cls, rentals, devices, assignments, today):
        device_by_id = {device.id: device for device in devices}
        changes = []
        for rental in rentals:
            target = assignments.get(rental.id)
            if (
                target is None
                or target == rental.device_id
                or not cls._is_movable(rental, today)
            ):
                continue
            changes.append({
                "rental_id": rental.id,
                "model_id": rental.device.model_id,
                "customer_name": rental.customer_name,
                "customer_phone": rental.customer_phone,
                "destination": rental.destination,
                "ship_out_time": rental.ship_out_time.isoformat(),
                "ship_in_time": rental.ship_in_time.isoformat(),
                "from_device_id": rental.device_id,
                "from_device_name": rental.device.name,
                "to_device_id": target,
                "to_device_name": device_by_id[target].name,
            })
        return sorted(changes, key=lambda item: item["rental_id"])

    @classmethod
    def preview(cls, decisions, today=None):
        today = today or date.today()
        normalized = cls._validate_decisions(decisions)
        analysis = cls._validate_overlap_decisions(normalized, today)
        rentals, devices, bindings = cls._load_reorder_graph(
            today=today, lock=False
        )
        snapshot = cls._snapshot(
            rentals, devices, bindings, normalized, today
        )
        models, skipped = cls._build_blocks(
            rentals, devices, bindings, normalized, today
        )

        assignments = {}
        model_results = []
        for model_id, model_data in sorted(models.items()):
            result = GanttReorderSolver.solve(
                model_data["blocks"],
                model_data["device_ids"],
                time_limit_seconds=3.0,
            )
            if result.status in {"OPTIMAL", "FEASIBLE"}:
                assignments.update(result.assignments)
            model_results.append(
                cls._model_summary(model_id, model_data, result)
            )

        changes = cls._changes(rentals, devices, assignments, today)
        token = cls._sign_preview(
            cls._hash_snapshot(snapshot),
            normalized,
            assignments,
            today,
        )
        return {
            "token": token,
            "models": model_results,
            "changes": changes,
            "skipped": skipped,
            "overlaps": analysis["overlaps"],
        }

    @classmethod
    def _validate_pinned_assignments(cls, models, assignments):
        for model_data in models.values():
            blocks = model_data["blocks"]
            expected_ids = {
                rental_id
                for block in blocks
                for rental_id in block.rental_ids
            }
            provided_ids = expected_ids.intersection(assignments)
            if not provided_ids:
                continue
            if provided_ids != expected_ids:
                raise ValueError("预览设备映射不完整")

            model_assignments = {
                rental_id: assignments[rental_id]
                for rental_id in expected_ids
            }
            GanttReorderSolver.validate_assignment(
                blocks, model_assignments
            )
            pinned_blocks = []
            pinned_devices = set()
            for block in blocks:
                targets = {
                    model_assignments[rental_id]
                    for rental_id in block.rental_ids
                }
                if len(targets) != 1:
                    raise ValueError("接力档期块被拆分")
                target = next(iter(targets))
                if target not in block.allowed_device_ids:
                    raise ValueError("预览包含不合法的目标设备")
                pinned_devices.add(target)
                pinned_blocks.append(replace(
                    block,
                    current_device_id=target,
                    allowed_device_ids=(target,),
                    fixed=True,
                ))
            result = GanttReorderSolver.solve(
                pinned_blocks,
                sorted(pinned_devices),
                time_limit_seconds=3.0,
            )
            if result.status not in {"OPTIMAL", "FEASIBLE"}:
                raise ValueError("预览设备映射已不可执行")

    @classmethod
    def _integrity_snapshot(cls, rentals, today):
        mains = [
            rental
            for rental in rentals
            if rental.parent_rental_id is None
        ]
        children = [
            rental
            for rental in rentals
            if rental.parent_rental_id is not None
        ]

        def immutable_values(rental):
            return (
                rental.id,
                rental.parent_rental_id,
                rental.start_date,
                rental.end_date,
                rental.ship_out_time,
                rental.ship_in_time,
                rental.status,
                rental.customer_name,
                rental.customer_phone,
                rental.destination,
            )

        child_ids_by_parent = {}
        for child in children:
            child_ids_by_parent.setdefault(
                child.parent_rental_id, []
            ).append(child.id)
        return {
            "main_ids": {rental.id for rental in mains},
            "child_ids": {rental.id for rental in children},
            "movable_main_ids": {
                rental.id
                for rental in mains
                if cls._is_movable(rental, today)
            },
            "main_immutable": {
                rental.id: (
                    immutable_values(rental),
                    rental.device.model_id if rental.device else None,
                    tuple(sorted(child_ids_by_parent.get(rental.id, []))),
                )
                for rental in mains
            },
            "child_values": {
                rental.id: (
                    rental.device_id,
                    immutable_values(rental),
                )
                for rental in children
            },
        }

    @staticmethod
    def _apply_relay_decisions(decisions, rentals, bindings):
        main_by_id = {
            rental.id: rental
            for rental in rentals
            if rental.parent_rental_id is None
        }
        binding_by_pair = {
            (
                binding.predecessor_rental_id,
                binding.successor_rental_id,
            ): binding
            for binding in bindings
        }
        changes = []
        for decision in decisions:
            pair = (
                decision["predecessor_rental_id"],
                decision["successor_rental_id"],
            )
            existing = binding_by_pair.get(pair)
            if decision["action"] == "keep" and existing is None:
                predecessor = main_by_id[pair[0]]
                successor = main_by_id[pair[1]]
                RentalRelayBinding.validate_pair(
                    predecessor, successor
                )
                db.session.add(RentalRelayBinding(
                    predecessor_rental_id=pair[0],
                    successor_rental_id=pair[1],
                ))
                changes.append({
                    "action": "created",
                    "predecessor_rental_id": pair[0],
                    "successor_rental_id": pair[1],
                })
            elif decision["action"] == "separate" and existing:
                db.session.delete(existing)
                changes.append({
                    "action": "deleted",
                    "predecessor_rental_id": pair[0],
                    "successor_rental_id": pair[1],
                })
        return changes

    @classmethod
    def _apply_device_assignments(
        cls, rentals, devices, assignments, today
    ):
        main_by_id = {
            rental.id: rental
            for rental in rentals
            if rental.parent_rental_id is None
        }
        device_by_id = {device.id: device for device in devices}
        for rental_id, target_device_id in assignments.items():
            rental = main_by_id.get(rental_id)
            if rental is None:
                raise ValueError("预览包含非主 rental")
            if target_device_id == rental.device_id:
                continue
            if not cls._is_movable(rental, today):
                raise ValueError("预览试图移动固定 rental")
            target = device_by_id.get(target_device_id)
            if target is None:
                raise ValueError("目标设备不存在")
            if (
                target.is_accessory
                or target.status != "online"
                or target.lifecycle_status != "active"
            ):
                raise ValueError("目标设备不是使用中的主设备")
            if target.model_id != rental.device.model_id:
                raise ValueError("禁止跨型号重排")
            rental.device_id = target_device_id

    @staticmethod
    def _write_audit_rows(device_changes, relay_changes):
        operation_id = str(uuid.uuid4())
        for change in device_changes:
            db.session.add(AuditLog(
                rental_id=change["rental_id"],
                device_id=change["to_device_id"],
                action="gantt_schedule_reordered",
                resource_type="rental",
                resource_id=str(change["rental_id"]),
                description="甘特图一键重排设备",
                details={"operation_id": operation_id, **change},
            ))
        if relay_changes:
            db.session.add(AuditLog(
                action="gantt_relay_bindings_changed",
                resource_type="rental_relay_binding",
                resource_id=operation_id,
                description="甘特图接力关系变更",
                details={
                    "operation_id": operation_id,
                    "changes": relay_changes,
                },
            ))

    @classmethod
    def _assert_integrity(
        cls, before, rentals, assignments, today
    ):
        after = cls._integrity_snapshot(rentals, today)
        if before["main_ids"] != after["main_ids"]:
            raise RuntimeError("主 rental 集合发生变化")
        if before["child_ids"] != after["child_ids"]:
            raise RuntimeError("子 rental 集合发生变化")
        if before["main_immutable"] != after["main_immutable"]:
            raise RuntimeError("主 rental 非设备字段发生变化")
        if before["child_values"] != after["child_values"]:
            raise RuntimeError("子 rental 字段发生变化")
        if set(assignments) - before["main_ids"]:
            raise RuntimeError("存在未授权 rental 映射")

        main_by_id = {
            rental.id: rental
            for rental in rentals
            if rental.parent_rental_id is None
        }
        for rental_id in before["movable_main_ids"]:
            if rental_id in assignments:
                if main_by_id[rental_id].device_id != assignments[rental_id]:
                    raise RuntimeError("实际设备分配与预览不一致")

    @classmethod
    def execute(cls, token):
        payload = cls._load_preview(token)
        preview_today = date.fromisoformat(payload["today"])
        if preview_today != date.today():
            raise StalePreviewError("预览日期已变化，请重新预览")

        try:
            decisions = cls._validate_decisions(payload["decisions"])
            rentals, devices, bindings = cls._load_reorder_graph(
                today=preview_today, lock=True
            )
            snapshot = cls._snapshot(
                rentals, devices, bindings, decisions, preview_today
            )
            if cls._hash_snapshot(snapshot) != payload["snapshot_hash"]:
                raise StalePreviewError("档期或设备状态已变化，请重新预览")

            assignments = {
                int(key): int(value)
                for key, value in payload["assignments"].items()
            }
            models, _ = cls._build_blocks(
                rentals,
                devices,
                bindings,
                decisions,
                preview_today,
            )
            cls._validate_pinned_assignments(models, assignments)
            before = cls._integrity_snapshot(rentals, preview_today)
            device_changes = cls._changes(
                rentals, devices, assignments, preview_today
            )
            relay_changes = cls._apply_relay_decisions(
                decisions, rentals, bindings
            )
            cls._apply_device_assignments(
                rentals, devices, assignments, preview_today
            )
            cls._write_audit_rows(device_changes, relay_changes)
            db.session.flush()
            cls._assert_integrity(
                before, rentals, assignments, preview_today
            )
            db.session.commit()
            return {
                "changes": device_changes,
                "relay_changes": relay_changes,
            }
        except Exception:
            db.session.rollback()
            raise
