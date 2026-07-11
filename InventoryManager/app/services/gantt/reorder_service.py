"""甘特图档期重排数据库编排服务。"""

from datetime import date, datetime, time

from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding


class GanttReorderService:
    """分析、预览并执行主设备档期重排。"""

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

        return {
            "today": today.isoformat(),
            "overlaps": overlaps,
        }
