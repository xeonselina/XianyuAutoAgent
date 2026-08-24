"""Realtime warehouse-aware rental availability in one tenant snapshot."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
from string import hexdigits
from typing import Final

from sqlalchemy import and_, case, select
from sqlalchemy.orm import Session

from app.models.accessory_inventory import (
    AccessoryType,
    AccessoryUnit,
    DeviceAccessoryConfig,
    RentalAccessoryUnitLink,
)
from app.models.device import Device
from app.models.rental import Rental
from app.models.warehouse import Warehouse, WarehouseProviderBinding
from app.services.scheduling import (
    ACTIVE_RENTAL_STATUSES,
    RentalSchedule,
    ScheduleOverlapPolicy,
)


_MAX_SCHEDULE_BUFFER_DAYS: Final = 8
_DESTINATION_FIELDS: Final = (
    "province",
    "city",
    "district",
    "address_detail",
)


class RentalAvailabilityInvalid(ValueError):
    """A booking availability request has an invalid bounded shape."""


@dataclass(frozen=True, slots=True)
class ManualLogisticsConfirmation:
    days: int
    context: str


@dataclass(frozen=True, slots=True)
class RentalAvailabilityInput:
    start_date: date
    end_date: date
    model_id: int
    preferred_warehouse_id: int | None
    exclude_rental_id: int | None
    destination: Mapping[str, str]
    requested_accessory_type_ids: tuple[int, ...]
    manual_logistics_by_warehouse: Mapping[
        int,
        ManualLogisticsConfirmation,
    ]


def parse_availability_input(value: object) -> RentalAvailabilityInput:
    if not isinstance(value, Mapping):
        raise RentalAvailabilityInvalid("可用性查询格式错误")
    start_date = _required_date(value.get("start_date"), "start_date")
    end_date = _required_date(value.get("end_date"), "end_date")
    if end_date < start_date:
        raise RentalAvailabilityInvalid("结束日期不能早于开始日期")
    model_id = _positive_integer(value.get("model_id"), "model_id")
    preferred_warehouse_id = _optional_positive_integer(
        value.get("preferred_warehouse_id"),
        "preferred_warehouse_id",
    )
    exclude_rental_id = _optional_positive_integer(
        value.get("exclude_rental_id"),
        "exclude_rental_id",
    )

    raw_destination = value.get("destination")
    if not isinstance(raw_destination, Mapping):
        raise RentalAvailabilityInvalid("必须提供结构化收货地址")
    destination = {}
    for field_name in _DESTINATION_FIELDS:
        maximum = 255 if field_name == "address_detail" else 64
        destination[field_name] = _required_text(
            raw_destination.get(field_name),
            field_name,
            maximum=maximum,
        )

    raw_requested_types = value.get("requested_accessory_type_ids", ())
    if not isinstance(raw_requested_types, (list, tuple)):
        raise RentalAvailabilityInvalid("附件类型选择格式错误")
    if len(raw_requested_types) > 32:
        raise RentalAvailabilityInvalid("附件类型选择过多")
    requested_accessory_type_ids = tuple(sorted({
        _positive_integer(item, "requested accessory_type_id")
        for item in raw_requested_types
    }))

    raw_confirmations = value.get("manual_logistics_by_warehouse", {})
    if not isinstance(raw_confirmations, Mapping):
        raise RentalAvailabilityInvalid("人工物流确认格式错误")
    confirmations: dict[int, ManualLogisticsConfirmation] = {}
    for raw_warehouse_id, raw_confirmation in raw_confirmations.items():
        warehouse_id = _positive_integer(
            raw_warehouse_id,
            "manual warehouse_id",
        )
        if not isinstance(raw_confirmation, Mapping):
            raise RentalAvailabilityInvalid("人工物流确认格式错误")
        raw_days = raw_confirmation.get("days")
        if isinstance(raw_days, bool):
            raise RentalAvailabilityInvalid("人工物流天数必须是0到7的整数")
        try:
            days = int(raw_days)
        except (TypeError, ValueError, OverflowError):
            raise RentalAvailabilityInvalid(
                "人工物流天数必须是0到7的整数"
            ) from None
        if days < 0 or days > 7 or str(days) != str(raw_days):
            raise RentalAvailabilityInvalid("人工物流天数必须是0到7的整数")
        context = raw_confirmation.get("context")
        if (
            not isinstance(context, str)
            or len(context) != 64
            or any(character not in hexdigits for character in context)
        ):
            raise RentalAvailabilityInvalid("人工物流确认上下文无效")
        confirmations[warehouse_id] = ManualLogisticsConfirmation(
            days=days,
            context=context.lower(),
        )

    return RentalAvailabilityInput(
        start_date=start_date,
        end_date=end_date,
        model_id=model_id,
        preferred_warehouse_id=preferred_warehouse_id,
        exclude_rental_id=exclude_rental_id,
        destination=destination,
        requested_accessory_type_ids=requested_accessory_type_ids,
        manual_logistics_by_warehouse=confirmations,
    )


class RentalAvailabilityService:
    """Build candidates with five fixed SQL statements and no provider call."""

    _schedule_policy = ScheduleOverlapPolicy()

    @classmethod
    def evaluate(
        cls,
        *,
        tenant_session: Session,
        request: RentalAvailabilityInput,
        tenant_timezone: str,
        database_now: datetime,
        request_id: str,
    ) -> Mapping[str, object]:
        candidate_rows = tenant_session.execute(
            select(
                Device.id,
                Device.name,
                Device.serial_number,
                Device.model,
                Device.model_id,
                Device.warehouse_id,
                Warehouse.warehouse_uuid,
                Warehouse.name.label("warehouse_name"),
                Warehouse.province,
                Warehouse.city,
                Warehouse.district,
                Warehouse.address_detail,
                WarehouseProviderBinding.status.label("sf_binding_status"),
                WarehouseProviderBinding.binding_revision.label(
                    "sf_binding_revision"
                ),
                WarehouseProviderBinding.verified_at.label(
                    "sf_binding_verified_at"
                ),
            )
            .join(Warehouse, Warehouse.id == Device.warehouse_id)
            .outerjoin(
                WarehouseProviderBinding,
                and_(
                    WarehouseProviderBinding.warehouse_id == Warehouse.id,
                    WarehouseProviderBinding.provider == "sf",
                ),
            )
            .where(
                Device.model_id == request.model_id,
                Device.is_accessory.is_(False),
                Device.lifecycle_status == "active",
                Warehouse.status == "active",
                Warehouse.setup_state == "ready",
            )
            .order_by(
                case(
                    (
                        Device.warehouse_id == request.preferred_warehouse_id,
                        0,
                    ),
                    else_=1,
                ),
                Device.id.asc(),
            )
        ).all()
        device_ids = tuple(row.id for row in candidate_rows)
        warehouse_ids = tuple(sorted({row.warehouse_id for row in candidate_rows}))

        schedule_start = request.start_date - timedelta(
            days=_MAX_SCHEDULE_BUFFER_DAYS
        )
        schedule_end = request.end_date + timedelta(
            days=_MAX_SCHEDULE_BUFFER_DAYS
        )
        schedule_predicates: list[object] = [
            Rental.device_id.in_(device_ids or (-1,)),
            Rental.parent_rental_id.is_(None),
            Rental.status.in_(ACTIVE_RENTAL_STATUSES),
            Rental.start_date <= schedule_end,
            Rental.end_date >= schedule_start,
        ]
        if request.exclude_rental_id is not None:
            schedule_predicates.append(Rental.id != request.exclude_rental_id)
        schedule_rows = tenant_session.execute(
            select(
                Rental.id,
                Rental.device_id,
                Rental.start_date,
                Rental.end_date,
                Rental.logistics_days,
                Rental.planned_ship_out_date,
                Rental.planned_return_date,
                Rental.status,
            )
            .where(*schedule_predicates)
            .order_by(
                Rental.device_id.asc(),
                Rental.start_date.asc(),
                Rental.id.asc(),
            )
        ).all()

        config_rows = tenant_session.execute(
            select(
                DeviceAccessoryConfig.device_id,
                AccessoryType.id.label("accessory_type_id"),
                AccessoryType.name.label("accessory_type_name"),
                AccessoryType.display_name.label("accessory_display_name"),
                AccessoryType.tracking_mode,
                AccessoryType.display_order,
            )
            .join(
                AccessoryType,
                AccessoryType.id == DeviceAccessoryConfig.accessory_type_id,
            )
            .where(
                DeviceAccessoryConfig.device_id.in_(device_ids or (-1,)),
                DeviceAccessoryConfig.enabled.is_(True),
                AccessoryType.is_active.is_(True),
            )
            .order_by(
                DeviceAccessoryConfig.device_id.asc(),
                AccessoryType.display_order.asc(),
                AccessoryType.id.asc(),
            )
        ).all()
        accessory_type_ids = tuple(sorted({
            row.accessory_type_id
            for row in config_rows
            if row.tracking_mode == "logical_unit"
        }))
        configured_type_ids = {
            row.accessory_type_id for row in config_rows
        }
        if (
            set(request.requested_accessory_type_ids)
            - configured_type_ids
        ):
            raise RentalAvailabilityInvalid("选择的附件类型不可用于该型号")

        unit_rows = tenant_session.execute(
            select(
                AccessoryUnit.id,
                AccessoryUnit.accessory_type_id,
                AccessoryUnit.warehouse_id,
                AccessoryUnit.current_holder_rental_id,
            )
            .where(
                AccessoryUnit.warehouse_id.in_(warehouse_ids or (-1,)),
                AccessoryUnit.accessory_type_id.in_(
                    accessory_type_ids or (-1,)
                ),
                AccessoryUnit.condition_status == "active",
            )
            .order_by(
                AccessoryUnit.warehouse_id.asc(),
                AccessoryUnit.accessory_type_id.asc(),
                AccessoryUnit.id.asc(),
            )
        ).all()
        broad_start = datetime.combine(schedule_start, time.min)
        broad_end = datetime.combine(schedule_end + timedelta(days=1), time.min)
        link_rows = tenant_session.execute(
            select(
                RentalAccessoryUnitLink.rental_id,
                RentalAccessoryUnitLink.accessory_type_id,
                RentalAccessoryUnitLink.accessory_unit_id,
                RentalAccessoryUnitLink.reservation_start_at,
                RentalAccessoryUnitLink.reservation_end_at,
                RentalAccessoryUnitLink.source_relay_case_id,
            )
            .join(
                AccessoryUnit,
                AccessoryUnit.id
                == RentalAccessoryUnitLink.accessory_unit_id,
            )
            .where(
                AccessoryUnit.warehouse_id.in_(warehouse_ids or (-1,)),
                AccessoryUnit.accessory_type_id.in_(
                    accessory_type_ids or (-1,)
                ),
                RentalAccessoryUnitLink.reservation_start_at < broad_end,
                RentalAccessoryUnitLink.reservation_end_at > broad_start,
            )
            .order_by(
                RentalAccessoryUnitLink.accessory_unit_id.asc(),
                RentalAccessoryUnitLink.reservation_start_at.asc(),
            )
        ).all()

        estimates = cls._warehouse_estimates(
            candidate_rows,
            request=request,
        )
        unknown_manual_ids = (
            set(request.manual_logistics_by_warehouse) - set(warehouse_ids)
        )
        if unknown_manual_ids:
            raise RentalAvailabilityInvalid("人工物流确认仓库已不可用")

        schedules_by_device: dict[int, list[object]] = defaultdict(list)
        for row in schedule_rows:
            schedules_by_device[row.device_id].append(row)
        configs_by_device: dict[int, list[object]] = defaultdict(list)
        for row in config_rows:
            configs_by_device[row.device_id].append(row)
        units_by_scope: dict[tuple[int, int], list[object]] = defaultdict(list)
        for row in unit_rows:
            units_by_scope[(row.warehouse_id, row.accessory_type_id)].append(row)
        links_by_unit: dict[str, list[object]] = defaultdict(list)
        for row in link_rows:
            links_by_unit[row.accessory_unit_id].append(row)

        candidates = []
        for row in candidate_rows:
            estimate = estimates[row.warehouse_id]
            logistics_days = estimate["logistics_days"]
            evaluation_days = logistics_days if logistics_days is not None else 0
            planned = cls._schedule_policy.calculate_planned_window(
                start_date=request.start_date,
                end_date=request.end_date,
                logistics_days=evaluation_days,
                tenant_timezone=tenant_timezone,
            )
            existing = tuple(
                RentalSchedule(
                    rental_id=existing_row.id,
                    device_id=existing_row.device_id,
                    start_date=existing_row.start_date,
                    end_date=existing_row.end_date,
                    logistics_days=existing_row.logistics_days,
                    status=existing_row.status,
                    planned_ship_out_date=(
                        existing_row.planned_ship_out_date
                    ),
                    planned_return_date=existing_row.planned_return_date,
                )
                for existing_row in schedules_by_device[row.id]
            )
            evaluation = cls._schedule_policy.evaluate(
                existing,
                candidate=RentalSchedule(
                    rental_id=None,
                    device_id=row.id,
                    start_date=request.start_date,
                    end_date=request.end_date,
                    logistics_days=evaluation_days,
                    status="not_shipped",
                    planned_ship_out_date=planned.planned_ship_out_date,
                    planned_return_date=planned.planned_return_date,
                ),
                tenant_timezone=tenant_timezone,
                require_planned_facts=True,
            )
            available = not evaluation.hard_conflicts
            warnings = []
            if logistics_days is not None:
                warnings = [
                    {
                        "code": warning.code,
                        "overlap_days": warning.overlap_days,
                        "predecessor_rental_id": (
                            warning.predecessor_rental_id
                        ),
                        "successor_rental_id": warning.successor_rental_id,
                        "blocking": warning.blocking,
                    }
                    for warning in evaluation.warnings
                ]
            candidates.append({
                "device": {
                    "id": row.id,
                    "name": row.name,
                    "serial_number": row.serial_number,
                    "model": row.model,
                    "model_id": row.model_id,
                    "warehouse_id": row.warehouse_id,
                },
                "warehouse": {
                    "id": row.warehouse_id,
                    "name": row.warehouse_name,
                    "province": row.province,
                    "city": row.city,
                    "district": row.district,
                },
                "available": available,
                "hard_conflicts": [
                    {
                        "code": conflict.code,
                        "predecessor_rental_id": (
                            conflict.predecessor_rental_id
                        ),
                        "successor_rental_id": conflict.successor_rental_id,
                    }
                    for conflict in evaluation.hard_conflicts
                ],
                "warnings": warnings,
                "relay_candidate": bool(warnings),
                "logistics_days": logistics_days,
                "planned_ship_out_date": (
                    planned.planned_ship_out_date.isoformat()
                    if logistics_days is not None else None
                ),
                "planned_return_date": (
                    planned.planned_return_date.isoformat()
                    if logistics_days is not None else None
                ),
                "submission_ready": (
                    available and logistics_days is not None
                ),
                "accessories": cls._accessory_counts(
                    configs_by_device[row.id],
                    units_by_scope=units_by_scope,
                    links_by_unit=links_by_unit,
                    warehouse_id=row.warehouse_id,
                    requested_type_ids=set(
                        request.requested_accessory_type_ids
                    ),
                    exclude_rental_id=request.exclude_rental_id,
                    relay_predecessor_ids={
                        int(warning["predecessor_rental_id"])
                        for warning in warnings
                        if warning["successor_rental_id"] is None
                        and warning["predecessor_rental_id"] is not None
                    },
                    planned_ship_out_date=(
                        planned.planned_ship_out_date
                        if logistics_days is not None else None
                    ),
                    planned_return_date=(
                        planned.planned_return_date
                        if logistics_days is not None else None
                    ),
                ),
            })

        return {
            "request_id": request_id,
            "evaluated_at": _utc_iso(database_now),
            "usage_period": {
                "start_date": request.start_date.isoformat(),
                "end_date": request.end_date.isoformat(),
                "inclusive": True,
            },
            "destination_summary": {
                field_name: request.destination[field_name]
                for field_name in ("province", "city", "district")
            },
            "preferred_warehouse_id": request.preferred_warehouse_id,
            "requested_accessory_type_ids": list(
                request.requested_accessory_type_ids
            ),
            "estimate_by_warehouse": {
                str(warehouse_id): estimate
                for warehouse_id, estimate in sorted(estimates.items())
            },
            "candidates": candidates,
        }

    @classmethod
    def _warehouse_estimates(
        cls,
        candidate_rows,
        *,
        request: RentalAvailabilityInput,
    ) -> dict[int, dict[str, object]]:
        estimates = {}
        first_by_warehouse = {}
        for row in candidate_rows:
            first_by_warehouse.setdefault(row.warehouse_id, row)
        destination_digest = sha256(
            json.dumps(
                dict(request.destination),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        for warehouse_id, row in first_by_warehouse.items():
            context_facts = {
                "warehouse_uuid": row.warehouse_uuid,
                "origin": {
                    "province": row.province,
                    "city": row.city,
                    "district": row.district,
                    "address_detail": row.address_detail,
                },
                "destination_digest": destination_digest,
                "sf_binding_revision": row.sf_binding_revision,
                "sf_binding_status": row.sf_binding_status,
                "sf_binding_verified_at": (
                    row.sf_binding_verified_at.isoformat()
                    if row.sf_binding_verified_at is not None else None
                ),
            }
            context = sha256(
                json.dumps(
                    context_facts,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            manual = request.manual_logistics_by_warehouse.get(warehouse_id)
            if manual is not None and manual.context != context:
                raise RentalAvailabilityInvalid("人工物流确认上下文已失效")
            if manual is not None:
                estimates[warehouse_id] = {
                    "warehouse_id": warehouse_id,
                    "status": "manual_confirmed",
                    "safe_failure_reason": None,
                    "logistics_days": manual.days,
                    "manual_confirmation_required": False,
                    "confirmation_context": context,
                }
                continue
            if (
                row.sf_binding_status == "active"
                and row.sf_binding_verified_at is not None
            ):
                failure_reason = "SF_ESTIMATOR_NOT_INSTALLED"
            elif row.sf_binding_status == "active":
                failure_reason = "SF_BINDING_UNVERIFIED"
            else:
                failure_reason = "SF_BINDING_UNAVAILABLE"
            estimates[warehouse_id] = {
                "warehouse_id": warehouse_id,
                "status": "unavailable",
                "safe_failure_reason": failure_reason,
                "logistics_days": None,
                "manual_confirmation_required": True,
                "confirmation_context": context,
            }
        return estimates

    @staticmethod
    def _accessory_counts(
        configs,
        *,
        units_by_scope,
        links_by_unit,
        warehouse_id: int,
        requested_type_ids: set[int],
        exclude_rental_id: int | None,
        relay_predecessor_ids: set[int],
        planned_ship_out_date: date | None,
        planned_return_date: date | None,
    ) -> list[dict[str, object]]:
        result = []
        if planned_ship_out_date is not None:
            reservation_start = datetime.combine(planned_ship_out_date, time.min)
            reservation_end = datetime.combine(
                planned_return_date + timedelta(days=1),
                time.min,
            )
        else:
            reservation_start = reservation_end = None
        for config in configs:
            base = {
                "accessory_type_id": config.accessory_type_id,
                "name": config.accessory_type_name,
                "display_name": config.accessory_display_name,
                "tracking_mode": config.tracking_mode,
                "requested": (
                    config.accessory_type_id in requested_type_ids
                ),
            }
            requested = config.accessory_type_id in requested_type_ids
            if config.tracking_mode != "logical_unit":
                result.append({
                    **base,
                    "total": None,
                    "reserved": None,
                    "available": None,
                    "availability_status": "device_bound",
                    "travels_with_device": False,
                    "fulfilled": requested,
                    "relay_confirmation_required": False,
                    "shortage": False,
                    "display_hint": (
                        "device_bound" if requested else "not_requested"
                    ),
                })
                continue
            units = units_by_scope[
                (warehouse_id, config.accessory_type_id)
            ]
            if reservation_start is None:
                result.append({
                    **base,
                    "total": len(units),
                    "reserved": None,
                    "available": None,
                    "availability_status": "logistics_confirmation_required",
                    "travels_with_device": False,
                    "fulfilled": False,
                    "relay_confirmation_required": False,
                    "shortage": False,
                    "display_hint": (
                        "logistics_confirmation_required"
                        if requested else "not_requested"
                    ),
                })
                continue
            available = 0
            already_fulfilled = False
            relay_candidate = False
            for unit in units:
                unit_links = links_by_unit[unit.id]
                own_link = any(
                    exclude_rental_id is not None
                    and link.rental_id == exclude_rental_id
                    for link in unit_links
                )
                if own_link:
                    already_fulfilled = True
                if (
                    unit.current_holder_rental_id
                    in relay_predecessor_ids
                ):
                    relay_candidate = True
                if (
                    unit.current_holder_rental_id is not None
                    and unit.current_holder_rental_id
                    != exclude_rental_id
                ):
                    continue
                if any(
                    link.rental_id != exclude_rental_id
                    and
                    link.reservation_start_at < reservation_end
                    and link.reservation_end_at > reservation_start
                    for link in unit_links
                ):
                    continue
                available += 1
            relay_confirmation_required = (
                requested and relay_candidate and not already_fulfilled
            )
            fulfilled = requested and (
                already_fulfilled
                or (available > 0 and not relay_confirmation_required)
            )
            shortage = (
                requested
                and available == 0
                and not already_fulfilled
                and not relay_candidate
            )
            if not requested:
                display_hint = "not_requested"
            elif already_fulfilled:
                display_hint = "already_fulfilled"
            elif relay_confirmation_required:
                display_hint = "relay_confirmation_required"
            elif available > 0:
                display_hint = "warehouse_available"
            else:
                display_hint = "shortage"
            result.append({
                **base,
                "total": len(units),
                "reserved": len(units) - available,
                "available": available,
                "availability_status": "evaluated",
                "travels_with_device": relay_candidate,
                "fulfilled": fulfilled,
                "relay_confirmation_required": (
                    relay_confirmation_required
                ),
                "shortage": shortage,
                "display_hint": display_hint,
            })
        return result


def _required_date(value: object, field_name: str) -> date:
    if not isinstance(value, str):
        raise RentalAvailabilityInvalid(f"{field_name} 格式错误")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise RentalAvailabilityInvalid(
            f"{field_name} 格式错误，请使用YYYY-MM-DD"
        ) from None


def _positive_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise RentalAvailabilityInvalid(f"{field_name} 必须是正整数")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise RentalAvailabilityInvalid(f"{field_name} 必须是正整数") from None
    if parsed < 1 or parsed > 2_147_483_647 or str(parsed) != str(value):
        raise RentalAvailabilityInvalid(f"{field_name} 必须是正整数")
    return parsed


def _optional_positive_integer(value: object, field_name: str) -> int | None:
    if value in (None, ""):
        return None
    return _positive_integer(value, field_name)


def _required_text(value: object, field_name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise RentalAvailabilityInvalid(f"{field_name} 不能为空")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > maximum
        or "\x00" in normalized
    ):
        raise RentalAvailabilityInvalid(f"{field_name} 不能为空或超出长度")
    return normalized


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


__all__ = [
    "RentalAvailabilityInput",
    "RentalAvailabilityInvalid",
    "RentalAvailabilityService",
    "parse_availability_input",
]
