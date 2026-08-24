"""Explicit, idempotent legacy-device to logical-accessory backfill."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable
from uuid import UUID, uuid5

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.accessory_inventory import (
    AccessoryType,
    AccessoryUnit,
    AccessoryUnitEvent,
    RentalAccessoryRequest,
    RentalAccessoryUnitLink,
)
from app.models.database_identity import TenantDatabaseIdentity
from app.models.device import Device
from app.models.rental import Rental
from app.services.scheduling.overlap_policy import ACTIVE_RENTAL_STATUSES
from inventory_control.default_migration import DefaultTenantMigrationManifest
from inventory_control.transactions import require_caller_transaction

_UNIT_DOMAIN = "inventory-manager/default-accessory-unit/v1/"
_LINK_DOMAIN = "inventory-manager/default-accessory-link/v1/"


class LogicalAccessoryBackfillError(RuntimeError):
    code = "LOGICAL_ACCESSORY_BACKFILL_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class LogicalAccessoryBackfillInputError(LogicalAccessoryBackfillError):
    code = "LOGICAL_ACCESSORY_BACKFILL_INPUT_INVALID"


class LogicalAccessoryBackfillTransactionError(LogicalAccessoryBackfillError):
    code = "LOGICAL_ACCESSORY_BACKFILL_TRANSACTION_INVALID"


class LogicalAccessoryBackfillIdentityMismatchError(LogicalAccessoryBackfillError):
    code = "LOGICAL_ACCESSORY_BACKFILL_IDENTITY_MISMATCH"


class LogicalAccessoryBackfillConflictError(LogicalAccessoryBackfillError):
    code = "LOGICAL_ACCESSORY_BACKFILL_CONFLICT"


class LogicalAccessoryBackfillPersistenceError(LogicalAccessoryBackfillError):
    code = "LOGICAL_ACCESSORY_BACKFILL_PERSISTENCE_FAILED"


@dataclass(frozen=True, slots=True, kw_only=True)
class LegacyAccessoryTypeEntry:
    accessory_type_id: int
    name: str
    display_name: str
    display_order: int

    def __post_init__(self) -> None:
        _positive(self.accessory_type_id)
        if (
            not isinstance(self.name, str)
            or not self.name.strip()
            or len(self.name.strip()) > 100
            or not isinstance(self.display_name, str)
            or not self.display_name.strip()
            or len(self.display_name.strip()) > 100
            or isinstance(self.display_order, bool)
            or not isinstance(self.display_order, int)
            or self.display_order < 0
        ):
            raise LogicalAccessoryBackfillInputError()
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "display_name", self.display_name.strip())


@dataclass(frozen=True, slots=True, kw_only=True)
class LegacyAccessoryUnitEntry:
    legacy_device_id: int
    accessory_type_id: int
    expected_warehouse_id: int
    expected_lifecycle_status: str
    reliable_and_available: bool

    def __post_init__(self) -> None:
        for value in (
            self.legacy_device_id,
            self.accessory_type_id,
            self.expected_warehouse_id,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise LogicalAccessoryBackfillInputError()
        if (
            self.expected_lifecycle_status
            not in {"active", "sold", "decommissioned", "damaged", "retired"}
            or not isinstance(self.reliable_and_available, bool)
            or (
                self.reliable_and_available
                and self.expected_lifecycle_status != "active"
            )
        ):
            raise LogicalAccessoryBackfillInputError()

    @property
    def target_condition_status(self) -> str:
        return "active" if self.reliable_and_available else "maintenance"


@dataclass(frozen=True, slots=True, kw_only=True)
class LegacyAccessoryRequestEntry:
    child_rental_id: int
    main_rental_id: int
    accessory_type_id: int
    linked_legacy_device_id: int | None
    expected_child_device_id: int | None = None
    expected_child_start_date: date | None = None
    expected_child_end_date: date | None = None
    expected_child_status: str | None = None

    def __post_init__(self) -> None:
        for value in (
            self.child_rental_id,
            self.main_rental_id,
            self.accessory_type_id,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise LogicalAccessoryBackfillInputError()
        if self.child_rental_id == self.main_rental_id:
            raise LogicalAccessoryBackfillInputError()
        if self.linked_legacy_device_id is not None and (
            isinstance(self.linked_legacy_device_id, bool)
            or not isinstance(self.linked_legacy_device_id, int)
            or self.linked_legacy_device_id < 1
        ):
            raise LogicalAccessoryBackfillInputError()
        source_values = (
            self.expected_child_device_id,
            self.expected_child_start_date,
            self.expected_child_end_date,
            self.expected_child_status,
        )
        if any(value is not None for value in source_values):
            if (
                isinstance(self.expected_child_device_id, bool)
                or not isinstance(self.expected_child_device_id, int)
                or self.expected_child_device_id < 1
                or not isinstance(self.expected_child_start_date, date)
                or not isinstance(self.expected_child_end_date, date)
                or self.expected_child_start_date > self.expected_child_end_date
                or self.expected_child_status not in ACTIVE_RENTAL_STATUSES
            ):
                raise LogicalAccessoryBackfillInputError()


@dataclass(frozen=True, slots=True, kw_only=True)
class LogicalAccessoryBackfillPlan:
    parent_manifest_digest: bytes
    migration_idempotency_key: str
    units: tuple[LegacyAccessoryUnitEntry, ...]
    requests: tuple[LegacyAccessoryRequestEntry, ...]
    types: tuple[LegacyAccessoryTypeEntry, ...] = ()
    child_fact_authority: str = "strict_match"
    policy_revision: int = 2

    def __post_init__(self) -> None:
        if (
            not isinstance(self.parent_manifest_digest, bytes)
            or len(self.parent_manifest_digest) != 32
            or not isinstance(self.migration_idempotency_key, str)
            or not self.migration_idempotency_key
            or self.policy_revision != 2
            or not isinstance(self.units, tuple)
            or not self.units
            or not all(
                isinstance(item, LegacyAccessoryUnitEntry) for item in self.units
            )
            or not isinstance(self.requests, tuple)
            or not all(
                isinstance(item, LegacyAccessoryRequestEntry) for item in self.requests
            )
            or not isinstance(self.types, tuple)
            or not all(
                isinstance(item, LegacyAccessoryTypeEntry) for item in self.types
            )
            or self.child_fact_authority not in {"strict_match", "main_rental"}
        ):
            raise LogicalAccessoryBackfillInputError()
        unit_ids = tuple(item.legacy_device_id for item in self.units)
        request_ids = tuple(item.child_rental_id for item in self.requests)
        type_ids = tuple(item.accessory_type_id for item in self.types)
        type_names = tuple(item.name for item in self.types)
        if (
            unit_ids != tuple(sorted(set(unit_ids)))
            or request_ids != tuple(sorted(set(request_ids)))
            or type_ids != tuple(sorted(set(type_ids)))
            or len(type_names) != len(set(type_names))
        ):
            raise LogicalAccessoryBackfillInputError()
        units_by_device = {item.legacy_device_id: item for item in self.units}
        request_identity = tuple(
            (item.main_rental_id, item.accessory_type_id) for item in self.requests
        )
        if len(request_identity) != len(set(request_identity)):
            raise LogicalAccessoryBackfillInputError()
        for request in self.requests:
            source_values = (
                request.expected_child_device_id,
                request.expected_child_start_date,
                request.expected_child_end_date,
                request.expected_child_status,
            )
            if self.child_fact_authority == "strict_match" and any(
                value is not None for value in source_values
            ):
                raise LogicalAccessoryBackfillInputError()
            if self.child_fact_authority == "main_rental" and any(
                value is None for value in source_values
            ):
                raise LogicalAccessoryBackfillInputError()
            if request.linked_legacy_device_id is None:
                continue
            unit = units_by_device.get(request.linked_legacy_device_id)
            if unit is None or unit.accessory_type_id != request.accessory_type_id:
                raise LogicalAccessoryBackfillInputError()

    @property
    def digest(self) -> bytes:
        return hashlib.sha256(self.canonical_bytes()).digest()

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            {
                "migration_idempotency_key": self.migration_idempotency_key,
                "parent_manifest_digest": self.parent_manifest_digest.hex(),
                "policy_revision": self.policy_revision,
                "child_fact_authority": self.child_fact_authority,
                "requests": [
                    {
                        "accessory_type_id": item.accessory_type_id,
                        "child_rental_id": item.child_rental_id,
                        "linked_legacy_device_id": item.linked_legacy_device_id,
                        "main_rental_id": item.main_rental_id,
                        "expected_child_device_id": item.expected_child_device_id,
                        "expected_child_end_date": (
                            None
                            if item.expected_child_end_date is None
                            else item.expected_child_end_date.isoformat()
                        ),
                        "expected_child_start_date": (
                            None
                            if item.expected_child_start_date is None
                            else item.expected_child_start_date.isoformat()
                        ),
                        "expected_child_status": item.expected_child_status,
                    }
                    for item in self.requests
                ],
                "units": [
                    {
                        "accessory_type_id": item.accessory_type_id,
                        "expected_lifecycle_status": (item.expected_lifecycle_status),
                        "expected_warehouse_id": item.expected_warehouse_id,
                        "legacy_device_id": item.legacy_device_id,
                        "reliable_and_available": item.reliable_and_available,
                    }
                    for item in self.units
                ],
                "types": [
                    {
                        "accessory_type_id": item.accessory_type_id,
                        "display_name": item.display_name,
                        "display_order": item.display_order,
                        "name": item.name,
                        "tracking_mode": "logical_unit",
                    }
                    for item in self.types
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")


@dataclass(frozen=True, slots=True, kw_only=True)
class LogicalAccessoryBackfillResult:
    plan_digest: bytes
    result_digest: bytes
    unit_count: int
    request_count: int
    link_count: int
    holder_count: int
    created_event_count: int
    linked_event_count: int
    dispatched_event_count: int
    created_fact_count: int
    idempotent_replay: bool


class LogicalAccessoryBackfillService:
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        if clock is not None and not callable(clock):
            raise TypeError("clock is invalid")
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def backfill(
        self,
        session: Session,
        *,
        manifest: DefaultTenantMigrationManifest,
        expected_schema_generation: int,
        plan: LogicalAccessoryBackfillPlan,
    ) -> LogicalAccessoryBackfillResult:
        if (
            not isinstance(manifest, DefaultTenantMigrationManifest)
            or not isinstance(plan, LogicalAccessoryBackfillPlan)
            or plan.parent_manifest_digest != manifest.digest
            or plan.migration_idempotency_key != manifest.migration_idempotency_key
        ):
            raise LogicalAccessoryBackfillInputError()
        generation = _positive(expected_schema_generation)
        require_caller_transaction(
            session,
            LogicalAccessoryBackfillTransactionError,
        )
        now = _naive_utc(self._clock())
        created_facts = 0
        try:
            _require_identity(session, manifest=manifest, generation=generation)
            for type_entry in plan.types:
                existing_type = session.scalar(
                    sa.select(AccessoryType)
                    .where(
                        sa.or_(
                            AccessoryType.id == type_entry.accessory_type_id,
                            AccessoryType.name == type_entry.name,
                        )
                    )
                    .with_for_update()
                )
                if existing_type is None:
                    existing_type = AccessoryType(
                        id=type_entry.accessory_type_id,
                        name=type_entry.name,
                        display_name=type_entry.display_name,
                        tracking_mode="logical_unit",
                        is_active=True,
                        display_order=type_entry.display_order,
                    )
                    session.add(existing_type)
                    session.flush()
                    created_facts += 1
                elif (
                    existing_type.id != type_entry.accessory_type_id
                    or existing_type.name != type_entry.name
                    or existing_type.display_name != type_entry.display_name
                    or existing_type.tracking_mode != "logical_unit"
                    or existing_type.is_active is not True
                    or existing_type.display_order != type_entry.display_order
                ):
                    raise LogicalAccessoryBackfillConflictError()
            unit_types = {item.accessory_type_id for item in plan.units}
            types = tuple(
                session.scalars(
                    sa.select(AccessoryType)
                    .where(AccessoryType.id.in_(tuple(sorted(unit_types))))
                    .order_by(AccessoryType.id)
                    .with_for_update()
                )
            )
            types_by_id = {item.id: item for item in types}
            if set(types_by_id) != unit_types or any(
                item.tracking_mode != "logical_unit" for item in types
            ):
                raise LogicalAccessoryBackfillConflictError()

            devices = tuple(
                session.scalars(
                    sa.select(Device)
                    .where(
                        Device.id.in_(
                            tuple(item.legacy_device_id for item in plan.units)
                        )
                    )
                    .order_by(Device.id)
                    .with_for_update()
                )
            )
            devices_by_id = {item.id: item for item in devices}
            if set(devices_by_id) != {item.legacy_device_id for item in plan.units}:
                raise LogicalAccessoryBackfillConflictError()

            incomplete_children = tuple(
                session.scalars(
                    sa.select(Rental)
                    .where(
                        Rental.parent_rental_id.is_not(None),
                        Rental.status.in_(tuple(sorted(ACTIVE_RENTAL_STATUSES))),
                        Rental.device_id.in_(tuple(sorted(devices_by_id))),
                    )
                    .order_by(Rental.id)
                    .with_for_update()
                )
            )
            if tuple(item.id for item in incomplete_children) != tuple(
                item.child_rental_id for item in plan.requests
            ):
                raise LogicalAccessoryBackfillConflictError()
            main_ids = tuple(sorted({item.main_rental_id for item in plan.requests}))
            mains = tuple(
                session.scalars(
                    sa.select(Rental)
                    .where(Rental.id.in_(main_ids))
                    .order_by(Rental.id)
                    .with_for_update()
                )
            )
            mains_by_id = {item.id: item for item in mains}
            if set(mains_by_id) != set(main_ids):
                raise LogicalAccessoryBackfillConflictError()

            units_by_device: dict[int, AccessoryUnit] = {}
            for entry in plan.units:
                device = devices_by_id[entry.legacy_device_id]
                if (
                    device.is_accessory is not True
                    or device.warehouse_id != entry.expected_warehouse_id
                    or device.lifecycle_status != entry.expected_lifecycle_status
                ):
                    raise LogicalAccessoryBackfillConflictError()
                unit_id = str(
                    uuid5(
                        manifest.database_uuid,
                        f"{_UNIT_DOMAIN}{entry.legacy_device_id}",
                    )
                )
                existing = session.scalar(
                    sa.select(AccessoryUnit)
                    .where(
                        sa.or_(
                            AccessoryUnit.id == unit_id,
                            sa.and_(
                                AccessoryUnit.legacy_source_type == "device",
                                AccessoryUnit.legacy_source_id
                                == str(entry.legacy_device_id),
                            ),
                        )
                    )
                    .with_for_update()
                )
                if existing is None:
                    existing = AccessoryUnit(
                        id=unit_id,
                        accessory_type_id=entry.accessory_type_id,
                        warehouse_id=entry.expected_warehouse_id,
                        current_holder_rental_id=None,
                        condition_status=entry.target_condition_status,
                        legacy_source_type="device",
                        legacy_source_id=str(entry.legacy_device_id),
                        row_version=1,
                    )
                    session.add(existing)
                    session.flush()
                    created_facts += 1
                elif (
                    existing.id != unit_id
                    or existing.accessory_type_id != entry.accessory_type_id
                    or existing.warehouse_id != entry.expected_warehouse_id
                    or existing.condition_status != entry.target_condition_status
                    or existing.legacy_source_type != "device"
                    or existing.legacy_source_id != str(entry.legacy_device_id)
                ):
                    raise LogicalAccessoryBackfillConflictError()
                units_by_device[entry.legacy_device_id] = existing
                created_facts += _ensure_event(
                    session,
                    manifest=manifest,
                    unit=existing,
                    event_type="created",
                    rental=None,
                    now=now,
                )

            holders: dict[str, int] = {}
            for request_entry, child in zip(
                plan.requests,
                incomplete_children,
                strict=True,
            ):
                main = mains_by_id[request_entry.main_rental_id]
                if (
                    child.parent_rental_id != main.id
                    or main.parent_rental_id is not None
                    or main.status not in ACTIVE_RENTAL_STATUSES
                    or main.planned_ship_out_date is None
                    or main.planned_return_date is None
                    or main.logistics_days is None
                ):
                    raise LogicalAccessoryBackfillConflictError()
                if self._child_source_conflicts(
                    plan=plan,
                    request=request_entry,
                    child=child,
                    main=main,
                ):
                    raise LogicalAccessoryBackfillConflictError()
                accessory_type = types_by_id[request_entry.accessory_type_id]
                request = session.get(
                    RentalAccessoryRequest,
                    {
                        "rental_id": main.id,
                        "accessory_type_id": request_entry.accessory_type_id,
                    },
                )
                if request is None:
                    request = RentalAccessoryRequest(
                        rental_id=main.id,
                        accessory_type_id=request_entry.accessory_type_id,
                        name_snapshot=accessory_type.display_name,
                    )
                    session.add(request)
                    session.flush()
                    created_facts += 1
                elif request.name_snapshot != accessory_type.display_name:
                    raise LogicalAccessoryBackfillConflictError()

                if request_entry.linked_legacy_device_id is None:
                    source_unit = units_by_device.get(child.device_id)
                    if child.status in {"shipped", "returned"} and (
                        source_unit is None
                        or source_unit.condition_status != "maintenance"
                    ):
                        raise LogicalAccessoryBackfillConflictError()
                    continue
                unit = units_by_device[request_entry.linked_legacy_device_id]
                if unit.condition_status != "active":
                    raise LogicalAccessoryBackfillConflictError()
                link_id = str(
                    uuid5(
                        manifest.database_uuid,
                        f"{_LINK_DOMAIN}{child.id}",
                    )
                )
                start_at = datetime.combine(
                    main.planned_ship_out_date,
                    time.min,
                )
                end_at = datetime.combine(
                    main.planned_return_date + timedelta(days=1),
                    time.min,
                )
                link = session.scalar(
                    sa.select(RentalAccessoryUnitLink)
                    .where(
                        sa.or_(
                            RentalAccessoryUnitLink.id == link_id,
                            sa.and_(
                                RentalAccessoryUnitLink.rental_id == main.id,
                                RentalAccessoryUnitLink.accessory_type_id
                                == request_entry.accessory_type_id,
                            ),
                        )
                    )
                    .with_for_update()
                )
                if link is None:
                    link = RentalAccessoryUnitLink(
                        id=link_id,
                        rental_id=main.id,
                        accessory_type_id=request_entry.accessory_type_id,
                        accessory_unit_id=unit.id,
                        reservation_start_at=start_at,
                        reservation_end_at=end_at,
                        source_relay_case_id=None,
                    )
                    session.add(link)
                    session.flush()
                    created_facts += 1
                elif (
                    link.id != link_id
                    or link.accessory_unit_id != unit.id
                    or link.reservation_start_at != start_at
                    or link.reservation_end_at != end_at
                    or link.source_relay_case_id is not None
                ):
                    raise LogicalAccessoryBackfillConflictError()
                created_facts += _ensure_event(
                    session,
                    manifest=manifest,
                    unit=unit,
                    event_type="linked",
                    rental=main,
                    now=now,
                )
                if child.status in {"shipped", "returned"}:
                    prior = holders.setdefault(unit.id, main.id)
                    if prior != main.id:
                        raise LogicalAccessoryBackfillConflictError()

            for unit in units_by_device.values():
                expected_holder = holders.get(unit.id)
                if unit.current_holder_rental_id not in {None, expected_holder}:
                    raise LogicalAccessoryBackfillConflictError()
                if expected_holder is not None:
                    unit.current_holder_rental_id = expected_holder
                    main = mains_by_id[expected_holder]
                    created_facts += _ensure_event(
                        session,
                        manifest=manifest,
                        unit=unit,
                        event_type="dispatched",
                        rental=main,
                        now=now,
                    )
            session.flush()
        except LogicalAccessoryBackfillError:
            raise
        except IntegrityError:
            raise LogicalAccessoryBackfillConflictError() from None
        except SQLAlchemyError:
            raise LogicalAccessoryBackfillPersistenceError() from None

        counts = {
            "created": _event_count(session, plan, manifest, "created"),
            "dispatched": _event_count(session, plan, manifest, "dispatched"),
            "linked": _event_count(session, plan, manifest, "linked"),
        }
        link_count = sum(
            item.linked_legacy_device_id is not None for item in plan.requests
        )
        holder_count = len(holders)
        result_payload = {
            "created_events": counts["created"],
            "dispatched_events": counts["dispatched"],
            "holders": holder_count,
            "linked_events": counts["linked"],
            "links": link_count,
            "requests": len(plan.requests),
            "units": len(plan.units),
        }
        return LogicalAccessoryBackfillResult(
            plan_digest=plan.digest,
            result_digest=hashlib.sha256(
                json.dumps(
                    result_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("ascii")
            ).digest(),
            unit_count=len(plan.units),
            request_count=len(plan.requests),
            link_count=link_count,
            holder_count=holder_count,
            created_event_count=counts["created"],
            linked_event_count=counts["linked"],
            dispatched_event_count=counts["dispatched"],
            created_fact_count=created_facts,
            idempotent_replay=created_facts == 0,
        )

    @staticmethod
    def _child_source_conflicts(
        *,
        plan: LogicalAccessoryBackfillPlan,
        request: LegacyAccessoryRequestEntry,
        child: Rental,
        main: Rental,
    ) -> bool:
        if plan.child_fact_authority == "strict_match":
            return (
                child.device_id
                != (
                    request.linked_legacy_device_id
                    if request.linked_legacy_device_id is not None
                    else child.device_id
                )
                or child.start_date != main.start_date
                or child.end_date != main.end_date
                or child.status != main.status
            )
        return (
            child.device_id != request.expected_child_device_id
            or child.start_date != request.expected_child_start_date
            or child.end_date != request.expected_child_end_date
            or child.status != request.expected_child_status
        )


def _require_identity(
    session: Session,
    *,
    manifest: DefaultTenantMigrationManifest,
    generation: int,
) -> None:
    identities = tuple(
        session.scalars(
            sa.select(TenantDatabaseIdentity)
            .order_by(TenantDatabaseIdentity.singleton_key)
            .with_for_update()
        )
    )
    if len(identities) != 1:
        raise LogicalAccessoryBackfillIdentityMismatchError()
    identity = identities[0]
    if (
        identity.singleton_key != 1
        or identity.tenant_id != str(manifest.tenant_uuid)
        or identity.database_uuid != str(manifest.database_uuid)
        or identity.schema_generation != generation
    ):
        raise LogicalAccessoryBackfillIdentityMismatchError()


def _ensure_event(
    session: Session,
    *,
    manifest: DefaultTenantMigrationManifest,
    unit: AccessoryUnit,
    event_type: str,
    rental: Rental | None,
    now: datetime,
) -> int:
    key = _event_key(
        manifest,
        event_type=event_type,
        unit_id=unit.id,
        rental_id=None if rental is None else rental.id,
    )
    event = session.scalar(
        sa.select(AccessoryUnitEvent)
        .where(AccessoryUnitEvent.idempotency_key == key)
        .with_for_update()
    )
    if event is None:
        event = AccessoryUnitEvent(
            unit_id=unit.id,
            event_type=event_type,
            main_device_id=None if rental is None else rental.device_id,
            rental_id=None if rental is None else rental.id,
            relay_case_id=None,
            from_warehouse_id=None,
            to_warehouse_id=(unit.warehouse_id if event_type == "created" else None),
            from_holder_rental_id=None,
            to_holder_rental_id=(
                rental.id if event_type == "dispatched" and rental else None
            ),
            actor_type="migration",
            actor_id=None,
            reason="migration",
            note=None,
            idempotency_key=key,
            occurred_at=now,
        )
        session.add(event)
        session.flush()
        return 1
    if (
        event.unit_id != unit.id
        or event.event_type != event_type
        or event.rental_id != (None if rental is None else rental.id)
        or event.reason != "migration"
        or event.actor_type != "migration"
    ):
        raise LogicalAccessoryBackfillConflictError()
    return 0


def _event_key(
    manifest: DefaultTenantMigrationManifest,
    *,
    event_type: str,
    unit_id: str,
    rental_id: int | None,
) -> str:
    payload = (
        manifest.digest
        + event_type.encode("ascii")
        + UUID(unit_id).bytes
        + str(rental_id or 0).encode("ascii")
    )
    return f"migration:{hashlib.sha256(payload).hexdigest()}"


def _event_count(
    session: Session,
    plan: LogicalAccessoryBackfillPlan,
    manifest: DefaultTenantMigrationManifest,
    event_type: str,
) -> int:
    unit_ids = tuple(
        str(
            uuid5(
                manifest.database_uuid,
                f"{_UNIT_DOMAIN}{item.legacy_device_id}",
            )
        )
        for item in plan.units
    )
    return int(
        session.scalar(
            sa.select(sa.func.count())
            .select_from(AccessoryUnitEvent)
            .where(
                AccessoryUnitEvent.unit_id.in_(unit_ids),
                AccessoryUnitEvent.event_type == event_type,
                AccessoryUnitEvent.reason == "migration",
            )
        )
        or 0
    )


def _naive_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise LogicalAccessoryBackfillInputError()
    if value.tzinfo is None:
        return value
    if value.utcoffset() is None:
        raise LogicalAccessoryBackfillInputError()
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LogicalAccessoryBackfillInputError()
    return value


__all__ = [
    "LegacyAccessoryRequestEntry",
    "LegacyAccessoryTypeEntry",
    "LegacyAccessoryUnitEntry",
    "LogicalAccessoryBackfillConflictError",
    "LogicalAccessoryBackfillError",
    "LogicalAccessoryBackfillIdentityMismatchError",
    "LogicalAccessoryBackfillInputError",
    "LogicalAccessoryBackfillPersistenceError",
    "LogicalAccessoryBackfillPlan",
    "LogicalAccessoryBackfillResult",
    "LogicalAccessoryBackfillService",
    "LogicalAccessoryBackfillTransactionError",
]
