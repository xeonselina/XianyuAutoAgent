"""Projected inspection reads for one trusted tenant session."""

from __future__ import annotations

from datetime import date
from math import ceil

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.accessory_inventory import (
    AccessoryType,
    AccessoryUnit,
    RentalAccessoryRequest,
    RentalAccessoryUnitLink,
)
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.inspection_check_item import InspectionCheckItem
from app.models.inspection_record import InspectionRecord
from app.models.rental import Rental
from app.models.warehouse import UserWarehousePreference, Warehouse
from app.services.checklist_generator import ChecklistGenerator


def load_latest_context(
    tenant_session: Session,
    *,
    business_date: date,
    actor_id: str,
    device_id: int | None = None,
    device_name: str | None = None,
) -> dict[str, object] | None:
    predicates = [
        Rental.parent_rental_id.is_(None),
        Rental.status == "returned",
    ]
    if device_id is not None:
        predicates.append(Device.id == device_id)
    elif device_name is not None:
        predicates.append(Device.name == device_name)
    else:
        raise ValueError("one device selector is required")

    row = tenant_session.execute(
        select(Rental, Device, DeviceModel)
        .join(Device, Device.id == Rental.device_id)
        .outerjoin(DeviceModel, DeviceModel.id == Device.model_id)
        .where(*predicates)
        .order_by(
            func.coalesce(
                Rental.actual_returned_at,
                Rental.ship_in_time,
                Rental.updated_at,
            ).desc(),
            Rental.id.desc(),
        )
        .limit(1)
    ).one_or_none()
    if row is None:
        return None
    rental, device, device_model = row

    legacy_children = tenant_session.execute(
        select(Device.name)
        .select_from(Rental)
        .join(Device, Device.id == Rental.device_id)
        .where(Rental.parent_rental_id == rental.id)
        .order_by(Rental.id.asc())
    ).all()
    logical_rows = tenant_session.execute(
        select(
            AccessoryType.id.label("accessory_type_id"),
            AccessoryType.name.label("type_code"),
            AccessoryType.display_name,
            RentalAccessoryRequest.rental_id.label("request_rental_id"),
        )
        .select_from(RentalAccessoryUnitLink)
        .join(
            AccessoryUnit,
            AccessoryUnit.id == RentalAccessoryUnitLink.accessory_unit_id,
        )
        .join(
            AccessoryType,
            AccessoryType.id == RentalAccessoryUnitLink.accessory_type_id,
        )
        .outerjoin(
            RentalAccessoryRequest,
            (
                RentalAccessoryRequest.rental_id
                == RentalAccessoryUnitLink.rental_id
            )
            & (
                RentalAccessoryRequest.accessory_type_id
                == RentalAccessoryUnitLink.accessory_type_id
            ),
        )
        .where(
            RentalAccessoryUnitLink.rental_id == rental.id,
            AccessoryUnit.current_holder_rental_id == rental.id,
        )
        .order_by(AccessoryType.display_order.asc(), AccessoryType.id.asc())
    ).all()
    warehouses = tenant_session.execute(
        select(Warehouse)
        .where(
            Warehouse.status == "active",
            Warehouse.setup_state == "ready",
        )
        .order_by(Warehouse.is_default.desc(), Warehouse.id.asc())
    ).scalars().all()
    preference = tenant_session.execute(
        select(UserWarehousePreference.warehouse_id)
        .where(
            UserWarehousePreference.user_id == actor_id,
            UserWarehousePreference.scene == "inspection",
        )
    ).scalar_one_or_none()
    warehouse_ids = {warehouse.id for warehouse in warehouses}
    selected_warehouse_id = (
        preference if preference in warehouse_ids else None
    )
    if selected_warehouse_id is None and len(warehouses) == 1:
        selected_warehouse_id = warehouses[0].id
    if selected_warehouse_id is None:
        default = next((item for item in warehouses if item.is_default), None)
        selected_warehouse_id = default.id if default is not None else None

    accessory_names = [row.name for row in legacy_children]
    accessory_names.extend(row.display_name for row in logical_rows)
    rental_dto = _rental_dto(
        rental,
        device,
        device_model,
        accessory_names=accessory_names,
        business_date=business_date,
    )
    return {
        "rental": rental_dto,
        "checklist": _checklist(rental, accessory_names=accessory_names),
        "accessory_receipts": [
            {
                "accessory_type_id": row.accessory_type_id,
                "type_code": row.type_code,
                "display_name": row.display_name,
                "travels_with_device": row.request_rental_id is None,
                "outcome": "received_normal",
            }
            for row in logical_rows
        ],
        "warehouses": [_warehouse_dto(warehouse) for warehouse in warehouses],
        "selected_warehouse_id": selected_warehouse_id,
    }


def load_inspection(
    tenant_session: Session,
    *,
    inspection_id: int,
    business_date: date,
) -> dict[str, object] | None:
    row = tenant_session.execute(
        select(InspectionRecord, Rental, Device, DeviceModel)
        .join(Rental, Rental.id == InspectionRecord.rental_id)
        .join(Device, Device.id == InspectionRecord.device_id)
        .outerjoin(DeviceModel, DeviceModel.id == Device.model_id)
        .where(InspectionRecord.id == inspection_id)
    ).one_or_none()
    if row is None:
        return None
    record, rental, device, device_model = row
    checks = tenant_session.execute(
        select(InspectionCheckItem)
        .where(InspectionCheckItem.inspection_record_id == record.id)
        .order_by(
            InspectionCheckItem.item_order.asc(),
            InspectionCheckItem.id.asc(),
        )
    ).scalars().all()
    return _inspection_dto(
        record,
        rental,
        device,
        device_model,
        checks=checks,
        business_date=business_date,
    )


def list_inspections(
    tenant_session: Session,
    *,
    device_name: str | None,
    status: str | None,
    page: int,
    per_page: int,
    business_date: date,
) -> dict[str, object]:
    predicates = []
    if device_name:
        predicates.append(Device.name.contains(device_name, autoescape=True))
    if status:
        predicates.append(InspectionRecord.status == status)
    total = int(
        tenant_session.scalar(
            select(func.count(InspectionRecord.id))
            .select_from(InspectionRecord)
            .join(Device, Device.id == InspectionRecord.device_id)
            .where(*predicates)
        )
        or 0
    )
    rows = tenant_session.execute(
        select(InspectionRecord, Rental, Device, DeviceModel)
        .join(Rental, Rental.id == InspectionRecord.rental_id)
        .join(Device, Device.id == InspectionRecord.device_id)
        .outerjoin(DeviceModel, DeviceModel.id == Device.model_id)
        .where(*predicates)
        .order_by(InspectionRecord.created_at.desc(), InspectionRecord.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()
    record_ids = tuple(row[0].id for row in rows)
    checks_by_record: dict[int, list[InspectionCheckItem]] = {
        record_id: [] for record_id in record_ids
    }
    if record_ids:
        checks = tenant_session.execute(
            select(InspectionCheckItem)
            .where(InspectionCheckItem.inspection_record_id.in_(record_ids))
            .order_by(
                InspectionCheckItem.inspection_record_id.asc(),
                InspectionCheckItem.item_order.asc(),
                InspectionCheckItem.id.asc(),
            )
        ).scalars().all()
        for check in checks:
            checks_by_record[check.inspection_record_id].append(check)
    pages = ceil(total / per_page) if total else 0
    return {
        "records": [
            _inspection_dto(
                record,
                rental,
                device,
                device_model,
                checks=checks_by_record[record.id],
                business_date=business_date,
            )
            for record, rental, device, device_model in rows
        ],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": pages,
            "has_prev": page > 1,
            "has_next": page < pages,
        },
    }


def _inspection_dto(
    record,
    rental,
    device,
    device_model,
    *,
    checks,
    business_date: date,
) -> dict[str, object]:
    return {
        "id": record.id,
        "rental_id": record.rental_id,
        "device_id": record.device_id,
        "status": record.status,
        "inspector_user_id": record.inspector_user_id,
        "inspector_user_uuid": record.inspector_user_uuid,
        "warehouse_id": record.warehouse_id,
        "created_at": _iso(record.created_at),
        "updated_at": _iso(record.updated_at),
        "rental": _rental_dto(
            rental,
            device,
            device_model,
            accessory_names=(),
            business_date=business_date,
        ),
        "device": _device_dto(device, device_model),
        "check_items": [_check_dto(check) for check in checks],
    }


def _rental_dto(
    rental,
    device,
    device_model,
    *,
    accessory_names,
    business_date: date,
) -> dict[str, object]:
    return {
        "id": rental.id,
        "device_id": rental.device_id,
        "start_date": rental.start_date.isoformat(),
        "end_date": rental.end_date.isoformat(),
        "customer_name": rental.customer_name,
        "customer_phone": rental.customer_phone,
        "damage_note": rental.damage_note,
        "status": rental.status,
        "includes_handle": rental.includes_handle,
        "includes_lens_mount": rental.includes_lens_mount,
        "photo_transfer": rental.photo_transfer,
        "created_at": _iso(rental.created_at),
        "updated_at": _iso(rental.updated_at),
        "duration_days": (rental.end_date - rental.start_date).days + 1,
        "is_overdue": rental.end_date < business_date,
        "device": _device_dto(device, device_model),
        "device_info": _device_dto(device, device_model),
        "accessories": [
            {
                "name": name,
                "type": "other",
                "is_bundled": False,
            }
            for name in accessory_names
        ],
    }


def _device_dto(device, device_model) -> dict[str, object]:
    model = None
    if device_model is not None:
        model = {
            "id": device_model.id,
            "name": device_model.name,
            "display_name": device_model.display_name,
            "is_accessory": device_model.is_accessory,
        }
    return {
        "id": device.id,
        "name": device.name,
        "model": device.model,
        "model_id": device.model_id,
        "device_model": model,
        "warehouse_id": device.warehouse_id,
        "is_accessory": device.is_accessory,
    }


def _checklist(rental, *, accessory_names) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for item in ChecklistGenerator.BASE_ITEMS:
        items.append({"name": item["name"], "order": len(items) + 1})
    if rental.includes_handle:
        items.append({"name": "手柄", "order": len(items) + 1})
    if rental.includes_lens_mount:
        items.append({"name": "镜头支架", "order": len(items) + 1})
    if accessory_names:
        items.append(
            {
                "name": "附件：" + "、".join(accessory_names),
                "order": len(items) + 1,
            }
        )
    if rental.photo_transfer:
        items.append({"name": "代传照片", "order": len(items) + 1})
    if rental.damage_note:
        items.append(
            {
                "name": f"处理用户反馈：{rental.damage_note}",
                "order": len(items) + 1,
                "default_checked": False,
            }
        )
    return items


def _warehouse_dto(warehouse) -> dict[str, object]:
    return {
        "id": warehouse.id,
        "name": warehouse.name,
        "is_default": warehouse.is_default,
        "province": warehouse.province,
        "city": warehouse.city,
        "district": warehouse.district,
        "address_detail": warehouse.address_detail,
    }


def _check_dto(check) -> dict[str, object]:
    return {
        "id": check.id,
        "inspection_record_id": check.inspection_record_id,
        "item_name": check.item_name,
        "is_checked": check.is_checked,
        "item_order": check.item_order,
    }


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


__all__ = ["list_inspections", "load_inspection", "load_latest_context"]
