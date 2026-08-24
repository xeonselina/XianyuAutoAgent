"""Fail-closed SaaS HTTP runtime for tenant inspections."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from flask import Request, current_app
from sqlalchemy.exc import SQLAlchemyError

from app.services.inspection.mutation_service import (
    InspectionMutationError,
    InspectionMutationService,
    parse_create_input,
    parse_update_input,
)
from app.services.inspection.view_service import (
    list_inspections,
    load_inspection,
    load_latest_context,
)
from app.services.tenant_business import (
    TenantBusinessHttpRuntime,
    TenantBusinessRuntimeUnavailable,
)
from inventory_control.domain.rbac import Capability


INSPECTION_SAAS_HTTP_RUNTIME_EXTENSION = "inventory_inspection_saas_http_runtime"


class InspectionSaasHttpRuntimeUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("INSPECTION_SAAS_RUNTIME_UNAVAILABLE")


class InspectionIdInvalid(ValueError):
    def __init__(self) -> None:
        super().__init__("无效的验货记录ID")


class InspectionQueryInvalid(ValueError):
    pass


@runtime_checkable
class InspectionSaasHttpRuntime(Protocol):
    def latest_by_device_id(
        self,
        *,
        flask_request: Request,
        device_id: object,
    ) -> Mapping[str, object] | None:
        ...

    def latest_by_device_name(
        self,
        *,
        flask_request: Request,
        device_name: object,
    ) -> Mapping[str, object] | None:
        ...

    def create_inspection(
        self,
        *,
        flask_request: Request,
        payload: object,
    ) -> Mapping[str, object]:
        ...

    def get_inspection(
        self,
        *,
        flask_request: Request,
        inspection_id: object,
    ) -> Mapping[str, object] | None:
        ...

    def update_inspection(
        self,
        *,
        flask_request: Request,
        inspection_id: object,
        payload: object,
    ) -> Mapping[str, object]:
        ...

    def list_inspections(
        self,
        *,
        flask_request: Request,
        filters: object,
    ) -> Mapping[str, object]:
        ...


class SqlAlchemyInspectionSaasHttpRuntime:
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

    def latest_by_device_id(self, *, flask_request, device_id):
        parsed_id: int | None = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed_id
            parsed_id = _positive_route_id(device_id, InspectionIdInvalid)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.INSPECTION_WRITE,
                additional_capabilities=(
                    Capability.RENTAL_READ,
                    Capability.INVENTORY_READ,
                    Capability.WAREHOUSE_READ,
                    Capability.CUSTOMER_PII_READ,
                ),
                request_id_prefix="inspection-latest",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(InspectionIdInvalid,),
            ) as scope:
                if parsed_id is None:
                    raise InspectionSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    return load_latest_context(
                        scope.tenant_session,
                        business_date=_business_date(scope),
                        actor_id=scope.auth_context.user_id,
                        device_id=parsed_id,
                    )
        except InspectionIdInvalid:
            raise
        except TenantBusinessRuntimeUnavailable:
            raise InspectionSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise InspectionSaasHttpRuntimeUnavailable() from None

    def latest_by_device_name(self, *, flask_request, device_name):
        parsed_name: str | None = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed_name
            parsed_name = _device_name(device_name)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.INSPECTION_WRITE,
                additional_capabilities=(
                    Capability.RENTAL_READ,
                    Capability.INVENTORY_READ,
                    Capability.WAREHOUSE_READ,
                    Capability.CUSTOMER_PII_READ,
                ),
                request_id_prefix="inspection-latest-name",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(InspectionQueryInvalid,),
            ) as scope:
                if parsed_name is None:
                    raise InspectionSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    return load_latest_context(
                        scope.tenant_session,
                        business_date=_business_date(scope),
                        actor_id=scope.auth_context.user_id,
                        device_name=parsed_name,
                    )
        except InspectionQueryInvalid:
            raise
        except TenantBusinessRuntimeUnavailable:
            raise InspectionSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise InspectionSaasHttpRuntimeUnavailable() from None

    def create_inspection(self, *, flask_request, payload):
        parsed = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed
            parsed = parse_create_input(payload)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.INSPECTION_WRITE,
                additional_capabilities=(
                    Capability.RENTAL_READ,
                    Capability.INVENTORY_WRITE,
                    Capability.WAREHOUSE_READ,
                    Capability.WAREHOUSE_DEVICE_MOVE,
                    Capability.CUSTOMER_PII_READ,
                ),
                request_id_prefix="inspection-create",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(InspectionMutationError,),
            ) as scope:
                if parsed is None:
                    raise InspectionSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    mutation_result = InspectionMutationService.create(
                        tenant_session=scope.tenant_session,
                        request=parsed,
                        database_now=scope.database_now,
                        request_id=scope.request_id,
                        actor_id=scope.auth_context.user_id,
                    )
                    result = load_inspection(
                        scope.tenant_session,
                        inspection_id=mutation_result.inspection_id,
                        business_date=_business_date(scope),
                    )
                    if result is None:
                        raise InspectionSaasHttpRuntimeUnavailable()
                    result["accessory_reassignments"] = [
                        asdict(item)
                        for item in mutation_result.accessory_reassignments
                    ]
                    return result
        except InspectionMutationError:
            raise
        except TenantBusinessRuntimeUnavailable:
            raise InspectionSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise InspectionSaasHttpRuntimeUnavailable() from None

    def get_inspection(self, *, flask_request, inspection_id):
        parsed_id: int | None = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed_id
            parsed_id = _positive_route_id(inspection_id, InspectionIdInvalid)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.INSPECTION_WRITE,
                additional_capabilities=(Capability.CUSTOMER_PII_READ,),
                request_id_prefix="inspection-detail",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(InspectionIdInvalid,),
            ) as scope:
                if parsed_id is None:
                    raise InspectionSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    return load_inspection(
                        scope.tenant_session,
                        inspection_id=parsed_id,
                        business_date=_business_date(scope),
                    )
        except InspectionIdInvalid:
            raise
        except TenantBusinessRuntimeUnavailable:
            raise InspectionSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise InspectionSaasHttpRuntimeUnavailable() from None

    def update_inspection(self, *, flask_request, inspection_id, payload):
        parsed_id: int | None = None
        parsed = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed_id, parsed
            parsed_id = _positive_route_id(inspection_id, InspectionIdInvalid)
            parsed = parse_update_input(payload)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.INSPECTION_WRITE,
                additional_capabilities=(Capability.CUSTOMER_PII_READ,),
                request_id_prefix="inspection-update",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(
                    InspectionIdInvalid,
                    InspectionMutationError,
                ),
            ) as scope:
                if parsed_id is None or parsed is None:
                    raise InspectionSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    result_id = InspectionMutationService.update(
                        tenant_session=scope.tenant_session,
                        inspection_id=parsed_id,
                        request=parsed,
                        database_now=scope.database_now,
                    )
                    result = load_inspection(
                        scope.tenant_session,
                        inspection_id=result_id,
                        business_date=_business_date(scope),
                    )
                    if result is None:
                        raise InspectionSaasHttpRuntimeUnavailable()
                    return result
        except (InspectionIdInvalid, InspectionMutationError):
            raise
        except TenantBusinessRuntimeUnavailable:
            raise InspectionSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise InspectionSaasHttpRuntimeUnavailable() from None

    def list_inspections(self, *, flask_request, filters):
        parsed = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed
            parsed = _list_filters(filters)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.INSPECTION_WRITE,
                additional_capabilities=(Capability.CUSTOMER_PII_READ,),
                request_id_prefix="inspection-list",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(InspectionQueryInvalid,),
            ) as scope:
                if parsed is None:
                    raise InspectionSaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    return list_inspections(
                        scope.tenant_session,
                        **parsed,
                        business_date=_business_date(scope),
                    )
        except InspectionQueryInvalid:
            raise
        except TenantBusinessRuntimeUnavailable:
            raise InspectionSaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise InspectionSaasHttpRuntimeUnavailable() from None

    def __repr__(self) -> str:
        return "SqlAlchemyInspectionSaasHttpRuntime(fail_closed=True)"


def require_inspection_saas_http_runtime() -> InspectionSaasHttpRuntime:
    runtime = current_app.extensions.get(INSPECTION_SAAS_HTTP_RUNTIME_EXTENSION)
    if not isinstance(runtime, InspectionSaasHttpRuntime):
        raise InspectionSaasHttpRuntimeUnavailable()
    return runtime


def _positive_route_id(value: object, error_type):
    if isinstance(value, bool):
        raise error_type()
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise error_type() from None
    if parsed < 1 or str(parsed) != str(value):
        raise error_type()
    return parsed


def _device_name(value: object) -> str:
    if not isinstance(value, str):
        raise InspectionQueryInvalid("设备名称无效")
    normalized = value.strip()
    if not normalized or len(normalized) > 100 or "\x00" in normalized:
        raise InspectionQueryInvalid("设备名称无效")
    return normalized


def _list_filters(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise InspectionQueryInvalid("查询参数无效")
    device_name_value = value.get("device_name")
    device_name = None
    if device_name_value not in (None, ""):
        device_name = _device_name(device_name_value)
    status = value.get("status")
    if status in (None, ""):
        status = None
    elif status not in {"normal", "abnormal"}:
        raise InspectionQueryInvalid("验货状态无效")
    page = _bounded_query_integer(value.get("page", 1), minimum=1, maximum=100000)
    per_page = _bounded_query_integer(
        value.get("per_page", 20), minimum=1, maximum=100
    )
    return {
        "device_name": device_name,
        "status": status,
        "page": page,
        "per_page": per_page,
    }


def _bounded_query_integer(value: object, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise InspectionQueryInvalid("分页参数无效")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise InspectionQueryInvalid("分页参数无效") from None
    if str(parsed) != str(value) or not minimum <= parsed <= maximum:
        raise InspectionQueryInvalid("分页参数无效")
    return parsed


def _business_date(scope) -> object:
    value: datetime = scope.database_now
    return value.astimezone(ZoneInfo(scope.auth_context.tenant_timezone)).date()


__all__ = [
    "INSPECTION_SAAS_HTTP_RUNTIME_EXTENSION",
    "InspectionIdInvalid",
    "InspectionQueryInvalid",
    "InspectionSaasHttpRuntime",
    "InspectionSaasHttpRuntimeUnavailable",
    "SqlAlchemyInspectionSaasHttpRuntime",
    "require_inspection_saas_http_runtime",
]
