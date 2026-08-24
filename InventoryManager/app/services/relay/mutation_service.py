"""Caller-transaction Relay mutations for the routed tenant database."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import re

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.device import Device
from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding
from app.models.rental_relay_case import RentalRelayCase
from app.services.accessory_relay_chain_service import (
    AccessoryRelayChainConflictError,
    AccessoryRelayChainError,
    AccessoryRelayChainService,
)
from app.services.relay.relay_case_service import RelayCaseService
from app.services.relay.relay_case_service import STATUS_ORDER


_RESULT_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class RelayManualMutationError(RuntimeError):
    code = "RELAY_MANUAL_MUTATION_FAILED"
    status_code = 409
    public_message = "人工接力建立失败，请刷新后重试"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class RelayManualMutationInvalid(RelayManualMutationError):
    code = "RELAY_MANUAL_MUTATION_INVALID"
    status_code = 400
    public_message = "人工接力参数无效"


class RelayManualMutationConflict(RelayManualMutationError):
    code = "RELAY_MANUAL_MUTATION_CONFLICT"
    status_code = 409
    public_message = "接力关系已变化，请刷新后重试"


class RelayManualMutationPersistenceError(RelayManualMutationError):
    code = "RELAY_MANUAL_MUTATION_PERSISTENCE_FAILED"
    status_code = 503
    public_message = "租户接力写服务尚未就绪"


class RelayStatusMutationError(RuntimeError):
    code = "RELAY_STATUS_MUTATION_FAILED"
    status_code = 409
    public_message = "接力状态更新失败，请刷新后重试"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class RelayStatusMutationInvalid(RelayStatusMutationError):
    code = "RELAY_STATUS_MUTATION_INVALID"
    status_code = 400
    public_message = "接力状态参数无效"


class RelayStatusMutationConflict(RelayStatusMutationError):
    code = "RELAY_STATUS_MUTATION_CONFLICT"
    status_code = 409
    public_message = "接力状态已变化，请刷新后重试"


class RelayStatusExternalMutationUnavailable(RelayStatusMutationError):
    code = "RELAY_STATUS_EXTERNAL_MUTATION_UNAVAILABLE"
    status_code = 503
    public_message = "接力发货与完成服务尚未就绪"


class RelayStatusMutationPersistenceError(RelayStatusMutationError):
    code = "RELAY_STATUS_MUTATION_PERSISTENCE_FAILED"
    status_code = 503
    public_message = "租户接力写服务尚未就绪"


@dataclass(frozen=True, slots=True)
class RelayManualMutationResult:
    relay_case: RentalRelayCase
    accessory_chain: dict[str, object]


class RelayManualMutationService:
    """Create one manual Relay binding without owning or committing Session."""

    @classmethod
    def create(
        cls,
        *,
        tenant_session: Session,
        device_id: int,
        database_now: datetime,
        actor_id: str,
        operation_key: str,
    ) -> RelayManualMutationResult:
        cls._validate_inputs(
            tenant_session=tenant_session,
            device_id=device_id,
            database_now=database_now,
            actor_id=actor_id,
            operation_key=operation_key,
        )
        occurred_at = database_now.replace(tzinfo=None)
        try:
            initial_pair = RelayCaseService._manual_pairs(
                tenant_session=tenant_session
            ).get(device_id)
            if initial_pair is None:
                raise RelayManualMutationConflict()

            device = tenant_session.execute(
                select(Device)
                .where(Device.id == device_id)
                .with_for_update()
            ).scalar_one_or_none()
            if (
                device is None
                or device.is_accessory is True
                or device.lifecycle_status != "active"
            ):
                raise RelayManualMutationConflict()

            # Every Relay mutation on a serialized device uses the same
            # device -> rentals prefix before case/accessory locks.
            tenant_session.execute(
                select(Rental)
                .where(
                    Rental.device_id == device_id,
                    Rental.parent_rental_id.is_(None),
                )
                .order_by(Rental.id.asc())
                .with_for_update()
            ).scalars().all()

            latest_pair = RelayCaseService._manual_pairs(
                tenant_session=tenant_session
            ).get(device_id)
            if latest_pair is None or (
                latest_pair[0].id != initial_pair[0].id
                or latest_pair[1].id != initial_pair[1].id
            ):
                raise RelayManualMutationConflict()
            predecessor, successor = latest_pair

            relay_case = tenant_session.execute(
                select(RentalRelayCase)
                .where(
                    RentalRelayCase.predecessor_rental_id == predecessor.id,
                    RentalRelayCase.successor_rental_id == successor.id,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if relay_case is not None and relay_case.status in {
                "agreed",
                "shipped",
                "completed",
            }:
                raise RelayManualMutationConflict()

            bindings = tuple(
                tenant_session.execute(
                    select(RentalRelayBinding)
                    .where(
                        or_(
                            RentalRelayBinding.predecessor_rental_id
                            == predecessor.id,
                            RentalRelayBinding.successor_rental_id
                            == successor.id,
                        )
                    )
                    .order_by(RentalRelayBinding.id.asc())
                    .with_for_update()
                )
                .scalars()
                .all()
            )
            if bindings:
                raise RelayManualMutationConflict()

            try:
                RentalRelayBinding.validate_pair(predecessor, successor)
            except ValueError:
                raise RelayManualMutationConflict() from None

            tenant_session.add(RentalRelayBinding(
                predecessor_rental_id=predecessor.id,
                successor_rental_id=successor.id,
                confirmed_at=occurred_at,
                created_at=occurred_at,
                updated_at=occurred_at,
            ))
            if relay_case is None:
                relay_case = RentalRelayCase(
                    predecessor_rental_id=predecessor.id,
                    successor_rental_id=successor.id,
                    created_at=occurred_at,
                )
            relay_case.status = "agreed"
            relay_case.updated_at = occurred_at
            RelayCaseService._update_milestones(
                relay_case,
                "agreed",
                occurred_at,
            )
            tenant_session.add(relay_case)
            tenant_session.flush()

            plan = AccessoryRelayChainService(
                tenant_session
            ).recompute_from_case(
                relay_case_id=relay_case.id,
                actor_type="tenant_user",
                actor_id=actor_id,
                operation_key=operation_key,
            )
            tenant_session.add(AuditLog(
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
                    "actor_id": actor_id,
                    "operation_key": operation_key,
                },
                created_at=occurred_at,
            ))
            tenant_session.flush()
            return RelayManualMutationResult(
                relay_case=relay_case,
                accessory_chain=asdict(plan),
            )
        except RelayManualMutationError:
            raise
        except (IntegrityError, AccessoryRelayChainConflictError):
            raise RelayManualMutationConflict() from None
        except AccessoryRelayChainError:
            raise RelayManualMutationPersistenceError() from None
        except SQLAlchemyError:
            raise RelayManualMutationPersistenceError() from None

    @staticmethod
    def _validate_inputs(
        *,
        tenant_session: Session,
        device_id: int,
        database_now: datetime,
        actor_id: str,
        operation_key: str,
    ) -> None:
        if (
            not isinstance(tenant_session, Session)
            or not tenant_session.in_transaction()
            or isinstance(device_id, bool)
            or not isinstance(device_id, int)
            or device_id <= 0
            or not isinstance(database_now, datetime)
            or database_now.tzinfo is None
            or database_now.utcoffset() is None
            or not isinstance(actor_id, str)
            or not actor_id.strip()
            or len(actor_id.strip()) > 64
            or not isinstance(operation_key, str)
            or not operation_key.strip()
            or len(operation_key.strip()) > 160
        ):
            raise RelayManualMutationInvalid()


class RelayStatusMutationService:
    """Persist provider-free Relay stages and D34 internal notes atomically."""

    LOCAL_STATUSES = frozenset(("pending", "notified", "agreed"))
    EXTERNAL_PROJECTION_STATUSES = frozenset(("shipped", "completed"))

    @classmethod
    def update(
        cls,
        *,
        tenant_session: Session,
        predecessor_id: int,
        successor_id: int,
        status: str,
        accessory_note_provided: bool,
        accessory_note: str | None,
        database_now: datetime,
        actor_id: str,
        operation_key: str,
        tenant_timezone: str,
    ) -> RelayManualMutationResult:
        cls._validate_inputs(
            tenant_session=tenant_session,
            predecessor_id=predecessor_id,
            successor_id=successor_id,
            status=status,
            accessory_note_provided=accessory_note_provided,
            accessory_note=accessory_note,
            database_now=database_now,
            actor_id=actor_id,
            operation_key=operation_key,
            tenant_timezone=tenant_timezone,
        )
        if status not in cls.LOCAL_STATUSES:
            raise RelayStatusExternalMutationUnavailable()
        return cls._mutate(
            tenant_session=tenant_session,
            predecessor_id=predecessor_id,
            successor_id=successor_id,
            status=status,
            accessory_note_provided=accessory_note_provided,
            accessory_note=accessory_note,
            sf_tracking_number=None,
            database_now=database_now,
            actor_id=actor_id,
            operation_key=operation_key,
            tenant_timezone=tenant_timezone,
            external_projection=False,
            source_result_digest=None,
        )

    @classmethod
    def project_external_stage(
        cls,
        *,
        tenant_session: Session,
        predecessor_id: int,
        successor_id: int,
        status: str,
        sf_tracking_number: str | None,
        database_now: datetime,
        actor_id: str,
        operation_key: str,
        tenant_timezone: str,
        source_result_digest: str | None = None,
    ) -> RelayManualMutationResult:
        """Project one already-authorized external stage without side effects.

        This internal transaction boundary never calls SF, Xianyu, printing,
        or a control database.  A future durable execution/reconciliation
        worker may call it only after it owns the corresponding external
        result.  The public HTTP runtime deliberately continues to reject
        ``shipped`` and ``completed`` until that orchestration is installed.
        """

        cls._validate_inputs(
            tenant_session=tenant_session,
            predecessor_id=predecessor_id,
            successor_id=successor_id,
            status=status,
            accessory_note_provided=False,
            accessory_note=None,
            database_now=database_now,
            actor_id=actor_id,
            operation_key=operation_key,
            tenant_timezone=tenant_timezone,
        )
        if status not in cls.EXTERNAL_PROJECTION_STATUSES:
            raise RelayStatusMutationInvalid()
        if sf_tracking_number is not None and (
            not isinstance(sf_tracking_number, str)
            or not sf_tracking_number.strip()
            or len(sf_tracking_number.strip()) > 50
        ):
            raise RelayStatusMutationInvalid()
        if status == "shipped" and sf_tracking_number is None:
            raise RelayStatusMutationInvalid()
        if source_result_digest is not None and (
            not isinstance(source_result_digest, str)
            or _RESULT_DIGEST.fullmatch(source_result_digest) is None
        ):
            raise RelayStatusMutationInvalid()
        return cls._mutate(
            tenant_session=tenant_session,
            predecessor_id=predecessor_id,
            successor_id=successor_id,
            status=status,
            accessory_note_provided=False,
            accessory_note=None,
            sf_tracking_number=(
                sf_tracking_number.strip()
                if sf_tracking_number is not None
                else None
            ),
            database_now=database_now,
            actor_id=actor_id,
            operation_key=operation_key,
            tenant_timezone=tenant_timezone,
            external_projection=True,
            source_result_digest=source_result_digest,
        )

    @classmethod
    def _mutate(
        cls,
        *,
        tenant_session: Session,
        predecessor_id: int,
        successor_id: int,
        status: str,
        accessory_note_provided: bool,
        accessory_note: str | None,
        sf_tracking_number: str | None,
        database_now: datetime,
        actor_id: str,
        operation_key: str,
        tenant_timezone: str,
        external_projection: bool,
        source_result_digest: str | None,
    ) -> RelayManualMutationResult:
        occurred_at = database_now.replace(tzinfo=None)
        try:
            predecessor_peek = tenant_session.get(Rental, predecessor_id)
            if predecessor_peek is None:
                raise RelayStatusMutationConflict()
            device_id = predecessor_peek.device_id
            device = tenant_session.execute(
                select(Device)
                .where(Device.id == device_id)
                .with_for_update()
            ).scalar_one_or_none()
            if (
                device is None
                or device.is_accessory is True
                or device.lifecycle_status != "active"
            ):
                raise RelayStatusMutationConflict()

            rentals = tuple(
                tenant_session.execute(
                    select(Rental)
                    .where(
                        Rental.device_id == device_id,
                        Rental.parent_rental_id.is_(None),
                    )
                    .order_by(Rental.id.asc())
                    .with_for_update()
                )
                .scalars()
                .all()
            )
            rental_by_id = {rental.id: rental for rental in rentals}
            predecessor = rental_by_id.get(predecessor_id)
            successor = rental_by_id.get(successor_id)
            if predecessor is None or successor is None:
                raise RelayStatusMutationConflict()
            rental_ids = tuple(sorted(rental_by_id))

            cases = tuple(
                tenant_session.execute(
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
            relay_case = next(
                (
                    item for item in cases
                    if item.predecessor_rental_id == predecessor_id
                    and item.successor_rental_id == successor_id
                ),
                None,
            )

            bindings = tuple(
                tenant_session.execute(
                    select(RentalRelayBinding)
                    .where(
                        or_(
                            RentalRelayBinding.predecessor_rental_id.in_(
                                rental_ids
                            ),
                            RentalRelayBinding.successor_rental_id.in_(
                                rental_ids
                            ),
                        )
                    )
                    .order_by(RentalRelayBinding.id.asc())
                    .with_for_update()
                )
                .scalars()
                .all()
            )
            exact_binding = next(
                (
                    item for item in bindings
                    if item.predecessor_rental_id == predecessor_id
                    and item.successor_rental_id == successor_id
                ),
                None,
            )
            old_status = (
                relay_case.status
                if relay_case is not None
                else ("agreed" if exact_binding is not None else "pending")
            )
            if external_projection:
                if relay_case is None or exact_binding is None:
                    raise RelayStatusMutationConflict()
                if status == "shipped" and old_status not in {
                    "agreed",
                    "shipped",
                }:
                    raise RelayStatusMutationConflict()
                if status == "completed" and old_status not in {
                    "shipped",
                    "completed",
                }:
                    raise RelayStatusMutationConflict()
                existing_tracking = (
                    relay_case.sf_tracking_number or ""
                ).strip()
                if status == "shipped":
                    if (
                        old_status == "shipped"
                        and existing_tracking != sf_tracking_number
                    ):
                        raise RelayStatusMutationConflict()
                elif (
                    not existing_tracking
                    or (
                        sf_tracking_number is not None
                        and sf_tracking_number != existing_tracking
                    )
                ):
                    raise RelayStatusMutationConflict()
            elif old_status in {"shipped", "completed"}:
                raise RelayStatusMutationConflict()

            crossing_into_agreed = (
                STATUS_ORDER[old_status] < STATUS_ORDER["agreed"]
                and status == "agreed"
            )
            manual_case = False
            if (
                not external_projection
                and crossing_into_agreed
                and relay_case is not None
                and relay_case.id is not None
            ):
                manual_case = tenant_session.execute(
                    select(AuditLog.id)
                    .where(
                        AuditLog.action == "relay_case_manually_created",
                        AuditLog.resource_type == "rental_relay_case",
                        AuditLog.resource_id == str(relay_case.id),
                    )
                    .limit(1)
                ).scalar_one_or_none() is not None
            if (
                not external_projection
                and crossing_into_agreed
                and exact_binding is None
                and not manual_case
            ):
                candidates = RelayCaseService.find_candidates(
                    tenant_session=tenant_session,
                    tenant_timezone=tenant_timezone,
                )
                if (predecessor_id, successor_id) not in candidates:
                    raise RelayStatusMutationConflict()

            if (
                not external_projection
                and status == "agreed"
                and exact_binding is None
            ):
                predecessor_conflict = any(
                    binding.predecessor_rental_id == predecessor_id
                    and binding.successor_rental_id != successor_id
                    for binding in bindings
                )
                successor_conflict = any(
                    binding.successor_rental_id == successor_id
                    and binding.predecessor_rental_id != predecessor_id
                    for binding in bindings
                )
                if predecessor_conflict or successor_conflict:
                    raise RelayStatusMutationConflict()
                try:
                    RentalRelayBinding.validate_pair(
                        predecessor,
                        successor,
                    )
                except ValueError:
                    raise RelayStatusMutationConflict() from None
                exact_binding = RentalRelayBinding(
                    predecessor_rental_id=predecessor_id,
                    successor_rental_id=successor_id,
                    confirmed_at=occurred_at,
                    created_at=occurred_at,
                    updated_at=occurred_at,
                )
                tenant_session.add(exact_binding)
            elif (
                not external_projection
                and status != "agreed"
                and exact_binding is not None
            ):
                tenant_session.delete(exact_binding)

            if relay_case is None:
                relay_case = RentalRelayCase(
                    predecessor_rental_id=predecessor_id,
                    successor_rental_id=successor_id,
                    created_at=occurred_at,
                )
            note_changed = False
            if not external_projection and accessory_note_provided:
                note_changed = relay_case.accessory_note != accessory_note
                if note_changed:
                    relay_case.accessory_note = accessory_note
                    relay_case.accessory_note_updated_by = actor_id
                    relay_case.accessory_note_updated_at = occurred_at
            is_replay = old_status == status
            if not external_projection:
                relay_case.status = status
                relay_case.updated_at = occurred_at
                RelayCaseService._update_milestones(
                    relay_case,
                    status,
                    occurred_at,
                )
                tenant_session.add(relay_case)
                tenant_session.flush()

            chain_result: dict[str, object] = {}
            if external_projection and status == "shipped":
                chain_service = AccessoryRelayChainService(tenant_session)
                if old_status == "agreed":
                    plan = chain_service.recompute_from_case(
                        relay_case_id=relay_case.id,
                        actor_type="tenant_user",
                        actor_id=actor_id,
                        operation_key=operation_key,
                    )
                    handoff = chain_service.handoff_case(
                        relay_case_id=relay_case.id,
                        actor_type="tenant_user",
                        actor_id=actor_id,
                        operation_key=operation_key,
                    )
                    chain_result = {**asdict(plan), **asdict(handoff)}
                    relay_case.sf_tracking_number = sf_tracking_number
                    successor.ship_out_tracking_no = sf_tracking_number
                    successor.status = "shipped"
                    if successor.ship_out_time is None:
                        successor.ship_out_time = occurred_at
                else:
                    chain_result = asdict(
                        chain_service.handoff_case(
                            relay_case_id=relay_case.id,
                            actor_type="tenant_user",
                            actor_id=actor_id,
                            operation_key=operation_key,
                        )
                    )
            elif not external_projection and (status == "agreed" or (
                STATUS_ORDER[old_status] >= STATUS_ORDER["agreed"]
                and status != "agreed"
            )):
                chain_result = asdict(
                    AccessoryRelayChainService(
                        tenant_session
                    ).recompute_from_case(
                        relay_case_id=relay_case.id,
                        actor_type="tenant_user",
                        actor_id=actor_id,
                        operation_key=operation_key,
                    )
                )

            if external_projection and not is_replay:
                relay_case.status = status
                relay_case.updated_at = occurred_at
                RelayCaseService._update_milestones(
                    relay_case,
                    status,
                    occurred_at,
                )
                tenant_session.add(relay_case)
                tenant_session.flush()

            if not is_replay:
                audit_details = {
                    "predecessor_rental_id": predecessor_id,
                    "successor_rental_id": successor_id,
                    "old_status": old_status,
                    "new_status": status,
                    "actor_id": actor_id,
                    "operation_key": operation_key,
                    "external_projection": external_projection,
                }
                if source_result_digest is not None:
                    audit_details["source_result_digest"] = (
                        source_result_digest
                    )
                tenant_session.add(AuditLog(
                    device_id=device_id,
                    rental_id=predecessor_id,
                    action="relay_case_status_changed",
                    resource_type="rental_relay_case",
                    resource_id=str(relay_case.id),
                    description="接力管理状态变更",
                    details=audit_details,
                    created_at=occurred_at,
                ))
            if note_changed:
                tenant_session.add(AuditLog(
                    device_id=device_id,
                    rental_id=predecessor_id,
                    action="relay_accessory_note_updated",
                    resource_type="rental_relay_case",
                    resource_id=str(relay_case.id),
                    description="接力内部补寄备注已更新",
                    details={
                        "actor_id": actor_id,
                        "operation_key": operation_key,
                        "note_present": accessory_note is not None,
                    },
                    created_at=occurred_at,
                ))
            tenant_session.flush()
            return RelayManualMutationResult(
                relay_case=relay_case,
                accessory_chain=chain_result,
            )
        except RelayStatusMutationError:
            raise
        except (IntegrityError, AccessoryRelayChainConflictError):
            raise RelayStatusMutationConflict() from None
        except AccessoryRelayChainError:
            raise RelayStatusMutationPersistenceError() from None
        except SQLAlchemyError:
            raise RelayStatusMutationPersistenceError() from None

    @classmethod
    def _validate_inputs(
        cls,
        *,
        tenant_session: Session,
        predecessor_id: int,
        successor_id: int,
        status: str,
        accessory_note_provided: bool,
        accessory_note: str | None,
        database_now: datetime,
        actor_id: str,
        operation_key: str,
        tenant_timezone: str,
    ) -> None:
        if (
            not isinstance(tenant_session, Session)
            or not tenant_session.in_transaction()
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                for value in (predecessor_id, successor_id)
            )
            or predecessor_id == successor_id
            or not isinstance(status, str)
            or status not in STATUS_ORDER
            or not isinstance(accessory_note_provided, bool)
            or (
                accessory_note is not None
                and (
                    not isinstance(accessory_note, str)
                    or len(accessory_note) > 500
                )
            )
            or not isinstance(database_now, datetime)
            or database_now.tzinfo is None
            or database_now.utcoffset() is None
            or not isinstance(actor_id, str)
            or not actor_id.strip()
            or len(actor_id.strip()) > 64
            or not isinstance(operation_key, str)
            or not operation_key.strip()
            or len(operation_key.strip()) > 160
            or not isinstance(tenant_timezone, str)
            or not tenant_timezone
        ):
            raise RelayStatusMutationInvalid()


__all__ = [
    "RelayManualMutationConflict",
    "RelayManualMutationError",
    "RelayManualMutationInvalid",
    "RelayManualMutationPersistenceError",
    "RelayManualMutationResult",
    "RelayManualMutationService",
    "RelayStatusExternalMutationUnavailable",
    "RelayStatusMutationConflict",
    "RelayStatusMutationError",
    "RelayStatusMutationInvalid",
    "RelayStatusMutationPersistenceError",
    "RelayStatusMutationService",
]
