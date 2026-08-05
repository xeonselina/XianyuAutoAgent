"""接力候选识别和列表合并。"""

from dataclasses import dataclass
from datetime import date, timedelta

from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding
from app.models.rental_relay_case import RentalRelayCase


OPEN_STATUSES = ("pending", "notified", "agreed", "shipped")
ALL_STATUSES = OPEN_STATUSES + ("completed",)


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
            Rental.ship_in_time.isnot(None),
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
                overlap_days = (
                    predecessor.ship_in_time.date()
                    - successor.ship_out_time.date()
                ).days
                if overlap_days < 2:
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
        overlap_days = (
            candidate.overlap_days
            if candidate
            else max(
                0,
                (
                    predecessor.ship_in_time.date()
                    - successor.ship_out_time.date()
                ).days,
            )
        )
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

