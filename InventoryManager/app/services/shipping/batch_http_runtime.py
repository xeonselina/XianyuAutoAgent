"""Trusted tenant HTTP producer for durable SF waybill intents."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Mapping, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.device import Device
from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding
from app.models.shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
)
from app.models.warehouse import Warehouse, WarehouseProviderBinding
from app.services.shipping.sf_waybill_intent import (
    SfWaybillIntentError,
    SfWaybillIntentSignal,
    SqlAlchemySfWaybillIntentEnqueuer,
)
from app.services.shipping_execution_service import (
    ShippingExecutionError,
    ShippingExecutionService,
    ShippingJobProvenance,
)
from app.services.tenant_business import (
    TenantBusinessHttpRuntime,
    TenantBusinessRuntimeUnavailable,
)
from inventory_control import ControlDatabase
from inventory_control.domain import Capability
from inventory_control.integrations import (
    ProviderContextError,
    SfProviderContextResolver,
    SfProviderExecutionContext,
)
from inventory_control.tenant_http import TenantHttpBoundary, TenantHttpError


SF_BATCH_SHIPPING_HTTP_RUNTIME_EXTENSION = (
    "inventory_sf_batch_shipping_http_runtime"
)
_MAX_BATCH_SIZE = 100
_EXPRESS_TYPE_IDS = frozenset({1, 2, 263})


class SfBatchShippingHttpError(RuntimeError):
    code = "SF_BATCH_SHIPPING_FAILED"
    public_message = "批量发货请求失败"
    status_code = 409

    def __init__(self) -> None:
        super().__init__(self.public_message)


class SfBatchShippingRequestInvalid(SfBatchShippingHttpError):
    code = "SF_BATCH_SHIPPING_REQUEST_INVALID"
    public_message = "批量发货参数无效"
    status_code = 400


class SfBatchShippingRejected(SfBatchShippingHttpError):
    code = "SF_BATCH_SHIPPING_REJECTED"
    public_message = "所选租赁当前无法预约发货"
    status_code = 409


class SfBatchShippingHttpRuntimeUnavailable(SfBatchShippingHttpError):
    code = "SF_BATCH_SHIPPING_RUNTIME_UNAVAILABLE"
    public_message = "租户发货服务尚未就绪"
    status_code = 503


class SfBatchShippingHttpRuntime(Protocol):
    def schedule_shipments(
        self,
        *,
        flask_request,
        payload: object,
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class _BatchRequest:
    request_uuid: str
    rental_ids: tuple[int, ...]
    scheduled_dispatch_at: datetime


@dataclass(frozen=True, slots=True)
class _ShipmentPlan:
    rental_id: int
    device_id: int
    shipment_uuid: str
    job_uuid: str
    receiver_snapshot: Mapping[str, str]
    express_type_id: int
    scheduled_dispatch_at: datetime
    warehouse_uuid: str
    provider_account_uuid: str
    binding_revision: int
    provider_context: SfProviderExecutionContext | None = None


class SqlAlchemySfBatchShippingHttpRuntime:
    """Authorize, snapshot tenant facts, resolve control facts, then persist."""

    __slots__ = (
        "_control_database",
        "_tenant_http_boundary",
        "_tenant_business_runtime",
        "_enqueuer",
    )

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        tenant_http_boundary: TenantHttpBoundary,
        tenant_business_runtime: TenantBusinessHttpRuntime,
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise TypeError("control_database must be a ControlDatabase")
        if not isinstance(tenant_http_boundary, TenantHttpBoundary):
            raise TypeError("tenant_http_boundary must be a TenantHttpBoundary")
        if not isinstance(tenant_business_runtime, TenantBusinessHttpRuntime):
            raise TypeError("tenant_business_runtime is invalid")
        self._control_database = control_database
        self._tenant_http_boundary = tenant_http_boundary
        self._tenant_business_runtime = tenant_business_runtime
        self._enqueuer = SqlAlchemySfWaybillIntentEnqueuer(
            control_database=control_database
        )

    @property
    def control_database(self) -> ControlDatabase:
        return self._control_database

    @property
    def tenant_http_boundary(self) -> TenantHttpBoundary:
        return self._tenant_http_boundary

    @property
    def tenant_business_runtime(self) -> TenantBusinessHttpRuntime:
        return self._tenant_business_runtime

    def schedule_shipments(self, *, flask_request, payload):
        parsed = None

        def parse_after_authorize(_auth) -> None:
            nonlocal parsed
            parsed = _parse_batch_request(payload)

        try:
            with self._tenant_business_runtime.tenant_session(
                flask_request=flask_request,
                capability=Capability.RENTAL_SHIP,
                additional_capabilities=(Capability.CUSTOMER_PII_READ,),
                request_id_prefix="sf-batch-schedule",
                after_authorize=parse_after_authorize,
                passthrough_exceptions=(SfBatchShippingRequestInvalid,),
            ) as scope:
                if parsed is None:
                    raise SfBatchShippingHttpRuntimeUnavailable()
                auth = scope.auth_context
                stable_request_id = f"sf-batch:{parsed.request_uuid}"
                provenance_by_rental = {
                    rental_id: ShippingJobProvenance(
                        job_uuid=_job_uuid(parsed.request_uuid, rental_id),
                        tenant_access_version=auth.tenant_access_version,
                        requested_by_user_uuid=auth.user_id,
                        request_id=stable_request_id,
                        correlation_id=parsed.request_uuid,
                    )
                    for rental_id in parsed.rental_ids
                }
                with scope.tenant_session.begin():
                    plans = _load_tenant_plans(
                        scope.tenant_session,
                        parsed=parsed,
                        tenant_uuid=auth.tenant_id,
                        provenance_by_rental=provenance_by_rental,
                    )

                unresolved = tuple(
                    plan for plan in plans if plan.provider_context is None
                )
                if unresolved:
                    with self._control_database.transaction() as control_session:
                        resolver = SfProviderContextResolver(control_session)
                        contexts = {
                            plan.rental_id: resolver.resolve_current(
                                tenant_uuid=auth.tenant_id,
                                warehouse_uuid=plan.warehouse_uuid,
                                provider_account_uuid=(
                                    plan.provider_account_uuid
                                ),
                                binding_revision=plan.binding_revision,
                            )
                            for plan in unresolved
                        }
                    plans = tuple(
                        replace(
                            plan,
                            provider_context=(
                                plan.provider_context
                                or contexts[plan.rental_id]
                            ),
                        )
                        for plan in plans
                    )

                signals = []
                statuses = {}
                with scope.tenant_session.begin():
                    service = ShippingExecutionService(scope.tenant_session)
                    for plan in plans:
                        context = plan.provider_context
                        if context is None:
                            raise SfBatchShippingHttpRuntimeUnavailable()
                        shipment = service.prepare_shipment(
                            shipment_uuid=plan.shipment_uuid,
                            rental_id=plan.rental_id,
                            device_id=plan.device_id,
                            provider_context=context,
                            receiver_snapshot=plan.receiver_snapshot,
                            express_type_id=plan.express_type_id,
                            scheduled_dispatch_at=(
                                plan.scheduled_dispatch_at.replace(
                                    tzinfo=timezone.utc
                                )
                            ),
                        )
                        provenance = provenance_by_rental[plan.rental_id]
                        attempt = service.prepare_provider_attempt(
                            shipment_id=shipment.shipment_id,
                            operation="create_waybill",
                            idempotency_key=(
                                f"sf-create-intent:{shipment.shipment_id}"
                            ),
                            job_provenance=provenance,
                        )
                        signal = SfWaybillIntentSignal(
                            tenant_uuid=auth.tenant_id,
                            tenant_access_version=auth.tenant_access_version,
                            job_uuid=provenance.job_uuid,
                            shipment_uuid=shipment.shipment_id,
                            attempt_uuid=attempt.attempt_id,
                            requested_by_user_uuid=auth.user_id,
                            request_id=stable_request_id,
                            correlation_id=parsed.request_uuid,
                        )
                        signals.append(signal)
                        statuses[plan.rental_id] = (
                            shipment.status,
                            attempt.status,
                        )

                enqueued = self._enqueue_and_acknowledge(
                    tenant_session=scope.tenant_session,
                    signals=tuple(signals),
                    available_at=scope.database_now,
                )
                return {
                    "request_uuid": parsed.request_uuid,
                    "scheduled_time": _iso_utc(
                        parsed.scheduled_dispatch_at
                    ),
                    "accepted_count": len(signals),
                    "items": [
                        {
                            "rental_id": plan.rental_id,
                            "shipment_uuid": signal.shipment_uuid,
                            "attempt_uuid": signal.attempt_uuid,
                            "job_uuid": signal.job_uuid,
                            "shipment_status": statuses[plan.rental_id][0],
                            "attempt_status": statuses[plan.rental_id][1],
                            "job_enqueued": signal.job_uuid in enqueued,
                        }
                        for plan, signal in zip(plans, signals, strict=True)
                    ],
                }
        except (SfBatchShippingHttpError, TenantHttpError):
            raise
        except (
            ProviderContextError,
            ShippingExecutionError,
        ):
            raise SfBatchShippingRejected() from None
        except (
            SQLAlchemyError,
            TenantBusinessRuntimeUnavailable,
        ):
            raise SfBatchShippingHttpRuntimeUnavailable() from None
        except Exception:
            raise SfBatchShippingHttpRuntimeUnavailable() from None

    def _enqueue_and_acknowledge(
        self,
        *,
        tenant_session: Session,
        signals: tuple[SfWaybillIntentSignal, ...],
        available_at: datetime,
    ) -> frozenset[str]:
        acknowledged = set()
        for signal in signals:
            try:
                queued = self._enqueuer.enqueue(
                    signal=signal,
                    available_at=available_at,
                )
                if queued.id != signal.job_uuid:
                    continue
                with tenant_session.begin():
                    ShippingExecutionService(
                        tenant_session
                    ).acknowledge_provider_job_enqueued(
                        attempt_id=signal.attempt_uuid,
                        shipment_id=signal.shipment_uuid,
                        provenance=ShippingJobProvenance(
                            job_uuid=signal.job_uuid,
                            tenant_access_version=(
                                signal.tenant_access_version
                            ),
                            requested_by_user_uuid=(
                                signal.requested_by_user_uuid
                            ),
                            request_id=signal.request_id,
                            correlation_id=signal.correlation_id,
                        ),
                        enqueued_at=_aware_utc(available_at).replace(
                            tzinfo=None
                        ),
                    )
                acknowledged.add(signal.job_uuid)
            except (SfWaybillIntentError, ShippingExecutionError, SQLAlchemyError):
                if tenant_session.in_transaction():
                    tenant_session.rollback()
                continue
            except Exception:
                if tenant_session.in_transaction():
                    tenant_session.rollback()
                continue
        return frozenset(acknowledged)


def install_sf_batch_shipping_http_runtime(
    app,
    runtime: SfBatchShippingHttpRuntime,
) -> None:
    if not _runtime_complete(runtime):
        raise TypeError("runtime must implement SfBatchShippingHttpRuntime")
    app.extensions[SF_BATCH_SHIPPING_HTTP_RUNTIME_EXTENSION] = runtime


def require_sf_batch_shipping_http_runtime() -> SfBatchShippingHttpRuntime:
    runtime = current_app.extensions.get(
        SF_BATCH_SHIPPING_HTTP_RUNTIME_EXTENSION
    )
    if not _runtime_complete(runtime):
        raise SfBatchShippingHttpRuntimeUnavailable()
    return runtime


def _runtime_complete(runtime) -> bool:
    return callable(getattr(runtime, "schedule_shipments", None))


def _parse_batch_request(payload: object) -> _BatchRequest:
    if not isinstance(payload, dict) or set(payload) != {
        "request_uuid",
        "rental_ids",
        "scheduled_time",
    }:
        raise SfBatchShippingRequestInvalid()
    try:
        request_uuid = _uuid(payload["request_uuid"])
        values = payload["rental_ids"]
        if (
            not isinstance(values, list)
            or not 1 <= len(values) <= _MAX_BATCH_SIZE
        ):
            raise ValueError
        rental_ids = tuple(dict.fromkeys(_positive(value) for value in values))
        scheduled = _parse_scheduled_time(payload["scheduled_time"])
    except (TypeError, ValueError):
        raise SfBatchShippingRequestInvalid() from None
    return _BatchRequest(
        request_uuid=request_uuid,
        rental_ids=rental_ids,
        scheduled_dispatch_at=scheduled.replace(tzinfo=None),
    )


def _load_tenant_plans(
    session: Session,
    *,
    parsed: _BatchRequest,
    tenant_uuid: str,
    provenance_by_rental: Mapping[int, ShippingJobProvenance],
) -> tuple[_ShipmentPlan, ...]:
    rentals = {
        rental.id: rental
        for rental in session.scalars(
            sa.select(Rental).where(Rental.id.in_(parsed.rental_ids))
        )
    }
    if set(rentals) != set(parsed.rental_ids):
        raise SfBatchShippingRejected()
    shipment_ids = {
        rental_id: _shipment_uuid(parsed.request_uuid, rental_id)
        for rental_id in parsed.rental_ids
    }
    existing_shipments = {
        shipment.id: shipment
        for shipment in session.scalars(
            sa.select(OutboundShipment).where(
                OutboundShipment.id.in_(tuple(shipment_ids.values()))
            )
        )
    }
    existing_attempts = {
        attempt.shipment_id: attempt
        for attempt in session.scalars(
            sa.select(ProviderOperationAttempt).where(
                ProviderOperationAttempt.shipment_id.in_(
                    tuple(existing_shipments)
                ),
                ProviderOperationAttempt.operation == "create_waybill",
            )
        )
        if attempt.idempotency_key
        == f"sf-create-intent:{attempt.shipment_id}"
    }
    successor_ids = frozenset(
        session.scalars(
            sa.select(RentalRelayBinding.successor_rental_id).where(
                RentalRelayBinding.successor_rental_id.in_(parsed.rental_ids)
            )
        )
    )
    new_ids = tuple(
        rental_id
        for rental_id in parsed.rental_ids
        if shipment_ids[rental_id] not in existing_shipments
    )
    current_rows = {
        rental.id: (rental, device, warehouse, binding)
        for rental, device, warehouse, binding in session.execute(
            sa.select(Rental, Device, Warehouse, WarehouseProviderBinding)
            .join(Device, Device.id == Rental.device_id)
            .join(Warehouse, Warehouse.id == Device.warehouse_id)
            .outerjoin(
                WarehouseProviderBinding,
                sa.and_(
                    WarehouseProviderBinding.warehouse_id == Warehouse.id,
                    WarehouseProviderBinding.provider == "sf",
                ),
            )
            .where(Rental.id.in_(new_ids))
        )
    }
    plans = []
    for rental_id in parsed.rental_ids:
        rental = rentals[rental_id]
        shipment_uuid = shipment_ids[rental_id]
        provenance = provenance_by_rental[rental_id]
        existing = existing_shipments.get(shipment_uuid)
        if existing is not None:
            plans.append(
                _replay_plan(
                    rental=rental,
                    shipment=existing,
                    attempt=existing_attempts.get(existing.id),
                    parsed=parsed,
                    provenance=provenance,
                    tenant_uuid=tenant_uuid,
                )
            )
            continue
        row = current_rows.get(rental_id)
        if row is None:
            raise SfBatchShippingRejected()
        selected_rental, device, warehouse, binding = row
        if (
            selected_rental.parent_rental_id is not None
            or selected_rental.id in successor_ids
            or selected_rental.status != "not_shipped"
            or selected_rental.ship_out_tracking_no is not None
            or device.is_accessory is True
            or warehouse.status != "active"
            or warehouse.setup_state != "ready"
            or binding is None
            or binding.status != "active"
            or binding.provider_account_uuid is None
            or binding.binding_revision < 1
            or binding.verified_at is None
            or selected_rental.express_type_id not in _EXPRESS_TYPE_IDS
        ):
            raise SfBatchShippingRejected()
        plans.append(
            _ShipmentPlan(
                rental_id=rental_id,
                device_id=device.id,
                shipment_uuid=shipment_uuid,
                job_uuid=provenance.job_uuid,
                receiver_snapshot=_receiver_snapshot(selected_rental),
                express_type_id=selected_rental.express_type_id,
                scheduled_dispatch_at=parsed.scheduled_dispatch_at,
                warehouse_uuid=warehouse.warehouse_uuid,
                provider_account_uuid=binding.provider_account_uuid,
                binding_revision=binding.binding_revision,
            )
        )
    return tuple(plans)


def _replay_plan(
    *,
    rental: Rental,
    shipment: OutboundShipment,
    attempt: ProviderOperationAttempt | None,
    parsed: _BatchRequest,
    provenance: ShippingJobProvenance,
    tenant_uuid: str,
) -> _ShipmentPlan:
    if (
        shipment.provider != "sf"
        or shipment.rental_id != rental.id
        or shipment.scheduled_dispatch_at != parsed.scheduled_dispatch_at
        or attempt is None
        or attempt.operation != "create_waybill"
        or attempt.background_job_uuid != provenance.job_uuid
        or attempt.tenant_access_version != provenance.tenant_access_version
        or attempt.requested_by_user_uuid
        != provenance.requested_by_user_uuid
        or attempt.request_id != provenance.request_id
        or attempt.correlation_id != provenance.correlation_id
    ):
        raise SfBatchShippingRejected()
    replay_claim = str(uuid5(NAMESPACE_URL, f"sf-replay:{shipment.id}"))
    context = SfProviderExecutionContext(
        tenant_uuid=tenant_uuid,
        warehouse_uuid=shipment.origin_warehouse_uuid,
        provider_account_uuid=shipment.provider_account_uuid,
        integration_uuid=shipment.integration_uuid,
        integration_secret_revision_uuid=(
            shipment.integration_secret_revision_uuid
        ),
        provider_account_secret_revision_uuid=(
            shipment.provider_account_secret_revision_uuid
        ),
        global_claim_uuid=replay_claim,
        claim_generation=1,
        binding_revision=shipment.binding_revision,
        masked_account_hint=shipment.account_masked_hint,
        historical=True,
    )
    return _ShipmentPlan(
        rental_id=rental.id,
        device_id=rental.device_id,
        shipment_uuid=shipment.id,
        job_uuid=provenance.job_uuid,
        receiver_snapshot=dict(shipment.receiver_snapshot),
        express_type_id=shipment.express_type_id,
        scheduled_dispatch_at=shipment.scheduled_dispatch_at,
        warehouse_uuid=shipment.origin_warehouse_uuid,
        provider_account_uuid=shipment.provider_account_uuid,
        binding_revision=shipment.binding_revision,
        provider_context=context,
    )


def _receiver_snapshot(rental: Rental) -> dict[str, str]:
    values = {
        "contact_name": rental.customer_name,
        "contact_phone": rental.customer_phone,
        "province": rental.customer_province,
        "city": rental.customer_city,
        "district": rental.customer_district,
        "address_detail": rental.customer_address_detail,
    }
    if any(
        not isinstance(value, str) or not value.strip()
        for value in values.values()
    ):
        raise SfBatchShippingRejected()
    return {name: value.strip() for name, value in values.items()}


def _shipment_uuid(request_uuid: str, rental_id: int) -> str:
    return str(uuid5(UUID(request_uuid), f"sf-shipment:{rental_id}"))


def _job_uuid(request_uuid: str, rental_id: int) -> str:
    return str(uuid5(UUID(request_uuid), f"sf-job:{rental_id}"))


def _parse_scheduled_time(value: object) -> datetime:
    if not isinstance(value, str) or not 1 <= len(value) <= 40:
        raise ValueError
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.microsecond != 0
    ):
        raise ValueError
    return parsed.astimezone(timezone.utc)


def _aware_utc(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError
    return value.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return f"{value.isoformat(timespec='seconds')}Z"


def _uuid(value: object) -> str:
    parsed = UUID(str(value))
    if parsed.int == 0:
        raise ValueError
    return str(parsed)


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError
    return value


__all__ = [
    "SF_BATCH_SHIPPING_HTTP_RUNTIME_EXTENSION",
    "SfBatchShippingHttpError",
    "SfBatchShippingHttpRuntime",
    "SfBatchShippingHttpRuntimeUnavailable",
    "SfBatchShippingRejected",
    "SfBatchShippingRequestInvalid",
    "SqlAlchemySfBatchShippingHttpRuntime",
    "install_sf_batch_shipping_http_runtime",
    "require_sf_batch_shipping_http_runtime",
]
