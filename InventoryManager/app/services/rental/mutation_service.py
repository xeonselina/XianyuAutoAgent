"""Final tenant-database rental booking mutations.

Preview responses are deliberately not authorization tokens.  This module
re-evaluates the selected device in one caller-owned transaction and uses the
logical-accessory inventory service for the final row-locking allocation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.accessory_inventory import (
    AccessoryType,
    AccessoryUnit,
    DeviceAccessoryConfig,
    RentalAccessoryRequest,
    RentalAccessoryUnitLink,
)
from app.models.device import Device
from app.models.rental import Rental
from app.models.rental_relay_case import RentalRelayCase
from app.models.shipping_execution import OutboundShipment
from app.models.warehouse import Warehouse
from app.services.accessory_inventory_service import (
    AccessoryInventoryError,
    AccessoryInventoryService,
    AccessoryUnitUnavailableError,
)
from app.services.rental.availability_service import (
    RentalAvailabilityInput,
    RentalAvailabilityInvalid,
    RentalAvailabilityService,
    parse_availability_input,
)


_LENS_COMBOS: Final = frozenset({
    "lens_400mm",
    "lens_200mm",
    "bare",
    "lens_dual",
})


class RentalMutationError(RuntimeError):
    """A safe final-write rejection with a stable public code."""

    code = "RENTAL_MUTATION_REJECTED"
    public_message = "租赁记录无法保存"
    status_code = 409

    def __init__(self, *, data: Mapping[str, object] | None = None) -> None:
        super().__init__(self.public_message)
        self.data = dict(data or {})


class RentalMutationInvalid(RentalMutationError):
    code = "RENTAL_MUTATION_INVALID"
    public_message = "租赁记录格式错误"
    status_code = 400


class RentalOriginWarehouseChanged(RentalMutationError):
    code = "ORIGIN_WAREHOUSE_CHANGED"
    public_message = "设备所在仓库已变化，请刷新物流信息后重试"


class RentalUsagePeriodConflict(RentalMutationError):
    code = "USAGE_PERIOD_CONFLICT"
    public_message = "租赁档期冲突"


class RentalAccessoryUnavailable(RentalMutationError):
    code = "ACCESSORY_UNIT_UNAVAILABLE"
    public_message = "所选附件库存已变化，请刷新后重试"


class RentalMutationNotFound(RentalMutationError):
    code = "RENTAL_NOT_FOUND"
    public_message = "租赁记录不存在"
    status_code = 404


class RentalAccessoryChainRecalculationRequired(RentalMutationError):
    code = "ACCESSORY_CHAIN_RECALCULATION_REQUIRED"
    public_message = "该订单已进入附件接力链，请先完成接力链重算"


class RentalStatusTransitionInvalid(RentalMutationError):
    code = "RENTAL_STATUS_TRANSITION_INVALID"
    public_message = "当前租赁状态不允许执行该转换"


class RentalAccessoryFulfillmentRequired(RentalMutationError):
    code = "ACCESSORY_FULFILLMENT_REQUIRED"
    public_message = "逻辑附件尚未备齐，不能确认发货"


class RentalAccessoryInspectionRequired(RentalMutationError):
    code = "ACCESSORY_INSPECTION_REQUIRED"
    public_message = "逻辑附件尚未完成验收入库，不能完成订单"


class RentalDeletionBlocked(RentalMutationError):
    code = "RENTAL_DELETION_BLOCKED"
    public_message = "该订单存在必须保留或先处理的履约事实，不能删除"


@dataclass(frozen=True, slots=True)
class RentalCreateInput:
    device_id: int
    expected_origin_warehouse_id: int
    availability: RentalAvailabilityInput
    customer_name: str
    customer_phone: str | None
    xianyu_order_no: str | None
    buyer_id: str | None
    order_amount: Decimal | None
    includes_handle: bool
    includes_lens_mount: bool
    photo_transfer: bool
    lens_combo: str


@dataclass(frozen=True, slots=True)
class RentalUpdateInput:
    booking: RentalCreateInput
    damage_note_present: bool
    damage_note: str | None


@dataclass(frozen=True, slots=True)
class RentalStatusInput:
    status: str


def parse_create_input(value: object) -> RentalCreateInput:
    if not isinstance(value, Mapping):
        raise RentalMutationInvalid()
    try:
        availability = parse_availability_input(value)
    except RentalAvailabilityInvalid as exc:
        raise RentalMutationInvalid(data={"detail": str(exc)}) from None

    device_id = _positive_integer(value.get("device_id"))
    expected_origin_warehouse_id = _positive_integer(
        value.get("expected_origin_warehouse_id")
    )
    customer_name = _required_text(
        value.get("customer_name"),
        maximum=100,
    )
    customer_phone = _optional_text(
        value.get("customer_phone"),
        maximum=20,
    )
    xianyu_order_no = _optional_text(
        value.get("xianyu_order_no"),
        maximum=50,
    )
    buyer_id = _optional_text(value.get("buyer_id"), maximum=100)
    lens_combo = value.get("lens_combo", "lens_400mm")
    if lens_combo not in _LENS_COMBOS:
        raise RentalMutationInvalid()

    return RentalCreateInput(
        device_id=device_id,
        expected_origin_warehouse_id=expected_origin_warehouse_id,
        availability=availability,
        customer_name=customer_name,
        customer_phone=customer_phone,
        xianyu_order_no=xianyu_order_no,
        buyer_id=buyer_id,
        order_amount=_optional_amount(value.get("order_amount")),
        includes_handle=_boolean(value.get("includes_handle", False)),
        includes_lens_mount=_boolean(
            value.get("includes_lens_mount", False)
        ),
        photo_transfer=_boolean(value.get("photo_transfer", False)),
        lens_combo=lens_combo,
    )


def parse_update_input(value: object) -> RentalUpdateInput:
    if not isinstance(value, Mapping):
        raise RentalMutationInvalid()
    damage_note_present = "damage_note" in value
    damage_note = None
    if damage_note_present:
        damage_note = _optional_text(value.get("damage_note"), maximum=1000)
    return RentalUpdateInput(
        booking=parse_create_input(value),
        damage_note_present=damage_note_present,
        damage_note=damage_note,
    )


def parse_status_input(value: object) -> RentalStatusInput:
    if not isinstance(value, Mapping):
        raise RentalMutationInvalid()
    status = value.get("status")
    if status not in {
        "not_shipped",
        "scheduled_for_shipping",
        "shipped",
        "returned",
        "completed",
        "cancelled",
    }:
        raise RentalMutationInvalid()
    return RentalStatusInput(status=status)


class RentalBookingMutationService:
    """Create an ordinary booking after final locked revalidation."""

    @classmethod
    def create(
        cls,
        *,
        tenant_session: Session,
        request: RentalCreateInput,
        tenant_timezone: str,
        database_now: datetime,
        request_id: str,
        actor_id: str,
    ) -> Mapping[str, object]:
        device = tenant_session.execute(
            select(Device)
            .where(Device.id == request.device_id)
            .with_for_update()
        ).scalar_one_or_none()
        if (
            device is None
            or device.is_accessory is True
            or device.lifecycle_status != "active"
            or device.model_id is None
            or device.warehouse_id is None
        ):
            raise RentalMutationInvalid()
        if device.model_id != request.availability.model_id:
            raise RentalMutationInvalid()

        warehouse = tenant_session.execute(
            select(Warehouse)
            .where(Warehouse.id == device.warehouse_id)
            .with_for_update()
        ).scalar_one_or_none()
        if (
            warehouse is None
            or warehouse.status != "active"
            or warehouse.setup_state != "ready"
        ):
            raise RentalMutationInvalid()
        if warehouse.id != request.expected_origin_warehouse_id:
            changed_origin_evaluation = RentalAvailabilityService.evaluate(
                tenant_session=tenant_session,
                request=replace(
                    request.availability,
                    preferred_warehouse_id=warehouse.id,
                    manual_logistics_by_warehouse={},
                ),
                tenant_timezone=tenant_timezone,
                database_now=database_now,
                request_id=request_id,
            )
            raise RentalOriginWarehouseChanged(data={
                "warehouse": _warehouse_summary(warehouse),
                "estimate": changed_origin_evaluation[
                    "estimate_by_warehouse"
                ].get(str(warehouse.id), {}),
            })

        evaluation = RentalAvailabilityService.evaluate(
            tenant_session=tenant_session,
            request=request.availability,
            tenant_timezone=tenant_timezone,
            database_now=database_now,
            request_id=request_id,
        )
        candidate = next(
            (
                item
                for item in evaluation["candidates"]
                if item["device"]["id"] == device.id
            ),
            None,
        )
        if candidate is None:
            raise RentalMutationInvalid()
        if not candidate["available"]:
            raise RentalUsagePeriodConflict(data={
                "conflicts": candidate["hard_conflicts"],
            })
        if not candidate["submission_ready"]:
            estimate = evaluation["estimate_by_warehouse"].get(
                str(warehouse.id),
                {},
            )
            raise RentalMutationInvalid(data={
                "code": "LOGISTICS_CONFIRMATION_REQUIRED",
                "estimate": estimate,
            })

        logistics_days = int(candidate["logistics_days"])
        planned_ship_out_date = date.fromisoformat(
            candidate["planned_ship_out_date"]
        )
        planned_return_date = date.fromisoformat(
            candidate["planned_return_date"]
        )
        destination = request.availability.destination
        destination_digest = sha256(
            "\x1f".join(
                destination[field]
                for field in (
                    "province",
                    "city",
                    "district",
                    "address_detail",
                )
            ).encode("utf-8")
        ).hexdigest()
        address_summary = "".join(
            destination[field]
            for field in ("province", "city", "district")
        )
        legacy_destination = address_summary + destination["address_detail"]

        rental = Rental(
            device_id=device.id,
            customer_name=request.customer_name,
            customer_phone=request.customer_phone,
            destination=legacy_destination,
            customer_province=destination["province"],
            customer_city=destination["city"],
            customer_district=destination["district"],
            customer_address_detail=destination["address_detail"],
            start_date=request.availability.start_date,
            end_date=request.availability.end_date,
            ship_out_time=datetime.combine(planned_ship_out_date, time.min),
            ship_in_time=datetime.combine(planned_return_date, time.min),
            xianyu_order_no=request.xianyu_order_no,
            order_amount=request.order_amount,
            buyer_id=request.buyer_id,
            status="not_shipped",
            preferred_warehouse_id=(
                request.availability.preferred_warehouse_id
            ),
            logistics_days=logistics_days,
            planned_ship_out_date=planned_ship_out_date,
            planned_return_date=planned_return_date,
            logistics_estimate_origin_warehouse_id=warehouse.id,
            logistics_estimate_provider="manual",
            logistics_estimate_provider_version="manual-confirmation-v1",
            logistics_estimate_rule_version="schedule-overlap-v1",
            logistics_estimate_days=logistics_days,
            logistics_estimate_evaluated_at=database_now.replace(tzinfo=None),
            logistics_estimate_address_digest=destination_digest,
            logistics_estimate_address_summary=address_summary,
            includes_handle=request.includes_handle,
            includes_lens_mount=request.includes_lens_mount,
            photo_transfer=request.photo_transfer,
            lens_combo=request.lens_combo,
        )
        tenant_session.add(rental)
        tenant_session.flush()

        warnings = list(candidate["warnings"])
        reservation_start_at = datetime.combine(
            planned_ship_out_date,
            time.min,
        )
        reservation_end_at = datetime.combine(
            planned_return_date + timedelta(days=1),
            time.min,
        )
        accessory_inventory = AccessoryInventoryService(tenant_session)
        accessory_by_type = {
            int(item["accessory_type_id"]): item
            for item in candidate["accessories"]
            if item["requested"]
        }
        for accessory_type_id in request.availability.requested_accessory_type_ids:
            accessory = accessory_by_type.get(accessory_type_id)
            if accessory is None or accessory["tracking_mode"] != "logical_unit":
                raise RentalMutationInvalid()
            if accessory["relay_confirmation_required"]:
                cls._create_unfulfilled_request(
                    tenant_session,
                    rental_id=rental.id,
                    device_id=device.id,
                    accessory_type_id=accessory_type_id,
                )
                warnings.append({
                    "code": "ACCESSORY_RELAY_CONFIRMATION_REQUIRED",
                    "accessory_type_id": accessory_type_id,
                })
                continue
            if accessory["shortage"]:
                if not candidate["relay_candidate"]:
                    raise RentalAccessoryUnavailable()
                cls._create_unfulfilled_request(
                    tenant_session,
                    rental_id=rental.id,
                    device_id=device.id,
                    accessory_type_id=accessory_type_id,
                )
                warnings.append({
                    "code": "ACCESSORY_UNIT_SHORTAGE_WARNING",
                    "accessory_type_id": accessory_type_id,
                })
                continue
            try:
                accessory_inventory.reserve_for_rental(
                    rental_id=rental.id,
                    accessory_type_id=accessory_type_id,
                    reservation_start_at=reservation_start_at,
                    reservation_end_at=reservation_end_at,
                    actor_type="tenant_user",
                    actor_id=actor_id,
                    operation_key=request_id,
                )
            except AccessoryUnitUnavailableError:
                raise RentalAccessoryUnavailable() from None
            except AccessoryInventoryError as exc:
                raise RentalMutationError(data={"code": exc.code}) from None

        tenant_session.flush()
        return {
            "main_rental": {
                "id": rental.id,
                "device_id": rental.device_id,
                "start_date": rental.start_date.isoformat(),
                "end_date": rental.end_date.isoformat(),
                "status": rental.status,
                "customer_name": rental.customer_name,
                "destination": rental.destination,
                "warehouse": _warehouse_summary(warehouse),
                "requested_accessory_type_ids": list(
                    request.availability.requested_accessory_type_ids
                ),
            },
            "accessory_rentals": [],
            "warnings": warnings,
            "refresh_scope": "current_window",
            "request_id": request_id,
        }

    @classmethod
    def update(
        cls,
        *,
        tenant_session: Session,
        rental_id: int,
        request: RentalUpdateInput,
        tenant_timezone: str,
        database_now: datetime,
        request_id: str,
        actor_id: str,
    ) -> Mapping[str, object]:
        update_input = request
        request = update_input.booking
        source_identity = tenant_session.execute(
            select(Rental.device_id, Rental.parent_rental_id).where(
                Rental.id == rental_id
            )
        ).one_or_none()
        if source_identity is None:
            raise RentalMutationNotFound()
        if source_identity.parent_rental_id is not None:
            raise RentalMutationInvalid()

        device_ids = tuple(sorted({
            int(source_identity.device_id),
            request.device_id,
        }))
        devices = tuple(
            tenant_session.execute(
                select(Device)
                .where(Device.id.in_(device_ids))
                .order_by(Device.id.asc())
                .with_for_update()
            ).scalars()
        )
        device_by_id = {device.id: device for device in devices}
        source_device = device_by_id.get(int(source_identity.device_id))
        target_device = device_by_id.get(request.device_id)
        if source_device is None or target_device is None:
            raise RentalMutationInvalid()
        if (
            target_device.is_accessory is True
            or target_device.lifecycle_status != "active"
            or target_device.model_id is None
            or target_device.warehouse_id is None
            or target_device.model_id != request.availability.model_id
        ):
            raise RentalMutationInvalid()

        rental = tenant_session.execute(
            select(Rental)
            .where(
                Rental.id == rental_id,
                Rental.device_id == source_device.id,
                Rental.parent_rental_id.is_(None),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if rental is None:
            raise RentalMutationNotFound()

        warehouse_ids = tuple(sorted({
            warehouse_id
            for warehouse_id in (
                source_device.warehouse_id,
                target_device.warehouse_id,
            )
            if warehouse_id is not None
        }))
        warehouses = tuple(
            tenant_session.execute(
                select(Warehouse)
                .where(Warehouse.id.in_(warehouse_ids))
                .order_by(Warehouse.id.asc())
                .with_for_update()
            ).scalars()
        )
        warehouse_by_id = {
            warehouse.id: warehouse for warehouse in warehouses
        }
        target_warehouse = warehouse_by_id.get(target_device.warehouse_id)
        if (
            target_warehouse is None
            or target_warehouse.status != "active"
            or target_warehouse.setup_state != "ready"
        ):
            raise RentalMutationInvalid()

        final_availability = replace(
            request.availability,
            exclude_rental_id=rental.id,
        )
        if target_warehouse.id != request.expected_origin_warehouse_id:
            changed_origin_evaluation = RentalAvailabilityService.evaluate(
                tenant_session=tenant_session,
                request=replace(
                    final_availability,
                    preferred_warehouse_id=target_warehouse.id,
                    manual_logistics_by_warehouse={},
                ),
                tenant_timezone=tenant_timezone,
                database_now=database_now,
                request_id=request_id,
            )
            raise RentalOriginWarehouseChanged(data={
                "warehouse": _warehouse_summary(target_warehouse),
                "estimate": changed_origin_evaluation[
                    "estimate_by_warehouse"
                ].get(str(target_warehouse.id), {}),
            })

        evaluation = RentalAvailabilityService.evaluate(
            tenant_session=tenant_session,
            request=final_availability,
            tenant_timezone=tenant_timezone,
            database_now=database_now,
            request_id=request_id,
        )
        candidate = next(
            (
                item
                for item in evaluation["candidates"]
                if item["device"]["id"] == target_device.id
            ),
            None,
        )
        if candidate is None:
            raise RentalMutationInvalid()
        if not candidate["available"]:
            raise RentalUsagePeriodConflict(data={
                "conflicts": candidate["hard_conflicts"],
            })
        if not candidate["submission_ready"]:
            raise RentalMutationInvalid(data={
                "code": "LOGISTICS_CONFIRMATION_REQUIRED",
                "estimate": evaluation["estimate_by_warehouse"].get(
                    str(target_warehouse.id),
                    {},
                ),
            })

        logistics_days = int(candidate["logistics_days"])
        planned_ship_out_date = date.fromisoformat(
            candidate["planned_ship_out_date"]
        )
        planned_return_date = date.fromisoformat(
            candidate["planned_return_date"]
        )
        reservation_start_at = datetime.combine(
            planned_ship_out_date,
            time.min,
        )
        reservation_end_at = datetime.combine(
            planned_return_date + timedelta(days=1),
            time.min,
        )

        existing_requests = tuple(
            tenant_session.execute(
                select(RentalAccessoryRequest)
                .where(RentalAccessoryRequest.rental_id == rental.id)
                .order_by(RentalAccessoryRequest.accessory_type_id.asc())
                .with_for_update()
            ).scalars()
        )
        existing_links = tuple(
            tenant_session.execute(
                select(RentalAccessoryUnitLink)
                .where(RentalAccessoryUnitLink.rental_id == rental.id)
                .order_by(RentalAccessoryUnitLink.accessory_type_id.asc())
                .with_for_update()
            ).scalars()
        )
        request_by_type = {
            item.accessory_type_id: item for item in existing_requests
        }
        link_by_type = {
            item.accessory_type_id: item for item in existing_links
        }
        target_type_ids = set(
            request.availability.requested_accessory_type_ids
        )
        schedule_or_device_changed = (
            source_device.id != target_device.id
            or rental.start_date != request.availability.start_date
            or rental.end_date != request.availability.end_date
            or rental.planned_ship_out_date != planned_ship_out_date
            or rental.planned_return_date != planned_return_date
        )
        requestless_links = [
            link
            for accessory_type_id, link in link_by_type.items()
            if accessory_type_id not in request_by_type
        ]
        if requestless_links and schedule_or_device_changed:
            raise RentalAccessoryChainRecalculationRequired()

        accessory_inventory = AccessoryInventoryService(tenant_session)
        for accessory_type_id in sorted(request_by_type):
            existing_request = request_by_type[accessory_type_id]
            existing_link = link_by_type.get(accessory_type_id)
            must_remove = accessory_type_id not in target_type_ids
            must_reallocate = (
                existing_link is not None
                and (
                    schedule_or_device_changed
                    or existing_link.reservation_start_at
                    != reservation_start_at
                    or existing_link.reservation_end_at
                    != reservation_end_at
                )
            )
            if existing_link is not None and existing_link.source_relay_case_id:
                if must_remove or must_reallocate:
                    raise RentalAccessoryChainRecalculationRequired()
                continue
            if must_remove or must_reallocate:
                if existing_link is not None:
                    accessory_inventory.release_reservation(
                        rental_id=rental.id,
                        accessory_type_id=accessory_type_id,
                        reservation_start_at=existing_link.reservation_start_at,
                        reservation_end_at=existing_link.reservation_end_at,
                        actor_type="tenant_user",
                        actor_id=actor_id,
                        operation_key=request_id,
                    )
                tenant_session.delete(existing_request)
                tenant_session.flush()
                request_by_type.pop(accessory_type_id, None)
                link_by_type.pop(accessory_type_id, None)

        destination = request.availability.destination
        destination_digest = sha256(
            "\x1f".join(
                destination[field]
                for field in (
                    "province",
                    "city",
                    "district",
                    "address_detail",
                )
            ).encode("utf-8")
        ).hexdigest()
        address_summary = "".join(
            destination[field]
            for field in ("province", "city", "district")
        )
        rental.device_id = target_device.id
        rental.customer_name = request.customer_name
        rental.customer_phone = request.customer_phone
        rental.destination = address_summary + destination["address_detail"]
        rental.customer_province = destination["province"]
        rental.customer_city = destination["city"]
        rental.customer_district = destination["district"]
        rental.customer_address_detail = destination["address_detail"]
        rental.start_date = request.availability.start_date
        rental.end_date = request.availability.end_date
        rental.ship_out_time = datetime.combine(
            planned_ship_out_date,
            time.min,
        )
        rental.ship_in_time = datetime.combine(
            planned_return_date,
            time.min,
        )
        rental.xianyu_order_no = request.xianyu_order_no
        rental.order_amount = request.order_amount
        rental.buyer_id = request.buyer_id
        rental.preferred_warehouse_id = (
            request.availability.preferred_warehouse_id
        )
        rental.logistics_days = logistics_days
        rental.planned_ship_out_date = planned_ship_out_date
        rental.planned_return_date = planned_return_date
        rental.logistics_estimate_origin_warehouse_id = target_warehouse.id
        rental.logistics_estimate_provider = "manual"
        rental.logistics_estimate_provider_version = "manual-confirmation-v1"
        rental.logistics_estimate_rule_version = "schedule-overlap-v1"
        rental.logistics_estimate_days = logistics_days
        rental.logistics_estimate_evaluated_at = database_now.replace(
            tzinfo=None
        )
        rental.logistics_estimate_address_digest = destination_digest
        rental.logistics_estimate_address_summary = address_summary
        rental.includes_handle = request.includes_handle
        rental.includes_lens_mount = request.includes_lens_mount
        rental.photo_transfer = request.photo_transfer
        rental.lens_combo = request.lens_combo
        if update_input.damage_note_present:
            rental.damage_note = update_input.damage_note
        tenant_session.flush()

        warnings = list(candidate["warnings"])
        accessory_by_type = {
            int(item["accessory_type_id"]): item
            for item in candidate["accessories"]
            if item["requested"]
        }
        for accessory_type_id in sorted(target_type_ids):
            accessory = accessory_by_type.get(accessory_type_id)
            if accessory is None or accessory["tracking_mode"] != "logical_unit":
                raise RentalMutationInvalid()
            existing_request = request_by_type.get(accessory_type_id)
            existing_link = link_by_type.get(accessory_type_id)
            if existing_request is not None and existing_link is not None:
                continue
            if accessory["relay_confirmation_required"]:
                if existing_request is None:
                    cls._create_unfulfilled_request(
                        tenant_session,
                        rental_id=rental.id,
                        device_id=target_device.id,
                        accessory_type_id=accessory_type_id,
                    )
                warnings.append({
                    "code": "ACCESSORY_RELAY_CONFIRMATION_REQUIRED",
                    "accessory_type_id": accessory_type_id,
                })
                continue
            if accessory["shortage"]:
                if not candidate["relay_candidate"]:
                    raise RentalAccessoryUnavailable()
                if existing_request is None:
                    cls._create_unfulfilled_request(
                        tenant_session,
                        rental_id=rental.id,
                        device_id=target_device.id,
                        accessory_type_id=accessory_type_id,
                    )
                warnings.append({
                    "code": "ACCESSORY_UNIT_SHORTAGE_WARNING",
                    "accessory_type_id": accessory_type_id,
                })
                continue
            if existing_request is not None and existing_link is None:
                tenant_session.delete(existing_request)
                tenant_session.flush()
            try:
                accessory_inventory.reserve_for_rental(
                    rental_id=rental.id,
                    accessory_type_id=accessory_type_id,
                    reservation_start_at=reservation_start_at,
                    reservation_end_at=reservation_end_at,
                    actor_type="tenant_user",
                    actor_id=actor_id,
                    operation_key=request_id,
                )
            except AccessoryUnitUnavailableError:
                raise RentalAccessoryUnavailable() from None
            except AccessoryInventoryError as exc:
                raise RentalMutationError(data={"code": exc.code}) from None

        tenant_session.flush()
        return {
            "rental": {
                "id": rental.id,
                "device_id": rental.device_id,
                "start_date": rental.start_date.isoformat(),
                "end_date": rental.end_date.isoformat(),
                "status": rental.status,
                "customer_name": rental.customer_name,
                "destination": rental.destination,
                "warehouse": _warehouse_summary(target_warehouse),
                "requested_accessory_type_ids": sorted(target_type_ids),
            },
            "warnings": warnings,
            "refresh_scope": "current_window",
            "request_id": request_id,
        }

    @classmethod
    def update_status(
        cls,
        *,
        tenant_session: Session,
        rental_id: int,
        request: RentalStatusInput,
        database_now: datetime,
        request_id: str,
        actor_id: str,
    ) -> Mapping[str, object]:
        source_identity = tenant_session.execute(
            select(Rental.device_id, Rental.parent_rental_id).where(
                Rental.id == rental_id
            )
        ).one_or_none()
        if source_identity is None:
            raise RentalMutationNotFound()
        if source_identity.parent_rental_id is not None:
            raise RentalMutationInvalid()

        device = tenant_session.execute(
            select(Device)
            .where(Device.id == source_identity.device_id)
            .with_for_update()
        ).scalar_one_or_none()
        rental = tenant_session.execute(
            select(Rental)
            .where(
                Rental.id == rental_id,
                Rental.device_id == source_identity.device_id,
                Rental.parent_rental_id.is_(None),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if device is None or rental is None:
            raise RentalMutationNotFound()

        current_status = rental.status
        target_status = request.status
        if current_status == target_status:
            return cls._status_response(
                rental=rental,
                request_id=request_id,
            )
        valid_transitions = {
            "not_shipped": {
                "scheduled_for_shipping",
                "shipped",
                "cancelled",
            },
            "scheduled_for_shipping": {
                "not_shipped",
                "shipped",
                "cancelled",
            },
            "shipped": {"returned"},
            "returned": {"completed"},
            "completed": set(),
            "cancelled": set(),
        }
        if target_status not in valid_transitions.get(current_status, set()):
            raise RentalStatusTransitionInvalid(data={
                "current_status": current_status,
                "requested_status": target_status,
            })

        requests = tuple(
            tenant_session.execute(
                select(RentalAccessoryRequest)
                .where(RentalAccessoryRequest.rental_id == rental.id)
                .order_by(RentalAccessoryRequest.accessory_type_id.asc())
                .with_for_update()
            ).scalars()
        )
        links = tuple(
            tenant_session.execute(
                select(RentalAccessoryUnitLink)
                .where(RentalAccessoryUnitLink.rental_id == rental.id)
                .order_by(RentalAccessoryUnitLink.accessory_type_id.asc())
                .with_for_update()
            ).scalars()
        )
        request_by_type = {
            item.accessory_type_id: item for item in requests
        }
        link_by_type = {
            item.accessory_type_id: item for item in links
        }
        relay_or_travel_link = any(
            link.source_relay_case_id is not None
            or link.accessory_type_id not in request_by_type
            for link in links
        )
        inventory = AccessoryInventoryService(tenant_session)

        if target_status == "shipped":
            if relay_or_travel_link:
                raise RentalAccessoryChainRecalculationRequired()
            if set(request_by_type) != set(link_by_type):
                raise RentalAccessoryFulfillmentRequired()
            for accessory_type_id in sorted(request_by_type):
                try:
                    inventory.dispatch_for_rental(
                        rental_id=rental.id,
                        accessory_type_id=accessory_type_id,
                        actor_type="tenant_user",
                        actor_id=actor_id,
                        operation_key=request_id,
                    )
                except AccessoryInventoryError as exc:
                    raise RentalMutationError(
                        data={"code": exc.code}
                    ) from None

        if target_status == "cancelled":
            if relay_or_travel_link:
                raise RentalAccessoryChainRecalculationRequired()
            for accessory_type_id in sorted(link_by_type):
                link = link_by_type[accessory_type_id]
                try:
                    inventory.release_reservation(
                        rental_id=rental.id,
                        accessory_type_id=accessory_type_id,
                        reservation_start_at=link.reservation_start_at,
                        reservation_end_at=link.reservation_end_at,
                        actor_type="tenant_user",
                        actor_id=actor_id,
                        operation_key=request_id,
                    )
                except AccessoryInventoryError as exc:
                    raise RentalMutationError(
                        data={"code": exc.code}
                    ) from None
            for accessory_request in requests:
                tenant_session.delete(accessory_request)

        if target_status == "completed":
            held_unit_exists = tenant_session.scalar(
                select(AccessoryUnit.id)
                .where(AccessoryUnit.current_holder_rental_id == rental.id)
                .limit(1)
                .with_for_update()
            )
            if held_unit_exists is not None:
                raise RentalAccessoryInspectionRequired()

        occurred_at = database_now.replace(tzinfo=None)
        rental.status = target_status
        if target_status == "shipped":
            if rental.actual_shipped_at is None:
                rental.actual_shipped_at = occurred_at
            if rental.ship_out_time is None:
                rental.ship_out_time = rental.actual_shipped_at
        elif target_status == "returned":
            if rental.actual_returned_at is None:
                rental.actual_returned_at = occurred_at
            if rental.ship_in_time is None:
                rental.ship_in_time = rental.actual_returned_at
        tenant_session.flush()
        return cls._status_response(rental=rental, request_id=request_id)

    @staticmethod
    def _status_response(
        *,
        rental: Rental,
        request_id: str,
    ) -> Mapping[str, object]:
        return {
            "id": rental.id,
            "status": rental.status,
            "ship_out_time": (
                rental.ship_out_time.isoformat()
                if rental.ship_out_time is not None
                else None
            ),
            "ship_in_time": (
                rental.ship_in_time.isoformat()
                if rental.ship_in_time is not None
                else None
            ),
            "actual_shipped_at": (
                rental.actual_shipped_at.isoformat()
                if rental.actual_shipped_at is not None
                else None
            ),
            "actual_returned_at": (
                rental.actual_returned_at.isoformat()
                if rental.actual_returned_at is not None
                else None
            ),
            "refresh_scope": "current_window",
            "request_id": request_id,
        }

    @classmethod
    def delete(
        cls,
        *,
        tenant_session: Session,
        rental_id: int,
        request_id: str,
        actor_id: str,
    ) -> Mapping[str, object]:
        source_identity = tenant_session.execute(
            select(Rental.device_id, Rental.parent_rental_id).where(
                Rental.id == rental_id
            )
        ).one_or_none()
        if source_identity is None:
            raise RentalMutationNotFound()
        if source_identity.parent_rental_id is not None:
            raise RentalMutationInvalid()

        device = tenant_session.execute(
            select(Device)
            .where(Device.id == source_identity.device_id)
            .with_for_update()
        ).scalar_one_or_none()
        rental = tenant_session.execute(
            select(Rental)
            .where(
                Rental.id == rental_id,
                Rental.device_id == source_identity.device_id,
                Rental.parent_rental_id.is_(None),
            )
            .with_for_update()
        ).scalar_one_or_none()
        if device is None or rental is None:
            raise RentalMutationNotFound()

        children = tuple(
            tenant_session.execute(
                select(Rental)
                .where(Rental.parent_rental_id == rental.id)
                .order_by(Rental.id.asc())
                .with_for_update()
            ).scalars()
        )
        requests = tuple(
            tenant_session.execute(
                select(RentalAccessoryRequest)
                .where(RentalAccessoryRequest.rental_id == rental.id)
                .order_by(RentalAccessoryRequest.accessory_type_id.asc())
                .with_for_update()
            ).scalars()
        )
        links = tuple(
            tenant_session.execute(
                select(RentalAccessoryUnitLink)
                .where(RentalAccessoryUnitLink.rental_id == rental.id)
                .order_by(RentalAccessoryUnitLink.accessory_type_id.asc())
                .with_for_update()
            ).scalars()
        )
        relay_case_exists = tenant_session.scalar(
            select(RentalRelayCase.id)
            .where(
                (RentalRelayCase.predecessor_rental_id == rental.id)
                | (RentalRelayCase.successor_rental_id == rental.id)
            )
            .order_by(RentalRelayCase.id.asc())
            .limit(1)
            .with_for_update()
        )
        shipment_exists = tenant_session.scalar(
            select(OutboundShipment.id)
            .where(OutboundShipment.rental_id == rental.id)
            .order_by(OutboundShipment.id.asc())
            .limit(1)
            .with_for_update()
        )
        holder_exists = tenant_session.scalar(
            select(AccessoryUnit.id)
            .where(AccessoryUnit.current_holder_rental_id == rental.id)
            .limit(1)
            .with_for_update()
        )
        relay_or_travel_link = any(
            link.source_relay_case_id is not None
            or all(
                request.accessory_type_id != link.accessory_type_id
                for request in requests
            )
            for link in links
        )
        if (
            rental.status in {"shipped", "returned"}
            or relay_case_exists is not None
            or shipment_exists is not None
            or holder_exists is not None
            or relay_or_travel_link
        ):
            raise RentalDeletionBlocked()

        inventory = AccessoryInventoryService(tenant_session)
        for link in links:
            try:
                inventory.release_reservation(
                    rental_id=rental.id,
                    accessory_type_id=link.accessory_type_id,
                    reservation_start_at=link.reservation_start_at,
                    reservation_end_at=link.reservation_end_at,
                    actor_type="tenant_user",
                    actor_id=actor_id,
                    operation_key=request_id,
                )
            except AccessoryInventoryError as exc:
                raise RentalMutationError(data={"code": exc.code}) from None
        for accessory_request in requests:
            tenant_session.delete(accessory_request)
        for child in children:
            tenant_session.delete(child)
        tenant_session.delete(rental)
        tenant_session.flush()
        return {
            "id": rental_id,
            "deleted": True,
            "refresh_scope": "current_window",
            "request_id": request_id,
        }

    @staticmethod
    def _create_unfulfilled_request(
        tenant_session: Session,
        *,
        rental_id: int,
        device_id: int,
        accessory_type_id: int,
    ) -> None:
        accessory_type = tenant_session.execute(
            select(AccessoryType)
            .where(AccessoryType.id == accessory_type_id)
            .with_for_update()
        ).scalar_one_or_none()
        if (
            accessory_type is None
            or accessory_type.is_active is not True
            or accessory_type.tracking_mode != "logical_unit"
        ):
            raise RentalMutationInvalid()
        config = tenant_session.execute(
            select(DeviceAccessoryConfig)
            .where(
                DeviceAccessoryConfig.device_id == device_id,
                DeviceAccessoryConfig.accessory_type_id
                == accessory_type_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if config is None or config.enabled is not True:
            raise RentalMutationInvalid()
        tenant_session.add(RentalAccessoryRequest(
            rental_id=rental_id,
            accessory_type_id=accessory_type.id,
            name_snapshot=accessory_type.display_name,
        ))
        tenant_session.flush()


def _warehouse_summary(warehouse: Warehouse) -> dict[str, object]:
    return {
        "id": warehouse.id,
        "name": warehouse.name,
        "province": warehouse.province,
        "city": warehouse.city,
        "district": warehouse.district,
    }


def _positive_integer(value: object) -> int:
    if isinstance(value, bool):
        raise RentalMutationInvalid()
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise RentalMutationInvalid() from None
    if parsed < 1 or str(parsed) != str(value):
        raise RentalMutationInvalid()
    return parsed


def _required_text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise RentalMutationInvalid()
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise RentalMutationInvalid()
    return normalized


def _optional_text(value: object, *, maximum: int) -> str | None:
    if value in (None, ""):
        return None
    return _required_text(value, maximum=maximum)


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise RentalMutationInvalid()
    return value


def _optional_amount(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise RentalMutationInvalid()
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise RentalMutationInvalid() from None
    if (
        not amount.is_finite()
        or amount < 0
        or amount > Decimal("99999999.99")
        or amount.as_tuple().exponent < -2
    ):
        raise RentalMutationInvalid()
    return amount


__all__ = [
    "RentalAccessoryChainRecalculationRequired",
    "RentalAccessoryFulfillmentRequired",
    "RentalAccessoryInspectionRequired",
    "RentalAccessoryUnavailable",
    "RentalBookingMutationService",
    "RentalCreateInput",
    "RentalDeletionBlocked",
    "RentalStatusInput",
    "RentalStatusTransitionInvalid",
    "RentalUpdateInput",
    "RentalMutationError",
    "RentalMutationInvalid",
    "RentalMutationNotFound",
    "RentalOriginWarehouseChanged",
    "RentalUsagePeriodConflict",
    "parse_create_input",
    "parse_status_input",
    "parse_update_input",
]
