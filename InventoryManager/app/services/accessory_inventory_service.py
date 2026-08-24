"""Transactional logical-accessory inventory operations.

The caller owns the tenant-database transaction.  Mutation methods require an
explicit ``Session.begin()`` transaction, flush their changes, and never
commit or roll back.  If a mutation raises, the caller must roll back the
whole transaction so its surrounding rental/device changes remain atomic.

Logical unit and link UUIDs are deliberately confined to this module and the
ORM repository.  Public result objects contain only accessory type metadata
and realtime aggregate counts; errors contain stable codes and generic text.

MySQL 8 and MariaDB enforce the contention boundary through
``SELECT .. FOR UPDATE`` on candidate units ordered by accessory type and unit
UUID.  SQL-backed tests use the same locking implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from hashlib import sha256
from typing import Iterable, Optional, Sequence

from sqlalchemy import and_, case, exists, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.accessory_inventory import (
    AccessoryType,
    AccessoryUnit,
    AccessoryUnitEvent,
    DeviceAccessoryConfig,
    RentalAccessoryRequest,
    RentalAccessoryUnitLink,
)
from app.models.device import Device
from app.models.rental import Rental
from app.models.rental_relay_case import RentalRelayCase
from app.models.shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
    WaybillPrintJob,
)
from app.models.warehouse import Warehouse
from inventory_control.transactions import require_caller_transaction


_FROZEN_PROVIDER_ATTEMPT_STATUSES = (
    "provider_submitting",
    "succeeded",
    "unknown",
    "needs_review",
)
_FROZEN_PRINT_JOB_STATUSES = (
    "provider_submitting",
    "printed",
    "unknown",
    "needs_review",
)
_UNSETTLED_PROVIDER_ATTEMPT_STATUSES = (
    "provider_submitting",
    "unknown",
    "needs_review",
)
_UNSETTLED_PRINT_JOB_STATUSES = (
    "provider_submitting",
    "unknown",
    "needs_review",
)
_FROZEN_SHIPMENT_STATUSES = (
    "provider_submitting",
    "submitted",
    "cancel_requested",
    "cancel_unknown",
    "needs_review",
)


class AccessoryInventoryError(RuntimeError):
    """Base rejection with a safe, stable public code and message."""

    code = "ACCESSORY_INVENTORY_ERROR"
    public_message = "accessory inventory operation failed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class AccessoryTransactionRequiredError(AccessoryInventoryError):
    code = "ACCESSORY_TRANSACTION_REQUIRED"
    public_message = "an explicit caller-owned transaction is required"


class AccessoryInputError(AccessoryInventoryError):
    code = "ACCESSORY_INPUT_INVALID"
    public_message = "accessory inventory input is invalid"


class AccessoryTypeUnavailableError(AccessoryInventoryError):
    code = "ACCESSORY_TYPE_UNAVAILABLE"
    public_message = "accessory type is unavailable"


class AccessoryWarehouseUnavailableError(AccessoryInventoryError):
    code = "ACCESSORY_WAREHOUSE_UNAVAILABLE"
    public_message = "accessory warehouse is unavailable"


class AccessoryReservationConflictError(AccessoryInventoryError):
    code = "ACCESSORY_RESERVATION_CONFLICT"
    public_message = "accessory reservation already has different facts"


class AccessoryReservationNotFoundError(AccessoryInventoryError):
    code = "ACCESSORY_RESERVATION_NOT_FOUND"
    public_message = "accessory reservation was not found"


class AccessoryUnitUnavailableError(AccessoryInventoryError):
    code = "ACCESSORY_UNIT_UNAVAILABLE"
    public_message = "accessory unit is unavailable"


class AccessoryRelayHandoffConflictError(AccessoryInventoryError):
    code = "ACCESSORY_RELAY_HANDOFF_CONFLICT"
    public_message = "accessory relay handoff facts do not agree"


class AccessoryInspectionConflictError(AccessoryInventoryError):
    code = "ACCESSORY_INSPECTION_CONFLICT"
    public_message = "accessory inspection facts do not agree"


class AccessoryInspectionChainRecalculationRequiredError(AccessoryInventoryError):
    code = "ACCESSORY_INSPECTION_CHAIN_RECALCULATION_REQUIRED"
    public_message = "accessory links require atomic recalculation"


class AccessoryCapacityReductionUnavailableError(AccessoryInventoryError):
    code = "ACCESSORY_CAPACITY_REDUCTION_UNAVAILABLE"
    public_message = "accessory capacity cannot be reduced"


class AccessoryIdempotencyConflictError(AccessoryInventoryError):
    code = "ACCESSORY_IDEMPOTENCY_CONFLICT"
    public_message = "accessory operation idempotency key conflicts"


class AccessoryFulfillmentFrozenError(AccessoryInventoryError):
    code = "ACCESSORY_FULFILLMENT_FROZEN"
    public_message = "accessory fulfillment can no longer be changed"


class AccessoryPersistenceError(AccessoryInventoryError):
    code = "ACCESSORY_PERSISTENCE_FAILED"
    public_message = "accessory inventory transaction could not be persisted"


def _hide_persistence_details(method):
    """Keep SQL text/parameters, including internal UUIDs, out of errors."""

    @wraps(method)
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except AccessoryInventoryError:
            raise
        except SQLAlchemyError:
            raise AccessoryPersistenceError() from None

    return wrapped


@dataclass(frozen=True, slots=True)
class AccessoryTypeCounts:
    """Public projection without logical unit/link identifiers.

    ``total`` counts active capacity in the warehouse. ``available`` counts
    active units with no current holder and no overlap in the requested
    window; ``reserved`` is the remainder of active capacity.
    """

    type_code: str
    display_name: str
    total: int
    reserved: int
    available: int


class AccessoryInventoryRepository:
    """SQLAlchemy persistence boundary for one already-routed tenant DB.

    ``lock_reservation_units`` is the concurrency seam.  Its deterministic
    ordering plus ``FOR UPDATE`` serializes contenders before overlap rows are
    reread using a locking/current read.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_accessory_type(self, accessory_type_id: int) -> Optional[AccessoryType]:
        return self.session.get(AccessoryType, accessory_type_id)

    def lock_accessory_type(self, accessory_type_id: int) -> Optional[AccessoryType]:
        return self.session.execute(
            select(AccessoryType)
            .where(AccessoryType.id == accessory_type_id)
            .with_for_update()
        ).scalar_one_or_none()

    def get_warehouse(self, warehouse_id: int) -> Optional[Warehouse]:
        return self.session.get(Warehouse, warehouse_id)

    def lock_warehouse(self, warehouse_id: int) -> Optional[Warehouse]:
        return self.session.execute(
            select(Warehouse).where(Warehouse.id == warehouse_id).with_for_update()
        ).scalar_one_or_none()

    def get_rental(self, rental_id: int) -> Optional[Rental]:
        return self.session.get(Rental, rental_id)

    def lock_rental(self, rental_id: int) -> Optional[Rental]:
        return self.session.execute(
            select(Rental).where(Rental.id == rental_id).with_for_update()
        ).scalar_one_or_none()

    def lock_rentals(self, rental_ids: Sequence[int]) -> Sequence[Rental]:
        if not rental_ids:
            return ()
        return tuple(
            self.session.execute(
                select(Rental)
                .where(Rental.id.in_(tuple(sorted(set(rental_ids)))))
                .order_by(Rental.id.asc())
                .with_for_update()
            )
            .scalars()
            .all()
        )

    def get_relay_case(self, relay_case_id: int) -> Optional[RentalRelayCase]:
        return self.session.get(RentalRelayCase, relay_case_id)

    def lock_relay_case(
        self,
        relay_case_id: int,
    ) -> Optional[RentalRelayCase]:
        return self.session.execute(
            select(RentalRelayCase)
            .where(RentalRelayCase.id == relay_case_id)
            .with_for_update()
        ).scalar_one_or_none()

    def lock_device(self, device_id: int) -> Optional[Device]:
        return self.session.execute(
            select(Device).where(Device.id == device_id).with_for_update()
        ).scalar_one_or_none()

    def fulfillment_execution_is_frozen(
        self,
        rental_ids: Sequence[int],
        *,
        allow_stable_submitted_shipment: bool = False,
    ) -> bool:
        """Current-read execution ledgers after device -> rental locks.

        Shipping crosses its external-effect boundary while holding the same
        device and rental rows.  ``NOWAIT`` is deliberate here: shipping
        locks its execution row before that shared context, so waiting for an
        execution row after taking the context would introduce a reverse-lock
        deadlock.  A collision instead fails closed through the service's
        persistence-error boundary and the caller rolls back its transaction.

        Relay handoff is the one mutation authorized by a stable submitted
        shipment.  Its caller may opt into that narrow exception, while any
        in-flight or uncertain provider/print fact remains frozen.
        """

        rental_ids = tuple(sorted(set(rental_ids)))
        if not rental_ids:
            return False

        shipment_statement = (
            select(OutboundShipment)
            .where(OutboundShipment.rental_id.in_(rental_ids))
            .order_by(OutboundShipment.rental_id.asc(), OutboundShipment.id.asc())
            .with_for_update(nowait=True)
        )
        shipments = tuple(self.session.execute(shipment_statement).scalars().all())
        if not shipments:
            return False

        shipment_ids = tuple(shipment.id for shipment in shipments)
        attempts = tuple(
            self.session.execute(
                select(ProviderOperationAttempt)
                .where(ProviderOperationAttempt.shipment_id.in_(shipment_ids))
                .order_by(
                    ProviderOperationAttempt.shipment_id.asc(),
                    ProviderOperationAttempt.id.asc(),
                )
                .with_for_update(nowait=True)
            )
            .scalars()
            .all()
        )
        print_jobs = tuple(
            self.session.execute(
                select(WaybillPrintJob)
                .where(WaybillPrintJob.shipment_id.in_(shipment_ids))
                .order_by(WaybillPrintJob.shipment_id.asc(), WaybillPrintJob.id.asc())
                .with_for_update(nowait=True)
            )
            .scalars()
            .all()
        )
        attempts_by_shipment: dict[str, list[ProviderOperationAttempt]] = {
            shipment_id: [] for shipment_id in shipment_ids
        }
        for attempt in attempts:
            attempts_by_shipment[attempt.shipment_id].append(attempt)
        jobs_by_shipment: dict[str, list[WaybillPrintJob]] = {
            shipment_id: [] for shipment_id in shipment_ids
        }
        for job in print_jobs:
            jobs_by_shipment[job.shipment_id].append(job)

        for shipment in shipments:
            shipment_attempts = attempts_by_shipment[shipment.id]
            shipment_jobs = jobs_by_shipment[shipment.id]
            if any(
                attempt.status in _UNSETTLED_PROVIDER_ATTEMPT_STATUSES
                for attempt in shipment_attempts
            ) or any(
                job.status in _UNSETTLED_PRINT_JOB_STATUSES for job in shipment_jobs
            ):
                return True
            if shipment.status in _FROZEN_SHIPMENT_STATUSES:
                if allow_stable_submitted_shipment and shipment.status == "submitted":
                    continue
                return True
            if shipment.status == "cancelled":
                cancellation_proven = any(
                    attempt.operation == "cancel_waybill"
                    and attempt.status == "succeeded"
                    for attempt in shipment_attempts
                )
                if not cancellation_proven:
                    return True
                continue
            if shipment.status in {"prepared", "failed"}:
                if any(
                    attempt.status in _FROZEN_PROVIDER_ATTEMPT_STATUSES
                    for attempt in shipment_attempts
                ) or any(
                    job.status in _FROZEN_PRINT_JOB_STATUSES for job in shipment_jobs
                ):
                    return True
                if shipment.status == "failed" and not any(
                    attempt.operation == "create_waybill"
                    and attempt.status == "definitive_failure"
                    for attempt in shipment_attempts
                ):
                    return True
                continue

            # Unknown persisted status or a future state not classified here
            # cannot prove that fulfillment facts are safe to mutate.
            return True
        return False

    def lock_device_accessory_config(
        self,
        *,
        device_id: int,
        accessory_type_id: int,
    ) -> Optional[DeviceAccessoryConfig]:
        return self.session.execute(
            select(DeviceAccessoryConfig)
            .where(
                DeviceAccessoryConfig.device_id == device_id,
                DeviceAccessoryConfig.accessory_type_id == accessory_type_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

    def lock_reservation_units(
        self,
        *,
        accessory_type_id: int,
        warehouse_id: int,
    ) -> Sequence[AccessoryUnit]:
        return tuple(
            self.session.execute(
                select(AccessoryUnit)
                .where(
                    AccessoryUnit.accessory_type_id == accessory_type_id,
                    AccessoryUnit.warehouse_id == warehouse_id,
                    AccessoryUnit.condition_status == "active",
                    AccessoryUnit.current_holder_rental_id.is_(None),
                )
                .order_by(
                    AccessoryUnit.accessory_type_id.asc(),
                    AccessoryUnit.id.asc(),
                )
                .with_for_update()
            )
            .scalars()
            .all()
        )

    def lock_overlapping_links(
        self,
        *,
        unit_ids: Sequence[str],
        reservation_start_at: datetime,
        reservation_end_at: datetime,
    ) -> Sequence[RentalAccessoryUnitLink]:
        if not unit_ids:
            return ()
        return tuple(
            self.session.execute(
                select(RentalAccessoryUnitLink)
                .where(
                    RentalAccessoryUnitLink.accessory_unit_id.in_(unit_ids),
                    RentalAccessoryUnitLink.reservation_start_at < reservation_end_at,
                    RentalAccessoryUnitLink.reservation_end_at > reservation_start_at,
                )
                .order_by(
                    RentalAccessoryUnitLink.accessory_type_id.asc(),
                    RentalAccessoryUnitLink.accessory_unit_id.asc(),
                    RentalAccessoryUnitLink.id.asc(),
                )
                .with_for_update()
            )
            .scalars()
            .all()
        )

    def lock_request(
        self,
        *,
        rental_id: int,
        accessory_type_id: int,
    ) -> Optional[RentalAccessoryRequest]:
        return self.session.execute(
            select(RentalAccessoryRequest)
            .where(
                RentalAccessoryRequest.rental_id == rental_id,
                RentalAccessoryRequest.accessory_type_id == accessory_type_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

    def lock_link(
        self,
        *,
        rental_id: int,
        accessory_type_id: int,
    ) -> Optional[RentalAccessoryUnitLink]:
        return self.session.execute(
            select(RentalAccessoryUnitLink)
            .where(
                RentalAccessoryUnitLink.rental_id == rental_id,
                RentalAccessoryUnitLink.accessory_type_id == accessory_type_id,
            )
            .with_for_update()
        ).scalar_one_or_none()

    def lock_links(
        self,
        *,
        rental_ids: Sequence[int],
        accessory_type_id: int,
    ) -> Sequence[RentalAccessoryUnitLink]:
        if not rental_ids:
            return ()
        return tuple(
            self.session.execute(
                select(RentalAccessoryUnitLink)
                .where(
                    RentalAccessoryUnitLink.rental_id.in_(
                        tuple(sorted(set(rental_ids)))
                    ),
                    RentalAccessoryUnitLink.accessory_type_id == accessory_type_id,
                )
                .order_by(
                    RentalAccessoryUnitLink.rental_id.asc(),
                    RentalAccessoryUnitLink.accessory_unit_id.asc(),
                )
                .with_for_update()
            )
            .scalars()
            .all()
        )

    def peek_link(
        self,
        *,
        rental_id: int,
        accessory_type_id: int,
    ) -> Optional[RentalAccessoryUnitLink]:
        return self.session.execute(
            select(RentalAccessoryUnitLink).where(
                RentalAccessoryUnitLink.rental_id == rental_id,
                RentalAccessoryUnitLink.accessory_type_id == accessory_type_id,
            )
        ).scalar_one_or_none()

    def lock_unit(
        self,
        *,
        accessory_type_id: int,
        unit_id: str,
    ) -> Optional[AccessoryUnit]:
        return self.session.execute(
            select(AccessoryUnit)
            .where(
                AccessoryUnit.accessory_type_id == accessory_type_id,
                AccessoryUnit.id == unit_id,
            )
            .order_by(
                AccessoryUnit.accessory_type_id.asc(),
                AccessoryUnit.id.asc(),
            )
            .with_for_update()
        ).scalar_one_or_none()

    def lock_units_for_capacity_reduction(
        self,
        *,
        accessory_type_id: int,
        warehouse_id: int,
    ) -> Sequence[AccessoryUnit]:
        return self.lock_reservation_units(
            accessory_type_id=accessory_type_id,
            warehouse_id=warehouse_id,
        )

    def lock_future_links(
        self,
        *,
        unit_ids: Sequence[str],
        effective_at: datetime,
    ) -> Sequence[RentalAccessoryUnitLink]:
        if not unit_ids:
            return ()
        return tuple(
            self.session.execute(
                select(RentalAccessoryUnitLink)
                .where(
                    RentalAccessoryUnitLink.accessory_unit_id.in_(unit_ids),
                    RentalAccessoryUnitLink.reservation_end_at > effective_at,
                )
                .order_by(
                    RentalAccessoryUnitLink.accessory_type_id.asc(),
                    RentalAccessoryUnitLink.accessory_unit_id.asc(),
                    RentalAccessoryUnitLink.id.asc(),
                )
                .with_for_update()
            )
            .scalars()
            .all()
        )

    def lock_event(self, idempotency_key: str) -> Optional[AccessoryUnitEvent]:
        return self.session.execute(
            select(AccessoryUnitEvent)
            .where(AccessoryUnitEvent.idempotency_key == idempotency_key)
            .with_for_update()
        ).scalar_one_or_none()

    def lock_events(
        self,
        idempotency_keys: Sequence[str],
    ) -> Sequence[AccessoryUnitEvent]:
        if not idempotency_keys:
            return ()
        return tuple(
            self.session.execute(
                select(AccessoryUnitEvent)
                .where(AccessoryUnitEvent.idempotency_key.in_(idempotency_keys))
                .order_by(AccessoryUnitEvent.idempotency_key.asc())
                .with_for_update()
            )
            .scalars()
            .all()
        )

    def availability_counts(
        self,
        *,
        accessory_type_id: int,
        warehouse_id: int,
        reservation_start_at: datetime,
        reservation_end_at: datetime,
    ) -> tuple[int, int, int]:
        overlapping_link = (
            exists()
            .where(
                RentalAccessoryUnitLink.accessory_unit_id == AccessoryUnit.id,
                RentalAccessoryUnitLink.reservation_start_at < reservation_end_at,
                RentalAccessoryUnitLink.reservation_end_at > reservation_start_at,
            )
            .correlate(AccessoryUnit)
        )
        available_unit = and_(
            AccessoryUnit.current_holder_rental_id.is_(None),
            ~overlapping_link,
        )
        total, available = self.session.execute(
            select(
                func.count(AccessoryUnit.id),
                func.coalesce(
                    func.sum(case((available_unit, 1), else_=0)),
                    0,
                ),
            ).where(
                AccessoryUnit.accessory_type_id == accessory_type_id,
                AccessoryUnit.warehouse_id == warehouse_id,
                AccessoryUnit.condition_status == "active",
            )
        ).one()
        total_count = int(total or 0)
        available_count = int(available or 0)
        return total_count, total_count - available_count, available_count

    def add(self, value: object) -> None:
        self.session.add(value)

    def add_all(self, values: Iterable[object]) -> None:
        self.session.add_all(tuple(values))

    def delete(self, value: object) -> None:
        self.session.delete(value)

    def flush(self) -> None:
        self.session.flush()


class AccessoryInventoryService:
    """Logical inventory mutations for one already-routed tenant database."""

    def __init__(
        self,
        session: Session,
        *,
        repository: Optional[AccessoryInventoryRepository] = None,
    ) -> None:
        self._session = session
        self._repository = repository or AccessoryInventoryRepository(session)

    @_hide_persistence_details
    def availability(
        self,
        *,
        accessory_type_id: int,
        warehouse_id: int,
        reservation_start_at: datetime,
        reservation_end_at: datetime,
    ) -> AccessoryTypeCounts:
        self._validate_window(reservation_start_at, reservation_end_at)
        accessory_type = self._repository.get_accessory_type(accessory_type_id)
        self._require_logical_type(accessory_type, require_active=True)
        warehouse = self._repository.get_warehouse(warehouse_id)
        self._require_warehouse(warehouse, require_ready=False)
        return self._counts(
            accessory_type=accessory_type,
            warehouse_id=warehouse_id,
            reservation_start_at=reservation_start_at,
            reservation_end_at=reservation_end_at,
        )

    @_hide_persistence_details
    def reserve_for_rental(
        self,
        *,
        rental_id: int,
        accessory_type_id: int,
        reservation_start_at: datetime,
        reservation_end_at: datetime,
        actor_type: str,
        actor_id: Optional[str],
        operation_key: str,
    ) -> AccessoryTypeCounts:
        """Create the request/link/event atomically inside the caller's tx."""

        self._require_explicit_transaction()
        self._validate_window(reservation_start_at, reservation_end_at)
        self._validate_actor(actor_type, actor_id)
        event_key = self._event_key(
            "reserve",
            operation_key,
            f"r{rental_id}:t{accessory_type_id}:linked",
        )

        peeked_rental = self._repository.get_rental(rental_id)
        if peeked_rental is None or peeked_rental.parent_rental_id is not None:
            raise AccessoryInputError()
        device = self._repository.lock_device(peeked_rental.device_id)
        rental = self._repository.lock_rental(rental_id)
        if (
            rental is None
            or rental.parent_rental_id is not None
            or rental.device_id != peeked_rental.device_id
        ):
            raise AccessoryInputError()
        if device is None or device.warehouse_id is None:
            raise AccessoryWarehouseUnavailableError()
        accessory_type = self._repository.lock_accessory_type(accessory_type_id)
        self._require_logical_type(accessory_type, require_active=True)
        warehouse = self._repository.lock_warehouse(device.warehouse_id)
        self._require_warehouse(warehouse, require_ready=True)
        config = self._repository.lock_device_accessory_config(
            device_id=device.id,
            accessory_type_id=accessory_type_id,
        )
        if config is None or config.enabled is not True:
            raise AccessoryTypeUnavailableError()

        prior_event = self._repository.lock_event(event_key)
        if prior_event is not None:
            try:
                return self._reservation_retry_counts(
                    event=prior_event,
                    rental_id=rental_id,
                    accessory_type=accessory_type,
                    warehouse_id=warehouse.id,
                    reservation_start_at=reservation_start_at,
                    reservation_end_at=reservation_end_at,
                )
            except AccessoryIdempotencyConflictError:
                self._require_fulfillment_mutable((rental.id,))
                raise
        self._require_fulfillment_mutable((rental.id,))

        units = self._repository.lock_reservation_units(
            accessory_type_id=accessory_type_id,
            warehouse_id=warehouse.id,
        )
        overlapping_links = self._repository.lock_overlapping_links(
            unit_ids=tuple(unit.id for unit in units),
            reservation_start_at=reservation_start_at,
            reservation_end_at=reservation_end_at,
        )

        # Re-read request/link after the unit lock wait.  MySQL locking reads
        # now observe a contender that committed while this transaction waited.
        existing_request = self._repository.lock_request(
            rental_id=rental_id,
            accessory_type_id=accessory_type_id,
        )
        existing_link = self._repository.lock_link(
            rental_id=rental_id,
            accessory_type_id=accessory_type_id,
        )
        if existing_request is not None or existing_link is not None:
            raise AccessoryReservationConflictError()

        unavailable_ids = {link.accessory_unit_id for link in overlapping_links}
        unit = next(
            (candidate for candidate in units if candidate.id not in unavailable_ids),
            None,
        )
        if unit is None:
            # Deliberately reject before adding a request or any conflict row.
            raise AccessoryUnitUnavailableError()

        request = RentalAccessoryRequest(
            rental_id=rental_id,
            accessory_type_id=accessory_type_id,
            name_snapshot=accessory_type.display_name,
        )
        link = RentalAccessoryUnitLink(
            rental_id=rental_id,
            accessory_type_id=accessory_type_id,
            accessory_unit_id=unit.id,
            reservation_start_at=reservation_start_at,
            reservation_end_at=reservation_end_at,
        )
        event = AccessoryUnitEvent(
            unit_id=unit.id,
            event_type="linked",
            main_device_id=device.id,
            rental_id=rental_id,
            actor_type=actor_type,
            actor_id=self._clean_actor_id(actor_id),
            reason="ordinary_reservation",
            idempotency_key=event_key,
        )
        self._repository.add_all((request, link, event))
        try:
            self._repository.flush()
        except IntegrityError:
            raise AccessoryUnitUnavailableError() from None
        return self._counts(
            accessory_type=accessory_type,
            warehouse_id=warehouse.id,
            reservation_start_at=reservation_start_at,
            reservation_end_at=reservation_end_at,
        )

    @_hide_persistence_details
    def dispatch_for_rental(
        self,
        *,
        rental_id: int,
        accessory_type_id: int,
        actor_type: str,
        actor_id: Optional[str],
        operation_key: str,
    ) -> AccessoryTypeCounts:
        """Transfer an ordinary linked unit from warehouse to its rental."""

        self._require_explicit_transaction()
        self._validate_actor(actor_type, actor_id)
        event_key = self._event_key(
            "dispatch",
            operation_key,
            f"r{rental_id}:t{accessory_type_id}:dispatched",
        )
        peeked_rental = self._repository.get_rental(rental_id)
        if peeked_rental is None or peeked_rental.parent_rental_id is not None:
            raise AccessoryInputError()
        device = self._repository.lock_device(peeked_rental.device_id)
        rental = self._repository.lock_rental(rental_id)
        if (
            rental is None
            or rental.parent_rental_id is not None
            or rental.device_id != peeked_rental.device_id
        ):
            raise AccessoryInputError()
        accessory_type = self._repository.lock_accessory_type(accessory_type_id)
        self._require_logical_type(accessory_type, require_active=False)

        prior_event = self._repository.lock_event(event_key)
        if prior_event is not None:
            prior_unit = self._repository.lock_unit(
                accessory_type_id=accessory_type_id,
                unit_id=prior_event.unit_id,
            )
            link = self._repository.lock_link(
                rental_id=rental_id,
                accessory_type_id=accessory_type_id,
            )
            if (
                prior_event.event_type != "dispatched"
                or prior_event.rental_id != rental_id
                or prior_unit is None
                or prior_unit.current_holder_rental_id != rental_id
                or link is None
                or link.accessory_unit_id != prior_unit.id
            ):
                self._require_fulfillment_mutable((rental.id,))
                raise AccessoryIdempotencyConflictError()
            return self._counts(
                accessory_type=accessory_type,
                warehouse_id=prior_unit.warehouse_id,
                reservation_start_at=link.reservation_start_at,
                reservation_end_at=link.reservation_end_at,
            )
        self._require_fulfillment_mutable((rental.id,))

        peeked_link = self._repository.peek_link(
            rental_id=rental_id,
            accessory_type_id=accessory_type_id,
        )
        if peeked_link is None:
            raise AccessoryReservationNotFoundError()
        unit = self._repository.lock_unit(
            accessory_type_id=accessory_type_id,
            unit_id=peeked_link.accessory_unit_id,
        )
        link = self._repository.lock_link(
            rental_id=rental_id,
            accessory_type_id=accessory_type_id,
        )
        if unit is None or link is None or link.accessory_unit_id != unit.id:
            raise AccessoryReservationNotFoundError()
        if (
            device is None
            or device.warehouse_id is None
            or unit.warehouse_id != device.warehouse_id
            or unit.condition_status != "active"
            or unit.current_holder_rental_id is not None
        ):
            raise AccessoryUnitUnavailableError()

        unit.current_holder_rental_id = rental_id
        unit.row_version += 1
        self._repository.add(
            AccessoryUnitEvent(
                unit_id=unit.id,
                event_type="dispatched",
                main_device_id=device.id,
                rental_id=rental_id,
                from_warehouse_id=unit.warehouse_id,
                to_holder_rental_id=rental_id,
                actor_type=actor_type,
                actor_id=self._clean_actor_id(actor_id),
                reason="ordinary_dispatch",
                idempotency_key=event_key,
            )
        )
        try:
            self._repository.flush()
        except IntegrityError:
            raise AccessoryPersistenceError() from None
        return self._counts(
            accessory_type=accessory_type,
            warehouse_id=unit.warehouse_id,
            reservation_start_at=link.reservation_start_at,
            reservation_end_at=link.reservation_end_at,
        )

    @_hide_persistence_details
    def handoff_for_relay(
        self,
        *,
        relay_case_id: int,
        accessory_type_id: int,
        actor_type: str,
        actor_id: Optional[str],
        operation_key: str,
    ) -> AccessoryTypeCounts:
        """Move custody from an agreed relay predecessor to its successor.

        The agreed-chain planner must already have linked the same logical
        unit to both rentals.  This operation never chooses a unit and never
        creates demand; it only verifies the neutral links and current holder
        under locks, advances the holder, and appends one immutable event.
        The relay status transition remains caller-owned so both changes can
        be committed by the same tenant-database transaction.
        """

        self._require_explicit_transaction()
        self._validate_actor(actor_type, actor_id)
        if (
            isinstance(relay_case_id, bool)
            or not isinstance(relay_case_id, int)
            or relay_case_id <= 0
        ):
            raise AccessoryInputError()
        event_key = self._event_key(
            "relay-handoff",
            operation_key,
            f"c{relay_case_id}:t{accessory_type_id}:handoff",
        )

        peeked_case = self._repository.get_relay_case(relay_case_id)
        if peeked_case is None:
            raise AccessoryRelayHandoffConflictError()
        peeked_predecessor = self._repository.get_rental(
            peeked_case.predecessor_rental_id
        )
        if (
            peeked_predecessor is None
            or peeked_predecessor.parent_rental_id is not None
        ):
            raise AccessoryRelayHandoffConflictError()

        device = self._repository.lock_device(peeked_predecessor.device_id)
        rentals = self._repository.lock_rentals(
            (
                peeked_case.predecessor_rental_id,
                peeked_case.successor_rental_id,
            )
        )
        rental_by_id = {rental.id: rental for rental in rentals}
        relay_case = self._repository.lock_relay_case(relay_case_id)
        if relay_case is None:
            raise AccessoryRelayHandoffConflictError()
        predecessor = rental_by_id.get(relay_case.predecessor_rental_id)
        successor = rental_by_id.get(relay_case.successor_rental_id)
        if (
            device is None
            or predecessor is None
            or successor is None
            or predecessor.parent_rental_id is not None
            or successor.parent_rental_id is not None
            or predecessor.id == successor.id
            or predecessor.device_id != device.id
            or successor.device_id != device.id
            or (relay_case.predecessor_rental_id != peeked_case.predecessor_rental_id)
            or relay_case.successor_rental_id != peeked_case.successor_rental_id
        ):
            raise AccessoryRelayHandoffConflictError()

        accessory_type = self._repository.lock_accessory_type(accessory_type_id)
        self._require_logical_type(accessory_type, require_active=False)
        peeked_predecessor_link = self._repository.peek_link(
            rental_id=predecessor.id,
            accessory_type_id=accessory_type_id,
        )
        peeked_successor_link = self._repository.peek_link(
            rental_id=successor.id,
            accessory_type_id=accessory_type_id,
        )
        if (
            peeked_predecessor_link is None
            or peeked_successor_link is None
            or peeked_predecessor_link.accessory_unit_id
            != peeked_successor_link.accessory_unit_id
            or peeked_successor_link.source_relay_case_id != relay_case.id
        ):
            raise AccessoryRelayHandoffConflictError()

        unit = self._repository.lock_unit(
            accessory_type_id=accessory_type_id,
            unit_id=peeked_predecessor_link.accessory_unit_id,
        )
        if unit is None or unit.condition_status != "active":
            raise AccessoryRelayHandoffConflictError()

        links = self._repository.lock_links(
            rental_ids=(predecessor.id, successor.id),
            accessory_type_id=accessory_type_id,
        )
        link_by_rental = {link.rental_id: link for link in links}
        predecessor_link = link_by_rental.get(predecessor.id)
        successor_link = link_by_rental.get(successor.id)
        if (
            predecessor_link is None
            or successor_link is None
            or predecessor_link.accessory_unit_id != unit.id
            or successor_link.accessory_unit_id != unit.id
            or successor_link.source_relay_case_id != relay_case.id
        ):
            raise AccessoryRelayHandoffConflictError()

        prior_event = self._repository.lock_event(event_key)
        if prior_event is not None:
            if (
                prior_event.event_type != "relay_handoff"
                or prior_event.unit_id != unit.id
                or prior_event.main_device_id != device.id
                or prior_event.rental_id != successor.id
                or prior_event.relay_case_id != relay_case.id
                or prior_event.from_holder_rental_id != predecessor.id
                or prior_event.to_holder_rental_id != successor.id
            ):
                raise AccessoryIdempotencyConflictError()
            # The immutable event is the result of this idempotent action.
            # Current custody may already have advanced through a later relay
            # edge (or a later receipt) and must not make replay of this
            # earlier, successfully committed handoff fail or move it back.
            return self._counts(
                accessory_type=accessory_type,
                warehouse_id=unit.warehouse_id,
                reservation_start_at=successor_link.reservation_start_at,
                reservation_end_at=successor_link.reservation_end_at,
            )
        if (
            relay_case.status != "agreed"
            or unit.current_holder_rental_id != predecessor.id
        ):
            raise AccessoryRelayHandoffConflictError()

        # A successfully submitted successor shipment is the authority that
        # normally causes this custody transition, so that one stable state is
        # allowed through the otherwise shared fulfillment freeze.  Any
        # in-flight or uncertain provider/print fact on either relay rental
        # still blocks the handoff.
        # This method does not rewrite requests, links, units, shipments, or
        # print facts: the exact agreed edge, same-unit neutral links and current
        # predecessor holder were all locked and verified above.  Every other
        # fulfillment mutation continues to use the ordinary freeze check.
        if self._repository.fulfillment_execution_is_frozen(
            (predecessor.id, successor.id),
            allow_stable_submitted_shipment=True,
        ):
            raise AccessoryFulfillmentFrozenError()

        unit.current_holder_rental_id = successor.id
        unit.row_version += 1
        self._repository.add(
            AccessoryUnitEvent(
                unit_id=unit.id,
                event_type="relay_handoff",
                main_device_id=device.id,
                rental_id=successor.id,
                relay_case_id=relay_case.id,
                from_holder_rental_id=predecessor.id,
                to_holder_rental_id=successor.id,
                actor_type=actor_type,
                actor_id=self._clean_actor_id(actor_id),
                reason="agreed_relay_handoff",
                idempotency_key=event_key,
            )
        )
        try:
            self._repository.flush()
        except IntegrityError:
            raise AccessoryPersistenceError() from None
        return self._counts(
            accessory_type=accessory_type,
            warehouse_id=unit.warehouse_id,
            reservation_start_at=successor_link.reservation_start_at,
            reservation_end_at=successor_link.reservation_end_at,
        )

    @_hide_persistence_details
    def release_reservation(
        self,
        *,
        rental_id: int,
        accessory_type_id: int,
        reservation_start_at: datetime,
        reservation_end_at: datetime,
        actor_type: str,
        actor_id: Optional[str],
        operation_key: str,
    ) -> AccessoryTypeCounts:
        """Delete a neutral link and append an immutable unlinked event.

        The request deliberately remains: callers may separately cancel the
        demand or let fulfillment gates derive a shortage from request-without-
        link.  Custody is not changed by releasing a planned link.
        """

        self._require_explicit_transaction()
        self._validate_window(reservation_start_at, reservation_end_at)
        self._validate_actor(actor_type, actor_id)
        release_fact_token = self._release_fact_token(
            rental_id,
            accessory_type_id,
            reservation_start_at,
            reservation_end_at,
        )
        event_key = self._event_key(
            "release",
            operation_key,
            f"f{release_fact_token}:unlinked",
        )
        peeked_rental = self._repository.get_rental(rental_id)
        if peeked_rental is None or peeked_rental.parent_rental_id is not None:
            raise AccessoryInputError()
        device = self._repository.lock_device(peeked_rental.device_id)
        rental = self._repository.lock_rental(rental_id)
        if (
            device is None
            or rental is None
            or rental.parent_rental_id is not None
            or rental.device_id != peeked_rental.device_id
        ):
            raise AccessoryInputError()
        accessory_type = self._repository.lock_accessory_type(accessory_type_id)
        self._require_logical_type(accessory_type, require_active=False)

        prior_event = self._repository.lock_event(event_key)
        if prior_event is not None:
            prior_unit = self._repository.lock_unit(
                accessory_type_id=accessory_type_id,
                unit_id=prior_event.unit_id,
            )
            link = self._repository.lock_link(
                rental_id=rental_id,
                accessory_type_id=accessory_type_id,
            )
            request = self._repository.lock_request(
                rental_id=rental_id,
                accessory_type_id=accessory_type_id,
            )
            if (
                prior_event.event_type != "unlinked"
                or prior_event.rental_id != rental_id
                or prior_unit is None
                or request is None
                or link is not None
            ):
                self._require_fulfillment_mutable((rental.id,))
                raise AccessoryIdempotencyConflictError()
            return self._counts(
                accessory_type=accessory_type,
                warehouse_id=prior_unit.warehouse_id,
                reservation_start_at=reservation_start_at,
                reservation_end_at=reservation_end_at,
            )
        self._require_fulfillment_mutable((rental.id,))

        peeked_link = self._repository.peek_link(
            rental_id=rental_id,
            accessory_type_id=accessory_type_id,
        )
        if peeked_link is None:
            raise AccessoryReservationNotFoundError()
        unit = self._repository.lock_unit(
            accessory_type_id=accessory_type_id,
            unit_id=peeked_link.accessory_unit_id,
        )
        link = self._repository.lock_link(
            rental_id=rental_id,
            accessory_type_id=accessory_type_id,
        )
        if unit is None or link is None or link.accessory_unit_id != unit.id:
            raise AccessoryReservationNotFoundError()
        if (
            link.reservation_start_at != reservation_start_at
            or link.reservation_end_at != reservation_end_at
        ):
            raise AccessoryReservationConflictError()

        self._repository.add(
            AccessoryUnitEvent(
                unit_id=unit.id,
                event_type="unlinked",
                rental_id=rental_id,
                actor_type=actor_type,
                actor_id=self._clean_actor_id(actor_id),
                reason="ordinary_reservation_release",
                idempotency_key=event_key,
            )
        )
        self._repository.delete(link)
        try:
            self._repository.flush()
        except IntegrityError:
            raise AccessoryPersistenceError() from None
        return self._counts(
            accessory_type=accessory_type,
            warehouse_id=unit.warehouse_id,
            reservation_start_at=reservation_start_at,
            reservation_end_at=reservation_end_at,
        )

    @_hide_persistence_details
    def inspect_return_for_rental(
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
    ) -> AccessoryTypeCounts:
        """Record one returned logical accessory without exposing its unit.

        ``received_normal`` and ``received_damaged`` both prove physical
        receipt and therefore clear custody.  A missing item remains held by
        the rental and becomes ``lost`` so it cannot be allocated.  Future
        links that would need a chain or warehouse recomputation are rejected
        until the complete D41 solver can update every affected rental in the
        same transaction.
        """

        self._require_explicit_transaction()
        self._validate_actor(actor_type, actor_id)
        if outcome not in {
            "received_normal",
            "received_damaged",
            "missing",
        }:
            raise AccessoryInputError()
        if not isinstance(occurred_at, datetime):
            raise AccessoryInputError()

        peeked_rental = self._repository.get_rental(rental_id)
        if peeked_rental is None or peeked_rental.parent_rental_id is not None:
            raise AccessoryInputError()
        device = self._repository.lock_device(peeked_rental.device_id)
        rental = self._repository.lock_rental(rental_id)
        warehouse = self._repository.lock_warehouse(warehouse_id)
        if (
            device is None
            or rental is None
            or rental.parent_rental_id is not None
            or rental.device_id != device.id
            or warehouse is None
            or warehouse.status != "active"
            or warehouse.setup_state != "ready"
        ):
            raise AccessoryInspectionConflictError()

        accessory_type = self._repository.lock_accessory_type(accessory_type_id)
        self._require_logical_type(accessory_type, require_active=False)
        peeked_link = self._repository.peek_link(
            rental_id=rental_id,
            accessory_type_id=accessory_type_id,
        )
        if peeked_link is None:
            raise AccessoryReservationNotFoundError()
        unit = self._repository.lock_unit(
            accessory_type_id=accessory_type_id,
            unit_id=peeked_link.accessory_unit_id,
        )
        link = self._repository.lock_link(
            rental_id=rental_id,
            accessory_type_id=accessory_type_id,
        )
        if unit is None or link is None or link.accessory_unit_id != unit.id:
            raise AccessoryInspectionConflictError()

        inspected_key = self._event_key(
            "inspection",
            operation_key,
            f"r{rental_id}:t{accessory_type_id}:inspected",
        )
        condition_key = self._event_key(
            "inspection-condition",
            operation_key,
            f"r{rental_id}:t{accessory_type_id}:{outcome}",
        )
        warehouse_key = self._event_key(
            "inspection-warehouse",
            operation_key,
            f"r{rental_id}:t{accessory_type_id}:moved",
        )
        expected_keys = [condition_key] if outcome == "missing" else [inspected_key]
        if outcome == "received_damaged":
            expected_keys.append(condition_key)
        prior_events = self._repository.lock_events(tuple(expected_keys))
        if prior_events:
            if len(prior_events) != len(expected_keys):
                raise AccessoryIdempotencyConflictError()
            events_by_key = {event.idempotency_key: event for event in prior_events}
            if outcome == "missing":
                prior = events_by_key.get(condition_key)
                if (
                    prior is None
                    or prior.event_type != "lost"
                    or prior.rental_id != rental_id
                    or prior.unit_id != unit.id
                    or unit.current_holder_rental_id != rental_id
                    or unit.condition_status != "lost"
                ):
                    raise AccessoryIdempotencyConflictError()
            else:
                inspected = events_by_key.get(inspected_key)
                if (
                    inspected is None
                    or inspected.event_type != "inspected"
                    or inspected.rental_id != rental_id
                    or inspected.unit_id != unit.id
                    or unit.current_holder_rental_id is not None
                    or unit.warehouse_id != warehouse_id
                ):
                    raise AccessoryIdempotencyConflictError()
                if outcome == "received_normal":
                    if unit.condition_status != "active":
                        raise AccessoryIdempotencyConflictError()
                else:
                    maintenance = events_by_key.get(condition_key)
                    if (
                        maintenance is None
                        or maintenance.event_type != "maintenance"
                        or maintenance.unit_id != unit.id
                        or unit.condition_status != "maintenance"
                    ):
                        raise AccessoryIdempotencyConflictError()
            return self._counts(
                accessory_type=accessory_type,
                warehouse_id=unit.warehouse_id,
                reservation_start_at=link.reservation_start_at,
                reservation_end_at=link.reservation_end_at,
            )

        if unit.current_holder_rental_id != rental_id:
            raise AccessoryInspectionConflictError()

        future_links = tuple(
            future_link
            for future_link in self._repository.lock_future_links(
                unit_ids=(unit.id,),
                effective_at=occurred_at,
            )
            if future_link.rental_id != rental_id
        )
        if future_links and (
            outcome != "received_normal" or unit.warehouse_id != warehouse_id
        ):
            raise AccessoryInspectionChainRecalculationRequiredError()

        from_warehouse_id = unit.warehouse_id
        if outcome == "missing":
            unit.condition_status = "lost"
            unit.row_version += 1
            self._repository.add(
                AccessoryUnitEvent(
                    unit_id=unit.id,
                    event_type="lost",
                    main_device_id=device.id,
                    rental_id=rental_id,
                    from_warehouse_id=from_warehouse_id,
                    from_holder_rental_id=rental_id,
                    to_holder_rental_id=rental_id,
                    actor_type=actor_type,
                    actor_id=self._clean_actor_id(actor_id),
                    reason="missing_on_inspection",
                    idempotency_key=condition_key,
                )
            )
        else:
            unit.current_holder_rental_id = None
            unit.warehouse_id = warehouse_id
            unit.condition_status = (
                "active" if outcome == "received_normal" else "maintenance"
            )
            unit.row_version += 1
            self._repository.add(
                AccessoryUnitEvent(
                    unit_id=unit.id,
                    event_type="inspected",
                    main_device_id=device.id,
                    rental_id=rental_id,
                    from_warehouse_id=from_warehouse_id,
                    to_warehouse_id=warehouse_id,
                    from_holder_rental_id=rental_id,
                    actor_type=actor_type,
                    actor_id=self._clean_actor_id(actor_id),
                    reason=(
                        "returned_normal"
                        if outcome == "received_normal"
                        else "returned_damaged"
                    ),
                    idempotency_key=inspected_key,
                )
            )
            if outcome == "received_damaged":
                self._repository.add(
                    AccessoryUnitEvent(
                        unit_id=unit.id,
                        event_type="maintenance",
                        main_device_id=device.id,
                        rental_id=rental_id,
                        to_warehouse_id=warehouse_id,
                        actor_type=actor_type,
                        actor_id=self._clean_actor_id(actor_id),
                        reason="damaged_on_inspection",
                        idempotency_key=condition_key,
                    )
                )
            if from_warehouse_id != warehouse_id:
                prior_move = self._repository.lock_event(warehouse_key)
                if prior_move is not None:
                    raise AccessoryIdempotencyConflictError()
                self._repository.add(
                    AccessoryUnitEvent(
                        unit_id=unit.id,
                        event_type="warehouse_moved",
                        main_device_id=device.id,
                        rental_id=rental_id,
                        from_warehouse_id=from_warehouse_id,
                        to_warehouse_id=warehouse_id,
                        actor_type=actor_type,
                        actor_id=self._clean_actor_id(actor_id),
                        reason="inspection_receipt",
                        idempotency_key=warehouse_key,
                    )
                )

        try:
            self._repository.flush()
        except IntegrityError:
            raise AccessoryPersistenceError() from None
        return self._counts(
            accessory_type=accessory_type,
            warehouse_id=unit.warehouse_id,
            reservation_start_at=link.reservation_start_at,
            reservation_end_at=link.reservation_end_at,
        )

    @_hide_persistence_details
    def add_capacity(
        self,
        *,
        accessory_type_id: int,
        warehouse_id: int,
        quantity: int,
        evaluation_start_at: datetime,
        evaluation_end_at: datetime,
        actor_type: str,
        actor_id: Optional[str],
        operation_key: str,
    ) -> AccessoryTypeCounts:
        """Create one internal unit and ``created`` event per capacity item."""

        self._require_explicit_transaction()
        self._validate_quantity(quantity)
        self._validate_window(evaluation_start_at, evaluation_end_at)
        self._validate_actor(actor_type, actor_id)
        accessory_type = self._repository.lock_accessory_type(accessory_type_id)
        self._require_logical_type(accessory_type, require_active=True)
        warehouse = self._repository.lock_warehouse(warehouse_id)
        self._require_warehouse(warehouse, require_ready=True)
        event_keys = tuple(
            self._event_key(
                "capacity-add",
                operation_key,
                f"t{accessory_type_id}:w{warehouse_id}:created-{index}",
            )
            for index in range(quantity)
        )
        prior_events = self._repository.lock_events(event_keys)
        if prior_events:
            self._validate_capacity_retry(
                events=prior_events,
                expected_keys=event_keys,
                event_type="created",
                accessory_type_id=accessory_type_id,
                warehouse_id=warehouse_id,
            )
            return self._counts(
                accessory_type=accessory_type,
                warehouse_id=warehouse_id,
                reservation_start_at=evaluation_start_at,
                reservation_end_at=evaluation_end_at,
            )

        units = tuple(
            AccessoryUnit(
                accessory_type_id=accessory_type_id,
                warehouse_id=warehouse_id,
                condition_status="active",
                row_version=1,
            )
            for _ in range(quantity)
        )
        self._repository.add_all(units)
        try:
            self._repository.flush()
            self._repository.add_all(
                AccessoryUnitEvent(
                    unit_id=unit.id,
                    event_type="created",
                    to_warehouse_id=warehouse_id,
                    actor_type=actor_type,
                    actor_id=self._clean_actor_id(actor_id),
                    reason="capacity_increase",
                    idempotency_key=event_key,
                )
                for unit, event_key in zip(units, event_keys)
            )
            self._repository.flush()
        except IntegrityError:
            raise AccessoryPersistenceError() from None
        return self._counts(
            accessory_type=accessory_type,
            warehouse_id=warehouse_id,
            reservation_start_at=evaluation_start_at,
            reservation_end_at=evaluation_end_at,
        )

    @_hide_persistence_details
    def reduce_capacity(
        self,
        *,
        accessory_type_id: int,
        warehouse_id: int,
        quantity: int,
        effective_at: datetime,
        evaluation_start_at: datetime,
        evaluation_end_at: datetime,
        actor_type: str,
        actor_id: Optional[str],
        operation_key: str,
    ) -> AccessoryTypeCounts:
        """Retire only active in-warehouse units with no future link."""

        self._require_explicit_transaction()
        self._validate_quantity(quantity)
        self._validate_window(evaluation_start_at, evaluation_end_at)
        if not isinstance(effective_at, datetime):
            raise AccessoryInputError()
        self._validate_actor(actor_type, actor_id)
        accessory_type = self._repository.lock_accessory_type(accessory_type_id)
        self._require_logical_type(accessory_type, require_active=False)
        warehouse = self._repository.lock_warehouse(warehouse_id)
        self._require_warehouse(warehouse, require_ready=False)
        event_keys = tuple(
            self._event_key(
                "capacity-reduce",
                operation_key,
                f"t{accessory_type_id}:w{warehouse_id}:retired-{index}",
            )
            for index in range(quantity)
        )
        prior_events = self._repository.lock_events(event_keys)
        if prior_events:
            self._validate_capacity_retry(
                events=prior_events,
                expected_keys=event_keys,
                event_type="retired",
                accessory_type_id=accessory_type_id,
                warehouse_id=warehouse_id,
            )
            return self._counts(
                accessory_type=accessory_type,
                warehouse_id=warehouse_id,
                reservation_start_at=evaluation_start_at,
                reservation_end_at=evaluation_end_at,
            )

        units = self._repository.lock_units_for_capacity_reduction(
            accessory_type_id=accessory_type_id,
            warehouse_id=warehouse_id,
        )
        future_links = self._repository.lock_future_links(
            unit_ids=tuple(unit.id for unit in units),
            effective_at=effective_at,
        )
        linked_unit_ids = {link.accessory_unit_id for link in future_links}
        retirement_units = tuple(
            unit for unit in units if unit.id not in linked_unit_ids
        )[:quantity]
        if len(retirement_units) != quantity:
            raise AccessoryCapacityReductionUnavailableError()

        for unit, event_key in zip(retirement_units, event_keys):
            unit.condition_status = "retired"
            unit.row_version += 1
            self._repository.add(
                AccessoryUnitEvent(
                    unit_id=unit.id,
                    event_type="retired",
                    from_warehouse_id=warehouse_id,
                    actor_type=actor_type,
                    actor_id=self._clean_actor_id(actor_id),
                    reason="capacity_decrease",
                    idempotency_key=event_key,
                )
            )
        try:
            self._repository.flush()
        except IntegrityError:
            raise AccessoryPersistenceError() from None
        return self._counts(
            accessory_type=accessory_type,
            warehouse_id=warehouse_id,
            reservation_start_at=evaluation_start_at,
            reservation_end_at=evaluation_end_at,
        )

    def _require_fulfillment_mutable(
        self,
        rental_ids: Sequence[int],
    ) -> None:
        if self._repository.fulfillment_execution_is_frozen(rental_ids):
            raise AccessoryFulfillmentFrozenError()

    def _reservation_retry_counts(
        self,
        *,
        event: AccessoryUnitEvent,
        rental_id: int,
        accessory_type: AccessoryType,
        warehouse_id: int,
        reservation_start_at: datetime,
        reservation_end_at: datetime,
    ) -> AccessoryTypeCounts:
        unit = self._repository.lock_unit(
            accessory_type_id=accessory_type.id,
            unit_id=event.unit_id,
        )
        link = self._repository.lock_link(
            rental_id=rental_id,
            accessory_type_id=accessory_type.id,
        )
        request = self._repository.lock_request(
            rental_id=rental_id,
            accessory_type_id=accessory_type.id,
        )
        if (
            event.event_type != "linked"
            or event.rental_id != rental_id
            or unit is None
            or unit.warehouse_id != warehouse_id
            or request is None
            or link is None
            or link.accessory_unit_id != unit.id
            or link.reservation_start_at != reservation_start_at
            or link.reservation_end_at != reservation_end_at
        ):
            raise AccessoryIdempotencyConflictError()
        return self._counts(
            accessory_type=accessory_type,
            warehouse_id=warehouse_id,
            reservation_start_at=reservation_start_at,
            reservation_end_at=reservation_end_at,
        )

    def _validate_capacity_retry(
        self,
        *,
        events: Sequence[AccessoryUnitEvent],
        expected_keys: Sequence[str],
        event_type: str,
        accessory_type_id: int,
        warehouse_id: int,
    ) -> None:
        if len(events) != len(expected_keys):
            raise AccessoryIdempotencyConflictError()
        if {event.idempotency_key for event in events} != set(expected_keys):
            raise AccessoryIdempotencyConflictError()
        for event in events:
            unit = self._repository.lock_unit(
                accessory_type_id=accessory_type_id,
                unit_id=event.unit_id,
            )
            if (
                event.event_type != event_type
                or unit is None
                or unit.warehouse_id != warehouse_id
            ):
                raise AccessoryIdempotencyConflictError()

    def _counts(
        self,
        *,
        accessory_type: AccessoryType,
        warehouse_id: int,
        reservation_start_at: datetime,
        reservation_end_at: datetime,
    ) -> AccessoryTypeCounts:
        total, reserved, available = self._repository.availability_counts(
            accessory_type_id=accessory_type.id,
            warehouse_id=warehouse_id,
            reservation_start_at=reservation_start_at,
            reservation_end_at=reservation_end_at,
        )
        return AccessoryTypeCounts(
            type_code=accessory_type.name,
            display_name=accessory_type.display_name,
            total=total,
            reserved=reserved,
            available=available,
        )

    def _require_explicit_transaction(self) -> None:
        require_caller_transaction(
            self._session,
            AccessoryTransactionRequiredError,
            accept_nested=True,
        )

    @staticmethod
    def _validate_window(start_at: datetime, end_at: datetime) -> None:
        if (
            not isinstance(start_at, datetime)
            or not isinstance(end_at, datetime)
            or start_at >= end_at
        ):
            raise AccessoryInputError()

    @staticmethod
    def _validate_quantity(quantity: int) -> None:
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise AccessoryInputError()

    @staticmethod
    def _validate_actor(actor_type: str, actor_id: Optional[str]) -> None:
        if (
            not isinstance(actor_type, str)
            or not actor_type.strip()
            or len(actor_type.strip()) > 32
            or (
                actor_id is not None
                and (
                    not isinstance(actor_id, str)
                    or not actor_id.strip()
                    or len(actor_id.strip()) > 64
                )
            )
        ):
            raise AccessoryInputError()

    @staticmethod
    def _clean_actor_id(actor_id: Optional[str]) -> Optional[str]:
        return actor_id.strip() if actor_id is not None else None

    @staticmethod
    def _release_fact_token(
        rental_id: int,
        accessory_type_id: int,
        start_at: datetime,
        end_at: datetime,
    ) -> str:
        canonical = (
            f"{rental_id}\0{accessory_type_id}\0"
            f"{start_at.isoformat(timespec='microseconds')}\0"
            f"{end_at.isoformat(timespec='microseconds')}"
        )
        return sha256(canonical.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _event_key(operation: str, operation_key: str, suffix: str) -> str:
        if (
            not isinstance(operation_key, str)
            or not operation_key.strip()
            or len(operation_key.strip()) > 48
        ):
            raise AccessoryInputError()
        value = f"accessory:{operation}:{operation_key.strip()}:{suffix}"
        if len(value) > 128:
            raise AccessoryInputError()
        return value

    @staticmethod
    def _require_logical_type(
        accessory_type: Optional[AccessoryType],
        *,
        require_active: bool,
    ) -> None:
        if (
            accessory_type is None
            or accessory_type.tracking_mode != "logical_unit"
            or (require_active and accessory_type.is_active is not True)
        ):
            raise AccessoryTypeUnavailableError()

    @staticmethod
    def _require_warehouse(
        warehouse: Optional[Warehouse],
        *,
        require_ready: bool,
    ) -> None:
        if (
            warehouse is None
            or warehouse.status != "active"
            or (require_ready and warehouse.setup_state != "ready")
        ):
            raise AccessoryWarehouseUnavailableError()
