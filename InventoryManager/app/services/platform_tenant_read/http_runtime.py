"""Audited one-tenant-at-a-time platform SELECT-only HTTP runtime."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Callable, Mapping, Protocol, TypeVar, runtime_checkable
from uuid import UUID, uuid4

from flask import Request, current_app
import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.tenancy import PlatformTenantReadContext
from inventory_control.database import ControlDatabase, read_database_utc_value
from inventory_control.domain import Capability, has_platform_capability
from inventory_control.models import PlatformAuditLog, Tenant
from inventory_control.platform_http import (
    PlatformAuthContext,
    PlatformCapabilityDenied,
    PlatformHttpBoundary,
    PlatformHttpError,
)
from inventory_control.routing import PlatformTenantReadRouter, TenantDatabaseRouter

from .query_service import (
    PlatformTenantBusinessQueryService,
    PlatformTenantQueryInputError,
)


PLATFORM_TENANT_READ_HTTP_RUNTIME_EXTENSION = (
    "inventory_platform_tenant_read_http_runtime"
)
_READABLE_TENANT_STATUSES = frozenset(
    {
        "active",
        "expired",
        "suspending",
        "suspended",
        "resuming",
        "deletion_cooling_off",
    }
)
_RENTAL_STATUSES = frozenset(
    {
        "not_shipped",
        "scheduled_for_shipping",
        "shipped",
        "returned",
        "completed",
        "cancelled",
    }
)
_DEVICE_STATUSES = frozenset(
    {"active", "sold", "decommissioned", "damaged", "retired"}
)
_WAREHOUSE_STATUSES = frozenset({"active", "inactive"})
_WAREHOUSE_SETUP_STATES = frozenset({"pending", "ready"})
_PII_REASON_CODE = re.compile(r"[a-z][a-z0-9_.:-]{0,39}", re.ASCII)


class PlatformTenantReadRuntimeUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("PLATFORM_TENANT_READ_RUNTIME_UNAVAILABLE")


class PlatformTenantReadQueryHttpInvalid(PlatformHttpError):
    status_code = 400
    code = "PLATFORM_TENANT_READ_QUERY_INVALID"
    public_message = "The platform tenant read query is invalid."


class PlatformTenantReadTargetHttpUnavailable(PlatformHttpError):
    status_code = 404
    code = "PLATFORM_TENANT_READ_TARGET_UNAVAILABLE"
    public_message = "The platform tenant read target is unavailable."


class PlatformTenantReadResourceHttpUnavailable(PlatformHttpError):
    status_code = 404
    code = "PLATFORM_TENANT_READ_RESOURCE_UNAVAILABLE"
    public_message = "The platform tenant read resource is unavailable."


TenantRouterFactory = Callable[
    [Session],
    AbstractContextManager[TenantDatabaseRouter[Engine]],
]
_TenantQueryResult = TypeVar("_TenantQueryResult")


@dataclass(frozen=True, slots=True)
class _ResolvedTarget:
    tenant_id: UUID
    access_version: int


@dataclass(frozen=True, slots=True)
class _ListOperation:
    request_id_prefix: str
    route: str
    action: str
    target_resource_type: str
    success_reason: str


_LIST_OPERATIONS = {
    "rentals": _ListOperation(
        request_id_prefix="platform-tenant-rentals",
        route="GET /platform/api/tenants/<tenant_id>/read/rentals",
        action="platform.tenant_rentals.list",
        target_resource_type="rental",
        success_reason="platform_tenant_read.rentals_succeeded",
    ),
    "devices": _ListOperation(
        request_id_prefix="platform-tenant-devices",
        route="GET /platform/api/tenants/<tenant_id>/read/devices",
        action="platform.tenant_devices.list",
        target_resource_type="device",
        success_reason="platform_tenant_read.devices_succeeded",
    ),
    "warehouses": _ListOperation(
        request_id_prefix="platform-tenant-warehouses",
        route="GET /platform/api/tenants/<tenant_id>/read/warehouses",
        action="platform.tenant_warehouses.list",
        target_resource_type="warehouse",
        success_reason="platform_tenant_read.warehouses_succeeded",
    ),
}


@runtime_checkable
class PlatformTenantReadHttpRuntime(Protocol):
    def list_rentals(
        self,
        *,
        flask_request: Request,
        tenant_id: object,
        query_arguments: object,
    ) -> Mapping[str, object]: ...

    def list_devices(
        self,
        *,
        flask_request: Request,
        tenant_id: object,
        query_arguments: object,
    ) -> Mapping[str, object]: ...

    def list_warehouses(
        self,
        *,
        flask_request: Request,
        tenant_id: object,
        query_arguments: object,
    ) -> Mapping[str, object]: ...

    def get_rental_customer_pii(
        self,
        *,
        flask_request: Request,
        tenant_id: object,
        rental_id: object,
        query_arguments: object,
    ) -> Mapping[str, object]: ...


class SqlAlchemyPlatformTenantReadHttpRuntime:
    """Use a distinct platform-read account and audit before returning data."""

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        platform_boundary: PlatformHttpBoundary,
        tenant_router_factory: TenantRouterFactory,
        read_policy_version: int,
        maximum_execution_time_ms: int,
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise TypeError("control_database must be a ControlDatabase")
        if not isinstance(platform_boundary, PlatformHttpBoundary):
            raise TypeError("platform_boundary must be a PlatformHttpBoundary")
        if not callable(tenant_router_factory):
            raise TypeError("tenant_router_factory must be callable")
        if (
            isinstance(read_policy_version, bool)
            or not isinstance(read_policy_version, int)
            or read_policy_version < 1
        ):
            raise ValueError("read_policy_version must be positive")
        self._control_database = control_database
        self._platform_boundary = platform_boundary
        self._tenant_router_factory = tenant_router_factory
        self._read_policy_version = read_policy_version
        self._query_service = PlatformTenantBusinessQueryService(
            maximum_execution_time_ms=maximum_execution_time_ms
        )

    @property
    def control_database(self) -> ControlDatabase:
        return self._control_database

    @property
    def platform_boundary(self) -> PlatformHttpBoundary:
        return self._platform_boundary

    def list_rentals(
        self,
        *,
        flask_request: Request,
        tenant_id: object,
        query_arguments: object,
    ) -> Mapping[str, object]:
        return self._list_resource(
            flask_request=flask_request,
            tenant_id=tenant_id,
            query_arguments=query_arguments,
            operation="rentals",
            parse_query=_rental_list_query,
            execute_query=lambda session, values: (
                self._query_service.list_rentals(
                    session,
                    page=values[0],
                    page_size=values[1],
                    status=values[2],
                )
            ),
        )

    def list_devices(
        self,
        *,
        flask_request: Request,
        tenant_id: object,
        query_arguments: object,
    ) -> Mapping[str, object]:
        return self._list_resource(
            flask_request=flask_request,
            tenant_id=tenant_id,
            query_arguments=query_arguments,
            operation="devices",
            parse_query=_device_list_query,
            execute_query=lambda session, values: (
                self._query_service.list_devices(
                    session,
                    page=values[0],
                    page_size=values[1],
                    lifecycle_status=values[2],
                )
            ),
        )

    def list_warehouses(
        self,
        *,
        flask_request: Request,
        tenant_id: object,
        query_arguments: object,
    ) -> Mapping[str, object]:
        return self._list_resource(
            flask_request=flask_request,
            tenant_id=tenant_id,
            query_arguments=query_arguments,
            operation="warehouses",
            parse_query=_warehouse_list_query,
            execute_query=lambda session, values: (
                self._query_service.list_warehouses(
                    session,
                    page=values[0],
                    page_size=values[1],
                    status=values[2],
                    setup_state=values[3],
                )
            ),
        )

    def get_rental_customer_pii(
        self,
        *,
        flask_request: Request,
        tenant_id: object,
        rental_id: object,
        query_arguments: object,
    ) -> Mapping[str, object]:
        request_id = f"platform-tenant-rental-pii:{uuid4()}"
        route = (
            "GET /platform/api/tenants/<tenant_id>/read/"
            "rentals/<rental_id>/customer-pii"
        )
        action = "platform.tenant_rental_customer_pii.read"
        actor: PlatformAuthContext | None = None
        try:
            actor = self._authorize(flask_request)
            if not has_platform_capability(
                actor.role,
                Capability.CUSTOMER_PII_READ,
            ):
                raise PlatformCapabilityDenied()
        except PlatformHttpError:
            self._audit(
                actor=actor,
                target_tenant_id=None,
                outcome="rejected",
                safe_reason_code="platform_tenant_pii.auth_rejected",
                result_count=None,
                request_id=request_id,
                route=route,
                action=action,
                pii_revealed=False,
            )
            raise
        except Exception:
            raise PlatformTenantReadRuntimeUnavailable() from None

        try:
            target = self._resolve_target(tenant_id)
        except PlatformTenantReadTargetHttpUnavailable:
            self._audit(
                actor=actor,
                target_tenant_id=None,
                outcome="rejected",
                safe_reason_code="platform_tenant_pii.target_rejected",
                result_count=None,
                request_id=request_id,
                route=route,
                action=action,
                pii_revealed=False,
            )
            raise
        except Exception:
            self._audit_failed(
                actor,
                None,
                request_id,
                route=route,
                action=action,
                safe_reason_code="platform_tenant_pii.target_failed",
            )
            raise PlatformTenantReadRuntimeUnavailable() from None

        try:
            selected_rental_id, reason_code = _pii_detail_query(
                rental_id,
                query_arguments,
            )
        except PlatformTenantQueryInputError:
            self._audit(
                actor=actor,
                target_tenant_id=target.tenant_id,
                outcome="rejected",
                safe_reason_code="platform_tenant_pii.query_rejected",
                result_count=None,
                request_id=request_id,
                route=route,
                action=action,
                pii_revealed=False,
            )
            raise PlatformTenantReadQueryHttpInvalid() from None

        try:
            result = self._read_rental_customer_pii(
                actor=actor,
                target=target,
                request_id=request_id,
                rental_id=selected_rental_id,
            )
        except Exception:
            self._audit_failed(
                actor,
                target.tenant_id,
                request_id,
                route=route,
                action=action,
                target_resource_id=str(selected_rental_id),
                safe_reason_code="platform_tenant_pii.query_failed",
            )
            raise PlatformTenantReadRuntimeUnavailable() from None
        if result is None:
            self._audit(
                actor=actor,
                target_tenant_id=target.tenant_id,
                outcome="rejected",
                safe_reason_code="platform_tenant_pii.resource_unavailable",
                result_count=0,
                request_id=request_id,
                route=route,
                action=action,
                pii_revealed=False,
                target_resource_id=str(selected_rental_id),
            )
            raise PlatformTenantReadResourceHttpUnavailable()

        self._audit(
            actor=actor,
            target_tenant_id=target.tenant_id,
            outcome="succeeded",
            safe_reason_code=f"platform_pii.{reason_code}",
            result_count=1,
            request_id=request_id,
            route=route,
            action=action,
            pii_revealed=True,
            target_resource_id=str(selected_rental_id),
        )
        return result

    def _list_resource(
        self,
        *,
        flask_request: Request,
        tenant_id: object,
        query_arguments: object,
        operation: str,
        parse_query: Callable[[object], object],
        execute_query: Callable[[Session, object], dict[str, object]],
    ) -> dict[str, object]:
        definition = _LIST_OPERATIONS[operation]
        request_id = f"{definition.request_id_prefix}:{uuid4()}"
        audit_fields = {
            "request_id": request_id,
            "route": definition.route,
            "action": definition.action,
            "target_resource_type": definition.target_resource_type,
        }
        try:
            actor = self._authorize(flask_request)
        except PlatformHttpError:
            self._audit(
                actor=None,
                target_tenant_id=None,
                outcome="rejected",
                safe_reason_code="platform_tenant_read.auth_rejected",
                result_count=None,
                **audit_fields,
            )
            raise
        except Exception:
            raise PlatformTenantReadRuntimeUnavailable() from None

        try:
            target = self._resolve_target(tenant_id)
        except PlatformTenantReadTargetHttpUnavailable:
            self._audit(
                actor=actor,
                target_tenant_id=None,
                outcome="rejected",
                safe_reason_code="platform_tenant_read.target_rejected",
                result_count=None,
                **audit_fields,
            )
            raise
        except Exception:
            self._audit(
                actor=actor,
                target_tenant_id=None,
                outcome="failed",
                safe_reason_code="platform_tenant_read.target_failed",
                result_count=None,
                **audit_fields,
            )
            raise PlatformTenantReadRuntimeUnavailable() from None

        try:
            parsed_query = parse_query(query_arguments)
        except PlatformTenantQueryInputError:
            self._audit(
                actor=actor,
                target_tenant_id=target.tenant_id,
                outcome="rejected",
                safe_reason_code="platform_tenant_read.query_rejected",
                result_count=None,
                **audit_fields,
            )
            raise PlatformTenantReadQueryHttpInvalid() from None

        try:
            result = self._read_tenant_query(
                actor=actor,
                target=target,
                request_id=request_id,
                query=lambda session: execute_query(session, parsed_query),
            )
        except Exception:
            self._audit(
                actor=actor,
                target_tenant_id=target.tenant_id,
                outcome="failed",
                safe_reason_code="platform_tenant_read.query_failed",
                result_count=None,
                **audit_fields,
            )
            raise PlatformTenantReadRuntimeUnavailable() from None

        self._audit(
            actor=actor,
            target_tenant_id=target.tenant_id,
            outcome="succeeded",
            safe_reason_code=definition.success_reason,
            result_count=len(result["items"]),
            **audit_fields,
        )
        return result

    def _authorize(self, flask_request: Request) -> PlatformAuthContext:
        with self._control_database.transaction() as session:
            return self._platform_boundary.authorize(
                session,
                flask_request,
                capability=Capability.PLATFORM_TENANT_BUSINESS_READ,
                now=_database_now(session),
            )

    def _resolve_target(self, value: object) -> _ResolvedTarget:
        try:
            canonical = str(value)
            target_id = UUID(canonical)
        except (TypeError, ValueError, AttributeError):
            raise PlatformTenantReadTargetHttpUnavailable() from None
        if str(target_id) != canonical:
            raise PlatformTenantReadTargetHttpUnavailable()
        with self._control_database.transaction() as session:
            row = session.execute(
                sa.select(Tenant.id, Tenant.status, Tenant.access_version).where(
                    Tenant.id == str(target_id)
                )
            ).one_or_none()
            if row is None or row.status not in _READABLE_TENANT_STATUSES:
                raise PlatformTenantReadTargetHttpUnavailable()
            return _ResolvedTarget(
                tenant_id=target_id,
                access_version=row.access_version,
            )

    def _read_tenant_query(
        self,
        *,
        actor: PlatformAuthContext,
        target: _ResolvedTarget,
        request_id: str,
        query: Callable[[Session], _TenantQueryResult],
    ) -> _TenantQueryResult:
        context = PlatformTenantReadContext(
            target_tenant_id=target.tenant_id,
            target_access_version=target.access_version,
            platform_admin_id=UUID(actor.platform_admin_id),
            platform_session_id=UUID(actor.session_id),
            read_policy_version=self._read_policy_version,
            request_id=request_id,
        )
        with self._control_database.transaction() as control_session:
            with self._tenant_router_factory(control_session) as router:
                if not isinstance(router, TenantDatabaseRouter):
                    raise TypeError("tenant router factory returned invalid router")
                engine = PlatformTenantReadRouter(router).get_engine(context)
        if not isinstance(engine, Engine):
            raise TypeError("platform read router returned invalid engine")
        tenant_session = Session(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )
        try:
            with tenant_session.begin():
                if engine.dialect.name in {"mysql", "mariadb"}:
                    tenant_session.execute(sa.text("SET TRANSACTION READ ONLY"))
                return query(tenant_session)
        finally:
            tenant_session.close()

    def _read_rental_customer_pii(
        self,
        *,
        actor: PlatformAuthContext,
        target: _ResolvedTarget,
        request_id: str,
        rental_id: int,
    ) -> dict[str, object] | None:
        return self._read_tenant_query(
            actor=actor,
            target=target,
            request_id=request_id,
            query=lambda tenant_session: self._query_service.get_customer_pii(
                tenant_session,
                rental_id=rental_id,
            ),
        )

    def _audit_failed(
        self,
        actor: PlatformAuthContext,
        target_tenant_id: UUID | None,
        request_id: str,
        *,
        route: str = "GET /platform/api/tenants/<tenant_id>/read/rentals",
        action: str = "platform.tenant_rentals.list",
        target_resource_id: str | None = None,
        target_resource_type: str = "rental",
        safe_reason_code: str = "platform_tenant_read.query_failed",
    ) -> None:
        self._audit(
            actor=actor,
            target_tenant_id=target_tenant_id,
            outcome="failed",
            safe_reason_code=safe_reason_code,
            result_count=None,
            request_id=request_id,
            route=route,
            action=action,
            target_resource_id=target_resource_id,
            target_resource_type=target_resource_type,
        )

    def _audit(
        self,
        *,
        actor: PlatformAuthContext | None,
        target_tenant_id: UUID | None,
        outcome: str,
        safe_reason_code: str,
        result_count: int | None,
        request_id: str,
        route: str = "GET /platform/api/tenants/<tenant_id>/read/rentals",
        action: str = "platform.tenant_rentals.list",
        pii_revealed: bool = False,
        target_resource_id: str | None = None,
        target_resource_type: str = "rental",
    ) -> None:
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                session.add(
                    PlatformAuditLog(
                        actor_type=(
                            "system" if actor is None else "platform_admin"
                        ),
                        actor_platform_admin_id=(
                            None if actor is None else actor.platform_admin_id
                        ),
                        actor_platform_session_id=(
                            None if actor is None else actor.session_id
                        ),
                        target_tenant_id=(
                            None
                            if target_tenant_id is None
                            else str(target_tenant_id)
                        ),
                        target_resource_type=target_resource_type,
                        target_resource_id=target_resource_id,
                        route_or_command_template=route,
                        action=action,
                        access_mode="tenant_read",
                        pii_revealed=pii_revealed,
                        outcome=outcome,
                        safe_reason_code=safe_reason_code,
                        authentication_factor=(
                            None if actor is None else actor.mfa_method
                        ),
                        result_count=result_count,
                        request_id=request_id,
                        created_at=now,
                    )
                )
                session.flush()
        except Exception:
            raise PlatformTenantReadRuntimeUnavailable() from None

    def __repr__(self) -> str:
        return "SqlAlchemyPlatformTenantReadHttpRuntime(select_only=True)"


def _rental_list_query(value: object) -> tuple[int, int, str | None]:
    selected = _paged_list_query(
        value,
        filters={"status": _RENTAL_STATUSES},
    )
    return selected[0], selected[1], selected[2]


def _device_list_query(value: object) -> tuple[int, int, str | None]:
    selected = _paged_list_query(
        value,
        filters={"lifecycle_status": _DEVICE_STATUSES},
    )
    return selected[0], selected[1], selected[2]


def _warehouse_list_query(
    value: object,
) -> tuple[int, int, str | None, str | None]:
    selected = _paged_list_query(
        value,
        filters={
            "status": _WAREHOUSE_STATUSES,
            "setup_state": _WAREHOUSE_SETUP_STATES,
        },
    )
    return selected[0], selected[1], selected[2], selected[3]


def _paged_list_query(
    value: object,
    *,
    filters: Mapping[str, frozenset[str]],
) -> tuple[object, ...]:
    if not hasattr(value, "keys") or not callable(getattr(value, "get", None)):
        raise PlatformTenantQueryInputError()
    try:
        keys = tuple(value.keys())
    except Exception:
        raise PlatformTenantQueryInputError() from None
    if any(key not in {"page", "page_size", *filters} for key in keys):
        raise PlatformTenantQueryInputError()
    getlist = getattr(value, "getlist", None)
    if callable(getlist) and any(len(getlist(key)) != 1 for key in keys):
        raise PlatformTenantQueryInputError()
    selected_filters = []
    for name, allowed in filters.items():
        selected = value.get(name)
        if selected in (None, ""):
            selected_filters.append(None)
        elif isinstance(selected, str) and selected in allowed:
            selected_filters.append(selected)
        else:
            raise PlatformTenantQueryInputError()
    return (
        _canonical_integer(value.get("page", "1"), maximum=100_000),
        _canonical_integer(value.get("page_size", "50"), maximum=100),
        *selected_filters,
    )


def _pii_detail_query(
    rental_id: object,
    value: object,
) -> tuple[int, str]:
    selected_id = _canonical_integer(
        rental_id,
        maximum=9_223_372_036_854_775_807,
    )
    if not hasattr(value, "keys") or not callable(getattr(value, "get", None)):
        raise PlatformTenantQueryInputError()
    try:
        keys = tuple(value.keys())
    except Exception:
        raise PlatformTenantQueryInputError() from None
    if keys != ("reason",):
        raise PlatformTenantQueryInputError()
    getlist = getattr(value, "getlist", None)
    if callable(getlist) and len(getlist("reason")) != 1:
        raise PlatformTenantQueryInputError()
    reason = value.get("reason")
    if not isinstance(reason, str) or _PII_REASON_CODE.fullmatch(reason) is None:
        raise PlatformTenantQueryInputError()
    return selected_id, reason


def _canonical_integer(value: object, *, maximum: int) -> int:
    try:
        selected = int(value)
    except (TypeError, ValueError, OverflowError):
        raise PlatformTenantQueryInputError() from None
    if (
        isinstance(value, bool)
        or not 1 <= selected <= maximum
        or (isinstance(value, str) and str(selected) != value)
    ):
        raise PlatformTenantQueryInputError()
    return selected


def _database_now(session: Session) -> datetime:
    value = read_database_utc_value(session)
    if not isinstance(value, datetime):
        raise ValueError("control database clock is unavailable")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def require_platform_tenant_read_http_runtime() -> PlatformTenantReadHttpRuntime:
    runtime = current_app.extensions.get(
        PLATFORM_TENANT_READ_HTTP_RUNTIME_EXTENSION
    )
    if not isinstance(runtime, PlatformTenantReadHttpRuntime):
        raise PlatformTenantReadRuntimeUnavailable()
    return runtime


__all__ = [
    "PLATFORM_TENANT_READ_HTTP_RUNTIME_EXTENSION",
    "PlatformTenantReadHttpRuntime",
    "PlatformTenantReadQueryHttpInvalid",
    "PlatformTenantReadResourceHttpUnavailable",
    "PlatformTenantReadRuntimeUnavailable",
    "PlatformTenantReadTargetHttpUnavailable",
    "SqlAlchemyPlatformTenantReadHttpRuntime",
    "require_platform_tenant_read_http_runtime",
]
