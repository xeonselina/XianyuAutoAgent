from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from inventory_control import ControlBase, Tenant
from inventory_control.jobs import (
    PeriodicJobDefinition,
    PeriodicTenantScheduler,
    ScheduleGateVerdict,
)
from inventory_control.jobs.scheduler import _current_cycle
from inventory_control.models.jobs import BackgroundJob
from tests.support.test_database import (
    clear_guarded_mysql_test_rows,
    guarded_mysql_control_database,
)


BUCKET_START = datetime(2026, 8, 22, 0, 0, tzinfo=timezone.utc)


class Gate:
    def __init__(self, denied=()):
        self.denied = set(denied)
        self.sessions = []

    def evaluate(self, session, *, tenant, now):
        # Keep the closed session objects alive so CPython cannot recycle an
        # address and make the transaction-boundary assertion flaky.
        self.sessions.append((session, tenant.id, now))
        if tenant.id in self.denied:
            return ScheduleGateVerdict(False, "recovery_hold")
        return ScheduleGateVerdict(True)


@pytest.fixture(scope="module")
def database_schema():
    with guarded_mysql_control_database(ControlBase.metadata) as database:
        yield database


@pytest.fixture
def database(database_schema):
    clear_guarded_mysql_test_rows(database_schema.engine, ControlBase.metadata)
    return database_schema


def create_tenants(database):
    with database.transaction() as session:
        first = Tenant(status="active", access_version=3)
        second = Tenant(status="active", access_version=7)
        inactive = Tenant(status="suspended", access_version=9)
        session.add_all((first, second, inactive))
        session.flush()
        return first.id, second.id, inactive.id


def definition(builder):
    return PeriodicJobDefinition(
        job_type="xianyu_alert_sync",
        interval=timedelta(seconds=180),
        not_after_window=timedelta(seconds=180),
        resource_key="connection-set:current",
        payload_builder=builder,
        priority=10,
    )


def test_fanout_uses_short_tenant_transactions_gate_and_stable_idempotency(database):
    first, second, _inactive = create_tenants(database)
    gate = Gate(denied={second})
    builder_sessions = []

    def build_payload(session, tenant, cycle):
        builder_sessions.append(id(session))
        return {
            "connection_revision_ids": [f"revision:{tenant.id}"],
            "bucket": cycle.bucket_key,
        }

    scheduler = PeriodicTenantScheduler(database=database, gate=gate)
    # The last second of the bucket is after every deterministic stagger and
    # remains before each trigger's one-interval not_after boundary.
    now = BUCKET_START + timedelta(seconds=179)
    first_run = scheduler.fan_out(definition(build_payload), now=now)
    second_run = scheduler.fan_out(definition(build_payload), now=now)

    assert first_run.evaluated_tenants == 2
    assert first_run.enqueued_jobs == 1
    assert first_run.skipped_gate == 1
    assert second_run.reused_jobs == 1
    assert len({id(session) for session, _tenant, _now in gate.sessions}) == 4
    assert len(builder_sessions) == 2

    with database.new_session() as session:
        jobs = list(session.scalars(select(BackgroundJob)))
    assert len(jobs) == 1
    assert jobs[0].tenant_id == first
    assert jobs[0].tenant_access_version == 3
    assert jobs[0].payload["connection_revision_ids"] == [f"revision:{first}"]
    assert jobs[0].idempotency_key.endswith(str(int(BUCKET_START.timestamp())))


def test_restart_enqueues_only_current_bucket_not_missed_history(database):
    first, _second, _inactive = create_tenants(database)
    gate = Gate()
    scheduler = PeriodicTenantScheduler(database=database, gate=gate)
    job_definition = definition(
        lambda _session, tenant, cycle: {
            "tenant": tenant.id,
            "bucket": cycle.bucket_key,
        }
    )

    late_now = BUCKET_START + timedelta(hours=12, seconds=179)
    result = scheduler.fan_out(job_definition, now=late_now)

    assert result.enqueued_jobs == 2
    with database.new_session() as session:
        jobs = list(session.scalars(select(BackgroundJob)))
    assert len(jobs) == 2
    assert {job.payload["bucket"] for job in jobs} == {
        str(int((BUCKET_START + timedelta(hours=12)).timestamp()))
    }
    assert any(job.tenant_id == first for job in jobs)


def test_tenant_is_skipped_until_its_deterministic_stagger(database):
    first, second, _inactive = create_tenants(database)
    cycles = {
        tenant_id: _current_cycle(
            tenant_id=tenant_id,
            job_type="xianyu_alert_sync",
            interval=timedelta(seconds=180),
            not_after_window=timedelta(seconds=180),
            now=BUCKET_START,
        )
        for tenant_id in (first, second)
    }
    earliest = min(cycle.trigger_at for cycle in cycles.values())
    if earliest == BUCKET_START:
        pytest.skip("deterministic fixture has a zero-second stagger")

    result = PeriodicTenantScheduler(database=database, gate=Gate()).fan_out(
        definition(lambda *_args: {}),
        now=earliest - timedelta(seconds=1),
    )

    assert result.enqueued_jobs == 0
    assert result.skipped_not_due == 2


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"interval": timedelta(0)}, "interval"),
        (
            {
                "interval": timedelta(seconds=30),
                "not_after_window": timedelta(seconds=31),
            },
            "not_after_window",
        ),
        ({"priority": -1}, "priority"),
    ],
)
def test_definition_rejects_unsafe_schedule_shapes(kwargs, message):
    values = {
        "job_type": "job",
        "interval": timedelta(seconds=60),
        "not_after_window": timedelta(seconds=60),
        "resource_key": "resource",
        "payload_builder": lambda *_args: {},
    }
    values.update(kwargs)
    with pytest.raises(ValueError, match=message):
        PeriodicJobDefinition(**values)


def test_definition_can_add_stable_payload_scope_to_idempotency(database):
    first, _second, _inactive = create_tenants(database)
    scheduler = PeriodicTenantScheduler(database=database, gate=Gate())
    scoped = PeriodicJobDefinition(
        job_type="scoped",
        interval=timedelta(seconds=180),
        not_after_window=timedelta(seconds=180),
        resource_key="current",
        payload_builder=lambda _session, tenant, _cycle: {
            "revision": f"revision-{tenant.id}"
        },
        idempotency_scope_builder=(
            lambda _session, _tenant, cycle, payload: (
                f"{cycle.bucket_key}:{payload['revision']}"
            )
        ),
    )

    scheduler.fan_out(scoped, now=BUCKET_START + timedelta(seconds=179))

    with database.new_session() as session:
        job = session.scalar(
            select(BackgroundJob).where(BackgroundJob.tenant_id == first)
        )
    assert job.idempotency_key.endswith(f":revision-{first}")
