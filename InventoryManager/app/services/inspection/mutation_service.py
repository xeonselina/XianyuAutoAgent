"""Atomic tenant-database inspection mutations.

The caller owns the routed SQLAlchemy transaction.  This module never commits,
rolls back, selects a tenant, or serializes logical-unit identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.accessory_inventory import (
    AccessoryType,
    AccessoryUnit,
    RentalAccessoryUnitLink,
)
from app.models.device import Device
from app.models.inspection_check_item import InspectionCheckItem
from app.models.inspection_record import InspectionRecord
from app.models.rental import Rental
from app.models.warehouse import (
    UserWarehousePreference,
    Warehouse,
)
from app.services.accessory_inventory_service import AccessoryInventoryError
from app.services.accessory_relay_chain_service import (
    AccessoryInspectionReassignmentResult,
    AccessoryRelayChainError,
    AccessoryRelayChainService,
)
from app.services.warehouse_service import DeviceWarehouseLocationService


class InspectionMutationError(RuntimeError):
    code = "INSPECTION_MUTATION_REJECTED"
    public_message = "验货操作未能完成"
    status_code = 409

    def __init__(self, *, data: Mapping[str, object] | None = None) -> None:
        super().__init__(self.public_message)
        self.data = dict(data or {})


class InspectionInputInvalid(InspectionMutationError):
    code = "INSPECTION_INPUT_INVALID"
    public_message = "验货输入无效"
    status_code = 400


class InspectionNotFound(InspectionMutationError):
    code = "INSPECTION_NOT_FOUND"
    public_message = "验货记录不存在"
    status_code = 404


class InspectionRentalNotFound(InspectionMutationError):
    code = "INSPECTION_RENTAL_NOT_FOUND"
    public_message = "租赁记录不存在"
    status_code = 404


class InspectionRentalNotReturned(InspectionMutationError):
    code = "INSPECTION_RENTAL_NOT_RETURNED"
    public_message = "租赁记录尚未进入已寄回状态"


class InspectionAlreadyExists(InspectionMutationError):
    code = "INSPECTION_ALREADY_EXISTS"
    public_message = "该租赁记录已有验货记录，请编辑现有记录"


class InspectionWarehouseRequired(InspectionMutationError):
    code = "INSPECTION_WAREHOUSE_REQUIRED"
    public_message = "多仓模式必须选择实际验货仓"
    status_code = 400


class InspectionWarehouseUnavailable(InspectionMutationError):
    code = "INSPECTION_WAREHOUSE_UNAVAILABLE"
    public_message = "验货仓不可用"


class InspectionAccessoryReceiptsMismatch(InspectionMutationError):
    code = "INSPECTION_ACCESSORY_RECEIPTS_MISMATCH"
    public_message = "逻辑附件验收结果与当前持有事实不一致"


class InspectionAccessoryRejected(InspectionMutationError):
    def __init__(
        self,
        source: AccessoryInventoryError | AccessoryRelayChainError,
    ) -> None:
        self.code = source.code
        self.public_message = source.public_message
        super().__init__()


@dataclass(frozen=True, slots=True)
class InspectionCheckInput:
    name: str
    is_checked: bool
    order: int


@dataclass(frozen=True, slots=True)
class InspectionReceiptInput:
    accessory_type_id: int
    outcome: str


@dataclass(frozen=True, slots=True)
class InspectionCreateInput:
    rental_id: int
    device_id: int
    warehouse_id: int | None
    check_items: tuple[InspectionCheckInput, ...]
    accessory_receipts: tuple[InspectionReceiptInput, ...]


@dataclass(frozen=True, slots=True)
class InspectionCheckUpdateInput:
    check_item_id: int
    is_checked: bool


@dataclass(frozen=True, slots=True)
class InspectionUpdateInput:
    check_items: tuple[InspectionCheckUpdateInput, ...]


@dataclass(frozen=True, slots=True)
class InspectionCreateResult:
    inspection_id: int
    accessory_reassignments: tuple[AccessoryInspectionReassignmentResult, ...]


def parse_create_input(value: object) -> InspectionCreateInput:
    if not isinstance(value, Mapping):
        raise InspectionInputInvalid()
    raw_checks = value.get("check_items")
    raw_receipts = value.get("accessory_receipts", ())
    if not isinstance(raw_checks, list) or not 1 <= len(raw_checks) <= 100:
        raise InspectionInputInvalid()
    if not isinstance(raw_receipts, list) or len(raw_receipts) > 50:
        raise InspectionInputInvalid()

    checks: list[InspectionCheckInput] = []
    for raw in raw_checks:
        if not isinstance(raw, Mapping):
            raise InspectionInputInvalid()
        name = _required_text(raw.get("name"), maximum=1020)
        checked = raw.get("is_checked", False)
        order = raw.get("order", 0)
        if not isinstance(checked, bool):
            raise InspectionInputInvalid()
        if isinstance(order, bool) or not isinstance(order, int) or not 0 <= order <= 10000:
            raise InspectionInputInvalid()
        checks.append(InspectionCheckInput(name, checked, order))

    receipts: list[InspectionReceiptInput] = []
    seen_types: set[int] = set()
    for raw in raw_receipts:
        if not isinstance(raw, Mapping):
            raise InspectionInputInvalid()
        accessory_type_id = _positive_integer(raw.get("accessory_type_id"))
        outcome = raw.get("outcome")
        if outcome not in {"received_normal", "received_damaged", "missing"}:
            raise InspectionInputInvalid()
        if accessory_type_id in seen_types:
            raise InspectionInputInvalid()
        seen_types.add(accessory_type_id)
        receipts.append(InspectionReceiptInput(accessory_type_id, outcome))

    warehouse_value = value.get("warehouse_id")
    warehouse_id = (
        None if warehouse_value is None else _positive_integer(warehouse_value)
    )
    return InspectionCreateInput(
        rental_id=_positive_integer(value.get("rental_id")),
        device_id=_positive_integer(value.get("device_id")),
        warehouse_id=warehouse_id,
        check_items=tuple(checks),
        accessory_receipts=tuple(sorted(receipts, key=lambda item: item.accessory_type_id)),
    )


def parse_update_input(value: object) -> InspectionUpdateInput:
    if not isinstance(value, Mapping):
        raise InspectionInputInvalid()
    raw_checks = value.get("check_items")
    if not isinstance(raw_checks, list) or not 1 <= len(raw_checks) <= 100:
        raise InspectionInputInvalid()
    checks: list[InspectionCheckUpdateInput] = []
    seen_ids: set[int] = set()
    for raw in raw_checks:
        if not isinstance(raw, Mapping):
            raise InspectionInputInvalid()
        item_id = _positive_integer(raw.get("id"))
        checked = raw.get("is_checked")
        if not isinstance(checked, bool) or item_id in seen_ids:
            raise InspectionInputInvalid()
        seen_ids.add(item_id)
        checks.append(InspectionCheckUpdateInput(item_id, checked))
    return InspectionUpdateInput(
        check_items=tuple(sorted(checks, key=lambda item: item.check_item_id))
    )


class InspectionMutationService:
    @classmethod
    def create(
        cls,
        *,
        tenant_session: Session,
        request: InspectionCreateInput,
        database_now: datetime,
        request_id: str,
        actor_id: str,
    ) -> InspectionCreateResult:
        peeked = tenant_session.execute(
            select(Rental.id, Rental.device_id, Rental.parent_rental_id)
            .where(Rental.id == request.rental_id)
        ).one_or_none()
        if peeked is None or peeked.parent_rental_id is not None:
            raise InspectionRentalNotFound()

        occurred_at = _database_naive_utc(database_now)
        accessory_chain = AccessoryRelayChainService(tenant_session)
        try:
            inspection_lock_scope = accessory_chain.lock_inspection_context(
                rental_id=request.rental_id,
                accessory_type_ids=tuple(
                    receipt.accessory_type_id
                    for receipt in request.accessory_receipts
                ),
                occurred_at=occurred_at,
            )
        except (AccessoryInventoryError, AccessoryRelayChainError) as exc:
            raise InspectionAccessoryRejected(exc) from None

        device = tenant_session.execute(
            select(Device).where(Device.id == peeked.device_id).with_for_update()
        ).scalar_one_or_none()
        rental = tenant_session.execute(
            select(Rental).where(Rental.id == request.rental_id).with_for_update()
        ).scalar_one_or_none()
        if (
            device is None
            or rental is None
            or rental.parent_rental_id is not None
            or device.id != request.device_id
            or rental.device_id != device.id
        ):
            raise InspectionRentalNotFound()
        if rental.status != "returned":
            raise InspectionRentalNotReturned()

        existing = tenant_session.execute(
            select(InspectionRecord.id)
            .where(InspectionRecord.rental_id == rental.id)
            .order_by(InspectionRecord.id.asc())
            .with_for_update()
        ).first()
        if existing is not None:
            raise InspectionAlreadyExists(data={"inspection_id": existing.id})

        warehouses = tuple(
            tenant_session.execute(
                select(Warehouse)
                .where(
                    Warehouse.status == "active",
                    Warehouse.setup_state == "ready",
                )
                .order_by(Warehouse.is_default.desc(), Warehouse.id.asc())
                .with_for_update()
            ).scalars().all()
        )
        if not warehouses:
            raise InspectionWarehouseUnavailable()
        if request.warehouse_id is None:
            if len(warehouses) != 1:
                raise InspectionWarehouseRequired()
            target_warehouse = warehouses[0]
        else:
            target_warehouse = next(
                (item for item in warehouses if item.id == request.warehouse_id),
                None,
            )
            if target_warehouse is None:
                raise InspectionWarehouseUnavailable()

        held_rows = tenant_session.execute(
            select(
                RentalAccessoryUnitLink.accessory_type_id,
                AccessoryType.display_name,
            )
            .join(
                AccessoryUnit,
                AccessoryUnit.id == RentalAccessoryUnitLink.accessory_unit_id,
            )
            .join(
                AccessoryType,
                AccessoryType.id == RentalAccessoryUnitLink.accessory_type_id,
            )
            .where(
                RentalAccessoryUnitLink.rental_id == rental.id,
                AccessoryUnit.current_holder_rental_id == rental.id,
            )
            .order_by(RentalAccessoryUnitLink.accessory_type_id.asc())
            .with_for_update()
        ).all()
        expected_type_ids = {row.accessory_type_id for row in held_rows}
        submitted_type_ids = {
            item.accessory_type_id for item in request.accessory_receipts
        }
        if expected_type_ids != submitted_type_ids:
            raise InspectionAccessoryReceiptsMismatch(
                data={"expected_accessory_type_ids": sorted(expected_type_ids)}
            )

        status = (
            "normal"
            if all(item.is_checked for item in request.check_items)
            and all(
                receipt.outcome == "received_normal"
                for receipt in request.accessory_receipts
            )
            else "abnormal"
        )
        record = InspectionRecord(
            rental_id=rental.id,
            device_id=device.id,
            status=status,
            inspector_user_uuid=actor_id,
            warehouse_id=target_warehouse.id,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
        tenant_session.add(record)
        tenant_session.flush()
        tenant_session.add_all(
            tuple(
                InspectionCheckItem(
                    inspection_record_id=record.id,
                    item_name=item.name,
                    is_checked=item.is_checked,
                    item_order=item.order,
                )
                for item in request.check_items
            )
        )

        from_warehouse_id = device.warehouse_id
        if from_warehouse_id != target_warehouse.id:
            DeviceWarehouseLocationService.move_locked_device(
                tenant_session=tenant_session,
                device=device,
                target_warehouse=target_warehouse,
                source="inspection",
                actor_user_id=actor_id,
                related_resource_type="inspection_record",
                related_resource_id=str(record.id),
            )

        accessory_reassignments: list[AccessoryInspectionReassignmentResult] = []
        for receipt in request.accessory_receipts:
            try:
                accessory_reassignments.append(
                    accessory_chain.inspect_return_and_reassign(
                        rental_id=rental.id,
                        accessory_type_id=receipt.accessory_type_id,
                        warehouse_id=target_warehouse.id,
                        outcome=receipt.outcome,
                        occurred_at=occurred_at,
                        actor_type="user",
                        actor_id=actor_id,
                        operation_key=f"{request_id}:inspection:{record.id}",
                        expected_affected_rental_ids=(
                            inspection_lock_scope.affected_rental_ids(
                                receipt.accessory_type_id
                            )
                        ),
                    )
                )
            except (AccessoryInventoryError, AccessoryRelayChainError) as exc:
                raise InspectionAccessoryRejected(exc) from None

        preference = tenant_session.execute(
            select(UserWarehousePreference)
            .where(
                UserWarehousePreference.user_id == actor_id,
                UserWarehousePreference.scene == "inspection",
            )
            .with_for_update()
        ).scalar_one_or_none()
        if preference is None:
            tenant_session.add(
                UserWarehousePreference(
                    user_id=actor_id,
                    scene="inspection",
                    warehouse_id=target_warehouse.id,
                    updated_at=occurred_at,
                )
            )
        else:
            preference.warehouse_id = target_warehouse.id
            preference.updated_at = occurred_at
        tenant_session.flush()
        return InspectionCreateResult(
            inspection_id=record.id,
            accessory_reassignments=tuple(accessory_reassignments),
        )

    @classmethod
    def update(
        cls,
        *,
        tenant_session: Session,
        inspection_id: int,
        request: InspectionUpdateInput,
        database_now: datetime,
    ) -> int:
        record = tenant_session.execute(
            select(InspectionRecord)
            .where(InspectionRecord.id == inspection_id)
            .with_for_update()
        ).scalar_one_or_none()
        if record is None:
            raise InspectionNotFound()
        item_ids = tuple(item.check_item_id for item in request.check_items)
        rows = tuple(
            tenant_session.execute(
                select(InspectionCheckItem)
                .where(InspectionCheckItem.id.in_(item_ids))
                .order_by(InspectionCheckItem.id.asc())
                .with_for_update()
            ).scalars().all()
        )
        if (
            len(rows) != len(item_ids)
            or any(row.inspection_record_id != record.id for row in rows)
        ):
            raise InspectionInputInvalid()
        updates = {item.check_item_id: item.is_checked for item in request.check_items}
        for row in rows:
            row.is_checked = updates[row.id]

        all_items = tuple(
            tenant_session.execute(
                select(InspectionCheckItem)
                .where(InspectionCheckItem.inspection_record_id == record.id)
                .order_by(InspectionCheckItem.id.asc())
                .with_for_update()
            ).scalars().all()
        )
        abnormal_accessory = tenant_session.execute(
            select(AccessoryUnit.id)
            .join(
                RentalAccessoryUnitLink,
                RentalAccessoryUnitLink.accessory_unit_id == AccessoryUnit.id,
            )
            .where(
                RentalAccessoryUnitLink.rental_id == record.rental_id,
                AccessoryUnit.condition_status.in_(("maintenance", "lost")),
            )
            .limit(1)
        ).first()
        record.status = (
            "normal"
            if all(item.is_checked for item in all_items)
            and abnormal_accessory is None
            else "abnormal"
        )
        record.updated_at = _database_naive_utc(database_now)
        tenant_session.flush()
        return record.id


def _positive_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InspectionInputInvalid()
    return value


def _required_text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise InspectionInputInvalid()
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise InspectionInputInvalid()
    return normalized


def _database_naive_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise InspectionInputInvalid()
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


__all__ = [
    "InspectionAccessoryReceiptsMismatch",
    "InspectionAlreadyExists",
    "InspectionCreateInput",
    "InspectionCreateResult",
    "InspectionInputInvalid",
    "InspectionMutationError",
    "InspectionMutationService",
    "InspectionNotFound",
    "InspectionRentalNotFound",
    "InspectionRentalNotReturned",
    "InspectionUpdateInput",
    "InspectionWarehouseRequired",
    "InspectionWarehouseUnavailable",
    "parse_create_input",
    "parse_update_input",
]
