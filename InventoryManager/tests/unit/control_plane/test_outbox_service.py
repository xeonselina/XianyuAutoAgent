from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from inventory_control import ControlBase, ControlDatabase
from inventory_control.jobs import (
    RESULT_DIGEST_VERSION,
    ControlJobService,
    ControlOutboxService,
    OutboxAuthorityVerdict,
    OutboxFailureCertainty,
    OutboxInputError,
    OutboxLane,
    OutboxLeaseFenceError,
    OutboxSystemCleanupPolicyError,
    OutboxTransactionRequiredError,
    OutboxTransitionError,
    verify_persisted_safe_result_mac,
)
from inventory_control.models import ControlOutboxEvent, Tenant


NOW = datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc)
TENANT_ID = UUID("60000000-0000-4000-8000-000000000001")
SOURCE_ID = UUID("60000000-0000-4000-8000-000000000002")
MAC_KEY = b"result-mac-key-material-32bytes!!"


class MutableDatabaseClock:
    def __init__(self, current=NOW):
        self.current = current

    def __call__(self, _session):
        return self.current

    def set(self, current):
        self.current = current


class FakeAuthority:
    def __init__(
        self,
        *,
        allowed=True,
        recovery_verified=True,
        source_generation=None,
        tenant_access_version=None,
        reason_code="authority_allowed",
        raises=False,
    ):
        self.allowed = allowed
        self.recovery_verified = recovery_verified
        self.source_generation = source_generation
        self.tenant_access_version = tenant_access_version
        self.reason_code = reason_code
        self.raises = raises
        self.calls = []

    def lock_current_outbox_authority(self, session, *, facts, phase):
        self.calls.append(("lock", session, facts, phase, None))
        if self.raises:
            raise RuntimeError("untrusted callback detail")
        return (facts, phase)

    def evaluate_locked_outbox_authority(
        self,
        session,
        *,
        locked_authority,
        facts,
        phase,
        now,
    ):
        self.calls.append(("evaluate", session, facts, phase, now))
        assert locked_authority == (facts, phase)
        return OutboxAuthorityVerdict(
            allowed=self.allowed,
            current_recovery_run_verified=self.recovery_verified,
            current_source_generation=(
                facts.source_generation
                if self.source_generation is None
                else self.source_generation
            ),
            current_tenant_access_version=(
                facts.tenant_access_version
                if self.tenant_access_version is None
                else self.tenant_access_version
            ),
            reason_code=self.reason_code,
        )


@pytest.fixture
def control_database(mysql_control_database):
    with mysql_control_database.transaction() as session:
        session.add(Tenant(id=str(TENANT_ID), status="active"))
    return mysql_control_database


def _enqueue(
    database,
    *,
    event_type="provider_notification",
    key="event:1",
    source_generation=1,
    tenant_access_version=1,
    max_attempts=3,
    available_at=NOW,
    not_after=None,
):
    with database.transaction() as session:
        return ControlJobService().enqueue_outbox(
            session,
            tenant_id=str(TENANT_ID),
            tenant_access_version=tenant_access_version,
            source_type="test_source",
            source_uuid=str(SOURCE_ID),
            source_generation=source_generation,
            event_type=event_type,
            payload={"operation_uuid": "safe-operation-1"},
            idempotency_key=key,
            max_attempts=max_attempts,
            available_at=available_at,
            not_after=not_after,
        )


def _claim_ordinary(database, service, authority, *, now=NOW, worker="worker-a"):
    with database.transaction() as session:
        return service.claim_ordinary_mysql_skip_locked(
            session,
            worker_id=worker,
            lease_duration=timedelta(seconds=30),
            authority=authority,
            now=now,
        )


def _authorize(database, service, authority, lease, *, now=None):
    with database.transaction() as session:
        return service.authorize_side_effect(
            session,
            event_id=lease.event_id,
            worker_id="worker-a",
            lease_token=lease.lease_token,
            execution_generation=lease.execution_generation,
            authority=authority,
            now=now or NOW + timedelta(seconds=1),
        )


def test_requires_explicit_transaction(control_database):
    service = ControlOutboxService()
    with control_database.new_session() as session:
        with pytest.raises(OutboxTransactionRequiredError):
            service.claim_ordinary_mysql_skip_locked(
                session,
                worker_id="worker-a",
                lease_duration=timedelta(seconds=30),
                authority=FakeAuthority(),
                now=NOW,
            )


def test_ordinary_and_system_cleanup_claims_are_separate(control_database):
    system = _enqueue(
        control_database,
        event_type="provisional_cleanup",
        key="system",
        available_at=NOW - timedelta(seconds=1),
    )
    ordinary = _enqueue(control_database, key="ordinary")
    service = ControlOutboxService()
    authority = FakeAuthority()

    claimed_ordinary = _claim_ordinary(control_database, service, authority)
    assert claimed_ordinary.event_id == ordinary.id
    assert claimed_ordinary.lane is OutboxLane.ORDINARY
    assert "safe-operation-1" not in repr(claimed_ordinary)
    assert claimed_ordinary.lease_token not in repr(claimed_ordinary)

    with control_database.transaction() as session:
        claimed_system = service.claim_system_cleanup_mysql_skip_locked(
            session,
            worker_id="cleanup-worker",
            lease_duration=timedelta(seconds=30),
            authority=authority,
            now=NOW,
        )
        assert claimed_system.event_id == system.id
        assert claimed_system.lane is OutboxLane.SYSTEM_CLEANUP


def test_claim_projection_is_nonlocking_and_lane_filtered():
    service = ControlOutboxService()
    statement = service._claim_candidate_statement(
        lane=OutboxLane.SYSTEM_CLEANUP,
        now=NOW,
        skip_locked=True,
    )
    compiled = str(
        statement.compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()

    assert "FOR UPDATE" not in compiled
    assert "CONTROL_OUTBOX_EVENTS.EVENT_TYPE IN" in compiled
    assert "CONTROL_OUTBOX_EVENTS.AVAILABLE_AT ASC" in compiled
    assert "CONTROL_OUTBOX_EVENTS.CREATED_AT ASC" in compiled

    locked = str(
        service._event_lock_statement(
            event_id=str(SOURCE_ID),
            skip_locked=True,
        ).compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()
    assert "FOR UPDATE SKIP LOCKED" in locked


def test_claim_uses_two_phase_authority_and_final_database_clock(
    control_database,
):
    event = _enqueue(control_database)
    trace = []

    class TracingAuthority(FakeAuthority):
        def lock_current_outbox_authority(self, session, *, facts, phase):
            trace.append(("authority_lock", session, facts.event_id, phase))
            return super().lock_current_outbox_authority(
                session, facts=facts, phase=phase
            )

        def evaluate_locked_outbox_authority(self, session, **kwargs):
            trace.append(
                (
                    "authority_evaluate",
                    session,
                    kwargs["facts"].event_id,
                    kwargs["phase"],
                )
            )
            return super().evaluate_locked_outbox_authority(
                session, **kwargs
            )

    def clock(session):
        trace.append(("database_clock", session, None, None))
        return NOW

    authority = TracingAuthority()
    service = ControlOutboxService(database_clock=clock)
    with control_database.transaction() as session:
        lease = service.claim_ordinary_mysql_skip_locked(
            session,
            worker_id="worker-a",
            lease_duration=timedelta(seconds=30),
            authority=authority,
        )
        assert lease.event_id == event.id
        assert [entry[0] for entry in trace] == [
            "database_clock",
            "authority_lock",
            "database_clock",
            "authority_evaluate",
        ]
        assert all(entry[1] is session for entry in trace)


def test_heartbeat_and_dispatch_use_lock_then_final_database_clock(
    control_database,
):
    event = _enqueue(control_database)
    trace = []

    class TracingAuthority(FakeAuthority):
        def lock_current_outbox_authority(self, session, *, facts, phase):
            trace.append(("authority_lock", session, phase))
            return super().lock_current_outbox_authority(
                session, facts=facts, phase=phase
            )

        def evaluate_locked_outbox_authority(self, session, **kwargs):
            trace.append(("authority_evaluate", session, kwargs["phase"]))
            return super().evaluate_locked_outbox_authority(
                session, **kwargs
            )

    clock_now = {"value": NOW}

    def clock(session):
        trace.append(("database_clock", session, None))
        return clock_now["value"]

    authority = TracingAuthority()
    service = ControlOutboxService(database_clock=clock)
    lease = _claim_ordinary(control_database, service, authority)

    trace.clear()
    clock_now["value"] = NOW + timedelta(seconds=1)
    with control_database.transaction() as session:
        service.heartbeat(
            session,
            event_id=event.id,
            worker_id="worker-a",
            lease_token=lease.lease_token,
            execution_generation=lease.execution_generation,
            lease_duration=timedelta(seconds=30),
            authority=authority,
        )
        assert [entry[0] for entry in trace] == [
            "authority_lock",
            "database_clock",
            "authority_evaluate",
        ]
        assert all(entry[1] is session for entry in trace)

    trace.clear()
    clock_now["value"] = NOW + timedelta(seconds=2)
    with control_database.transaction() as session:
        permit = service.authorize_side_effect(
            session,
            event_id=event.id,
            worker_id="worker-a",
            lease_token=lease.lease_token,
            execution_generation=lease.execution_generation,
            authority=authority,
        )
        assert permit is not None
        assert [entry[0] for entry in trace] == [
            "authority_lock",
            "database_clock",
            "authority_evaluate",
        ]
        assert all(entry[1] is session for entry in trace)


def test_event_authority_projection_drift_fails_before_final_evaluation(
    control_database,
):
    event = _enqueue(control_database)

    class DriftingAuthority(FakeAuthority):
        def lock_current_outbox_authority(self, session, *, facts, phase):
            locked = super().lock_current_outbox_authority(
                session, facts=facts, phase=phase
            )
            session.execute(
                sa.update(ControlOutboxEvent)
                .where(ControlOutboxEvent.id == facts.event_id)
                .values(source_generation=facts.source_generation + 1)
            )
            return locked

    authority = DriftingAuthority()
    with pytest.raises(OutboxLeaseFenceError):
        _claim_ordinary(
            control_database,
            ControlOutboxService(),
            authority,
        )
    assert [call[0] for call in authority.calls] == ["lock"]
    with control_database.new_session() as session:
        assert session.get(ControlOutboxEvent, event.id).source_generation == 1


def test_legacy_sessionless_authority_is_not_accepted(control_database):
    _enqueue(control_database)

    class LegacyAuthority:
        def verify_outbox_authority(self, *, facts, phase, now):
            del facts, phase, now

    with pytest.raises(TypeError, match="lock current outbox authority"):
        _claim_ordinary(
            control_database,
            ControlOutboxService(),
            LegacyAuthority(),
        )


def test_claim_authority_mismatch_quarantines_without_dispatch(control_database):
    event = _enqueue(control_database)
    service = ControlOutboxService()
    authority = FakeAuthority(source_generation=2)

    assert _claim_ordinary(control_database, service, authority) is None
    with control_database.new_session() as session:
        persisted = session.get(ControlOutboxEvent, event.id)
        assert persisted.state == "recovery_quarantined"
        assert persisted.last_error_code == "authority_version_mismatch"
        assert persisted.attempts == 0


def test_authority_callback_failure_is_fail_closed(control_database):
    event = _enqueue(control_database)
    service = ControlOutboxService()
    lease = _claim_ordinary(control_database, service, FakeAuthority())

    assert _authorize(
        control_database, service, FakeAuthority(raises=True), lease
    ) is None
    with control_database.new_session() as session:
        persisted = session.get(ControlOutboxEvent, event.id)
        assert persisted.state == "recovery_quarantined"
        assert persisted.last_error_code == "authority_verification_failed"


def test_heartbeat_is_fenced_and_authority_checked(control_database):
    event = _enqueue(control_database)
    clock = MutableDatabaseClock()
    service = ControlOutboxService(database_clock=clock)
    authority = FakeAuthority()
    lease = _claim_ordinary(control_database, service, authority)

    clock.set(NOW + timedelta(seconds=10))
    with control_database.transaction() as session:
        heartbeat = service.heartbeat(
            session,
            event_id=event.id,
            worker_id="worker-a",
            lease_token=lease.lease_token,
            execution_generation=lease.execution_generation,
            lease_duration=timedelta(seconds=30),
            authority=authority,
            now=NOW + timedelta(seconds=10),
        )
        assert heartbeat.state == "leased"
    with control_database.new_session() as session:
        persisted = session.get(ControlOutboxEvent, event.id)
        assert persisted.lease_expires_at.replace(tzinfo=timezone.utc) == (
            NOW + timedelta(seconds=40)
        )
    with control_database.transaction() as session:
        with pytest.raises(OutboxLeaseFenceError):
            service.heartbeat(
                session,
                event_id=event.id,
                worker_id="worker-b",
                lease_token=lease.lease_token,
                execution_generation=lease.execution_generation,
                lease_duration=timedelta(seconds=30),
                authority=authority,
                now=NOW + timedelta(seconds=11),
            )


def test_success_stores_only_versioned_digest_and_mac(control_database):
    event = _enqueue(control_database)
    service = ControlOutboxService()
    authority = FakeAuthority()
    lease = _claim_ordinary(control_database, service, authority)
    permit = _authorize(control_database, service, authority, lease)
    assert permit is not None
    assert "safe-operation-1" not in repr(permit)
    safe_facts_digest = hashlib.sha256(b"allowlisted-safe-facts").digest()
    evidence = service.make_safe_result_evidence(
        permit,
        safe_code="PROVIDER_ACCEPTED",
        safe_facts_digest=safe_facts_digest,
        result_mac_key=MAC_KEY,
    )

    with control_database.transaction() as session:
        completed = service.complete_success(
            session,
            event_id=event.id,
            worker_id="worker-a",
            lease_token=lease.lease_token,
            execution_generation=lease.execution_generation,
            evidence=evidence,
            result_mac_key=MAC_KEY,
            authority=authority,
            now=NOW + timedelta(seconds=2),
        )
        assert completed.state == "succeeded"
    with control_database.new_session() as session:
        persisted = session.get(ControlOutboxEvent, event.id)
        assert persisted.result_digest_version == 1
        assert persisted.result_digest == evidence.digest_hex
        assert persisted.result_mac == evidence.mac_hex
        assert len(persisted.result_digest) == 64
        assert len(persisted.result_mac) == 64
        assert "allowlisted-safe-facts" not in persisted.result_digest

    with control_database.transaction() as session:
        replay = service.complete_success(
            session,
            event_id=event.id,
            worker_id="irrelevant-after-authenticated-success",
            lease_token="irrelevant-after-authenticated-success",
            execution_generation=lease.execution_generation,
            evidence=evidence,
            result_mac_key=MAC_KEY,
            authority=authority,
            now=NOW + timedelta(seconds=3),
        )
        assert replay.idempotent_replay is True


def test_tampered_result_mac_is_rejected_without_persisting_result(control_database):
    event = _enqueue(control_database)
    service = ControlOutboxService()
    authority = FakeAuthority()
    lease = _claim_ordinary(control_database, service, authority)
    permit = _authorize(control_database, service, authority, lease)
    evidence = service.make_safe_result_evidence(
        permit,
        safe_code="PROVIDER_ACCEPTED",
        safe_facts_digest=hashlib.sha256(b"safe").digest(),
        result_mac_key=MAC_KEY,
    )
    altered = type(evidence)(
        safe_code=evidence.safe_code,
        digest_version=evidence.digest_version,
        digest_hex=evidence.digest_hex,
        mac_hex="0" * 64,
    )

    with control_database.transaction() as session:
        with pytest.raises(OutboxInputError):
            service.complete_success(
                session,
                event_id=event.id,
                worker_id="worker-a",
                lease_token=lease.lease_token,
                execution_generation=lease.execution_generation,
                evidence=altered,
                result_mac_key=MAC_KEY,
                authority=authority,
                now=NOW + timedelta(seconds=2),
            )
    with control_database.new_session() as session:
        persisted = session.get(ControlOutboxEvent, event.id)
        assert persisted.state == "leased"
        assert persisted.result_digest is None
        assert persisted.result_mac is None


def test_persisted_safe_result_mac_verifier_is_boolean_and_fail_closed(
    control_database,
):
    _enqueue(control_database)
    service = ControlOutboxService()
    authority = FakeAuthority()
    lease = _claim_ordinary(control_database, service, authority)
    permit = _authorize(control_database, service, authority, lease)
    evidence = service.make_safe_result_evidence(
        permit,
        safe_code="PROVIDER_ACCEPTED",
        safe_facts_digest=hashlib.sha256(b"safe").digest(),
        result_mac_key=MAC_KEY,
    )

    assert verify_persisted_safe_result_mac(
        permit.event_id,
        permit.execution_generation,
        evidence.safe_code,
        evidence.digest_version,
        evidence.digest_hex,
        evidence.mac_hex,
        MAC_KEY,
    )
    assert not verify_persisted_safe_result_mac(
        permit.event_id,
        permit.execution_generation,
        evidence.safe_code,
        evidence.digest_version,
        evidence.digest_hex,
        "0" * 64,
        MAC_KEY,
    )
    for invalid in (
        {"event_id": "not-a-uuid"},
        {"execution_generation": True},
        {"safe_code": "not allowed"},
        {"digest_version": RESULT_DIGEST_VERSION + 1},
        {"digest_version": float(RESULT_DIGEST_VERSION)},
        {"digest_hex": None},
        {"mac_hex": "not-hex"},
        {"result_mac_key": b"short"},
    ):
        values = {
            "event_id": permit.event_id,
            "execution_generation": permit.execution_generation,
            "safe_code": evidence.safe_code,
            "digest_version": evidence.digest_version,
            "digest_hex": evidence.digest_hex,
            "mac_hex": evidence.mac_hex,
            "result_mac_key": MAC_KEY,
        }
        values.update(invalid)
        assert verify_persisted_safe_result_mac(**values) is False


def test_result_after_authority_change_is_saved_but_quarantined(control_database):
    event = _enqueue(control_database)
    service = ControlOutboxService()
    lease = _claim_ordinary(control_database, service, FakeAuthority())
    permit = _authorize(control_database, service, FakeAuthority(), lease)
    evidence = service.make_safe_result_evidence(
        permit,
        safe_code="PROVIDER_ACCEPTED",
        safe_facts_digest=hashlib.sha256(b"safe").digest(),
        result_mac_key=MAC_KEY,
    )

    with control_database.transaction() as session:
        completed = service.complete_success(
            session,
            event_id=event.id,
            worker_id="worker-a",
            lease_token=lease.lease_token,
            execution_generation=lease.execution_generation,
            evidence=evidence,
            result_mac_key=MAC_KEY,
            authority=FakeAuthority(
                allowed=False, reason_code="recovery_hold_active"
            ),
            now=NOW + timedelta(seconds=2),
        )
        assert completed.state == "recovery_quarantined"
    with control_database.new_session() as session:
        persisted = session.get(ControlOutboxEvent, event.id)
        assert persisted.result_digest == evidence.digest_hex
        assert persisted.result_mac == evidence.mac_hex
        assert persisted.last_error_code == "recovery_hold_active"


def test_safe_failure_retries_then_ordinary_exhaustion_cancels(control_database):
    event = _enqueue(control_database, max_attempts=2)
    clock = MutableDatabaseClock()
    service = ControlOutboxService(database_clock=clock)
    authority = FakeAuthority()
    first = _claim_ordinary(control_database, service, authority)
    clock.set(NOW + timedelta(seconds=1))
    with control_database.transaction() as session:
        retry = service.record_safe_failure(
            session,
            event_id=event.id,
            worker_id="worker-a",
            lease_token=first.lease_token,
            execution_generation=first.execution_generation,
            certainty=OutboxFailureCertainty.BEFORE_SIDE_EFFECT,
            error_code="local_dependency_unavailable",
            retry_at=NOW + timedelta(seconds=5),
            authority=authority,
            now=NOW + timedelta(seconds=1),
        )
        assert retry.state == "pending"

    clock.set(NOW + timedelta(seconds=5))
    second = _claim_ordinary(
        control_database,
        service,
        authority,
        now=NOW + timedelta(seconds=5),
    )
    clock.set(NOW + timedelta(seconds=6))
    permit = _authorize(
        control_database,
        service,
        authority,
        second,
        now=NOW + timedelta(seconds=6),
    )
    assert permit is not None
    clock.set(NOW + timedelta(seconds=7))
    with control_database.transaction() as session:
        exhausted = service.record_safe_failure(
            session,
            event_id=event.id,
            worker_id="worker-a",
            lease_token=second.lease_token,
            execution_generation=second.execution_generation,
            certainty=OutboxFailureCertainty.PROVIDER_CONFIRMED_NO_EFFECT,
            error_code="provider_rejected_without_effect",
            retry_at=NOW + timedelta(seconds=8),
            authority=authority,
            now=NOW + timedelta(seconds=7),
        )
        assert exhausted.state == "cancelled"
        assert exhausted.attempts == 2


def test_system_cleanup_exhaustion_quarantines_and_cannot_cancel(control_database):
    event = _enqueue(
        control_database,
        event_type="provisional_cleanup",
        max_attempts=1,
    )
    service = ControlOutboxService()
    authority = FakeAuthority()
    with control_database.transaction() as session:
        lease = service.claim_system_cleanup_mysql_skip_locked(
            session,
            worker_id="cleanup-worker",
            lease_duration=timedelta(seconds=30),
            authority=authority,
            now=NOW,
        )
    with control_database.transaction() as session:
        with pytest.raises(OutboxSystemCleanupPolicyError):
            service.cancel_leased_ordinary_before_side_effect(
                session,
                event_id=event.id,
                worker_id="cleanup-worker",
                lease_token=lease.lease_token,
                execution_generation=lease.execution_generation,
                authority=authority,
                reason_code="operator_cancelled",
                now=NOW + timedelta(seconds=1),
            )
    with control_database.transaction() as session:
        exhausted = service.record_safe_failure(
            session,
            event_id=event.id,
            worker_id="cleanup-worker",
            lease_token=lease.lease_token,
            execution_generation=lease.execution_generation,
            certainty=OutboxFailureCertainty.BEFORE_SIDE_EFFECT,
            error_code="cleanup_dependency_unavailable",
            authority=authority,
            now=NOW + timedelta(seconds=1),
        )
        assert exhausted.state == "recovery_quarantined"


def test_unknown_outcome_and_expired_lease_are_never_reclaimed(control_database):
    unknown_event = _enqueue(control_database, key="unknown")
    clock = MutableDatabaseClock()
    service = ControlOutboxService(database_clock=clock)
    authority = FakeAuthority()
    unknown_lease = _claim_ordinary(control_database, service, authority)
    _authorize(control_database, service, authority, unknown_lease)
    with control_database.transaction() as session:
        unknown = service.record_unknown_outcome(
            session,
            event_id=unknown_event.id,
            worker_id="worker-a",
            lease_token=unknown_lease.lease_token,
            execution_generation=unknown_lease.execution_generation,
            now=NOW + timedelta(seconds=2),
        )
        assert unknown.state == "recovery_quarantined"

    expired_event = _enqueue(control_database, key="expired")
    expired_lease = _claim_ordinary(control_database, service, authority)
    assert expired_lease.event_id == expired_event.id
    clock.set(NOW + timedelta(seconds=31))
    assert _claim_ordinary(
        control_database,
        service,
        authority,
        now=NOW + timedelta(seconds=31),
        worker="worker-b",
    ) is None
    with control_database.new_session() as session:
        expired = session.get(ControlOutboxEvent, expired_event.id)
        assert expired.state == "recovery_quarantined"
        assert expired.last_error_code == "lease_expired_outcome_unknown"


def test_duplicate_dispatch_boundary_quarantines(control_database):
    event = _enqueue(control_database)
    service = ControlOutboxService()
    authority = FakeAuthority()
    lease = _claim_ordinary(control_database, service, authority)
    assert _authorize(control_database, service, authority, lease) is not None
    assert _authorize(
        control_database,
        service,
        authority,
        lease,
        now=NOW + timedelta(seconds=2),
    ) is None
    with control_database.new_session() as session:
        persisted = session.get(ControlOutboxEvent, event.id)
        assert persisted.state == "recovery_quarantined"
        assert persisted.last_error_code == "duplicate_dispatch_boundary"


def test_pending_and_leased_ordinary_cancellation(control_database):
    pending = _enqueue(control_database, key="pending")
    service = ControlOutboxService()
    authority = FakeAuthority()
    with control_database.transaction() as session:
        cancelled = service.cancel_pending_ordinary(
            session,
            event_id=pending.id,
            expected_source_generation=1,
            expected_execution_generation=0,
            authority=authority,
            reason_code="operator_cancelled",
            now=NOW,
        )
        assert cancelled.state == "cancelled"

    leased = _enqueue(control_database, key="leased")
    lease = _claim_ordinary(control_database, service, authority)
    assert lease.event_id == leased.id
    with control_database.transaction() as session:
        cancelled = service.cancel_leased_ordinary_before_side_effect(
            session,
            event_id=leased.id,
            worker_id="worker-a",
            lease_token=lease.lease_token,
            execution_generation=lease.execution_generation,
            authority=authority,
            reason_code="operator_cancelled",
            now=NOW + timedelta(seconds=1),
        )
        assert cancelled.state == "cancelled"


def test_recovery_quarantine_advances_fence_and_stale_worker_cannot_finish(
    control_database,
):
    event = _enqueue(control_database)
    service = ControlOutboxService()
    lease = _claim_ordinary(control_database, service, FakeAuthority())
    recovery_authority = FakeAuthority(
        source_generation=2,
        tenant_access_version=2,
        reason_code="current_recovery_run",
    )
    with control_database.transaction() as session:
        quarantined = service.quarantine_for_recovery(
            session,
            event_id=event.id,
            expected_source_generation=1,
            expected_execution_generation=lease.execution_generation,
            authority=recovery_authority,
            reason_code="host_restore_normalization",
            now=NOW + timedelta(seconds=1),
        )
        assert quarantined.state == "recovery_quarantined"
        assert quarantined.execution_generation == lease.execution_generation + 1

    with control_database.transaction() as session:
        with pytest.raises(OutboxTransitionError):
            service.heartbeat(
                session,
                event_id=event.id,
                worker_id="worker-a",
                lease_token=lease.lease_token,
                execution_generation=lease.execution_generation,
                lease_duration=timedelta(seconds=30),
                authority=FakeAuthority(),
                now=NOW + timedelta(seconds=2),
            )


def test_housekeeping_is_lane_scoped_and_uses_lane_specific_terminal_state(
    control_database,
):
    ordinary = _enqueue(
        control_database,
        key="ordinary-expired",
        not_after=NOW + timedelta(seconds=1),
    )
    system = _enqueue(
        control_database,
        event_type="provisional_cleanup",
        key="system-expired",
        not_after=NOW + timedelta(seconds=1),
    )
    service = ControlOutboxService()
    with control_database.transaction() as session:
        assert service.claim_ordinary_mysql_skip_locked(
            session,
            worker_id="worker-a",
            lease_duration=timedelta(seconds=30),
            authority=FakeAuthority(),
            now=NOW + timedelta(seconds=2),
        ) is None
    with control_database.new_session() as session:
        assert session.get(ControlOutboxEvent, ordinary.id).state == "cancelled"
        assert session.get(ControlOutboxEvent, system.id).state == "pending"

    with control_database.transaction() as session:
        assert service.claim_system_cleanup_mysql_skip_locked(
            session,
            worker_id="cleanup-worker",
            lease_duration=timedelta(seconds=30),
            authority=FakeAuthority(),
            now=NOW + timedelta(seconds=2),
        ) is None
    with control_database.new_session() as session:
        assert (
            session.get(ControlOutboxEvent, system.id).state
            == "recovery_quarantined"
        )


def test_sqlite_claim_method_refuses_mysql_backend(control_database):
    service = ControlOutboxService()
    with control_database.transaction() as session:
        with pytest.raises(OutboxInputError):
            service.claim_ordinary_sqlite_for_test(
                session,
                worker_id="worker-a",
                lease_duration=timedelta(seconds=30),
                authority=FakeAuthority(),
                now=NOW,
            )
