"""Atomic planning for logical accessories carried through relay chains.

The caller owns one explicit tenant-database transaction.  This service locks
the affected main device, rentals, relay cases, logical types, units, requests,
and links before it derives a complete downstream plan.  Logical unit UUIDs
never appear in public results or error messages.

The planner deliberately has no HTTP, provider, printing, or control-database
dependency.  A relay status mutation can therefore compose it in the same
tenant transaction before any external side effect is attempted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from functools import wraps
from hashlib import sha256
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.accessory_inventory import (
    AccessoryType,
    AccessoryUnit,
    AccessoryUnitEvent,
    RentalAccessoryRequest,
    RentalAccessoryUnitLink,
)
from app.models.device import Device
from app.models.rental import Rental
from app.models.rental_relay_case import RentalRelayCase
from app.models.warehouse import Warehouse
from app.services.accessory_inventory_service import (
    AccessoryFulfillmentFrozenError,
    AccessoryInventoryError,
    AccessoryInventoryRepository,
    AccessoryInventoryService,
)
from inventory_control.transactions import require_caller_transaction


_ACTIVE_RELAY_STATUSES = frozenset(("agreed", "shipped", "completed"))
_EXECUTED_RELAY_STATUSES = frozenset(("shipped", "completed"))


class AccessoryRelayChainError(RuntimeError):
    """Safe stable rejection for a relay-chain mutation."""

    code = "ACCESSORY_RELAY_CHAIN_ERROR"
    public_message = "accessory relay chain operation failed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class AccessoryRelayChainInputError(AccessoryRelayChainError):
    code = "ACCESSORY_RELAY_CHAIN_INPUT_INVALID"
    public_message = "accessory relay chain input is invalid"


class AccessoryRelayChainTransactionRequiredError(AccessoryRelayChainError):
    code = "ACCESSORY_RELAY_CHAIN_TRANSACTION_REQUIRED"
    public_message = "an explicit caller-owned transaction is required"


class AccessoryRelayChainConflictError(AccessoryRelayChainError):
    code = "ACCESSORY_RELAY_CHAIN_REVIEW_REQUIRED"
    public_message = "accessory relay chain requires manual review"


class AccessoryRelayChainPersistenceError(AccessoryRelayChainError):
    code = "ACCESSORY_RELAY_CHAIN_PERSISTENCE_FAILED"
    public_message = "accessory relay chain could not be persisted"


def _hide_persistence_details(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except AccessoryRelayChainError:
            raise
        except (AccessoryFulfillmentFrozenError, AccessoryInventoryError):
            raise AccessoryRelayChainConflictError() from None
        except SQLAlchemyError:
            raise AccessoryRelayChainPersistenceError() from None

    return wrapped


@dataclass(frozen=True, slots=True)
class AccessoryRelayChainPlanResult:
    """Public recomputation result without logical unit or link identifiers."""

    linked_count: int
    unlinked_count: int
    shortage_count: int
    shortage_type_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AccessoryRelayHandoffResult:
    """Public handoff result without logical unit or link identifiers."""

    handed_off_count: int
    accessory_type_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AccessoryInspectionReassignmentResult:
    """Type-level D41 result without logical unit or link identifiers."""

    type_code: str
    display_name: str
    outcome: str
    retained_relay_count: int
    reassigned_count: int
    shortage_count: int
    affected_rental_ids: tuple[int, ...]
    shortage_rental_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class AccessoryInspectionLockScope:
    """Pre-warehouse lock scope used by the inspection composition."""

    rental_id: int
    affected_rentals_by_type: tuple[tuple[int, tuple[int, ...]], ...]

    def affected_rental_ids(self, accessory_type_id: int) -> tuple[int, ...]:
        return next(
            (
                rental_ids
                for type_id, rental_ids in self.affected_rentals_by_type
                if type_id == accessory_type_id
            ),
            (self.rental_id,),
        )


@dataclass(frozen=True, slots=True)
class _PlannedLink:
    unit: AccessoryUnit
    source_relay_case_id: Optional[int]
    reservation_start_at: datetime
    reservation_end_at: datetime


class AccessoryRelayChainService:
    """Recompute and execute one same-device logical-accessory relay chain."""

    def __init__(
        self,
        session: Session,
        *,
        inventory_repository: Optional[AccessoryInventoryRepository] = None,
    ) -> None:
        self._session = session
        self._inventory_repository = (
            inventory_repository or AccessoryInventoryRepository(session)
        )

    @_hide_persistence_details
    def lock_inspection_context(
        self,
        *,
        rental_id: int,
        accessory_type_ids: Sequence[int],
        occurred_at: datetime,
    ) -> AccessoryInspectionLockScope:
        """Lock every known device/rental before inspection locks warehouses.

        The inspection mutation calls this once for all submitted logical
        types.  The later receipt operation compares this scope before it
        attempts any additional device/rental lock, so a concurrently added
        future link fails closed instead of reversing the shared
        device -> rental -> warehouse lock direction.
        """

        self._require_explicit_transaction()
        raw_type_ids = tuple(accessory_type_ids)
        if (
            isinstance(rental_id, bool)
            or not isinstance(rental_id, int)
            or rental_id <= 0
            or not isinstance(occurred_at, datetime)
            or any(
                isinstance(type_id, bool)
                or not isinstance(type_id, int)
                or type_id <= 0
                for type_id in raw_type_ids
            )
            or len(set(raw_type_ids)) != len(raw_type_ids)
        ):
            raise AccessoryRelayChainInputError()
        type_ids = tuple(sorted(raw_type_ids))

        peeked_rental = self._session.get(Rental, rental_id)
        if peeked_rental is None or peeked_rental.parent_rental_id is not None:
            raise AccessoryRelayChainConflictError()
        current_links = (
            tuple(
                self._session.execute(
                    select(RentalAccessoryUnitLink).where(
                        RentalAccessoryUnitLink.rental_id == rental_id,
                        RentalAccessoryUnitLink.accessory_type_id.in_(type_ids),
                    )
                )
                .scalars()
                .all()
            )
            if type_ids
            else ()
        )
        unit_to_type = {
            link.accessory_unit_id: link.accessory_type_id for link in current_links
        }
        future_links = (
            tuple(
                self._session.execute(
                    select(RentalAccessoryUnitLink).where(
                        RentalAccessoryUnitLink.accessory_unit_id.in_(
                            tuple(sorted(unit_to_type))
                        ),
                        RentalAccessoryUnitLink.rental_id != rental_id,
                        RentalAccessoryUnitLink.reservation_end_at > occurred_at,
                    )
                )
                .scalars()
                .all()
            )
            if unit_to_type
            else ()
        )
        affected_by_type: dict[int, set[int]] = {
            type_id: {rental_id} for type_id in type_ids
        }
        for link in future_links:
            type_id = unit_to_type.get(link.accessory_unit_id)
            if type_id is None or link.accessory_type_id != type_id:
                raise AccessoryRelayChainConflictError()
            affected_by_type[type_id].add(link.rental_id)
        affected_rental_ids = tuple(
            sorted(
                {
                    rental_id,
                    *(
                        affected_rental_id
                        for rental_ids in affected_by_type.values()
                        for affected_rental_id in rental_ids
                    ),
                }
            )
        )
        peeked_rentals = tuple(
            self._session.execute(
                select(Rental).where(Rental.id.in_(affected_rental_ids))
            )
            .scalars()
            .all()
        )
        if len(peeked_rentals) != len(affected_rental_ids):
            raise AccessoryRelayChainConflictError()
        device_ids = tuple(sorted({item.device_id for item in peeked_rentals}))
        devices = tuple(
            self._session.execute(
                select(Device)
                .where(Device.id.in_(device_ids))
                .order_by(Device.id.asc())
                .with_for_update()
            )
            .scalars()
            .all()
        )
        rentals = tuple(
            self._session.execute(
                select(Rental)
                .where(Rental.id.in_(affected_rental_ids))
                .order_by(Rental.id.asc())
                .with_for_update()
            )
            .scalars()
            .all()
        )
        if (
            len(devices) != len(device_ids)
            or len(rentals) != len(affected_rental_ids)
            or any(device.is_accessory is True for device in devices)
            or any(rental.parent_rental_id is not None for rental in rentals)
        ):
            raise AccessoryRelayChainConflictError()
        return AccessoryInspectionLockScope(
            rental_id=rental_id,
            affected_rentals_by_type=tuple(
                (type_id, tuple(sorted(affected_by_type[type_id])))
                for type_id in type_ids
            ),
        )

    @_hide_persistence_details
    def recompute_from_case(
        self,
        *,
        relay_case_id: int,
        actor_type: str,
        actor_id: Optional[str],
        operation_key: str,
    ) -> AccessoryRelayChainPlanResult:
        """Derive and persist the complete plan from one relay edge forward.

        The relay case must already contain its target status in this caller-
        owned transaction.  A pending/notified target removes its no-longer-
        reachable carried links; an agreed target propagates the predecessor's
        full logical-accessory set, including neutral carry-through links.
        Downstream agreed edges are always solved again from the new facts.
        """

        self._require_explicit_transaction()
        self._validate_common_inputs(
            relay_case_id=relay_case_id,
            actor_type=actor_type,
            actor_id=actor_id,
            operation_key=operation_key,
        )

        peeked_case = self._session.get(RentalRelayCase, relay_case_id)
        if peeked_case is None:
            raise AccessoryRelayChainInputError()
        peeked_predecessor = self._session.get(
            Rental,
            peeked_case.predecessor_rental_id,
        )
        if (
            peeked_predecessor is None
            or peeked_predecessor.parent_rental_id is not None
        ):
            raise AccessoryRelayChainConflictError()

        device = self._session.execute(
            select(Device)
            .where(Device.id == peeked_predecessor.device_id)
            .with_for_update()
        ).scalar_one_or_none()
        if device is None or device.is_accessory is True:
            raise AccessoryRelayChainConflictError()

        # Lock every main rental on the device.  The chain is then derived in
        # schedule order, independently of primary-key creation order.
        rentals = tuple(
            self._session.execute(
                select(Rental)
                .where(
                    Rental.device_id == device.id,
                    Rental.parent_rental_id.is_(None),
                )
                .order_by(Rental.id.asc())
                .with_for_update()
            )
            .scalars()
            .all()
        )
        rental_by_id = {rental.id: rental for rental in rentals}
        if peeked_case.predecessor_rental_id not in rental_by_id:
            raise AccessoryRelayChainConflictError()

        rental_ids = tuple(sorted(rental_by_id))
        relay_cases = tuple(
            self._session.execute(
                select(RentalRelayCase)
                .where(
                    RentalRelayCase.predecessor_rental_id.in_(rental_ids),
                    RentalRelayCase.successor_rental_id.in_(rental_ids),
                )
                .order_by(RentalRelayCase.id.asc())
                .with_for_update()
            )
            .scalars()
            .all()
        )
        case_by_id = {relay_case.id: relay_case for relay_case in relay_cases}
        relay_case = case_by_id.get(relay_case_id)
        if (
            relay_case is None
            or relay_case.predecessor_rental_id != peeked_case.predecessor_rental_id
            or relay_case.successor_rental_id != peeked_case.successor_rental_id
        ):
            raise AccessoryRelayChainConflictError()

        chain_cases, chain_rentals = self._derive_downstream_chain(
            relay_case=relay_case,
            relay_cases=relay_cases,
            rental_by_id=rental_by_id,
        )
        managed_rental_ids = tuple(edge.successor_rental_id for edge in chain_cases)
        scope_rental_ids = tuple(
            sorted(
                {
                    relay_case.predecessor_rental_id,
                    *managed_rental_ids,
                }
            )
        )

        # A handoff is an immutable physical fact.  A caller that has already
        # changed such an edge back to pending/notified is rejected here, so
        # the surrounding status mutation rolls back with the chain.
        executed_case_ids = set(
            self._session.execute(
                select(AccessoryUnitEvent.relay_case_id)
                .where(
                    AccessoryUnitEvent.relay_case_id.in_(
                        tuple(edge.id for edge in chain_cases)
                    ),
                    AccessoryUnitEvent.event_type == "relay_handoff",
                )
                .with_for_update()
            )
            .scalars()
            .all()
        )
        if any(
            edge.id in executed_case_ids and edge.status not in _EXECUTED_RELAY_STATUSES
            for edge in chain_cases
        ):
            raise AccessoryRelayChainConflictError()

        # Discover the small logical-type scope without returning or logging
        # unit identifiers.  Locked rentals serialize request/link mutations
        # that follow the SaaS mutation contract.
        type_ids = tuple(
            sorted(
                set(
                    self._session.execute(
                        select(RentalAccessoryRequest.accessory_type_id).where(
                            RentalAccessoryRequest.rental_id.in_(scope_rental_ids)
                        )
                    ).scalars()
                )
                | set(
                    self._session.execute(
                        select(RentalAccessoryUnitLink.accessory_type_id).where(
                            RentalAccessoryUnitLink.rental_id.in_(scope_rental_ids)
                        )
                    ).scalars()
                )
            )
        )
        if not type_ids:
            return AccessoryRelayChainPlanResult(0, 0, 0, ())

        accessory_types = tuple(
            self._session.execute(
                select(AccessoryType)
                .where(AccessoryType.id.in_(type_ids))
                .order_by(AccessoryType.id.asc())
                .with_for_update()
            )
            .scalars()
            .all()
        )
        type_by_id = {item.id: item for item in accessory_types}
        if set(type_by_id) != set(type_ids) or any(
            item.tracking_mode != "logical_unit" for item in accessory_types
        ):
            raise AccessoryRelayChainConflictError()

        # Lock all units for the scoped types.  This intentionally includes a
        # currently held unit: it may be planned for a later non-overlapping
        # order after its recorded reservation window, but it is never counted
        # as currently available.
        units = tuple(
            self._session.execute(
                select(AccessoryUnit)
                .where(AccessoryUnit.accessory_type_id.in_(type_ids))
                .order_by(
                    AccessoryUnit.accessory_type_id.asc(),
                    AccessoryUnit.id.asc(),
                )
                .with_for_update()
            )
            .scalars()
            .all()
        )
        unit_by_id = {unit.id: unit for unit in units}
        units_by_type: dict[int, list[AccessoryUnit]] = {
            type_id: [] for type_id in type_ids
        }
        for unit in units:
            units_by_type[unit.accessory_type_id].append(unit)

        requests = tuple(
            self._session.execute(
                select(RentalAccessoryRequest)
                .where(RentalAccessoryRequest.rental_id.in_(scope_rental_ids))
                .order_by(
                    RentalAccessoryRequest.rental_id.asc(),
                    RentalAccessoryRequest.accessory_type_id.asc(),
                )
                .with_for_update()
            )
            .scalars()
            .all()
        )
        # Every link for a locked unit is needed to prove non-overlap.  This
        # is the same unit-before-overlap-link lock direction used by ordinary
        # reservations.
        all_unit_links = tuple(
            self._session.execute(
                select(RentalAccessoryUnitLink)
                .where(
                    RentalAccessoryUnitLink.accessory_unit_id.in_(
                        tuple(sorted(unit_by_id))
                    )
                )
                .order_by(
                    RentalAccessoryUnitLink.accessory_type_id.asc(),
                    RentalAccessoryUnitLink.accessory_unit_id.asc(),
                    RentalAccessoryUnitLink.rental_id.asc(),
                )
                .with_for_update()
            )
            .scalars()
            .all()
        )
        link_by_key = {
            (link.rental_id, link.accessory_type_id): link
            for link in all_unit_links
            if link.rental_id in scope_rental_ids
        }
        if len(link_by_key) != sum(
            1 for link in all_unit_links if link.rental_id in scope_rental_ids
        ):
            raise AccessoryRelayChainConflictError()
        request_types_by_rental: dict[int, set[int]] = {
            rental_id: set() for rental_id in scope_rental_ids
        }
        for request in requests:
            request_types_by_rental[request.rental_id].add(request.accessory_type_id)

        planned_by_rental = self._derive_plan(
            device=device,
            chain_cases=chain_cases,
            chain_rentals=chain_rentals,
            request_types_by_rental=request_types_by_rental,
            current_link_by_key=link_by_key,
            units_by_type=units_by_type,
            all_unit_links=all_unit_links,
            managed_rental_ids=set(managed_rental_ids),
        )

        mutation_required = any(
            not self._same_link(
                link_by_key.get((rental.id, type_id)),
                planned_by_rental[rental.id].get(type_id),
            )
            for rental in chain_rentals[1:]
            for type_id in (
                {
                    linked_type_id
                    for (linked_rental_id, linked_type_id) in link_by_key
                    if linked_rental_id == rental.id
                }
                | set(planned_by_rental[rental.id])
            )
        )
        if (
            mutation_required
            and self._inventory_repository.fulfillment_execution_is_frozen(
                managed_rental_ids
            )
        ):
            raise AccessoryRelayChainConflictError()

        linked_count = 0
        unlinked_count = 0
        shortage_keys: set[tuple[int, int]] = set()
        case_by_successor = {edge.successor_rental_id: edge for edge in chain_cases}
        clean_actor_id = actor_id.strip() if actor_id is not None else None

        for rental in chain_rentals[1:]:
            desired_by_type = planned_by_rental[rental.id]
            existing_types = {
                type_id
                for (rental_id, type_id) in link_by_key
                if rental_id == rental.id
            }
            requested_types = request_types_by_rental.get(rental.id, set())
            shortage_keys.update(
                (rental.id, type_id)
                for type_id in requested_types - set(desired_by_type)
            )
            edge = case_by_successor[rental.id]
            for type_id in sorted(existing_types | set(desired_by_type)):
                existing = link_by_key.get((rental.id, type_id))
                desired = desired_by_type.get(type_id)
                if self._same_link(existing, desired):
                    continue
                if edge.status in _EXECUTED_RELAY_STATUSES:
                    raise AccessoryRelayChainConflictError()
                if existing is not None:
                    existing_unit = unit_by_id.get(existing.accessory_unit_id)
                    if existing_unit is None:
                        raise AccessoryRelayChainConflictError()
                    # A unit actually dispatched to this successor cannot be
                    # silently replaced by a newly derived travelling unit.
                    if existing_unit.current_holder_rental_id is not None and not (
                        existing.source_relay_case_id is not None
                        and existing_unit.current_holder_rental_id != rental.id
                        and existing.source_relay_case_id not in executed_case_ids
                    ):
                        raise AccessoryRelayChainConflictError()
                    self._session.add(
                        self._event(
                            unit=existing_unit,
                            event_type="unlinked",
                            device_id=device.id,
                            rental_id=rental.id,
                            relay_case_id=(existing.source_relay_case_id or edge.id),
                            actor_type=actor_type.strip(),
                            actor_id=clean_actor_id,
                            operation_key=operation_key,
                            action_token="unlinked",
                            accessory_type_id=type_id,
                        )
                    )
                    unlinked_count += 1
                if desired is None:
                    if existing is not None:
                        self._session.delete(existing)
                        link_by_key.pop((rental.id, type_id), None)
                    continue

                if existing is None:
                    existing = RentalAccessoryUnitLink(
                        rental_id=rental.id,
                        accessory_type_id=type_id,
                        accessory_unit_id=desired.unit.id,
                        reservation_start_at=desired.reservation_start_at,
                        reservation_end_at=desired.reservation_end_at,
                        source_relay_case_id=desired.source_relay_case_id,
                    )
                    self._session.add(existing)
                    link_by_key[(rental.id, type_id)] = existing
                else:
                    existing.accessory_unit_id = desired.unit.id
                    existing.reservation_start_at = desired.reservation_start_at
                    existing.reservation_end_at = desired.reservation_end_at
                    existing.source_relay_case_id = desired.source_relay_case_id
                self._session.add(
                    self._event(
                        unit=desired.unit,
                        event_type="linked",
                        device_id=device.id,
                        rental_id=rental.id,
                        relay_case_id=desired.source_relay_case_id,
                        actor_type=actor_type.strip(),
                        actor_id=clean_actor_id,
                        operation_key=operation_key,
                        action_token="linked",
                        accessory_type_id=type_id,
                    )
                )
                linked_count += 1

        try:
            self._session.flush()
        except IntegrityError:
            raise AccessoryRelayChainPersistenceError() from None

        shortage_codes = tuple(
            sorted({type_by_id[type_id].name for _, type_id in shortage_keys})
        )
        return AccessoryRelayChainPlanResult(
            linked_count=linked_count,
            unlinked_count=unlinked_count,
            shortage_count=len(shortage_keys),
            shortage_type_codes=shortage_codes,
        )

    @_hide_persistence_details
    def inspect_return_and_reassign(
        self,
        *,
        rental_id: int,
        accessory_type_id: int,
        warehouse_id: int,
        outcome: str,
        occurred_at: datetime,
        actor_type: str,
        actor_id: Optional[str],
        operation_key: str,
        expected_affected_rental_ids: Sequence[int] | None = None,
    ) -> AccessoryInspectionReassignmentResult:
        """Apply one receipt and atomically repair its future link graph.

        A normal receipt may retain the exact same-device chain reachable
        through consecutive ``agreed`` edges.  Every other future link to the
        received unit is removed and, when it represents a request, is
        deterministically reassigned from that rental's main-device warehouse.
        No candidate leaves the request without a link and reports a shortage;
        the receipt and real warehouse move still commit.
        """

        self._require_explicit_transaction()
        self._validate_inspection_inputs(
            rental_id=rental_id,
            accessory_type_id=accessory_type_id,
            warehouse_id=warehouse_id,
            outcome=outcome,
            occurred_at=occurred_at,
            actor_type=actor_type,
            actor_id=actor_id,
            operation_key=operation_key,
        )

        peeked_rental = self._session.get(Rental, rental_id)
        peeked_link = self._session.execute(
            select(RentalAccessoryUnitLink).where(
                RentalAccessoryUnitLink.rental_id == rental_id,
                RentalAccessoryUnitLink.accessory_type_id == accessory_type_id,
            )
        ).scalar_one_or_none()
        if (
            peeked_rental is None
            or peeked_rental.parent_rental_id is not None
            or peeked_link is None
        ):
            raise AccessoryRelayChainConflictError()

        peeked_future_links = tuple(
            self._session.execute(
                select(RentalAccessoryUnitLink).where(
                    RentalAccessoryUnitLink.accessory_unit_id
                    == peeked_link.accessory_unit_id,
                    RentalAccessoryUnitLink.rental_id != rental_id,
                    RentalAccessoryUnitLink.reservation_end_at > occurred_at,
                )
            )
            .scalars()
            .all()
        )
        affected_rental_ids = tuple(
            sorted(
                {
                    rental_id,
                    *(link.rental_id for link in peeked_future_links),
                }
            )
        )
        if expected_affected_rental_ids is not None and affected_rental_ids != tuple(
            sorted(set(expected_affected_rental_ids))
        ):
            raise AccessoryRelayChainConflictError()
        peeked_rentals = tuple(
            self._session.execute(
                select(Rental).where(Rental.id.in_(affected_rental_ids))
            )
            .scalars()
            .all()
        )
        if len(peeked_rentals) != len(affected_rental_ids):
            raise AccessoryRelayChainConflictError()
        device_ids = tuple(sorted({item.device_id for item in peeked_rentals}))
        devices = tuple(
            self._session.execute(
                select(Device)
                .where(Device.id.in_(device_ids))
                .order_by(Device.id.asc())
                .with_for_update()
            )
            .scalars()
            .all()
        )
        device_by_id = {device.id: device for device in devices}
        if len(device_by_id) != len(device_ids):
            raise AccessoryRelayChainConflictError()

        rentals = tuple(
            self._session.execute(
                select(Rental)
                .where(Rental.id.in_(affected_rental_ids))
                .order_by(Rental.id.asc())
                .with_for_update()
            )
            .scalars()
            .all()
        )
        rental_by_id = {item.id: item for item in rentals}
        rental = rental_by_id.get(rental_id)
        if (
            rental is None
            or rental.parent_rental_id is not None
            or rental.device_id != peeked_rental.device_id
            or any(item.parent_rental_id is not None for item in rentals)
            or device_by_id[rental.device_id].warehouse_id != warehouse_id
            or any(device.is_accessory is True for device in devices)
        ):
            raise AccessoryRelayChainConflictError()

        warehouse_ids = tuple(
            sorted(
                {
                    warehouse_id,
                    *(
                        device.warehouse_id
                        for device in devices
                        if device.warehouse_id is not None
                    ),
                }
            )
        )
        warehouses = tuple(
            self._session.execute(
                select(Warehouse)
                .where(Warehouse.id.in_(warehouse_ids))
                .order_by(Warehouse.is_default.desc(), Warehouse.id.asc())
                .with_for_update()
            )
            .scalars()
            .all()
        )
        warehouse_by_id = {item.id: item for item in warehouses}
        target_warehouse = warehouse_by_id.get(warehouse_id)
        if (
            target_warehouse is None
            or target_warehouse.status != "active"
            or target_warehouse.setup_state != "ready"
        ):
            raise AccessoryRelayChainConflictError()

        relay_cases = tuple(
            self._session.execute(
                select(RentalRelayCase)
                .where(
                    RentalRelayCase.predecessor_rental_id.in_(affected_rental_ids),
                    RentalRelayCase.successor_rental_id.in_(affected_rental_ids),
                )
                .order_by(RentalRelayCase.id.asc())
                .with_for_update()
            )
            .scalars()
            .all()
        )
        accessory_type = self._session.execute(
            select(AccessoryType)
            .where(AccessoryType.id == accessory_type_id)
            .with_for_update()
        ).scalar_one_or_none()
        if accessory_type is None or accessory_type.tracking_mode != "logical_unit":
            raise AccessoryRelayChainConflictError()

        units = tuple(
            self._session.execute(
                select(AccessoryUnit)
                .where(AccessoryUnit.accessory_type_id == accessory_type_id)
                .order_by(AccessoryUnit.id.asc())
                .with_for_update()
            )
            .scalars()
            .all()
        )
        unit_by_id = {unit.id: unit for unit in units}
        inspected_unit = unit_by_id.get(peeked_link.accessory_unit_id)
        if inspected_unit is None:
            raise AccessoryRelayChainConflictError()

        requests = tuple(
            self._session.execute(
                select(RentalAccessoryRequest)
                .where(
                    RentalAccessoryRequest.rental_id.in_(affected_rental_ids),
                    RentalAccessoryRequest.accessory_type_id == accessory_type_id,
                )
                .order_by(RentalAccessoryRequest.rental_id.asc())
                .with_for_update()
            )
            .scalars()
            .all()
        )
        request_by_rental_id = {item.rental_id: item for item in requests}
        all_links = tuple(
            self._session.execute(
                select(RentalAccessoryUnitLink)
                .where(
                    RentalAccessoryUnitLink.accessory_unit_id.in_(
                        tuple(sorted(unit_by_id))
                    )
                )
                .order_by(
                    RentalAccessoryUnitLink.accessory_unit_id.asc(),
                    RentalAccessoryUnitLink.rental_id.asc(),
                )
                .with_for_update()
            )
            .scalars()
            .all()
        )
        current_link = next(
            (
                link
                for link in all_links
                if link.rental_id == rental_id
                and link.accessory_type_id == accessory_type_id
            ),
            None,
        )
        future_links = tuple(
            link
            for link in all_links
            if link.accessory_unit_id == inspected_unit.id
            and link.rental_id != rental_id
            and link.reservation_end_at > occurred_at
        )
        if (
            current_link is None
            or current_link.accessory_unit_id != inspected_unit.id
            or tuple(sorted((link.rental_id, link.id) for link in future_links))
            != tuple(sorted((link.rental_id, link.id) for link in peeked_future_links))
            or inspected_unit.current_holder_rental_id != rental_id
        ):
            raise AccessoryRelayChainConflictError()

        retained_link_ids = self._reachable_inspection_relay_link_ids(
            outcome=outcome,
            starting_rental=rental,
            inspected_unit=inspected_unit,
            future_links=future_links,
            relay_cases=relay_cases,
            rental_by_id=rental_by_id,
        )
        managed_links = tuple(
            link for link in future_links if link.id not in retained_link_ids
        )
        managed_link_ids = {link.id for link in managed_links}

        desired_units: dict[str, AccessoryUnit] = {}
        occupied: dict[str, list[tuple[datetime, datetime]]] = {
            unit.id: [] for unit in units
        }
        for link in all_links:
            if link.id in managed_link_ids or link.id == current_link.id:
                continue
            occupied[link.accessory_unit_id].append(
                (link.reservation_start_at, link.reservation_end_at)
            )

        for link in sorted(
            managed_links,
            key=lambda item: (
                item.reservation_start_at,
                item.rental_id,
                item.id,
            ),
        ):
            request = request_by_rental_id.get(link.rental_id)
            future_rental = rental_by_id[link.rental_id]
            future_device = device_by_id.get(future_rental.device_id)
            future_warehouse = (
                warehouse_by_id.get(future_device.warehouse_id)
                if future_device is not None and future_device.warehouse_id is not None
                else None
            )
            if (
                request is None
                or future_device is None
                or future_warehouse is None
                or future_warehouse.status != "active"
                or future_warehouse.setup_state != "ready"
            ):
                continue
            window = (link.reservation_start_at, link.reservation_end_at)
            candidate = next(
                (
                    unit
                    for unit in units
                    if self._inspection_candidate_available(
                        unit=unit,
                        inspected_unit=inspected_unit,
                        inspection_outcome=outcome,
                        target_warehouse_id=warehouse_id,
                        required_warehouse_id=future_device.warehouse_id,
                        window=window,
                        occupied=occupied[unit.id],
                    )
                ),
                None,
            )
            if candidate is not None:
                desired_units[link.id] = candidate
                occupied[candidate.id].append(window)

        mutation_rental_ids = tuple(sorted(link.rental_id for link in managed_links))
        if (
            mutation_rental_ids
            and self._inventory_repository.fulfillment_execution_is_frozen(
                mutation_rental_ids
            )
        ):
            raise AccessoryRelayChainConflictError()

        clean_actor_id = actor_id.strip() if actor_id is not None else None
        from_warehouse_id = inspected_unit.warehouse_id
        if outcome == "missing":
            inspected_unit.condition_status = "lost"
            inspected_unit.row_version += 1
            self._session.add(
                self._inspection_event(
                    unit=inspected_unit,
                    event_type="lost",
                    device_id=rental.device_id,
                    rental_id=rental.id,
                    from_warehouse_id=from_warehouse_id,
                    from_holder_rental_id=rental.id,
                    to_holder_rental_id=rental.id,
                    actor_type=actor_type.strip(),
                    actor_id=clean_actor_id,
                    reason="missing_on_inspection",
                    operation_key=operation_key,
                    action_token="lost",
                )
            )
        else:
            inspected_unit.current_holder_rental_id = None
            inspected_unit.warehouse_id = warehouse_id
            inspected_unit.condition_status = (
                "active" if outcome == "received_normal" else "maintenance"
            )
            inspected_unit.row_version += 1
            self._session.add(
                self._inspection_event(
                    unit=inspected_unit,
                    event_type="inspected",
                    device_id=rental.device_id,
                    rental_id=rental.id,
                    from_warehouse_id=from_warehouse_id,
                    to_warehouse_id=warehouse_id,
                    from_holder_rental_id=rental.id,
                    actor_type=actor_type.strip(),
                    actor_id=clean_actor_id,
                    reason=(
                        "returned_normal"
                        if outcome == "received_normal"
                        else "returned_damaged"
                    ),
                    operation_key=operation_key,
                    action_token="inspected",
                )
            )
            if outcome == "received_damaged":
                self._session.add(
                    self._inspection_event(
                        unit=inspected_unit,
                        event_type="maintenance",
                        device_id=rental.device_id,
                        rental_id=rental.id,
                        to_warehouse_id=warehouse_id,
                        actor_type=actor_type.strip(),
                        actor_id=clean_actor_id,
                        reason="damaged_on_inspection",
                        operation_key=operation_key,
                        action_token="maintenance",
                    )
                )
            if from_warehouse_id != warehouse_id:
                self._session.add(
                    self._inspection_event(
                        unit=inspected_unit,
                        event_type="warehouse_moved",
                        device_id=rental.device_id,
                        rental_id=rental.id,
                        from_warehouse_id=from_warehouse_id,
                        to_warehouse_id=warehouse_id,
                        actor_type=actor_type.strip(),
                        actor_id=clean_actor_id,
                        reason="inspection_receipt",
                        operation_key=operation_key,
                        action_token="warehouse-moved",
                    )
                )

        reassigned_count = 0
        shortage_count = 0
        shortage_rental_ids: list[int] = []
        for link in managed_links:
            self._session.add(
                self._inspection_event(
                    unit=inspected_unit,
                    event_type="unlinked",
                    device_id=rental_by_id[link.rental_id].device_id,
                    rental_id=link.rental_id,
                    relay_case_id=link.source_relay_case_id,
                    actor_type=actor_type.strip(),
                    actor_id=clean_actor_id,
                    reason="inspection_future_reassignment",
                    operation_key=operation_key,
                    action_token=f"unlinked:{link.rental_id}",
                )
            )
            desired = desired_units.get(link.id)
            if desired is None:
                self._session.delete(link)
                if link.rental_id in request_by_rental_id:
                    shortage_count += 1
                    shortage_rental_ids.append(link.rental_id)
                continue
            link.accessory_unit_id = desired.id
            link.source_relay_case_id = None
            self._session.add(
                self._inspection_event(
                    unit=desired,
                    event_type="linked",
                    device_id=rental_by_id[link.rental_id].device_id,
                    rental_id=link.rental_id,
                    to_warehouse_id=desired.warehouse_id,
                    actor_type=actor_type.strip(),
                    actor_id=clean_actor_id,
                    reason="inspection_future_reassignment",
                    operation_key=operation_key,
                    action_token=f"linked:{link.rental_id}",
                )
            )
            reassigned_count += 1

        try:
            self._session.flush()
        except IntegrityError:
            raise AccessoryRelayChainPersistenceError() from None
        return AccessoryInspectionReassignmentResult(
            type_code=accessory_type.name,
            display_name=accessory_type.display_name,
            outcome=outcome,
            retained_relay_count=len(retained_link_ids),
            reassigned_count=reassigned_count,
            shortage_count=shortage_count,
            affected_rental_ids=tuple(
                sorted({link.rental_id for link in managed_links})
            ),
            shortage_rental_ids=tuple(sorted(set(shortage_rental_ids))),
        )

    @_hide_persistence_details
    def handoff_case(
        self,
        *,
        relay_case_id: int,
        actor_type: str,
        actor_id: Optional[str],
        operation_key: str,
    ) -> AccessoryRelayHandoffResult:
        """Transfer every unit linked through one agreed relay edge.

        Call this before changing the relay case from ``agreed`` to ``shipped``
        in the same transaction.  The lower-level handoff verifies the exact
        predecessor holder, successor link, source edge, and idempotency event.
        """

        self._require_explicit_transaction()
        self._validate_common_inputs(
            relay_case_id=relay_case_id,
            actor_type=actor_type,
            actor_id=actor_id,
            operation_key=operation_key,
        )
        peeked_case = self._session.get(RentalRelayCase, relay_case_id)
        if peeked_case is None:
            raise AccessoryRelayChainInputError()
        peeked_predecessor = self._session.get(
            Rental,
            peeked_case.predecessor_rental_id,
        )
        if (
            peeked_predecessor is None
            or peeked_predecessor.parent_rental_id is not None
        ):
            raise AccessoryRelayChainConflictError()
        device = self._session.execute(
            select(Device)
            .where(Device.id == peeked_predecessor.device_id)
            .with_for_update()
        ).scalar_one_or_none()
        rentals = tuple(
            self._session.execute(
                select(Rental)
                .where(
                    Rental.id.in_(
                        (
                            peeked_case.predecessor_rental_id,
                            peeked_case.successor_rental_id,
                        )
                    )
                )
                .order_by(Rental.id.asc())
                .with_for_update()
            )
            .scalars()
            .all()
        )
        relay_case = self._session.execute(
            select(RentalRelayCase)
            .where(RentalRelayCase.id == relay_case_id)
            .with_for_update()
        ).scalar_one_or_none()
        rental_by_id = {rental.id: rental for rental in rentals}
        predecessor = rental_by_id.get(peeked_case.predecessor_rental_id)
        successor = rental_by_id.get(peeked_case.successor_rental_id)
        if (
            device is None
            or device.is_accessory is True
            or relay_case is None
            or predecessor is None
            or successor is None
            or predecessor.parent_rental_id is not None
            or successor.parent_rental_id is not None
            or predecessor.device_id != device.id
            or successor.device_id != device.id
            or relay_case.predecessor_rental_id != predecessor.id
            or relay_case.successor_rental_id != successor.id
        ):
            raise AccessoryRelayChainConflictError()
        type_ids = tuple(
            self._session.execute(
                select(RentalAccessoryUnitLink.accessory_type_id)
                .where(
                    RentalAccessoryUnitLink.rental_id == relay_case.successor_rental_id,
                    RentalAccessoryUnitLink.source_relay_case_id == relay_case.id,
                )
                .order_by(RentalAccessoryUnitLink.accessory_type_id.asc())
            )
            .scalars()
            .all()
        )
        if len(type_ids) != len(set(type_ids)):
            raise AccessoryRelayChainConflictError()

        inventory = AccessoryInventoryService(
            self._session,
            repository=self._inventory_repository,
        )
        type_codes: list[str] = []
        for type_id in type_ids:
            counts = inventory.handoff_for_relay(
                relay_case_id=relay_case.id,
                accessory_type_id=type_id,
                actor_type=actor_type,
                actor_id=actor_id,
                operation_key=operation_key,
            )
            type_codes.append(counts.type_code)
        return AccessoryRelayHandoffResult(
            handed_off_count=len(type_codes),
            accessory_type_codes=tuple(sorted(type_codes)),
        )

    @staticmethod
    def _reachable_inspection_relay_link_ids(
        *,
        outcome: str,
        starting_rental: Rental,
        inspected_unit: AccessoryUnit,
        future_links: Sequence[RentalAccessoryUnitLink],
        relay_cases: Sequence[RentalRelayCase],
        rental_by_id: dict[int, Rental],
    ) -> set[str]:
        if outcome != "received_normal":
            return set()
        case_by_predecessor: dict[int, RentalRelayCase] = {}
        for edge in relay_cases:
            if edge.status != "agreed":
                continue
            prior = case_by_predecessor.get(edge.predecessor_rental_id)
            if prior is not None and prior.id != edge.id:
                raise AccessoryRelayChainConflictError()
            case_by_predecessor[edge.predecessor_rental_id] = edge
        link_by_rental = {link.rental_id: link for link in future_links}
        if len(link_by_rental) != len(future_links):
            raise AccessoryRelayChainConflictError()

        retained: set[str] = set()
        current = starting_rental
        visited = {current.id}
        while True:
            edge = case_by_predecessor.get(current.id)
            if edge is None:
                break
            successor = rental_by_id.get(edge.successor_rental_id)
            link = link_by_rental.get(edge.successor_rental_id)
            if (
                successor is None
                or successor.id in visited
                or successor.device_id != starting_rental.device_id
                or link is None
                or link.accessory_unit_id != inspected_unit.id
                or link.source_relay_case_id != edge.id
            ):
                break
            retained.add(link.id)
            visited.add(successor.id)
            current = successor
        return retained

    @staticmethod
    def _inspection_candidate_available(
        *,
        unit: AccessoryUnit,
        inspected_unit: AccessoryUnit,
        inspection_outcome: str,
        target_warehouse_id: int,
        required_warehouse_id: Optional[int],
        window: tuple[datetime, datetime],
        occupied: Sequence[tuple[datetime, datetime]],
    ) -> bool:
        if required_warehouse_id is None:
            return False
        if unit.id == inspected_unit.id:
            usable = (
                inspection_outcome == "received_normal"
                and target_warehouse_id == required_warehouse_id
            )
        else:
            usable = (
                unit.condition_status == "active"
                and unit.current_holder_rental_id is None
                and unit.warehouse_id == required_warehouse_id
            )
        return usable and not any(
            occupied_start < window[1] and occupied_end > window[0]
            for occupied_start, occupied_end in occupied
        )

    @staticmethod
    def _inspection_event(
        *,
        unit: AccessoryUnit,
        event_type: str,
        device_id: int,
        rental_id: int,
        actor_type: str,
        actor_id: Optional[str],
        reason: str,
        operation_key: str,
        action_token: str,
        relay_case_id: Optional[int] = None,
        from_warehouse_id: Optional[int] = None,
        to_warehouse_id: Optional[int] = None,
        from_holder_rental_id: Optional[int] = None,
        to_holder_rental_id: Optional[int] = None,
    ) -> AccessoryUnitEvent:
        digest = sha256(
            "\x1f".join(
                (
                    "inspection-reassignment-v1",
                    operation_key,
                    str(rental_id),
                    str(unit.accessory_type_id),
                    action_token,
                    unit.id,
                )
            ).encode("utf-8")
        ).hexdigest()
        return AccessoryUnitEvent(
            unit_id=unit.id,
            event_type=event_type,
            main_device_id=device_id,
            rental_id=rental_id,
            relay_case_id=relay_case_id,
            from_warehouse_id=from_warehouse_id,
            to_warehouse_id=to_warehouse_id,
            from_holder_rental_id=from_holder_rental_id,
            to_holder_rental_id=to_holder_rental_id,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            idempotency_key=f"inspection-reassignment:{digest}",
        )

    @staticmethod
    def _validate_inspection_inputs(
        *,
        rental_id: int,
        accessory_type_id: int,
        warehouse_id: int,
        outcome: str,
        occurred_at: datetime,
        actor_type: str,
        actor_id: Optional[str],
        operation_key: str,
    ) -> None:
        if (
            any(
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
                for value in (rental_id, accessory_type_id, warehouse_id)
            )
            or outcome not in {"received_normal", "received_damaged", "missing"}
            or not isinstance(occurred_at, datetime)
            or not isinstance(actor_type, str)
            or not actor_type.strip()
            or len(actor_type.strip()) > 32
            or not isinstance(operation_key, str)
            or not operation_key.strip()
            or (
                actor_id is not None
                and (
                    not isinstance(actor_id, str)
                    or not actor_id.strip()
                    or len(actor_id.strip()) > 64
                )
            )
        ):
            raise AccessoryRelayChainInputError()

    def _derive_plan(
        self,
        *,
        device: Device,
        chain_cases: Sequence[RentalRelayCase],
        chain_rentals: Sequence[Rental],
        request_types_by_rental: dict[int, set[int]],
        current_link_by_key: dict[tuple[int, int], RentalAccessoryUnitLink],
        units_by_type: dict[int, list[AccessoryUnit]],
        all_unit_links: Sequence[RentalAccessoryUnitLink],
        managed_rental_ids: set[int],
    ) -> dict[int, dict[int, _PlannedLink]]:
        planned: dict[int, dict[int, _PlannedLink]] = {}
        anchor = chain_rentals[0]
        anchor_window = self._rental_window(anchor)
        planned[anchor.id] = {}
        for (rental_id, type_id), link in current_link_by_key.items():
            if rental_id != anchor.id:
                continue
            unit = next(
                (
                    unit
                    for unit in units_by_type.get(type_id, ())
                    if unit.id == link.accessory_unit_id
                ),
                None,
            )
            if unit is None or unit.condition_status != "active":
                raise AccessoryRelayChainConflictError()
            planned[anchor.id][type_id] = _PlannedLink(
                unit=unit,
                source_relay_case_id=link.source_relay_case_id,
                reservation_start_at=link.reservation_start_at,
                reservation_end_at=link.reservation_end_at,
            )
        # The anchor window is validated even when it has no logical links.
        del anchor_window

        external_links = tuple(
            link for link in all_unit_links if link.rental_id not in managed_rental_ids
        )
        for index, edge in enumerate(chain_cases):
            predecessor = chain_rentals[index]
            successor = chain_rentals[index + 1]
            window = self._rental_window(successor)
            desired: dict[int, _PlannedLink] = {}
            if edge.status in _ACTIVE_RELAY_STATUSES:
                for type_id, predecessor_plan in planned[predecessor.id].items():
                    desired[type_id] = _PlannedLink(
                        unit=predecessor_plan.unit,
                        source_relay_case_id=edge.id,
                        reservation_start_at=window[0],
                        reservation_end_at=window[1],
                    )

            for type_id in sorted(request_types_by_rental.get(successor.id, set())):
                if type_id in desired:
                    continue
                existing = current_link_by_key.get((successor.id, type_id))
                candidates = units_by_type.get(type_id, ())
                preferred = next(
                    (
                        unit
                        for unit in candidates
                        if (
                            existing is not None
                            and existing.source_relay_case_id is None
                            and unit.id == existing.accessory_unit_id
                        )
                    ),
                    None,
                )
                ordered_candidates = ([preferred] if preferred is not None else []) + [
                    unit for unit in candidates if unit is not preferred
                ]
                unit = next(
                    (
                        candidate
                        for candidate in ordered_candidates
                        if self._unit_can_serve_local_plan(
                            unit=candidate,
                            warehouse_id=device.warehouse_id,
                            reservation_start_at=window[0],
                            reservation_end_at=window[1],
                            external_links=external_links,
                            prior_plans=planned,
                        )
                    ),
                    None,
                )
                if unit is not None:
                    desired[type_id] = _PlannedLink(
                        unit=unit,
                        source_relay_case_id=None,
                        reservation_start_at=window[0],
                        reservation_end_at=window[1],
                    )
            planned[successor.id] = desired
        return planned

    @staticmethod
    def _unit_can_serve_local_plan(
        *,
        unit: AccessoryUnit,
        warehouse_id: Optional[int],
        reservation_start_at: datetime,
        reservation_end_at: datetime,
        external_links: Sequence[RentalAccessoryUnitLink],
        prior_plans: dict[int, dict[int, _PlannedLink]],
    ) -> bool:
        if (
            warehouse_id is None
            or unit.warehouse_id != warehouse_id
            or unit.condition_status != "active"
        ):
            return False
        unit_external_links = tuple(
            link for link in external_links if link.accessory_unit_id == unit.id
        )
        if any(
            link.reservation_start_at < reservation_end_at
            and link.reservation_end_at > reservation_start_at
            for link in unit_external_links
        ):
            return False
        if any(
            plan.unit.id == unit.id
            and plan.reservation_start_at < reservation_end_at
            and plan.reservation_end_at > reservation_start_at
            for rental_plan in prior_plans.values()
            for plan in rental_plan.values()
        ):
            return False
        if unit.current_holder_rental_id is None:
            return True
        # A held unit can only be planned beyond its holder's already-linked
        # expected return.  It still remains absent from current availability.
        holder_links = tuple(
            link
            for link in unit_external_links
            if link.rental_id == unit.current_holder_rental_id
        )
        return (
            bool(holder_links)
            and max(link.reservation_end_at for link in holder_links)
            <= reservation_start_at
        )

    @staticmethod
    def _derive_downstream_chain(
        *,
        relay_case: RentalRelayCase,
        relay_cases: Sequence[RentalRelayCase],
        rental_by_id: dict[int, Rental],
    ) -> tuple[tuple[RentalRelayCase, ...], tuple[Rental, ...]]:
        case_by_predecessor: dict[int, RentalRelayCase] = {}
        for edge in relay_cases:
            existing = case_by_predecessor.get(edge.predecessor_rental_id)
            if existing is not None and existing.id != edge.id:
                raise AccessoryRelayChainConflictError()
            case_by_predecessor[edge.predecessor_rental_id] = edge

        chain_cases: list[RentalRelayCase] = []
        chain_rentals: list[Rental] = [rental_by_id[relay_case.predecessor_rental_id]]
        edge: Optional[RentalRelayCase] = relay_case
        seen_rental_ids = {relay_case.predecessor_rental_id}
        while edge is not None:
            predecessor = rental_by_id.get(edge.predecessor_rental_id)
            successor = rental_by_id.get(edge.successor_rental_id)
            if (
                predecessor is None
                or successor is None
                or predecessor.device_id != successor.device_id
                or successor.id in seen_rental_ids
                or AccessoryRelayChainService._schedule_key(predecessor)
                >= AccessoryRelayChainService._schedule_key(successor)
            ):
                raise AccessoryRelayChainConflictError()
            chain_cases.append(edge)
            chain_rentals.append(successor)
            seen_rental_ids.add(successor.id)
            edge = case_by_predecessor.get(successor.id)
        return tuple(chain_cases), tuple(chain_rentals)

    @staticmethod
    def _schedule_key(rental: Rental) -> tuple:
        return (
            rental.planned_ship_out_date or rental.start_date,
            rental.start_date,
            rental.id,
        )

    @staticmethod
    def _rental_window(rental: Rental) -> tuple[datetime, datetime]:
        if (
            rental.parent_rental_id is not None
            or rental.planned_ship_out_date is None
            or rental.planned_return_date is None
            or rental.planned_ship_out_date >= rental.planned_return_date
        ):
            raise AccessoryRelayChainConflictError()
        return (
            datetime.combine(rental.planned_ship_out_date, time.min),
            datetime.combine(
                rental.planned_return_date + timedelta(days=1),
                time.min,
            ),
        )

    @staticmethod
    def _same_link(
        existing: Optional[RentalAccessoryUnitLink],
        desired: Optional[_PlannedLink],
    ) -> bool:
        if existing is None or desired is None:
            return existing is None and desired is None
        return (
            existing.accessory_unit_id == desired.unit.id
            and existing.source_relay_case_id == desired.source_relay_case_id
            and existing.reservation_start_at == desired.reservation_start_at
            and existing.reservation_end_at == desired.reservation_end_at
        )

    @staticmethod
    def _event(
        *,
        unit: AccessoryUnit,
        event_type: str,
        device_id: int,
        rental_id: int,
        relay_case_id: Optional[int],
        actor_type: str,
        actor_id: Optional[str],
        operation_key: str,
        action_token: str,
        accessory_type_id: int,
    ) -> AccessoryUnitEvent:
        digest = sha256(
            "\x1f".join(
                (
                    "relay-chain-v1",
                    operation_key,
                    action_token,
                    str(rental_id),
                    str(accessory_type_id),
                    str(relay_case_id or 0),
                    unit.id,
                )
            ).encode("utf-8")
        ).hexdigest()
        return AccessoryUnitEvent(
            unit_id=unit.id,
            event_type=event_type,
            main_device_id=device_id,
            rental_id=rental_id,
            relay_case_id=relay_case_id,
            actor_type=actor_type,
            actor_id=actor_id,
            reason="relay_chain_recalculation",
            idempotency_key=f"relay-chain:{digest}",
        )

    def _require_explicit_transaction(self) -> None:
        require_caller_transaction(
            self._session,
            AccessoryRelayChainTransactionRequiredError,
            accept_nested=True,
        )

    @staticmethod
    def _validate_common_inputs(
        *,
        relay_case_id: int,
        actor_type: str,
        actor_id: Optional[str],
        operation_key: str,
    ) -> None:
        if (
            isinstance(relay_case_id, bool)
            or not isinstance(relay_case_id, int)
            or relay_case_id <= 0
            or not isinstance(actor_type, str)
            or not actor_type.strip()
            or len(actor_type.strip()) > 32
            or not isinstance(operation_key, str)
            or not operation_key.strip()
            or (
                actor_id is not None
                and (
                    not isinstance(actor_id, str)
                    or not actor_id.strip()
                    or len(actor_id.strip()) > 64
                )
            )
        ):
            raise AccessoryRelayChainInputError()


__all__ = [
    "AccessoryInspectionLockScope",
    "AccessoryInspectionReassignmentResult",
    "AccessoryRelayChainConflictError",
    "AccessoryRelayChainError",
    "AccessoryRelayChainInputError",
    "AccessoryRelayChainPersistenceError",
    "AccessoryRelayChainPlanResult",
    "AccessoryRelayChainService",
    "AccessoryRelayChainTransactionRequiredError",
    "AccessoryRelayHandoffResult",
]
