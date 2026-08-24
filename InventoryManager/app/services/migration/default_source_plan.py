"""Deterministic, provider-free plans for the approved default-tenant source.

The builder reads already expanded tenant tables and emits immutable plans.  It
never writes, calls a provider or treats a child rental as authority.  Main
rental facts drive planned logistics and logical-accessory windows; exact child
facts remain source commitments so drift still fails closed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from types import MappingProxyType
from typing import Final, Mapping

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental
from app.services.scheduling.overlap_policy import ACTIVE_RENTAL_STATUSES
from inventory_control.default_migration import DefaultTenantMigrationManifest

from .logical_accessory_backfill import (
    LegacyAccessoryRequestEntry,
    LegacyAccessoryTypeEntry,
    LegacyAccessoryUnitEntry,
    LogicalAccessoryBackfillPlan,
)
from .planned_logistics_backfill import (
    PlannedLogisticsBackfillEntry,
    PlannedLogisticsBackfillPlan,
    PlannedLogisticsChildSourceFact,
    legacy_logistics_source_digest,
)
from .structured_address_backfill import (
    StructuredAddressBackfillPlan,
    StructuredRentalAddressEntry,
    UnavailableStructuredRentalAddressEntry,
    legacy_destination_digest,
)

DEFAULT_SOURCE_PLAN_POLICY_REVISION: Final = 1
LEGACY_NO_FACT_LOGISTICS_DAYS: Final = 1
PHONE_HOLDER_TYPE_ID: Final = 1
TRIPOD_TYPE_ID: Final = 2
_CHINESE_ADDRESS = re.compile(
    r"(?P<province>北京市|上海市|天津市|重庆市|"
    r"[\u4e00-\u9fff]{2,}(?:省|自治区))\s*"
    r"(?P<city>[\u4e00-\u9fff]{2,}(?:市|自治州|地区|盟))\s*"
    r"(?P<district>[\u4e00-\u9fff]{2,}(?:区|县|旗))\s*"
    r"(?P<detail>.+)$"
)


class DefaultSourcePlanError(RuntimeError):
    code = "DEFAULT_SOURCE_PLAN_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class DefaultSourcePlanAudit:
    active_main_rental_count: int
    logistics_source_counts: tuple[tuple[str, int], ...]
    structured_address_count: int
    unavailable_address_count: int
    logical_unit_count: int
    reliable_logical_unit_count: int
    unavailable_logical_unit_count: int
    logical_request_count: int
    linked_logical_request_count: int

    def __post_init__(self) -> None:
        values = (
            self.active_main_rental_count,
            self.structured_address_count,
            self.unavailable_address_count,
            self.logical_unit_count,
            self.reliable_logical_unit_count,
            self.unavailable_logical_unit_count,
            self.logical_request_count,
            self.linked_logical_request_count,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in values
        ):
            raise DefaultSourcePlanError()
        if (
            not isinstance(self.logistics_source_counts, tuple)
            or tuple(key for key, _ in self.logistics_source_counts)
            != ("legacy_ship_out", "legacy_ship_in", "scheduled_ship", "legacy_ui_1")
            or any(
                not isinstance(count, int) or isinstance(count, bool) or count < 0
                for _, count in self.logistics_source_counts
            )
            or sum(count for _, count in self.logistics_source_counts)
            != self.active_main_rental_count
            or self.structured_address_count + self.unavailable_address_count
            != self.active_main_rental_count
            or self.reliable_logical_unit_count + self.unavailable_logical_unit_count
            != self.logical_unit_count
            or self.linked_logical_request_count > self.logical_request_count
        ):
            raise DefaultSourcePlanError()

    @property
    def digest(self) -> bytes:
        return hashlib.sha256(
            json.dumps(
                dict(self.safe_summary()),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).digest()

    def safe_summary(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "active_main_rental_count": self.active_main_rental_count,
                "linked_logical_request_count": self.linked_logical_request_count,
                "logical_request_count": self.logical_request_count,
                "logical_unit_count": self.logical_unit_count,
                "logistics_source_counts": dict(self.logistics_source_counts),
                "policy_revision": DEFAULT_SOURCE_PLAN_POLICY_REVISION,
                "reliable_logical_unit_count": self.reliable_logical_unit_count,
                "structured_address_count": self.structured_address_count,
                "unavailable_address_count": self.unavailable_address_count,
                "unavailable_logical_unit_count": (self.unavailable_logical_unit_count),
            }
        )


@dataclass(frozen=True, slots=True)
class DefaultSourceBackfillPlans:
    planned_logistics: PlannedLogisticsBackfillPlan
    structured_addresses: StructuredAddressBackfillPlan
    logical_accessories: LogicalAccessoryBackfillPlan
    audit: DefaultSourcePlanAudit

    @property
    def digest(self) -> bytes:
        return hashlib.sha256(
            self.planned_logistics.digest
            + self.structured_addresses.digest
            + self.logical_accessories.digest
            + self.audit.digest
        ).digest()


class DefaultSourceBackfillPlanBuilder:
    """Compile the approved main-authoritative policy from exact source rows."""

    def build(
        self,
        session: Session,
        *,
        manifest: DefaultTenantMigrationManifest,
        expected_warehouse_id: int,
    ) -> DefaultSourceBackfillPlans:
        if (
            not isinstance(session, Session)
            or not isinstance(manifest, DefaultTenantMigrationManifest)
            or isinstance(expected_warehouse_id, bool)
            or not isinstance(expected_warehouse_id, int)
            or expected_warehouse_id < 1
        ):
            raise DefaultSourcePlanError()
        mains = tuple(
            session.scalars(
                sa.select(Rental)
                .where(
                    Rental.parent_rental_id.is_(None),
                    Rental.status.in_(tuple(sorted(ACTIVE_RENTAL_STATUSES))),
                )
                .order_by(Rental.id)
            )
        )
        if not mains:
            raise DefaultSourcePlanError()
        main_by_id = {item.id: item for item in mains}
        children = tuple(
            session.scalars(
                sa.select(Rental)
                .where(Rental.parent_rental_id.in_(tuple(main_by_id)))
                .order_by(Rental.parent_rental_id, Rental.id)
            )
        )
        children_by_parent: dict[int, list[Rental]] = {item.id: [] for item in mains}
        for child in children:
            children_by_parent[child.parent_rental_id].append(child)

        logistics_entries: list[PlannedLogisticsBackfillEntry] = []
        logistics_sources = {
            "legacy_ship_out": 0,
            "legacy_ship_in": 0,
            "scheduled_ship": 0,
            "legacy_ui_1": 0,
        }
        logistics_by_main: dict[int, int] = {}
        for main in mains:
            logistics_days, source = _derive_logistics_days(main)
            logistics_sources[source] += 1
            logistics_by_main[main.id] = logistics_days
            source_children = tuple(children_by_parent[main.id])
            logistics_entries.append(
                PlannedLogisticsBackfillEntry(
                    rental_id=main.id,
                    expected_device_id=main.device_id,
                    expected_start_date=main.start_date,
                    expected_end_date=main.end_date,
                    expected_status=_status(main.status),
                    logistics_days=logistics_days,
                    expected_child_rental_ids=tuple(
                        child.id for child in source_children
                    ),
                    child_fact_authority="main_rental",
                    expected_child_source_facts=tuple(
                        PlannedLogisticsChildSourceFact(
                            rental_id=child.id,
                            expected_device_id=child.device_id,
                            expected_start_date=child.start_date,
                            expected_end_date=child.end_date,
                            expected_status=_status(child.status),
                        )
                        for child in source_children
                    ),
                    expected_legacy_logistics_digest=(
                        legacy_logistics_source_digest(
                            ship_out_time=main.ship_out_time,
                            ship_in_time=main.ship_in_time,
                            scheduled_ship_time=main.scheduled_ship_time,
                        )
                    ),
                )
            )
        logistics_plan = PlannedLogisticsBackfillPlan(
            parent_manifest_digest=manifest.digest,
            migration_idempotency_key=manifest.migration_idempotency_key,
            entries=tuple(logistics_entries),
        )

        address_entries: list[StructuredRentalAddressEntry] = []
        unavailable_addresses: list[UnavailableStructuredRentalAddressEntry] = []
        for main in mains:
            parsed = _parse_structured_address(main.destination)
            if parsed is None:
                unavailable_addresses.append(
                    UnavailableStructuredRentalAddressEntry(
                        rental_id=main.id,
                        expected_parent_rental_id=None,
                        expected_legacy_destination_digest=(
                            legacy_destination_digest(main.destination)
                        ),
                        reason=(
                            "blank"
                            if not isinstance(main.destination, str)
                            or not main.destination.strip()
                            else "unparseable"
                        ),
                    )
                )
                continue
            address_entries.append(
                StructuredRentalAddressEntry(
                    rental_id=main.id,
                    expected_parent_rental_id=None,
                    expected_legacy_destination_digest=(
                        legacy_destination_digest(main.destination)
                    ),
                    province=parsed[0],
                    city=parsed[1],
                    district=parsed[2],
                    address_detail=parsed[3],
                )
            )
        address_plan = StructuredAddressBackfillPlan(
            parent_manifest_digest=manifest.digest,
            migration_idempotency_key=manifest.migration_idempotency_key,
            entries=tuple(address_entries),
            unavailable_entries=tuple(unavailable_addresses),
        )

        devices = tuple(
            session.execute(
                sa.select(Device, DeviceModel.name)
                .outerjoin(DeviceModel, DeviceModel.id == Device.model_id)
                .where(Device.is_accessory.is_(True))
                .order_by(Device.id)
            )
        )
        logical_device_type: dict[int, int] = {}
        device_by_id: dict[int, Device] = {}
        for device, model_name in devices:
            type_id = _logical_type_id(device, model_name)
            if type_id is None:
                continue
            if device.warehouse_id != expected_warehouse_id:
                raise DefaultSourcePlanError()
            logical_device_type[device.id] = type_id
            device_by_id[device.id] = device
        if not logical_device_type:
            raise DefaultSourcePlanError()
        logical_children = tuple(
            session.scalars(
                sa.select(Rental)
                .where(
                    Rental.parent_rental_id.is_not(None),
                    Rental.status.in_(tuple(sorted(ACTIVE_RENTAL_STATUSES))),
                    Rental.device_id.in_(tuple(sorted(logical_device_type))),
                )
                .order_by(Rental.id)
            )
        )
        request_children_by_device: dict[int, list[Rental]] = {
            item: [] for item in logical_device_type
        }
        for child in logical_children:
            if child.parent_rental_id not in main_by_id:
                raise DefaultSourcePlanError()
            request_children_by_device[child.device_id].append(child)

        reliable_by_device = {
            device_id: _unit_is_reliable(
                device=device_by_id[device_id],
                children=tuple(request_children_by_device[device_id]),
                main_by_id=main_by_id,
                logistics_by_main=logistics_by_main,
            )
            for device_id in logical_device_type
        }
        units = tuple(
            LegacyAccessoryUnitEntry(
                legacy_device_id=device_id,
                accessory_type_id=logical_device_type[device_id],
                expected_warehouse_id=expected_warehouse_id,
                expected_lifecycle_status=_status(
                    device_by_id[device_id].lifecycle_status
                ),
                reliable_and_available=reliable_by_device[device_id],
            )
            for device_id in sorted(logical_device_type)
        )
        requests = tuple(
            LegacyAccessoryRequestEntry(
                child_rental_id=child.id,
                main_rental_id=child.parent_rental_id,
                accessory_type_id=logical_device_type[child.device_id],
                linked_legacy_device_id=(
                    child.device_id if reliable_by_device[child.device_id] else None
                ),
                expected_child_device_id=child.device_id,
                expected_child_start_date=child.start_date,
                expected_child_end_date=child.end_date,
                expected_child_status=_status(child.status),
            )
            for child in logical_children
        )
        accessory_plan = LogicalAccessoryBackfillPlan(
            parent_manifest_digest=manifest.digest,
            migration_idempotency_key=manifest.migration_idempotency_key,
            types=(
                LegacyAccessoryTypeEntry(
                    accessory_type_id=PHONE_HOLDER_TYPE_ID,
                    name="phone_holder",
                    display_name="手机支架",
                    display_order=10,
                ),
                LegacyAccessoryTypeEntry(
                    accessory_type_id=TRIPOD_TYPE_ID,
                    name="tripod",
                    display_name="三脚架",
                    display_order=20,
                ),
            ),
            units=units,
            requests=requests,
            child_fact_authority="main_rental",
        )
        reliable_units = sum(reliable_by_device.values())
        audit = DefaultSourcePlanAudit(
            active_main_rental_count=len(mains),
            logistics_source_counts=tuple(logistics_sources.items()),
            structured_address_count=len(address_entries),
            unavailable_address_count=len(unavailable_addresses),
            logical_unit_count=len(units),
            reliable_logical_unit_count=reliable_units,
            unavailable_logical_unit_count=len(units) - reliable_units,
            logical_request_count=len(requests),
            linked_logical_request_count=sum(
                item.linked_legacy_device_id is not None for item in requests
            ),
        )
        return DefaultSourceBackfillPlans(
            planned_logistics=logistics_plan,
            structured_addresses=address_plan,
            logical_accessories=accessory_plan,
            audit=audit,
        )


def _derive_logistics_days(rental: Rental) -> tuple[int, str]:
    candidates = (
        (
            _days_before(rental.start_date, rental.ship_out_time),
            "legacy_ship_out",
        ),
        (
            _days_after(rental.end_date, rental.ship_in_time),
            "legacy_ship_in",
        ),
        (
            _days_before(rental.start_date, rental.scheduled_ship_time),
            "scheduled_ship",
        ),
    )
    for value, source in candidates:
        if value is not None and 0 <= value <= 7:
            return value, source
    return LEGACY_NO_FACT_LOGISTICS_DAYS, "legacy_ui_1"


def _days_before(start_date: date, value: datetime | None) -> int | None:
    if value is None:
        return None
    return (start_date - value.date()).days - 1


def _days_after(end_date: date, value: datetime | None) -> int | None:
    if value is None:
        return None
    return (value.date() - end_date).days - 1


def _parse_structured_address(
    destination: str | None,
) -> tuple[str, str, str, str] | None:
    if not isinstance(destination, str) or not destination.strip():
        return None
    raw = destination.strip()
    matched = _CHINESE_ADDRESS.search(raw)
    if matched is None:
        return None
    parts = tuple(
        matched.group(name).strip()
        for name in (
            "province",
            "city",
            "district",
            "detail",
        )
    )
    if not all(parts):
        return None
    province, city, district, detail = parts
    return province, city, district, detail


def _logical_type_id(device: Device, model_name: object) -> int | None:
    searchable = "|".join(
        value
        for value in (model_name, device.model, device.name)
        if isinstance(value, str)
    )
    if "手机支架" in searchable:
        return PHONE_HOLDER_TYPE_ID
    if "三脚架" in searchable:
        return TRIPOD_TYPE_ID
    return None


def _unit_is_reliable(
    *,
    device: Device,
    children: tuple[Rental, ...],
    main_by_id: Mapping[int, Rental],
    logistics_by_main: Mapping[int, int],
) -> bool:
    if _status(device.lifecycle_status) != "active":
        return False
    holders = sum(
        _status(child.status) in {"shipped", "returned"} for child in children
    )
    if holders > 1:
        return False
    windows = []
    for child in children:
        main = main_by_id[child.parent_rental_id]
        days = logistics_by_main[main.id]
        windows.append(
            (
                datetime.combine(
                    main.start_date - timedelta(days=days + 1),
                    time.min,
                ),
                datetime.combine(
                    main.end_date + timedelta(days=days + 2),
                    time.min,
                ),
            )
        )
    windows.sort()
    return all(
        current[0] >= previous[1]
        for previous, current in zip(windows, windows[1:], strict=False)
    )


def _status(value: object) -> str:
    if hasattr(value, "value"):
        value = value.value
    if not isinstance(value, str) or not value:
        raise DefaultSourcePlanError()
    return value


__all__ = [
    "DEFAULT_SOURCE_PLAN_POLICY_REVISION",
    "DefaultSourceBackfillPlanBuilder",
    "DefaultSourceBackfillPlans",
    "DefaultSourcePlanAudit",
    "DefaultSourcePlanError",
    "LEGACY_NO_FACT_LOGISTICS_DAYS",
    "PHONE_HOLDER_TYPE_ID",
    "TRIPOD_TYPE_ID",
]
