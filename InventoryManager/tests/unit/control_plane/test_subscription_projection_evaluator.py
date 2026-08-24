from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from inventory_control import ControlBase, ControlDatabase
from inventory_control.models import PlanRevision, Subscription, Tenant
from inventory_control.subscriptions import (
    SubscriptionProjectionConflictError,
    SubscriptionProjectionEvaluator,
    SubscriptionProjectionLifecycleLocks,
    SubscriptionProjectionTransactionError,
    parse_core_entitlements,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
TENANT_UUID = UUID("20000000-0000-4000-8000-000000000001")
PLAN_UUID = UUID("20000000-0000-4000-8000-000000000002")
SUBSCRIPTION_UUID = UUID("20000000-0000-4000-8000-000000000003")
ENTITLEMENTS = {
    "features": {"xianyu_sync": True},
    "limits": {"member_seats": 10},
}


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


def _seed(
    database,
    *,
    tenant_status="active",
    subscription_status="active",
    expires_at=NOW + timedelta(days=1),
):
    snapshot = parse_core_entitlements(
        schema_version=1,
        entitlements=ENTITLEMENTS,
    )
    with database.transaction() as session:
        session.add(
            Tenant(
                id=str(TENANT_UUID),
                status=tenant_status,
                access_version=11,
                row_version=4,
            )
        )
        session.add(
            PlanRevision(
                id=str(PLAN_UUID),
                code="core",
                revision=1,
                name="Core",
                entitlements_schema_version=1,
                entitlements_json=ENTITLEMENTS,
                entitlements_digest=snapshot.digest_sha256,
                active=True,
            )
        )
        session.add(
            Subscription(
                id=str(SUBSCRIPTION_UUID),
                tenant_id=str(TENANT_UUID),
                plan_revision_uuid=str(PLAN_UUID),
                entitlements_schema_version=1,
                entitlements_json=ENTITLEMENTS,
                entitlements_digest=snapshot.digest_sha256,
                status=subscription_status,
                expires_at=expires_at,
                row_version=6,
                provider="manual",
            )
        )


def _evaluate(database, *, now=NOW):
    evaluator = SubscriptionProjectionEvaluator(
        lifecycle_locker=_test_lifecycle_locker,
        database_clock=lambda _session: now,
    )
    with database.transaction() as session:
        return evaluator.evaluate(session, tenant_uuid=TENANT_UUID)


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _test_lifecycle_locker(_session, _tenant):
    return SubscriptionProjectionLifecycleLocks(
        recovery_run_uuid="10000000-0000-4000-8000-000000000001",
        recovery_hold_uuid="10000000-0000-4000-8000-000000000002",
        deletion_request_uuid=None,
        suspension_uuid=None,
        suspension_action_uuid=None,
    )


def test_exact_expiry_boundary_projects_both_rows_to_expired(control_database):
    _seed(control_database, expires_at=NOW)

    result = _evaluate(control_database)

    assert result.effective_status == "expired"
    assert result.tenant_changed is True
    assert result.subscription_changed is True
    assert result.tenant_row_version_after == 5
    assert result.subscription_row_version_after == 7
    with control_database.new_session() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        subscription = session.get(Subscription, str(SUBSCRIPTION_UUID))
        assert tenant.status == "expired"
        assert tenant.access_version == 11
        assert tenant.row_version == 5
        assert subscription.status == "expired"
        assert subscription.row_version == 7


def test_evaluation_is_idempotent_and_does_not_append_subscription_event(
    control_database,
):
    _seed(control_database, expires_at=NOW - timedelta(seconds=1))

    first = _evaluate(control_database)
    second = _evaluate(control_database, now=NOW + timedelta(days=2))

    assert first.tenant_changed and first.subscription_changed
    assert not second.tenant_changed
    assert not second.subscription_changed
    assert second.tenant_row_version_before == 5
    assert second.subscription_row_version_before == 7


def test_future_expiry_reactivates_stale_expired_projection(control_database):
    _seed(
        control_database,
        tenant_status="expired",
        subscription_status="expired",
        expires_at=NOW + timedelta(days=30),
    )

    result = _evaluate(control_database)

    assert result.effective_status == "active"
    with control_database.new_session() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        subscription = session.get(Subscription, str(SUBSCRIPTION_UUID))
        assert tenant.status == "active"
        assert tenant.access_version == 11
        assert subscription.status == "active"


@pytest.mark.parametrize(
    "tenant_status",
    [
        "provisioning",
        "suspending",
        "suspended",
        "resuming",
        "deletion_cooling_off",
        "deletion_committing",
        "deleted",
    ],
)
def test_higher_priority_tenant_state_is_never_overwritten(
    control_database,
    tenant_status,
):
    _seed(
        control_database,
        tenant_status=tenant_status,
        subscription_status="active",
        expires_at=NOW - timedelta(days=1),
    )

    result = _evaluate(control_database)

    assert result.tenant_changed is False
    assert result.tenant_status_after == tenant_status
    assert result.subscription_changed is True
    assert result.subscription_status_after == "expired"
    with control_database.new_session() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        subscription = session.get(Subscription, str(SUBSCRIPTION_UUID))
        assert tenant.status == tenant_status
        assert tenant.row_version == 4
        assert tenant.access_version == 11
        assert subscription.status == "expired"


def test_projection_uses_database_clock_not_caller_expiry_guess(control_database):
    deadline = NOW + timedelta(hours=1)
    _seed(control_database, expires_at=deadline)

    active = _evaluate(control_database, now=deadline - timedelta(microseconds=1))
    expired = _evaluate(control_database, now=deadline)

    assert active.effective_status == "active"
    assert expired.effective_status == "expired"
    assert expired.evaluated_at == deadline


def test_outer_rollback_reverts_both_projection_updates(control_database):
    _seed(control_database, expires_at=NOW - timedelta(days=1))
    evaluator = SubscriptionProjectionEvaluator(
        lifecycle_locker=_test_lifecycle_locker,
        database_clock=lambda _session: NOW,
    )
    session = control_database.new_session()
    try:
        with session.begin():
            evaluator.evaluate(session, tenant_uuid=TENANT_UUID)
            raise RuntimeError("later operation failed")
    except RuntimeError:
        pass
    finally:
        session.close()

    with control_database.new_session() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        subscription = session.get(Subscription, str(SUBSCRIPTION_UUID))
        assert tenant.status == "active"
        assert tenant.row_version == 4
        assert subscription.status == "active"
        assert subscription.row_version == 6
        assert _utc(subscription.expires_at) == NOW - timedelta(days=1)


def test_missing_subscription_and_dirty_unit_of_work_fail_closed(control_database):
    with control_database.transaction() as session:
        session.add(Tenant(id=str(TENANT_UUID), status="active"))

    evaluator = SubscriptionProjectionEvaluator(
        lifecycle_locker=_test_lifecycle_locker,
        database_clock=lambda _session: NOW,
    )
    with pytest.raises(SubscriptionProjectionConflictError):
        with control_database.transaction() as session:
            evaluator.evaluate(session, tenant_uuid=TENANT_UUID)

    with control_database.new_session() as session:
        with session.begin():
            session.add(Tenant(id="30000000-0000-4000-8000-000000000001"))
            with pytest.raises(SubscriptionProjectionTransactionError, match="clean"):
                evaluator.evaluate(session, tenant_uuid=TENANT_UUID)


def test_requires_explicit_transaction_and_valid_database_time(control_database):
    _seed(control_database)
    evaluator = SubscriptionProjectionEvaluator(
        lifecycle_locker=_test_lifecycle_locker,
        database_clock=lambda _session: NOW,
    )
    with control_database.new_session() as session:
        with pytest.raises(SubscriptionProjectionTransactionError):
            evaluator.evaluate(session, tenant_uuid=TENANT_UUID)

    evaluator = SubscriptionProjectionEvaluator(
        lifecycle_locker=_test_lifecycle_locker,
        database_clock=lambda _session: "not-a-time",
    )
    with pytest.raises(SubscriptionProjectionTransactionError, match="clock"):
        with control_database.transaction() as session:
            evaluator.evaluate(session, tenant_uuid=TENANT_UUID)
