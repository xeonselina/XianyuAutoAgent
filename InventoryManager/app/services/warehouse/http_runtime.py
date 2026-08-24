"""Fail-closed SaaS HTTP runtime for warehouse and device-move operations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from flask import Request, current_app
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select

from app.models.device import Device
from app.models.device_model import DeviceModel
from app.services.tenant_business import (
    TenantBusinessHttpRuntime,
    TenantBusinessRuntimeUnavailable,
)
from app.services.warehouse_service import (
    AccessoryMoveReassignmentUnsupportedError,
    DefaultWarehouseProtectedError,
    DeviceModelNotFoundError,
    DeviceNotFoundError,
    DeviceSerialNumberConflictError,
    MoveConfirmationRequiredError,
    SameWarehouseMoveError,
    StaleDeviceWarehouseError,
    UnsupportedDeviceMoveError,
    WarehouseNotFoundError,
    WarehouseInventoryPresentError,
    WarehousePersistenceError,
    WarehouseService,
    WarehouseServiceError,
    WarehouseUnavailableError,
)
from inventory_control.domain.rbac import Capability


WAREHOUSE_SAAS_HTTP_RUNTIME_EXTENSION = "inventory_warehouse_saas_http_runtime"


class WarehouseSaasHttpRuntimeUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("WAREHOUSE_SAAS_RUNTIME_UNAVAILABLE")


class WarehouseRequestInvalid(ValueError):
    code = "WAREHOUSE_REQUEST_INVALID"
    public_message = "仓库请求参数无效"
    status_code = 400

    def __init__(self) -> None:
        super().__init__(self.public_message)


class WarehouseMutationError(RuntimeError):
    code = "WAREHOUSE_OPERATION_REJECTED"
    public_message = "仓库操作未能完成"
    status_code = 409

    def __init__(self, source: WarehouseServiceError) -> None:
        error_type = type(source)
        self.code, self.public_message, self.status_code = _ERROR_MAP.get(
            error_type,
            (self.code, self.public_message, self.status_code),
        )
        super().__init__(self.public_message)


_ERROR_MAP: dict[type[WarehouseServiceError], tuple[str, str, int]] = {
    DeviceNotFoundError: ("DEVICE_NOT_FOUND", "设备不存在", 404),
    DeviceModelNotFoundError: (
        "DEVICE_MODEL_NOT_FOUND",
        "设备型号不存在或不可用",
        404,
    ),
    DeviceSerialNumberConflictError: (
        "DEVICE_SERIAL_NUMBER_CONFLICT",
        "设备序列号已存在",
        409,
    ),
    WarehouseNotFoundError: ("WAREHOUSE_NOT_FOUND", "仓库不存在", 404),
    WarehouseUnavailableError: (
        "WAREHOUSE_UNAVAILABLE",
        "目标仓库当前不可用",
        409,
    ),
    StaleDeviceWarehouseError: (
        "WAREHOUSE_MOVE_PREVIEW_STALE",
        "设备或受影响订单已变化，请重新预览",
        409,
    ),
    SameWarehouseMoveError: (
        "DEVICE_ALREADY_IN_WAREHOUSE",
        "设备已经位于目标仓库",
        409,
    ),
    MoveConfirmationRequiredError: (
        "WAREHOUSE_MOVE_CONFIRMATION_REQUIRED",
        "请先预览并确认调仓影响",
        400,
    ),
    UnsupportedDeviceMoveError: (
        "WAREHOUSE_MOVE_DEVICE_UNSUPPORTED",
        "只有主设备可以使用调仓流程",
        409,
    ),
    AccessoryMoveReassignmentUnsupportedError: (
        "ACCESSORY_CHAIN_RECALCULATION_REQUIRED",
        "附件接力链需要先处理后再调仓",
        409,
    ),
    DefaultWarehouseProtectedError: (
        "DEFAULT_WAREHOUSE_PROTECTED",
        "请先将另一个可用仓库设为默认仓库",
        409,
    ),
    WarehouseInventoryPresentError: (
        "WAREHOUSE_INVENTORY_PRESENT",
        "请先迁出当前可用设备和附件库存",
        409,
    ),
}


@runtime_checkable
class WarehouseSaasHttpRuntime(Protocol):
    def get_default_setup(
        self,
        *,
        flask_request: Request,
    ) -> Mapping[str, object]: ...

    def setup_default_warehouse(
        self,
        *,
        flask_request: Request,
        payload: object,
    ) -> Mapping[str, object]: ...

    def list_warehouses(
        self,
        *,
        flask_request: Request,
    ) -> tuple[Mapping[str, object], ...]: ...

    def create_warehouse(
        self,
        *,
        flask_request: Request,
        payload: object,
    ) -> Mapping[str, object]: ...

    def update_warehouse(
        self,
        *,
        flask_request: Request,
        warehouse_id: object,
        payload: object,
    ) -> Mapping[str, object]: ...

    def set_default_warehouse(
        self,
        *,
        flask_request: Request,
        warehouse_id: object,
    ) -> Mapping[str, object]: ...

    def deactivate_warehouse(
        self,
        *,
        flask_request: Request,
        warehouse_id: object,
    ) -> Mapping[str, object]: ...

    def set_user_preference(
        self,
        *,
        flask_request: Request,
        scene: object,
        payload: object,
    ) -> Mapping[str, object]: ...

    def get_user_preferences(
        self,
        *,
        flask_request: Request,
    ) -> Mapping[str, object]: ...

    def list_main_devices(
        self,
        *,
        flask_request: Request,
    ) -> tuple[Mapping[str, object], ...]: ...

    def list_main_device_models(
        self,
        *,
        flask_request: Request,
    ) -> tuple[Mapping[str, object], ...]: ...

    def create_main_device(
        self,
        *,
        flask_request: Request,
        payload: object,
    ) -> Mapping[str, object]: ...

    def preview_device_move(
        self,
        *,
        flask_request: Request,
        payload: object,
    ) -> Mapping[str, object]: ...

    def confirm_device_move(
        self,
        *,
        flask_request: Request,
        payload: object,
    ) -> Mapping[str, object]: ...


class SqlAlchemyWarehouseSaasHttpRuntime:
    __slots__ = ("_tenant_business_runtime",)

    def __init__(
        self,
        *,
        tenant_business_runtime: TenantBusinessHttpRuntime,
    ) -> None:
        if not isinstance(tenant_business_runtime, TenantBusinessHttpRuntime):
            raise TypeError(
                "tenant_business_runtime must implement TenantBusinessHttpRuntime"
            )
        self._tenant_business_runtime = tenant_business_runtime

    def get_default_setup(self, *, flask_request):
        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.WAREHOUSE_SETUP,
                request_id_prefix="warehouse-default-setup-read",
                allow_pending_warehouse_setup=True,
            ) as scope:
                with scope.tenant_session.begin():
                    row = WarehouseService.get_default_warehouse(
                        tenant_session=scope.tenant_session
                    )
                    return _warehouse_dto(row)
        except WarehouseServiceError as exc:
            if isinstance(exc, WarehousePersistenceError):
                raise WarehouseSaasHttpRuntimeUnavailable() from None
            raise WarehouseMutationError(exc) from None
        except TenantBusinessRuntimeUnavailable:
            raise WarehouseSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise WarehouseSaasHttpRuntimeUnavailable() from None

    def setup_default_warehouse(self, *, flask_request, payload):
        parsed = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed
            parsed = _parse_profile(payload)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.WAREHOUSE_SETUP,
                request_id_prefix="warehouse-default-setup-write",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(WarehouseRequestInvalid,),
                allow_pending_warehouse_setup=True,
            ) as scope:
                if parsed is None:
                    raise WarehouseSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    row = WarehouseService.setup_default_warehouse(
                        tenant_session=scope.tenant_session,
                        **parsed,
                    )
                    return _warehouse_dto(row)
        except WarehouseRequestInvalid:
            raise
        except WarehouseServiceError as exc:
            if isinstance(exc, WarehousePersistenceError):
                raise WarehouseSaasHttpRuntimeUnavailable() from None
            raise WarehouseMutationError(exc) from None
        except TenantBusinessRuntimeUnavailable:
            raise WarehouseSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise WarehouseSaasHttpRuntimeUnavailable() from None

    def list_warehouses(self, *, flask_request):
        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.WAREHOUSE_READ,
                request_id_prefix="warehouse-list",
            ) as scope:
                with scope.tenant_session.begin():
                    rows = WarehouseService.list_warehouses(
                        tenant_session=scope.tenant_session
                    )
                    return tuple(_warehouse_dto(row) for row in rows)
        except TenantBusinessRuntimeUnavailable:
            raise WarehouseSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise WarehouseSaasHttpRuntimeUnavailable() from None

    def create_warehouse(self, *, flask_request, payload):
        parsed = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed
            parsed = _parse_profile(payload)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.WAREHOUSE_WRITE,
                request_id_prefix="warehouse-create",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(WarehouseRequestInvalid,),
            ) as scope:
                if parsed is None:
                    raise WarehouseSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    row = WarehouseService.create_ready_warehouse(
                        tenant_session=scope.tenant_session,
                        **parsed,
                    )
                    return _warehouse_dto(row)
        except WarehouseRequestInvalid:
            raise
        except WarehouseServiceError as exc:
            if isinstance(exc, WarehousePersistenceError):
                raise WarehouseSaasHttpRuntimeUnavailable() from None
            raise WarehouseMutationError(exc) from None
        except TenantBusinessRuntimeUnavailable:
            raise WarehouseSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise WarehouseSaasHttpRuntimeUnavailable() from None

    def update_warehouse(
        self,
        *,
        flask_request,
        warehouse_id,
        payload,
    ):
        parsed = None
        parsed_id = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed, parsed_id
            parsed_id = _positive_integer(warehouse_id)
            parsed = _parse_profile(payload)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.WAREHOUSE_WRITE,
                request_id_prefix="warehouse-update",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(WarehouseRequestInvalid,),
            ) as scope:
                if parsed is None or parsed_id is None:
                    raise WarehouseSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    row = WarehouseService.update_warehouse(
                        tenant_session=scope.tenant_session,
                        warehouse_id=parsed_id,
                        **parsed,
                    )
                    return _warehouse_dto(row)
        except WarehouseRequestInvalid:
            raise
        except WarehouseServiceError as exc:
            if isinstance(exc, WarehousePersistenceError):
                raise WarehouseSaasHttpRuntimeUnavailable() from None
            raise WarehouseMutationError(exc) from None
        except TenantBusinessRuntimeUnavailable:
            raise WarehouseSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise WarehouseSaasHttpRuntimeUnavailable() from None

    def set_default_warehouse(
        self,
        *,
        flask_request,
        warehouse_id,
    ):
        parsed_id = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed_id
            parsed_id = _positive_integer(warehouse_id)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.WAREHOUSE_WRITE,
                request_id_prefix="warehouse-set-default",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(WarehouseRequestInvalid,),
            ) as scope:
                if parsed_id is None:
                    raise WarehouseSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    row = WarehouseService.set_default_warehouse(
                        tenant_session=scope.tenant_session,
                        warehouse_id=parsed_id,
                    )
                    return _warehouse_dto(row)
        except WarehouseRequestInvalid:
            raise
        except WarehouseServiceError as exc:
            if isinstance(exc, WarehousePersistenceError):
                raise WarehouseSaasHttpRuntimeUnavailable() from None
            raise WarehouseMutationError(exc) from None
        except TenantBusinessRuntimeUnavailable:
            raise WarehouseSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise WarehouseSaasHttpRuntimeUnavailable() from None

    def deactivate_warehouse(
        self,
        *,
        flask_request,
        warehouse_id,
    ):
        parsed_id = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed_id
            parsed_id = _positive_integer(warehouse_id)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.WAREHOUSE_WRITE,
                request_id_prefix="warehouse-deactivate",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(WarehouseRequestInvalid,),
            ) as scope:
                if parsed_id is None:
                    raise WarehouseSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    row = WarehouseService.deactivate_warehouse(
                        tenant_session=scope.tenant_session,
                        warehouse_id=parsed_id,
                    )
                    return _warehouse_dto(row)
        except WarehouseRequestInvalid:
            raise
        except WarehouseServiceError as exc:
            if isinstance(exc, WarehousePersistenceError):
                raise WarehouseSaasHttpRuntimeUnavailable() from None
            raise WarehouseMutationError(exc) from None
        except TenantBusinessRuntimeUnavailable:
            raise WarehouseSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise WarehouseSaasHttpRuntimeUnavailable() from None

    def set_user_preference(
        self,
        *,
        flask_request,
        scene,
        payload,
    ):
        parsed = None

        def parse_after_authorize(auth_context) -> None:
            nonlocal parsed
            parsed = _parse_preference(
                scene=scene,
                payload=payload,
                user_id=auth_context.user_id,
            )

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.WAREHOUSE_WRITE,
                request_id_prefix="warehouse-preference",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(WarehouseRequestInvalid,),
            ) as scope:
                if parsed is None:
                    raise WarehouseSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    preference = WarehouseService.set_user_warehouse_preference(
                        tenant_session=scope.tenant_session,
                        **parsed,
                    )
                    return {
                        "scene": preference.scene,
                        "warehouse_id": preference.warehouse_id,
                    }
        except WarehouseRequestInvalid:
            raise
        except WarehouseServiceError as exc:
            if isinstance(exc, WarehousePersistenceError):
                raise WarehouseSaasHttpRuntimeUnavailable() from None
            raise WarehouseMutationError(exc) from None
        except TenantBusinessRuntimeUnavailable:
            raise WarehouseSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise WarehouseSaasHttpRuntimeUnavailable() from None

    def get_user_preferences(self, *, flask_request):
        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.WAREHOUSE_READ,
                request_id_prefix="warehouse-preference-list",
            ) as scope:
                with scope.tenant_session.begin():
                    rows = WarehouseService.list_user_warehouse_preferences(
                        tenant_session=scope.tenant_session,
                        user_id=scope.auth_context.user_id,
                    )
                    return {
                        row.scene: row.warehouse_id
                        for row in rows
                    }
        except WarehouseServiceError as exc:
            if isinstance(exc, WarehousePersistenceError):
                raise WarehouseSaasHttpRuntimeUnavailable() from None
            raise WarehouseMutationError(exc) from None
        except TenantBusinessRuntimeUnavailable:
            raise WarehouseSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise WarehouseSaasHttpRuntimeUnavailable() from None

    def list_main_devices(self, *, flask_request):
        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.INVENTORY_READ,
                additional_capabilities=(Capability.WAREHOUSE_READ,),
                request_id_prefix="warehouse-device-list",
            ) as scope:
                with scope.tenant_session.begin():
                    rows = tuple(
                        scope.tenant_session.execute(
                            select(Device)
                            .where(
                                Device.is_accessory.is_(False),
                                Device.lifecycle_status == "active",
                            )
                            .order_by(Device.name.asc(), Device.id.asc())
                        )
                        .scalars()
                        .all()
                    )
                    return tuple(
                        {
                            "id": row.id,
                            "name": row.name,
                            "serial_number": row.serial_number,
                            "model": row.model,
                            "model_id": row.model_id,
                            "warehouse_id": row.warehouse_id,
                        }
                        for row in rows
                    )
        except TenantBusinessRuntimeUnavailable:
            raise WarehouseSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise WarehouseSaasHttpRuntimeUnavailable() from None

    def list_main_device_models(self, *, flask_request):
        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.INVENTORY_READ,
                request_id_prefix="warehouse-device-model-list",
            ) as scope:
                with scope.tenant_session.begin():
                    rows = tuple(
                        scope.tenant_session.execute(
                            select(DeviceModel)
                            .where(
                                DeviceModel.is_active.is_(True),
                                DeviceModel.is_accessory.is_(False),
                            )
                            .order_by(
                                DeviceModel.display_name.asc(),
                                DeviceModel.id.asc(),
                            )
                        )
                        .scalars()
                        .all()
                    )
                    return tuple(
                        {
                            "id": row.id,
                            "name": row.name,
                            "display_name": row.display_name,
                        }
                        for row in rows
                    )
        except TenantBusinessRuntimeUnavailable:
            raise WarehouseSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise WarehouseSaasHttpRuntimeUnavailable() from None

    def create_main_device(self, *, flask_request, payload):
        parsed = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed
            parsed = _parse_main_device(payload)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.INVENTORY_WRITE,
                additional_capabilities=(Capability.WAREHOUSE_READ,),
                request_id_prefix="warehouse-device-create",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(WarehouseRequestInvalid,),
            ) as scope:
                if parsed is None:
                    raise WarehouseSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    row = WarehouseService.create_main_device(
                        tenant_session=scope.tenant_session,
                        **parsed,
                    )
                    return {
                        "id": row.id,
                        "name": row.name,
                        "serial_number": row.serial_number,
                        "model": row.model,
                        "model_id": row.model_id,
                        "warehouse_id": row.warehouse_id,
                        "lifecycle_status": row.lifecycle_status,
                    }
        except WarehouseRequestInvalid:
            raise
        except WarehouseServiceError as exc:
            if isinstance(exc, WarehousePersistenceError):
                raise WarehouseSaasHttpRuntimeUnavailable() from None
            raise WarehouseMutationError(exc) from None
        except TenantBusinessRuntimeUnavailable:
            raise WarehouseSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise WarehouseSaasHttpRuntimeUnavailable() from None

    def preview_device_move(self, *, flask_request, payload):
        parsed = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed
            parsed = _parse_move_preview(payload)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.WAREHOUSE_DEVICE_MOVE,
                additional_capabilities=(
                    Capability.WAREHOUSE_READ,
                    Capability.RENTAL_READ,
                    Capability.INVENTORY_READ,
                ),
                request_id_prefix="warehouse-move-preview",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(WarehouseRequestInvalid,),
            ) as scope:
                if parsed is None:
                    raise WarehouseSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    result = WarehouseService.preview_device_move(
                        tenant_session=scope.tenant_session,
                        business_date=_business_date(scope),
                        **parsed,
                    )
                    return _preview_dto(result)
        except WarehouseRequestInvalid:
            raise
        except WarehouseServiceError as exc:
            raise WarehouseMutationError(exc) from None
        except TenantBusinessRuntimeUnavailable:
            raise WarehouseSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise WarehouseSaasHttpRuntimeUnavailable() from None

    def confirm_device_move(self, *, flask_request, payload):
        parsed = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed
            parsed = _parse_move_confirmation(payload)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.WAREHOUSE_DEVICE_MOVE,
                additional_capabilities=(
                    Capability.WAREHOUSE_WRITE,
                    Capability.INVENTORY_WRITE,
                    Capability.RENTAL_READ,
                ),
                request_id_prefix="warehouse-move-confirm",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(WarehouseRequestInvalid,),
            ) as scope:
                if parsed is None:
                    raise WarehouseSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    result = WarehouseService.execute_device_move(
                        tenant_session=scope.tenant_session,
                        business_date=_business_date(scope),
                        actor_user_id=scope.auth_context.user_id,
                        **parsed,
                    )
                    return _move_result_dto(result)
        except WarehouseRequestInvalid:
            raise
        except WarehouseServiceError as exc:
            if isinstance(exc, WarehousePersistenceError):
                raise WarehouseSaasHttpRuntimeUnavailable() from None
            raise WarehouseMutationError(exc) from None
        except TenantBusinessRuntimeUnavailable:
            raise WarehouseSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise WarehouseSaasHttpRuntimeUnavailable() from None

    def __repr__(self) -> str:
        return "SqlAlchemyWarehouseSaasHttpRuntime(fail_closed=True)"


def require_warehouse_saas_http_runtime() -> WarehouseSaasHttpRuntime:
    runtime = current_app.extensions.get(WAREHOUSE_SAAS_HTTP_RUNTIME_EXTENSION)
    if not isinstance(runtime, WarehouseSaasHttpRuntime):
        raise WarehouseSaasHttpRuntimeUnavailable()
    return runtime


def _warehouse_dto(row) -> dict[str, object]:
    return {
        "id": row.id,
        "warehouse_uuid": row.warehouse_uuid,
        "name": row.name,
        "status": row.status,
        "setup_state": row.setup_state,
        "is_default": row.is_default is True,
        "contact_name": row.contact_name,
        "contact_phone": row.contact_phone,
        "province": row.province,
        "city": row.city,
        "district": row.district,
        "address_detail": row.address_detail,
    }


def _preview_dto(result) -> dict[str, object]:
    return {
        "device": {
            "id": result.device.id,
            "name": result.device.name,
            "warehouse_id": result.device.warehouse_id,
        },
        "current_warehouse": (
            _warehouse_reference_dto(result.current_warehouse)
            if result.current_warehouse is not None
            else None
        ),
        "target_warehouse": _warehouse_reference_dto(
            result.target_warehouse
        ),
        "is_same_warehouse": result.is_same_warehouse,
        "affected_rental_ids": list(result.affected_rental_ids),
        "affected_rentals": [
            {
                "rental_id": rental.rental_id,
                "order_number": rental.order_number,
                "customer_start_date": rental.customer_start_date.isoformat(),
                "customer_end_date": rental.customer_end_date.isoformat(),
                "logistics_days": rental.logistics_days,
                "planned_ship_out_date": (
                    rental.planned_ship_out_date.isoformat()
                    if rental.planned_ship_out_date is not None
                    else None
                ),
                "planned_return_date": (
                    rental.planned_return_date.isoformat()
                    if rental.planned_return_date is not None
                    else None
                ),
                "affected_accessory_types": [
                    {
                        "accessory_type_id": item.accessory_type_id,
                        "name": item.name,
                    }
                    for item in rental.affected_accessory_types
                ],
            }
            for rental in result.affected_rentals
        ],
        "revision": result.revision,
        "preserves_logistics_facts": result.preserves_logistics_facts,
    }


def _warehouse_reference_dto(row) -> dict[str, object]:
    return {
        "id": row.id,
        "warehouse_uuid": row.warehouse_uuid,
        "name": row.name,
        "status": row.status,
        "setup_state": row.setup_state,
    }


def _move_result_dto(result) -> dict[str, object]:
    return {
        "device_id": result.device_id,
        "from_warehouse_id": result.from_warehouse_id,
        "to_warehouse_id": result.to_warehouse_id,
        "movement_id": result.movement_id,
        "affected_rental_ids": list(result.affected_rental_ids),
        "accessory_fulfillment": [
            {
                "rental_id": item.rental_id,
                "accessory_type_id": item.accessory_type_id,
                "accessory_name": item.accessory_name,
                "status": item.status,
            }
            for item in result.accessory_fulfillment
        ],
    }


def _parse_profile(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise WarehouseRequestInvalid()
    limits = {
        "name": 120,
        "contact_name": 120,
        "contact_phone": 32,
        "province": 64,
        "city": 64,
        "district": 64,
        "address_detail": 255,
    }
    return {
        field: _required_text(value.get(field), maximum=maximum)
        for field, maximum in limits.items()
    }


def _parse_preference(
    *,
    scene: object,
    payload: object,
    user_id: str,
) -> dict[str, object]:
    if (
        scene not in {"booking", "shipping", "inspection"}
        or not isinstance(payload, Mapping)
    ):
        raise WarehouseRequestInvalid()
    return {
        "user_id": user_id,
        "scene": scene,
        "warehouse_id": _positive_integer(payload.get("warehouse_id")),
    }


def _parse_move_preview(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise WarehouseRequestInvalid()
    return {
        "device_id": _positive_integer(value.get("device_id")),
        "target_warehouse_id": _positive_integer(
            value.get("target_warehouse_id")
        ),
    }


def _parse_main_device(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise WarehouseRequestInvalid()
    warehouse_value = value.get("warehouse_id")
    return {
        "name": _required_text(value.get("name"), maximum=100),
        "serial_number": _required_text(
            value.get("serial_number"), maximum=100
        ),
        "model_id": _positive_integer(value.get("model_id")),
        "warehouse_id": (
            None
            if warehouse_value is None
            else _positive_integer(warehouse_value)
        ),
    }


def _parse_move_confirmation(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise WarehouseRequestInvalid()
    expected_value = value.get("expected_current_warehouse_id")
    expected_current_warehouse_id = (
        None if expected_value is None else _positive_integer(expected_value)
    )
    revision = value.get("expected_preview_revision")
    if (
        not isinstance(revision, str)
        or len(revision) != 64
        or any(character not in "0123456789abcdef" for character in revision)
        or value.get("confirmed") is not True
    ):
        raise WarehouseRequestInvalid()
    raw_note = value.get("note")
    note = None
    if raw_note is not None:
        if not isinstance(raw_note, str) or "\x00" in raw_note:
            raise WarehouseRequestInvalid()
        note = raw_note.strip() or None
        if note is not None and len(note) > 500:
            raise WarehouseRequestInvalid()
    return {
        "device_id": _positive_integer(value.get("device_id")),
        "target_warehouse_id": _positive_integer(
            value.get("target_warehouse_id")
        ),
        "expected_current_warehouse_id": expected_current_warehouse_id,
        "expected_preview_revision": revision,
        "confirmation_token_confirmed": True,
        "note": note,
    }


def _positive_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WarehouseRequestInvalid()
    return value


def _required_text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise WarehouseRequestInvalid()
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise WarehouseRequestInvalid()
    return normalized


def _business_date(scope) -> date:
    return scope.database_now.astimezone(
        ZoneInfo(scope.auth_context.tenant_timezone)
    ).date()


__all__ = [
    "WAREHOUSE_SAAS_HTTP_RUNTIME_EXTENSION",
    "SqlAlchemyWarehouseSaasHttpRuntime",
    "WarehouseMutationError",
    "WarehouseRequestInvalid",
    "WarehouseSaasHttpRuntime",
    "WarehouseSaasHttpRuntimeUnavailable",
    "require_warehouse_saas_http_runtime",
]
