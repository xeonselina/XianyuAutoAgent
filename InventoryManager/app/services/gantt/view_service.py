"""Bounded normalized Gantt range projection for one tenant snapshot."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.accessory_inventory import AccessoryType, RentalAccessoryRequest
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental
from app.models.xianyu_order_alert import (
    XianyuOrderAlert,
    XianyuOrderSyncState,
)
from app.services.scheduling import (
    ACTIVE_RENTAL_STATUSES,
    RentalSchedule,
    ScheduleOverlapPolicy,
)


_MAX_LOGISTICS_BUFFER_DAYS = 8


class GanttRangeViewService:
    """Build the complete range contract with six fixed SQL statements."""

    _schedule_policy = ScheduleOverlapPolicy()

    @classmethod
    def build(
        cls,
        *,
        tenant_session: Session,
        start_date: date,
        end_date: date,
        device_model_id: int | None,
        lifecycle_status: str | None,
        tenant_timezone: str,
        database_now: datetime,
        request_id: str,
    ) -> Mapping[str, object]:
        device_predicates = cls._device_predicates(
            device_model_id=device_model_id,
            lifecycle_status=lifecycle_status,
        )
        device_rows = tenant_session.execute(
            select(
                Device.id,
                Device.name,
                Device.serial_number,
                Device.model,
                Device.model_id,
                Device.warehouse_id,
                Device.lifecycle_status,
                Device.lifecycle_reason,
                Device.lifecycle_date,
                Device.updated_at,
                DeviceModel.name.label("model_name"),
                DeviceModel.display_name.label("model_display_name"),
            )
            .outerjoin(DeviceModel, DeviceModel.id == Device.model_id)
            .where(*device_predicates)
            .order_by(Device.model_id.asc(), Device.id.asc())
        ).all()
        facet_predicates: list[object] = [Device.is_accessory.is_(False)]
        if lifecycle_status is not None:
            facet_predicates.append(
                Device.lifecycle_status == lifecycle_status
            )
        facet_rows = tenant_session.execute(
            select(
                Device.model_id,
                DeviceModel.name.label("model_name"),
                DeviceModel.display_name.label("model_display_name"),
                func.count(Device.id).label("device_count"),
            )
            .outerjoin(DeviceModel, DeviceModel.id == Device.model_id)
            .where(*facet_predicates)
            .group_by(
                Device.model_id,
                DeviceModel.name,
                DeviceModel.display_name,
            )
            .order_by(Device.model_id.asc())
        ).all()

        schedule_start = start_date - timedelta(
            days=_MAX_LOGISTICS_BUFFER_DAYS
        )
        schedule_end = end_date + timedelta(
            days=_MAX_LOGISTICS_BUFFER_DAYS
        )
        visible_overlap = and_(
            Rental.start_date <= end_date,
            Rental.end_date >= start_date,
        )
        schedule_neighbor = and_(
            Rental.status.in_(ACTIVE_RENTAL_STATUSES),
            Rental.start_date <= schedule_end,
            Rental.end_date >= schedule_start,
        )
        rental_rows = tenant_session.execute(
            select(
                Rental.id,
                Rental.device_id,
                Rental.start_date,
                Rental.end_date,
                Rental.customer_name,
                Rental.customer_phone,
                Rental.destination,
                Rental.ship_out_tracking_no,
                Rental.ship_in_tracking_no,
                Rental.xianyu_order_no,
                Rental.order_amount,
                Rental.buyer_id,
                Rental.damage_note,
                Rental.includes_handle,
                Rental.includes_lens_mount,
                Rental.photo_transfer,
                Rental.lens_combo,
                Rental.status,
                Rental.ship_out_time,
                Rental.ship_in_time,
                Rental.logistics_days,
                Rental.planned_ship_out_date,
                Rental.planned_return_date,
                Rental.updated_at,
                Device.name.label("device_name"),
            )
            .join(Device, Device.id == Rental.device_id)
            .where(
                Rental.parent_rental_id.is_(None),
                Rental.status != "cancelled",
                or_(visible_overlap, schedule_neighbor),
                *device_predicates,
            )
            .order_by(
                Rental.device_id.asc(),
                Rental.start_date.asc(),
                Rental.id.asc(),
            )
        ).all()

        visible_rows = [
            row
            for row in rental_rows
            if row.start_date <= end_date and row.end_date >= start_date
        ]
        visible_rental_ids = [row.id for row in visible_rows]
        child_accessory_rows = tenant_session.execute(
            select(
                Rental.parent_rental_id,
                Rental.status,
                Rental.ship_out_time,
                Rental.planned_ship_out_date,
                Rental.updated_at,
                Device.id.label("accessory_device_id"),
                Device.name.label("accessory_name"),
                Device.serial_number.label("accessory_serial_number"),
                Device.model.label("accessory_model"),
            )
            .join(Device, Device.id == Rental.device_id)
            .where(
                Rental.parent_rental_id.in_(visible_rental_ids),
                Rental.status != "cancelled",
                Device.is_accessory.is_(True),
            )
            .order_by(Rental.parent_rental_id.asc(), Device.id.asc())
        ).all()
        logical_accessory_rows = tenant_session.execute(
            select(
                RentalAccessoryRequest.rental_id,
                RentalAccessoryRequest.name_snapshot,
                RentalAccessoryRequest.updated_at,
                AccessoryType.name.label("accessory_type"),
                AccessoryType.display_name,
            )
            .join(
                AccessoryType,
                AccessoryType.id
                == RentalAccessoryRequest.accessory_type_id,
            )
            .where(RentalAccessoryRequest.rental_id.in_(visible_rental_ids))
            .order_by(
                RentalAccessoryRequest.rental_id.asc(),
                AccessoryType.display_order.asc(),
                AccessoryType.id.asc(),
            )
        ).all()

        business_date = database_now.astimezone(
            ZoneInfo(tenant_timezone)
        ).date()
        summary = tenant_session.execute(
            cls._summary_statement(business_date=business_date)
        ).one()

        devices = [cls._device_dto(row) for row in device_rows]
        accessories_by_rental = cls._accessories_by_rental(
            visible_rows,
            child_accessory_rows,
            logical_accessory_rows,
        )
        rentals = [
            cls._rental_dto(
                row,
                accessories=accessories_by_rental[row.id],
            )
            for row in visible_rows
        ]
        warnings = cls._warnings(
            rental_rows,
            start_date=start_date,
            end_date=end_date,
            tenant_timezone=tenant_timezone,
        )
        daily_stats = cls._daily_stats(
            device_rows,
            rental_rows,
            child_accessory_rows,
            start_date=start_date,
            end_date=end_date,
        )
        facets = cls._model_facets(facet_rows)
        pending_revision = cls._summary_revision(
            summary.pending_updated_at,
            int(summary.pending_count or 0),
        )
        alert_revision = cls._summary_revision(
            summary.alert_sync_at or summary.alert_updated_at,
            int(summary.alert_count or 0),
        )
        revision_facts = {
            "range": [start_date.isoformat(), end_date.isoformat()],
            "devices": [
                [
                    row.id,
                    cls._optional_iso(row.updated_at),
                    row.model_id,
                    row.model_name,
                    row.model_display_name,
                    row.lifecycle_status,
                ]
                for row in device_rows
            ],
            "model_facets": [
                [
                    row.model_id,
                    row.model_name,
                    row.model_display_name,
                    int(row.device_count),
                ]
                for row in facet_rows
            ],
            "rentals": [
                [row.id, cls._optional_iso(row.updated_at)]
                for row in rental_rows
            ],
            "device_bound_accessories": [
                [
                    row.parent_rental_id,
                    row.accessory_device_id,
                    cls._optional_iso(row.updated_at),
                ]
                for row in child_accessory_rows
            ],
            "logical_accessory_requests": [
                [
                    row.rental_id,
                    row.accessory_type,
                    cls._optional_iso(row.updated_at),
                ]
                for row in logical_accessory_rows
            ],
            "pending_returns": pending_revision,
            "xianyu_alerts": alert_revision,
        }
        return {
            "request_id": request_id,
            "evaluated_at": cls._utc_iso(database_now),
            "date_range": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
            "devices": devices,
            "rentals": rentals,
            "daily_stats_by_date": daily_stats,
            "model_facets": facets,
            "schedule_warnings": warnings,
            "summaries": {
                "pending_returns": {
                    "count": int(summary.pending_count or 0),
                    "revision": pending_revision,
                },
                "xianyu_alerts": {
                    "count": int(summary.alert_count or 0),
                    "revision": alert_revision,
                },
            },
            "data_revision": sha256(
                json.dumps(
                    revision_facts,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
        }

    @staticmethod
    def _device_predicates(
        *,
        device_model_id: int | None,
        lifecycle_status: str | None,
    ) -> tuple[object, ...]:
        predicates: list[object] = [Device.is_accessory.is_(False)]
        if device_model_id is not None:
            predicates.append(Device.model_id == device_model_id)
        if lifecycle_status is not None:
            predicates.append(Device.lifecycle_status == lifecycle_status)
        return tuple(predicates)

    @staticmethod
    def _summary_statement(*, business_date: date):
        pending_predicates = (
            Rental.status == "shipped",
            Rental.parent_rental_id.is_(None),
            Rental.end_date < business_date,
        )
        pending_count = (
            select(func.count(Rental.id))
            .where(*pending_predicates)
            .scalar_subquery()
        )
        pending_updated_at = (
            select(func.max(Rental.updated_at))
            .where(*pending_predicates)
            .scalar_subquery()
        )
        alert_count = (
            select(func.count(XianyuOrderAlert.id))
            .where(XianyuOrderAlert.state == "pending")
            .scalar_subquery()
        )
        alert_updated_at = (
            select(func.max(XianyuOrderAlert.updated_at))
            .where(XianyuOrderAlert.state == "pending")
            .scalar_subquery()
        )
        alert_sync_at = (
            select(XianyuOrderSyncState.last_success_at)
            .where(XianyuOrderSyncState.id == 1)
            .scalar_subquery()
        )
        return select(
            pending_count.label("pending_count"),
            pending_updated_at.label("pending_updated_at"),
            alert_count.label("alert_count"),
            alert_updated_at.label("alert_updated_at"),
            alert_sync_at.label("alert_sync_at"),
        )

    @staticmethod
    def _device_dto(row) -> dict[str, object]:
        return {
            "id": row.id,
            "name": row.name,
            "serial_number": row.serial_number,
            "model": row.model,
            "model_id": row.model_id,
            "model_name": row.model_name,
            "model_display_name": row.model_display_name,
            "warehouse_id": row.warehouse_id,
            "lifecycle_status": row.lifecycle_status,
            "lifecycle_reason": row.lifecycle_reason,
            "lifecycle_date": GanttRangeViewService._optional_iso(
                row.lifecycle_date
            ),
        }

    @staticmethod
    def _rental_dto(
        row,
        *,
        accessories: list[dict[str, object]],
    ) -> dict[str, object]:
        return {
            "id": row.id,
            "device_id": row.device_id,
            "device_name": row.device_name,
            "start_date": row.start_date.isoformat(),
            "end_date": row.end_date.isoformat(),
            "customer_name": row.customer_name,
            "customer_phone": row.customer_phone,
            "destination": row.destination,
            "ship_out_tracking_no": row.ship_out_tracking_no,
            "ship_in_tracking_no": row.ship_in_tracking_no,
            "xianyu_order_no": row.xianyu_order_no,
            "order_amount": (
                float(row.order_amount)
                if row.order_amount is not None else None
            ),
            "buyer_id": row.buyer_id,
            "damage_note": row.damage_note,
            "includes_handle": bool(row.includes_handle),
            "includes_lens_mount": bool(row.includes_lens_mount),
            "photo_transfer": bool(row.photo_transfer),
            "lens_combo": row.lens_combo,
            "accessories": accessories,
            "status": row.status,
            "ship_out_time": GanttRangeViewService._optional_iso(
                row.ship_out_time
            ),
            "ship_in_time": GanttRangeViewService._optional_iso(
                row.ship_in_time
            ),
            "logistics_days": row.logistics_days,
            "planned_ship_out_date": GanttRangeViewService._optional_iso(
                row.planned_ship_out_date
            ),
            "planned_return_date": GanttRangeViewService._optional_iso(
                row.planned_return_date
            ),
        }

    @classmethod
    def _accessories_by_rental(
        cls,
        rental_rows,
        child_rows,
        logical_rows,
    ) -> defaultdict[int, list[dict[str, object]]]:
        result: defaultdict[int, list[dict[str, object]]] = defaultdict(list)
        for row in rental_rows:
            if row.includes_handle:
                result[row.id].append({
                    "name": "手柄",
                    "type": "handle",
                    "tracking_mode": "device_bound",
                    "is_accessory": True,
                    "is_bundled": True,
                })
            if row.includes_lens_mount:
                result[row.id].append({
                    "name": "镜头支架",
                    "type": "lens_mount",
                    "tracking_mode": "device_bound",
                    "is_accessory": True,
                    "is_bundled": True,
                })
        for row in child_rows:
            result[row.parent_rental_id].append({
                "id": row.accessory_device_id,
                "name": row.accessory_name,
                "serial_number": row.accessory_serial_number,
                "model": row.accessory_model,
                "type": cls._infer_accessory_type(row.accessory_name),
                "tracking_mode": "device_bound",
                "is_accessory": True,
                "is_bundled": False,
            })
        for row in logical_rows:
            result[row.rental_id].append({
                "name": row.name_snapshot or row.display_name,
                "type": row.accessory_type,
                "tracking_mode": "logical_unit",
                "is_accessory": True,
                "is_bundled": False,
            })
        return result

    @staticmethod
    def _infer_accessory_type(name: str) -> str:
        lowered = name.lower()
        if "手机支架" in name or "phone" in lowered:
            return "phone_holder"
        if "三脚架" in name or "tripod" in lowered:
            return "tripod"
        if "手柄" in name:
            return "handle"
        if "镜头支架" in name:
            return "lens_mount"
        return "other"

    @classmethod
    def _warnings(
        cls,
        rows,
        *,
        start_date: date,
        end_date: date,
        tenant_timezone: str,
    ) -> list[dict[str, object]]:
        active_rows = [
            row for row in rows if row.status in ACTIVE_RENTAL_STATUSES
        ]
        row_by_id = {row.id: row for row in active_rows}
        evaluation = cls._schedule_policy.evaluate(
            tuple(
                RentalSchedule(
                    rental_id=row.id,
                    device_id=row.device_id,
                    start_date=row.start_date,
                    end_date=row.end_date,
                    logistics_days=row.logistics_days,
                    status=row.status,
                    planned_ship_out_date=row.planned_ship_out_date,
                    planned_return_date=row.planned_return_date,
                )
                for row in active_rows
            ),
            tenant_timezone=tenant_timezone,
            require_planned_facts=True,
        )
        result = []
        for warning in evaluation.warnings:
            predecessor = row_by_id[warning.predecessor_rental_id]
            successor = row_by_id[warning.successor_rental_id]
            if (
                predecessor.planned_return_date < start_date
                or successor.planned_ship_out_date > end_date
            ):
                continue
            result.append({
                "code": warning.code,
                "blocking": warning.blocking,
                "relay_candidate": warning.relay_candidate,
                "device_id": warning.device_id,
                "predecessor_rental_id": warning.predecessor_rental_id,
                "successor_rental_id": warning.successor_rental_id,
                "overlap_days": warning.overlap_days,
            })
        return result

    @staticmethod
    def _daily_stats(
        device_rows,
        rental_rows,
        child_accessory_rows,
        *,
        start_date: date,
        end_date: date,
    ) -> dict[str, dict[str, int]]:
        active_device_ids = {
            row.id
            for row in device_rows
            if row.lifecycle_status == "active"
        }
        occupied: dict[date, set[int]] = defaultdict(set)
        ship_out_counts: dict[date, int] = defaultdict(int)
        return_counts: dict[date, int] = defaultdict(int)
        accessory_ship_out_counts: dict[date, int] = defaultdict(int)
        for row in rental_rows:
            if row.status not in ACTIVE_RENTAL_STATUSES:
                continue
            lower = max(start_date, row.start_date)
            upper = min(end_date, row.end_date)
            current = lower
            while current <= upper:
                if row.device_id in active_device_ids:
                    occupied[current].add(row.device_id)
                current += timedelta(days=1)
            if (
                row.planned_ship_out_date is not None
                and start_date <= row.planned_ship_out_date <= end_date
            ):
                ship_out_counts[row.planned_ship_out_date] += 1
            if (
                row.planned_return_date is not None
                and start_date <= row.planned_return_date <= end_date
            ):
                return_counts[row.planned_return_date] += 1
        for row in child_accessory_rows:
            if row.status not in ACTIVE_RENTAL_STATUSES:
                continue
            ship_out_date = row.planned_ship_out_date
            if ship_out_date is None and row.ship_out_time is not None:
                ship_out_date = row.ship_out_time.date()
            if (
                ship_out_date is not None
                and start_date <= ship_out_date <= end_date
            ):
                accessory_ship_out_counts[ship_out_date] += 1

        result = {}
        current = start_date
        total = len(active_device_ids)
        while current <= end_date:
            occupied_count = len(occupied[current])
            result[current.isoformat()] = {
                "total_device_count": total,
                "available_count": total - occupied_count,
                "occupied_count": occupied_count,
                "planned_ship_out_count": ship_out_counts[current],
                "planned_return_count": return_counts[current],
                # Compatibility names used by both Gantt clients.  They are
                # derived in the same snapshot, not fetched per day.
                "ship_out_count": ship_out_counts[current],
                "accessory_ship_out_count": (
                    accessory_ship_out_counts[current]
                ),
            }
            current += timedelta(days=1)
        return result

    @staticmethod
    def _model_facets(rows) -> list[dict[str, object]]:
        return [
            {
                "model_id": row.model_id,
                "name": row.model_name or "未分类型号",
                "display_name": (
                    row.model_display_name
                    or row.model_name
                    or "未分类型号"
                ),
                "device_count": int(row.device_count),
            }
            for row in rows
        ]

    @staticmethod
    def _summary_revision(value: object, count: int) -> str:
        return f"{GanttRangeViewService._optional_iso(value) or 'none'}:{count}"

    @staticmethod
    def _optional_iso(value: object) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _utc_iso(value: datetime) -> str:
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")


__all__ = ["GanttRangeViewService"]
