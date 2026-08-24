from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from app.services.relay.result_signal import RelayShipmentSubmissionSignal
from app.services.relay.external_projection import (
    RELAY_EXTERNAL_PROJECTION_JOB_TYPE,
)
from app.services.relay.reconciliation import (
    RELAY_EXTERNAL_RECONCILIATION_JOB_TYPE,
)
from app.services.shipping.sf_relay_process import build_sf_relay_job_process
from app.services.shipping.sf_waybill_provider import (
    SfWaybillProviderDispatcher,
    SfWaybillProviderResult,
    SfWaybillProviderSettings,
    SfWaybillQueryDispatcher,
    SfWaybillQueryResult,
)
from app.services.shipping.sf_waybill_intent import (
    SF_WAYBILL_INTENT_JOB_TYPE,
    SF_WAYBILL_INTENT_RESOURCE_KEY,
    SfWaybillIntentJobHandler,
    SfWaybillIntentPersistenceError,
    SfWaybillIntentSignal,
    SqlAlchemySfWaybillIntentEnqueuer,
)
from app.services.shipping.sf_waybill_reconciliation import (
    SF_WAYBILL_RECONCILIATION_JOB_TYPE,
    SF_WAYBILL_RECONCILIATION_RESOURCE_KEY,
    SfWaybillReconciliationJobHandler,
    SfWaybillReconciliationSnapshot,
    StoredSfWaybillReconciliation,
)
from app.services.shipping.sf_waybill_composition import (
    build_sf_waybill_capability,
)
from app.services.shipping.sf_waybill_worker import (
    SF_CREATE_WAYBILL_JOB_TYPE,
    PreparedSfWaybillJob,
    SfCreateWaybillJobCoordinator,
    SfCreateWaybillJobHandler,
    SfWaybillSubmissionSnapshot,
)
from app.services.shipping_execution_service import (
    ProviderOutcome,
    UnknownResolution,
)
from inventory_control import ControlDatabase
from inventory_control.integrations import (
    SfCreateWaybillRequest,
    SfProviderExecutionContext,
    SfWaybillCredentialError,
    SfWaybillQueryRequest,
)
from inventory_control.jobs import (
    AuthorityVerdict,
    OutcomeDisposition,
    RetryBackoffPolicy,
    ScheduleGateVerdict,
)
from inventory_control.models.foundation import Tenant
from inventory_control.models.jobs import BackgroundJob
from inventory_control.routing import (
    DatabaseInstanceConfig,
    DatabaseInstanceRegistry,
    TenantEnginePoolSettings,
)


NOW = datetime(2026, 8, 23, 9, tzinfo=timezone.utc)
TENANT_UUID = "11111111-1111-4111-8111-111111111111"
SHIPMENT_UUID = "22222222-2222-4222-8222-222222222222"
ATTEMPT_UUID = "33333333-3333-4333-8333-333333333333"
JOB_UUID = "44444444-4444-4444-8444-444444444444"
ACTOR_UUID = "55555555-5555-4555-8555-555555555555"
WAREHOUSE_UUID = "66666666-6666-4666-8666-666666666666"
INTEGRATION_UUID = "77777777-7777-4777-8777-777777777777"
ACCOUNT_UUID = "88888888-8888-4888-8888-888888888888"
INTEGRATION_REVISION_UUID = "99999999-9999-4999-8999-999999999999"
ACCOUNT_REVISION_UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CLAIM_UUID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
RESULT_DIGEST = "c" * 64


class _Request:
    def __init__(self, calls):
        self.calls = calls
        self.discarded = False

    def discard_credentials(self):
        self.calls.append("discard")
        self.discarded = True


class _Authorizer:
    def __init__(self, calls, verdicts=None):
        self.calls = calls
        self.verdicts = list(verdicts or [AuthorityVerdict(True)] * 3)

    def authorize(self, _job):
        self.calls.append("authorize")
        return self.verdicts.pop(0)


class _Store:
    def __init__(self, calls, *, relay=True):
        self.calls = calls
        self.relay = relay
        self.result = None

    def load_snapshot(self, prepared):
        self.calls.append("load_snapshot")
        return SfWaybillSubmissionSnapshot(
            tenant_uuid=prepared.tenant_uuid,
            shipment_uuid=prepared.shipment_uuid,
            attempt_uuid=prepared.attempt_uuid,
            origin_warehouse_uuid=WAREHOUSE_UUID,
            integration_uuid=INTEGRATION_UUID,
            provider_account_uuid=ACCOUNT_UUID,
            integration_secret_revision_uuid=INTEGRATION_REVISION_UUID,
            provider_account_secret_revision_uuid=ACCOUNT_REVISION_UUID,
            binding_revision=1,
            sender_snapshot={"safe": True},
            receiver_snapshot={"safe": True},
            cargo_snapshot={
                "items": [{"name": "租赁设备", "count": 1}]
            },
            express_type_id=2,
            scheduled_dispatch_at=NOW.replace(tzinfo=None),
        )

    def mark_submitting(self, _prepared, *, started_at):
        assert started_at == NOW
        self.calls.append("mark_submitting")

    def record_result(self, prepared, *, result, finished_at):
        assert finished_at == NOW
        self.calls.append("record_result")
        self.result = result
        signal = None
        if self.relay and result.outcome is ProviderOutcome.SUCCESS:
            signal = RelayShipmentSubmissionSignal(
                shipment_uuid=prepared.shipment_uuid,
                predecessor_rental_id=1,
                successor_rental_id=2,
                waybill_no=result.waybill_no,
                source_result_digest=result.response_hash,
                occurred_at=NOW,
            )
        return type(
            "Stored",
            (),
            {
                "shipment_uuid": prepared.shipment_uuid,
                "attempt_uuid": prepared.attempt_uuid,
                "outcome": result.outcome,
                "relay_signal": signal,
            },
        )()


class _Credentials:
    def __init__(self, calls, request):
        self.calls = calls
        self.request = request

    def prepare(self, *, job, snapshot):
        assert snapshot.shipment_uuid == job.shipment_uuid
        self.calls.append("credentials")
        return self.request


class _Dispatcher:
    def __init__(self, calls, result):
        self.calls = calls
        self.result = result

    def dispatch(self, _request):
        self.calls.append("provider")
        return self.result


class _Relay:
    def __init__(self, calls, *, fail=False):
        self.calls = calls
        self.fail = fail
        self.signals = []

    def enqueue(self, **values):
        self.calls.append("relay_enqueue")
        if self.fail:
            raise RuntimeError("synthetic enqueue response loss")
        self.signals.append(values["signal"])
        return object()


def _job() -> BackgroundJob:
    return BackgroundJob(
        id=JOB_UUID,
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
        requested_by_id=ACTOR_UUID,
        request_id="waybill-request",
        available_at=NOW,
    )


def _handler(calls, *, result, verdicts=None, relay=True, relay_fail=False):
    request = _Request(calls)
    store = _Store(calls, relay=relay)
    relay_sink = _Relay(calls, fail=relay_fail)
    handler = SfCreateWaybillJobHandler(
        tenant_store=store,
        credential_source=_Credentials(calls, request),
        provider_dispatcher=_Dispatcher(calls, result),
        call_authorizer=_Authorizer(calls, verdicts),
        relay_enqueuer=relay_sink,
        clock=lambda: NOW,
    )
    return handler, store, request, relay_sink


def test_success_uses_three_authority_checks_and_enqueues_after_result():
    calls = []
    result = SfWaybillProviderResult(
        outcome="success",
        waybill_no="SF1234567890",
        response_hash=RESULT_DIGEST,
        latency_ms=5,
    )
    handler, store, _request, relay = _handler(calls, result=result)
    job = _job()

    outcome = handler.execute(job, handler.prepare(job))

    assert outcome.disposition is OutcomeDisposition.SUCCEEDED
    assert outcome.safe_result == {
        "shipment_uuid": SHIPMENT_UUID,
        "provider_outcome": "success",
        "relay_direct_enqueued": True,
    }
    assert calls == [
        "authorize",
        "load_snapshot",
        "credentials",
        "mark_submitting",
        "authorize",
        "provider",
        "discard",
        "authorize",
        "record_result",
        "relay_enqueue",
    ]
    assert store.result == result
    assert relay.signals[0].source_result_digest == RESULT_DIGEST


def test_unknown_result_is_persisted_and_never_enqueued_or_retried():
    calls = []
    result = SfWaybillProviderResult(
        outcome="unknown",
        safe_provider_code="SF_PROVIDER_RESULT_UNKNOWN",
    )
    handler, store, _request, relay = _handler(calls, result=result)
    job = _job()

    outcome = handler.execute(job, handler.prepare(job))

    assert outcome.disposition is OutcomeDisposition.REVIEW
    assert outcome.reason_code == "sf_provider_result_unknown"
    assert store.result.outcome is ProviderOutcome.UNKNOWN
    assert relay.signals == []


def test_direct_enqueue_loss_keeps_known_provider_success_terminal():
    calls = []
    result = SfWaybillProviderResult(
        outcome="success",
        waybill_no="SF1234567890",
        response_hash=RESULT_DIGEST,
    )
    handler, store, _request, relay = _handler(
        calls,
        result=result,
        relay_fail=True,
    )
    job = _job()

    outcome = handler.execute(job, handler.prepare(job))

    assert outcome.disposition is OutcomeDisposition.SUCCEEDED
    assert outcome.safe_result["relay_direct_enqueued"] is False
    assert store.result.outcome is ProviderOutcome.SUCCESS
    assert relay.signals == []


def test_denial_before_credentials_does_not_open_provider_or_tenant_store():
    calls = []
    result = SfWaybillProviderResult(
        outcome="success",
        waybill_no="SF1234567890",
        response_hash=RESULT_DIGEST,
    )
    handler, store, _request, relay = _handler(
        calls,
        result=result,
        verdicts=[AuthorityVerdict(False, "TENANT_SUSPENDED")],
    )
    job = _job()

    outcome = handler.execute(job, handler.prepare(job))

    assert outcome.disposition is OutcomeDisposition.REVIEW
    assert outcome.reason_code == "TENANT_SUSPENDED"
    assert calls == ["authorize"]
    assert store.result is None
    assert relay.signals == []


def test_job_parser_rejects_payload_or_identity_drift():
    handler, _store, _request, _relay = _handler(
        [],
        result=SfWaybillProviderResult(
            outcome="unknown",
            safe_provider_code="SF_PROVIDER_RESULT_UNKNOWN",
        ),
    )
    job = _job()
    parsed = handler.prepare(job).value
    assert isinstance(parsed, PreparedSfWaybillJob)
    job.resource_key = "sf-shipment:wrong"
    with pytest.raises(Exception):
        handler.prepare(job)


def test_control_coordinator_is_current_tenant_bound_and_idempotent(
    mysql_control_database,
):
    database = mysql_control_database
    with database.transaction() as session:
        session.add(
            Tenant(
                id=TENANT_UUID,
                status="active",
                access_version=3,
                timezone="Asia/Shanghai",
            )
        )
    coordinator = SfCreateWaybillJobCoordinator()
    with database.transaction() as session:
        first = coordinator.enqueue(
            session,
            tenant_uuid=TENANT_UUID,
            tenant_access_version=3,
            shipment_uuid=SHIPMENT_UUID,
            attempt_uuid=ATTEMPT_UUID,
            requested_by_user_uuid=ACTOR_UUID,
            available_at=NOW,
            job_uuid=JOB_UUID,
        )
        replay = coordinator.enqueue(
            session,
            tenant_uuid=TENANT_UUID,
            tenant_access_version=3,
            shipment_uuid=SHIPMENT_UUID,
            attempt_uuid=ATTEMPT_UUID,
            requested_by_user_uuid=ACTOR_UUID,
            available_at=NOW,
            job_uuid=JOB_UUID,
        )
        assert replay.id == first.id == JOB_UUID
    with database.new_session() as session:
        jobs = tuple(session.scalars(sa.select(BackgroundJob)))
    assert len(jobs) == 1
    assert jobs[0].max_attempts == 1
    assert jobs[0].payload["attempt_uuid"] == ATTEMPT_UUID


def _intent_job() -> BackgroundJob:
    return BackgroundJob(
        id="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        tenant_id=TENANT_UUID,
        tenant_access_version=3,
        job_type=SF_WAYBILL_INTENT_JOB_TYPE,
        resource_key=SF_WAYBILL_INTENT_RESOURCE_KEY,
        payload={"contract_version": 1},
        idempotency_key=f"scheduler:{SF_WAYBILL_INTENT_JOB_TYPE}:bucket-1",
        requested_by_type="scheduler",
        request_id="sf-waybill-intent-reconciliation",
        max_attempts=3,
        available_at=NOW,
    )


def _intent_signal(*, tenant_access_version=3):
    return SfWaybillIntentSignal(
        tenant_uuid=TENANT_UUID,
        tenant_access_version=tenant_access_version,
        job_uuid=JOB_UUID,
        shipment_uuid=SHIPMENT_UUID,
        attempt_uuid=ATTEMPT_UUID,
        requested_by_user_uuid=ACTOR_UUID,
        request_id="waybill-request",
        correlation_id="waybill-correlation",
    )


def test_intent_retry_replays_exact_control_job_after_ack_response_loss(
    mysql_control_database,
):
    database = mysql_control_database
    calls = []

    class Store:
        def discover_one(self, _prepared):
            calls.append("discover")
            return _intent_signal()

        def acknowledge_enqueued(
            self,
            _prepared,
            *,
            signal,
            acknowledged_at,
        ):
            assert signal.job_uuid == JOB_UUID
            assert acknowledged_at == NOW
            calls.append("ack")
            if calls.count("ack") == 1:
                raise SfWaybillIntentPersistenceError()
            return True

    try:
        with database.transaction() as session:
            session.add(
                Tenant(
                    id=TENANT_UUID,
                    status="active",
                    access_version=3,
                    timezone="Asia/Shanghai",
                )
            )
        handler = SfWaybillIntentJobHandler(
            store=Store(),
            enqueuer=SqlAlchemySfWaybillIntentEnqueuer(
                control_database=database,
            ),
            clock=lambda: NOW,
        )
        scheduled_job = _intent_job()

        first = handler.execute(scheduled_job, handler.prepare(scheduled_job))
        second = handler.execute(scheduled_job, handler.prepare(scheduled_job))

        assert first.disposition is OutcomeDisposition.RETRY
        assert first.reason_code == "sf_waybill_intent_ack_failed"
        assert second.disposition is OutcomeDisposition.SUCCEEDED
        assert second.safe_result == {
            "enqueued": True,
            "acknowledged": True,
            "shipment_uuid": SHIPMENT_UUID,
        }
        with database.new_session() as session:
            jobs = tuple(
                session.scalars(
                    sa.select(BackgroundJob).where(
                        BackgroundJob.job_type == SF_CREATE_WAYBILL_JOB_TYPE
                    )
                )
            )
        assert len(jobs) == 1
        assert jobs[0].id == JOB_UUID
        assert jobs[0].requested_by_id == ACTOR_UUID
        assert calls == ["discover", "ack", "discover", "ack"]
    finally:
        pass


def test_intent_enqueue_denies_stale_tenant_access_version(
    mysql_control_database,
):
    database = mysql_control_database

    class Store:
        def discover_one(self, _prepared):
            return _intent_signal(tenant_access_version=2)

        def acknowledge_enqueued(self, *_args, **_kwargs):
            raise AssertionError("denied intent must not be acknowledged")

    try:
        with database.transaction() as session:
            session.add(
                Tenant(
                    id=TENANT_UUID,
                    status="active",
                    access_version=3,
                    timezone="Asia/Shanghai",
                )
            )
        handler = SfWaybillIntentJobHandler(
            store=Store(),
            enqueuer=SqlAlchemySfWaybillIntentEnqueuer(
                control_database=database,
            ),
            clock=lambda: NOW,
        )

        outcome = handler.execute(
            _intent_job(),
            handler.prepare(_intent_job()),
        )

        assert outcome.disposition is OutcomeDisposition.REVIEW
        assert outcome.reason_code == "sf_waybill_intent_authority_denied"
        with database.new_session() as session:
            assert session.scalar(
                sa.select(sa.func.count()).select_from(BackgroundJob)
            ) == 0
    finally:
        pass


def _provider_request() -> SfCreateWaybillRequest:
    context = SfProviderExecutionContext(
        tenant_uuid=TENANT_UUID,
        warehouse_uuid=WAREHOUSE_UUID,
        provider_account_uuid=ACCOUNT_UUID,
        integration_uuid=INTEGRATION_UUID,
        integration_secret_revision_uuid=INTEGRATION_REVISION_UUID,
        provider_account_secret_revision_uuid=ACCOUNT_REVISION_UUID,
        global_claim_uuid=CLAIM_UUID,
        claim_generation=1,
        binding_revision=1,
        masked_account_hint="****1234",
        historical=True,
    )
    return SfCreateWaybillRequest(
        context=context,
        shipment_uuid=SHIPMENT_UUID,
        sender_snapshot={"contact": "sender"},
        receiver_snapshot={"contact": "receiver"},
        cargo_snapshot={
            "items": [{"name": "租赁设备", "count": 1}]
        },
        express_type_id=2,
        scheduled_dispatch_at=NOW.replace(tzinfo=None),
        integration_credentials={
            "partner_id": "fake-partner",
            "checkword": "fake-checkword",
        },
        account_secret="fake-account",
    )


def test_provider_dispatcher_consumes_request_and_classifies_exception_unknown():
    class Adapter:
        def create_waybill(self, *, request, settings):
            assert settings.test_mode is True
            request.take_credentials()
            raise RuntimeError("synthetic provider failure")

    request = _provider_request()
    dispatcher = SfWaybillProviderDispatcher(
        adapter=Adapter(),
        settings=SfWaybillProviderSettings(
            test_mode=True,
            connect_timeout_seconds=1,
            read_timeout_seconds=1,
        ),
    )

    result = dispatcher.dispatch(request)

    assert result.outcome is ProviderOutcome.UNKNOWN
    assert result.safe_provider_code == "SF_PROVIDER_RESULT_UNKNOWN"
    with pytest.raises(SfWaybillCredentialError):
        request.take_credentials()


def _query_request() -> SfWaybillQueryRequest:
    return SfWaybillQueryRequest(
        context=_provider_request().context,
        shipment_uuid=SHIPMENT_UUID,
        integration_credentials={
            "partner_id": "fake-partner",
            "checkword": "fake-checkword",
        },
        account_secret="fake-account",
    )


def test_query_dispatcher_consumes_request_and_classifies_exception_unknown():
    class Adapter:
        def query_waybill(self, *, request, settings):
            assert settings.test_mode is True
            request.take_credentials()
            raise RuntimeError("synthetic query failure")

    request = _query_request()
    dispatcher = SfWaybillQueryDispatcher(
        adapter=Adapter(),
        settings=SfWaybillProviderSettings(
            test_mode=True,
            connect_timeout_seconds=1,
            read_timeout_seconds=1,
        ),
    )

    result = dispatcher.dispatch(request)

    assert result.resolution is UnknownResolution.STILL_UNKNOWN
    assert result.safe_provider_code == "SF_QUERY_RESULT_UNKNOWN"
    with pytest.raises(SfWaybillCredentialError):
        request.take_credentials()


def _reconciliation_job() -> BackgroundJob:
    return BackgroundJob(
        id=JOB_UUID,
        tenant_id=TENANT_UUID,
        tenant_access_version=3,
        job_type=SF_WAYBILL_RECONCILIATION_JOB_TYPE,
        resource_key=SF_WAYBILL_RECONCILIATION_RESOURCE_KEY,
        payload={"contract_version": 1},
        idempotency_key=(
            f"scheduler:{SF_WAYBILL_RECONCILIATION_JOB_TYPE}:bucket-1"
        ),
        requested_by_type="scheduler",
        request_id="sf-waybill-reconciliation",
        max_attempts=1,
        available_at=NOW,
    )


def test_query_reconciliation_success_uses_one_claim_and_direct_signal():
    calls = []
    snapshot = SfWaybillReconciliationSnapshot(
        tenant_uuid=TENANT_UUID,
        shipment_uuid=SHIPMENT_UUID,
        attempt_uuid=ATTEMPT_UUID,
        origin_warehouse_uuid=WAREHOUSE_UUID,
        integration_uuid=INTEGRATION_UUID,
        provider_account_uuid=ACCOUNT_UUID,
        integration_secret_revision_uuid=INTEGRATION_REVISION_UUID,
        provider_account_secret_revision_uuid=ACCOUNT_REVISION_UUID,
        binding_revision=1,
    )
    signal = RelayShipmentSubmissionSignal(
        shipment_uuid=SHIPMENT_UUID,
        predecessor_rental_id=1,
        successor_rental_id=2,
        waybill_no="SF1234567890",
        source_result_digest=RESULT_DIGEST,
        occurred_at=NOW,
    )

    class Store:
        def claim_one(self, _prepared, *, started_at):
            assert started_at == NOW
            calls.append("claim")
            return snapshot

        def record_result(
            self,
            _prepared,
            *,
            snapshot: SfWaybillReconciliationSnapshot,
            result,
            finished_at,
        ):
            assert snapshot.attempt_uuid == ATTEMPT_UUID
            assert result.resolution is UnknownResolution.CONFIRMED_SUCCESS
            assert finished_at == NOW
            calls.append("record_result")
            return StoredSfWaybillReconciliation(
                shipment_uuid=SHIPMENT_UUID,
                attempt_uuid=ATTEMPT_UUID,
                resolution=result.resolution,
                relay_signal=signal,
            )

    class Credentials:
        def prepare(self, *, job, snapshot):
            assert job.tenant_uuid == snapshot.tenant_uuid
            calls.append("credentials")
            return _Request(calls)

    class Dispatcher:
        def dispatch(self, _request):
            calls.append("provider")
            return SfWaybillQueryResult(
                resolution=UnknownResolution.CONFIRMED_SUCCESS,
                safe_provider_code="SF_QUERY_CONFIRMED",
                waybill_no="SF1234567890",
                response_hash=RESULT_DIGEST,
            )

    relay = _Relay(calls)
    handler = SfWaybillReconciliationJobHandler(
        store=Store(),
        credential_source=Credentials(),
        provider_dispatcher=Dispatcher(),
        call_authorizer=_Authorizer(calls),
        relay_enqueuer=relay,
        clock=lambda: NOW,
    )
    job = _reconciliation_job()

    outcome = handler.execute(job, handler.prepare(job))

    assert outcome.disposition is OutcomeDisposition.SUCCEEDED
    assert outcome.safe_result == {
        "reconciled": True,
        "shipment_uuid": SHIPMENT_UUID,
        "resolution": "confirmed_success",
        "relay_direct_enqueued": True,
    }
    assert calls == [
        "authorize",
        "claim",
        "credentials",
        "authorize",
        "provider",
        "discard",
        "authorize",
        "record_result",
        "relay_enqueue",
    ]


def test_query_reconciliation_still_unknown_is_terminal_review():
    calls = []
    snapshot = SfWaybillReconciliationSnapshot(
        tenant_uuid=TENANT_UUID,
        shipment_uuid=SHIPMENT_UUID,
        attempt_uuid=ATTEMPT_UUID,
        origin_warehouse_uuid=WAREHOUSE_UUID,
        integration_uuid=INTEGRATION_UUID,
        provider_account_uuid=ACCOUNT_UUID,
        integration_secret_revision_uuid=INTEGRATION_REVISION_UUID,
        provider_account_secret_revision_uuid=ACCOUNT_REVISION_UUID,
        binding_revision=1,
    )

    class Store:
        def claim_one(self, _prepared, *, started_at):
            del started_at
            calls.append("claim")
            return snapshot

        def record_result(self, _prepared, *, snapshot, result, finished_at):
            del snapshot, finished_at
            calls.append("record_result")
            return StoredSfWaybillReconciliation(
                shipment_uuid=SHIPMENT_UUID,
                attempt_uuid=ATTEMPT_UUID,
                resolution=result.resolution,
                relay_signal=None,
            )

    class Credentials:
        def prepare(self, *, job, snapshot):
            del job, snapshot
            calls.append("credentials")
            return _Request(calls)

    class Dispatcher:
        def dispatch(self, _request):
            calls.append("provider")
            return SfWaybillQueryResult(
                resolution=UnknownResolution.STILL_UNKNOWN,
                safe_provider_code="SF_QUERY_RESULT_UNKNOWN",
            )

    handler = SfWaybillReconciliationJobHandler(
        store=Store(),
        credential_source=Credentials(),
        provider_dispatcher=Dispatcher(),
        call_authorizer=_Authorizer(calls),
        relay_enqueuer=_Relay(calls),
        clock=lambda: NOW,
    )
    job = _reconciliation_job()

    outcome = handler.execute(job, handler.prepare(job))

    assert outcome.disposition is OutcomeDisposition.REVIEW
    assert outcome.reason_code == "sf_waybill_result_still_unknown"
    assert "relay_enqueue" not in calls


def test_capability_composition_registers_handler_without_io(tmp_path: Path):
    class Authority:
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

    class Adapter:
        def create_waybill(self, *, request, settings):
            raise AssertionError("composition must not call provider")

        def query_waybill(self, *, request, settings):
            raise AssertionError("composition must not query provider")

    database = ControlDatabase(
        engine=SimpleNamespace(dispose=lambda: None),
        session_factory=object(),
    )
    capability = build_sf_waybill_capability(
        control_database=database,
        authority=Authority(),
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
        provider_adapter=Adapter(),
        provider_settings=SfWaybillProviderSettings(
            test_mode=True,
            connect_timeout_seconds=1,
            read_timeout_seconds=1,
        ),
    )

    assert set(capability.handlers) == {
        SF_CREATE_WAYBILL_JOB_TYPE,
        SF_WAYBILL_INTENT_JOB_TYPE,
        SF_WAYBILL_RECONCILIATION_JOB_TYPE,
    }
    assert [item.job_type for item in capability.schedules] == [
        SF_WAYBILL_INTENT_JOB_TYPE,
        SF_WAYBILL_RECONCILIATION_JOB_TYPE
    ]


def test_sf_relay_process_composes_one_worker_without_io(tmp_path: Path):
    class Authority:
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

    class ScheduleGate:
        def evaluate(self, _session, *, tenant, now):
            del tenant, now
            return ScheduleGateVerdict(True)

    class Adapter:
        def create_waybill(self, *, request, settings):
            del request, settings
            raise AssertionError("composition must not call provider")

        def query_waybill(self, *, request, settings):
            del request, settings
            raise AssertionError("composition must not query provider")

    database = ControlDatabase(
        engine=SimpleNamespace(dispose=lambda: None),
        session_factory=object(),
    )
    process = build_sf_relay_job_process(
        control_database=database,
        authority=Authority(),
        heartbeat_recorder=lambda _session, *, observed_at: None,
        retry_backoff_policy=RetryBackoffPolicy(
            delays=(timedelta(seconds=1),)
        ),
        schedule_gate=ScheduleGate(),
        worker_id="sf-relay-worker",
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
        provider_adapter=Adapter(),
        provider_settings=SfWaybillProviderSettings(
            test_mode=True,
            connect_timeout_seconds=1,
            read_timeout_seconds=1,
        ),
        clock=lambda: NOW,
    )

    expected_job_types = {
        SF_CREATE_WAYBILL_JOB_TYPE,
        SF_WAYBILL_INTENT_JOB_TYPE,
        SF_WAYBILL_RECONCILIATION_JOB_TYPE,
        RELAY_EXTERNAL_PROJECTION_JOB_TYPE,
        RELAY_EXTERNAL_RECONCILIATION_JOB_TYPE,
    }
    assert set(process._worker._handlers) == expected_job_types
    assert process._worker._claim_job_types == expected_job_types
    assert [item.job_type for item in process._definitions] == [
        SF_WAYBILL_INTENT_JOB_TYPE,
        SF_WAYBILL_RECONCILIATION_JOB_TYPE,
        RELAY_EXTERNAL_RECONCILIATION_JOB_TYPE
    ]
