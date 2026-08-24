"""Opt-in real-MySQL contention checks for logical accessory allocation.

These tests are intentionally inert in the normal suite.  They may run only
when the caller explicitly enables them and supplies a guarded URL whose exact
schema name is ``inventory_management_test``.  The shared metadata guard owns
the destructive test-schema rebuild; this module never accepts a production
schema or a caller-provided SQL statement.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import os
from threading import Barrier, Lock, Thread
from typing import Callable
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app import create_app, db
from app.models.accessory_inventory import (
    AccessoryType,
    AccessoryUnit,
    AccessoryUnitEvent,
    DeviceAccessoryConfig,
    RentalAccessoryRequest,
    RentalAccessoryUnitLink,
)
from app.models.audit_log import AuditLog
from app.models.device import Device
from app.models.rental import Rental
from app.models.rental_relay_case import RentalRelayCase
from app.models.shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
)
from app.models.warehouse import Warehouse
from app.services.accessory_inventory_service import (
    AccessoryInventoryService,
    AccessoryUnitUnavailableError,
)
from app.services.relay.mutation_service import (
    RelayStatusMutationConflict,
    RelayStatusMutationService,
)
from app.services.relay.reconciliation import (
    RelayExternalReconciliationService,
)
from app.services.relay.result_signal import RelayShipmentResultSignalService
from app.services.shipping.sf_waybill_provider import (
    SfWaybillProviderResult,
    SfWaybillQueryResult,
)
from app.services.shipping.sf_waybill_intent import (
    PreparedSfWaybillIntentJob,
    SqlAlchemySfWaybillIntentStore,
)
from app.services.shipping.sf_waybill_reconciliation import (
    PreparedSfWaybillReconciliationJob,
    SqlAlchemySfWaybillReconciliationStore,
)
from app.services.shipping.sf_waybill_worker import (
    SF_CREATE_WAYBILL_JOB_TYPE,
    SfCreateWaybillJobHandler,
    SqlAlchemySfWaybillTenantStore,
)
from app.services.shipping.tracking_ledger import (
    SHIPMENT_TRACKING_RESULT_ACTION,
    ShipmentTrackingLedgerService,
    ShipmentTrackingObservation,
)
from app.services.shipping_execution_service import (
    ProviderOutcome,
    UnknownResolution,
)
from inventory_control.jobs import AuthorityVerdict, OutcomeDisposition
from inventory_control.models.jobs import BackgroundJob
from tests.support.test_database import (
    build_mysql_test_config,
    guarded_mysql_test_metadata,
)


_REAL_CONTENTION_ENABLED = (
    os.environ.get("RUN_REAL_MYSQL_CONTENTION_TESTS", "").lower() == "true"
)
pytestmark = pytest.mark.skipif(
    not _REAL_CONTENTION_ENABLED,
    reason=(
        "real MySQL contention requires "
        "RUN_REAL_MYSQL_CONTENTION_TESTS=true"
    ),
)


@pytest.fixture(scope="module")
def mysql_application():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.fail("TEST_DATABASE_URL is required for real contention tests")
    if os.environ.get("TESTING", "").lower() != "true":
        pytest.fail("TESTING=true is required for real contention tests")

    application = create_app(build_mysql_test_config())
    with application.app_context():
        if db.engine.dialect.name != "mysql":
            pytest.fail("real contention tests require a MySQL-protocol engine")
        with guarded_mysql_test_metadata(db.engine, db.metadata):
            try:
                yield application
            finally:
                db.session.remove()


@dataclass(frozen=True, slots=True)
class _SeededContention:
    accessory_type_id: int
    rental_ids: tuple[int, int]


def _ready_warehouse(suffix: str) -> Warehouse:
    warehouse = Warehouse(
        status="active",
        setup_state="pending",
        is_default=False,
        default_slot=None,
    )
    warehouse.mark_ready(
        name=f"contention-{suffix}",
        contact_name="测试负责人",
        contact_phone="13800138000",
        province="广东省",
        city="深圳市",
        district="南山区",
        address_detail="隔离测试库地址",
    )
    return warehouse


def _rental(device: Device, *, start_on: date, end_on: date) -> Rental:
    return Rental(
        device=device,
        start_date=start_on,
        end_date=end_on,
        customer_name="并发测试客户",
        customer_phone="13800138000",
        destination="隔离测试目的地",
        status="not_shipped",
    )


def _seed_last_unit(session_factory) -> _SeededContention:
    suffix = uuid4().hex[:12]
    with session_factory.begin() as session:
        warehouse = _ready_warehouse(suffix)
        device = Device(
            name=f"contention-device-{suffix}",
            serial_number=f"contention-{suffix}",
            is_accessory=False,
            warehouse=warehouse,
        )
        accessory_type = AccessoryType(
            name=f"tripod-{suffix}",
            display_name="并发测试三脚架",
            tracking_mode="logical_unit",
            is_active=True,
        )
        session.add_all((warehouse, device, accessory_type))
        session.flush()
        session.add(
            DeviceAccessoryConfig(
                device_id=device.id,
                accessory_type_id=accessory_type.id,
                enabled=True,
            )
        )
        session.add(
            AccessoryUnit(
                accessory_type_id=accessory_type.id,
                warehouse_id=warehouse.id,
                condition_status="active",
            )
        )
        rentals = (
            _rental(
                device,
                start_on=date(2026, 9, 10),
                end_on=date(2026, 9, 12),
            ),
            _rental(
                device,
                start_on=date(2026, 9, 11),
                end_on=date(2026, 9, 13),
            ),
        )
        session.add_all(rentals)
        session.flush()
        return _SeededContention(
            accessory_type_id=accessory_type.id,
            rental_ids=(rentals[0].id, rentals[1].id),
        )


def _run_two_reservations(
    session_factory,
    seeded: _SeededContention,
    *,
    windows: tuple[tuple[datetime, datetime], tuple[datetime, datetime]],
) -> tuple[object, object]:
    start = Barrier(3, timeout=15)
    result_lock = Lock()
    results: list[object | None] = [None, None]

    def reserve(index: int) -> None:
        session: Session = session_factory()
        try:
            start.wait()
            with session.begin():
                AccessoryInventoryService(session).reserve_for_rental(
                    rental_id=seeded.rental_ids[index],
                    accessory_type_id=seeded.accessory_type_id,
                    reservation_start_at=windows[index][0],
                    reservation_end_at=windows[index][1],
                    actor_type="system",
                    actor_id="mysql-contention-test",
                    operation_key=f"mysql-race-{uuid4().hex}",
                )
            outcome: object = "committed"
        except BaseException as exc:  # retained for assertion in main thread
            session.rollback()
            outcome = exc
        finally:
            session.close()
        with result_lock:
            results[index] = outcome

    threads = tuple(
        Thread(
            target=reserve,
            args=(index,),
            name=f"accessory-contention-{index}",
            daemon=True,
        )
        for index in range(2)
    )
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads), (
        "contention worker did not finish before the bounded timeout"
    )
    assert all(result is not None for result in results)
    return results[0], results[1]


def _counts(session_factory, seeded: _SeededContention) -> tuple[int, int, int]:
    with session_factory() as session:
        request_count = session.scalar(
            select(func.count())
            .select_from(RentalAccessoryRequest)
            .where(
                RentalAccessoryRequest.rental_id.in_(seeded.rental_ids),
                RentalAccessoryRequest.accessory_type_id
                == seeded.accessory_type_id,
            )
        )
        link_count = session.scalar(
            select(func.count())
            .select_from(RentalAccessoryUnitLink)
            .where(
                RentalAccessoryUnitLink.rental_id.in_(seeded.rental_ids),
                RentalAccessoryUnitLink.accessory_type_id
                == seeded.accessory_type_id,
            )
        )
        event_count = session.scalar(
            select(func.count())
            .select_from(AccessoryUnitEvent)
            .where(
                AccessoryUnitEvent.rental_id.in_(seeded.rental_ids),
                AccessoryUnitEvent.event_type == "linked",
            )
        )
        return int(request_count), int(link_count), int(event_count)


def _factory() -> Callable[[], Session]:
    return sessionmaker(bind=db.engine, expire_on_commit=False)


def test_last_overlapping_unit_has_exactly_one_commit(mysql_application):
    del mysql_application
    session_factory = _factory()
    seeded = _seed_last_unit(session_factory)
    shared_window = (
        datetime(2026, 9, 8, 0, 0),
        datetime(2026, 9, 14, 0, 0),
    )

    outcomes = _run_two_reservations(
        session_factory,
        seeded,
        windows=(shared_window, shared_window),
    )

    assert outcomes.count("committed") == 1
    failures = tuple(item for item in outcomes if item != "committed")
    assert len(failures) == 1
    assert isinstance(failures[0], AccessoryUnitUnavailableError)
    assert _counts(session_factory, seeded) == (1, 1, 1)


def test_last_unit_can_serve_two_non_overlapping_windows(mysql_application):
    del mysql_application
    session_factory = _factory()
    seeded = _seed_last_unit(session_factory)
    windows = (
        (datetime(2026, 9, 8, 0, 0), datetime(2026, 9, 10, 0, 0)),
        (datetime(2026, 9, 10, 0, 0), datetime(2026, 9, 14, 0, 0)),
    )

    outcomes = _run_two_reservations(
        session_factory,
        seeded,
        windows=windows,
    )

    assert outcomes == ("committed", "committed")
    assert _counts(session_factory, seeded) == (2, 2, 2)


@dataclass(frozen=True, slots=True)
class _SeededRelayChain:
    rental_ids: tuple[int, int, int]
    unit_id: str


def _relay_window(rental: Rental) -> tuple[datetime, datetime]:
    return (
        datetime.combine(rental.planned_ship_out_date, time.min),
        datetime.combine(
            rental.planned_return_date + timedelta(days=1),
            time.min,
        ),
    )


def _seed_relay_chain(session_factory) -> _SeededRelayChain:
    suffix = uuid4().hex[:12]
    unit_id = str(uuid4())
    with session_factory.begin() as session:
        warehouse = _ready_warehouse(f"relay-{suffix}")
        accessory_type = AccessoryType(
            name=f"relay-tripod-{suffix}",
            display_name="接力并发测试三脚架",
            tracking_mode="logical_unit",
            is_active=True,
        )
        device = Device(
            name=f"relay-device-{suffix}",
            serial_number=f"relay-{suffix}",
            warehouse=warehouse,
        )
        session.add_all((warehouse, accessory_type, device))
        session.flush()
        rentals = []
        for index, planned_ship_out in enumerate(
            (date(2026, 10, 1), date(2026, 10, 5), date(2026, 10, 9))
        ):
            rental = _rental(
                device,
                start_on=planned_ship_out + timedelta(days=2),
                end_on=planned_ship_out + timedelta(days=4),
            )
            rental.planned_ship_out_date = planned_ship_out
            rental.planned_return_date = planned_ship_out + timedelta(days=6)
            rental.logistics_days = 1
            session.add(rental)
            rentals.append(rental)
        session.flush()
        unit = AccessoryUnit(
            id=unit_id,
            accessory_type_id=accessory_type.id,
            warehouse_id=warehouse.id,
            condition_status="active",
            current_holder_rental_id=rentals[0].id,
        )
        first_start, first_end = _relay_window(rentals[0])
        session.add_all(
            (
                unit,
                RentalAccessoryUnitLink(
                    rental_id=rentals[0].id,
                    accessory_type_id=accessory_type.id,
                    accessory_unit_id=unit_id,
                    reservation_start_at=first_start,
                    reservation_end_at=first_end,
                ),
                RentalRelayCase(
                    predecessor_rental_id=rentals[0].id,
                    successor_rental_id=rentals[1].id,
                    status="pending",
                ),
                RentalRelayCase(
                    predecessor_rental_id=rentals[1].id,
                    successor_rental_id=rentals[2].id,
                    status="pending",
                ),
            )
        )
        rental_ids = tuple(rental.id for rental in rentals)

    for predecessor_id, successor_id, operation_key in (
        (rental_ids[1], rental_ids[2], f"agree-b-c-{suffix}"),
        (rental_ids[0], rental_ids[1], f"agree-a-b-{suffix}"),
    ):
        with session_factory.begin() as session:
            RelayStatusMutationService.update(
                tenant_session=session,
                predecessor_id=predecessor_id,
                successor_id=successor_id,
                status="agreed",
                accessory_note_provided=False,
                accessory_note=None,
                database_now=datetime(
                    2026,
                    8,
                    23,
                    8,
                    tzinfo=timezone.utc,
                ),
                actor_id="mysql-contention-test",
                operation_key=operation_key,
                tenant_timezone="Asia/Shanghai",
            )
    return _SeededRelayChain(
        rental_ids=rental_ids,
        unit_id=unit_id,
    )


def _project_relay_edge(
    session_factory,
    *,
    predecessor_id: int,
    successor_id: int,
    tracking_number: str,
    operation_key: str,
) -> None:
    with session_factory.begin() as session:
        RelayStatusMutationService.project_external_stage(
            tenant_session=session,
            predecessor_id=predecessor_id,
            successor_id=successor_id,
            status="shipped",
            sf_tracking_number=tracking_number,
            database_now=datetime(
                2026,
                8,
                23,
                9,
                tzinfo=timezone.utc,
            ),
            actor_id="mysql-contention-test",
            operation_key=operation_key,
            tenant_timezone="Asia/Shanghai",
        )


def _run_relay_projections(
    session_factory,
    operations: tuple[tuple[int, int, str, str], ...],
) -> tuple[object, ...]:
    start = Barrier(len(operations) + 1, timeout=15)
    result_lock = Lock()
    results: list[object | None] = [None] * len(operations)

    def project(index: int) -> None:
        predecessor_id, successor_id, tracking, operation_key = operations[
            index
        ]
        try:
            start.wait()
            _project_relay_edge(
                session_factory,
                predecessor_id=predecessor_id,
                successor_id=successor_id,
                tracking_number=tracking,
                operation_key=operation_key,
            )
            outcome: object = "committed"
        except BaseException as exc:  # retained for assertion in main thread
            outcome = exc
        with result_lock:
            results[index] = outcome

    threads = tuple(
        Thread(
            target=project,
            args=(index,),
            name=f"relay-contention-{index}",
            daemon=True,
        )
        for index in range(len(operations))
    )
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)
    assert all(result is not None for result in results)
    return tuple(results)


def _relay_facts(session_factory, seeded: _SeededRelayChain):
    with session_factory() as session:
        cases = tuple(
            session.scalars(
                select(RentalRelayCase)
                .where(
                    RentalRelayCase.predecessor_rental_id.in_(
                        seeded.rental_ids
                    )
                )
                .order_by(RentalRelayCase.predecessor_rental_id)
            )
        )
        unit = session.get(AccessoryUnit, seeded.unit_id)
        event_count = session.scalar(
            select(func.count())
            .select_from(AccessoryUnitEvent)
            .where(
                AccessoryUnitEvent.unit_id == seeded.unit_id,
                AccessoryUnitEvent.event_type == "relay_handoff",
            )
        )
        audit_count = session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "relay_case_status_changed",
                AuditLog.rental_id.in_(seeded.rental_ids),
            )
        )
        assert unit is not None
        return (
            tuple(case.status for case in cases),
            unit.current_holder_rental_id,
            int(event_count),
            int(audit_count),
        )


def test_relay_exact_handoff_race_is_one_event(mysql_application):
    del mysql_application
    session_factory = _factory()
    seeded = _seed_relay_chain(session_factory)
    first_id, second_id, _third_id = seeded.rental_ids
    operation = (
        first_id,
        second_id,
        f"SF-AB-{uuid4().hex[:10]}",
        f"relay-replay-{uuid4().hex[:10]}",
    )

    outcomes = _run_relay_projections(
        session_factory,
        (operation, operation),
    )

    assert outcomes == ("committed", "committed")
    statuses, holder_id, event_count, audit_count = _relay_facts(
        session_factory,
        seeded,
    )
    assert statuses == ("shipped", "agreed")
    assert holder_id == second_id
    assert event_count == 1
    assert audit_count == 3


@dataclass(frozen=True, slots=True)
class _SeededSfExecution:
    shipment_id: str
    attempt_id: str
    response_digest: str
    waybill: str
    submitted_at: datetime


def _seed_sf_execution(
    session_factory,
    *,
    rental_id: int,
    provider_submitting: bool = False,
) -> _SeededSfExecution:
    seeded = _SeededSfExecution(
        shipment_id=str(uuid4()),
        attempt_id=str(uuid4()),
        response_digest=uuid4().hex + uuid4().hex,
        waybill=f"SF-LEDGER-{uuid4().hex[:10]}",
        submitted_at=datetime(2026, 8, 23, 9, tzinfo=timezone.utc),
    )
    with session_factory.begin() as session:
        rental = session.get(Rental, rental_id)
        assert rental is not None
        warehouse = session.get(Warehouse, rental.device.warehouse_id)
        assert warehouse is not None
        integration_id = str(uuid4())
        account_id = str(uuid4())
        integration_revision = str(uuid4())
        account_revision = str(uuid4())
        session.add_all(
            (
                OutboundShipment(
                    id=seeded.shipment_id,
                    provider="sf",
                    rental_id=rental_id,
                    origin_warehouse_id=warehouse.id,
                    origin_warehouse_uuid=warehouse.warehouse_uuid,
                    integration_uuid=integration_id,
                    provider_account_uuid=account_id,
                    integration_secret_revision_uuid=integration_revision,
                    provider_account_secret_revision_uuid=account_revision,
                    binding_revision=1,
                    account_masked_hint="****1234",
                    sender_snapshot={"synthetic": True},
                    receiver_snapshot={"synthetic": True},
                    cargo_snapshot={
                        "items": [{"name": "租赁设备", "count": 1}]
                    },
                    tracking_check_phone_last4="8000",
                    express_type_id=2,
                    scheduled_dispatch_at=seeded.submitted_at.replace(
                        tzinfo=None
                    ),
                    provider_order_id=f"sf:test:{seeded.shipment_id}",
                    request_hash=uuid4().hex + uuid4().hex,
                    status=(
                        "provider_submitting"
                        if provider_submitting
                        else "prepared"
                    ),
                    prepared_at=seeded.submitted_at,
                ),
                ProviderOperationAttempt(
                    id=seeded.attempt_id,
                    shipment_id=seeded.shipment_id,
                    operation="create_waybill",
                    idempotency_key=f"sf:test:{seeded.attempt_id}",
                    attempt_no=1,
                    integration_secret_revision_uuid=integration_revision,
                    provider_account_secret_revision_uuid=account_revision,
                    binding_revision=1,
                    status=(
                        "provider_submitting"
                        if provider_submitting
                        else "prepared"
                    ),
                    started_at=(
                        seeded.submitted_at if provider_submitting else None
                    ),
                ),
            )
        )
    return seeded


def test_committed_shipment_reconciliation_race_is_one_handoff(
    mysql_application,
):
    del mysql_application
    session_factory = _factory()
    seeded = _seed_relay_chain(session_factory)
    first_id, second_id, _third_id = seeded.rental_ids
    execution = _seed_sf_execution(
        session_factory,
        rental_id=second_id,
    )
    shipment_id = execution.shipment_id
    attempt_id = execution.attempt_id
    response_digest = execution.response_digest
    waybill = execution.waybill
    submitted_at = execution.submitted_at

    @contextmanager
    def tenant_transaction(_prepared):
        with session_factory.begin() as session:
            yield session

    class Request:
        def discard_credentials(self):
            return None

    class Credentials:
        def prepare(self, *, job, snapshot):
            assert snapshot.shipment_uuid == job.shipment_uuid
            return Request()

    class Dispatcher:
        def dispatch(self, _request):
            return SfWaybillProviderResult(
                outcome=ProviderOutcome.SUCCESS,
                waybill_no=waybill,
                response_hash=response_digest,
                latency_ms=5,
            )

    class Authorizer:
        def authorize(self, _job):
            return AuthorityVerdict(True)

    class LostDirectRelayResponse:
        def enqueue(self, **_values):
            raise RuntimeError("synthetic direct relay response loss")

    tenant_uuid = str(uuid4())
    sf_job = BackgroundJob(
        id=str(uuid4()),
        tenant_id=tenant_uuid,
        tenant_access_version=1,
        job_type=SF_CREATE_WAYBILL_JOB_TYPE,
        resource_key=f"sf-shipment:{shipment_id}",
        payload={
            "contract_version": 1,
            "shipment_uuid": shipment_id,
            "attempt_uuid": attempt_id,
        },
        idempotency_key=f"sf-create:{attempt_id}",
        requested_by_type="tenant_user",
        requested_by_id=str(uuid4()),
        request_id="mysql-fake-sf-create",
        available_at=submitted_at,
    )
    handler = SfCreateWaybillJobHandler(
        tenant_store=SqlAlchemySfWaybillTenantStore(tenant_transaction),
        credential_source=Credentials(),
        provider_dispatcher=Dispatcher(),
        call_authorizer=Authorizer(),
        relay_enqueuer=LostDirectRelayResponse(),
        clock=lambda: submitted_at,
    )

    outcome = handler.execute(sf_job, handler.prepare(sf_job))

    assert outcome.disposition is OutcomeDisposition.SUCCEEDED
    assert outcome.safe_result["relay_direct_enqueued"] is False
    with session_factory.begin() as session:
        signal = RelayShipmentResultSignalService.capture(
            tenant_session=session,
            attempt_uuid=attempt_id,
        )
    assert signal is not None
    assert signal.shipment_uuid == shipment_id
    assert signal.source_result_digest == response_digest
    start = Barrier(3, timeout=15)
    result_lock = Lock()
    results: list[object | None] = [None, None]

    def project(index: int) -> None:
        try:
            start.wait()
            with session_factory.begin() as session:
                receipt = RelayExternalReconciliationService.reconcile_one(
                    tenant_session=session,
                    tenant_timezone="Asia/Shanghai",
                )
                assert receipt is None or receipt.shipment_uuid == shipment_id
            outcome: object = "committed"
        except BaseException as exc:  # retained for assertion in main thread
            outcome = exc
        with result_lock:
            results[index] = outcome

    threads = tuple(
        Thread(target=project, args=(index,), daemon=True)
        for index in range(2)
    )
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)
    assert results == ["committed", "committed"]
    statuses, holder_id, event_count, audit_count = _relay_facts(
        session_factory,
        seeded,
    )
    assert statuses == ("shipped", "agreed")
    assert holder_id == second_id
    assert event_count == 1
    assert audit_count == 3

    observation = ShipmentTrackingObservation(
        shipment_uuid=shipment_id,
        waybill_no=waybill,
        status="delivered",
        occurred_at=datetime(2026, 8, 23, 10, tzinfo=timezone.utc),
    )
    tracking_start = Barrier(3, timeout=15)
    tracking_results: list[object | None] = [None, None]

    def record_tracking(index: int) -> None:
        try:
            tracking_start.wait()
            with session_factory.begin() as session:
                receipt = ShipmentTrackingLedgerService.record(
                    tenant_session=session,
                    observation=observation,
                )
            outcome: object = receipt.observation.result_digest
        except BaseException as exc:  # retained for assertion in main thread
            outcome = exc
        with result_lock:
            tracking_results[index] = outcome

    tracking_threads = tuple(
        Thread(target=record_tracking, args=(index,), daemon=True)
        for index in range(2)
    )
    for thread in tracking_threads:
        thread.start()
    tracking_start.wait()
    for thread in tracking_threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in tracking_threads)
    assert tracking_results == [
        observation.result_digest,
        observation.result_digest,
    ]
    with session_factory() as session:
        assert session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == SHIPMENT_TRACKING_RESULT_ACTION,
                AuditLog.resource_id == shipment_id,
            )
        ) == 1


def test_unknown_waybill_query_claim_is_single_and_handoff_recovers(
    mysql_application,
):
    del mysql_application
    session_factory = _factory()
    relay = _seed_relay_chain(session_factory)
    first_id, second_id, _third_id = relay.rental_ids
    execution = _seed_sf_execution(
        session_factory,
        rental_id=second_id,
        provider_submitting=True,
    )

    @contextmanager
    def tenant_transaction(_context):
        with session_factory.begin() as session:
            yield session

    store = SqlAlchemySfWaybillReconciliationStore(tenant_transaction)
    prepared = PreparedSfWaybillReconciliationJob(
        job_uuid=str(uuid4()),
        tenant_uuid=str(uuid4()),
        tenant_access_version=1,
        request_id="mysql-sf-query-reconciliation",
    )
    start = Barrier(3, timeout=15)
    result_lock = Lock()
    results: list[object | None] = [None, None]

    def claim(index: int) -> None:
        try:
            start.wait()
            outcome: object = store.claim_one(
                prepared,
                started_at=execution.submitted_at,
            )
        except BaseException as exc:  # retained for assertion in main thread
            outcome = exc
        with result_lock:
            results[index] = outcome

    threads = tuple(
        Thread(target=claim, args=(index,), daemon=True)
        for index in range(2)
    )
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)
    snapshots = tuple(
        result
        for result in results
        if result is not None and not isinstance(result, BaseException)
    )
    assert len(snapshots) == 1
    assert sum(result is None for result in results) == 1, repr(results)

    stored = store.record_result(
        prepared,
        snapshot=snapshots[0],
        result=SfWaybillQueryResult(
            resolution=UnknownResolution.CONFIRMED_SUCCESS,
            safe_provider_code="SF_QUERY_CONFIRMED",
            waybill_no=execution.waybill,
            response_hash=execution.response_digest,
        ),
        finished_at=execution.submitted_at,
    )

    assert stored.relay_signal is not None
    with session_factory.begin() as session:
        receipt = RelayExternalReconciliationService.reconcile_one(
            tenant_session=session,
            tenant_timezone="Asia/Shanghai",
        )
        assert receipt is not None
        assert receipt.shipment_uuid == execution.shipment_id
    statuses, holder_id, event_count, _audit_count = _relay_facts(
        session_factory,
        relay,
    )
    assert statuses == ("shipped", "agreed")
    assert holder_id == second_id
    assert first_id != second_id
    assert event_count == 1


def test_waybill_intent_ack_race_is_one_winner(mysql_application):
    del mysql_application
    session_factory = _factory()
    relay = _seed_relay_chain(session_factory)
    _first_id, second_id, _third_id = relay.rental_ids
    execution = _seed_sf_execution(session_factory, rental_id=second_id)
    tenant_uuid = str(uuid4())
    actor_uuid = str(uuid4())
    job_uuid = str(uuid4())

    with session_factory.begin() as session:
        attempt = session.get(ProviderOperationAttempt, execution.attempt_id)
        assert attempt is not None
        attempt.background_job_uuid = job_uuid
        attempt.tenant_access_version = 3
        attempt.requested_by_user_uuid = actor_uuid
        attempt.request_id = "mysql-waybill-intent"
        attempt.correlation_id = "mysql-waybill-intent-correlation"

    @contextmanager
    def tenant_transaction(_context):
        with session_factory.begin() as session:
            yield session

    store = SqlAlchemySfWaybillIntentStore(tenant_transaction)
    prepared = PreparedSfWaybillIntentJob(
        job_uuid=str(uuid4()),
        tenant_uuid=tenant_uuid,
        tenant_access_version=3,
        request_id="mysql-waybill-intent-reconciliation",
    )
    signal = store.discover_one(prepared)
    assert signal is not None
    assert signal.job_uuid == job_uuid
    assert signal.requested_by_user_uuid == actor_uuid

    start = Barrier(3, timeout=15)
    result_lock = Lock()
    results: list[object | None] = [None, None]

    def acknowledge(index: int) -> None:
        try:
            start.wait()
            outcome: object = store.acknowledge_enqueued(
                prepared,
                signal=signal,
                acknowledged_at=execution.submitted_at,
            )
        except BaseException as exc:  # retained for assertion in main thread
            outcome = exc
        with result_lock:
            results[index] = outcome

    threads = tuple(
        Thread(target=acknowledge, args=(index,), daemon=True)
        for index in range(2)
    )
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)
    assert sorted(results) == [False, True]

    with session_factory() as session:
        attempt = session.get(ProviderOperationAttempt, execution.attempt_id)
        assert attempt is not None
        assert attempt.job_enqueued_at == execution.submitted_at.replace(
            tzinfo=None
        )


def test_out_of_order_relay_handoff_race_converges_after_retry(
    mysql_application,
):
    del mysql_application
    session_factory = _factory()
    seeded = _seed_relay_chain(session_factory)
    first_id, second_id, third_id = seeded.rental_ids
    operations = (
        (
            first_id,
            second_id,
            f"SF-AB-{uuid4().hex[:10]}",
            f"relay-a-b-{uuid4().hex[:10]}",
        ),
        (
            second_id,
            third_id,
            f"SF-BC-{uuid4().hex[:10]}",
            f"relay-b-c-{uuid4().hex[:10]}",
        ),
    )

    outcomes = _run_relay_projections(session_factory, operations)
    assert outcomes[0] == "committed"
    assert outcomes[1] == "committed" or isinstance(
        outcomes[1],
        RelayStatusMutationConflict,
    )
    statuses, holder_id, event_count, _audit_count = _relay_facts(
        session_factory,
        seeded,
    )
    assert statuses in {("shipped", "agreed"), ("shipped", "shipped")}
    assert (holder_id, event_count) in {(second_id, 1), (third_id, 2)}

    if statuses[1] == "agreed":
        _project_relay_edge(
            session_factory,
            predecessor_id=operations[1][0],
            successor_id=operations[1][1],
            tracking_number=operations[1][2],
            operation_key=operations[1][3],
        )
    final_statuses, final_holder, final_events, _final_audits = _relay_facts(
        session_factory,
        seeded,
    )
    assert final_statuses == ("shipped", "shipped")
    assert final_holder == third_id
    assert final_events == 2
