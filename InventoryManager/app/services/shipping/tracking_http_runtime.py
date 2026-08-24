"""Trusted tenant HTTP runtime for historical SF tracking reads."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Protocol, Sequence
from uuid import UUID

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from app.services.tenant_business import (
    TenantBusinessHttpRuntime,
    TenantBusinessRuntimeUnavailable,
)
from inventory_control.crypto import RootKeyLoadError, SqlAlchemyRootKeyRegistry
from inventory_control.database import ControlDatabase, read_database_utc_value
from inventory_control.domain import Capability
from inventory_control.integrations import (
    HistoricalTrackingCredentialError,
    SfHistoricalTrackingCredentialFactory,
    SfTrackingQueryItem,
)
from inventory_control.tenant_http import TenantHttpBoundary, TenantHttpError

from .tracking_provider import (
    SfHistoricalTrackingDispatcher,
    SfTrackingProviderAdapter,
    TrackingProviderError,
)
from .tracking_query_service import (
    ShipmentTrackingQueryService,
    TrackingQueryError,
)


SF_TRACKING_HTTP_RUNTIME_EXTENSION = "inventory_sf_tracking_http_runtime"


class SfTrackingHttpRuntimeUnavailable(RuntimeError):
    code = "SF_TRACKING_RUNTIME_UNAVAILABLE"
    public_message = "顺丰轨迹服务暂时不可用"
    status_code = 503

    def __init__(self) -> None:
        super().__init__(self.public_message)


class SfTrackingRequestInvalid(RuntimeError):
    code = "SF_TRACKING_REQUEST_INVALID"
    public_message = "顺丰轨迹查询参数无效"
    status_code = 400

    def __init__(self) -> None:
        super().__init__(self.public_message)


class SfTrackingQueryRejected(RuntimeError):
    code = "SF_TRACKING_QUERY_REJECTED"
    public_message = "所选运单当前无法查询"
    status_code = 409

    def __init__(self) -> None:
        super().__init__(self.public_message)


class SfTrackingProviderUnavailable(RuntimeError):
    code = "SF_TRACKING_PROVIDER_UNAVAILABLE"
    public_message = "顺丰轨迹暂时不可用，请稍后重试"
    status_code = 502

    def __init__(self) -> None:
        super().__init__(self.public_message)


class SfTrackingHttpRuntime(Protocol):
    def list_shipments(
        self,
        *,
        flask_request,
        page_size: object,
        after_cursor: object,
    ) -> Mapping[str, object]: ...

    def query_shipment(
        self,
        *,
        flask_request,
        payload: object,
    ) -> Mapping[str, object]: ...

    def query_shipments(
        self,
        *,
        flask_request,
        payload: object,
    ) -> Mapping[str, object]: ...


class SqlAlchemySfTrackingHttpRuntime:
    """Authorize, plan in the tenant DB, resolve in control, then dispatch."""

    __slots__ = (
        "_control_database",
        "_tenant_http_boundary",
        "_tenant_business_runtime",
        "_root_key_directory",
        "_adapter",
    )

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        tenant_http_boundary: TenantHttpBoundary,
        tenant_business_runtime: TenantBusinessHttpRuntime,
        root_key_directory: str | os.PathLike[str],
        adapter: SfTrackingProviderAdapter,
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise TypeError("control_database must be a ControlDatabase")
        if not isinstance(tenant_http_boundary, TenantHttpBoundary):
            raise TypeError("tenant_http_boundary must be a TenantHttpBoundary")
        if not isinstance(tenant_business_runtime, TenantBusinessHttpRuntime):
            raise TypeError("tenant_business_runtime is invalid")
        root = os.fspath(root_key_directory)
        if not isinstance(root, str) or not Path(root).is_absolute():
            raise ValueError("root_key_directory must be absolute")
        if not callable(getattr(adapter, "query_routes", None)):
            raise TypeError("adapter must implement SfTrackingProviderAdapter")
        self._control_database = control_database
        self._tenant_http_boundary = tenant_http_boundary
        self._tenant_business_runtime = tenant_business_runtime
        self._root_key_directory = root
        self._adapter = adapter

    @property
    def control_database(self) -> ControlDatabase:
        return self._control_database

    @property
    def tenant_http_boundary(self) -> TenantHttpBoundary:
        return self._tenant_http_boundary

    @property
    def tenant_business_runtime(self) -> TenantBusinessHttpRuntime:
        return self._tenant_business_runtime

    def list_shipments(
        self,
        *,
        flask_request,
        page_size,
        after_cursor,
    ):
        parsed = None

        def parse_after_authorize(_auth) -> None:
            nonlocal parsed
            parsed = _parse_page(page_size, after_cursor)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.RENTAL_READ,
                request_id_prefix="sf-tracking-list",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(SfTrackingRequestInvalid,),
            ) as scope:
                if parsed is None:
                    raise SfTrackingHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    page = ShipmentTrackingQueryService(
                        scope.tenant_session
                    ).list_shipments(
                        page_size=parsed[0],
                        after_cursor=parsed[1],
                    )
            return {
                "items": [_summary_dto(item) for item in page.items],
                "next_cursor": page.next_cursor,
            }
        except (SfTrackingRequestInvalid, TenantHttpError):
            raise
        except TrackingQueryError:
            raise SfTrackingQueryRejected() from None
        except (TenantBusinessRuntimeUnavailable, SQLAlchemyError):
            raise SfTrackingHttpRuntimeUnavailable() from None

    def query_shipment(self, *, flask_request, payload):
        return self._query(
            flask_request=flask_request,
            payload=payload,
            single=True,
        )

    def query_shipments(self, *, flask_request, payload):
        return self._query(
            flask_request=flask_request,
            payload=payload,
            single=False,
        )

    def _query(self, *, flask_request, payload, single: bool):
        selected_ids = None

        def parse_after_authorize(_auth) -> None:
            nonlocal selected_ids
            selected_ids = _parse_shipment_ids(payload, single=single)

        requests = []
        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.RENTAL_READ,
                request_id_prefix=(
                    "sf-tracking-query-one"
                    if single
                    else "sf-tracking-query-batch"
                ),
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(SfTrackingRequestInvalid,),
            ) as scope:
                if selected_ids is None:
                    raise SfTrackingHttpRuntimeUnavailable()
                local_auth = scope.auth_context
                with scope.tenant_session.begin():
                    batches = ShipmentTrackingQueryService(
                        scope.tenant_session
                    ).plan_historical_batches(shipment_ids=selected_ids)

            with self._control_database.transaction() as control_session:
                now = read_database_utc_value(control_session)
                current_auth = self._tenant_http_boundary.authorize(
                    control_session,
                    flask_request,
                    capability=Capability.RENTAL_READ,
                    now=now,
                )
                _require_same_auth(local_auth, current_auth)
                key_ring = SqlAlchemyRootKeyRegistry(
                    session=control_session
                ).load(self._root_key_directory)
                factory = SfHistoricalTrackingCredentialFactory(
                    control_session
                )
                for batch in batches:
                    requests.append(
                        factory.prepare(
                            tenant_uuid=current_auth.tenant_id,
                            warehouse_uuid=batch.origin_warehouse_uuid,
                            integration_uuid=batch.integration_uuid,
                            provider_account_uuid=batch.provider_account_uuid,
                            integration_secret_revision_uuid=(
                                batch.integration_secret_revision_uuid
                            ),
                            provider_account_secret_revision_uuid=(
                                batch.provider_account_secret_revision_uuid
                            ),
                            binding_revision=batch.binding_revision,
                            phone_last4=batch.phone_last4,
                            items=tuple(
                                SfTrackingQueryItem(
                                    shipment_uuid=item.shipment_id,
                                    waybill_no=item.waybill_no,
                                )
                                for item in batch.shipments
                            ),
                            root_key_ring=key_ring,
                        )
                    )

            result_by_id = {}
            for provider_request in requests:
                for result in SfHistoricalTrackingDispatcher.dispatch(
                    request=provider_request,
                    adapter=self._adapter,
                ):
                    result_by_id[result.shipment_uuid] = result
            ordered = tuple(result_by_id[shipment_id] for shipment_id in selected_ids)
            if single:
                return _result_dto(ordered[0])
            return {"items": [_result_dto(item) for item in ordered]}
        except (SfTrackingRequestInvalid, TenantHttpError):
            raise
        except TrackingQueryError:
            raise SfTrackingQueryRejected() from None
        except TrackingProviderError:
            raise SfTrackingProviderUnavailable() from None
        except (
            HistoricalTrackingCredentialError,
            RootKeyLoadError,
            SQLAlchemyError,
            TenantBusinessRuntimeUnavailable,
        ):
            raise SfTrackingHttpRuntimeUnavailable() from None
        finally:
            for provider_request in requests:
                provider_request.discard_credentials()


def install_sf_tracking_http_runtime(
    app,
    runtime: SfTrackingHttpRuntime,
) -> None:
    if not _runtime_complete(runtime):
        raise TypeError("runtime must implement SfTrackingHttpRuntime")
    app.extensions[SF_TRACKING_HTTP_RUNTIME_EXTENSION] = runtime


def require_sf_tracking_http_runtime() -> SfTrackingHttpRuntime:
    runtime = current_app.extensions.get(SF_TRACKING_HTTP_RUNTIME_EXTENSION)
    if not _runtime_complete(runtime):
        raise SfTrackingHttpRuntimeUnavailable()
    return runtime


def _runtime_complete(runtime) -> bool:
    return runtime is not None and all(
        callable(getattr(runtime, method, None))
        for method in (
            "list_shipments",
            "query_shipment",
            "query_shipments",
        )
    )


def _parse_page(page_size, after_cursor) -> tuple[int, str | None]:
    if page_size in (None, ""):
        selected_size = 50
    elif (
        isinstance(page_size, str)
        and page_size.isascii()
        and page_size.isdigit()
    ):
        selected_size = int(page_size)
    elif isinstance(page_size, int) and not isinstance(page_size, bool):
        selected_size = page_size
    else:
        raise SfTrackingRequestInvalid()
    if selected_size < 1 or selected_size > 100:
        raise SfTrackingRequestInvalid()
    if after_cursor is not None and (
        not isinstance(after_cursor, str)
        or not after_cursor
        or len(after_cursor) > 512
    ):
        raise SfTrackingRequestInvalid()
    return selected_size, after_cursor


def _parse_shipment_ids(payload, *, single: bool) -> tuple[str, ...]:
    if not isinstance(payload, Mapping):
        raise SfTrackingRequestInvalid()
    expected_key = "shipment_id" if single else "shipment_ids"
    if set(payload) != {expected_key}:
        raise SfTrackingRequestInvalid()
    raw = payload[expected_key]
    values = (raw,) if single else raw
    if (
        isinstance(values, (str, bytes))
        or not isinstance(values, Sequence)
        or not values
        or len(values) > 500
    ):
        raise SfTrackingRequestInvalid()
    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        try:
            shipment_id = str(UUID(str(value)))
        except (AttributeError, TypeError, ValueError):
            raise SfTrackingRequestInvalid() from None
        if shipment_id not in seen:
            seen.add(shipment_id)
            selected.append(shipment_id)
    return tuple(selected)


def _require_same_auth(first, second) -> None:
    if (
        first.tenant_id != second.tenant_id
        or first.user_id != second.user_id
        or first.session_id != second.session_id
        or first.role is not second.role
        or first.effective_gate is not second.effective_gate
        or first.tenant_access_version != second.tenant_access_version
    ):
        raise SfTrackingHttpRuntimeUnavailable()


def _summary_dto(item) -> dict[str, object]:
    return {
        "shipment_id": item.shipment_id,
        "rental_id": item.rental_id,
        "waybill_no": item.waybill_no,
        "shipment_status": item.shipment_status,
        "origin_warehouse_uuid": item.origin_warehouse_uuid,
        "submitted_at": item.submitted_at.isoformat(),
    }


def _result_dto(item) -> dict[str, object]:
    return {
        "shipment_id": item.shipment_uuid,
        "waybill_no": item.waybill_no,
        "found": item.found,
        "status_code": item.status_code,
        "events": [
            {
                "occurred_at": event.occurred_at.isoformat(),
                "status_code": event.status_code,
                "summary": event.summary,
            }
            for event in item.events
        ],
        "last_update": (
            item.last_update.isoformat()
            if item.last_update is not None
            else None
        ),
    }


__all__ = [
    "SF_TRACKING_HTTP_RUNTIME_EXTENSION",
    "SfTrackingHttpRuntime",
    "SfTrackingHttpRuntimeUnavailable",
    "SfTrackingProviderUnavailable",
    "SfTrackingQueryRejected",
    "SfTrackingRequestInvalid",
    "SqlAlchemySfTrackingHttpRuntime",
    "install_sf_tracking_http_runtime",
    "require_sf_tracking_http_runtime",
]
