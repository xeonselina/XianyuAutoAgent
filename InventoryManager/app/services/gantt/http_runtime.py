"""Fail-closed HTTP composition contract for SaaS Gantt reordering.

The legacy Flask application still owns a single Flask-SQLAlchemy session, so
an HTTP handler must not silently construct tenant authority from that global
state.  A composition root that has authenticated the opaque tenant session,
resolved and verified the tenant database route, and installed the current
Gantt proof authority provides this runtime explicitly.

Keeping the extension contract here makes the public route safe while the
remaining application endpoints are migrated: absence or shape mismatch is a
fixed service-unavailable result, never a fallback to the legacy
``SECRET_KEY`` signer.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timedelta
from typing import Callable, Iterator, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from flask import Request, current_app
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.services.gantt.reorder_service import GanttReorderService
from app.services.gantt.view_service import GanttRangeViewService
from app.services.tenant_business.http_runtime import (
    SqlAlchemyTenantBusinessHttpRuntime,
    TenantBusinessRequestScope,
    TenantBusinessRuntimeUnavailable,
)
from inventory_control.database import ControlDatabase
from inventory_control.domain.rbac import Capability
from inventory_control.proofs import (
    GanttPreviewProofAdapter,
    GanttPreviewProofError,
)
from inventory_control.routing import TenantDatabaseRouter
from inventory_control.tenant_http import (
    AuthContext,
    TenantHttpBoundary,
)


GANTT_SAAS_HTTP_RUNTIME_EXTENSION = "inventory_gantt_saas_http_runtime"


class GanttSaasHttpRuntimeUnavailable(RuntimeError):
    """No trusted SaaS composition is installed for the public route."""

    def __init__(self) -> None:
        super().__init__("GANTT_SAAS_RUNTIME_UNAVAILABLE")


class GanttPreviewTokenRequired(ValueError):
    """The authenticated execute request did not carry a preview proof."""

    def __init__(self) -> None:
        super().__init__("缺少预览令牌")


class GanttViewQueryInvalid(ValueError):
    """The normalized range view received an invalid bounded query."""


@runtime_checkable
class GanttSaasHttpRuntime(Protocol):
    """Authenticate, route, and execute one Gantt HTTP request.

    Implementations own the control transaction, opaque-session/CSRF/RBAC
    boundary, trusted tenant router, tenant database scope, and proof adapter.
    Request JSON supplies only the business decisions or proof token.
    """

    def analyze(self, *, flask_request: Request) -> Mapping[str, object]:
        ...

    def view(
        self,
        *,
        flask_request: Request,
        query: object,
    ) -> Mapping[str, object]:
        ...

    def preview(
        self,
        *,
        flask_request: Request,
        decisions: object,
    ) -> Mapping[str, object]:
        ...

    def execute(
        self,
        *,
        flask_request: Request,
        token: object,
    ) -> Mapping[str, object]:
        ...


class SqlAlchemyGanttSaasHttpRuntime:
    """Concrete control-authenticated, tenant-routed Gantt runtime.

    The runtime accepts no tenant selector, database URL, signing secret, or
    caller-supplied clock.  It authorizes the opaque browser session and CSRF
    proof against control-database UTC time, derives the trusted tenant
    context, obtains only its verified DML engine, and gives the scheduling
    service an independent SQLAlchemy session bound to that engine.
    """

    __slots__ = (
        "_proof_adapter",
        "_tenant_business_runtime",
    )

    def __init__(
        self,
        *,
        proof_adapter: GanttPreviewProofAdapter,
        control_database: ControlDatabase | None = None,
        tenant_http_boundary: TenantHttpBoundary | None = None,
        tenant_router_factory: Callable[
            [Session],
            AbstractContextManager[TenantDatabaseRouter[Engine]],
        ] | None = None,
        tenant_business_runtime: (
            SqlAlchemyTenantBusinessHttpRuntime | None
        ) = None,
    ) -> None:
        if not isinstance(proof_adapter, GanttPreviewProofAdapter):
            raise TypeError(
                "proof_adapter must be a GanttPreviewProofAdapter"
            )
        if tenant_business_runtime is not None:
            if not isinstance(
                tenant_business_runtime,
                SqlAlchemyTenantBusinessHttpRuntime,
            ):
                raise TypeError(
                    "tenant_business_runtime has an invalid type"
                )
            if any(
                value is not None
                for value in (
                    control_database,
                    tenant_http_boundary,
                    tenant_router_factory,
                )
            ):
                raise ValueError(
                    "shared runtime cannot be combined with raw dependencies"
                )
            shared_runtime = tenant_business_runtime
        else:
            if not isinstance(control_database, ControlDatabase):
                raise TypeError(
                    "control_database must be a ControlDatabase"
                )
            if not isinstance(tenant_http_boundary, TenantHttpBoundary):
                raise TypeError(
                    "tenant_http_boundary must be a TenantHttpBoundary"
                )
            if not callable(tenant_router_factory):
                raise TypeError(
                    "tenant_router_factory must be callable"
                )
            shared_runtime = SqlAlchemyTenantBusinessHttpRuntime(
                control_database=control_database,
                tenant_http_boundary=tenant_http_boundary,
                tenant_router_factory=tenant_router_factory,
            )
        self._proof_adapter = proof_adapter
        self._tenant_business_runtime = shared_runtime

    @property
    def tenant_business_runtime(self) -> SqlAlchemyTenantBusinessHttpRuntime:
        """Expose the exact shared runtime for composition-root publication."""

        return self._tenant_business_runtime

    def analyze(self, *, flask_request: Request) -> Mapping[str, object]:
        with self._request_scope(flask_request) as scope:
            try:
                today = self._proof_adapter.current_business_date(
                    auth_context=scope.auth_context
                )
            except GanttPreviewProofError:
                raise GanttSaasHttpRuntimeUnavailable() from None
            return GanttReorderService.analyze(
                today=today,
                tenant_session=scope.tenant_session,
            )

    def view(
        self,
        *,
        flask_request: Request,
        query: object,
    ) -> Mapping[str, object]:
        parsed_query: dict[str, object] | None = None

        def parse_query_after_authorize(_auth_context: AuthContext) -> None:
            nonlocal parsed_query
            parsed_query = _parse_view_query(query)

        try:
            with self._request_scope(
                flask_request,
                capability=Capability.RENTAL_READ,
                additional_capabilities=(Capability.CUSTOMER_PII_READ,),
                request_id_prefix="gantt-view",
                after_authorize=parse_query_after_authorize,
                passthrough_exceptions=(GanttViewQueryInvalid,),
            ) as scope:
                if parsed_query is None:
                    raise GanttSaasHttpRuntimeUnavailable()
                business_date = scope.database_now.astimezone(
                    ZoneInfo(scope.auth_context.tenant_timezone)
                ).date()
                start_date = parsed_query["start_date"] or business_date
                end_date = parsed_query["end_date"] or (
                    start_date + timedelta(days=15)
                )
                with scope.tenant_session.begin():
                    return GanttRangeViewService.build(
                        tenant_session=scope.tenant_session,
                        start_date=start_date,
                        end_date=end_date,
                        device_model_id=parsed_query["device_model_id"],
                        lifecycle_status=parsed_query["lifecycle_status"],
                        tenant_timezone=scope.auth_context.tenant_timezone,
                        database_now=scope.database_now,
                        request_id=scope.request_id,
                    )
        except GanttViewQueryInvalid:
            raise
        except (TenantBusinessRuntimeUnavailable, SQLAlchemyError):
            raise GanttSaasHttpRuntimeUnavailable() from None

    def preview(
        self,
        *,
        flask_request: Request,
        decisions: object,
    ) -> Mapping[str, object]:
        with self._request_scope(flask_request) as scope:
            try:
                return GanttReorderService.preview_saas(
                    decisions,
                    auth_context=scope.auth_context,
                    proof_adapter=self._proof_adapter,
                    tenant_session=scope.tenant_session,
                )
            except GanttPreviewProofError:
                raise GanttSaasHttpRuntimeUnavailable() from None

    def execute(
        self,
        *,
        flask_request: Request,
        token: object,
    ) -> Mapping[str, object]:
        def require_token_after_authorize(_auth_context: AuthContext) -> None:
            if not isinstance(token, str) or not token:
                raise GanttPreviewTokenRequired()

        with self._request_scope(
            flask_request,
            after_authorize=require_token_after_authorize,
            passthrough_exceptions=(GanttPreviewTokenRequired,),
        ) as scope:
            return GanttReorderService.execute_saas(
                token,
                auth_context=scope.auth_context,
                proof_adapter=self._proof_adapter,
                tenant_session=scope.tenant_session,
            )

    @contextmanager
    def _request_scope(
        self,
        flask_request: Request,
        *,
        capability: Capability = Capability.RENTAL_WRITE,
        additional_capabilities: tuple[Capability, ...] = (),
        request_id_prefix: str = "gantt-reorder",
        after_authorize: Callable[[AuthContext], None] | None = None,
        passthrough_exceptions: tuple[type[BaseException], ...] = (),
    ) -> Iterator[TenantBusinessRequestScope]:
        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=capability,
                additional_capabilities=additional_capabilities,
                request_id_prefix=request_id_prefix,
                after_authorize=after_authorize,
                passthrough_exceptions=passthrough_exceptions,
            ) as scope:
                yield scope
        except TenantBusinessRuntimeUnavailable:
            raise GanttSaasHttpRuntimeUnavailable() from None

    def __repr__(self) -> str:
        return "SqlAlchemyGanttSaasHttpRuntime(fail_closed=True)"


_GANTT_VIEW_LIFECYCLE_STATUSES = frozenset({
    "active",
    "sold",
    "decommissioned",
    "damaged",
    "retired",
})


def _parse_view_query(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise GanttViewQueryInvalid("甘特范围查询格式错误")
    start_raw = value.get("start_date")
    end_raw = value.get("end_date")
    if bool(start_raw) != bool(end_raw):
        raise GanttViewQueryInvalid("start_date 和 end_date 必须同时提供")

    start_date = end_date = None
    if start_raw and end_raw:
        try:
            start_date = datetime.strptime(
                str(start_raw), "%Y-%m-%d"
            ).date()
            end_date = datetime.strptime(str(end_raw), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            raise GanttViewQueryInvalid(
                "日期格式错误，请使用YYYY-MM-DD格式"
            ) from None
        if end_date < start_date:
            raise GanttViewQueryInvalid("结束日期不能早于开始日期")
        if (end_date - start_date).days + 1 > 62:
            raise GanttViewQueryInvalid("甘特范围不能超过62天")

    model_raw = value.get("device_model_id")
    device_model_id = None
    if model_raw not in (None, ""):
        if isinstance(model_raw, bool):
            raise GanttViewQueryInvalid("device_model_id 必须是正整数")
        try:
            device_model_id = int(model_raw)
        except (TypeError, ValueError, OverflowError):
            raise GanttViewQueryInvalid(
                "device_model_id 必须是正整数"
            ) from None
        if (
            device_model_id < 1
            or device_model_id > 2_147_483_647
            or str(device_model_id) != str(model_raw)
        ):
            raise GanttViewQueryInvalid("device_model_id 必须是正整数")

    lifecycle_raw = value.get("lifecycle_status")
    lifecycle_status = None
    if lifecycle_raw not in (None, ""):
        if not isinstance(lifecycle_raw, str):
            raise GanttViewQueryInvalid("lifecycle_status 无效")
        lifecycle_status = lifecycle_raw.strip()
        if lifecycle_status not in _GANTT_VIEW_LIFECYCLE_STATUSES:
            raise GanttViewQueryInvalid("lifecycle_status 无效")

    return {
        "start_date": start_date,
        "end_date": end_date,
        "device_model_id": device_model_id,
        "lifecycle_status": lifecycle_status,
    }


def require_gantt_saas_http_runtime() -> GanttSaasHttpRuntime:
    """Return only an explicitly installed, protocol-complete runtime."""

    runtime = current_app.extensions.get(
        GANTT_SAAS_HTTP_RUNTIME_EXTENSION
    )
    if not isinstance(runtime, GanttSaasHttpRuntime):
        raise GanttSaasHttpRuntimeUnavailable()
    return runtime


__all__ = [
    "GANTT_SAAS_HTTP_RUNTIME_EXTENSION",
    "GanttSaasHttpRuntime",
    "GanttSaasHttpRuntimeUnavailable",
    "GanttPreviewTokenRequired",
    "GanttViewQueryInvalid",
    "SqlAlchemyGanttSaasHttpRuntime",
    "require_gantt_saas_http_runtime",
]
