from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app import create_app, db
from app.models.accessory_inventory import (
    AccessoryType,
    AccessoryUnit,
    AccessoryUnitEvent,
    RentalAccessoryUnitLink,
)
from app.models.audit_log import AuditLog
from app.models.device import Device
from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding
from app.models.rental_relay_case import RentalRelayCase
from app.models.shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
)
from app.models.warehouse import Warehouse
from app.services.accessory_relay_chain_service import AccessoryRelayChainService
from app.services.relay.external_projection import (
    RELAY_EXTERNAL_PROJECTION_JOB_TYPE,
    RelayExternalProjectionCommand,
    RelayExternalProjectionConflict,
    RelayExternalProjectionCoordinator,
    RelayExternalProjectionError,
    RelayExternalProjectionInputError,
    RelayExternalProjectionJobHandler,
    RelayExternalProjectionReceipt,
    RelayExternalProjectionService,
    RelayExternalStage,
)
from app.services.relay.composition import (
    build_relay_external_projection_capability,
)
from app.services.relay.reconciliation import (
    RELAY_EXTERNAL_RECONCILIATION_JOB_TYPE,
    RELAY_EXTERNAL_RECONCILIATION_RESOURCE_KEY,
    RelayExternalReconciliationJobHandler,
    RelayExternalReconciliationService,
)
from app.services.relay.result_signal import (
    RelayCommittedShipmentResultEnqueuer,
    RelayShipmentResultSignalService,
)
from app.services.shipping.tracking_ledger import (
    SHIPMENT_TRACKING_RESULT_ACTION,
    ShipmentTrackingLedgerConflict,
    ShipmentTrackingLedgerService,
    ShipmentTrackingObservation,
)
from app.services.shipping.sf_waybill_provider import (
    SfWaybillProviderResult,
    SfWaybillQueryResult,
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
from app.services.shipping_execution_service import (
    ProviderOutcome,
    UnknownResolution,
)
from inventory_control import ControlDatabase
from inventory_control.jobs import AuthorityVerdict, OutcomeDisposition
from inventory_control.models.foundation import Tenant
from inventory_control.models.jobs import BackgroundJob
from inventory_control.routing import (
    DatabaseInstanceConfig,
    DatabaseInstanceRegistry,
    TenantEnginePoolSettings,
)
from tests.support.test_database import build_mysql_test_config


TENANT_UUID = "11111111-1111-4111-8111-111111111111"
SHIPMENT_UUID = "22222222-2222-4222-8222-222222222222"
ATTEMPT_UUID = "33333333-3333-4333-8333-333333333333"
JOB_UUID = "44444444-4444-4444-8444-444444444444"
SF_JOB_UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
INTEGRATION_UUID = "55555555-5555-4555-8555-555555555555"
ACCOUNT_UUID = "66666666-6666-4666-8666-666666666666"
INTEGRATION_REVISION_UUID = "77777777-7777-4777-8777-777777777777"
ACCOUNT_REVISION_UUID = "88888888-8888-4888-8888-888888888888"
UNIT_UUID = "99999999-9999-4999-8999-999999999999"
WAYBILL = "SF1234567890"
SUBMIT_DIGEST = "a" * 64
DELIVERY_DIGEST = "b" * 64
SUBMITTED_AT = datetime(2026, 8, 23, 9)


@pytest.fixture
def application(mysql_routed_database):
    del mysql_routed_database
    app = create_app(build_mysql_test_config())
    with app.app_context():
        try:
            yield app
        finally:
            db.session.remove()


@pytest.fixture
def mysql_relay_harness(mysql_routed_database):
    app = create_app(build_mysql_test_config())
    with app.app_context():
        try:
            yield app, mysql_routed_database
        finally:
            db.session.remove()


def _window(rental: Rental) -> tuple[datetime, datetime]:
    return (
        datetime.combine(rental.planned_ship_out_date, time.min),
        datetime.combine(
            rental.planned_return_date + timedelta(days=1),
            time.min,
        ),
    )


def _seed(application):
    session = db.session()
    with session.begin():
        warehouse = Warehouse(
            name="接力账本仓",
            status="active",
            setup_state="ready",
            is_default=True,
            default_slot=1,
            contact_name="负责人",
            contact_phone="13800138000",
            province="广东省",
            city="深圳市",
            district="南山区",
            address_detail="测试地址",
        )
        accessory_type = AccessoryType(
            name="relay-tripod",
            display_name="接力三脚架",
            tracking_mode="logical_unit",
        )
        device = Device(name="接力主设备", warehouse=warehouse)
        predecessor = Rental(
            device=device,
            start_date=date(2026, 9, 3),
            end_date=date(2026, 9, 5),
            planned_ship_out_date=date(2026, 9, 1),
            planned_return_date=date(2026, 9, 7),
            logistics_days=1,
            customer_name="前单",
        )
        successor = Rental(
            device=device,
            start_date=date(2026, 9, 7),
            end_date=date(2026, 9, 9),
            planned_ship_out_date=date(2026, 9, 5),
            planned_return_date=date(2026, 9, 11),
            logistics_days=1,
            customer_name="后单",
        )
        session.add_all(
            (warehouse, accessory_type, device, predecessor, successor)
        )
        session.flush()
        relay_case = RentalRelayCase(
            predecessor_rental_id=predecessor.id,
            successor_rental_id=successor.id,
            status="agreed",
        )
        unit = AccessoryUnit(
            id=UNIT_UUID,
            accessory_type=accessory_type,
            warehouse=warehouse,
            current_holder_rental_id=predecessor.id,
        )
        start_at, end_at = _window(predecessor)
        session.add_all(
            (
                relay_case,
                unit,
                RentalRelayBinding(
                    predecessor_rental_id=predecessor.id,
                    successor_rental_id=successor.id,
                    confirmed_at=SUBMITTED_AT,
                ),
                RentalAccessoryUnitLink(
                    rental_id=predecessor.id,
                    accessory_type_id=accessory_type.id,
                    accessory_unit_id=unit.id,
                    reservation_start_at=start_at,
                    reservation_end_at=end_at,
                ),
            )
        )
        session.flush()
        case_id = relay_case.id
        predecessor_id = predecessor.id
        successor_id = successor.id
        warehouse_id = warehouse.id
        warehouse_uuid = warehouse.warehouse_uuid

    with session.begin():
        AccessoryRelayChainService(session).recompute_from_case(
            relay_case_id=case_id,
            actor_type="tenant_user",
            actor_id="seed",
            operation_key="seed-relay-chain",
        )
        shipment = OutboundShipment(
            id=SHIPMENT_UUID,
            provider="sf",
            rental_id=successor_id,
            origin_warehouse_id=warehouse_id,
            origin_warehouse_uuid=warehouse_uuid,
            integration_uuid=INTEGRATION_UUID,
            provider_account_uuid=ACCOUNT_UUID,
            integration_secret_revision_uuid=INTEGRATION_REVISION_UUID,
            provider_account_secret_revision_uuid=ACCOUNT_REVISION_UUID,
            binding_revision=1,
            account_masked_hint="****1234",
            sender_snapshot={"safe": True},
            receiver_snapshot={"safe": True},
            cargo_snapshot={
                "items": [{"name": "租赁设备", "count": 1}]
            },
            tracking_check_phone_last4="8000",
            express_type_id=2,
            scheduled_dispatch_at=SUBMITTED_AT.replace(tzinfo=None),
            provider_order_id="sf:test:relay-projection",
            request_hash="c" * 64,
            waybill_no=WAYBILL,
            status="submitted",
            prepared_at=SUBMITTED_AT,
            submitted_at=SUBMITTED_AT,
        )
        attempt = ProviderOperationAttempt(
            id=ATTEMPT_UUID,
            shipment_id=SHIPMENT_UUID,
            operation="create_waybill",
            idempotency_key="sf:test:relay-projection:attempt-1",
            attempt_no=1,
            integration_secret_revision_uuid=INTEGRATION_REVISION_UUID,
            provider_account_secret_revision_uuid=ACCOUNT_REVISION_UUID,
            binding_revision=1,
            status="succeeded",
            response_hash=SUBMIT_DIGEST,
            started_at=SUBMITTED_AT,
            finished_at=SUBMITTED_AT,
        )
        session.add_all((shipment, attempt))
    return session, predecessor_id, successor_id, case_id


def _command(
    predecessor_id: int,
    successor_id: int,
    *,
    stage: str = "shipped",
    digest: str = SUBMIT_DIGEST,
    hour: int = 9,
) -> RelayExternalProjectionCommand:
    return RelayExternalProjectionCommand(
        shipment_uuid=SHIPMENT_UUID,
        predecessor_rental_id=predecessor_id,
        successor_rental_id=successor_id,
        stage=stage,
        waybill_no=WAYBILL,
        source_result_digest=digest,
        occurred_at=datetime(2026, 8, 23, hour, tzinfo=timezone.utc),
        tenant_timezone="Asia/Shanghai",
    )


def test_committed_shipment_projects_handoff_and_exact_replay(application):
    session, predecessor_id, successor_id, case_id = _seed(application)
    command = _command(predecessor_id, successor_id)

    with session.begin():
        first = RelayExternalProjectionService.apply(
            tenant_session=session,
            command=command,
        )
        assert first.status == "shipped"
        assert session.get(AccessoryUnit, UNIT_UUID).current_holder_rental_id == (
            successor_id
        )
        assert session.get(Rental, successor_id).ship_out_tracking_no == WAYBILL

    with session.begin():
        replay = RelayExternalProjectionService.apply(
            tenant_session=session,
            command=command,
        )
        assert replay == first
        assert session.scalar(
            sa.select(sa.func.count(AccessoryUnitEvent.id)).where(
                AccessoryUnitEvent.event_type == "relay_handoff",
                AccessoryUnitEvent.relay_case_id == case_id,
            )
        ) == 1
        audits = tuple(
            session.scalars(
                sa.select(AuditLog).where(
                    AuditLog.action == "relay_case_status_changed"
                )
            )
        )
        assert len(audits) == 1
        assert audits[0].details["source_result_digest"] == SUBMIT_DIGEST


def test_projection_rejects_unbound_digest_without_mutating_relay(application):
    session, predecessor_id, successor_id, case_id = _seed(application)
    command = _command(predecessor_id, successor_id, digest="d" * 64)

    with pytest.raises(RelayExternalProjectionConflict):
        with session.begin():
            RelayExternalProjectionService.apply(
                tenant_session=session,
                command=command,
            )

    with session.begin():
        assert session.get(RentalRelayCase, case_id).status == "agreed"
        assert session.get(AccessoryUnit, UNIT_UUID).current_holder_rental_id == (
            predecessor_id
        )
        assert session.scalar(sa.select(sa.func.count(AuditLog.id))) == 0


def test_delivered_projection_is_digest_bound_and_updates_tracking(application):
    session, predecessor_id, successor_id, case_id = _seed(application)
    shipped = _command(predecessor_id, successor_id)
    observation = ShipmentTrackingObservation(
        shipment_uuid=SHIPMENT_UUID,
        waybill_no=WAYBILL,
        status="delivered",
        occurred_at=datetime(2026, 8, 23, 10, tzinfo=timezone.utc),
    )
    delivered = _command(
        predecessor_id,
        successor_id,
        stage="completed",
        digest=observation.result_digest,
        hour=10,
    )
    with session.begin():
        RelayExternalProjectionService.apply(
            tenant_session=session,
            command=shipped,
        )
    with session.begin():
        ShipmentTrackingLedgerService.record(
            tenant_session=session,
            observation=observation,
        )
    with session.begin():
        receipt = RelayExternalProjectionService.apply(
            tenant_session=session,
            command=delivered,
        )
        relay_case = session.get(RentalRelayCase, case_id)
        assert receipt.status == "completed"
        assert relay_case.sf_tracking_status == "delivered"
        assert relay_case.sf_tracking_summary == "已签收"
        assert relay_case.sf_last_checked_at == datetime(2026, 8, 23, 10)

    conflicting_replay = _command(
        predecessor_id,
        successor_id,
        stage="completed",
        digest="e" * 64,
        hour=11,
    )
    with pytest.raises(RelayExternalProjectionConflict):
        with session.begin():
            RelayExternalProjectionService.apply(
                tenant_session=session,
                command=conflicting_replay,
            )
    with session.begin():
        relay_case = session.get(RentalRelayCase, case_id)
        assert relay_case.sf_last_checked_at == datetime(2026, 8, 23, 10)


def test_completed_projection_rejects_unpersisted_delivery_result(application):
    session, predecessor_id, successor_id, case_id = _seed(application)
    with session.begin():
        RelayExternalProjectionService.apply(
            tenant_session=session,
            command=_command(predecessor_id, successor_id),
        )

    with pytest.raises(RelayExternalProjectionConflict):
        with session.begin():
            RelayExternalProjectionService.apply(
                tenant_session=session,
                command=_command(
                    predecessor_id,
                    successor_id,
                    stage="completed",
                    digest=DELIVERY_DIGEST,
                    hour=10,
                ),
            )

    with session.begin():
        assert session.get(RentalRelayCase, case_id).status == "shipped"


def test_tracking_ledger_records_exact_delivery_once_and_rejects_tamper(
    application,
):
    session, _predecessor_id, _successor_id, _case_id = _seed(application)
    observation = ShipmentTrackingObservation(
        shipment_uuid=SHIPMENT_UUID,
        waybill_no=WAYBILL,
        status="delivered",
        occurred_at=datetime(2026, 8, 23, 10, tzinfo=timezone.utc),
    )
    with session.begin():
        first = ShipmentTrackingLedgerService.record(
            tenant_session=session,
            observation=observation,
        )
        replay = ShipmentTrackingLedgerService.record(
            tenant_session=session,
            observation=observation,
        )
        assert replay.audit_id == first.audit_id
        assert replay.idempotent_replay is True
        assert session.scalar(
            sa.select(sa.func.count(AuditLog.id)).where(
                AuditLog.action == SHIPMENT_TRACKING_RESULT_ACTION
            )
        ) == 1

    with session.begin():
        audit = session.get(AuditLog, first.audit_id)
        audit.details = {**audit.details, "unexpected": True}
    with pytest.raises(ShipmentTrackingLedgerConflict):
        with session.begin():
            ShipmentTrackingLedgerService.require_delivered(
                tenant_session=session,
                shipment_uuid=SHIPMENT_UUID,
                waybill_no=WAYBILL,
                result_digest=observation.result_digest,
                occurred_at=observation.occurred_at,
            )


class _Store:
    def __init__(self, *, conflict: bool = False) -> None:
        self.conflict = conflict
        self.prepared = []

    def apply(self, prepared):
        self.prepared.append(prepared)
        if self.conflict:
            raise RelayExternalProjectionConflict()
        return RelayExternalProjectionReceipt(
            shipment_uuid=prepared.command.shipment_uuid,
            relay_case_id=7,
            status=prepared.command.stage.value,
            source_result_digest=prepared.command.source_result_digest,
        )


def _job(command: RelayExternalProjectionCommand) -> BackgroundJob:
    return BackgroundJob(
        id=JOB_UUID,
        tenant_id=TENANT_UUID,
        tenant_access_version=3,
        job_type=RELAY_EXTERNAL_PROJECTION_JOB_TYPE,
        resource_key=command.resource_key,
        payload=command.payload(),
        idempotency_key=command.idempotency_key,
        requested_by_type="worker",
        request_id="relay-result-request",
        available_at=command.occurred_at,
    )


def test_durable_job_handler_parses_exact_identity_and_never_crosses_provider():
    command = _command(1, 2)
    job = _job(command)
    store = _Store()
    handler = RelayExternalProjectionJobHandler(store=store)

    prepared = handler.prepare(job)
    outcome = handler.execute(job, prepared)

    assert handler.crosses_provider_boundary is False
    assert handler.recovery_category is None
    assert outcome.disposition is OutcomeDisposition.SUCCEEDED
    assert outcome.safe_result == {
        "stage": "shipped",
        "relay_status": "shipped",
    }
    assert store.prepared[0].tenant_uuid == TENANT_UUID
    assert store.prepared[0].tenant_access_version == 3
    assert store.prepared[0].command == command

    job.resource_key = "relay-shipment:wrong"
    with pytest.raises(RelayExternalProjectionInputError):
        handler.prepare(job)


def test_durable_handler_quarantines_conflict_and_coordinator_is_idempotent():
    command = _command(1, 2)
    job = _job(command)
    handler = RelayExternalProjectionJobHandler(store=_Store(conflict=True))
    outcome = handler.execute(job, handler.prepare(job))
    assert outcome.disposition is OutcomeDisposition.REVIEW
    assert outcome.reason_code == "relay_projection_conflict"

    calls = []

    class _JobService:
        def enqueue_job(self, session, **values):
            calls.append((session, values))
            return SimpleNamespace(**values)

    with Session() as control_session:
        with control_session.begin():
            queued = RelayExternalProjectionCoordinator(
                service=_JobService()
            ).enqueue(
                control_session,
                tenant_uuid=TENANT_UUID,
                tenant_access_version=3,
                command=command,
                available_at=command.occurred_at,
                request_id="request-1",
            )
    assert queued.job_type == RELAY_EXTERNAL_PROJECTION_JOB_TYPE
    assert queued.resource_key == command.resource_key
    assert queued.idempotency_key == command.idempotency_key
    assert queued.payload == command.payload()
    assert queued.requested_by_type == "worker"
    assert len(calls) == 1


def test_committed_shipping_signal_enqueues_one_current_direct_job(
    application, mysql_routed_database
):
    session, predecessor_id, successor_id, _case_id = _seed(application)
    with session.begin():
        signal = RelayShipmentResultSignalService.capture(
            tenant_session=session,
            attempt_uuid=ATTEMPT_UUID,
        )
    assert signal is not None
    assert signal.predecessor_rental_id == predecessor_id
    assert signal.successor_rental_id == successor_id
    assert signal.source_result_digest == SUBMIT_DIGEST

    database = mysql_routed_database
    try:
        with database.transaction() as control_session:
            control_session.add(
                Tenant(
                    id=TENANT_UUID,
                    status="active",
                    access_version=3,
                    timezone="Asia/Shanghai",
                )
            )
        enqueuer = RelayCommittedShipmentResultEnqueuer(
            control_database=database
        )
        first = enqueuer.enqueue(
            tenant_uuid=TENANT_UUID,
            signal=signal,
            available_at=signal.occurred_at,
            request_id="shipment-result-request",
        )
        replay = enqueuer.enqueue(
            tenant_uuid=TENANT_UUID,
            signal=signal,
            available_at=signal.occurred_at,
            request_id="shipment-result-request",
        )
        with database.new_session() as control_session:
            jobs = tuple(control_session.scalars(sa.select(BackgroundJob)))
        assert replay.id == first.id
        assert len(jobs) == 1
        assert jobs[0].tenant_access_version == 3
        assert jobs[0].job_type == RELAY_EXTERNAL_PROJECTION_JOB_TYPE
        assert jobs[0].payload["tenant_timezone"] == "Asia/Shanghai"
        assert jobs[0].payload["source_result_digest"] == SUBMIT_DIGEST
    finally:
        pass


def test_shipping_signal_is_absent_for_non_agreed_ordinary_shipment(application):
    session, _predecessor_id, _successor_id, case_id = _seed(application)
    with session.begin():
        session.get(RentalRelayCase, case_id).status = "pending"
    with session.begin():
        assert RelayShipmentResultSignalService.capture(
            tenant_session=session,
            attempt_uuid=ATTEMPT_UUID,
        ) is None


def test_fake_sf_worker_success_reaches_direct_relay_handoff(
    mysql_relay_harness,
):
    application, database = mysql_relay_harness
    session, predecessor_id, successor_id, _case_id = _seed(application)
    with session.begin():
        shipment = session.get(OutboundShipment, SHIPMENT_UUID)
        attempt = session.get(ProviderOperationAttempt, ATTEMPT_UUID)
        shipment.status = "prepared"
        shipment.waybill_no = None
        shipment.submitted_at = None
        attempt.status = "prepared"
        attempt.response_hash = None
        attempt.started_at = None
        attempt.finished_at = None

    @contextmanager
    def tenant_transaction(_prepared):
        with session.begin():
            yield session

    calls = []

    class Request:
        def discard_credentials(self):
            calls.append("discard_credentials")

    class Credentials:
        def prepare(self, *, job, snapshot):
            assert snapshot.shipment_uuid == job.shipment_uuid
            calls.append("credentials")
            return Request()

    class Dispatcher:
        def dispatch(self, _request):
            calls.append("provider")
            return SfWaybillProviderResult(
                outcome=ProviderOutcome.SUCCESS,
                waybill_no=WAYBILL,
                response_hash=SUBMIT_DIGEST,
                latency_ms=5,
            )

    class Authorizer:
        def authorize(self, _job):
            calls.append("authorize")
            return AuthorityVerdict(True)

    try:
        with database.transaction() as control_session:
            control_session.add(
                Tenant(
                    id=TENANT_UUID,
                    status="active",
                    access_version=3,
                    timezone="Asia/Shanghai",
                )
            )
        sf_job = BackgroundJob(
            id=SF_JOB_UUID,
            tenant_id=TENANT_UUID,
            tenant_access_version=3,
            job_type=SF_CREATE_WAYBILL_JOB_TYPE,
            resource_key=f"sf-shipment:{SHIPMENT_UUID}",
            payload={
                "contract_version": 1,
                "shipment_uuid": SHIPMENT_UUID,
                "attempt_uuid": ATTEMPT_UUID,
            },
            idempotency_key=f"sf-create:{ATTEMPT_UUID}",
            requested_by_type="tenant_user",
            request_id="fake-sf-create-request",
            available_at=datetime(2026, 8, 23, 10, tzinfo=timezone.utc),
        )
        handler = SfCreateWaybillJobHandler(
            tenant_store=SqlAlchemySfWaybillTenantStore(
                tenant_transaction
            ),
            credential_source=Credentials(),
            provider_dispatcher=Dispatcher(),
            call_authorizer=Authorizer(),
            relay_enqueuer=RelayCommittedShipmentResultEnqueuer(
                control_database=database
            ),
            clock=lambda: datetime(
                2026,
                8,
                23,
                10,
                tzinfo=timezone.utc,
            ),
        )

        outcome = handler.execute(sf_job, handler.prepare(sf_job))

        assert outcome.disposition is OutcomeDisposition.SUCCEEDED
        assert outcome.safe_result["relay_direct_enqueued"] is True
        with session.begin():
            assert session.get(OutboundShipment, SHIPMENT_UUID).status == (
                "submitted"
            )
            assert session.get(ProviderOperationAttempt, ATTEMPT_UUID).status == (
                "succeeded"
            )
        with database.new_session() as control_session:
            direct = control_session.scalar(
                sa.select(BackgroundJob).where(
                    BackgroundJob.job_type
                    == RELAY_EXTERNAL_PROJECTION_JOB_TYPE
                )
            )
            assert direct is not None
            control_session.expunge(direct)

        class ProjectionStore:
            def apply(self, prepared):
                with session.begin():
                    return RelayExternalProjectionService.apply(
                        tenant_session=session,
                        command=prepared.command,
                    )

        projection = RelayExternalProjectionJobHandler(
            store=ProjectionStore()
        )
        projected = projection.execute(direct, projection.prepare(direct))

        assert projected.disposition is OutcomeDisposition.SUCCEEDED
        with session.begin():
            assert session.get(RentalRelayCase, _case_id).status == "shipped"
            assert session.get(AccessoryUnit, UNIT_UUID).current_holder_rental_id == (
                successor_id
            )
        assert predecessor_id != successor_id
        assert calls == [
            "authorize",
            "credentials",
            "authorize",
            "provider",
            "discard_credentials",
            "authorize",
        ]
    finally:
        db.session.remove()


def test_unknown_sf_query_claim_resolves_to_committed_relay_signal(application):
    session, predecessor_id, successor_id, _case_id = _seed(application)
    with session.begin():
        shipment = session.get(OutboundShipment, SHIPMENT_UUID)
        attempt = session.get(ProviderOperationAttempt, ATTEMPT_UUID)
        shipment.status = "provider_submitting"
        shipment.waybill_no = None
        shipment.submitted_at = None
        attempt.status = "provider_submitting"
        attempt.response_hash = None
        attempt.finished_at = None

    @contextmanager
    def tenant_transaction(_context):
        with session.begin():
            yield session

    store = SqlAlchemySfWaybillReconciliationStore(tenant_transaction)
    prepared = PreparedSfWaybillReconciliationJob(
        job_uuid=SF_JOB_UUID,
        tenant_uuid=TENANT_UUID,
        tenant_access_version=3,
        request_id="fake-sf-query",
    )

    snapshot = store.claim_one(
        prepared,
        started_at=datetime(2026, 8, 23, 10, tzinfo=timezone.utc),
    )

    assert snapshot is not None
    assert snapshot.shipment_uuid == SHIPMENT_UUID
    assert store.claim_one(
        prepared,
        started_at=datetime(2026, 8, 23, 10, tzinfo=timezone.utc),
    ) is None
    stored = store.record_result(
        prepared,
        snapshot=snapshot,
        result=SfWaybillQueryResult(
            resolution=UnknownResolution.CONFIRMED_SUCCESS,
            safe_provider_code="SF_QUERY_CONFIRMED",
            waybill_no=WAYBILL,
            response_hash=SUBMIT_DIGEST,
        ),
        finished_at=datetime(2026, 8, 23, 10, tzinfo=timezone.utc),
    )

    assert stored.resolution is UnknownResolution.CONFIRMED_SUCCESS
    assert stored.relay_signal is not None
    assert stored.relay_signal.predecessor_rental_id == predecessor_id
    assert stored.relay_signal.successor_rental_id == successor_id
    with session.begin():
        assert session.get(OutboundShipment, SHIPMENT_UUID).status == "submitted"
        assert session.get(ProviderOperationAttempt, ATTEMPT_UUID).status == (
            "succeeded"
        )


def test_projection_requires_explicit_transaction(application):
    session, predecessor_id, successor_id, _case_id = _seed(application)
    with pytest.raises(RelayExternalProjectionInputError):
        RelayExternalProjectionService.apply(
            tenant_session=session,
            command=_command(predecessor_id, successor_id),
        )


def test_periodic_reconciliation_projects_oldest_committed_shipment_once(
    application,
):
    session, predecessor_id, successor_id, _case_id = _seed(application)

    with session.begin():
        receipt = RelayExternalReconciliationService.reconcile_one(
            tenant_session=session,
            tenant_timezone="Asia/Shanghai",
        )
        assert receipt is not None
        assert receipt.shipment_uuid == SHIPMENT_UUID
        assert receipt.status == "shipped"
        assert session.get(AccessoryUnit, UNIT_UUID).current_holder_rental_id == (
            successor_id
        )

    with session.begin():
        assert RelayExternalReconciliationService.reconcile_one(
            tenant_session=session,
            tenant_timezone="Asia/Shanghai",
        ) is None
        assert session.scalar(
            sa.select(sa.func.count(AccessoryUnitEvent.id)).where(
                AccessoryUnitEvent.event_type == "relay_handoff"
            )
        ) == 1
        relay_case = session.scalar(
            sa.select(RentalRelayCase).where(
                RentalRelayCase.predecessor_rental_id == predecessor_id,
                RentalRelayCase.successor_rental_id == successor_id,
            )
        )
        assert relay_case is not None and relay_case.status == "shipped"


class _ReconciliationStore:
    def __init__(self, *, receipt=None, conflict=False):
        self.receipt = receipt
        self.conflict = conflict
        self.prepared = []

    def reconcile(self, prepared):
        self.prepared.append(prepared)
        if self.conflict:
            raise RelayExternalProjectionConflict()
        return self.receipt


def _reconciliation_job() -> BackgroundJob:
    return BackgroundJob(
        id=JOB_UUID,
        tenant_id=TENANT_UUID,
        tenant_access_version=3,
        job_type=RELAY_EXTERNAL_RECONCILIATION_JOB_TYPE,
        resource_key=RELAY_EXTERNAL_RECONCILIATION_RESOURCE_KEY,
        payload={
            "contract_version": 1,
            "tenant_timezone": "Asia/Shanghai",
        },
        idempotency_key=(
            f"scheduler:{RELAY_EXTERNAL_RECONCILIATION_JOB_TYPE}:123"
        ),
        requested_by_type="scheduler",
        request_id="relay-reconciliation-request",
        available_at=datetime(2026, 8, 23, 9, tzinfo=timezone.utc),
    )


def test_reconciliation_job_is_strict_provider_free_and_reviewable():
    receipt = RelayExternalProjectionReceipt(
        shipment_uuid=SHIPMENT_UUID,
        relay_case_id=7,
        status="shipped",
        source_result_digest=SUBMIT_DIGEST,
    )
    store = _ReconciliationStore(receipt=receipt)
    handler = RelayExternalReconciliationJobHandler(store=store)
    job = _reconciliation_job()

    outcome = handler.execute(job, handler.prepare(job))

    assert handler.crosses_provider_boundary is False
    assert handler.recovery_category is None
    assert outcome.disposition is OutcomeDisposition.SUCCEEDED
    assert outcome.safe_result == {
        "projected": True,
        "stage": "shipped",
        "relay_status": "shipped",
    }
    assert store.prepared[0].tenant_uuid == TENANT_UUID
    assert store.prepared[0].tenant_access_version == 3
    assert store.prepared[0].tenant_timezone == "Asia/Shanghai"

    conflict_handler = RelayExternalReconciliationJobHandler(
        store=_ReconciliationStore(conflict=True)
    )
    conflict = conflict_handler.execute(
        job,
        conflict_handler.prepare(job),
    )
    assert conflict.disposition is OutcomeDisposition.REVIEW
    assert conflict.reason_code == "relay_reconciliation_conflict"

    job.resource_key = "relay:wrong"
    with pytest.raises(RelayExternalProjectionError):
        handler.prepare(job)


class _Authority:
    def lock_current_job_authority(self, _session, *, job, phase):
        return job.id, phase

    def evaluate_locked_job_authority(
        self,
        _session,
        *,
        locked_authority,
        job,
        phase,
        now,
    ):
        del now
        return AuthorityVerdict(locked_authority == (job.id, phase))


def test_relay_capability_registers_direct_and_reconciliation_jobs_without_io(
    tmp_path: Path,
):
    database = ControlDatabase(
        engine=SimpleNamespace(dispose=lambda: None),
        session_factory=object(),
    )
    capability = build_relay_external_projection_capability(
            control_database=database,
            authority=_Authority(),
            root_key_directory=tmp_path,
            database_instances=DatabaseInstanceRegistry(
                [
                    DatabaseInstanceConfig(
                        key="primary",
                        host="mysql.internal",
                    )
                ]
            ),
            engine_pool_settings=TenantEnginePoolSettings(),
            max_cache_entries=8,
        )

    assert set(capability.handlers) == {
        RELAY_EXTERNAL_PROJECTION_JOB_TYPE,
        RELAY_EXTERNAL_RECONCILIATION_JOB_TYPE,
    }
    assert [definition.job_type for definition in capability.schedules] == [
        RELAY_EXTERNAL_RECONCILIATION_JOB_TYPE
    ]
