import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from inventory_control import ControlDatabase
from inventory_control.models import (
    ControlBase,
    MemberSeatGuard,
    PlanRevision,
    Subscription,
    SubscriptionEvent,
    Tenant,
)


CORE_ENTITLEMENTS = {"limits": {"member_seats": 10}}


def _canonical_digest(value=CORE_ENTITLEMENTS):
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).digest()


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


def _plan(*, code="core", revision=1):
    return PlanRevision(
        code=code,
        revision=revision,
        name="SaaS Core",
        entitlements_schema_version=1,
        entitlements_json=CORE_ENTITLEMENTS,
        entitlements_digest=_canonical_digest(),
        active=True,
    )


def _subscription(*, tenant, plan, now, registration_commit_uuid=None):
    return Subscription(
        tenant_id=tenant.id,
        plan_revision_uuid=plan.id,
        entitlements_schema_version=plan.entitlements_schema_version,
        entitlements_json=CORE_ENTITLEMENTS,
        entitlements_digest=plan.entitlements_digest,
        status="active",
        expires_at=now + timedelta(days=30),
        provider="manual",
        provider_ref="offline-contract-1",
        created_from_registration_commit_uuid=registration_commit_uuid,
    )


def _registration_event(*, tenant, subscription, plan, now, **overrides):
    values = {
        "tenant_id": tenant.id,
        "subscription_id": subscription.id,
        "event_type": "activated",
        "source_type": "registration",
        "source_uuid": str(uuid4()),
        "consumed_code_uuid": str(uuid4()),
        "before_plan_revision_uuid": None,
        "after_plan_revision_uuid": plan.id,
        "before_entitlements_digest": None,
        "after_entitlements_digest": plan.entitlements_digest,
        "exact_duration_seconds": 30 * 24 * 60 * 60,
        "signed_delta_days": None,
        "calculation_base_at": now,
        "database_effective_at": now,
        "before_expires_at": None,
        "after_expires_at": subscription.expires_at,
        "before_status": None,
        "after_status": "active",
        "expected_subscription_row_version": None,
        "idempotency_key": str(uuid4()),
        "request_digest": hashlib.sha256(b"registration-request").digest(),
        "canonicalization_version": 1,
        "platform_actor_id": None,
        "platform_session_id": None,
        "factor_method": None,
        "factor_accepted_at": None,
        "reason_code": "registration",
        "note": None,
        "offline_reference": None,
    }
    values.update(overrides)
    return SubscriptionEvent(**values)


def _platform_adjustment_event(*, tenant, subscription, plan, now, **overrides):
    values = {
        "tenant_id": tenant.id,
        "subscription_id": subscription.id,
        "event_type": "days_adjusted",
        "source_type": "platform_adjustment",
        "source_uuid": str(uuid4()),
        "consumed_code_uuid": None,
        "before_plan_revision_uuid": plan.id,
        "after_plan_revision_uuid": plan.id,
        "before_entitlements_digest": plan.entitlements_digest,
        "after_entitlements_digest": plan.entitlements_digest,
        "exact_duration_seconds": None,
        "signed_delta_days": 7,
        "calculation_base_at": subscription.expires_at,
        "database_effective_at": now,
        "before_expires_at": subscription.expires_at,
        "after_expires_at": subscription.expires_at + timedelta(days=7),
        "before_status": "active",
        "after_status": "active",
        "expected_subscription_row_version": 1,
        "idempotency_key": str(uuid4()),
        "request_digest": hashlib.sha256(b"adjustment-request").digest(),
        "canonicalization_version": 1,
        "platform_actor_id": str(uuid4()),
        "platform_session_id": str(uuid4()),
        "factor_method": "totp",
        "factor_accepted_at": now,
        "reason_code": "service_compensation",
        "note": "safe note",
        "offline_reference": "offline-case-1",
    }
    values.update(overrides)
    return SubscriptionEvent(**values)


def _persist_subscription_graph(database):
    now = datetime.now(timezone.utc)
    tenant = Tenant(name="Test tenant", slug="test-tenant")
    plan = _plan()
    registration_commit_uuid = str(uuid4())
    with database.transaction() as session:
        session.add_all((tenant, plan))
        session.flush()
        guard = MemberSeatGuard(tenant_id=tenant.id)
        subscription = _subscription(
            tenant=tenant,
            plan=plan,
            now=now,
            registration_commit_uuid=registration_commit_uuid,
        )
        session.add_all((guard, subscription))
        session.flush()
        event = _registration_event(
            tenant=tenant,
            subscription=subscription,
            plan=plan,
            now=now,
            source_uuid=registration_commit_uuid,
        )
        session.add(event)
    return now, tenant, plan, guard, subscription, event


def test_subscription_foundation_persists_frozen_snapshots(control_database):
    _, tenant, plan, guard, subscription, event = _persist_subscription_graph(
        control_database
    )

    assert plan.entitlements_json == CORE_ENTITLEMENTS
    assert subscription.entitlements_json == CORE_ENTITLEMENTS
    assert subscription.entitlements_digest == plan.entitlements_digest
    assert subscription.tenant_id == tenant.id
    assert subscription.row_version == 1
    assert subscription.status == "active"
    assert guard.quota_key == "member_seats"
    assert event.subscription_id == subscription.id
    assert event.after_plan_revision_uuid == plan.id
    assert event.exact_duration_seconds == 30 * 24 * 60 * 60
    assert event.signed_delta_days is None


def test_plan_code_revision_is_unique_and_positive(control_database):
    with control_database.transaction() as session:
        session.add(_plan())

    with pytest.raises(DBAPIError):
        with control_database.transaction() as session:
            session.add(_plan())

    with pytest.raises(DBAPIError):
        with control_database.transaction() as session:
            session.add(_plan(code="invalid", revision=0))


def test_only_one_subscription_can_exist_per_tenant(control_database):
    now = datetime.now(timezone.utc)
    tenant = Tenant()
    plan = _plan()
    with control_database.transaction() as session:
        session.add_all((tenant, plan))

    with pytest.raises(DBAPIError):
        with control_database.transaction() as session:
            session.add_all(
                (
                    _subscription(tenant=tenant, plan=plan, now=now),
                    _subscription(tenant=tenant, plan=plan, now=now),
                )
            )


def test_member_seat_guard_has_no_cached_usage_and_rejects_other_quota_keys(
    control_database,
):
    columns = set(MemberSeatGuard.__table__.columns.keys())
    assert columns == {
        "tenant_id",
        "quota_key",
        "row_version",
        "created_at",
        "updated_at",
    }

    tenant = Tenant()
    with pytest.raises(DBAPIError):
        with control_database.transaction() as session:
            session.add(tenant)
            session.flush()
            session.add(
                MemberSeatGuard(
                    tenant_id=tenant.id,
                    quota_key="active_devices",
                )
            )


def test_platform_adjustment_requires_fresh_factor_evidence(control_database):
    now, tenant, plan, _, subscription, _ = _persist_subscription_graph(
        control_database
    )

    with pytest.raises(DBAPIError):
        with control_database.transaction() as session:
            session.add(
                _platform_adjustment_event(
                    tenant=tenant,
                    subscription=subscription,
                    plan=plan,
                    now=now,
                    factor_method=None,
                    factor_accepted_at=None,
                )
            )


def test_platform_adjustment_accepts_signed_days_without_payment_state(
    control_database,
):
    now, tenant, plan, _, subscription, _ = _persist_subscription_graph(
        control_database
    )
    event = _platform_adjustment_event(
        tenant=tenant,
        subscription=subscription,
        plan=plan,
        now=now,
        signed_delta_days=-3,
    )

    with control_database.transaction() as session:
        session.add(event)

    assert event.signed_delta_days == -3
    assert event.exact_duration_seconds is None
    forbidden = {
        "amount",
        "currency",
        "payment_amount",
        "payment_currency",
        "payment_status",
        "refund_status",
        "paid_at",
    }
    assert forbidden.isdisjoint(Subscription.__table__.columns.keys())
    assert forbidden.isdisjoint(SubscriptionEvent.__table__.columns.keys())


def test_expire_now_is_distinct_from_a_large_negative_delta(control_database):
    now, tenant, plan, _, subscription, _ = _persist_subscription_graph(
        control_database
    )
    event = _platform_adjustment_event(
        tenant=tenant,
        subscription=subscription,
        plan=plan,
        now=now,
        event_type="expired_now",
        signed_delta_days=None,
        calculation_base_at=now,
        after_expires_at=now,
        after_status="expired",
    )

    with control_database.transaction() as session:
        session.add(event)

    assert event.event_type == "expired_now"
    assert event.signed_delta_days is None


def test_registration_event_requires_consumed_code(control_database):
    now, tenant, plan, _, subscription, _ = _persist_subscription_graph(
        control_database
    )

    with pytest.raises(DBAPIError):
        with control_database.transaction() as session:
            session.add(
                _registration_event(
                    tenant=tenant,
                    subscription=subscription,
                    plan=plan,
                    now=now,
                    consumed_code_uuid=None,
                )
            )


def test_redemption_event_preserves_before_and_after_terms(control_database):
    now, tenant, plan, _, subscription, _ = _persist_subscription_graph(
        control_database
    )
    event = _registration_event(
        tenant=tenant,
        subscription=subscription,
        plan=plan,
        now=now,
        event_type="renewed",
        source_type="redemption",
        before_plan_revision_uuid=plan.id,
        before_entitlements_digest=plan.entitlements_digest,
        before_expires_at=subscription.expires_at,
        before_status="active",
        after_expires_at=subscription.expires_at + timedelta(days=30),
        expected_subscription_row_version=1,
        reason_code="redemption",
    )

    with control_database.transaction() as session:
        session.add(event)

    assert event.source_type == "redemption"
    assert event.before_entitlements_digest == event.after_entitlements_digest


def test_valid_migration_grant_freezes_exact_36500_days(control_database):
    now = datetime.now(timezone.utc)
    tenant = Tenant()
    plan = _plan()
    with control_database.transaction() as session:
        session.add_all((tenant, plan))
        session.flush()
        subscription = _subscription(tenant=tenant, plan=plan, now=now)
        subscription.expires_at = now + timedelta(days=36500)
        session.add(subscription)
        session.flush()
        event = _registration_event(
            tenant=tenant,
            subscription=subscription,
            plan=plan,
            now=now,
            event_type="migration_granted",
            source_type="migration_grant",
            consumed_code_uuid=None,
            exact_duration_seconds=36500 * 24 * 60 * 60,
            after_expires_at=subscription.expires_at,
            reason_code="initial_migration",
        )
        session.add(event)

    assert event.exact_duration_seconds == 3_153_600_000


def test_migration_grant_requires_exact_36500_day_duration(control_database):
    now = datetime.now(timezone.utc)
    tenant = Tenant()
    plan = _plan()
    with control_database.transaction() as session:
        session.add_all((tenant, plan))
        session.flush()
        subscription = _subscription(tenant=tenant, plan=plan, now=now)
        session.add(subscription)
    invalid_event = _registration_event(
        tenant=tenant,
        subscription=subscription,
        plan=plan,
        now=now,
        event_type="migration_granted",
        source_type="migration_grant",
        consumed_code_uuid=None,
        exact_duration_seconds=36500 * 24 * 60 * 60 - 1,
        reason_code="initial_migration",
    )

    with pytest.raises(DBAPIError):
        with control_database.transaction() as session:
            session.add(invalid_event)


def test_event_source_and_idempotency_keys_are_unique(control_database):
    now, tenant, plan, _, subscription, _ = _persist_subscription_graph(
        control_database
    )
    source_uuid = str(uuid4())
    idempotency_key = str(uuid4())

    with pytest.raises(DBAPIError):
        with control_database.transaction() as session:
            session.add_all(
                (
                    _registration_event(
                        tenant=tenant,
                        subscription=subscription,
                        plan=plan,
                        now=now,
                        source_uuid=source_uuid,
                        idempotency_key=idempotency_key,
                    ),
                    _registration_event(
                        tenant=tenant,
                        subscription=subscription,
                        plan=plan,
                        now=now,
                        source_uuid=source_uuid,
                        idempotency_key=str(uuid4()),
                    ),
                )
            )

    with pytest.raises(DBAPIError):
        with control_database.transaction() as session:
            session.add_all(
                (
                    _registration_event(
                        tenant=tenant,
                        subscription=subscription,
                        plan=plan,
                        now=now,
                        source_uuid=str(uuid4()),
                        idempotency_key=idempotency_key,
                    ),
                    _registration_event(
                        tenant=tenant,
                        subscription=subscription,
                        plan=plan,
                        now=now,
                        source_uuid=str(uuid4()),
                        idempotency_key=idempotency_key,
                    ),
                )
            )


def test_subscription_times_are_declared_timezone_aware_and_events_append_only():
    assert Subscription.__table__.c.expires_at.type.timezone is True
    assert SubscriptionEvent.__table__.c.database_effective_at.type.timezone is True
    assert "updated_at" not in SubscriptionEvent.__table__.columns
    assert "row_version" not in SubscriptionEvent.__table__.columns
