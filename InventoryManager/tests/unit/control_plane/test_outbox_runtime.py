from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from inventory_control import ControlBase, ControlDatabase
from inventory_control.jobs import (
    ControlJobService,
    ControlOutboxService,
    DurableOrdinaryOutboxWorker,
    OutboxAuthorityVerdict,
    OutboxHandlerResult,
    OutboxResultDisposition,
    PreparedOutboxDispatch,
)
from inventory_control.models import ControlOutboxEvent, Tenant


NOW = datetime(2026, 8, 23, 2, 0, tzinfo=timezone.utc)
TENANT_ID = UUID("6a000000-0000-4000-8000-000000000001")
SOURCE_ID = UUID("6a000000-0000-4000-8000-000000000002")
MAC_KEY = b"ordinary-outbox-result-key-material"


class _Authority:
    def __init__(self, *, allowed=True):
        self.allowed = allowed

    def lock_current_outbox_authority(self, _session, *, facts, phase):
        return facts, phase

    def evaluate_locked_outbox_authority(
        self,
        _session,
        *,
        locked_authority,
        facts,
        phase,
        now,
    ):
        assert locked_authority == (facts, phase)
        return OutboxAuthorityVerdict(
            allowed=self.allowed,
            current_recovery_run_verified=True,
            current_source_generation=facts.source_generation,
            current_tenant_access_version=facts.tenant_access_version,
            reason_code="authority_allowed" if self.allowed else "tenant_blocked",
        )


class _Handler:
    def __init__(self, *, fail_prepare=False, fail_execute=False, unknown=False):
        self.fail_prepare = fail_prepare
        self.fail_execute = fail_execute
        self.unknown = unknown
        self.calls = []

    def prepare_dispatch(self, session, *, lease, permit):
        self.calls.append(("prepare", session, lease.event_id, permit.event_id))
        if self.fail_prepare:
            raise RuntimeError("sensitive local detail")
        return PreparedOutboxDispatch({"safe": "request"})

    def execute(self, *, permit, prepared):
        self.calls.append(("execute", None, permit.event_id, prepared.value))
        if self.fail_execute:
            raise RuntimeError("provider response unavailable")
        if self.unknown:
            return OutboxHandlerResult(
                OutboxResultDisposition.UNKNOWN,
                safe_code="PROVIDER_UNKNOWN",
                safe_facts_digest=hashlib.sha256(b"unknown").digest(),
                reason_code="provider_result_unknown",
            )
        return OutboxHandlerResult(
            OutboxResultDisposition.COMPLETE,
            safe_code="PROVIDER_ACCEPTED",
            safe_facts_digest=hashlib.sha256(b"accepted").digest(),
            value={"accepted": True},
        )

    def persist_result(self, session, *, permit, result, completed_at):
        self.calls.append(("persist", session, permit.event_id, result.value))
        assert completed_at.tzinfo is not None

    def persist_unknown(
        self,
        session,
        *,
        permit,
        result,
        reason_code,
        completed_at,
    ):
        self.calls.append(("unknown", session, permit.event_id, reason_code))
        assert completed_at.tzinfo is not None


@pytest.fixture
def database(mysql_control_database):
    with mysql_control_database.transaction() as session:
        session.add(Tenant(id=str(TENANT_ID), status="active"))
    return mysql_control_database


def _enqueue(database, *, max_attempts=1):
    with database.transaction() as session:
        return (
            ControlJobService()
            .enqueue_outbox(
                session,
                tenant_id=str(TENANT_ID),
                tenant_access_version=1,
                source_type="test_source",
                source_uuid=str(SOURCE_ID),
                source_generation=1,
                event_type="provider_validate",
                payload={"safe": "payload"},
                idempotency_key="validate:1",
                max_attempts=max_attempts,
                available_at=NOW,
            )
            .id
        )


def _worker(database, handler, *, handlers=True, heartbeats=None):
    def heartbeat(_session, *, observed_at):
        if heartbeats is not None:
            heartbeats.append(observed_at)

    return DurableOrdinaryOutboxWorker(
        database=database,
        authority=_Authority(),
        handlers={"provider_validate": handler} if handlers else {},
        heartbeat_recorder=heartbeat,
        worker_id="outbox-worker-1",
        result_mac_key=MAC_KEY,
        lease_duration=timedelta(minutes=2),
        clock=lambda: NOW,
        service=ControlOutboxService(database_clock=lambda _session: NOW),
    )


def test_complete_provider_result_and_business_projection_commit_together(database):
    event_id = _enqueue(database)
    handler = _Handler()
    heartbeats = []

    result = _worker(database, handler, heartbeats=heartbeats).run_once()

    assert result.state == "succeeded"
    assert [call[0] for call in handler.calls] == ["prepare", "execute", "persist"]
    assert handler.calls[0][1] is not handler.calls[2][1]
    assert handler.calls[1][1] is None
    assert len(heartbeats) == 1
    with database.new_session() as session:
        event = session.get(ControlOutboxEvent, event_id)
        assert event.state == "succeeded"
        assert event.result_digest is not None
        assert event.result_mac is not None


@pytest.mark.parametrize("explicit_unknown", [False, True])
def test_unknown_provider_outcome_is_quarantined_without_retry(
    database,
    explicit_unknown,
):
    event_id = _enqueue(database, max_attempts=3)
    handler = _Handler(
        fail_execute=not explicit_unknown,
        unknown=explicit_unknown,
    )

    result = _worker(database, handler).run_once()

    assert result.state == "recovery_quarantined"
    assert result.reason_code == "provider_result_unknown"
    assert handler.calls[-1][0] == "unknown"
    with database.new_session() as session:
        event = session.get(ControlOutboxEvent, event_id)
        assert event.state == "recovery_quarantined"
        assert event.last_error_code == "provider_result_unknown"


def test_prepare_failure_and_missing_handler_end_before_provider_boundary(database):
    failed_id = _enqueue(database)
    handler = _Handler(fail_prepare=True)
    failed = _worker(database, handler).run_once()
    assert failed.state == "cancelled"
    assert [call[0] for call in handler.calls] == ["prepare"]
    with database.new_session() as session:
        assert session.get(ControlOutboxEvent, failed_id).last_attempt_at is None

    with database.transaction() as session:
        second = ControlJobService().enqueue_outbox(
            session,
            tenant_id=str(TENANT_ID),
            tenant_access_version=1,
            source_type="test_source",
            source_uuid=str(UUID("6a000000-0000-4000-8000-000000000003")),
            source_generation=1,
            event_type="provider_validate",
            payload={},
            idempotency_key="validate:2",
            max_attempts=1,
            available_at=NOW,
        )
        second_id = second.id
    missing = _worker(database, handler, handlers=False).run_once()
    assert missing.state == "cancelled"
    assert missing.reason_code == "handler_not_registered"
    with database.new_session() as session:
        assert session.get(ControlOutboxEvent, second_id).last_attempt_at is None
