"""接力候选识别和列表合并。"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re

from app import db
from app.models.audit_log import AuditLog
from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding
from app.models.rental_relay_case import RentalRelayCase
from app.services.shipping.sf_tracking_service import SFTrackingService


OPEN_STATUSES = ("pending", "notified", "agreed", "shipped")
ALL_STATUSES = OPEN_STATUSES + ("completed",)
STATUS_ORDER = {
    "pending": 0,
    "notified": 1,
    "agreed": 2,
    "shipped": 3,
    "completed": 4,
}
MILESTONE_FIELDS = {
    "notified": "notified_at",
    "agreed": "agreed_at",
    "shipped": "shipped_at",
    "completed": "completed_at",
}


class RelayBindingConflictError(ValueError):
    """目标 rental 已被另一条不可分叉接力关系占用。"""


@dataclass(frozen=True)
class RelayCandidate:
    predecessor: Rental
    successor: Rental
    overlap_days: int

    @property
    def pair(self):
        return self.predecessor.id, self.successor.id


class RelayCaseService:
    """组合实时候选与已经持久化的运营记录。"""

    @staticmethod
    def find_candidates():
        rentals = Rental.query.filter(
            Rental.parent_rental_id.is_(None),
            Rental.status != "cancelled",
            Rental.ship_out_time.isnot(None),
        ).order_by(
            Rental.device_id,
            Rental.ship_out_time,
            Rental.id,
        ).all()

        by_device = {}
        for rental in rentals:
            by_device.setdefault(rental.device_id, []).append(rental)

        candidates = {}
        for device_rentals in by_device.values():
            for predecessor, successor in zip(
                device_rentals, device_rentals[1:]
            ):
                if (
                    predecessor.ship_in_time is None
                    or successor.ship_out_time is None
                ):
                    continue
                overlap_days = (
                    predecessor.ship_in_time.date()
                    - successor.ship_out_time.date()
                ).days
                if overlap_days <= 0:
                    continue
                candidate = RelayCandidate(
                    predecessor=predecessor,
                    successor=successor,
                    overlap_days=overlap_days,
                )
                candidates[candidate.pair] = candidate
        return candidates

    @staticmethod
    def _customer(rental):
        return {
            "id": rental.id,
            "start_date": rental.start_date.isoformat(),
            "end_date": rental.end_date.isoformat(),
            "buyer_id": rental.buyer_id,
            "customer_name": rental.customer_name,
            "customer_phone": rental.customer_phone,
            "destination": rental.destination,
        }

    @staticmethod
    def _device(rental):
        device = rental.device
        model = device.device_model if device else None
        return {
            "id": device.id if device else None,
            "name": device.name if device else None,
            "model": device.model if device else None,
            "model_id": device.model_id if device else None,
            "model_display_name": (
                model.display_name if model else (device.model if device else None)
            ),
        }

    @staticmethod
    def _tracking(case):
        return {
            "number": case.sf_tracking_number if case else None,
            "status": case.sf_tracking_status if case else None,
            "summary": case.sf_tracking_summary if case else None,
            "last_checked_at": (
                case.sf_last_checked_at.isoformat()
                if case and case.sf_last_checked_at
                else None
            ),
        }

    @classmethod
    def _item(cls, pair, candidate, case, binding):
        predecessor = candidate.predecessor if candidate else (
            case.predecessor if case else binding.predecessor
        )
        successor = candidate.successor if candidate else (
            case.successor if case else binding.successor
        )
        if candidate:
            overlap_days = candidate.overlap_days
        elif predecessor.ship_in_time and successor.ship_out_time:
            overlap_days = max(
                0,
                (
                    predecessor.ship_in_time.date()
                    - successor.ship_out_time.date()
                ).days,
            )
        else:
            overlap_days = 0
        status = case.status if case else ("agreed" if binding else "pending")
        return {
            "case_id": case.id if case else None,
            "pair_key": f"{pair[0]}:{pair[1]}",
            "status": status,
            "binding_id": binding.id if binding else None,
            "schedule_changed": candidate is None,
            "overlap_days": overlap_days,
            "planned_ship_date": (
                predecessor.end_date + timedelta(days=1)
            ).isoformat(),
            "planned_receive_date": (
                successor.start_date - timedelta(days=1)
            ).isoformat(),
            "predecessor": cls._customer(predecessor),
            "successor": cls._customer(successor),
            "device": cls._device(predecessor),
            "lens_combo": predecessor.lens_combo,
            "accessories": predecessor.get_all_accessories_for_display(),
            "successor_lens_combo": successor.lens_combo,
            "successor_accessories": successor.get_all_accessories_for_display(),
            "tracking": cls._tracking(case),
            "created_at": (
                case.created_at.isoformat() if case and case.created_at else None
            ),
            "updated_at": (
                case.updated_at.isoformat() if case and case.updated_at else None
            ),
        }

    @classmethod
    def list_cases(
        cls,
        statuses=None,
        ship_date_from=None,
        ship_date_to=None,
        page=1,
        per_page=50,
        today=None,
    ):
        today = today or date.today()
        statuses = list(statuses or OPEN_STATUSES)
        invalid_statuses = set(statuses) - set(ALL_STATUSES)
        if invalid_statuses:
            raise ValueError(
                "无效的接力状态: " + ", ".join(sorted(invalid_statuses))
            )
        ship_date_from = ship_date_from or today - timedelta(days=3)
        ship_date_to = ship_date_to or today + timedelta(days=5)
        if ship_date_from > ship_date_to:
            raise ValueError("寄出时间范围开始日期不能晚于结束日期")
        if page < 1 or per_page < 1:
            raise ValueError("分页参数必须为正整数")

        candidates = cls.find_candidates()
        cases = {
            (case.predecessor_rental_id, case.successor_rental_id): case
            for case in RentalRelayCase.query.all()
        }
        bindings = {
            (binding.predecessor_rental_id, binding.successor_rental_id): binding
            for binding in RentalRelayBinding.query.all()
        }

        pairs = set(candidates) | set(cases) | set(bindings)
        items = []
        for pair in pairs:
            candidate = candidates.get(pair)
            case = cases.get(pair)
            binding = bindings.get(pair)
            status = case.status if case else ("agreed" if binding else "pending")
            if candidate is None and status == "pending":
                continue
            if status not in statuses:
                continue
            item = cls._item(pair, candidate, case, binding)
            planned_ship_date = date.fromisoformat(item["planned_ship_date"])
            if not ship_date_from <= planned_ship_date <= ship_date_to:
                continue
            items.append(item)

        items.sort(
            key=lambda item: (
                item["planned_ship_date"],
                item["predecessor"]["id"],
                item["successor"]["id"],
            )
        )
        total = len(items)
        start = (page - 1) * per_page
        paginated_items = items[start:start + per_page]
        return {
            "items": paginated_items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            "open_total": sum(
                1 for item in items if item["status"] != "completed"
            ),
            "filters": {
                "statuses": statuses,
                "ship_date_from": ship_date_from.isoformat(),
                "ship_date_to": ship_date_to.isoformat(),
            },
        }

    @classmethod
    def _require_current_candidate(cls, predecessor, successor):
        pair = (predecessor.id, successor.id)
        if pair not in cls.find_candidates():
            raise ValueError("档期已变化，当前组合不再满足接力条件")

    @staticmethod
    def _exact_binding(predecessor_id, successor_id, lock=False):
        query = RentalRelayBinding.query.filter_by(
            predecessor_rental_id=predecessor_id,
            successor_rental_id=successor_id,
        )
        if lock:
            query = query.with_for_update()
        return query.one_or_none()

    @classmethod
    def _ensure_binding(cls, predecessor, successor):
        existing = cls._exact_binding(
            predecessor.id, successor.id, lock=True
        )
        if existing:
            return existing

        predecessor_conflict = RentalRelayBinding.query.filter(
            RentalRelayBinding.predecessor_rental_id == predecessor.id,
            RentalRelayBinding.successor_rental_id != successor.id,
        ).with_for_update().first()
        successor_conflict = RentalRelayBinding.query.filter(
            RentalRelayBinding.successor_rental_id == successor.id,
            RentalRelayBinding.predecessor_rental_id != predecessor.id,
        ).with_for_update().first()
        if predecessor_conflict or successor_conflict:
            conflict = predecessor_conflict or successor_conflict
            raise RelayBindingConflictError(
                "前单或后单已存在其他接力绑定"
                f"（{conflict.predecessor_rental_id}:"
                f"{conflict.successor_rental_id}）"
            )

        RentalRelayBinding.validate_pair(predecessor, successor)
        binding = RentalRelayBinding(
            predecessor_rental_id=predecessor.id,
            successor_rental_id=successor.id,
        )
        db.session.add(binding)
        return binding

    @classmethod
    def _delete_exact_binding(cls, predecessor_id, successor_id):
        binding = cls._exact_binding(
            predecessor_id, successor_id, lock=True
        )
        if binding:
            db.session.delete(binding)

    @staticmethod
    def _update_milestones(relay_case, target_status, now):
        target_order = STATUS_ORDER[target_status]
        for milestone_status, field_name in MILESTONE_FIELDS.items():
            milestone_order = STATUS_ORDER[milestone_status]
            if milestone_order <= target_order:
                if getattr(relay_case, field_name) is None:
                    setattr(relay_case, field_name, now)
            else:
                setattr(relay_case, field_name, None)

    @classmethod
    def _add_audit(cls, relay_case, old_status, new_status):
        db.session.add(AuditLog(
            rental_id=relay_case.predecessor_rental_id,
            action="relay_case_status_changed",
            resource_type="rental_relay_case",
            resource_id=str(relay_case.id),
            description="接力管理状态变更",
            details={
                "predecessor_rental_id": relay_case.predecessor_rental_id,
                "successor_rental_id": relay_case.successor_rental_id,
                "old_status": old_status,
                "new_status": new_status,
                "sf_tracking_number": relay_case.sf_tracking_number,
            },
        ))

    @classmethod
    def update_case(
        cls,
        predecessor_id,
        successor_id,
        status,
        sf_tracking_number=None,
        now=None,
    ):
        if status not in STATUS_ORDER:
            raise ValueError("无效的接力状态")
        if predecessor_id == successor_id:
            raise ValueError("接力前后 rental 不能相同")

        now = now or datetime.utcnow()
        try:
            rentals = Rental.query.filter(
                Rental.id.in_([predecessor_id, successor_id])
            ).with_for_update().all()
            rental_by_id = {rental.id: rental for rental in rentals}
            predecessor = rental_by_id.get(predecessor_id)
            successor = rental_by_id.get(successor_id)
            if predecessor is None or successor is None:
                raise ValueError("前单或后单不存在")

            relay_case = RentalRelayCase.query.filter_by(
                predecessor_rental_id=predecessor_id,
                successor_rental_id=successor_id,
            ).with_for_update().one_or_none()
            exact_binding = cls._exact_binding(
                predecessor_id, successor_id, lock=True
            )
            old_status = (
                relay_case.status
                if relay_case
                else ("agreed" if exact_binding else "pending")
            )

            crossing_into_agreed = (
                STATUS_ORDER[old_status] < STATUS_ORDER["agreed"]
                and STATUS_ORDER[status] >= STATUS_ORDER["agreed"]
            )
            if crossing_into_agreed:
                cls._require_current_candidate(predecessor, successor)

            relay_case = relay_case or RentalRelayCase(
                predecessor_rental_id=predecessor_id,
                successor_rental_id=successor_id,
            )

            if STATUS_ORDER[status] >= STATUS_ORDER["agreed"]:
                cls._ensure_binding(predecessor, successor)
            elif STATUS_ORDER[old_status] >= STATUS_ORDER["agreed"]:
                cls._delete_exact_binding(predecessor_id, successor_id)

            if STATUS_ORDER[status] >= STATUS_ORDER["shipped"]:
                tracking_number = (
                    sf_tracking_number
                    or relay_case.sf_tracking_number
                    or ""
                ).strip()
                if not tracking_number:
                    raise ValueError("已寄出必须录入顺丰运单号")
                relay_case.sf_tracking_number = tracking_number

            relay_case.status = status
            cls._update_milestones(relay_case, status, now)
            db.session.add(relay_case)
            db.session.flush()
            cls._add_audit(relay_case, old_status, status)
            db.session.commit()
            return relay_case
        except Exception:
            db.session.rollback()
            raise

    @classmethod
    def refresh_tracking(cls, case_id, now=None):
        now = now or datetime.utcnow()
        relay_case = RentalRelayCase.query.filter_by(id=case_id).one_or_none()
        if relay_case is None:
            raise ValueError("接力记录不存在")
        if relay_case.status not in {"shipped", "completed"}:
            raise ValueError("接力记录尚未寄出，不能查询物流")
        if not relay_case.sf_tracking_number:
            raise ValueError("接力记录缺少顺丰运单号")

        try:
            phone_digits = re.sub(
                r"\D", "", relay_case.predecessor.customer_phone or ""
            )
            if len(phone_digits) < 4:
                raise ValueError("缺少前单客户手机号，无法查询顺丰物流")

            route_info = SFTrackingService.query(
                relay_case.sf_tracking_number,
                phone_digits[-4:],
            )
            relay_case.sf_tracking_status = route_info.get(
                "status", "unknown"
            )
            status_text = route_info.get("status_text") or "未知状态"
            last_update = route_info.get("last_update")
            relay_case.sf_tracking_summary = (
                f"{status_text} · {last_update}"
                if last_update
                else status_text
            )
        except Exception as exc:
            relay_case.sf_tracking_status = "query_failed"
            relay_case.sf_tracking_summary = str(exc) or "顺丰物流查询失败"

        relay_case.sf_last_checked_at = now
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return cls._tracking(relay_case)
