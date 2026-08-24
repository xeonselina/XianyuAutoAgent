"""Authenticated tenant HTTP boundary for local Xianyu snapshots and jobs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from flask import Request, current_app
from sqlalchemy.exc import SQLAlchemyError

from app.services.tenant_business import (
    TenantBusinessHttpRuntime,
    TenantBusinessRuntimeUnavailable,
)
from inventory_control.domain.rbac import Capability
from inventory_control.jobs import (
    ManualXianyuSyncSubmission,
    XianyuSyncJobCoordinator,
    XianyuSyncNotConfigured,
    XianyuSyncScheduleDenied,
    XianyuSyncSchedulingError,
)

from .query_service import (
    XianyuAlertNotFound,
    XianyuAlertQueryInputError,
    XianyuAlertSnapshotQueryService,
)


XIANYU_SYNC_HTTP_RUNTIME_EXTENSION = "inventory_xianyu_sync_http_runtime"


class XianyuSyncHttpError(RuntimeError):
    status_code = 503
    code = "XIANYU_SYNC_UNAVAILABLE"
    public_message = "闲鱼同步服务暂不可用"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class XianyuSyncHttpRuntimeUnavailable(XianyuSyncHttpError):
    pass


class XianyuSyncConfigurationRequired(XianyuSyncHttpError):
    status_code = 409
    code = "XIANYU_CONNECTION_REQUIRED"
    public_message = "请先配置可用的闲鱼连接"


class XianyuSyncRefreshRejected(XianyuSyncHttpError):
    status_code = 409
    code = "XIANYU_SYNC_REFRESH_REJECTED"
    public_message = "当前租户暂时不能刷新闲鱼订单"


class XianyuSyncRequestInvalid(XianyuSyncHttpError):
    status_code = 400
    code = "XIANYU_SYNC_REQUEST_INVALID"
    public_message = "请求参数无效"


class XianyuSyncAlertMissing(XianyuSyncHttpError):
    status_code = 404
    code = "XIANYU_ALERT_NOT_FOUND"
    public_message = "待处理订单不存在"


@runtime_checkable
class XianyuSyncHttpRuntime(Protocol):
    def get_alerts(
        self, *, flask_request: Request
    ) -> Mapping[str, object]: ...

    def refresh_alerts(
        self, *, flask_request: Request
    ) -> Mapping[str, object]: ...

    def ignore_alert(
        self,
        *,
        flask_request: Request,
        order_no: object,
        payload: object,
    ) -> Mapping[str, object]: ...


class SqlAlchemyXianyuSyncHttpRuntime:
    __slots__ = ("_tenant_business_runtime", "_job_coordinator")

    def __init__(
        self,
        *,
        tenant_business_runtime: TenantBusinessHttpRuntime,
        job_coordinator: XianyuSyncJobCoordinator,
    ) -> None:
        if not isinstance(tenant_business_runtime, TenantBusinessHttpRuntime):
            raise TypeError(
                "tenant_business_runtime must implement TenantBusinessHttpRuntime"
            )
        if not isinstance(job_coordinator, XianyuSyncJobCoordinator):
            raise TypeError("job_coordinator must be a XianyuSyncJobCoordinator")
        self._tenant_business_runtime = tenant_business_runtime
        self._job_coordinator = job_coordinator

    @property
    def tenant_business_runtime(self) -> TenantBusinessHttpRuntime:
        return self._tenant_business_runtime

    @property
    def job_coordinator(self) -> XianyuSyncJobCoordinator:
        return self._job_coordinator

    def get_alerts(self, *, flask_request: Request) -> Mapping[str, object]:
        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.XIANYU_SYNC,
                additional_capabilities=(Capability.CUSTOMER_PII_READ,),
                request_id_prefix="xianyu-alert-list",
            ) as scope:
                with scope.tenant_session.begin():
                    return XianyuAlertSnapshotQueryService(
                        scope.tenant_session
                    ).get_snapshot(database_now=scope.database_now)
        except TenantBusinessRuntimeUnavailable:
            raise XianyuSyncHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise XianyuSyncHttpRuntimeUnavailable() from None

    def refresh_alerts(
        self, *, flask_request: Request
    ) -> Mapping[str, object]:
        try:
            # Capture only non-secret authority and revision facts.  The tenant
            # session is closed before the coordinator opens its control-plane
            # transaction, and no provider call occurs on this request path.
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.XIANYU_SYNC,
                request_id_prefix="xianyu-alert-refresh",
            ) as scope:
                with scope.tenant_session.begin():
                    snapshot_revision = XianyuAlertSnapshotQueryService(
                        scope.tenant_session
                    ).get_snapshot_revision()
                tenant_id = scope.auth_context.tenant_id
                user_id = scope.auth_context.user_id
                request_id = scope.request_id
                database_now = scope.database_now

            submission = self._job_coordinator.enqueue_manual(
                tenant_uuid=tenant_id,
                requested_by_user_uuid=user_id,
                snapshot_revision=snapshot_revision,
                now=database_now,
                request_id=request_id,
                correlation_id=request_id,
            )
            return _submission_dto(submission)
        except XianyuSyncNotConfigured:
            raise XianyuSyncConfigurationRequired() from None
        except XianyuSyncScheduleDenied:
            raise XianyuSyncRefreshRejected() from None
        except XianyuSyncSchedulingError:
            raise XianyuSyncHttpRuntimeUnavailable() from None
        except TenantBusinessRuntimeUnavailable:
            raise XianyuSyncHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise XianyuSyncHttpRuntimeUnavailable() from None

    def ignore_alert(
        self,
        *,
        flask_request: Request,
        order_no: object,
        payload: object,
    ) -> Mapping[str, object]:
        parsed_order: str | None = None
        parsed_reason: str | None = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed_order, parsed_reason
            parsed_order = _text(order_no, maximum=50)
            if not isinstance(payload, Mapping):
                raise XianyuSyncRequestInvalid()
            parsed_reason = _text(payload.get("reason"), maximum=500)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.XIANYU_SYNC,
                additional_capabilities=(Capability.CUSTOMER_PII_READ,),
                request_id_prefix="xianyu-alert-ignore",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(XianyuSyncRequestInvalid,),
            ) as scope:
                if parsed_order is None or parsed_reason is None:
                    raise XianyuSyncHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    service = XianyuAlertSnapshotQueryService(
                        scope.tenant_session
                    )
                    service.ignore(
                        order_no=parsed_order,
                        reason=parsed_reason,
                        ignored_at=scope.database_now,
                    )
                    return service.get_snapshot(
                        database_now=scope.database_now
                    )
        except XianyuSyncRequestInvalid:
            raise
        except XianyuAlertNotFound:
            raise XianyuSyncAlertMissing() from None
        except XianyuAlertQueryInputError:
            raise XianyuSyncRequestInvalid() from None
        except TenantBusinessRuntimeUnavailable:
            raise XianyuSyncHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise XianyuSyncHttpRuntimeUnavailable() from None

    def __repr__(self) -> str:
        return "SqlAlchemyXianyuSyncHttpRuntime(fail_closed=True)"


def require_xianyu_sync_http_runtime() -> XianyuSyncHttpRuntime:
    runtime = current_app.extensions.get(XIANYU_SYNC_HTTP_RUNTIME_EXTENSION)
    if not isinstance(runtime, XianyuSyncHttpRuntime):
        raise XianyuSyncHttpRuntimeUnavailable()
    return runtime


def _submission_dto(
    submission: ManualXianyuSyncSubmission,
) -> dict[str, object]:
    return {
        "job_id": submission.job_uuid,
        "snapshot_revision": submission.snapshot_revision,
        "job_status": submission.job_status,
        "reused": submission.reused,
    }


def _text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise XianyuSyncRequestInvalid()
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise XianyuSyncRequestInvalid()
    return normalized


__all__ = [
    "XIANYU_SYNC_HTTP_RUNTIME_EXTENSION",
    "SqlAlchemyXianyuSyncHttpRuntime",
    "XianyuSyncAlertMissing",
    "XianyuSyncConfigurationRequired",
    "XianyuSyncHttpError",
    "XianyuSyncHttpRuntime",
    "XianyuSyncHttpRuntimeUnavailable",
    "XianyuSyncRefreshRejected",
    "XianyuSyncRequestInvalid",
    "require_xianyu_sync_http_runtime",
]
