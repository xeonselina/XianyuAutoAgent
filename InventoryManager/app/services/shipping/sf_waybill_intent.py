"""Provider-free bridge from committed tenant intents to control jobs.

The tenant attempt owns the immutable actor, access-version and preallocated
job UUID.  The control enqueue commits in a separate transaction, then the
tenant row is acknowledged.  If the response or acknowledgement is lost, the
next reconciliation run replays the exact control job identity.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Final, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, SessionTransactionOrigin

from app.models.shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
)
from app.services.shipping.sf_waybill_worker import (
    SfCreateWaybillJobCoordinator,
    SfWaybillWorkerConflict,
    SfWaybillWorkerInputError,
)
from app.services.shipping_execution_service import (
    ShippingExecutionError,
    ShippingExecutionService,
    ShippingJobProvenance,
)
from app.tenancy import TenantContext, TenantContextSource
from inventory_control import ControlDatabase
from inventory_control.jobs import (
    JobIdempotencyConflict,
    JobOutcome,
    OutcomeDisposition,
    PeriodicJobDefinition,
    PreparedJob,
    ScheduleCycle,
)
from inventory_control.models.foundation import Tenant
from inventory_control.models.jobs import BackgroundJob


SF_WAYBILL_INTENT_JOB_TYPE: Final = "sf_waybill_enqueue_intent"
SF_WAYBILL_INTENT_RESOURCE_KEY: Final = "sf:waybill-intent-enqueue"
SF_WAYBILL_INTENT_INTERVAL: Final = timedelta(seconds=30)


class SfWaybillIntentError(RuntimeError):
    code = "SF_WAYBILL_INTENT_FAILED"
    public_message = "SF waybill intent enqueue failed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class SfWaybillIntentInputError(SfWaybillIntentError):
    code = "SF_WAYBILL_INTENT_INPUT_INVALID"


class SfWaybillIntentConflict(SfWaybillIntentError):
    code = "SF_WAYBILL_INTENT_CONFLICT"


class SfWaybillIntentPersistenceError(SfWaybillIntentError):
    code = "SF_WAYBILL_INTENT_PERSISTENCE_FAILED"


@dataclass(frozen=True, slots=True)
class PreparedSfWaybillIntentJob:
    job_uuid: str
    tenant_uuid: str
    tenant_access_version: int
    request_id: str


@dataclass(frozen=True, slots=True)
class SfWaybillIntentSignal:
    tenant_uuid: str
    tenant_access_version: int
    job_uuid: str
    shipment_uuid: str
    attempt_uuid: str
    requested_by_user_uuid: str
    request_id: str
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "tenant_uuid", _uuid(self.tenant_uuid))
            object.__setattr__(self, "job_uuid", _uuid(self.job_uuid))
            object.__setattr__(self, "shipment_uuid", _uuid(self.shipment_uuid))
            object.__setattr__(self, "attempt_uuid", _uuid(self.attempt_uuid))
            object.__setattr__(
                self,
                "requested_by_user_uuid",
                _uuid(self.requested_by_user_uuid),
            )
            object.__setattr__(
                self,
                "tenant_access_version",
                _positive(self.tenant_access_version),
            )
            object.__setattr__(
                self,
                "request_id",
                _text(self.request_id, maximum=64),
            )
            object.__setattr__(
                self,
                "correlation_id",
                _optional_text(self.correlation_id, maximum=64),
            )
        except (TypeError, ValueError):
            raise SfWaybillIntentInputError() from None


class SfWaybillIntentStore(Protocol):
    def discover_one(
        self,
        prepared: PreparedSfWaybillIntentJob,
    ) -> SfWaybillIntentSignal | None: ...

    def acknowledge_enqueued(
        self,
        prepared: PreparedSfWaybillIntentJob,
        *,
        signal: SfWaybillIntentSignal,
        acknowledged_at: datetime,
    ) -> bool: ...


class SfWaybillIntentEnqueuer(Protocol):
    def enqueue(
        self,
        *,
        signal: SfWaybillIntentSignal,
        available_at: datetime,
    ) -> BackgroundJob: ...


TenantTransactionProvider = Callable[
    [TenantContext], AbstractContextManager[Session]
]


class SqlAlchemySfWaybillIntentStore:
    """Read and acknowledge one committed intent in short transactions."""

    def __init__(self, transaction_provider: TenantTransactionProvider) -> None:
        if not callable(transaction_provider):
            raise TypeError("tenant transaction provider is required")
        self._transactions = transaction_provider

    def discover_one(
        self,
        prepared: PreparedSfWaybillIntentJob,
    ) -> SfWaybillIntentSignal | None:
        _prepared(prepared)
        try:
            with self._transactions(_tenant_context(prepared)) as session:
                _require_transaction(session)
                attempt = session.scalar(
                    sa.select(ProviderOperationAttempt)
                    .where(
                        ProviderOperationAttempt.operation == "create_waybill",
                        ProviderOperationAttempt.status == "prepared",
                        ProviderOperationAttempt.job_enqueued_at.is_(None),
                        ProviderOperationAttempt.background_job_uuid.is_not(None),
                        ProviderOperationAttempt.tenant_access_version
                        == prepared.tenant_access_version,
                        ProviderOperationAttempt.requested_by_user_uuid.is_not(
                            None
                        ),
                        ProviderOperationAttempt.request_id.is_not(None),
                    )
                    .order_by(
                        ProviderOperationAttempt.created_at.asc(),
                        ProviderOperationAttempt.id.asc(),
                    )
                    .limit(1)
                    .with_for_update(skip_locked=True)
                    .execution_options(populate_existing=True)
                )
                if attempt is None:
                    return None
                shipment = session.scalar(
                    sa.select(OutboundShipment)
                    .where(OutboundShipment.id == attempt.shipment_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if (
                    shipment is None
                    or shipment.provider != "sf"
                    or shipment.status not in {"prepared", "failed"}
                    or attempt.integration_secret_revision_uuid
                    != shipment.integration_secret_revision_uuid
                    or attempt.provider_account_secret_revision_uuid
                    != shipment.provider_account_secret_revision_uuid
                    or attempt.binding_revision != shipment.binding_revision
                ):
                    raise SfWaybillIntentConflict()
                return SfWaybillIntentSignal(
                    tenant_uuid=prepared.tenant_uuid,
                    tenant_access_version=attempt.tenant_access_version,
                    job_uuid=attempt.background_job_uuid,
                    shipment_uuid=shipment.id,
                    attempt_uuid=attempt.id,
                    requested_by_user_uuid=attempt.requested_by_user_uuid,
                    request_id=attempt.request_id,
                    correlation_id=attempt.correlation_id,
                )
        except SfWaybillIntentError:
            raise
        except SQLAlchemyError:
            raise SfWaybillIntentPersistenceError() from None
        except Exception:
            raise SfWaybillIntentConflict() from None

    def acknowledge_enqueued(
        self,
        prepared: PreparedSfWaybillIntentJob,
        *,
        signal: SfWaybillIntentSignal,
        acknowledged_at: datetime,
    ) -> bool:
        _prepared(prepared)
        if (
            not isinstance(signal, SfWaybillIntentSignal)
            or signal.tenant_uuid != prepared.tenant_uuid
            or signal.tenant_access_version != prepared.tenant_access_version
        ):
            raise SfWaybillIntentInputError()
        current_time = _utc(acknowledged_at)
        try:
            with self._transactions(_tenant_context(prepared)) as session:
                _require_transaction(session)
                return ShippingExecutionService(
                    session
                ).acknowledge_provider_job_enqueued(
                    attempt_id=signal.attempt_uuid,
                    shipment_id=signal.shipment_uuid,
                    provenance=ShippingJobProvenance(
                        job_uuid=signal.job_uuid,
                        tenant_access_version=signal.tenant_access_version,
                        requested_by_user_uuid=(
                            signal.requested_by_user_uuid
                        ),
                        request_id=signal.request_id,
                        correlation_id=signal.correlation_id,
                    ),
                    enqueued_at=current_time,
                )
        except SfWaybillIntentError:
            raise
        except ShippingExecutionError:
            raise SfWaybillIntentConflict() from None
        except SQLAlchemyError:
            raise SfWaybillIntentPersistenceError() from None
        except Exception:
            raise SfWaybillIntentConflict() from None


class SqlAlchemySfWaybillIntentEnqueuer:
    """Commit the exact preallocated control job under current authority."""

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        coordinator: SfCreateWaybillJobCoordinator | None = None,
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise TypeError("control database is required")
        selected = coordinator or SfCreateWaybillJobCoordinator()
        if not callable(getattr(selected, "enqueue", None)):
            raise TypeError("SF waybill coordinator is invalid")
        self._database = control_database
        self._coordinator = selected

    def enqueue(
        self,
        *,
        signal: SfWaybillIntentSignal,
        available_at: datetime,
    ) -> BackgroundJob:
        if not isinstance(signal, SfWaybillIntentSignal):
            raise SfWaybillIntentInputError()
        current_time = _utc(available_at)
        try:
            with self._database.transaction() as control_session:
                return self._coordinator.enqueue(
                    control_session,
                    tenant_uuid=signal.tenant_uuid,
                    tenant_access_version=signal.tenant_access_version,
                    shipment_uuid=signal.shipment_uuid,
                    attempt_uuid=signal.attempt_uuid,
                    requested_by_user_uuid=signal.requested_by_user_uuid,
                    available_at=current_time,
                    job_uuid=signal.job_uuid,
                    request_id=signal.request_id,
                    correlation_id=signal.correlation_id,
                )
        except (SfWaybillWorkerConflict, JobIdempotencyConflict):
            raise SfWaybillIntentConflict() from None
        except SfWaybillWorkerInputError:
            raise SfWaybillIntentInputError() from None
        except SQLAlchemyError:
            raise SfWaybillIntentPersistenceError() from None
        except SfWaybillIntentError:
            raise
        except Exception:
            raise SfWaybillIntentPersistenceError() from None


class SfWaybillIntentJobHandler:
    crosses_provider_boundary = False
    recovery_category = None

    def __init__(
        self,
        *,
        store: SfWaybillIntentStore,
        enqueuer: SfWaybillIntentEnqueuer,
        clock: Callable[[], datetime],
    ) -> None:
        if (
            not all(
                callable(getattr(store, method, None))
                for method in ("discover_one", "acknowledge_enqueued")
            )
            or not callable(getattr(enqueuer, "enqueue", None))
            or not callable(clock)
        ):
            raise TypeError("SF waybill intent composition is invalid")
        self._store = store
        self._enqueuer = enqueuer
        self._clock = clock

    def prepare(self, job: BackgroundJob) -> PreparedJob:
        return PreparedJob(_parse_job(job))

    def execute(self, job: BackgroundJob, prepared: PreparedJob) -> JobOutcome:
        del job
        value = prepared.value
        if not isinstance(value, PreparedSfWaybillIntentJob):
            raise SfWaybillIntentInputError()
        try:
            signal = self._store.discover_one(value)
        except SfWaybillIntentConflict:
            return _review("sf_waybill_intent_conflict")
        except SfWaybillIntentError:
            return _retry("sf_waybill_intent_read_failed")
        if signal is None:
            return JobOutcome(
                OutcomeDisposition.SUCCEEDED,
                safe_result={"enqueued": False},
            )
        try:
            queued = self._enqueuer.enqueue(
                signal=signal,
                available_at=_utc(self._clock()),
            )
        except SfWaybillIntentConflict:
            return _review("sf_waybill_intent_authority_denied")
        except SfWaybillIntentError:
            return _retry("sf_waybill_intent_enqueue_failed")
        if queued.id != signal.job_uuid:
            return _review("sf_waybill_intent_job_mismatch")
        try:
            acknowledged = self._store.acknowledge_enqueued(
                value,
                signal=signal,
                acknowledged_at=_utc(self._clock()),
            )
        except SfWaybillIntentConflict:
            return _review("sf_waybill_intent_ack_conflict")
        except SfWaybillIntentError:
            return _retry("sf_waybill_intent_ack_failed")
        return JobOutcome(
            OutcomeDisposition.SUCCEEDED,
            safe_result={
                "enqueued": True,
                "acknowledged": acknowledged,
                "shipment_uuid": signal.shipment_uuid,
            },
        )


def sf_waybill_intent_job_definition() -> PeriodicJobDefinition:
    return PeriodicJobDefinition(
        job_type=SF_WAYBILL_INTENT_JOB_TYPE,
        interval=SF_WAYBILL_INTENT_INTERVAL,
        not_after_window=SF_WAYBILL_INTENT_INTERVAL,
        resource_key=SF_WAYBILL_INTENT_RESOURCE_KEY,
        payload_builder=_scheduled_payload,
        priority=85,
        max_attempts=3,
    )


def _scheduled_payload(
    session: Session,
    tenant: Tenant,
    cycle: ScheduleCycle,
) -> dict[str, object]:
    del session, tenant, cycle
    return {"contract_version": 1}


def _parse_job(job: BackgroundJob) -> PreparedSfWaybillIntentJob:
    expected_prefix = f"scheduler:{SF_WAYBILL_INTENT_JOB_TYPE}:"
    if (
        not isinstance(job, BackgroundJob)
        or job.job_type != SF_WAYBILL_INTENT_JOB_TYPE
        or job.resource_key != SF_WAYBILL_INTENT_RESOURCE_KEY
        or job.requested_by_type != "scheduler"
        or not isinstance(job.idempotency_key, str)
        or not job.idempotency_key.startswith(expected_prefix)
        or job.payload != {"contract_version": 1}
        or job.max_attempts != 3
    ):
        raise SfWaybillIntentInputError()
    try:
        return PreparedSfWaybillIntentJob(
            job_uuid=_uuid(job.id),
            tenant_uuid=_uuid(job.tenant_id),
            tenant_access_version=_positive(job.tenant_access_version),
            request_id=_text(
                job.correlation_id or job.request_id or job.id,
                maximum=64,
            ),
        )
    except (TypeError, ValueError):
        raise SfWaybillIntentInputError() from None


def _tenant_context(prepared: PreparedSfWaybillIntentJob) -> TenantContext:
    return TenantContext(
        tenant_id=UUID(prepared.tenant_uuid),
        access_version=prepared.tenant_access_version,
        source=TenantContextSource.WORKER_JOB,
        principal_ref="sf-waybill-intent-worker",
        source_ref=prepared.job_uuid,
        request_id=prepared.request_id,
    )


def _prepared(value: object) -> PreparedSfWaybillIntentJob:
    if not isinstance(value, PreparedSfWaybillIntentJob):
        raise SfWaybillIntentInputError()
    return value


def _require_transaction(session: Session) -> None:
    transaction = session.get_transaction() if isinstance(session, Session) else None
    if (
        transaction is None
        or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
    ):
        raise SfWaybillIntentInputError()


def _uuid(value: object) -> str:
    selected = str(UUID(str(value)))
    if UUID(selected).int == 0:
        raise ValueError
    return selected


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError
    return value


def _text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError
    selected = value.strip()
    if (
        not selected
        or selected != value
        or len(selected) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in selected)
    ):
        raise ValueError
    return selected


def _optional_text(value: object, *, maximum: int) -> str | None:
    if value is None:
        return None
    return _text(value, maximum=maximum)


def _utc(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("worker clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _retry(reason_code: str) -> JobOutcome:
    return JobOutcome(OutcomeDisposition.RETRY, reason_code=reason_code)


def _review(reason_code: str) -> JobOutcome:
    return JobOutcome(OutcomeDisposition.REVIEW, reason_code=reason_code)


__all__ = [
    "PreparedSfWaybillIntentJob",
    "SF_WAYBILL_INTENT_INTERVAL",
    "SF_WAYBILL_INTENT_JOB_TYPE",
    "SF_WAYBILL_INTENT_RESOURCE_KEY",
    "SfWaybillIntentConflict",
    "SfWaybillIntentError",
    "SfWaybillIntentInputError",
    "SfWaybillIntentJobHandler",
    "SfWaybillIntentPersistenceError",
    "SfWaybillIntentSignal",
    "SqlAlchemySfWaybillIntentEnqueuer",
    "SqlAlchemySfWaybillIntentStore",
    "sf_waybill_intent_job_definition",
]
