"""Tenant-routed warehouse operations without provider side effects."""

from __future__ import annotations

from contextlib import nullcontext
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from typing import Optional, Sequence, Tuple

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import db
from app.models.accessory_inventory import (
    AccessoryType,
    AccessoryUnit,
    AccessoryUnitEvent,
    RentalAccessoryRequest,
    RentalAccessoryUnitLink,
)
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental
from app.models.rental_relay_case import RentalRelayCase
from app.models.warehouse import (
    DeviceWarehouseMovement,
    UserWarehousePreference,
    Warehouse,
)
from app.services.accessory_relay_chain_service import (
    AccessoryRelayChainError,
    AccessoryRelayChainService,
)
from inventory_control.transactions import require_caller_transaction


_UNSHIPPED_RENTAL_STATUSES = (
    "not_shipped",
    "scheduled_for_shipping",
)


class WarehouseServiceError(ValueError):
    """Base class for stable warehouse service rejections."""


class DeviceNotFoundError(WarehouseServiceError):
    pass


class DeviceModelNotFoundError(WarehouseServiceError):
    pass


class DeviceSerialNumberConflictError(WarehouseServiceError):
    pass


class WarehouseNotFoundError(WarehouseServiceError):
    pass


class WarehouseUnavailableError(WarehouseServiceError):
    pass


class DefaultWarehouseProtectedError(WarehouseServiceError):
    """The current default must be replaced before it can be deactivated."""


class WarehouseInventoryPresentError(WarehouseServiceError):
    """Current serviceable inventory must be moved before deactivation."""


class StaleDeviceWarehouseError(WarehouseServiceError):
    pass


class SameWarehouseMoveError(WarehouseServiceError):
    pass


class MoveConfirmationRequiredError(WarehouseServiceError):
    pass


class UnsupportedDeviceMoveError(WarehouseServiceError):
    """Only serialized main devices participate in this move workflow."""


class AccessoryMoveReassignmentUnsupportedError(WarehouseServiceError):
    """The ordinary move path cannot safely rewrite a relay/custody chain."""


class WarehousePersistenceError(WarehouseServiceError):
    """Persistence failed without exposing internal inventory identifiers."""


class DeviceWarehouseLocationService:
    """Apply one already-authorized location fact in the caller transaction."""

    @staticmethod
    def move_locked_device(
        *,
        tenant_session: Session,
        device: Device,
        target_warehouse: Warehouse,
        source: str,
        actor_user_id: str,
        note: Optional[str] = None,
        related_resource_type: Optional[str] = None,
        related_resource_id: Optional[str] = None,
        require_explicit_transaction: bool = True,
    ) -> DeviceWarehouseMovement:
        if require_explicit_transaction:
            _operation_session(tenant_session)
        elif not isinstance(tenant_session, Session):
            raise TypeError("tenant_session must be a SQLAlchemy Session")
        if (
            not isinstance(device, Device)
            or not isinstance(target_warehouse, Warehouse)
            or source not in {"inspection", "manual_change"}
            or not isinstance(actor_user_id, str)
            or not actor_user_id.strip()
            or len(actor_user_id.strip()) > 36
            or (note is not None and len(note) > 500)
            or (related_resource_type is not None and len(related_resource_type) > 64)
            or (related_resource_id is not None and len(related_resource_id) > 64)
        ):
            raise WarehouseServiceError("device warehouse movement is invalid")
        if device.warehouse_id == target_warehouse.id:
            raise SameWarehouseMoveError("device is already in the target warehouse")
        movement = DeviceWarehouseMovement(
            device_id=device.id,
            from_warehouse_id=device.warehouse_id,
            to_warehouse_id=target_warehouse.id,
            source=source,
            note=note,
            actor_user_id=actor_user_id.strip(),
            related_resource_type=related_resource_type,
            related_resource_id=related_resource_id,
        )
        device.warehouse_id = target_warehouse.id
        tenant_session.add(movement)
        tenant_session.flush()
        return movement


@dataclass(frozen=True, slots=True)
class DeviceReference:
    id: int
    name: str
    warehouse_id: Optional[int]


@dataclass(frozen=True, slots=True)
class WarehouseReference:
    id: int
    warehouse_uuid: str
    name: Optional[str]
    status: str
    setup_state: str


@dataclass(frozen=True, slots=True)
class AccessoryTypeReference:
    accessory_type_id: int
    name: str


@dataclass(frozen=True, slots=True)
class AffectedRentalMovePreview:
    rental_id: int
    order_number: Optional[str]
    customer_start_date: date
    customer_end_date: date
    logistics_days: Optional[int]
    planned_ship_out_date: Optional[date]
    planned_return_date: Optional[date]
    affected_accessory_types: Tuple[AccessoryTypeReference, ...]


@dataclass(frozen=True, slots=True)
class RentalAccessoryFulfillmentFact:
    rental_id: int
    accessory_type_id: int
    accessory_name: str
    status: str


@dataclass(frozen=True, slots=True)
class DeviceWarehouseMovePreview:
    device: DeviceReference
    current_warehouse: Optional[WarehouseReference]
    target_warehouse: WarehouseReference
    is_same_warehouse: bool
    affected_rental_ids: Tuple[int, ...]
    affected_rentals: Tuple[AffectedRentalMovePreview, ...]
    revision: str
    preserves_logistics_facts: bool = True


@dataclass(frozen=True, slots=True)
class DeviceWarehouseMoveResult:
    device_id: int
    from_warehouse_id: Optional[int]
    to_warehouse_id: int
    movement_id: str
    affected_rental_ids: Tuple[int, ...]
    accessory_fulfillment: Tuple[RentalAccessoryFulfillmentFact, ...]


def _device_reference(device: Device) -> DeviceReference:
    return DeviceReference(
        id=device.id,
        name=device.name,
        warehouse_id=device.warehouse_id,
    )


def _warehouse_reference(warehouse: Warehouse) -> WarehouseReference:
    return WarehouseReference(
        id=warehouse.id,
        warehouse_uuid=warehouse.warehouse_uuid,
        name=warehouse.name,
        status=warehouse.status,
        setup_state=warehouse.setup_state,
    )


def _affected_future_main_rentals(
    session: Session,
    device_id: int,
    *,
    business_date: date,
    lock: bool,
) -> Tuple[Rental, ...]:
    statement = (
        select(Rental)
        .where(
            Rental.device_id == device_id,
            Rental.parent_rental_id.is_(None),
            Rental.status.in_(_UNSHIPPED_RENTAL_STATUSES),
            Rental.end_date >= business_date,
        )
        .order_by(Rental.start_date.asc(), Rental.id.asc())
        .execution_options(populate_existing=True)
    )
    if lock:
        statement = statement.with_for_update()
    return tuple(session.execute(statement).scalars().all())


def _load_preview_accessory_types(
    session: Session,
    rental_ids: Sequence[int],
) -> dict[int, Tuple[AccessoryTypeReference, ...]]:
    if not rental_ids:
        return {}
    requests = tuple(
        session.execute(
            select(RentalAccessoryRequest)
            .where(RentalAccessoryRequest.rental_id.in_(tuple(rental_ids)))
            .order_by(
                RentalAccessoryRequest.rental_id.asc(),
                RentalAccessoryRequest.accessory_type_id.asc(),
            )
            .execution_options(populate_existing=True)
        )
        .scalars()
        .all()
    )
    links = tuple(
        session.execute(
            select(RentalAccessoryUnitLink)
            .where(RentalAccessoryUnitLink.rental_id.in_(tuple(rental_ids)))
            .order_by(
                RentalAccessoryUnitLink.rental_id.asc(),
                RentalAccessoryUnitLink.accessory_type_id.asc(),
            )
            .execution_options(populate_existing=True)
        )
        .scalars()
        .all()
    )
    type_ids = {row.accessory_type_id for row in (*requests, *links)}
    type_names = {
        accessory_type.id: accessory_type.display_name
        for accessory_type in (
            session.execute(
                select(AccessoryType)
                .where(AccessoryType.id.in_(tuple(sorted(type_ids))))
                .order_by(AccessoryType.id.asc())
                .execution_options(populate_existing=True)
            )
            .scalars()
            .all()
            if type_ids
            else ()
        )
    }
    request_names = {
        (request.rental_id, request.accessory_type_id): request.name_snapshot
        for request in requests
    }
    types_by_rental: dict[int, set[int]] = {
        rental_id: set() for rental_id in rental_ids
    }
    for row in (*requests, *links):
        types_by_rental[row.rental_id].add(row.accessory_type_id)
    return {
        rental_id: tuple(
            AccessoryTypeReference(
                accessory_type_id=accessory_type_id,
                name=request_names.get(
                    (rental_id, accessory_type_id),
                    type_names.get(accessory_type_id, "unknown"),
                ),
            )
            for accessory_type_id in sorted(type_ids_for_rental)
        )
        for rental_id, type_ids_for_rental in types_by_rental.items()
    }


def _rental_preview(
    rental: Rental,
    accessory_types: Tuple[AccessoryTypeReference, ...],
) -> AffectedRentalMovePreview:
    return AffectedRentalMovePreview(
        rental_id=rental.id,
        order_number=rental.xianyu_order_no,
        customer_start_date=rental.start_date,
        customer_end_date=rental.end_date,
        logistics_days=rental.logistics_days,
        planned_ship_out_date=rental.planned_ship_out_date,
        planned_return_date=rental.planned_return_date,
        affected_accessory_types=accessory_types,
    )


def _preview_revision(
    *,
    device: Device,
    current_warehouse: Optional[Warehouse],
    target_warehouse: Warehouse,
    rentals: Sequence[Rental],
    requests: Sequence[RentalAccessoryRequest],
    links: Sequence[RentalAccessoryUnitLink],
    relay_cases: Sequence[RentalRelayCase],
    unit_by_id: dict[str, AccessoryUnit],
) -> str:
    facts: list[object] = [
        ("device", device.id, device.warehouse_id, target_warehouse.id),
        (
            "current_warehouse",
            current_warehouse.id if current_warehouse is not None else None,
            (
                current_warehouse.warehouse_uuid
                if current_warehouse is not None
                else None
            ),
            current_warehouse.name if current_warehouse is not None else None,
            current_warehouse.status if current_warehouse is not None else None,
            (current_warehouse.setup_state if current_warehouse is not None else None),
        ),
        (
            "target_warehouse",
            target_warehouse.id,
            target_warehouse.warehouse_uuid,
            target_warehouse.name,
            target_warehouse.status,
            target_warehouse.setup_state,
        ),
    ]
    for rental in sorted(rentals, key=lambda row: row.id):
        facts.append(
            (
                "rental",
                rental.id,
                rental.status,
                rental.start_date.isoformat(),
                rental.end_date.isoformat(),
                rental.xianyu_order_no,
                rental.logistics_days,
                (
                    rental.planned_ship_out_date.isoformat()
                    if rental.planned_ship_out_date is not None
                    else None
                ),
                (
                    rental.planned_return_date.isoformat()
                    if rental.planned_return_date is not None
                    else None
                ),
                rental.logistics_estimate_origin_warehouse_id,
                rental.logistics_estimate_provider,
                rental.logistics_estimate_provider_version,
                rental.logistics_estimate_rule_version,
                rental.logistics_estimate_days,
                (
                    rental.logistics_estimate_evaluated_at.isoformat(
                        timespec="microseconds"
                    )
                    if rental.logistics_estimate_evaluated_at is not None
                    else None
                ),
                rental.logistics_estimate_address_digest,
                rental.logistics_estimate_address_summary,
            )
        )
    for request in sorted(
        requests,
        key=lambda row: (row.rental_id, row.accessory_type_id),
    ):
        facts.append(
            (
                "request",
                request.rental_id,
                request.accessory_type_id,
                request.name_snapshot,
            )
        )
    for relay_case in sorted(relay_cases, key=lambda row: row.id):
        facts.append(
            (
                "relay_case",
                relay_case.id,
                relay_case.predecessor_rental_id,
                relay_case.successor_rental_id,
                relay_case.status,
            )
        )
    for link in sorted(
        links,
        key=lambda row: (
            row.rental_id,
            row.accessory_type_id,
            row.accessory_unit_id,
        ),
    ):
        unit = unit_by_id.get(link.accessory_unit_id)
        facts.append(
            (
                "link",
                link.rental_id,
                link.accessory_type_id,
                link.id,
                link.accessory_unit_id,
                link.reservation_start_at.isoformat(timespec="microseconds"),
                link.reservation_end_at.isoformat(timespec="microseconds"),
                link.source_relay_case_id,
                unit.warehouse_id if unit is not None else None,
                unit.condition_status if unit is not None else None,
                (unit.current_holder_rental_id is None if unit is not None else False),
                (
                    unit.accessory_type_id == link.accessory_type_id
                    if unit is not None
                    else False
                ),
            )
        )
    canonical = json.dumps(
        facts,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _load_relay_cases(
    session: Session,
    rental_ids: Sequence[int],
    *,
    lock: bool,
) -> Tuple[RentalRelayCase, ...]:
    if not rental_ids:
        return ()
    statement = (
        select(RentalRelayCase)
        .where(
            RentalRelayCase.predecessor_rental_id.in_(tuple(rental_ids)),
            RentalRelayCase.successor_rental_id.in_(tuple(rental_ids)),
        )
        .order_by(RentalRelayCase.id.asc())
        .execution_options(populate_existing=True)
    )
    if lock:
        statement = statement.with_for_update()
    return tuple(session.execute(statement).scalars().all())


def _relay_chain_roots(
    relay_cases: Sequence[RentalRelayCase],
    *,
    affected_rental_ids: Sequence[int],
) -> Tuple[RentalRelayCase, ...]:
    if not relay_cases:
        return ()
    affected = set(affected_rental_ids)
    successor_ids = {item.successor_rental_id for item in relay_cases}
    all_roots = tuple(
        item for item in relay_cases if item.predecessor_rental_id not in successor_ids
    )
    if not all_roots:
        raise AccessoryMoveReassignmentUnsupportedError(
            "relay chain has no stable root"
        )
    case_by_predecessor: dict[int, RentalRelayCase] = {}
    for relay_case in relay_cases:
        if relay_case.predecessor_rental_id in case_by_predecessor:
            raise AccessoryMoveReassignmentUnsupportedError(
                "relay chain branches require manual review"
            )
        case_by_predecessor[relay_case.predecessor_rental_id] = relay_case
    relevant_roots: list[RentalRelayCase] = []
    for root in all_roots:
        edge: Optional[RentalRelayCase] = root
        chain_rental_ids = {root.predecessor_rental_id}
        while edge is not None:
            if edge.successor_rental_id in chain_rental_ids:
                raise AccessoryMoveReassignmentUnsupportedError(
                    "relay chain cycle requires manual review"
                )
            chain_rental_ids.add(edge.successor_rental_id)
            edge = case_by_predecessor.get(edge.successor_rental_id)
        if chain_rental_ids & affected:
            relevant_roots.append(root)
    return tuple(relevant_roots)


def _load_preview_revision_facts(
    session: Session,
    rental_ids: Sequence[int],
) -> tuple[
    Tuple[RentalAccessoryRequest, ...],
    Tuple[RentalAccessoryUnitLink, ...],
    dict[str, AccessoryUnit],
]:
    if not rental_ids:
        return (), (), {}
    requests = tuple(
        session.execute(
            select(RentalAccessoryRequest)
            .where(RentalAccessoryRequest.rental_id.in_(tuple(rental_ids)))
            .order_by(
                RentalAccessoryRequest.rental_id.asc(),
                RentalAccessoryRequest.accessory_type_id.asc(),
            )
            .execution_options(populate_existing=True)
        )
        .scalars()
        .all()
    )
    links = tuple(
        session.execute(
            select(RentalAccessoryUnitLink)
            .where(RentalAccessoryUnitLink.rental_id.in_(tuple(rental_ids)))
            .order_by(
                RentalAccessoryUnitLink.rental_id.asc(),
                RentalAccessoryUnitLink.accessory_type_id.asc(),
                RentalAccessoryUnitLink.accessory_unit_id.asc(),
            )
            .execution_options(populate_existing=True)
        )
        .scalars()
        .all()
    )
    unit_ids = tuple(sorted({link.accessory_unit_id for link in links}))
    units = (
        tuple(
            session.execute(
                select(AccessoryUnit)
                .where(AccessoryUnit.id.in_(unit_ids))
                .order_by(
                    AccessoryUnit.accessory_type_id.asc(),
                    AccessoryUnit.id.asc(),
                )
                .execution_options(populate_existing=True)
            )
            .scalars()
            .all()
        )
        if unit_ids
        else ()
    )
    return requests, links, {unit.id: unit for unit in units}


def _request_window(
    rental: Rental,
    existing_link: Optional[RentalAccessoryUnitLink],
) -> Optional[tuple[datetime, datetime]]:
    if existing_link is not None:
        return (
            existing_link.reservation_start_at,
            existing_link.reservation_end_at,
        )
    if rental.planned_ship_out_date is None or rental.planned_return_date is None:
        return None
    return (
        datetime.combine(rental.planned_ship_out_date, time.min),
        datetime.combine(
            rental.planned_return_date + timedelta(days=1),
            time.min,
        ),
    )


def _windows_overlap(
    left: tuple[datetime, datetime],
    right: tuple[datetime, datetime],
) -> bool:
    return left[0] < right[1] and left[1] > right[0]


def _movement_event_key(
    *,
    movement_id: str,
    event_type: str,
    rental_id: int,
    accessory_type_id: int,
    from_warehouse_id: Optional[int],
    to_warehouse_id: int,
    window: tuple[datetime, datetime],
) -> str:
    facts = (
        f"{event_type}\0{rental_id}\0{accessory_type_id}\0"
        f"{from_warehouse_id}\0{to_warehouse_id}\0"
        f"{window[0].isoformat(timespec='microseconds')}\0"
        f"{window[1].isoformat(timespec='microseconds')}"
    )
    digest = sha256(facts.encode("utf-8")).hexdigest()[:24]
    return f"warehouse-move:{movement_id}:{event_type}:f{digest}"


def _operation_session(
    tenant_session: Optional[Session],
) -> tuple[Session, bool]:
    if tenant_session is None:
        return db.session(), True
    if not isinstance(tenant_session, Session):
        raise TypeError("tenant_session must be a SQLAlchemy Session")
    require_caller_transaction(
        tenant_session,
        lambda: WarehouseServiceError(
            "an explicit caller-owned tenant transaction is required"
        ),
        accept_nested=True,
    )
    return tenant_session, False


class WarehouseService:
    """Warehouse operations scoped by the caller's trusted tenant database."""

    @staticmethod
    def create_ready_warehouse(
        *,
        name: str,
        contact_name: str,
        contact_phone: str,
        province: str,
        city: str,
        district: str,
        address_detail: str,
        tenant_session: Optional[Session] = None,
    ) -> Warehouse:
        """Create one active, ready, non-default warehouse."""

        session, owns_transaction = _operation_session(tenant_session)
        try:
            warehouse = Warehouse(
                status="active",
                setup_state="pending",
                is_default=False,
                default_slot=None,
            )
            warehouse.mark_ready(
                name=name,
                contact_name=contact_name,
                contact_phone=contact_phone,
                province=province,
                city=city,
                district=district,
                address_detail=address_detail,
            )
            session.add(warehouse)
            session.flush()
            if owns_transaction:
                session.commit()
            return warehouse
        except Exception:
            if owns_transaction:
                session.rollback()
            raise

    @staticmethod
    def create_main_device(
        *,
        name: str,
        serial_number: str,
        model_id: int,
        warehouse_id: Optional[int] = None,
        tenant_session: Optional[Session] = None,
    ) -> Device:
        """Create a serialized main device in a ready warehouse."""

        session, owns_transaction = _operation_session(tenant_session)
        try:
            if (
                not isinstance(name, str)
                or not name.strip()
                or len(name.strip()) > 100
                or not isinstance(serial_number, str)
                or not serial_number.strip()
                or len(serial_number.strip()) > 100
                or isinstance(model_id, bool)
                or not isinstance(model_id, int)
                or model_id <= 0
                or (
                    warehouse_id is not None
                    and (
                        isinstance(warehouse_id, bool)
                        or not isinstance(warehouse_id, int)
                        or warehouse_id <= 0
                    )
                )
            ):
                raise WarehouseServiceError("device input is invalid")
            model = session.execute(
                select(DeviceModel)
                .where(DeviceModel.id == model_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            ).scalar_one_or_none()
            if (
                model is None
                or model.is_active is not True
                or model.is_accessory is True
            ):
                raise DeviceModelNotFoundError("main device model not found")
            warehouse_statement = select(Warehouse).where(
                Warehouse.id == warehouse_id
                if warehouse_id is not None
                else Warehouse.is_default.is_(True)
            )
            warehouses = tuple(
                session.execute(
                    warehouse_statement.order_by(Warehouse.id.asc())
                    .execution_options(populate_existing=True)
                    .with_for_update()
                )
                .scalars()
                .all()
            )
            if len(warehouses) != 1:
                if warehouse_id is None:
                    raise WarehousePersistenceError(
                        "exactly one default warehouse is required"
                    )
                raise WarehouseNotFoundError("warehouse not found")
            warehouse = warehouses[0]
            if warehouse.status != "active" or warehouse.setup_state != "ready":
                raise WarehouseUnavailableError(
                    "device warehouse must be active and ready"
                )
            existing = session.execute(
                select(Device.id)
                .where(Device.serial_number == serial_number.strip())
                .limit(1)
                .with_for_update()
            ).scalar_one_or_none()
            if existing is not None:
                raise DeviceSerialNumberConflictError(
                    "device serial number already exists"
                )
            device = Device(
                name=name.strip(),
                serial_number=serial_number.strip(),
                model=model.name,
                model_id=model.id,
                is_accessory=False,
                lifecycle_status="active",
                warehouse_id=warehouse.id,
            )
            session.add(device)
            session.flush()
            if owns_transaction:
                session.commit()
            return device
        except Exception:
            if owns_transaction:
                session.rollback()
            raise

    @staticmethod
    def list_active_warehouses(
        *,
        tenant_session: Optional[Session] = None,
    ):
        """List active warehouses from the already-routed tenant database."""

        session = tenant_session or db.session()
        if not isinstance(session, Session):
            raise TypeError("tenant_session must be a SQLAlchemy Session")
        return tuple(
            session.execute(
                select(Warehouse)
                .where(Warehouse.status == "active")
                .order_by(Warehouse.is_default.desc(), Warehouse.id.asc())
            )
            .scalars()
            .all()
        )

    @staticmethod
    def list_warehouses(
        *,
        tenant_session: Optional[Session] = None,
    ) -> tuple[Warehouse, ...]:
        """List current and inactive warehouse records for management."""

        session = tenant_session or db.session()
        if not isinstance(session, Session):
            raise TypeError("tenant_session must be a SQLAlchemy Session")
        return tuple(
            session.execute(
                select(Warehouse).order_by(
                    Warehouse.is_default.desc(),
                    Warehouse.status.asc(),
                    Warehouse.id.asc(),
                )
            )
            .scalars()
            .all()
        )

    @staticmethod
    def get_default_warehouse(
        *,
        tenant_session: Optional[Session] = None,
    ) -> Warehouse:
        """Return the sole default, including its pending setup record."""

        session = tenant_session or db.session()
        if not isinstance(session, Session):
            raise TypeError("tenant_session must be a SQLAlchemy Session")
        defaults = tuple(
            session.execute(
                select(Warehouse)
                .where(Warehouse.is_default.is_(True))
                .order_by(Warehouse.id.asc())
            )
            .scalars()
            .all()
        )
        if len(defaults) != 1:
            raise WarehousePersistenceError("exactly one default warehouse is required")
        return defaults[0]

    @staticmethod
    def setup_default_warehouse(
        *,
        name: str,
        contact_name: str,
        contact_phone: str,
        province: str,
        city: str,
        district: str,
        address_detail: str,
        tenant_session: Optional[Session] = None,
    ) -> Warehouse:
        """Confirm the provisioned default warehouse in one transaction."""

        session, owns_transaction = _operation_session(tenant_session)
        try:
            defaults = tuple(
                session.execute(
                    select(Warehouse)
                    .where(Warehouse.is_default.is_(True))
                    .order_by(Warehouse.id.asc())
                    .execution_options(populate_existing=True)
                    .with_for_update()
                )
                .scalars()
                .all()
            )
            if len(defaults) != 1:
                raise WarehousePersistenceError(
                    "exactly one default warehouse is required"
                )
            warehouse = defaults[0]
            if warehouse.status != "active":
                raise WarehouseUnavailableError("default warehouse must be active")
            warehouse.mark_ready(
                name=name,
                contact_name=contact_name,
                contact_phone=contact_phone,
                province=province,
                city=city,
                district=district,
                address_detail=address_detail,
            )
            session.flush()
            if owns_transaction:
                session.commit()
            return warehouse
        except Exception:
            if owns_transaction:
                session.rollback()
            raise

    @staticmethod
    def update_warehouse(
        *,
        warehouse_id: int,
        name: str,
        contact_name: str,
        contact_phone: str,
        province: str,
        city: str,
        district: str,
        address_detail: str,
        tenant_session: Optional[Session] = None,
    ) -> Warehouse:
        """Edit one active ready warehouse without changing its identity."""

        session, owns_transaction = _operation_session(tenant_session)
        try:
            warehouse = session.execute(
                select(Warehouse)
                .where(Warehouse.id == warehouse_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            ).scalar_one_or_none()
            if warehouse is None:
                raise WarehouseNotFoundError("warehouse not found")
            if warehouse.status != "active" or warehouse.setup_state != "ready":
                raise WarehouseUnavailableError("warehouse must be active and ready")
            warehouse.mark_ready(
                name=name,
                contact_name=contact_name,
                contact_phone=contact_phone,
                province=province,
                city=city,
                district=district,
                address_detail=address_detail,
            )
            session.flush()
            if owns_transaction:
                session.commit()
            return warehouse
        except Exception:
            if owns_transaction:
                session.rollback()
            raise

    @staticmethod
    def set_default_warehouse(
        *,
        warehouse_id: int,
        tenant_session: Optional[Session] = None,
    ) -> Warehouse:
        """Atomically transfer the tenant's unique default slot."""

        session, owns_transaction = _operation_session(tenant_session)
        try:
            warehouses = tuple(
                session.execute(
                    select(Warehouse)
                    .order_by(Warehouse.id.asc())
                    .execution_options(populate_existing=True)
                    .with_for_update()
                )
                .scalars()
                .all()
            )
            target = next(
                (row for row in warehouses if row.id == warehouse_id),
                None,
            )
            if target is None:
                raise WarehouseNotFoundError("warehouse not found")
            if target.status != "active" or target.setup_state != "ready":
                raise WarehouseUnavailableError(
                    "default warehouse must be active and ready"
                )
            defaults = tuple(row for row in warehouses if row.is_default)
            if len(defaults) != 1:
                raise WarehousePersistenceError(
                    "exactly one default warehouse is required"
                )
            current = defaults[0]
            if current.id == target.id:
                if owns_transaction:
                    session.commit()
                return target
            current.is_default = False
            current.default_slot = None
            session.flush()
            target.is_default = True
            target.default_slot = 1
            session.flush()
            if owns_transaction:
                session.commit()
            return target
        except Exception:
            if owns_transaction:
                session.rollback()
            raise

    @staticmethod
    def deactivate_warehouse(
        *,
        warehouse_id: int,
        tenant_session: Optional[Session] = None,
    ) -> Warehouse:
        """Remove a non-default warehouse from new operations, never delete it."""

        session, owns_transaction = _operation_session(tenant_session)
        try:
            warehouse = session.execute(
                select(Warehouse)
                .where(Warehouse.id == warehouse_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            ).scalar_one_or_none()
            if warehouse is None:
                raise WarehouseNotFoundError("warehouse not found")
            if warehouse.is_default:
                raise DefaultWarehouseProtectedError(
                    "replace the default warehouse before deactivation"
                )
            if warehouse.status == "inactive":
                if owns_transaction:
                    session.commit()
                return warehouse
            serviceable_device_id = session.execute(
                select(Device.id)
                .where(
                    Device.warehouse_id == warehouse.id,
                    Device.lifecycle_status == "active",
                )
                .order_by(Device.id.asc())
                .limit(1)
                .with_for_update()
            ).scalar_one_or_none()
            serviceable_unit_id = session.execute(
                select(AccessoryUnit.id)
                .where(
                    AccessoryUnit.warehouse_id == warehouse.id,
                    AccessoryUnit.condition_status != "retired",
                )
                .order_by(AccessoryUnit.id.asc())
                .limit(1)
                .with_for_update()
            ).scalar_one_or_none()
            if serviceable_device_id is not None or serviceable_unit_id is not None:
                raise WarehouseInventoryPresentError(
                    "move current inventory before warehouse deactivation"
                )
            warehouse.status = "inactive"
            session.flush()
            if owns_transaction:
                session.commit()
            return warehouse
        except Exception:
            if owns_transaction:
                session.rollback()
            raise

    @staticmethod
    def set_user_warehouse_preference(
        *,
        user_id: str,
        scene: str,
        warehouse_id: int,
        tenant_session: Optional[Session] = None,
    ) -> UserWarehousePreference:
        """Remember one actor's last ready warehouse for a bounded scene."""

        session, owns_transaction = _operation_session(tenant_session)
        try:
            if (
                not isinstance(user_id, str)
                or not user_id.strip()
                or len(user_id.strip()) > 36
                or scene not in {"booking", "shipping", "inspection"}
            ):
                raise WarehouseServiceError("warehouse preference is invalid")
            warehouse = session.execute(
                select(Warehouse)
                .where(Warehouse.id == warehouse_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            ).scalar_one_or_none()
            if warehouse is None:
                raise WarehouseNotFoundError("warehouse not found")
            if warehouse.status != "active" or warehouse.setup_state != "ready":
                raise WarehouseUnavailableError(
                    "preferred warehouse must be active and ready"
                )
            preference = session.get(
                UserWarehousePreference,
                (user_id.strip(), scene),
                with_for_update=True,
            )
            if preference is None:
                preference = UserWarehousePreference(
                    user_id=user_id.strip(),
                    scene=scene,
                    warehouse_id=warehouse.id,
                )
                session.add(preference)
            else:
                preference.warehouse_id = warehouse.id
            session.flush()
            if owns_transaction:
                session.commit()
            return preference
        except Exception:
            if owns_transaction:
                session.rollback()
            raise

    @staticmethod
    def list_user_warehouse_preferences(
        *,
        user_id: str,
        tenant_session: Optional[Session] = None,
    ) -> tuple[UserWarehousePreference, ...]:
        """Read one actor's bounded per-scene warehouse choices."""

        session = tenant_session or db.session()
        if not isinstance(session, Session):
            raise TypeError("tenant_session must be a SQLAlchemy Session")
        if (
            not isinstance(user_id, str)
            or not user_id.strip()
            or len(user_id.strip()) > 36
        ):
            raise WarehouseServiceError("warehouse preference is invalid")
        return tuple(
            session.execute(
                select(UserWarehousePreference)
                .join(Warehouse, Warehouse.id == UserWarehousePreference.warehouse_id)
                .where(
                    UserWarehousePreference.user_id == user_id.strip(),
                    Warehouse.status == "active",
                    Warehouse.setup_state == "ready",
                )
                .order_by(UserWarehousePreference.scene.asc())
            )
            .scalars()
            .all()
        )

    @staticmethod
    def preview_device_move(
        *,
        device_id: int,
        target_warehouse_id: int,
        business_date: Optional[date] = None,
        tenant_session: Optional[Session] = None,
    ) -> DeviceWarehouseMovePreview:
        """Return immutable technical facts without changing any record."""

        session = tenant_session or db.session()
        if not isinstance(session, Session):
            raise TypeError("tenant_session must be a SQLAlchemy Session")
        effective_business_date = business_date or date.today()
        if not isinstance(effective_business_date, date):
            raise WarehouseServiceError("business_date is invalid")

        device = session.execute(
            select(Device)
            .where(Device.id == device_id)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if device is None:
            raise DeviceNotFoundError("device not found")
        if device.is_accessory is True:
            raise UnsupportedDeviceMoveError("warehouse move requires a main device")

        target_warehouse = session.execute(
            select(Warehouse)
            .where(Warehouse.id == target_warehouse_id)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if target_warehouse is None:
            raise WarehouseNotFoundError("target warehouse not found")

        current_warehouse = (
            session.execute(
                select(Warehouse)
                .where(Warehouse.id == device.warehouse_id)
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if device.warehouse_id is not None
            else None
        )
        affected_rentals = _affected_future_main_rentals(
            session,
            device.id,
            business_date=effective_business_date,
            lock=False,
        )
        accessory_types_by_rental = _load_preview_accessory_types(
            session, tuple(rental.id for rental in affected_rentals)
        )
        (
            revision_requests,
            revision_links,
            revision_unit_by_id,
        ) = _load_preview_revision_facts(
            session, tuple(rental.id for rental in affected_rentals)
        )
        device_rental_ids = tuple(
            session.execute(
                select(Rental.id)
                .where(
                    Rental.device_id == device.id,
                    Rental.parent_rental_id.is_(None),
                )
                .order_by(Rental.id.asc())
            ).scalars()
        )
        revision_relay_cases = _load_relay_cases(
            session,
            device_rental_ids,
            lock=False,
        )
        return DeviceWarehouseMovePreview(
            device=_device_reference(device),
            current_warehouse=(
                _warehouse_reference(current_warehouse)
                if current_warehouse is not None
                else None
            ),
            target_warehouse=_warehouse_reference(target_warehouse),
            is_same_warehouse=device.warehouse_id == target_warehouse.id,
            affected_rental_ids=tuple(rental.id for rental in affected_rentals),
            affected_rentals=tuple(
                _rental_preview(
                    rental,
                    accessory_types_by_rental.get(rental.id, ()),
                )
                for rental in affected_rentals
            ),
            revision=_preview_revision(
                device=device,
                current_warehouse=current_warehouse,
                target_warehouse=target_warehouse,
                rentals=affected_rentals,
                requests=revision_requests,
                links=revision_links,
                relay_cases=revision_relay_cases,
                unit_by_id=revision_unit_by_id,
            ),
        )

    @staticmethod
    def execute_device_move(
        *,
        device_id: int,
        target_warehouse_id: int,
        expected_current_warehouse_id: Optional[int],
        expected_preview_revision: str,
        confirmation_token_confirmed: bool,
        actor_user_id: str,
        note: Optional[str] = None,
        business_date: Optional[date] = None,
        tenant_session: Optional[Session] = None,
    ) -> DeviceWarehouseMoveResult:
        """Move a device and recompute ordinary future accessory links."""

        session, owns_transaction = _operation_session(tenant_session)
        effective_business_date = business_date or date.today()
        try:
            if confirmation_token_confirmed is not True:
                raise MoveConfirmationRequiredError(
                    "confirmed move preview is required"
                )
            if not isinstance(actor_user_id, str) or not actor_user_id.strip():
                raise WarehouseServiceError("actor_user_id is required")
            if (
                not isinstance(expected_preview_revision, str)
                or len(expected_preview_revision) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in expected_preview_revision
                )
            ):
                raise StaleDeviceWarehouseError(
                    "move preview revision is missing or invalid"
                )

            if not isinstance(effective_business_date, date):
                raise WarehouseServiceError("business_date is invalid")
            device = session.execute(
                select(Device)
                .where(Device.id == device_id)
                .execution_options(populate_existing=True)
                .with_for_update()
            ).scalar_one_or_none()
            if device is None:
                raise DeviceNotFoundError("device not found")
            if device.is_accessory is True:
                raise UnsupportedDeviceMoveError(
                    "warehouse move requires a main device"
                )

            # Lock every main rental in the same ID order used by the shared
            # relay-chain solver.  The affected move projection is then
            # derived in memory, avoiding a subset-first lock inversion.
            device_rentals = tuple(
                session.execute(
                    select(Rental)
                    .where(
                        Rental.device_id == device.id,
                        Rental.parent_rental_id.is_(None),
                    )
                    .order_by(Rental.id.asc())
                    .execution_options(populate_existing=True)
                    .with_for_update()
                )
                .scalars()
                .all()
            )
            affected_rentals = tuple(
                sorted(
                    (
                        rental
                        for rental in device_rentals
                        if (
                            rental.status in _UNSHIPPED_RENTAL_STATUSES
                            and rental.end_date >= effective_business_date
                        )
                    ),
                    key=lambda rental: (rental.start_date, rental.id),
                )
            )
            affected_rental_ids = tuple(rental.id for rental in affected_rentals)
            rental_by_id = {rental.id: rental for rental in affected_rentals}
            relay_cases = _load_relay_cases(
                session,
                tuple(rental.id for rental in device_rentals),
                lock=True,
            )
            relay_roots = _relay_chain_roots(
                relay_cases,
                affected_rental_ids=affected_rental_ids,
            )
            relay_successor_ids = {
                relay_case.successor_rental_id for relay_case in relay_cases
            }

            # Shared lock order is device -> affected rentals -> warehouses.
            # Locking both ends serializes ordinary reservations in either the
            # source or target warehouse before this path locks links/units.
            warehouse_ids = tuple(
                sorted(
                    {
                        warehouse_id
                        for warehouse_id in (
                            device.warehouse_id,
                            target_warehouse_id,
                        )
                        if warehouse_id is not None
                    }
                )
            )
            locked_warehouses = tuple(
                session.execute(
                    select(Warehouse)
                    .where(Warehouse.id.in_(warehouse_ids))
                    # Match inspection's global warehouse lock order.
                    .order_by(Warehouse.is_default.desc(), Warehouse.id.asc())
                    .execution_options(populate_existing=True)
                    .with_for_update()
                )
                .scalars()
                .all()
            )
            target_warehouse = next(
                (
                    warehouse
                    for warehouse in locked_warehouses
                    if warehouse.id == target_warehouse_id
                ),
                None,
            )
            if target_warehouse is None:
                raise WarehouseNotFoundError("target warehouse not found")

            if device.warehouse_id != expected_current_warehouse_id:
                raise StaleDeviceWarehouseError(
                    "device warehouse changed after preview"
                )
            if device.warehouse_id == target_warehouse.id:
                raise SameWarehouseMoveError(
                    "device is already in the target warehouse"
                )
            requests = (
                tuple(
                    session.execute(
                        select(RentalAccessoryRequest)
                        .where(
                            RentalAccessoryRequest.rental_id.in_(affected_rental_ids)
                        )
                        .order_by(
                            RentalAccessoryRequest.rental_id.asc(),
                            RentalAccessoryRequest.accessory_type_id.asc(),
                        )
                        .execution_options(populate_existing=True)
                        .with_for_update()
                    )
                    .scalars()
                    .all()
                )
                if affected_rental_ids
                else ()
            )
            links = (
                tuple(
                    session.execute(
                        select(RentalAccessoryUnitLink)
                        .where(
                            RentalAccessoryUnitLink.rental_id.in_(affected_rental_ids)
                        )
                        .order_by(
                            RentalAccessoryUnitLink.rental_id.asc(),
                            RentalAccessoryUnitLink.accessory_type_id.asc(),
                            RentalAccessoryUnitLink.accessory_unit_id.asc(),
                        )
                        .execution_options(populate_existing=True)
                        .with_for_update()
                    )
                    .scalars()
                    .all()
                )
                if affected_rental_ids
                else ()
            )
            request_by_key = {
                (request.rental_id, request.accessory_type_id): request
                for request in requests
            }
            link_by_key = {
                (link.rental_id, link.accessory_type_id): link for link in links
            }
            requested_type_ids = tuple(
                sorted({request.accessory_type_id for request in requests})
            )
            linked_unit_ids = tuple(sorted({link.accessory_unit_id for link in links}))
            unit_predicates = []
            if linked_unit_ids:
                unit_predicates.append(AccessoryUnit.id.in_(linked_unit_ids))
            if requested_type_ids:
                unit_predicates.append(
                    and_(
                        AccessoryUnit.accessory_type_id.in_(requested_type_ids),
                        AccessoryUnit.warehouse_id == target_warehouse.id,
                        AccessoryUnit.condition_status == "active",
                        AccessoryUnit.current_holder_rental_id.is_(None),
                    )
                )
            units = (
                tuple(
                    session.execute(
                        select(AccessoryUnit)
                        .where(or_(*unit_predicates))
                        .order_by(
                            AccessoryUnit.accessory_type_id.asc(),
                            AccessoryUnit.id.asc(),
                        )
                        .execution_options(populate_existing=True)
                        .with_for_update()
                    )
                    .scalars()
                    .all()
                )
                if unit_predicates
                else ()
            )
            unit_by_id = {unit.id: unit for unit in units}

            current_preview_revision = _preview_revision(
                device=device,
                current_warehouse=next(
                    (
                        warehouse
                        for warehouse in locked_warehouses
                        if warehouse.id == device.warehouse_id
                    ),
                    None,
                ),
                target_warehouse=target_warehouse,
                rentals=affected_rentals,
                requests=requests,
                links=links,
                relay_cases=relay_cases,
                unit_by_id=unit_by_id,
            )
            if current_preview_revision != expected_preview_revision:
                raise StaleDeviceWarehouseError("move facts changed after preview")
            if (
                target_warehouse.status != "active"
                or target_warehouse.setup_state != "ready"
            ):
                raise WarehouseUnavailableError(
                    "target warehouse must be active and ready"
                )

            for link in links:
                if link.rental_id in relay_successor_ids:
                    # The shared chain solver owns every successor link,
                    # including requestless neutral carry-through links.
                    continue
                unit = unit_by_id.get(link.accessory_unit_id)
                request = request_by_key.get((link.rental_id, link.accessory_type_id))
                if (
                    link.source_relay_case_id is not None
                    or request is None
                    or unit is None
                    or unit.accessory_type_id != link.accessory_type_id
                    or unit.current_holder_rental_id is not None
                    or unit.warehouse_id
                    not in {device.warehouse_id, target_warehouse.id}
                ):
                    raise AccessoryMoveReassignmentUnsupportedError(
                        "relay, neutral, or held accessory links require "
                        "chain-aware reassignment"
                    )

            ordinary_requests = tuple(
                request
                for request in requests
                if request.rental_id not in relay_successor_ids
            )
            retained_keys: set[tuple[int, int]] = set()
            links_to_delete: list[RentalAccessoryUnitLink] = []
            windows_by_key: dict[
                tuple[int, int],
                Optional[tuple[datetime, datetime]],
            ] = {}
            for request in ordinary_requests:
                key = (request.rental_id, request.accessory_type_id)
                link = link_by_key.get(key)
                unit = (
                    unit_by_id.get(link.accessory_unit_id) if link is not None else None
                )
                windows_by_key[key] = _request_window(
                    rental_by_id[request.rental_id],
                    link,
                )
                if (
                    link is not None
                    and unit is not None
                    and unit.warehouse_id == target_warehouse.id
                    and unit.condition_status == "active"
                ):
                    retained_keys.add(key)
                elif link is not None:
                    links_to_delete.append(link)

            candidate_units = tuple(
                unit
                for unit in units
                if (
                    unit.accessory_type_id in requested_type_ids
                    and unit.warehouse_id == target_warehouse.id
                    and unit.condition_status == "active"
                    and unit.current_holder_rental_id is None
                )
            )
            candidate_unit_ids = tuple(unit.id for unit in candidate_units)
            known_windows = tuple(
                window for window in windows_by_key.values() if window is not None
            )
            overlapping_links = (
                tuple(
                    session.execute(
                        select(RentalAccessoryUnitLink)
                        .where(
                            RentalAccessoryUnitLink.accessory_unit_id.in_(
                                candidate_unit_ids
                            ),
                            RentalAccessoryUnitLink.reservation_start_at
                            < max(window[1] for window in known_windows),
                            RentalAccessoryUnitLink.reservation_end_at
                            > min(window[0] for window in known_windows),
                        )
                        .order_by(
                            RentalAccessoryUnitLink.accessory_type_id.asc(),
                            RentalAccessoryUnitLink.accessory_unit_id.asc(),
                            RentalAccessoryUnitLink.id.asc(),
                        )
                        .execution_options(populate_existing=True)
                        .with_for_update()
                    )
                    .scalars()
                    .all()
                )
                if candidate_unit_ids and known_windows
                else ()
            )
            deleted_link_ids = {link.id for link in links_to_delete}
            occupied_windows: dict[
                str,
                list[tuple[datetime, datetime]],
            ] = {unit_id: [] for unit_id in candidate_unit_ids}
            for link in overlapping_links:
                if link.id not in deleted_link_ids:
                    occupied_windows[link.accessory_unit_id].append(
                        (
                            link.reservation_start_at,
                            link.reservation_end_at,
                        )
                    )

            assigned_units: dict[tuple[int, int], AccessoryUnit] = {}
            for request in ordinary_requests:
                key = (request.rental_id, request.accessory_type_id)
                if key in retained_keys:
                    continue
                window = windows_by_key[key]
                if window is None:
                    continue
                for unit in candidate_units:
                    if unit.accessory_type_id != request.accessory_type_id:
                        continue
                    if any(
                        _windows_overlap(window, occupied)
                        for occupied in occupied_windows[unit.id]
                    ):
                        continue
                    assigned_units[key] = unit
                    occupied_windows[unit.id].append(window)
                    break

            from_warehouse_id = device.warehouse_id
            movement = DeviceWarehouseLocationService.move_locked_device(
                tenant_session=session,
                device=device,
                target_warehouse=target_warehouse,
                source="manual_change",
                note=note,
                actor_user_id=actor_user_id,
                require_explicit_transaction=not owns_transaction,
            )

            for link in links_to_delete:
                unit = unit_by_id[link.accessory_unit_id]
                window = (
                    link.reservation_start_at,
                    link.reservation_end_at,
                )
                session.add(
                    AccessoryUnitEvent(
                        unit_id=unit.id,
                        event_type="unlinked",
                        main_device_id=device.id,
                        rental_id=link.rental_id,
                        from_warehouse_id=unit.warehouse_id,
                        actor_type="user",
                        actor_id=actor_user_id.strip(),
                        reason="device_warehouse_reassignment",
                        idempotency_key=_movement_event_key(
                            movement_id=movement.id,
                            event_type="unlinked",
                            rental_id=link.rental_id,
                            accessory_type_id=link.accessory_type_id,
                            from_warehouse_id=unit.warehouse_id,
                            to_warehouse_id=target_warehouse.id,
                            window=window,
                        ),
                    )
                )
                session.delete(link)
            session.flush()

            for key, unit in assigned_units.items():
                rental_id, accessory_type_id = key
                window = windows_by_key[key]
                assert window is not None
                session.add_all(
                    (
                        RentalAccessoryUnitLink(
                            rental_id=rental_id,
                            accessory_type_id=accessory_type_id,
                            accessory_unit_id=unit.id,
                            reservation_start_at=window[0],
                            reservation_end_at=window[1],
                        ),
                        AccessoryUnitEvent(
                            unit_id=unit.id,
                            event_type="linked",
                            main_device_id=device.id,
                            rental_id=rental_id,
                            to_warehouse_id=target_warehouse.id,
                            actor_type="user",
                            actor_id=actor_user_id.strip(),
                            reason="device_warehouse_reassignment",
                            idempotency_key=_movement_event_key(
                                movement_id=movement.id,
                                event_type="linked",
                                rental_id=rental_id,
                                accessory_type_id=accessory_type_id,
                                from_warehouse_id=from_warehouse_id,
                                to_warehouse_id=target_warehouse.id,
                                window=window,
                            ),
                        ),
                    )
                )
            session.flush()

            try:
                chain_service = AccessoryRelayChainService(session)
                chain_transaction = (
                    session.begin_nested() if owns_transaction else nullcontext()
                )
                with chain_transaction:
                    for relay_root in relay_roots:
                        chain_service.recompute_from_case(
                            relay_case_id=relay_root.id,
                            actor_type="tenant_user",
                            actor_id=actor_user_id.strip(),
                            operation_key=(
                                f"warehouse-move:{movement.id}:"
                                f"relay-root:{relay_root.id}"
                            ),
                        )
            except AccessoryRelayChainError:
                raise AccessoryMoveReassignmentUnsupportedError(
                    "relay accessory chain requires manual review"
                ) from None
            session.flush()

            fulfilled_keys = (
                set(
                    session.execute(
                        select(
                            RentalAccessoryUnitLink.rental_id,
                            RentalAccessoryUnitLink.accessory_type_id,
                        ).where(
                            RentalAccessoryUnitLink.rental_id.in_(affected_rental_ids)
                        )
                    ).all()
                )
                if affected_rental_ids
                else set()
            )
            fulfillment = tuple(
                RentalAccessoryFulfillmentFact(
                    rental_id=request.rental_id,
                    accessory_type_id=request.accessory_type_id,
                    accessory_name=request.name_snapshot,
                    status=(
                        "fulfilled"
                        if (request.rental_id, request.accessory_type_id)
                        in fulfilled_keys
                        else "shortage"
                    ),
                )
                for request in requests
            )

            result = DeviceWarehouseMoveResult(
                device_id=device.id,
                from_warehouse_id=from_warehouse_id,
                to_warehouse_id=target_warehouse.id,
                movement_id=movement.id,
                affected_rental_ids=affected_rental_ids,
                accessory_fulfillment=fulfillment,
            )
            if owns_transaction:
                session.commit()
            return result
        except SQLAlchemyError:
            if owns_transaction:
                session.rollback()
            raise WarehousePersistenceError(
                "warehouse move persistence failed"
            ) from None
        except Exception:
            if owns_transaction:
                session.rollback()
            raise
