from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy import event, func, select

from inventory_control import ControlBase, ControlDatabase
from inventory_control.crypto import RootKey
from inventory_control.models import (
    PlanRevision,
    PlatformAdmin,
    PlatformAdminRecoveryCode,
    PlatformAdminSession,
    PlatformAdminTotpCredential,
    Subscription,
    SubscriptionEvent,
    Tenant,
)
from inventory_control.platform_identity import (
    encrypt_totp_seed,
    generate_totp_code,
    issue_recovery_code,
    totp_time_step,
)
from inventory_control.subscriptions import (
    ServicePeriodAdjustment,
    ServicePeriodReductionRejectedError,
    parse_core_entitlements,
)
from inventory_control.subscriptions.adjustment_service import (
    PlatformSubscriptionAdjustmentService,
    SubscriptionAdjustmentAuthenticationError,
    SubscriptionAdjustmentConflictError,
    SubscriptionAdjustmentGate,
    SubscriptionAdjustmentGateError,
    SubscriptionAdjustmentTransactionError,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
TENANT_UUID = UUID("51000000-0000-4000-8000-000000000001")
PLAN_UUID = UUID("51000000-0000-4000-8000-000000000002")
SUBSCRIPTION_UUID = UUID("51000000-0000-4000-8000-000000000003")
ADMIN_UUID = UUID("51000000-0000-4000-8000-000000000004")
TOTP_UUID = UUID("51000000-0000-4000-8000-000000000005")
SESSION_RECOVERY_UUID = UUID("51000000-0000-4000-8000-000000000006")
ACTION_RECOVERY_UUID = UUID("51000000-0000-4000-8000-000000000007")
PLATFORM_SESSION_UUID = UUID("51000000-0000-4000-8000-000000000008")
ACTION_UUID = UUID("51000000-0000-4000-8000-000000000009")
SECOND_ACTION_UUID = UUID("51000000-0000-4000-8000-00000000000a")

ROOT_KEY = RootKey(version=7, material=bytes(range(32)))
TOTP_SEED = b"12345678901234567890"


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


@dataclass(frozen=True)
class SeededFactors:
    recovery_code: str


def _seed(
    control_database,
    *,
    tenant_status: str = "active",
    expires_at: datetime = NOW + timedelta(days=10),
) -> SeededFactors:
    snapshot = parse_core_entitlements(
        schema_version=1,
        entitlements={
            "features": {"xianyu_sync": True},
            "limits": {"member_seats": 10},
        },
    )
    action_code = issue_recovery_code()
    session_code = issue_recovery_code()
    envelope = encrypt_totp_seed(
        root_key=ROOT_KEY,
        credential_id=str(TOTP_UUID),
        platform_admin_id=str(ADMIN_UUID),
        secret_revision=1,
        seed=TOTP_SEED,
    )
    current_step = totp_time_step(int(NOW.timestamp()))

    with control_database.transaction() as session:
        session.add(
            Tenant(
                id=str(TENANT_UUID),
                status=tenant_status,
                access_version=9,
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
                entitlements_json={
                    "features": {"xianyu_sync": True},
                    "limits": {"member_seats": 10},
                },
                entitlements_digest=snapshot.digest_sha256,
                active=True,
            )
        )
        session.add(
            PlatformAdmin(
                id=str(ADMIN_UUID),
                username_canonical="root.admin",
                status="active",
                password_hash_encoded="$argon2id-v1$redacted",
                password_hash_algorithm="argon2id",
                password_hash_version=1,
                auth_version=3,
                setup_version=2,
                totp_generation=1,
                recovery_code_generation=1,
                row_version=1,
                created_at=NOW - timedelta(days=10),
                updated_at=NOW - timedelta(days=1),
            )
        )
        session.flush()

        session.add(
            Subscription(
                id=str(SUBSCRIPTION_UUID),
                tenant_id=str(TENANT_UUID),
                plan_revision_uuid=str(PLAN_UUID),
                entitlements_schema_version=1,
                entitlements_json={
                    "features": {"xianyu_sync": True},
                    "limits": {"member_seats": 10},
                },
                entitlements_digest=snapshot.digest_sha256,
                status="active" if expires_at > NOW else "expired",
                expires_at=expires_at,
                row_version=1,
                provider="manual",
            )
        )
        session.add(
            PlatformAdminTotpCredential(
                id=str(TOTP_UUID),
                platform_admin_id=str(ADMIN_UUID),
                generation=1,
                secret_revision=1,
                status="confirmed",
                seed_nonce=envelope.nonce,
                seed_ciphertext=envelope.ciphertext,
                root_key_version=envelope.root_key_version,
                crypto_version=envelope.crypto_version,
                aad_version=envelope.aad_version,
                totp_algorithm="SHA1",
                totp_digits=6,
                totp_period_seconds=30,
                last_accepted_time_step=current_step - 1,
                row_version=1,
                created_at=NOW - timedelta(days=5),
                confirmed_at=NOW - timedelta(days=5),
            )
        )
        session.add_all(
            [
                PlatformAdminRecoveryCode(
                    id=str(SESSION_RECOVERY_UUID),
                    platform_admin_id=str(ADMIN_UUID),
                    generation=1,
                    ordinal=1,
                    token_digest_sha256=session_code.digest_sha256,
                    state="consumed",
                    row_version=2,
                    created_at=NOW - timedelta(days=5),
                    consumed_at=NOW - timedelta(hours=1),
                ),
                PlatformAdminRecoveryCode(
                    id=str(ACTION_RECOVERY_UUID),
                    platform_admin_id=str(ADMIN_UUID),
                    generation=1,
                    ordinal=2,
                    token_digest_sha256=action_code.digest_sha256,
                    state="active",
                    row_version=1,
                    created_at=NOW - timedelta(days=5),
                ),
            ]
        )
        session.flush()

        session.add(
            PlatformAdminSession(
                id=str(PLATFORM_SESSION_UUID),
                platform_admin_id=str(ADMIN_UUID),
                token_digest_sha256=b"s" * 32,
                csrf_digest_sha256=b"c" * 32,
                auth_version_at_issue=3,
                setup_version_at_issue=2,
                mfa_method="recovery_code",
                mfa_verified_at=NOW - timedelta(hours=1),
                recovery_code_id=str(SESSION_RECOVERY_UUID),
                policy_version=1,
                csrf_generation=1,
                idle_timeout_seconds=7_200,
                created_at=NOW - timedelta(hours=1),
                last_seen_at=NOW - timedelta(minutes=5),
                idle_expires_at=NOW + timedelta(hours=1),
                absolute_expires_at=NOW + timedelta(hours=4),
            )
        )
    return SeededFactors(recovery_code=action_code.plaintext)


def _open_gate(_session, tenant, _database_now):
    suspended = tenant.status == "suspended"
    return SubscriptionAdjustmentGate(
        recovery_run_completed=True,
        tenant_hold_released=True,
        no_unresolved_deletion=True,
        suspension_state="active" if suspended else None,
        suspension_barrier_complete=suspended,
    )


def _service(*, gate=_open_gate, clock=lambda _session: NOW):
    return PlatformSubscriptionAdjustmentService(
        gate_current_read=gate,
        database_clock=clock,
    )


def _adjust(
    service,
    session,
    *,
    recovery_code,
    adjustment=ServicePeriodAdjustment(add_days=5),
    action_uuid=ACTION_UUID,
    idempotency_key="d53:action-1",
    expected_revision=1,
    reason_code="customer_compensation",
    note="Five service days restored.",
    offline_reference="CASE-2026-001",
    factor_method="recovery_code",
    presented_factor=None,
    root_key=None,
):
    return service.adjust(
        session,
        tenant_uuid=TENANT_UUID,
        platform_actor_uuid=ADMIN_UUID,
        platform_session_uuid=PLATFORM_SESSION_UUID,
        action_uuid=action_uuid,
        idempotency_key=idempotency_key,
        expected_subscription_row_version=expected_revision,
        adjustment=adjustment,
        reason_code=reason_code,
        note=note,
        offline_reference=offline_reference,
        factor_method=factor_method,
        presented_factor=(
            recovery_code if presented_factor is None else presented_factor
        ),
        root_key=root_key,
    )


def _as_utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def test_recovery_factor_add_is_one_atomic_subscription_event(control_database):
    factors = _seed(control_database)

    with control_database.transaction() as session:
        result = _adjust(_service(), session, recovery_code=factors.recovery_code)

    assert result.created is True
    assert result.before_expires_at == NOW + timedelta(days=10)
    assert result.calculation_base_at == NOW + timedelta(days=10)
    assert result.after_expires_at == NOW + timedelta(days=15)
    assert result.signed_delta_days == 5
    assert result.resulting_subscription_row_version == 2

    with control_database.new_session() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        subscription = session.get(Subscription, str(SUBSCRIPTION_UUID))
        recovery = session.get(
            PlatformAdminRecoveryCode,
            str(ACTION_RECOVERY_UUID),
        )
        ledger = session.scalar(select(SubscriptionEvent))
        assert tenant.status == "active"
        assert tenant.access_version == 9
        assert tenant.row_version == 4
        assert subscription.status == "active"
        assert subscription.row_version == 2
        assert _as_utc(subscription.expires_at) == NOW + timedelta(days=15)
        assert recovery.state == "consumed"
        assert _as_utc(recovery.consumed_at) == NOW
        assert ledger.source_type == "platform_adjustment"
        assert ledger.event_type == "days_adjusted"
        assert ledger.factor_method == "recovery_code"
        assert ledger.platform_actor_id == str(ADMIN_UUID)
        assert ledger.platform_session_id == str(PLATFORM_SESSION_UUID)
        assert len(ledger.request_digest) == 32
        assert ledger.reason_code == "customer_compensation"
        assert ledger.note == "Five service days restored."
        assert ledger.offline_reference == "CASE-2026-001"


def test_expired_add_uses_database_now_and_reactivates_subscription_projection(
    control_database,
):
    factors = _seed(
        control_database,
        tenant_status="expired",
        expires_at=NOW - timedelta(days=20),
    )

    with control_database.transaction() as session:
        result = _adjust(
            _service(),
            session,
            recovery_code=factors.recovery_code,
            adjustment=ServicePeriodAdjustment(add_days=3),
        )

    assert result.before_status == "expired"
    assert result.after_status == "active"
    assert result.calculation_base_at == NOW
    assert result.after_expires_at == NOW + timedelta(days=3)
    with control_database.new_session() as session:
        # D53 does not mutate tenant/access authority.  The effective gate reads
        # subscription expiry and the normal reducer/evaluator owns projection.
        assert session.get(Tenant, str(TENANT_UUID)).status == "expired"
        assert session.get(Subscription, str(SUBSCRIPTION_UUID)).status == "active"


@pytest.mark.parametrize(
    ("adjustment", "expected_expiry", "event_type", "delta"),
    [
        (ServicePeriodAdjustment(subtract_days=2), NOW + timedelta(days=8), "days_adjusted", -2),
        (ServicePeriodAdjustment(expire_now=True), NOW, "expired_now", None),
    ],
)
def test_subtract_and_expire_now_have_distinct_ledger_semantics(
    control_database,
    adjustment,
    expected_expiry,
    event_type,
    delta,
):
    factors = _seed(control_database)
    with control_database.transaction() as session:
        result = _adjust(
            _service(),
            session,
            recovery_code=factors.recovery_code,
            adjustment=adjustment,
        )

    assert result.after_expires_at == expected_expiry
    assert result.signed_delta_days == delta
    with control_database.new_session() as session:
        ledger = session.scalar(select(SubscriptionEvent))
        assert ledger.event_type == event_type
        assert ledger.signed_delta_days == delta
        assert ledger.exact_duration_seconds is None


def test_fully_suspended_adjustment_never_changes_tenant_or_access(control_database):
    factors = _seed(control_database, tenant_status="suspended")

    with control_database.transaction() as session:
        _adjust(_service(), session, recovery_code=factors.recovery_code)

    with control_database.new_session() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        assert tenant.status == "suspended"
        assert tenant.access_version == 9
        assert tenant.row_version == 4
        assert session.scalar(select(func.count()).select_from(SubscriptionEvent)) == 1


@pytest.mark.parametrize(
    "gate",
    [
        SubscriptionAdjustmentGate(False, True, True),
        SubscriptionAdjustmentGate(True, False, True),
        SubscriptionAdjustmentGate(True, True, False),
        SubscriptionAdjustmentGate(True, True, True, "freezing", False),
        None,
    ],
)
def test_incomplete_lifecycle_gate_fails_before_factor(control_database, gate):
    factors = _seed(control_database, tenant_status="suspended")
    service = _service(gate=lambda *_args: gate)

    with control_database.transaction() as session:
        with pytest.raises(SubscriptionAdjustmentGateError):
            _adjust(service, session, recovery_code=factors.recovery_code)

    with control_database.new_session() as session:
        recovery = session.get(PlatformAdminRecoveryCode, str(ACTION_RECOVERY_UUID))
        assert recovery.state == "active"
        assert session.scalar(select(func.count()).select_from(SubscriptionEvent)) == 0


@pytest.mark.parametrize(
    "tenant_status",
    [
        "provisioning",
        "suspending",
        "resuming",
        "deletion_cooling_off",
        "deletion_committing",
        "deleted",
    ],
)
def test_transitional_and_deletion_tenant_states_fail_closed_before_factor(
    control_database,
    tenant_status,
):
    factors = _seed(control_database, tenant_status=tenant_status)

    with control_database.transaction() as session:
        with pytest.raises(SubscriptionAdjustmentGateError):
            _adjust(_service(), session, recovery_code=factors.recovery_code)

    with control_database.new_session() as session:
        assert session.get(
            PlatformAdminRecoveryCode,
            str(ACTION_RECOVERY_UUID),
        ).state == "active"


def test_expired_tenant_rejects_subtract_before_factor_even_if_expiry_is_future(
    control_database,
):
    factors = _seed(control_database, tenant_status="expired")

    with control_database.transaction() as session:
        with pytest.raises(SubscriptionAdjustmentGateError):
            _adjust(
                _service(),
                session,
                recovery_code=factors.recovery_code,
                adjustment=ServicePeriodAdjustment(subtract_days=1),
            )

    with control_database.new_session() as session:
        assert session.get(
            PlatformAdminRecoveryCode,
            str(ACTION_RECOVERY_UUID),
        ).state == "active"


def test_reduction_crossing_database_now_fails_without_consuming_factor(
    control_database,
):
    factors = _seed(control_database, expires_at=NOW + timedelta(days=1))

    with control_database.transaction() as session:
        with pytest.raises(ServicePeriodReductionRejectedError):
            _adjust(
                _service(),
                session,
                recovery_code=factors.recovery_code,
                adjustment=ServicePeriodAdjustment(subtract_days=1),
            )

    with control_database.new_session() as session:
        assert session.get(
            PlatformAdminRecoveryCode,
            str(ACTION_RECOVERY_UUID),
        ).state == "active"
        assert session.get(Subscription, str(SUBSCRIPTION_UUID)).row_version == 1


def test_stale_subscription_revision_fails_before_factor(control_database):
    factors = _seed(control_database)

    with control_database.transaction() as session:
        with pytest.raises(SubscriptionAdjustmentConflictError):
            _adjust(
                _service(),
                session,
                recovery_code=factors.recovery_code,
                expected_revision=2,
            )

    with control_database.new_session() as session:
        assert session.get(
            PlatformAdminRecoveryCode,
            str(ACTION_RECOVERY_UUID),
        ).state == "active"


def test_invalid_platform_session_fails_before_factor(control_database):
    factors = _seed(control_database)
    with control_database.transaction() as session:
        platform_session = session.get(PlatformAdminSession, str(PLATFORM_SESSION_UUID))
        platform_session.revoked_at = NOW - timedelta(seconds=1)
        platform_session.revoked_reason_code = "operator_revoke"

    with control_database.transaction() as session:
        with pytest.raises(SubscriptionAdjustmentAuthenticationError):
            _adjust(_service(), session, recovery_code=factors.recovery_code)

    with control_database.new_session() as session:
        assert session.get(
            PlatformAdminRecoveryCode,
            str(ACTION_RECOVERY_UUID),
        ).state == "active"


def test_wrong_recovery_code_leaves_subscription_and_factor_unchanged(control_database):
    factors = _seed(control_database)

    with control_database.transaction() as session:
        with pytest.raises(SubscriptionAdjustmentAuthenticationError):
            _adjust(
                _service(),
                session,
                recovery_code=factors.recovery_code,
                presented_factor="impr1_wrong-do-not-log",
            )

    with control_database.new_session() as session:
        assert session.get(
            PlatformAdminRecoveryCode,
            str(ACTION_RECOVERY_UUID),
        ).state == "active"
        assert session.get(Subscription, str(SUBSCRIPTION_UUID)).row_version == 1
        assert session.scalar(select(func.count()).select_from(SubscriptionEvent)) == 0


def test_savepoint_restores_factor_when_event_flush_fails_and_outer_commits(
    control_database,
):
    factors = _seed(control_database)

    with control_database.transaction() as session:
        def reject_event_flush(target_session, _flush_context, _instances):
            if any(isinstance(row, SubscriptionEvent) for row in target_session.new):
                raise RuntimeError("forced platform audit/event failure")

        event.listen(session, "before_flush", reject_event_flush)
        try:
            with pytest.raises(RuntimeError, match="forced platform"):
                _adjust(_service(), session, recovery_code=factors.recovery_code)
        finally:
            event.remove(session, "before_flush", reject_event_flush)
        # Exiting the context commits the still-usable outer transaction.  The
        # D53 SAVEPOINT must nevertheless have restored all three action writes.

    with control_database.new_session() as session:
        recovery = session.get(PlatformAdminRecoveryCode, str(ACTION_RECOVERY_UUID))
        subscription = session.get(Subscription, str(SUBSCRIPTION_UUID))
        assert recovery.state == "active"
        assert recovery.row_version == 1
        assert subscription.row_version == 1
        assert _as_utc(subscription.expires_at) == NOW + timedelta(days=10)
        assert session.scalar(select(func.count()).select_from(SubscriptionEvent)) == 0


def test_later_caller_audit_failure_rolls_back_the_whole_outer_transaction(
    control_database,
):
    factors = _seed(control_database)

    with pytest.raises(RuntimeError, match="audit unavailable"):
        with control_database.transaction() as session:
            _adjust(_service(), session, recovery_code=factors.recovery_code)
            # The service intentionally leaves platform audit to its caller.
            raise RuntimeError("platform audit unavailable")

    with control_database.new_session() as session:
        recovery = session.get(PlatformAdminRecoveryCode, str(ACTION_RECOVERY_UUID))
        subscription = session.get(Subscription, str(SUBSCRIPTION_UUID))
        assert recovery.state == "active"
        assert recovery.row_version == 1
        assert subscription.row_version == 1
        assert _as_utc(subscription.expires_at) == NOW + timedelta(days=10)
        assert session.scalar(select(func.count()).select_from(SubscriptionEvent)) == 0


def test_success_retry_returns_original_without_clock_gate_or_factor(control_database):
    factors = _seed(control_database)
    with control_database.transaction() as session:
        first = _adjust(_service(), session, recovery_code=factors.recovery_code)

    def forbidden(*_args):
        raise AssertionError("idempotent retry reached a new-action dependency")

    retry_service = _service(gate=forbidden, clock=forbidden)
    with control_database.transaction() as session:
        retry = _adjust(
            retry_service,
            session,
            recovery_code=factors.recovery_code,
        )

    assert retry.created is False
    assert retry.event_uuid == first.event_uuid
    assert retry.database_effective_at == first.database_effective_at
    assert retry.before_expires_at == first.before_expires_at
    assert retry.after_expires_at == first.after_expires_at
    with control_database.new_session() as session:
        assert session.scalar(select(func.count()).select_from(SubscriptionEvent)) == 1
        assert session.get(Subscription, str(SUBSCRIPTION_UUID)).row_version == 2


def test_idempotency_payload_change_conflicts_before_factor(control_database):
    factors = _seed(control_database)
    with control_database.transaction() as session:
        _adjust(_service(), session, recovery_code=factors.recovery_code)

    with control_database.transaction() as session:
        with pytest.raises(SubscriptionAdjustmentConflictError):
            _adjust(
                _service(),
                session,
                recovery_code="unused-value",
                note="Changed note must not replay.",
            )

    with control_database.new_session() as session:
        assert session.scalar(select(func.count()).select_from(SubscriptionEvent)) == 1
        assert session.get(Subscription, str(SUBSCRIPTION_UUID)).row_version == 2


def test_fresh_totp_succeeds_once_and_same_step_cannot_authorize_second_action(
    control_database,
):
    factors = _seed(control_database)
    current_step = totp_time_step(int(NOW.timestamp()))
    code = generate_totp_code(TOTP_SEED, current_step)
    service = _service()

    with control_database.transaction() as session:
        first = _adjust(
            service,
            session,
            recovery_code=factors.recovery_code,
            factor_method="totp",
            presented_factor=code,
            root_key=ROOT_KEY,
        )
    assert first.created is True

    with control_database.transaction() as session:
        with pytest.raises(SubscriptionAdjustmentAuthenticationError):
            _adjust(
                service,
                session,
                recovery_code=factors.recovery_code,
                action_uuid=SECOND_ACTION_UUID,
                idempotency_key="d53:action-2",
                expected_revision=2,
                factor_method="totp",
                presented_factor=code,
                root_key=ROOT_KEY,
            )

    with control_database.new_session() as session:
        credential = session.get(PlatformAdminTotpCredential, str(TOTP_UUID))
        assert credential.last_accepted_time_step == current_step
        assert credential.row_version == 2
        assert session.get(Subscription, str(SUBSCRIPTION_UUID)).row_version == 2
        assert session.scalar(select(func.count()).select_from(SubscriptionEvent)) == 1


def test_consumed_recovery_code_cannot_authorize_a_different_action(control_database):
    factors = _seed(control_database)
    service = _service()
    with control_database.transaction() as session:
        _adjust(service, session, recovery_code=factors.recovery_code)

    with control_database.transaction() as session:
        with pytest.raises(SubscriptionAdjustmentAuthenticationError):
            _adjust(
                service,
                session,
                recovery_code=factors.recovery_code,
                action_uuid=SECOND_ACTION_UUID,
                idempotency_key="d53:action-2",
                expected_revision=2,
            )

    with control_database.new_session() as session:
        recovery = session.get(PlatformAdminRecoveryCode, str(ACTION_RECOVERY_UUID))
        assert recovery.state == "consumed"
        assert recovery.row_version == 2
        assert session.get(Subscription, str(SUBSCRIPTION_UUID)).row_version == 2
        assert session.scalar(select(func.count()).select_from(SubscriptionEvent)) == 1


def test_caller_must_start_with_a_clean_explicit_transaction(control_database):
    factors = _seed(control_database)
    service = _service()

    with control_database.new_session() as session:
        with pytest.raises(SubscriptionAdjustmentTransactionError):
            _adjust(service, session, recovery_code=factors.recovery_code)

    with control_database.transaction() as session:
        session.add(Tenant(status="provisioning"))
        with pytest.raises(SubscriptionAdjustmentTransactionError):
            _adjust(service, session, recovery_code=factors.recovery_code)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reason_code", ""),
        ("reason_code", "r" * 65),
        ("reason_code", "unsafe\nreason"),
        ("note", "n" * 501),
        ("offline_reference", "contains whitespace"),
        ("offline_reference", "r" * 129),
    ],
)
def test_bounded_event_text_is_rejected_before_factor(
    control_database,
    field,
    value,
):
    factors = _seed(control_database)
    kwargs = {field: value}

    with control_database.transaction() as session:
        with pytest.raises(ValueError):
            _adjust(
                _service(),
                session,
                recovery_code=factors.recovery_code,
                **kwargs,
            )

    with control_database.new_session() as session:
        assert session.get(
            PlatformAdminRecoveryCode,
            str(ACTION_RECOVERY_UUID),
        ).state == "active"


def test_api_has_no_target_timestamp_input(control_database):
    factors = _seed(control_database)
    with control_database.transaction() as session:
        with pytest.raises(TypeError, match="expires_at"):
            _adjust(
                _service(),
                session,
                recovery_code=factors.recovery_code,
                expires_at=NOW + timedelta(days=999),
            )
