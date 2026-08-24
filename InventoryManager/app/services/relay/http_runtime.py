"""Fail-closed tenant runtime for relay-management read surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from flask import Request, current_app
from sqlalchemy.exc import SQLAlchemyError

from app.services.relay.relay_case_service import (
    ALL_STATUSES,
    OPEN_STATUSES,
    RelayCaseService,
)
from app.services.relay.mutation_service import (
    RelayManualMutationError,
    RelayManualMutationInvalid,
    RelayManualMutationPersistenceError,
    RelayManualMutationService,
    RelayStatusMutationError,
    RelayStatusMutationInvalid,
    RelayStatusMutationPersistenceError,
    RelayStatusMutationService,
)
from app.services.tenant_business import (
    TenantBusinessHttpRuntime,
    TenantBusinessRuntimeUnavailable,
)
from inventory_control.domain.rbac import Capability


RELAY_SAAS_HTTP_RUNTIME_EXTENSION = "inventory_relay_saas_http_runtime"


class RelaySaasHttpRuntimeUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("RELAY_SAAS_RUNTIME_UNAVAILABLE")


class RelayQueryInvalid(ValueError):
    public_message = "接力列表参数无效"

    def __init__(self) -> None:
        super().__init__(self.public_message)


@runtime_checkable
class RelaySaasHttpRuntime(Protocol):
    def list_cases(
        self,
        *,
        flask_request: Request,
        query: object,
    ) -> Mapping[str, object]: ...

    def list_manual_options(
        self,
        *,
        flask_request: Request,
    ) -> Mapping[str, object]: ...

    def create_manual_case(
        self,
        *,
        flask_request: Request,
        payload: object,
    ) -> Mapping[str, object]: ...

    def update_case(
        self,
        *,
        flask_request: Request,
        predecessor_id: object,
        successor_id: object,
        payload: object,
    ) -> Mapping[str, object]: ...


class SqlAlchemyRelaySaasHttpRuntime:
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

    @property
    def tenant_business_runtime(self) -> TenantBusinessHttpRuntime:
        return self._tenant_business_runtime

    def list_cases(self, *, flask_request, query):
        parsed = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed
            parsed = _parse_list_query(query)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.RENTAL_READ,
                additional_capabilities=(
                    Capability.RELAY_WRITE,
                    Capability.INVENTORY_READ,
                    Capability.CUSTOMER_PII_READ,
                ),
                request_id_prefix="relay-list",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(RelayQueryInvalid,),
            ) as scope:
                if parsed is None:
                    raise RelaySaasHttpRuntimeUnavailable()
                business_date = _business_date(scope)
                with scope.tenant_session.begin():
                    return RelayCaseService.list_cases(
                        tenant_session=scope.tenant_session,
                        tenant_timezone=scope.auth_context.tenant_timezone,
                        today=business_date,
                        **parsed,
                    )
        except RelayQueryInvalid:
            raise
        except TenantBusinessRuntimeUnavailable:
            raise RelaySaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise RelaySaasHttpRuntimeUnavailable() from None

    def list_manual_options(self, *, flask_request):
        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.RENTAL_READ,
                additional_capabilities=(
                    Capability.RELAY_WRITE,
                    Capability.INVENTORY_READ,
                    Capability.CUSTOMER_PII_READ,
                ),
                request_id_prefix="relay-manual-options",
            ) as scope:
                with scope.tenant_session.begin():
                    return RelayCaseService.list_manual_options(
                        tenant_session=scope.tenant_session
                    )
        except TenantBusinessRuntimeUnavailable:
            raise RelaySaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise RelaySaasHttpRuntimeUnavailable() from None

    def create_manual_case(self, *, flask_request, payload):
        parsed_device_id: int | None = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed_device_id
            parsed_device_id = _manual_device_id(payload)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.RELAY_WRITE,
                additional_capabilities=(
                    Capability.RENTAL_WRITE,
                    Capability.INVENTORY_WRITE,
                ),
                request_id_prefix="relay-manual-create",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(RelayManualMutationError,),
            ) as scope:
                if parsed_device_id is None:
                    raise RelaySaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    result = RelayManualMutationService.create(
                        tenant_session=scope.tenant_session,
                        device_id=parsed_device_id,
                        database_now=scope.database_now,
                        actor_id=scope.auth_context.user_id,
                        operation_key=scope.request_id,
                    )
                    return {
                        **_case_payload(result.relay_case),
                        "accessory_chain": result.accessory_chain,
                    }
        except RelayManualMutationPersistenceError:
            raise RelaySaasHttpRuntimeUnavailable() from None
        except RelayManualMutationError:
            raise
        except TenantBusinessRuntimeUnavailable:
            raise RelaySaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise RelaySaasHttpRuntimeUnavailable() from None

    def update_case(
        self,
        *,
        flask_request,
        predecessor_id,
        successor_id,
        payload,
    ):
        parsed = None

        def parse_after_authorize(_auth_context) -> None:
            nonlocal parsed
            parsed = _status_mutation_input(
                predecessor_id=predecessor_id,
                successor_id=successor_id,
                payload=payload,
            )

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.RELAY_WRITE,
                additional_capabilities=(
                    Capability.RENTAL_WRITE,
                    Capability.INVENTORY_WRITE,
                ),
                request_id_prefix="relay-status-update",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(RelayStatusMutationError,),
            ) as scope:
                if parsed is None:
                    raise RelaySaasHttpRuntimeUnavailable()
                with scope.tenant_session.begin():
                    result = RelayStatusMutationService.update(
                        tenant_session=scope.tenant_session,
                        database_now=scope.database_now,
                        actor_id=scope.auth_context.user_id,
                        operation_key=scope.request_id,
                        tenant_timezone=scope.auth_context.tenant_timezone,
                        **parsed,
                    )
                    return {
                        **_case_payload(result.relay_case),
                        "xianyu_sync": {
                            "attempted": False,
                            "success": False,
                            "message": "",
                        },
                        "accessory_chain": result.accessory_chain,
                    }
        except RelayStatusMutationPersistenceError:
            raise RelaySaasHttpRuntimeUnavailable() from None
        except RelayStatusMutationError:
            raise
        except TenantBusinessRuntimeUnavailable:
            raise RelaySaasHttpRuntimeUnavailable() from None
        except SQLAlchemyError:
            raise RelaySaasHttpRuntimeUnavailable() from None

    def __repr__(self) -> str:
        return "SqlAlchemyRelaySaasHttpRuntime(fail_closed=True)"


def require_relay_saas_http_runtime() -> RelaySaasHttpRuntime:
    runtime = current_app.extensions.get(RELAY_SAAS_HTTP_RUNTIME_EXTENSION)
    if not isinstance(runtime, RelaySaasHttpRuntime):
        raise RelaySaasHttpRuntimeUnavailable()
    return runtime


def _parse_list_query(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise RelayQueryInvalid()
    raw_statuses = (
        value.getlist("statuses")
        if callable(getattr(value, "getlist", None))
        else [value.get("statuses")]
    )
    statuses: list[str] = []
    for raw in raw_statuses:
        if raw in (None, ""):
            continue
        if not isinstance(raw, str):
            raise RelayQueryInvalid()
        statuses.extend(
            item.strip() for item in raw.split(",") if item.strip()
        )
    if not statuses:
        statuses = list(OPEN_STATUSES)
    if set(statuses) - set(ALL_STATUSES):
        raise RelayQueryInvalid()
    statuses = list(dict.fromkeys(statuses))
    return {
        "statuses": statuses,
        "ship_date_from": _optional_date(value.get("ship_date_from")),
        "ship_date_to": _optional_date(value.get("ship_date_to")),
        "page": _positive_integer(value.get("page"), default=1),
        "per_page": _positive_integer(
            value.get("per_page"), default=50, maximum=100
        ),
    }


def _optional_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise RelayQueryInvalid()
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise RelayQueryInvalid() from None


def _positive_integer(
    value: object,
    *,
    default: int,
    maximum: int | None = None,
) -> int:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise RelayQueryInvalid()
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise RelayQueryInvalid() from None
    if parsed < 1 or (maximum is not None and parsed > maximum):
        raise RelayQueryInvalid()
    return parsed


def _business_date(scope) -> date:
    return scope.database_now.astimezone(
        ZoneInfo(scope.auth_context.tenant_timezone)
    ).date()


def _manual_device_id(payload: object) -> int:
    if not isinstance(payload, Mapping):
        raise RelayManualMutationInvalid()
    value = payload.get("device_id")
    if isinstance(value, bool):
        raise RelayManualMutationInvalid()
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise RelayManualMutationInvalid() from None
    if parsed <= 0:
        raise RelayManualMutationInvalid()
    return parsed


def _case_payload(relay_case) -> dict[str, object]:
    return {
        "case_id": relay_case.id,
        "predecessor_rental_id": relay_case.predecessor_rental_id,
        "successor_rental_id": relay_case.successor_rental_id,
        "status": relay_case.status,
        "sf_tracking_number": relay_case.sf_tracking_number,
        "accessory_note": relay_case.accessory_note,
        "accessory_note_updated_at": (
            relay_case.accessory_note_updated_at.isoformat()
            if relay_case.accessory_note_updated_at else None
        ),
        "tracking": RelayCaseService._tracking(relay_case),
        "notified_at": (
            relay_case.notified_at.isoformat()
            if relay_case.notified_at else None
        ),
        "agreed_at": (
            relay_case.agreed_at.isoformat()
            if relay_case.agreed_at else None
        ),
        "shipped_at": (
            relay_case.shipped_at.isoformat()
            if relay_case.shipped_at else None
        ),
        "completed_at": (
            relay_case.completed_at.isoformat()
            if relay_case.completed_at else None
        ),
    }


def _status_mutation_input(
    *,
    predecessor_id: object,
    successor_id: object,
    payload: object,
) -> dict[str, object]:
    try:
        parsed_predecessor = int(predecessor_id)
        parsed_successor = int(successor_id)
    except (TypeError, ValueError, OverflowError):
        raise RelayStatusMutationInvalid() from None
    if (
        isinstance(predecessor_id, bool)
        or isinstance(successor_id, bool)
        or parsed_predecessor <= 0
        or parsed_successor <= 0
        or parsed_predecessor == parsed_successor
        or not isinstance(payload, Mapping)
    ):
        raise RelayStatusMutationInvalid()
    status = payload.get("status")
    if not isinstance(status, str) or status not in ALL_STATUSES:
        raise RelayStatusMutationInvalid()
    note_provided = "accessory_note" in payload
    raw_note = payload.get("accessory_note")
    if note_provided and raw_note is not None and not isinstance(raw_note, str):
        raise RelayStatusMutationInvalid()
    note = raw_note.strip() if isinstance(raw_note, str) else None
    if note == "":
        note = None
    if note is not None and len(note) > 500:
        raise RelayStatusMutationInvalid()
    return {
        "predecessor_id": parsed_predecessor,
        "successor_id": parsed_successor,
        "status": status,
        "accessory_note_provided": note_provided,
        "accessory_note": note,
    }


__all__ = [
    "RELAY_SAAS_HTTP_RUNTIME_EXTENSION",
    "RelayQueryInvalid",
    "RelayManualMutationError",
    "RelaySaasHttpRuntime",
    "RelaySaasHttpRuntimeUnavailable",
    "SqlAlchemyRelaySaasHttpRuntime",
    "require_relay_saas_http_runtime",
]
