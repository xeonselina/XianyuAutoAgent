from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, select

from inventory_control import ControlBase, ControlDatabase
from inventory_control.models import (
    PlanRevision,
    PlatformAdmin,
    RedemptionCode,
    RedemptionCodeBatch,
    Subscription,
    SubscriptionEvent,
    Tenant,
    TenantMembership,
    User,
)
from inventory_control.subscriptions import (
    SubscriptionRenewalAuthorizationError,
    SubscriptionRenewalCodeError,
    SubscriptionRenewalConflictError,
    SubscriptionRenewalGate,
    SubscriptionRenewalGateError,
    SubscriptionRenewalService,
    SubscriptionRenewalTransactionError,
    parse_core_entitlements,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
TENANT_UUID = UUID("10000000-0000-4000-8000-000000000001")
USER_UUID = UUID("10000000-0000-4000-8000-000000000002")
MEMBERSHIP_UUID = UUID("10000000-0000-4000-8000-000000000003")
SUBSCRIPTION_UUID = UUID("10000000-0000-4000-8000-000000000004")
OLD_PLAN_UUID = UUID("10000000-0000-4000-8000-000000000005")
CODE_PLAN_UUID = UUID("10000000-0000-4000-8000-000000000006")
ADMIN_UUID = UUID("10000000-0000-4000-8000-000000000007")
BATCH_UUID = UUID("10000000-0000-4000-8000-000000000008")
CODE_UUID = UUID("10000000-0000-4000-8000-000000000009")
RUN_UUID = UUID("10000000-0000-4000-8000-000000000010")
OTHER_RUN_UUID = UUID("10000000-0000-4000-8000-000000000011")
LOOKUP_HASH = b"c" * 32
OLD_ENTITLEMENTS = {
    "features": {"xianyu_sync": False},
    "limits": {"member_seats": 10},
}
CODE_ENTITLEMENTS = {
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
    access_version=7,
    tenant_row_version=3,
    membership_role="admin",
    membership_status="active",
    expires_at=NOW + timedelta(days=10),
    subscription_revision=4,
    code_status="active",
    code_run=RUN_UUID,
    redeem_before=NOW + timedelta(days=20),
    code_digest_override=None,
):
    old_snapshot = parse_core_entitlements(
        schema_version=1,
        entitlements=OLD_ENTITLEMENTS,
    )
    code_snapshot = parse_core_entitlements(
        schema_version=1,
        entitlements=CODE_ENTITLEMENTS,
    )
    code_digest = code_digest_override or code_snapshot.digest_sha256
    with database.transaction() as session:
        session.add(
            Tenant(
                id=str(TENANT_UUID),
                status=tenant_status,
                access_version=access_version,
                row_version=tenant_row_version,
            )
        )
        session.add(
            User(
                id=str(USER_UUID),
                phone_e164="+8613800000000",
                phone_normalization_version=1,
                phone_metadata_version="test-v1",
                phone_verified_at=NOW,
                status="active",
            )
        )
        session.add(
            TenantMembership(
                id=str(MEMBERSHIP_UUID),
                tenant_id=str(TENANT_UUID),
                user_id=str(USER_UUID),
                role_key=membership_role,
                status=membership_status,
                source_type="migration",
                row_version=2,
            )
        )
        session.add_all(
            [
                PlanRevision(
                    id=str(OLD_PLAN_UUID),
                    code="core",
                    revision=1,
                    name="Core r1",
                    entitlements_schema_version=1,
                    entitlements_json=OLD_ENTITLEMENTS,
                    entitlements_digest=old_snapshot.digest_sha256,
                    active=False,
                ),
                PlanRevision(
                    id=str(CODE_PLAN_UUID),
                    code="core",
                    revision=2,
                    name="Core r2",
                    entitlements_schema_version=1,
                    entitlements_json=CODE_ENTITLEMENTS,
                    entitlements_digest=code_digest,
                    # A code freezes its terms; later plan retirement must not
                    # silently change or invalidate those terms.
                    active=False,
                ),
            ]
        )
        session.add(
            PlatformAdmin(
                id=str(ADMIN_UUID),
                username_canonical="platform-admin",
                status="active",
                password_hash_encoded="scrypt$redacted",
                password_hash_algorithm="scrypt",
                password_hash_version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            Subscription(
                id=str(SUBSCRIPTION_UUID),
                tenant_id=str(TENANT_UUID),
                plan_revision_uuid=str(OLD_PLAN_UUID),
                entitlements_schema_version=1,
                entitlements_json=OLD_ENTITLEMENTS,
                entitlements_digest=old_snapshot.digest_sha256,
                status="active" if expires_at > NOW else "expired",
                expires_at=expires_at,
                row_version=subscription_revision,
                provider="manual",
            )
        )
        session.flush()
        session.add(
            RedemptionCodeBatch(
                id=str(BATCH_UUID),
                generation_request_uuid="10000000-0000-4000-8000-000000000012",
                request_digest=b"b" * 32,
                name="test batch",
                quantity=1,
                plan_revision_uuid=str(CODE_PLAN_UUID),
                entitlements_schema_version=1,
                entitlements_json=CODE_ENTITLEMENTS,
                entitlements_digest=code_digest,
                service_duration_seconds=30 * 24 * 60 * 60,
                default_redeem_before=redeem_before,
                created_by_platform_admin_id=str(ADMIN_UUID),
                created_at=NOW - timedelta(days=1),
                plaintext_exported_at=NOW - timedelta(days=1),
            )
        )
        values = {
            "id": str(CODE_UUID),
            "crypto_context_uuid": "10000000-0000-4000-8000-000000000013",
            "batch_id": str(BATCH_UUID),
            "code_prefix": "ABCD",
            "lookup_hash": LOOKUP_HASH,
            "code_ciphertext": b"x" * 42,
            "code_nonce": b"n" * 12,
            "secret_revision": 1,
            "root_key_version": 1,
            "crypto_version": 1,
            "aad_version": 1,
            "status": code_status,
            "plan_revision_uuid": str(CODE_PLAN_UUID),
            "entitlements_schema_version": 1,
            "entitlements_json": CODE_ENTITLEMENTS,
            "entitlements_digest": code_digest,
            "service_duration_seconds": 30 * 24 * 60 * 60,
            "redeem_before": redeem_before,
            "created_under_recovery_run_uuid": str(code_run),
            "row_version": 5,
            "created_at": NOW - timedelta(days=1),
            "updated_at": NOW - timedelta(days=1),
        }
        if code_status == "reserved":
            values.update(
                reserved_registration_attempt_uuid=(
                    "10000000-0000-4000-8000-000000000014"
                ),
                reserved_user_uuid=str(USER_UUID),
            )
        elif code_status == "redeemed":
            values.update(
                redeemed_tenant_uuid=str(TENANT_UUID),
                redeemed_at=NOW - timedelta(hours=1),
            )
        elif code_status == "revoked":
            values.update(
                revoked_at=NOW - timedelta(hours=1),
                revocation_reason_code="test_revocation",
            )
        session.add(RedemptionCode(**values))


def _gate(**overrides):
    values = {
        "recovery_run_completed": True,
        "tenant_hold_released": True,
        "no_unresolved_deletion": True,
        "no_unresolved_suspension": True,
    }
    values.update(overrides)
    return SubscriptionRenewalGate(**values)


def _service(*, gate=None, clock=NOW):
    current_gate = _gate() if gate is None else gate
    return SubscriptionRenewalService(
        gate_current_read=lambda *_args: current_gate,
        database_clock=lambda _session: clock,
    )


def _renew(service, session, **overrides):
    values = {
        "tenant_uuid": TENANT_UUID,
        "membership_uuid": MEMBERSHIP_UUID,
        "code_lookup_hash": LOOKUP_HASH,
        "idempotency_key": "renewal:request:1",
        "current_recovery_run_uuid": RUN_UUID,
        "expected_tenant_access_version": 7,
        "expected_subscription_row_version": 4,
    }
    values.update(overrides)
    return service.renew(session, **values)


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def test_active_renewal_consumes_code_and_uses_frozen_snapshot(control_database):
    _seed(control_database)
    with control_database.transaction() as session:
        result = _renew(_service(), session)

    assert result.created is True
    assert result.before_status == "active"
    assert result.calculation_base_at == NOW + timedelta(days=10)
    assert result.after_expires_at == NOW + timedelta(days=40)
    assert result.resulting_subscription_row_version == 5

    with control_database.new_session() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        code = session.get(RedemptionCode, str(CODE_UUID))
        subscription = session.get(Subscription, str(SUBSCRIPTION_UUID))
        event = session.scalar(select(SubscriptionEvent))
        assert tenant.status == "active"
        assert tenant.row_version == 3
        assert tenant.access_version == 7
        assert code.status == "redeemed"
        assert code.redeemed_tenant_uuid == str(TENANT_UUID)
        assert code.row_version == 6
        assert subscription.plan_revision_uuid == str(CODE_PLAN_UUID)
        assert subscription.entitlements_json == CODE_ENTITLEMENTS
        assert subscription.row_version == 5
        assert _utc(subscription.expires_at) == NOW + timedelta(days=40)
        assert event.source_uuid == str(CODE_UUID)
        assert event.consumed_code_uuid == str(CODE_UUID)
        assert event.exact_duration_seconds == 30 * 24 * 60 * 60
        assert event.before_plan_revision_uuid == str(OLD_PLAN_UUID)
        assert event.after_plan_revision_uuid == str(CODE_PLAN_UUID)


def test_expired_renewal_starts_at_database_now_and_reactivates_tenant(
    control_database,
):
    _seed(
        control_database,
        tenant_status="expired",
        expires_at=NOW - timedelta(days=3),
    )
    with control_database.transaction() as session:
        result = _renew(_service(), session)

    assert result.before_status == "expired"
    assert result.calculation_base_at == NOW
    assert result.after_expires_at == NOW + timedelta(days=30)
    with control_database.new_session() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        assert tenant.status == "active"
        assert tenant.access_version == 7
        assert tenant.row_version == 4


def test_retry_returns_original_result_without_reusing_code_or_clock(
    control_database,
):
    _seed(control_database)
    with control_database.transaction() as session:
        first = _renew(_service(), session)
    with control_database.transaction() as session:
        retry = _renew(_service(clock=NOW + timedelta(days=90)), session)

    assert retry.created is False
    assert retry.event_uuid == first.event_uuid
    assert retry.after_expires_at == first.after_expires_at
    with control_database.new_session() as session:
        assert session.scalar(select(func.count()).select_from(SubscriptionEvent)) == 1
        assert session.get(RedemptionCode, str(CODE_UUID)).row_version == 6
        assert session.get(Subscription, str(SUBSCRIPTION_UUID)).row_version == 5


def test_same_code_or_key_with_changed_request_is_a_conflict(control_database):
    _seed(control_database)
    with control_database.transaction() as session:
        _renew(_service(), session)

    with pytest.raises(SubscriptionRenewalConflictError):
        with control_database.transaction() as session:
            _renew(
                _service(),
                session,
                idempotency_key="renewal:request:2",
            )
    with pytest.raises(SubscriptionRenewalConflictError):
        with control_database.transaction() as session:
            _renew(
                _service(),
                session,
                expected_tenant_access_version=8,
            )


@pytest.mark.parametrize(
    "gate",
    [
        _gate(recovery_run_completed=False),
        _gate(tenant_hold_released=False),
        _gate(no_unresolved_deletion=False),
        _gate(no_unresolved_suspension=False),
        None,
    ],
)
def test_each_incomplete_lifecycle_fact_rejects_without_consuming_code(
    control_database,
    gate,
):
    _seed(control_database)
    service = SubscriptionRenewalService(
        gate_current_read=lambda *_args: gate,
        database_clock=lambda _session: NOW,
    )
    with pytest.raises(SubscriptionRenewalGateError):
        with control_database.transaction() as session:
            _renew(service, session)
    _assert_unchanged(control_database)


@pytest.mark.parametrize(
    ("role", "status"),
    [("operator", "active"), ("admin", "disabled")],
)
def test_only_active_admin_membership_can_renew(
    control_database,
    role,
    status,
):
    _seed(
        control_database,
        membership_role=role,
        membership_status=status,
    )
    with pytest.raises(SubscriptionRenewalAuthorizationError):
        with control_database.transaction() as session:
            _renew(_service(), session)
    _assert_unchanged(control_database)


@pytest.mark.parametrize(
    "overrides",
    [
        {"code_run": OTHER_RUN_UUID},
        {"redeem_before": NOW},
        {"code_status": "reserved"},
        {"code_status": "revoked"},
        {"code_status": "redeemed"},
    ],
)
def test_non_current_or_non_active_code_is_not_redeemable(
    control_database,
    overrides,
):
    _seed(control_database, **overrides)
    with pytest.raises(SubscriptionRenewalCodeError):
        with control_database.transaction() as session:
            _renew(_service(), session)
    with control_database.new_session() as session:
        assert session.scalar(select(func.count()).select_from(SubscriptionEvent)) == 0
        assert session.get(Subscription, str(SUBSCRIPTION_UUID)).row_version == 4


def test_stale_access_or_subscription_revision_rejects_before_consumption(
    control_database,
):
    _seed(control_database)
    with pytest.raises(SubscriptionRenewalGateError):
        with control_database.transaction() as session:
            _renew(
                _service(),
                session,
                expected_tenant_access_version=6,
            )
    with pytest.raises(SubscriptionRenewalConflictError):
        with control_database.transaction() as session:
            _renew(
                _service(),
                session,
                expected_subscription_row_version=3,
            )
    _assert_unchanged(control_database)


def test_corrupted_frozen_entitlement_digest_fails_closed(control_database):
    _seed(control_database, code_digest_override=b"z" * 32)
    with pytest.raises(SubscriptionRenewalCodeError, match="terms"):
        with control_database.transaction() as session:
            _renew(_service(), session)
    _assert_unchanged(control_database)


def test_outer_rollback_restores_code_subscription_and_tenant(control_database):
    _seed(
        control_database,
        tenant_status="expired",
        expires_at=NOW - timedelta(days=1),
    )
    session = control_database.new_session()
    try:
        with session.begin():
            _renew(_service(), session)
            raise RuntimeError("later audit write failed")
    except RuntimeError:
        pass
    finally:
        session.close()

    _assert_unchanged(
        control_database,
        expected_tenant_status="expired",
        expected_expiry=NOW - timedelta(days=1),
    )


def test_service_requires_explicit_clean_caller_transaction(control_database):
    _seed(control_database)
    with control_database.new_session() as session:
        with pytest.raises(SubscriptionRenewalTransactionError):
            _renew(_service(), session)

    with control_database.new_session() as session:
        with session.begin():
            session.add(Tenant(id="20000000-0000-4000-8000-000000000001"))
            with pytest.raises(SubscriptionRenewalTransactionError, match="clean"):
                _renew(_service(), session)


def test_suspended_tenant_and_invalid_hash_do_not_enumerate_code(control_database):
    _seed(control_database, tenant_status="suspended")
    with pytest.raises(SubscriptionRenewalGateError):
        with control_database.transaction() as session:
            _renew(_service(), session)

    with pytest.raises(SubscriptionRenewalCodeError) as error:
        with control_database.transaction() as session:
            _renew(_service(), session, code_lookup_hash=b"short")
    assert error.value.code == "CODE_NOT_REDEEMABLE"


def _assert_unchanged(
    database,
    *,
    expected_tenant_status="active",
    expected_expiry=NOW + timedelta(days=10),
):
    with database.new_session() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        code = session.get(RedemptionCode, str(CODE_UUID))
        subscription = session.get(Subscription, str(SUBSCRIPTION_UUID))
        assert tenant.status == expected_tenant_status
        assert tenant.row_version == 3
        assert tenant.access_version == 7
        assert code.status == "active"
        assert code.row_version == 5
        assert subscription.row_version == 4
        assert _utc(subscription.expires_at) == expected_expiry
        assert session.scalar(select(func.count()).select_from(SubscriptionEvent)) == 0
