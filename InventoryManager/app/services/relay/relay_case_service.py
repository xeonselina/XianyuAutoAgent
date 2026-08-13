"""接力候选识别和列表合并。"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re

from flask import current_app

from app import db
from app.models.audit_log import AuditLog
from app.models.device import Device
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
MANUAL_CURRENT_STATUSES = ("shipped", "returned")
MANUAL_NEXT_STATUSES = ("not_shipped", "scheduled_for_shipping")


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


@dataclass(frozen=True)
class RelayCaseUpdateOutcome:
    relay_case: RentalRelayCase
    xianyu_sync: dict


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
    def _item(cls, pair, candidate, case, binding, source="automatic"):
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
            "source": source,
            "schedule_changed": candidate is None and source != "manual",
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
        manual_case_ids = {
            int(resource_id)
            for (resource_id,) in db.session.query(AuditLog.resource_id).filter(
                AuditLog.action == "relay_case_manually_created",
                AuditLog.resource_id.isnot(None),
            ).all()
            if resource_id.isdigit()
        }

        pairs = set(candidates) | set(cases) | set(bindings)
        items = []
        for pair in pairs:
            candidate = candidates.get(pair)
            case = cases.get(pair)
            binding = bindings.get(pair)
            status = case.status if case else ("agreed" if binding else "pending")
            source = (
                "manual"
                if case and case.id in manual_case_ids
                else "automatic"
            )
            if candidate is None and status == "pending" and source != "manual":
                continue
            if status not in statuses:
                continue
            item = cls._item(pair, candidate, case, binding, source=source)
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

    @staticmethod
    def _manual_rental(rental):
        return {
            "id": rental.id,
            "status": rental.status,
            "start_date": rental.start_date.isoformat(),
            "end_date": rental.end_date.isoformat(),
            "ship_out_time": (
                rental.ship_out_time.isoformat()
                if rental.ship_out_time else None
            ),
            "ship_in_time": (
                rental.ship_in_time.isoformat()
                if rental.ship_in_time else None
            ),
            "buyer_id": rental.buyer_id,
            "customer_name": rental.customer_name,
            "customer_phone": rental.customer_phone,
            "destination": rental.destination,
        }

    @classmethod
    def _manual_pairs(cls):
        rentals = Rental.query.join(
            Device, Device.id == Rental.device_id
        ).filter(
            Rental.parent_rental_id.is_(None),
            Rental.ship_out_time.isnot(None),
            Rental.status.in_(
                MANUAL_CURRENT_STATUSES + MANUAL_NEXT_STATUSES
            ),
            Device.lifecycle_status == "active",
            Device.is_accessory.is_(False),
        ).order_by(
            Rental.device_id,
            Rental.ship_out_time,
            Rental.id,
        ).all()

        by_device = {}
        for rental in rentals:
            by_device.setdefault(rental.device_id, []).append(rental)

        pairs = {}
        for device_id, device_rentals in by_device.items():
            current_rentals = [
                rental for rental in device_rentals
                if rental.status in MANUAL_CURRENT_STATUSES
            ]
            if not current_rentals:
                continue
            predecessor = current_rentals[-1]
            successor = next(
                (
                    rental for rental in device_rentals
                    if rental.status in MANUAL_NEXT_STATUSES
                    and rental.ship_out_time > predecessor.ship_out_time
                ),
                None,
            )
            if successor:
                pairs[device_id] = (predecessor, successor)
        return pairs

    @classmethod
    def list_manual_options(cls):
        pairs = cls._manual_pairs()
        bindings = RentalRelayBinding.query.all()
        exact_pairs = {
            (binding.predecessor_rental_id, binding.successor_rental_id)
            for binding in bindings
        }
        predecessor_bindings = {
            binding.predecessor_rental_id: binding for binding in bindings
        }
        successor_bindings = {
            binding.successor_rental_id: binding for binding in bindings
        }

        items = []
        for predecessor, successor in pairs.values():
            pair = (predecessor.id, successor.id)
            blocked_reason = None
            if pair in exact_pairs:
                blocked_reason = "当前单和下一单已标记为接力"
            elif predecessor.id in predecessor_bindings:
                blocked_reason = "当前 rental 已接力给其他订单"
            elif successor.id in successor_bindings:
                blocked_reason = "下一笔 rental 已从其他订单接力"

            items.append({
                "device": cls._device(predecessor),
                "predecessor": cls._manual_rental(predecessor),
                "successor": cls._manual_rental(successor),
                "lens_combo": predecessor.lens_combo,
                "accessories": predecessor.get_all_accessories_for_display(),
                "successor_lens_combo": successor.lens_combo,
                "successor_accessories": (
                    successor.get_all_accessories_for_display()
                ),
                "can_create": blocked_reason is None,
                "blocked_reason": blocked_reason,
            })

        items.sort(key=lambda item: (
            item["device"]["name"] or "",
            item["device"]["id"] or 0,
        ))
        return {"items": items, "total": len(items)}

    @classmethod
    def create_manual_case(cls, device_id, now=None):
        now = now or datetime.utcnow()
        pair = cls._manual_pairs().get(device_id)
        if pair is None:
            raise ValueError("该设备没有可接力的当前 rental 和下一笔 rental")
        predecessor, successor = pair

        try:
            rentals = Rental.query.filter(
                Rental.id.in_([predecessor.id, successor.id])
            ).with_for_update().all()
            rental_by_id = {rental.id: rental for rental in rentals}
            predecessor = rental_by_id.get(predecessor.id)
            successor = rental_by_id.get(successor.id)
            if predecessor is None or successor is None:
                raise ValueError("当前 rental 或下一笔 rental 不存在")
            latest_pair = cls._manual_pairs().get(device_id)
            if not latest_pair or (
                latest_pair[0].id != predecessor.id
                or latest_pair[1].id != successor.id
            ):
                raise ValueError("档期已变化，请刷新后重试")

            if cls._exact_binding(
                predecessor.id, successor.id, lock=True
            ):
                raise RelayBindingConflictError(
                    "当前单和下一单已标记为接力"
                )

            cls._ensure_binding(predecessor, successor)
            relay_case = RentalRelayCase.query.filter_by(
                predecessor_rental_id=predecessor.id,
                successor_rental_id=successor.id,
            ).with_for_update().one_or_none()
            relay_case = relay_case or RentalRelayCase(
                predecessor_rental_id=predecessor.id,
                successor_rental_id=successor.id,
            )
            relay_case.status = "agreed"
            cls._update_milestones(relay_case, "agreed", now)
            db.session.add(relay_case)
            db.session.flush()
            db.session.add(AuditLog(
                device_id=device_id,
                rental_id=predecessor.id,
                action="relay_case_manually_created",
                resource_type="rental_relay_case",
                resource_id=str(relay_case.id),
                description="人工标记设备当前单与下一单为接力",
                details={
                    "device_id": device_id,
                    "predecessor_rental_id": predecessor.id,
                    "successor_rental_id": successor.id,
                },
            ))
            db.session.commit()
            return relay_case
        except Exception:
            db.session.rollback()
            raise

    @classmethod
    def _require_current_candidate(cls, predecessor, successor):
        pair = (predecessor.id, successor.id)
        if pair not in cls.find_candidates():
            raise ValueError("档期已变化，当前组合不再满足接力条件")

    @staticmethod
    def _is_manual_case(relay_case):
        if relay_case is None or relay_case.id is None:
            return False
        return AuditLog.query.filter_by(
            action="relay_case_manually_created",
            resource_type="rental_relay_case",
            resource_id=str(relay_case.id),
        ).first() is not None

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

    @staticmethod
    def _sync_successor_to_xianyu(successor):
        from app.services import xianyu_order_service

        try:
            result = xianyu_order_service.get_xianyu_service().ship_order(
                successor
            )
            sync_success = bool(result.get("success"))
            message = result.get("message") or (
                "ok" if sync_success else "闲鱼发货失败"
            )
            return {
                "attempted": True,
                "success": sync_success,
                "message": str(message),
            }
        except Exception as exc:
            current_app.logger.exception(
                "接力后一单同步闲鱼失败: successor_rental_id=%s",
                successor.id,
            )
            return {
                "attempted": True,
                "success": False,
                "message": str(exc) or "闲鱼发货失败",
            }

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
            entering_shipped = (
                STATUS_ORDER[old_status] < STATUS_ORDER["shipped"]
                and status == "shipped"
            )

            crossing_into_agreed = (
                STATUS_ORDER[old_status] < STATUS_ORDER["agreed"]
                and STATUS_ORDER[status] >= STATUS_ORDER["agreed"]
            )
            if (
                crossing_into_agreed
                and exact_binding is None
                and not cls._is_manual_case(relay_case)
            ):
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
                if entering_shipped:
                    successor.ship_out_tracking_no = tracking_number
                    successor.status = "shipped"
                    if successor.ship_out_time is None:
                        successor.ship_out_time = now

            relay_case.status = status
            cls._update_milestones(relay_case, status, now)
            db.session.add(relay_case)
            db.session.flush()
            cls._add_audit(relay_case, old_status, status)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        xianyu_sync = {
            "attempted": False,
            "success": False,
            "message": "",
        }
        if entering_shipped:
            xianyu_sync = cls._sync_successor_to_xianyu(successor)
        return RelayCaseUpdateOutcome(
            relay_case=relay_case,
            xianyu_sync=xianyu_sync,
        )

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
