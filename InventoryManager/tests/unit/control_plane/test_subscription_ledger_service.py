from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, select

from inventory_control import ControlBase
from inventory_control.models import (
    MemberSeatGuard,
    PlanRevision,
    Subscription,
    SubscriptionEvent,
    Tenant,
    TenantDatabase,
)
from inventory_control.subscriptions import (
    SubscriptionLedgerConflictError,
    SubscriptionLedgerService,
    SubscriptionLedgerTransactionError,
    SubscriptionPlanInvalidError,
    parse_core_entitlements,
)
from tests.support.test_database import (
    clear_guarded_mysql_test_rows,
    guarded_mysql_control_database,
)


TENANT_UUID = UUID("10000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("10000000-0000-4000-8000-000000000002")
PLAN_UUID = UUID("10000000-0000-4000-8000-000000000003")
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def control_database_schema():
    with guarded_mysql_control_database(ControlBase.metadata) as database:
        yield database


@pytest.fixture
def control_database(control_database_schema):
    clear_guarded_mysql_test_rows(
        control_database_schema.engine,
        ControlBase.metadata,
    )
    return control_database_schema


def _seed(control_database, *, digest_override=None):
    snapshot = parse_core_entitlements(
        schema_version=1,
        entitlements={
            "features": {"xianyu_sync": True},
            "limits": {"member_seats": 10},
        },
    )
    with control_database.transaction() as session:
        session.add(Tenant(id=str(TENANT_UUID), status="provisioning"))
        session.add(
            TenantDatabase(
                tenant_id=str(TENANT_UUID),
                database_uuid=str(DATABASE_UUID),
                database_instance_key="local-test",
                database_name="tenant_fixture",
                status="ready",
                schema_version="test-head",
                activated_by_registration_commit_uuid=(
                    "10000000-0000-4000-8000-000000000099"
                ),
                activation_route_version=1,
                activation_credential_generation=1,
                dml_username="tenant_dml_g1",
                dml_credential_generation=1,
                dml_root_key_version=1,
                dml_derivation_version=1,
                route_version=1,
                dml_desired_login_state="active",
                dml_observed_login_state="active",
                dml_login_state_version=1,
                platform_read_username="tenant_read_g1",
                platform_read_credential_generation=1,
                platform_read_root_key_version=1,
                platform_read_derivation_version=1,
                platform_read_route_version=1,
            )
        )
        session.add(
            PlanRevision(
                id=str(PLAN_UUID),
                code="core",
                revision=1,
                name="Core",
                entitlements_schema_version=1,
                entitlements_json={
                    "features": {"xianyu_sync": True},
                    "limits": {"member_seats": 10},
                },
                entitlements_digest=(
                    digest_override
                    if digest_override is not None
                    else snapshot.digest_sha256
                ),
                active=True,
            )
        )


def _service(now=NOW):
    return SubscriptionLedgerService(database_clock=lambda _session: now)


def _record(service, session, *, key="default-tenant:v1", database_uuid=DATABASE_UUID):
    return service.record_default_tenant_migration_grant(
        session,
        tenant_uuid=TENANT_UUID,
        database_uuid=database_uuid,
        baseline_migration_id="initial-baseline-v1",
        migration_idempotency_key=key,
        plan_revision_uuid=PLAN_UUID,
    )


def test_default_grant_creates_one_subscription_event_and_prebuilt_guard(
    control_database,
) -> None:
    _seed(control_database)
    service = _service()

    with control_database.transaction() as session:
        result = _record(service, session)
        assert result.created is True
        assert result.expires_at == NOW + timedelta(days=36_500)

    with control_database.new_session() as session:
        subscription = session.scalar(select(Subscription))
        event = session.scalar(select(SubscriptionEvent))
        guard = session.get(
            MemberSeatGuard,
            {"tenant_id": str(TENANT_UUID), "quota_key": "member_seats"},
        )
        assert subscription.tenant_id == str(TENANT_UUID)
        assert subscription.status == "active"
        assert subscription.provider == "manual"
        assert event.source_type == "migration_grant"
        assert event.event_type == "migration_granted"
        assert event.exact_duration_seconds == 3_153_600_000
        assert event.consumed_code_uuid is None
        assert guard is not None


def test_retry_returns_original_grant_without_extending_expiry(control_database) -> None:
    _seed(control_database)
    service = _service()
    with control_database.transaction() as session:
        first = _record(service, session)

    with control_database.transaction() as session:
        retry = _record(_service(NOW + timedelta(days=30)), session)

    assert retry.created is False
    assert retry.subscription_uuid == first.subscription_uuid
    assert retry.event_uuid == first.event_uuid
    assert retry.expires_at.replace(tzinfo=timezone.utc) == first.expires_at
    with control_database.new_session() as session:
        assert session.scalar(select(func.count()).select_from(Subscription)) == 1
        assert session.scalar(select(func.count()).select_from(SubscriptionEvent)) == 1


def test_different_idempotency_key_cannot_add_a_second_grant(control_database) -> None:
    _seed(control_database)
    service = _service()
    with control_database.transaction() as session:
        _record(service, session)

    with control_database.transaction() as session:
        with pytest.raises(SubscriptionLedgerConflictError):
            _record(service, session, key="default-tenant:v2")


def test_plan_digest_mismatch_fails_before_subscription_write(control_database) -> None:
    _seed(control_database, digest_override=b"x" * 32)
    service = _service()

    with control_database.transaction() as session:
        with pytest.raises(SubscriptionPlanInvalidError, match="digest"):
            _record(service, session)

    with control_database.new_session() as session:
        assert session.scalar(select(func.count()).select_from(Subscription)) == 0
        assert session.scalar(select(func.count()).select_from(SubscriptionEvent)) == 0


def test_grant_rejects_a_database_uuid_not_owned_by_the_locked_tenant(
    control_database,
) -> None:
    _seed(control_database)

    with control_database.transaction() as session:
        with pytest.raises(SubscriptionLedgerConflictError, match="database identity"):
            _record(
                _service(),
                session,
                database_uuid=UUID("10000000-0000-4000-8000-000000000099"),
            )

    with control_database.new_session() as session:
        assert session.scalar(select(func.count()).select_from(Subscription)) == 0


def test_service_requires_caller_transaction_and_valid_database_clock(
    control_database,
) -> None:
    _seed(control_database)
    with control_database.new_session() as session:
        with pytest.raises(SubscriptionLedgerTransactionError, match="caller-owned"):
            _record(_service(), session)

    with control_database.transaction() as session:
        with pytest.raises(SubscriptionLedgerTransactionError, match="clock"):
            _record(
                SubscriptionLedgerService(database_clock=lambda _session: None),
                session,
            )
