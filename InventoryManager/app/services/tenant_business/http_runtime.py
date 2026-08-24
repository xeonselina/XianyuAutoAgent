"""Shared authenticated tenant-database scope for business HTTP handlers.

Business services must not obtain tenant authority from request parameters or
the legacy process-global Flask-SQLAlchemy session.  This runtime owns the
common control-plane sequence used by every migrated business capability:

1. authenticate the opaque browser session and enforce CSRF/RBAC;
2. derive the immutable tenant context from that trusted session;
3. resolve and verify exactly one tenant DML engine; and
4. expose an independent, request-bounded SQLAlchemy ``Session``.

Construction and extension lookup are intentionally fail closed.  No legacy
database, cookie signer, API key, or environment-based tenant selector is a
fallback when this composition is absent or incomplete.
"""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterator, Protocol, runtime_checkable
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Request, current_app
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from inventory_control.database import ControlDatabase, read_database_utc_value
from inventory_control.domain.access_policy import (
    has_tenant_capability_for_gate,
)
from inventory_control.domain.rbac import Capability
from inventory_control.routing import AccountKind, TenantDatabaseRouter
from inventory_control.tenant_http import (
    AuthContext,
    TenantCapabilityDenied,
    TenantHttpBoundary,
    TenantHttpError,
    active_tenant_context,
)


TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION = (
    "inventory_tenant_business_http_runtime"
)


class TenantBusinessRuntimeUnavailable(RuntimeError):
    """Trusted authentication or tenant routing could not be established."""

    def __init__(self) -> None:
        super().__init__("TENANT_BUSINESS_RUNTIME_UNAVAILABLE")


class TenantSetupRequired(TenantHttpError):
    """The tenant route is valid but its default warehouse is not ready."""

    status_code = 409
    code = "tenant_setup_required"
    public_message = "请先完成默认仓库设置"


@dataclass(frozen=True, slots=True)
class TenantBusinessRequestScope:
    """Trusted identity and the sole tenant session for one business request."""

    auth_context: AuthContext
    request_id: str
    database_now: datetime
    tenant_session: Session


@runtime_checkable
class TenantBusinessHttpRuntime(Protocol):
    """Open one authorized and routed tenant-business request scope."""

    def tenant_session(
        self,
        *,
        flask_request: Request,
        capability: Capability,
        additional_capabilities: tuple[Capability, ...] = (),
        request_id_prefix: str,
        after_authorize: Callable[[AuthContext], None] | None = None,
        passthrough_exceptions: tuple[type[BaseException], ...] = (),
        allow_pending_warehouse_setup: bool = False,
    ) -> AbstractContextManager[TenantBusinessRequestScope]:
        ...


class SqlAlchemyTenantBusinessHttpRuntime:
    """Control-authenticated, request-scoped tenant DML runtime."""

    __slots__ = (
        "_control_database",
        "_tenant_http_boundary",
        "_tenant_router_factory",
    )

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        tenant_http_boundary: TenantHttpBoundary,
        tenant_router_factory: Callable[
            [Session],
            AbstractContextManager[TenantDatabaseRouter[Engine]],
        ],
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise TypeError("control_database must be a ControlDatabase")
        if not isinstance(tenant_http_boundary, TenantHttpBoundary):
            raise TypeError(
                "tenant_http_boundary must be a TenantHttpBoundary"
            )
        if not callable(tenant_router_factory):
            raise TypeError("tenant_router_factory must be callable")
        self._control_database = control_database
        self._tenant_http_boundary = tenant_http_boundary
        self._tenant_router_factory = tenant_router_factory

    @property
    def control_database(self) -> ControlDatabase:
        return self._control_database

    @property
    def tenant_http_boundary(self) -> TenantHttpBoundary:
        return self._tenant_http_boundary

    @contextmanager
    def tenant_session(
        self,
        *,
        flask_request: Request,
        capability: Capability,
        additional_capabilities: tuple[Capability, ...] = (),
        request_id_prefix: str,
        after_authorize: Callable[[AuthContext], None] | None = None,
        passthrough_exceptions: tuple[type[BaseException], ...] = (),
        allow_pending_warehouse_setup: bool = False,
    ) -> Iterator[TenantBusinessRequestScope]:
        """Authorize before routing, then yield one independently bound session.

        ``after_authorize`` is limited to request-shape checks that must not
        precede authentication (for example, requiring a workflow proof).  A
        caller must enumerate its own safe public exceptions explicitly; all
        other composition, route, and callback failures become the same fixed
        runtime-unavailable condition.
        """

        auth_context, request_id, database_now, engine = self._authorize_and_route(
            flask_request=flask_request,
            capability=capability,
            additional_capabilities=additional_capabilities,
            request_id_prefix=request_id_prefix,
            after_authorize=after_authorize,
            passthrough_exceptions=passthrough_exceptions,
        )
        if not isinstance(allow_pending_warehouse_setup, bool):
            raise TypeError("allow_pending_warehouse_setup must be a bool")
        try:
            tenant_session = Session(
                bind=engine,
                autoflush=False,
                expire_on_commit=False,
            )
        except Exception:
            raise TenantBusinessRuntimeUnavailable() from None

        try:
            if not allow_pending_warehouse_setup:
                try:
                    _require_ready_default_warehouse(tenant_session)
                finally:
                    # The setup gate is a preflight read, never a business
                    # commit.  End its AUTOBEGIN transaction before the
                    # caller opens the authoritative operation transaction.
                    if tenant_session.in_transaction():
                        tenant_session.rollback()
            yield TenantBusinessRequestScope(
                auth_context=auth_context,
                request_id=request_id,
                database_now=database_now,
                tenant_session=tenant_session,
            )
        finally:
            tenant_session.close()

    def _authorize_and_route(
        self,
        *,
        flask_request: Request,
        capability: Capability,
        additional_capabilities: tuple[Capability, ...],
        request_id_prefix: str,
        after_authorize: Callable[[AuthContext], None] | None,
        passthrough_exceptions: tuple[type[BaseException], ...],
    ) -> tuple[AuthContext, str, datetime, Engine]:
        if not isinstance(flask_request, Request):
            raise TypeError("flask_request must be a Flask Request")
        if not isinstance(capability, Capability):
            raise TypeError("capability must be a Capability")
        if (
            not isinstance(additional_capabilities, tuple)
            or any(
                not isinstance(extra, Capability)
                for extra in additional_capabilities
            )
        ):
            raise TypeError(
                "additional_capabilities must contain capabilities"
            )
        if (
            not isinstance(request_id_prefix, str)
            or not request_id_prefix
            or len(request_id_prefix) > 80
        ):
            raise ValueError("request_id_prefix must be a non-empty short string")
        if after_authorize is not None and not callable(after_authorize):
            raise TypeError("after_authorize must be callable")
        if (
            not isinstance(passthrough_exceptions, tuple)
            or any(
                not isinstance(exception_type, type)
                or not issubclass(exception_type, BaseException)
                for exception_type in passthrough_exceptions
            )
        ):
            raise TypeError(
                "passthrough_exceptions must contain exception types"
            )

        try:
            with self._control_database.transaction() as control_session:
                database_now = _database_utc_now(control_session)
                auth_context = self._tenant_http_boundary.authorize(
                    control_session,
                    flask_request,
                    capability=capability,
                    now=database_now,
                )
                _validate_tenant_timezone(auth_context.tenant_timezone)
                for extra_capability in additional_capabilities:
                    if not has_tenant_capability_for_gate(
                        role=auth_context.role,
                        gate=auth_context.effective_gate,
                        capability=extra_capability,
                    ):
                        raise TenantCapabilityDenied()
                if after_authorize is not None:
                    after_authorize(auth_context)
                request_id = f"{request_id_prefix}:{uuid4()}"
                tenant_context = active_tenant_context(
                    auth_context,
                    request_id=request_id,
                )
                with self._tenant_router_factory(control_session) as router:
                    if not isinstance(router, TenantDatabaseRouter):
                        raise TypeError
                    engine = router.get_engine(
                        tenant_context,
                        account_kind=AccountKind.DML,
                    )
                if not isinstance(engine, Engine):
                    raise TypeError
                return auth_context, request_id, database_now, engine
        except TenantHttpError:
            raise
        except passthrough_exceptions:
            raise
        except Exception:
            raise TenantBusinessRuntimeUnavailable() from None

    def __repr__(self) -> str:
        return "SqlAlchemyTenantBusinessHttpRuntime(fail_closed=True)"


def _database_utc_now(session: Session) -> datetime:
    value = read_database_utc_value(session)
    if not isinstance(value, datetime):
        raise ValueError("control database clock is unavailable")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _validate_tenant_timezone(value: object) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 64
        or "\x00" in value
    ):
        raise ValueError("tenant timezone is invalid")
    try:
        zone = ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("tenant timezone is invalid") from None
    if zone.key != value:
        raise ValueError("tenant timezone is not canonical")


def _require_ready_default_warehouse(tenant_session: Session) -> None:
    """Enforce D14 setup before yielding any normal business transaction."""

    from app.models.warehouse import Warehouse

    defaults = tuple(
        tenant_session.execute(
            select(Warehouse.status, Warehouse.setup_state)
            .where(Warehouse.is_default.is_(True))
            .order_by(Warehouse.id.asc())
        ).all()
    )
    if defaults != (("active", "ready"),):
        raise TenantSetupRequired()


def require_tenant_business_http_runtime() -> TenantBusinessHttpRuntime:
    """Return only an explicitly installed, protocol-complete runtime."""

    runtime = current_app.extensions.get(
        TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION
    )
    if not isinstance(runtime, TenantBusinessHttpRuntime):
        raise TenantBusinessRuntimeUnavailable()
    return runtime


__all__ = [
    "TENANT_BUSINESS_HTTP_RUNTIME_EXTENSION",
    "SqlAlchemyTenantBusinessHttpRuntime",
    "TenantBusinessHttpRuntime",
    "TenantBusinessRequestScope",
    "TenantBusinessRuntimeUnavailable",
    "TenantSetupRequired",
    "require_tenant_business_http_runtime",
]
