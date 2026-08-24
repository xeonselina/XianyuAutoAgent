from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from flask import Flask
import sqlalchemy as sa

from app.routes.tenant_subscription_api import bp as subscription_bp
from app.services.tenant_subscription import (
    TENANT_SUBSCRIPTION_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyTenantSubscriptionHttpRuntime,
)
from inventory_control import ControlBase, ControlDatabase
from inventory_control.domain.rbac import TenantRole
from inventory_control.identity import SessionService
from inventory_control.models import (
    DisasterRecoveryRun,
    PlanRevision,
    PlatformAdmin,
    RedemptionCode,
    RedemptionCodeBatch,
    Subscription,
    SubscriptionEvent,
    Tenant,
    TenantMembership,
    TenantRecoveryHold,
    TenantSuspension,
    User,
)
from inventory_control.recovery import RecoveryAuthorityService
from inventory_control.redemption import canonicalize_redemption_code
from inventory_control.subscriptions import (
    SqlAlchemySubscriptionRenewalGate,
    SubscriptionRenewalService,
    parse_core_entitlements,
)
from inventory_control.tenant_http import (
    TENANT_CSRF_HEADER_NAME,
    TENANT_SESSION_COOKIE_NAME,
    TenantHttpBoundary,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
RUN_ID = "10000000-0000-4000-8000-000000000001"
TENANT_ID = "10000000-0000-4000-8000-000000000002"
DATABASE_ID = "10000000-0000-4000-8000-000000000003"
USER_ID = "10000000-0000-4000-8000-000000000004"
MEMBERSHIP_ID = "10000000-0000-4000-8000-000000000005"
OLD_PLAN_ID = "10000000-0000-4000-8000-000000000006"
NEW_PLAN_ID = "10000000-0000-4000-8000-000000000007"
SUBSCRIPTION_ID = "10000000-0000-4000-8000-000000000008"
PLATFORM_ADMIN_ID = "10000000-0000-4000-8000-000000000009"
BATCH_ID = "10000000-0000-4000-8000-000000000010"
CODE_ID = "10000000-0000-4000-8000-000000000011"
CODE_TEXT = "0123456789ABCDEFGHJKMNPQRS"
OLD_ENTITLEMENTS = {
    "features": {"xianyu_sync": False},
    "limits": {"member_seats": 10},
}
NEW_ENTITLEMENTS = {
    "features": {"xianyu_sync": True},
    "limits": {"member_seats": 10},
}


def _run():
    return DisasterRecoveryRun(
        id=RUN_ID,
        kind="initial_baseline",
        policy_version=1,
        status="completed",
        expected_survivor_count=1,
        actual_survivor_count=1,
        sealed_coverage_digest=b"s" * 32,
        final_coverage_digest=b"f" * 32,
        host_installation_fingerprint="a" * 64,
        deployment_marker_fingerprint="b" * 64,
        row_version=1,
        started_at=NOW,
        reviewing_at=NOW,
        completed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _build_harness(database, *, role: TenantRole = TenantRole.ADMIN):
    old_snapshot = parse_core_entitlements(
        schema_version=1,
        entitlements=OLD_ENTITLEMENTS,
    )
    new_snapshot = parse_core_entitlements(
        schema_version=1,
        entitlements=NEW_ENTITLEMENTS,
    )
    canonical_code = canonicalize_redemption_code(CODE_TEXT)
    with database.transaction() as session:
        session.add_all([
            Tenant(
                id=TENANT_ID,
                status="expired",
                access_version=7,
                row_version=3,
            ),
            _run(),
            User(
                id=USER_ID,
                phone_e164="+8613800138001",
                phone_normalization_version=1,
                phone_metadata_version="test-v1",
                phone_verified_at=NOW,
                status="active",
            ),
            PlanRevision(
                id=OLD_PLAN_ID,
                code="core",
                revision=1,
                name="Core r1",
                entitlements_schema_version=1,
                entitlements_json=OLD_ENTITLEMENTS,
                entitlements_digest=old_snapshot.digest_sha256,
                active=False,
            ),
            PlanRevision(
                id=NEW_PLAN_ID,
                code="core",
                revision=2,
                name="Core r2",
                entitlements_schema_version=1,
                entitlements_json=NEW_ENTITLEMENTS,
                entitlements_digest=new_snapshot.digest_sha256,
                active=False,
            ),
            PlatformAdmin(
                id=PLATFORM_ADMIN_ID,
                username_canonical="platform-admin",
                status="active",
                password_hash_encoded="scrypt$redacted",
                password_hash_algorithm="scrypt",
                password_hash_version=1,
                created_at=NOW,
                updated_at=NOW,
            ),
        ])
        session.flush()
        session.add_all([
            TenantMembership(
                id=MEMBERSHIP_ID,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                role_key=role.value,
                status="active",
                source_type="migration",
                row_version=2,
            ),
            TenantRecoveryHold(
                recovery_run_id=RUN_ID,
                tenant_id=TENANT_ID,
                database_uuid=DATABASE_ID,
                state="released",
                hold_revision=1,
                snapshot_underlying_status="expired",
                snapshot_access_version=7,
                expected_dml_login_state_version=1,
                dml_convergence_status="active",
                held_at=NOW,
                released_at=NOW,
                row_version=1,
                created_at=NOW,
                updated_at=NOW,
            ),
            Subscription(
                id=SUBSCRIPTION_ID,
                tenant_id=TENANT_ID,
                plan_revision_uuid=OLD_PLAN_ID,
                entitlements_schema_version=1,
                entitlements_json=OLD_ENTITLEMENTS,
                entitlements_digest=old_snapshot.digest_sha256,
                status="expired",
                expires_at=NOW - timedelta(days=1),
                row_version=4,
                provider="manual",
            ),
        ])
        session.flush()
        session.add(
            RedemptionCodeBatch(
                id=BATCH_ID,
                generation_request_uuid=(
                    "10000000-0000-4000-8000-000000000012"
                ),
                request_digest=b"b" * 32,
                name="test batch",
                quantity=1,
                plan_revision_uuid=NEW_PLAN_ID,
                entitlements_schema_version=1,
                entitlements_json=NEW_ENTITLEMENTS,
                entitlements_digest=new_snapshot.digest_sha256,
                service_duration_seconds=30 * 24 * 60 * 60,
                default_redeem_before=NOW + timedelta(days=20),
                created_by_platform_admin_id=PLATFORM_ADMIN_ID,
                created_at=NOW - timedelta(days=1),
                plaintext_exported_at=NOW - timedelta(days=1),
            )
        )
        session.flush()
        session.add(
            RedemptionCode(
                id=CODE_ID,
                crypto_context_uuid=(
                    "10000000-0000-4000-8000-000000000013"
                ),
                batch_id=BATCH_ID,
                code_prefix=CODE_TEXT[:4],
                lookup_hash=canonical_code.lookup_hash,
                code_ciphertext=b"x" * 42,
                code_nonce=b"n" * 12,
                secret_revision=1,
                root_key_version=1,
                crypto_version=1,
                aad_version=1,
                status="active",
                plan_revision_uuid=NEW_PLAN_ID,
                entitlements_schema_version=1,
                entitlements_json=NEW_ENTITLEMENTS,
                entitlements_digest=new_snapshot.digest_sha256,
                service_duration_seconds=30 * 24 * 60 * 60,
                redeem_before=NOW + timedelta(days=20),
                created_under_recovery_run_uuid=RUN_ID,
                row_version=5,
                created_at=NOW - timedelta(days=1),
                updated_at=NOW - timedelta(days=1),
            )
        )

    authority = RecoveryAuthorityService(database_clock=lambda _session: NOW)
    sessions = SessionService(gate_current_read=authority)
    boundary = TenantHttpBoundary(sessions)
    with database.transaction() as session:
        issued = sessions.issue(
            session,
            user_id=USER_ID,
            idle_timeout=timedelta(days=30),
            absolute_timeout=timedelta(days=60),
            now=NOW,
        )
    runtime = SqlAlchemyTenantSubscriptionHttpRuntime(
        control_database=database,
        tenant_http_boundary=boundary,
        renewal_service=SubscriptionRenewalService(
            gate_current_read=SqlAlchemySubscriptionRenewalGate(),
            database_clock=lambda _session: NOW,
        ),
    )
    app = Flask(__name__)
    app.register_blueprint(subscription_bp)
    app.extensions[TENANT_SUBSCRIPTION_HTTP_RUNTIME_EXTENSION] = runtime
    client = app.test_client()
    client.set_cookie(
        TENANT_SESSION_COOKIE_NAME,
        issued.session_token,
        secure=True,
    )
    return app, database, client, issued


def test_expired_operator_reads_minimal_status_but_cannot_redeem(
    mysql_control_database,
) -> None:
    _app, database, client, issued = _build_harness(
        mysql_control_database,
        role=TenantRole.OPERATOR
    )
    try:
        status = client.get("/api/subscription/status")
        denied = client.post(
            "/api/subscription/redeem",
            headers={TENANT_CSRF_HEADER_NAME: issued.csrf_token},
            json={
                "code": CODE_TEXT,
                "idempotency_key": "renew:operator:1",
                "expected_subscription_row_version": 4,
            },
        )

        assert status.status_code == 200
        assert status.get_json()["data"] == {
            "effective_status": "expired",
            "expires_at": "2026-08-21T12:00:00Z",
            "subscription_row_version": 4,
            "can_redeem": False,
        }
        assert denied.status_code == 403
        with database.new_session() as session:
            assert session.get(RedemptionCode, CODE_ID).status == "active"
    finally:
        database.dispose()


def test_expired_admin_redeems_atomically_and_replays_same_result(
    mysql_control_database,
) -> None:
    _app, database, client, issued = _build_harness(mysql_control_database)
    payload = {
        "code": CODE_TEXT,
        "idempotency_key": "renew:admin:1",
        "expected_subscription_row_version": 4,
    }
    try:
        no_csrf = client.post("/api/subscription/redeem", json=payload)
        first = client.post(
            "/api/subscription/redeem",
            headers={TENANT_CSRF_HEADER_NAME: issued.csrf_token},
            json=payload,
        )
        replay = client.post(
            "/api/subscription/redeem",
            headers={TENANT_CSRF_HEADER_NAME: issued.csrf_token},
            json=payload,
        )

        assert no_csrf.status_code == 403
        assert first.status_code == replay.status_code == 200
        assert first.get_json()["data"] == {
            "effective_status": "active",
            "expires_at": "2026-09-21T12:00:00Z",
            "subscription_row_version": 5,
            "idempotent_replay": False,
        }
        assert replay.get_json()["data"]["idempotent_replay"] is True
        with database.new_session() as session:
            assert session.get(RedemptionCode, CODE_ID).status == "redeemed"
            assert session.get(Tenant, TENANT_ID).status == "active"
            subscription = session.get(Subscription, SUBSCRIPTION_ID)
            assert subscription.row_version == 5
            assert subscription.expires_at == datetime(
                2026, 9, 21, 12, 0
            )
            events = session.scalars(sa.select(SubscriptionEvent)).all()
            assert len(events) == 1
            assert events[0].consumed_code_uuid == CODE_ID
    finally:
        database.dispose()


def test_session_precheck_rejects_existing_suspension(
    mysql_control_database,
) -> None:
    _app, database, client, issued = _build_harness(mysql_control_database)
    with database.transaction() as session:
        session.add(
            TenantSuspension(
                tenant_id=TENANT_ID,
                state="active",
                initial_reason_code="security_review",
                barrier_generation=1,
                committed_tenant_row_version=3,
                committed_access_version=7,
                requested_at=NOW,
                frozen_at=NOW,
                row_version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    try:
        response = client.post(
            "/api/subscription/redeem",
            headers={TENANT_CSRF_HEADER_NAME: issued.csrf_token},
            json={
                "code": CODE_TEXT,
                "idempotency_key": "renew:admin:race",
                "expected_subscription_row_version": 4,
            },
        )

        assert response.status_code == 403
        assert response.get_json()["data"]["code"] == (
            "TENANT_CAPABILITY_DENIED"
        )
        with database.new_session() as session:
            assert session.get(RedemptionCode, CODE_ID).status == "active"
            assert session.get(Subscription, SUBSCRIPTION_ID).row_version == 4
            assert session.scalar(
                sa.select(sa.func.count(SubscriptionEvent.id))
            ) == 0
    finally:
        database.dispose()


def test_malformed_and_unknown_codes_have_one_public_rejection(
    mysql_control_database,
) -> None:
    _app, database, client, issued = _build_harness(mysql_control_database)
    headers = {TENANT_CSRF_HEADER_NAME: issued.csrf_token}
    try:
        malformed = client.post(
            "/api/subscription/redeem",
            headers=headers,
            json={
                "code": "not-a-code",
                "idempotency_key": "renew:malformed:1",
                "expected_subscription_row_version": 4,
            },
        )
        unknown = client.post(
            "/api/subscription/redeem",
            headers=headers,
            json={
                "code": "1123456789ABCDEFGHJKMNPQRS",
                "idempotency_key": "renew:unknown:1",
                "expected_subscription_row_version": 4,
            },
        )

        assert malformed.status_code == unknown.status_code == 422
        assert malformed.get_json() == unknown.get_json()
        with database.new_session() as session:
            assert session.get(RedemptionCode, CODE_ID).status == "active"
    finally:
        database.dispose()


def test_missing_runtime_is_fixed_503_and_no_store() -> None:
    app = Flask(__name__)
    app.register_blueprint(subscription_bp)

    response = app.test_client().get("/api/subscription/status")

    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.get_json() == {
        "success": False,
        "message": "租户订阅服务尚未就绪",
    }
