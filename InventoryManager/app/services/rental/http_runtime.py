"""Fail-closed SaaS HTTP runtime for migrated rental capabilities."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from flask import Request, current_app
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.models.rental import Rental
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.accessory_inventory import (
    AccessoryType,
    RentalAccessoryRequest,
    RentalAccessoryUnitLink,
)
from app.models.warehouse import UserWarehousePreference, Warehouse
from app.services.tenant_business import (
    TenantBusinessHttpRuntime,
    TenantBusinessRuntimeUnavailable,
)
from app.services.rental.availability_service import (
    RentalAvailabilityInput,
    RentalAvailabilityInvalid,
    RentalAvailabilityService,
    parse_availability_input,
)
from app.services.rental.mutation_service import (
    RentalBookingMutationService,
    RentalCreateInput,
    RentalMutationError,
    parse_create_input,
    parse_status_input,
    parse_update_input,
)
from inventory_control.domain.rbac import Capability


RENTAL_SAAS_HTTP_RUNTIME_EXTENSION = "inventory_rental_saas_http_runtime"


class RentalSaasHttpRuntimeUnavailable(RuntimeError):
    """No trusted Rental SaaS composition is available."""

    def __init__(self) -> None:
        super().__init__("RENTAL_SAAS_RUNTIME_UNAVAILABLE")


class RentalIdInvalid(ValueError):
    """A rental route parameter is not a supported local identifier."""

    def __init__(self) -> None:
        super().__init__("无效的租赁记录ID")


class RentalQueryInvalid(ValueError):
    """A rental list/search request has an invalid bounded query shape."""


@runtime_checkable
class RentalSaasHttpRuntime(Protocol):
    """Operations already migrated away from the global database session."""

    def get_rental(
        self,
        *,
        flask_request: Request,
        rental_id: object,
    ) -> Mapping[str, object] | None:
        ...

    def get_edit_context(
        self,
        *,
        flask_request: Request,
        rental_id: object,
    ) -> Mapping[str, object] | None:
        ...

    def list_rentals(
        self,
        *,
        flask_request: Request,
        filters: object,
    ) -> Mapping[str, object]:
        ...

    def list_pending_returns(
        self,
        *,
        flask_request: Request,
        pagination: object,
    ) -> Mapping[str, object]:
        ...

    def booking_bootstrap(
        self,
        *,
        flask_request: Request,
    ) -> Mapping[str, object]:
        ...

    def booking_availability(
        self,
        *,
        flask_request: Request,
        payload: object,
    ) -> Mapping[str, object]:
        ...

    def create_rental(
        self,
        *,
        flask_request: Request,
        payload: object,
    ) -> Mapping[str, object]:
        ...

    def update_rental(
        self,
        *,
        flask_request: Request,
        rental_id: object,
        payload: object,
    ) -> Mapping[str, object]:
        ...

    def update_rental_status(
        self,
        *,
        flask_request: Request,
        rental_id: object,
        payload: object,
    ) -> Mapping[str, object]:
        ...

    def delete_rental(
        self,
        *,
        flask_request: Request,
        rental_id: object,
    ) -> Mapping[str, object]:
        ...


class SqlAlchemyRentalSaasHttpRuntime:
    """Rental reads backed only by an authorized tenant request scope."""

    __slots__ = ("_tenant_business_runtime",)

    def __init__(
        self,
        *,
        tenant_business_runtime: TenantBusinessHttpRuntime,
    ) -> None:
        if not isinstance(
            tenant_business_runtime,
            TenantBusinessHttpRuntime,
        ):
            raise TypeError(
                "tenant_business_runtime must implement TenantBusinessHttpRuntime"
            )
        self._tenant_business_runtime = tenant_business_runtime

    def get_rental(
        self,
        *,
        flask_request: Request,
        rental_id: object,
    ) -> Mapping[str, object] | None:
        parsed_rental_id: int | None = None

        def parse_id_after_authorize(_auth_context) -> None:
            nonlocal parsed_rental_id
            parsed_rental_id = _parse_rental_id(rental_id)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.RENTAL_READ,
                additional_capabilities=(Capability.CUSTOMER_PII_READ,),
                request_id_prefix="rental-detail",
                after_authorize=parse_id_after_authorize,
                passthrough_exceptions=(RentalIdInvalid,),
            ) as scope:
                if parsed_rental_id is None:
                    raise RentalSaasHttpRuntimeUnavailable()
                business_date = scope.database_now.astimezone(
                    ZoneInfo(scope.auth_context.tenant_timezone)
                ).date()
                with scope.tenant_session.begin():
                    return _load_rental_detail(
                        scope.tenant_session,
                        rental_id=parsed_rental_id,
                        business_date=business_date,
                    )
        except RentalIdInvalid:
            raise
        except TenantBusinessRuntimeUnavailable:
            raise RentalSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise RentalSaasHttpRuntimeUnavailable() from None

    def get_edit_context(
        self,
        *,
        flask_request: Request,
        rental_id: object,
    ) -> Mapping[str, object] | None:
        """Return one authoritative rental and all non-inventory edit metadata."""

        parsed_rental_id: int | None = None

        def parse_id_after_authorize(_auth_context) -> None:
            nonlocal parsed_rental_id
            parsed_rental_id = _parse_rental_id(rental_id)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.RENTAL_READ,
                additional_capabilities=(
                    Capability.CUSTOMER_PII_READ,
                    Capability.INVENTORY_READ,
                    Capability.WAREHOUSE_READ,
                ),
                request_id_prefix="rental-edit-context",
                after_authorize=parse_id_after_authorize,
                passthrough_exceptions=(RentalIdInvalid,),
            ) as scope:
                if parsed_rental_id is None:
                    raise RentalSaasHttpRuntimeUnavailable()
                business_date = scope.database_now.astimezone(
                    ZoneInfo(scope.auth_context.tenant_timezone)
                ).date()
                with scope.tenant_session.begin():
                    rental = _load_rental_detail(
                        scope.tenant_session,
                        rental_id=parsed_rental_id,
                        business_date=business_date,
                    )
                    if rental is None:
                        return None
                    request_rows = scope.tenant_session.execute(
                        select(
                            RentalAccessoryRequest.accessory_type_id,
                            RentalAccessoryUnitLink.rental_id.label(
                                "fulfilled_rental_id"
                            ),
                        )
                        .outerjoin(
                            RentalAccessoryUnitLink,
                            and_(
                                RentalAccessoryUnitLink.rental_id
                                == RentalAccessoryRequest.rental_id,
                                RentalAccessoryUnitLink.accessory_type_id
                                == RentalAccessoryRequest.accessory_type_id,
                            ),
                        )
                        .where(
                            RentalAccessoryRequest.rental_id
                            == parsed_rental_id
                        )
                        .order_by(
                            RentalAccessoryRequest.accessory_type_id.asc()
                        )
                    ).all()
                    rental["requested_accessory_type_ids"] = [
                        row.accessory_type_id for row in request_rows
                    ]
                    rental["accessory_requests"] = [
                        {
                            "accessory_type_id": row.accessory_type_id,
                            "fulfilled": row.fulfilled_rental_id is not None,
                        }
                        for row in request_rows
                    ]
                    bootstrap = _load_booking_bootstrap(
                        scope.tenant_session,
                        user_id=scope.auth_context.user_id,
                        request_id=scope.request_id,
                        database_now=scope.database_now,
                    )
                    selected_device_ids = [int(rental["device_id"])]
                    selected_device_ids.extend(
                        int(accessory["id"])
                        for accessory in rental["accessories"]
                        if accessory.get("id") is not None
                    )
                    editing_inventory = _load_editing_inventory(
                        scope.tenant_session,
                        selected_device_ids=selected_device_ids,
                    )
                    return {
                        **bootstrap,
                        **editing_inventory,
                        "rental": rental,
                    }
        except RentalIdInvalid:
            raise
        except TenantBusinessRuntimeUnavailable:
            raise RentalSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise RentalSaasHttpRuntimeUnavailable() from None

    def list_rentals(
        self,
        *,
        flask_request: Request,
        filters: object,
    ) -> Mapping[str, object]:
        parsed_filters: dict[str, object] | None = None

        def parse_filters_after_authorize(_auth_context) -> None:
            nonlocal parsed_filters
            parsed_filters = _parse_list_filters(filters)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.RENTAL_READ,
                additional_capabilities=(Capability.CUSTOMER_PII_READ,),
                request_id_prefix="rental-list",
                after_authorize=parse_filters_after_authorize,
                passthrough_exceptions=(RentalQueryInvalid,),
            ) as scope:
                if parsed_filters is None:
                    raise RentalSaasHttpRuntimeUnavailable()
                predicates = _rental_list_predicates(parsed_filters)
                page = int(parsed_filters["page"])
                per_page = int(parsed_filters["per_page"])
                total = int(
                    scope.tenant_session.scalar(
                        select(func.count(Rental.id)).where(*predicates)
                    )
                    or 0
                )
                rows = scope.tenant_session.execute(
                    select(*_rental_summary_columns())
                    .join(Device, Device.id == Rental.device_id)
                    .outerjoin(DeviceModel, DeviceModel.id == Device.model_id)
                    .where(*predicates)
                    .order_by(Rental.id.desc())
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                ).all()
                pages = (total + per_page - 1) // per_page
                return {
                    "rentals": [_rental_summary_dto(row) for row in rows],
                    "total": total,
                    "pages": pages,
                    "current_page": page,
                    "per_page": per_page,
                    "has_next": page < pages,
                    "has_prev": page > 1,
                }
        except RentalQueryInvalid:
            raise
        except TenantBusinessRuntimeUnavailable:
            raise RentalSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise RentalSaasHttpRuntimeUnavailable() from None

    def list_pending_returns(
        self,
        *,
        flask_request: Request,
        pagination: object,
    ) -> Mapping[str, object]:
        parsed_pagination: tuple[int, int] | None = None

        def parse_pagination_after_authorize(_auth_context) -> None:
            nonlocal parsed_pagination
            parsed_pagination = _parse_pagination(pagination)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.RENTAL_READ,
                additional_capabilities=(Capability.CUSTOMER_PII_READ,),
                request_id_prefix="rental-pending-returns",
                after_authorize=parse_pagination_after_authorize,
                passthrough_exceptions=(RentalQueryInvalid,),
            ) as scope:
                if parsed_pagination is None:
                    raise RentalSaasHttpRuntimeUnavailable()
                page, per_page = parsed_pagination
                business_date = scope.database_now.astimezone(
                    ZoneInfo(scope.auth_context.tenant_timezone)
                ).date()
                latest_end_date = business_date - timedelta(days=1)
                predicates = (
                    Rental.end_date <= latest_end_date,
                    Rental.status == "shipped",
                    Rental.parent_rental_id.is_(None),
                )
                total = int(
                    scope.tenant_session.scalar(
                        select(func.count(Rental.id)).where(*predicates)
                    )
                    or 0
                )
                rows = scope.tenant_session.execute(
                    select(
                        Rental.id,
                        Rental.start_date,
                        Rental.end_date,
                        Rental.destination,
                        Rental.customer_phone,
                        Rental.status,
                        Device.name.label("device_name"),
                        Device.model.label("device_model_key"),
                        DeviceModel.display_name.label(
                            "device_model_display_name"
                        ),
                    )
                    .join(Device, Device.id == Rental.device_id)
                    .outerjoin(DeviceModel, DeviceModel.id == Device.model_id)
                    .where(*predicates)
                    .order_by(Rental.end_date.asc(), Rental.id.asc())
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                ).all()
                pages = (total + per_page - 1) // per_page
                rentals = []
                for row in rows:
                    due_date = row.end_date + timedelta(days=1)
                    rentals.append({
                        "id": row.id,
                        "device_model": (
                            row.device_model_display_name
                            or row.device_model_key
                            or row.device_name
                            or "-"
                        ),
                        "start_date": row.start_date.isoformat(),
                        "end_date": row.end_date.isoformat(),
                        "due_date": due_date.isoformat(),
                        "overdue_days": (business_date - due_date).days,
                        "destination": row.destination,
                        "customer_phone": row.customer_phone,
                        "status": row.status,
                    })
                return {
                    "rentals": rentals,
                    "count": len(rentals),
                    "total": total,
                    "pages": pages,
                    "current_page": page,
                    "per_page": per_page,
                    "has_next": page < pages,
                    "has_prev": page > 1,
                    "as_of_date": business_date.isoformat(),
                }
        except RentalQueryInvalid:
            raise
        except TenantBusinessRuntimeUnavailable:
            raise RentalSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise RentalSaasHttpRuntimeUnavailable() from None

    def booking_bootstrap(
        self,
        *,
        flask_request: Request,
    ) -> Mapping[str, object]:
        """Return form metadata only; no device availability is cached here."""

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.RENTAL_READ,
                additional_capabilities=(
                    Capability.INVENTORY_READ,
                    Capability.WAREHOUSE_READ,
                ),
                request_id_prefix="rental-booking-bootstrap",
            ) as scope:
                with scope.tenant_session.begin():
                    return _load_booking_bootstrap(
                        scope.tenant_session,
                        user_id=scope.auth_context.user_id,
                        request_id=scope.request_id,
                        database_now=scope.database_now,
                    )
        except TenantBusinessRuntimeUnavailable:
            raise RentalSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise RentalSaasHttpRuntimeUnavailable() from None

    def booking_availability(
        self,
        *,
        flask_request: Request,
        payload: object,
    ) -> Mapping[str, object]:
        parsed_input: RentalAvailabilityInput | None = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed_input
            parsed_input = parse_availability_input(payload)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.RENTAL_READ,
                additional_capabilities=(
                    Capability.INVENTORY_READ,
                    Capability.WAREHOUSE_READ,
                ),
                request_id_prefix="rental-booking-availability",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(RentalAvailabilityInvalid,),
            ) as scope:
                if parsed_input is None:
                    raise RentalSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    return RentalAvailabilityService.evaluate(
                        tenant_session=scope.tenant_session,
                        request=parsed_input,
                        tenant_timezone=scope.auth_context.tenant_timezone,
                        database_now=scope.database_now,
                        request_id=scope.request_id,
                    )
        except RentalAvailabilityInvalid:
            raise
        except TenantBusinessRuntimeUnavailable:
            raise RentalSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise RentalSaasHttpRuntimeUnavailable() from None

    def create_rental(
        self,
        *,
        flask_request: Request,
        payload: object,
    ) -> Mapping[str, object]:
        """Create in one routed tenant transaction after final revalidation."""

        parsed_input: RentalCreateInput | None = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed_input
            parsed_input = parse_create_input(payload)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.RENTAL_WRITE,
                additional_capabilities=(
                    Capability.CUSTOMER_PII_READ,
                    Capability.INVENTORY_READ,
                    Capability.WAREHOUSE_READ,
                ),
                request_id_prefix="rental-create",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(RentalMutationError,),
            ) as scope:
                if parsed_input is None:
                    raise RentalSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    return RentalBookingMutationService.create(
                        tenant_session=scope.tenant_session,
                        request=parsed_input,
                        tenant_timezone=scope.auth_context.tenant_timezone,
                        database_now=scope.database_now,
                        request_id=scope.request_id,
                        actor_id=scope.auth_context.user_id,
                    )
        except RentalMutationError:
            raise
        except TenantBusinessRuntimeUnavailable:
            raise RentalSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise RentalSaasHttpRuntimeUnavailable() from None

    def update_rental(
        self,
        *,
        flask_request: Request,
        rental_id: object,
        payload: object,
    ) -> Mapping[str, object]:
        """Update in one routed tenant transaction after final revalidation."""

        parsed_rental_id: int | None = None
        parsed_input = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed_rental_id, parsed_input
            parsed_rental_id = _parse_rental_id(rental_id)
            parsed_input = parse_update_input(payload)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.RENTAL_WRITE,
                additional_capabilities=(
                    Capability.CUSTOMER_PII_READ,
                    Capability.INVENTORY_READ,
                    Capability.WAREHOUSE_READ,
                ),
                request_id_prefix="rental-update",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(
                    RentalIdInvalid,
                    RentalMutationError,
                ),
            ) as scope:
                if parsed_rental_id is None or parsed_input is None:
                    raise RentalSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    return RentalBookingMutationService.update(
                        tenant_session=scope.tenant_session,
                        rental_id=parsed_rental_id,
                        request=parsed_input,
                        tenant_timezone=scope.auth_context.tenant_timezone,
                        database_now=scope.database_now,
                        request_id=scope.request_id,
                        actor_id=scope.auth_context.user_id,
                    )
        except (RentalIdInvalid, RentalMutationError):
            raise
        except TenantBusinessRuntimeUnavailable:
            raise RentalSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise RentalSaasHttpRuntimeUnavailable() from None

    def update_rental_status(
        self,
        *,
        flask_request: Request,
        rental_id: object,
        payload: object,
    ) -> Mapping[str, object]:
        """Apply one tenant-local status transition and inventory effects."""

        parsed_rental_id: int | None = None
        parsed_input = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed_rental_id, parsed_input
            parsed_rental_id = _parse_rental_id(rental_id)
            parsed_input = parse_status_input(payload)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.RENTAL_WRITE,
                additional_capabilities=(Capability.INVENTORY_READ,),
                request_id_prefix="rental-status",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(
                    RentalIdInvalid,
                    RentalMutationError,
                ),
            ) as scope:
                if parsed_rental_id is None or parsed_input is None:
                    raise RentalSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    return RentalBookingMutationService.update_status(
                        tenant_session=scope.tenant_session,
                        rental_id=parsed_rental_id,
                        request=parsed_input,
                        database_now=scope.database_now,
                        request_id=scope.request_id,
                        actor_id=scope.auth_context.user_id,
                    )
        except (RentalIdInvalid, RentalMutationError):
            raise
        except TenantBusinessRuntimeUnavailable:
            raise RentalSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise RentalSaasHttpRuntimeUnavailable() from None

    def delete_rental(
        self,
        *,
        flask_request: Request,
        rental_id: object,
    ) -> Mapping[str, object]:
        """Delete a safe tenant-local rental and release ordinary links."""

        parsed_rental_id: int | None = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed_rental_id
            parsed_rental_id = _parse_rental_id(rental_id)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.RENTAL_WRITE,
                additional_capabilities=(Capability.INVENTORY_READ,),
                request_id_prefix="rental-delete",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(
                    RentalIdInvalid,
                    RentalMutationError,
                ),
            ) as scope:
                if parsed_rental_id is None:
                    raise RentalSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    return RentalBookingMutationService.delete(
                        tenant_session=scope.tenant_session,
                        rental_id=parsed_rental_id,
                        request_id=scope.request_id,
                        actor_id=scope.auth_context.user_id,
                    )
        except (RentalIdInvalid, RentalMutationError):
            raise
        except TenantBusinessRuntimeUnavailable:
            raise RentalSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise RentalSaasHttpRuntimeUnavailable() from None

    def __repr__(self) -> str:
        return "SqlAlchemyRentalSaasHttpRuntime(fail_closed=True)"


def require_rental_saas_http_runtime() -> RentalSaasHttpRuntime:
    """Return only an explicitly installed, protocol-complete runtime."""

    runtime = current_app.extensions.get(
        RENTAL_SAAS_HTTP_RUNTIME_EXTENSION
    )
    if not isinstance(runtime, RentalSaasHttpRuntime):
        raise RentalSaasHttpRuntimeUnavailable()
    return runtime


def _parse_rental_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise RentalIdInvalid()
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise RentalIdInvalid() from None
    if parsed < 1 or str(parsed) != str(value):
        raise RentalIdInvalid()
    return parsed


def _load_rental_detail(
    tenant_session: Session,
    *,
    rental_id: int,
    business_date,
) -> dict[str, object] | None:
    row = tenant_session.execute(
        select(*_rental_detail_columns())
        .join(Device, Device.id == Rental.device_id)
        .outerjoin(DeviceModel, DeviceModel.id == Device.model_id)
        .where(Rental.id == rental_id)
    ).one_or_none()
    if row is None:
        return None
    child_rows = tenant_session.execute(
        select(*_rental_detail_columns())
        .join(Device, Device.id == Rental.device_id)
        .outerjoin(DeviceModel, DeviceModel.id == Device.model_id)
        .where(Rental.parent_rental_id == rental_id)
        .order_by(Rental.id.asc())
    ).all()
    return _rental_detail_dto(
        row,
        child_rows=child_rows,
        business_date=business_date,
    )


def _load_booking_bootstrap(
    tenant_session: Session,
    *,
    user_id: str,
    request_id: str,
    database_now: datetime,
) -> dict[str, object]:
    warehouse_rows = tenant_session.execute(
        select(
            Warehouse.id,
            Warehouse.warehouse_uuid,
            Warehouse.name,
            Warehouse.is_default,
            Warehouse.province,
            Warehouse.city,
            Warehouse.district,
            UserWarehousePreference.warehouse_id.label(
                "recent_warehouse_id"
            ),
        )
        .outerjoin(
            UserWarehousePreference,
            and_(
                UserWarehousePreference.warehouse_id == Warehouse.id,
                UserWarehousePreference.user_id == user_id,
                UserWarehousePreference.scene == "booking",
            ),
        )
        .where(
            Warehouse.status == "active",
            Warehouse.setup_state == "ready",
        )
        .order_by(
            Warehouse.is_default.desc(),
            Warehouse.id.asc(),
        )
    ).all()
    model_rows = tenant_session.execute(
        select(
            DeviceModel.id,
            DeviceModel.name,
            DeviceModel.display_name,
            DeviceModel.description,
        )
        .where(
            DeviceModel.is_active.is_(True),
            DeviceModel.is_accessory.is_(False),
        )
        .order_by(
            DeviceModel.display_name.asc(),
            DeviceModel.id.asc(),
        )
    ).all()
    accessory_rows = tenant_session.execute(
        select(
            AccessoryType.id,
            AccessoryType.name,
            AccessoryType.display_name,
            AccessoryType.tracking_mode,
            AccessoryType.display_order,
        )
        .where(AccessoryType.is_active.is_(True))
        .order_by(
            AccessoryType.display_order.asc(),
            AccessoryType.id.asc(),
        )
    ).all()

    recent_warehouse_id = next(
        (
            row.recent_warehouse_id
            for row in warehouse_rows
            if row.recent_warehouse_id is not None
        ),
        None,
    )
    default_warehouse_id = next(
        (row.id for row in warehouse_rows if row.is_default),
        None,
    )
    return {
        "request_id": request_id,
        "evaluated_at": _utc_isoformat(database_now),
        "warehouses": [
            {
                "id": row.id,
                "warehouse_uuid": row.warehouse_uuid,
                "name": row.name,
                "is_default": row.is_default,
                "province": row.province,
                "city": row.city,
                "district": row.district,
                "address_summary": "".join(
                    part
                    for part in (
                        row.province,
                        row.city,
                        row.district,
                    )
                    if part
                ),
            }
            for row in warehouse_rows
        ],
        "recent_warehouse_id": recent_warehouse_id,
        "default_warehouse_id": default_warehouse_id,
        "device_models": [
            {
                "id": row.id,
                "name": row.name,
                "display_name": row.display_name,
                "description": row.description,
            }
            for row in model_rows
        ],
        "accessory_types": [
            {
                "id": row.id,
                "name": row.name,
                "display_name": row.display_name,
                "tracking_mode": row.tracking_mode,
                "display_order": row.display_order,
            }
            for row in accessory_rows
        ],
        "form_policy": {
            "minimum_logistics_days": 0,
            "maximum_logistics_days": 7,
            "operational_buffer_days": 1,
            "lens_combo_codes": [
                "lens_400mm",
                "lens_200mm",
                "bare",
                "lens_dual",
            ],
        },
    }


def _load_editing_inventory(
    tenant_session: Session,
    *,
    selected_device_ids: list[int],
) -> dict[str, list[dict[str, object]]]:
    """Project active edit choices without ORM traversal or logical-unit IDs."""

    rows = tenant_session.execute(
        select(*_editing_device_columns())
        .outerjoin(DeviceModel, DeviceModel.id == Device.model_id)
        .where(or_(
            Device.lifecycle_status == "active",
            Device.id.in_(selected_device_ids),
        ))
        .order_by(
            Device.is_accessory.asc(),
            Device.model_id.asc(),
            Device.id.asc(),
        )
    ).all()
    devices: list[dict[str, object]] = []
    legacy_accessories: list[dict[str, object]] = []
    for row in rows:
        item = _device_dto(row)
        if row.device_is_accessory:
            legacy_accessories.append(item)
        else:
            devices.append(item)
    return {
        "devices": devices,
        "legacy_device_bound_accessories": legacy_accessories,
    }


_VALID_RENTAL_STATUSES = frozenset({
    "not_shipped",
    "scheduled_for_shipping",
    "shipped",
    "returned",
    "completed",
    "cancelled",
})


def _parse_list_filters(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise RentalQueryInvalid("查询条件格式错误")

    page = _bounded_integer(value.get("page", 1), name="page", maximum=1_000_000)
    per_page = _bounded_integer(
        value.get("per_page", 20),
        name="per_page",
        maximum=100,
    )
    device_id_raw = value.get("device_id")
    device_id = (
        None
        if device_id_raw in (None, "")
        else _bounded_integer(
            device_id_raw,
            name="device_id",
            maximum=2_147_483_647,
        )
    )
    status = _optional_text(value.get("status"), name="status", maximum=32)
    if status is not None and status not in _VALID_RENTAL_STATUSES:
        raise RentalQueryInvalid("status 无效")

    start_raw = value.get("start_date")
    end_raw = value.get("end_date")
    if bool(start_raw) != bool(end_raw):
        raise RentalQueryInvalid("start_date 和 end_date 必须同时提供")
    start_date = end_date = None
    if start_raw and end_raw:
        try:
            start_date = datetime.strptime(
                str(start_raw), "%Y-%m-%d"
            ).date()
            end_date = datetime.strptime(str(end_raw), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            raise RentalQueryInvalid("日期格式错误，请使用YYYY-MM-DD格式") from None
        if end_date < start_date:
            raise RentalQueryInvalid("结束日期不能早于开始日期")

    return {
        "page": page,
        "per_page": per_page,
        "device_id": device_id,
        "status": status,
        "start_date": start_date,
        "end_date": end_date,
        "q": _optional_text(value.get("q"), name="q", maximum=100),
        "customer_name": _optional_text(
            value.get("customer_name"),
            name="customer_name",
            maximum=100,
        ),
        "phone": _optional_text(
            value.get("phone"),
            name="phone",
            maximum=32,
        ),
        "destination": _optional_text(
            value.get("destination"),
            name="destination",
            maximum=255,
        ),
    }


def _parse_pagination(value: object) -> tuple[int, int]:
    if not isinstance(value, Mapping):
        raise RentalQueryInvalid("分页条件格式错误")
    return (
        _bounded_integer(value.get("page", 1), name="page", maximum=1_000_000),
        _bounded_integer(value.get("per_page", 50), name="per_page", maximum=100),
    )


def _bounded_integer(value: object, *, name: str, maximum: int) -> int:
    if isinstance(value, bool):
        raise RentalQueryInvalid(f"{name} 必须是正整数")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise RentalQueryInvalid(f"{name} 必须是正整数") from None
    if parsed < 1 or parsed > maximum or str(parsed) != str(value):
        raise RentalQueryInvalid(f"{name} 必须是正整数")
    return parsed


def _optional_text(
    value: object,
    *,
    name: str,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RentalQueryInvalid(f"{name} 格式错误")
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > maximum or "\x00" in normalized:
        raise RentalQueryInvalid(f"{name} 超出允许长度")
    return normalized


def _rental_list_predicates(filters: Mapping[str, object]) -> list[object]:
    predicates: list[object] = []
    if filters["device_id"] is not None:
        predicates.append(Rental.device_id == filters["device_id"])
    if filters["status"] is not None:
        predicates.append(Rental.status == filters["status"])
    if filters["start_date"] is not None:
        predicates.extend((
            Rental.start_date >= filters["start_date"],
            Rental.end_date <= filters["end_date"],
        ))

    query = filters["q"]
    if query is not None:
        predicates.append(or_(
            Rental.customer_name.contains(query, autoescape=True),
            Rental.customer_phone.contains(query, autoescape=True),
            Rental.destination.contains(query, autoescape=True),
        ))
    else:
        if filters["customer_name"] is not None:
            predicates.append(
                Rental.customer_name.contains(
                    filters["customer_name"],
                    autoescape=True,
                )
            )
        if filters["phone"] is not None:
            predicates.append(
                Rental.customer_phone.contains(
                    filters["phone"],
                    autoescape=True,
                )
            )
        if filters["destination"] is not None:
            predicates.append(
                Rental.destination.contains(
                    filters["destination"],
                    autoescape=True,
                )
            )
    return predicates


def _rental_summary_columns() -> tuple[object, ...]:
    """Return the fixed projected list/search contract without relationships."""

    return (
        Rental.id,
        Rental.device_id,
        Rental.start_date,
        Rental.end_date,
        Rental.ship_out_time,
        Rental.ship_in_time,
        Rental.customer_name,
        Rental.customer_phone,
        Rental.destination,
        Rental.xianyu_order_no,
        Rental.order_amount,
        Rental.damage_note,
        Rental.ship_out_tracking_no,
        Rental.ship_in_tracking_no,
        Rental.scheduled_ship_time,
        Rental.express_type_id,
        Rental.preferred_warehouse_id,
        Rental.logistics_days,
        Rental.planned_ship_out_date,
        Rental.planned_return_date,
        Rental.actual_shipped_at,
        Rental.actual_returned_at,
        Rental.status,
        Rental.parent_rental_id,
        Rental.includes_handle,
        Rental.includes_lens_mount,
        Rental.photo_transfer,
        Rental.lens_combo,
        Rental.created_at,
        Rental.updated_at,
        Device.name.label("device_name"),
        Device.serial_number.label("device_serial_number"),
        Device.model.label("device_model_key"),
        Device.model_id.label("device_model_id"),
        Device.warehouse_id.label("device_warehouse_id"),
        Device.is_accessory.label("device_is_accessory"),
        Device.lifecycle_status.label("device_lifecycle_status"),
        Device.lifecycle_reason.label("device_lifecycle_reason"),
        Device.lifecycle_date.label("device_lifecycle_date"),
        Device.created_at.label("device_created_at"),
        Device.updated_at.label("device_updated_at"),
        DeviceModel.name.label("device_model_name"),
        DeviceModel.display_name.label("device_model_display_name"),
        DeviceModel.is_accessory.label("device_model_is_accessory"),
        DeviceModel.device_value.label("device_model_value"),
    )


def _editing_device_columns() -> tuple[object, ...]:
    return (
        Device.id.label("device_id"),
        Device.name.label("device_name"),
        Device.serial_number.label("device_serial_number"),
        Device.model.label("device_model_key"),
        Device.model_id.label("device_model_id"),
        Device.warehouse_id.label("device_warehouse_id"),
        Device.is_accessory.label("device_is_accessory"),
        Device.lifecycle_status.label("device_lifecycle_status"),
        Device.lifecycle_reason.label("device_lifecycle_reason"),
        Device.lifecycle_date.label("device_lifecycle_date"),
        Device.created_at.label("device_created_at"),
        Device.updated_at.label("device_updated_at"),
        DeviceModel.name.label("device_model_name"),
        DeviceModel.display_name.label("device_model_display_name"),
        DeviceModel.is_accessory.label("device_model_is_accessory"),
        DeviceModel.device_value.label("device_model_value"),
    )


def _device_dto(row) -> dict[str, object]:
    device_model = None
    if row.device_model_id is not None:
        device_model = {
            "id": row.device_model_id,
            "name": row.device_model_name,
            "display_name": row.device_model_display_name,
            "is_accessory": row.device_model_is_accessory,
            "device_value": (
                float(row.device_model_value)
                if row.device_model_value is not None
                else None
            ),
        }
    return {
        "id": row.device_id,
        "name": row.device_name,
        "serial_number": row.device_serial_number,
        "model": row.device_model_key,
        "model_id": row.device_model_id,
        "device_model": device_model,
        "is_accessory": row.device_is_accessory,
        "warehouse_id": row.device_warehouse_id,
        "lifecycle_status": row.device_lifecycle_status,
        "lifecycle_reason": row.device_lifecycle_reason,
        "lifecycle_date": _optional_isoformat(row.device_lifecycle_date),
        "created_at": _optional_isoformat(row.device_created_at),
        "updated_at": _optional_isoformat(row.device_updated_at),
    }


def _rental_summary_dto(row) -> dict[str, object]:
    device = _device_dto(row)
    return {
        "id": row.id,
        "device_id": row.device_id,
        "device": device,
        "device_info": device,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "ship_out_time": _optional_isoformat(row.ship_out_time),
        "ship_in_time": _optional_isoformat(row.ship_in_time),
        "customer_name": row.customer_name,
        "customer_phone": row.customer_phone,
        "destination": row.destination,
        "xianyu_order_no": row.xianyu_order_no,
        "order_amount": (
            float(row.order_amount) if row.order_amount is not None else None
        ),
        "damage_note": row.damage_note,
        "ship_out_tracking_no": row.ship_out_tracking_no,
        "ship_in_tracking_no": row.ship_in_tracking_no,
        "scheduled_ship_time": _optional_isoformat(row.scheduled_ship_time),
        "express_type_id": row.express_type_id,
        "preferred_warehouse_id": row.preferred_warehouse_id,
        "logistics_days": row.logistics_days,
        "planned_ship_out_date": _optional_isoformat(
            row.planned_ship_out_date
        ),
        "planned_return_date": _optional_isoformat(row.planned_return_date),
        "actual_shipped_at": _optional_isoformat(row.actual_shipped_at),
        "actual_returned_at": _optional_isoformat(row.actual_returned_at),
        "status": row.status,
        "parent_rental_id": row.parent_rental_id,
        "includes_handle": row.includes_handle,
        "includes_lens_mount": row.includes_lens_mount,
        "photo_transfer": row.photo_transfer,
        "lens_combo": row.lens_combo,
        "created_at": _optional_isoformat(row.created_at),
        "updated_at": _optional_isoformat(row.updated_at),
        "duration_days": (row.end_date - row.start_date).days + 1,
    }


def _optional_isoformat(value: object) -> str | None:
    return value.isoformat() if value is not None else None


def _utc_isoformat(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _rental_detail_columns() -> tuple[object, ...]:
    return _rental_summary_columns() + (
        Rental.customer_note,
        Rental.customer_province,
        Rental.customer_city,
        Rental.customer_district,
        Rental.customer_address_detail,
        Rental.buyer_id,
        Rental.logistics_estimate_origin_warehouse_id,
        Rental.logistics_estimate_provider,
        Rental.logistics_estimate_provider_version,
        Rental.logistics_estimate_rule_version,
        Rental.logistics_estimate_days,
        Rental.logistics_estimate_evaluated_at,
        Rental.logistics_estimate_address_digest,
        Rental.logistics_estimate_address_summary,
    )


def _rental_detail_dto(
    row,
    *,
    child_rows,
    business_date,
) -> dict[str, object]:
    result = _rental_summary_dto(row)
    result.update({
        "customer_note": row.customer_note,
        "customer_province": row.customer_province,
        "customer_city": row.customer_city,
        "customer_district": row.customer_district,
        "customer_address_detail": row.customer_address_detail,
        "buyer_id": row.buyer_id,
        "logistics_estimate_origin_warehouse_id": (
            row.logistics_estimate_origin_warehouse_id
        ),
        "logistics_estimate_provider": row.logistics_estimate_provider,
        "logistics_estimate_provider_version": (
            row.logistics_estimate_provider_version
        ),
        "logistics_estimate_rule_version": (
            row.logistics_estimate_rule_version
        ),
        "logistics_estimate_days": row.logistics_estimate_days,
        "logistics_estimate_evaluated_at": _optional_isoformat(
            row.logistics_estimate_evaluated_at
        ),
        "logistics_estimate_address_digest": (
            row.logistics_estimate_address_digest
        ),
        "logistics_estimate_address_summary": (
            row.logistics_estimate_address_summary
        ),
        "is_overdue": (
            row.status == "shipped" and business_date > row.end_date
        ),
    })

    child_dtos = []
    accessories = []
    for child in child_rows:
        child_dto = _rental_summary_dto(child)
        child_dto.update({
            "customer_note": child.customer_note,
            "customer_province": child.customer_province,
            "customer_city": child.customer_city,
            "customer_district": child.customer_district,
            "customer_address_detail": child.customer_address_detail,
            "buyer_id": child.buyer_id,
            "is_overdue": (
                child.status == "shipped"
                and business_date > child.end_date
            ),
            "accessories": [],
            "child_rentals": [],
        })
        child_dtos.append(child_dto)
        accessories.append({
            "id": child.device_id,
            "name": child.device_name,
            "model": (
                child.device_model_name
                or child.device_model_key
            ),
            "is_accessory": child.device_is_accessory,
            "value": (
                float(child.device_model_value)
                if child.device_model_value is not None
                else None
            ),
        })
    result["accessories"] = accessories
    result["child_rentals"] = child_dtos
    return result


__all__ = [
    "RENTAL_SAAS_HTTP_RUNTIME_EXTENSION",
    "RentalIdInvalid",
    "RentalAvailabilityInvalid",
    "RentalQueryInvalid",
    "RentalSaasHttpRuntime",
    "RentalSaasHttpRuntimeUnavailable",
    "SqlAlchemyRentalSaasHttpRuntime",
    "require_rental_saas_http_runtime",
]
