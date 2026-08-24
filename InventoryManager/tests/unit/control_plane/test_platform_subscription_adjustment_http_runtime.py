from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa
from flask import Flask

from app.routes.platform_identity_api import bp as identity_bp
from app.routes.platform_subscription_adjustment_api import bp as adjustment_bp
from app.routes.platform_redemption_api import bp as redemption_bp
from app.services.platform_identity import (
    PlatformLoginRuntimeSettings,
    SqlAlchemyPlatformIdentityHttpRuntime,
    install_platform_identity_http_runtime,
)
from app.services.platform_subscription_adjustment import (
    SqlAlchemyPlatformSubscriptionAdjustmentHttpRuntime,
    install_platform_subscription_adjustment_http_runtime,
)
from app.services.platform_redemption import (
    PlatformRedemptionRuntimeSettings,
    SqlAlchemyPlatformRedemptionHttpRuntime,
    install_platform_redemption_http_runtime,
)
from inventory_control import ControlBase, ControlDatabase
from inventory_control.crypto import RootKey
from inventory_control.models import (
    DisasterRecoveryRun,
    PlanRevision,
    PlatformAdmin,
    PlatformAdminRateLimitCounter,
    PlatformAdminRecoveryCode,
    PlatformAdminTotpCredential,
    PlatformAuditLog,
    PlatformRootKeyVersion,
    Subscription,
    SubscriptionEvent,
    Tenant,
    TenantRecoveryHold,
)
from inventory_control.platform_http import PLATFORM_CSRF_HEADER_NAME
from inventory_control.platform_identity import (
    PlatformLoginPolicy,
    PlatformPasswordHasher,
    PlatformRateLimitPolicy,
    PlatformRateLimitRule,
    encrypt_totp_seed,
    issue_recovery_code,
)
from inventory_control.sms import TrustedSourceBucket
from inventory_control.subscriptions import parse_core_entitlements


ROOT_KEY = RootKey(version=1, material=bytes(range(32)))
PASSWORD = "correct horse battery staple"
TENANT_ID = UUID("d1000000-0000-4000-8000-000000000001")
RUN_ID = UUID("d1000000-0000-4000-8000-000000000002")
HOLD_ID = UUID("d1000000-0000-4000-8000-000000000003")
DATABASE_ID = UUID("d1000000-0000-4000-8000-000000000004")
PLAN_ID = UUID("d1000000-0000-4000-8000-000000000005")
SUBSCRIPTION_ID = UUID("d1000000-0000-4000-8000-000000000006")
ADMIN_ID = UUID("d1000000-0000-4000-8000-000000000007")
TOTP_ID = UUID("d1000000-0000-4000-8000-000000000008")
TOTP_SEED = b"12345678901234567890"


@pytest.fixture
def harness(tmp_path, mysql_control_database):
    database = mysql_control_database
    root_directory = tmp_path / "root-keys"
    root_directory.mkdir()
    key_file = root_directory / "v1"
    key_file.write_bytes(base64.b64encode(bytes(range(32))) + b"\n")
    key_file.chmod(0o400)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    entitlements = {
        "features": {"xianyu_sync": True},
        "limits": {"member_seats": 10},
    }
    snapshot = parse_core_entitlements(
        schema_version=1,
        entitlements=entitlements,
    )
    login_code = issue_recovery_code()
    action_code = issue_recovery_code()
    spare_code = issue_recovery_code()
    envelope = encrypt_totp_seed(
        root_key=ROOT_KEY,
        credential_id=str(TOTP_ID),
        platform_admin_id=str(ADMIN_ID),
        secret_revision=1,
        seed=TOTP_SEED,
    )
    password = PlatformPasswordHasher().hash(PASSWORD)
    with database.transaction() as session:
        session.add_all(
            [
                PlatformRootKeyVersion(
                    version=1,
                    fingerprint_sha256=bytes.fromhex(
                        ROOT_KEY.fingerprint_sha256
                    ),
                    status="active",
                    activated_at=now - timedelta(days=1),
                ),
                PlatformAdmin(
                    id=str(ADMIN_ID),
                    username_canonical="root.admin",
                    status="active",
                    password_hash_encoded=password.encoded,
                    password_hash_algorithm=password.algorithm,
                    password_hash_version=password.version,
                    auth_version=3,
                    setup_version=2,
                    totp_generation=1,
                    recovery_code_generation=1,
                    row_version=1,
                    created_at=now - timedelta(days=2),
                    updated_at=now - timedelta(days=1),
                ),
                Tenant(
                    id=str(TENANT_ID),
                    status="active",
                    access_version=7,
                    row_version=4,
                ),
                DisasterRecoveryRun(
                    id=str(RUN_ID),
                    kind="initial_baseline",
                    policy_version=1,
                    status="completed",
                    expected_survivor_count=1,
                    actual_survivor_count=1,
                    sealed_coverage_digest=b"s" * 32,
                    final_coverage_digest=b"f" * 32,
                    host_installation_fingerprint="a" * 64,
                    deployment_marker_fingerprint="b" * 64,
                    row_version=2,
                    started_at=now - timedelta(days=2),
                    reviewing_at=now - timedelta(days=1),
                    completed_at=now - timedelta(days=1),
                    created_at=now - timedelta(days=2),
                    updated_at=now - timedelta(days=1),
                ),
                PlanRevision(
                    id=str(PLAN_ID),
                    code="core",
                    revision=1,
                    name="Core",
                    entitlements_schema_version=1,
                    entitlements_json=entitlements,
                    entitlements_digest=snapshot.digest_sha256,
                    active=True,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                PlatformAdminTotpCredential(
                    id=str(TOTP_ID),
                    platform_admin_id=str(ADMIN_ID),
                    generation=1,
                    secret_revision=1,
                    status="confirmed",
                    seed_nonce=envelope.nonce,
                    seed_ciphertext=envelope.ciphertext,
                    root_key_version=1,
                    crypto_version=1,
                    aad_version=1,
                    totp_algorithm="SHA1",
                    totp_digits=6,
                    totp_period_seconds=30,
                    row_version=1,
                    created_at=now - timedelta(days=1),
                    confirmed_at=now - timedelta(days=1),
                ),
                *[
                    PlatformAdminRecoveryCode(
                        platform_admin_id=str(ADMIN_ID),
                        generation=1,
                        ordinal=ordinal,
                        token_digest_sha256=code.digest_sha256,
                        state="active",
                        row_version=1,
                        created_at=now - timedelta(days=1),
                    )
                    for ordinal, code in enumerate(
                        (login_code, action_code, spare_code), start=1
                    )
                ],
                TenantRecoveryHold(
                    id=str(HOLD_ID),
                    recovery_run_id=str(RUN_ID),
                    tenant_id=str(TENANT_ID),
                    database_uuid=str(DATABASE_ID),
                    state="released",
                    hold_revision=3,
                    snapshot_underlying_status="active",
                    snapshot_access_version=7,
                    expected_dml_login_state_version=1,
                    dml_convergence_status="active",
                    held_at=now - timedelta(days=1),
                    released_at=now - timedelta(days=1),
                    row_version=2,
                    created_at=now - timedelta(days=1),
                    updated_at=now - timedelta(days=1),
                ),
                Subscription(
                    id=str(SUBSCRIPTION_ID),
                    tenant_id=str(TENANT_ID),
                    plan_revision_uuid=str(PLAN_ID),
                    entitlements_schema_version=1,
                    entitlements_json=entitlements,
                    entitlements_digest=snapshot.digest_sha256,
                    status="active",
                    expires_at=now + timedelta(days=10),
                    row_version=5,
                    provider="manual",
                ),
            ]
        )

    settings = _settings()
    identity = SqlAlchemyPlatformIdentityHttpRuntime(
        control_database=database,
        root_key_directory=str(root_directory),
        login_settings=settings,
    )
    adjustment = SqlAlchemyPlatformSubscriptionAdjustmentHttpRuntime(
        control_database=database,
        platform_boundary=identity.boundary,
        root_key_directory=str(root_directory),
        login_settings=settings,
    )
    redemption = SqlAlchemyPlatformRedemptionHttpRuntime(
        control_database=database,
        platform_boundary=identity.boundary,
        root_key_directory=str(root_directory),
        login_settings=settings,
        runtime_settings=_redemption_settings(),
    )
    app = Flask(__name__)
    app.config.update(TESTING=True)
    app.register_blueprint(identity_bp)
    app.register_blueprint(adjustment_bp)
    app.register_blueprint(redemption_bp)
    install_platform_identity_http_runtime(app, runtime=identity)
    install_platform_subscription_adjustment_http_runtime(
        app,
        runtime=adjustment,
    )
    install_platform_redemption_http_runtime(app, runtime=redemption)
    client = app.test_client()
    response = client.post(
        "/platform/api/login",
        base_url="https://localhost",
        json={
            "username": "root.admin",
            "password": PASSWORD,
            "factor_method": "recovery_code",
            "factor": login_code.plaintext,
        },
    )
    assert response.status_code == 200
    csrf = response.get_json()["data"]["csrf_token"]
    yield database, client, csrf, action_code.plaintext, spare_code.plaintext


def _settings() -> PlatformLoginRuntimeSettings:
    rules = tuple(
        PlatformRateLimitRule(
            scope=scope,
            subject_type=subject_type,
            window_kind=(
                "device_burst" if subject_type == "device" else "rolling_hour"
            ),
            window_duration=(
                timedelta(minutes=5)
                if subject_type == "device"
                else timedelta(hours=1)
            ),
            max_failures=5,
        )
        for scope in ("password", "mfa")
        for subject_type in ("username", "ip", "device")
    )
    return PlatformLoginRuntimeSettings(
        policy=PlatformLoginPolicy(
            rate_limit=PlatformRateLimitPolicy(
                version=1,
                calendar_timezone="Asia/Shanghai",
                rules=rules,
            ),
            idle_timeout=timedelta(minutes=30),
            absolute_timeout=timedelta(hours=8),
            factor_max_age=timedelta(minutes=5),
            session_policy_version=1,
            allowed_totp_drift_steps=1,
        ),
        trusted_source_resolver=lambda _request: (
            TrustedSourceBucket.from_trusted_ip("203.0.113.9")
        ),
        device_cookie_max_age_seconds=86_400,
        setup_allowed_totp_drift_steps=1,
        recovery_code_count=6,
        recovery_code_ttl=None,
    )


def _redemption_settings(
    *,
    threshold: int = 5,
) -> PlatformRedemptionRuntimeSettings:
    rules = tuple(
        PlatformRateLimitRule(
            scope="code_reveal",
            subject_type=subject_type,
            window_kind=(
                "device_burst" if subject_type == "device" else "rolling_hour"
            ),
            window_duration=(
                timedelta(minutes=5)
                if subject_type == "device"
                else timedelta(hours=1)
            ),
            max_failures=threshold,
        )
        for subject_type in ("username", "ip", "device")
    )
    return PlatformRedemptionRuntimeSettings(
        reveal_rate_limit=PlatformRateLimitPolicy(
            version=1,
            calendar_timezone="Asia/Shanghai",
            rules=rules,
        )
    )


def _payload(**overrides):
    values = {
        "operation": "add_days",
        "days": 3,
        "reason_code": "customer_compensation",
        "note": "Restore three service days.",
        "offline_reference": "CASE-2026-001",
        "idempotency_key": "d53:http:1",
    }
    values.update(overrides)
    return values


def _preview(client, csrf, **overrides):
    return client.post(
        f"/platform/api/tenants/{TENANT_ID}/subscription-adjustments/preview",
        base_url="https://localhost",
        headers={PLATFORM_CSRF_HEADER_NAME: csrf},
        json=_payload(**overrides),
    )


def _commit(client, csrf, preview, factor, **overrides):
    payload = {
        **_payload(),
        "action_id": preview["action_id"],
        "expected_subscription_row_version": preview[
            "expected_subscription_row_version"
        ],
        "confirmation_token": preview["confirmation_token"],
        "factor_method": "recovery_code",
        "factor": factor,
    }
    payload.update(overrides)
    return client.post(
        f"/platform/api/tenants/{TENANT_ID}/subscription-adjustments",
        base_url="https://localhost",
        headers={PLATFORM_CSRF_HEADER_NAME: csrf},
        json=payload,
    )


def test_preview_commit_and_tampered_token_replay_are_atomic(harness):
    database, client, csrf, action_code, _ = harness
    response = _preview(client, csrf)
    assert response.status_code == 200
    preview = response.get_json()["data"]
    assert preview["expected_subscription_row_version"] == 5
    assert response.headers["Cache-Control"] == "private, no-store"

    response = _commit(client, csrf, preview, action_code)
    assert response.status_code == 200
    result = response.get_json()["data"]
    assert result["created"] is True
    assert result["signed_delta_days"] == 3
    assert "does not prove" in result["refund_disclaimer"]

    # A lost response may be retried even when its confirmation is no longer
    # usable; the immutable event identity proves this is not a new action.
    response = _commit(
        client,
        csrf,
        preview,
        "not-used-on-replay",
        confirmation_token=preview["confirmation_token"] + "x",
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["created"] is False

    with database.new_session() as session:
        subscription = session.get(Subscription, str(SUBSCRIPTION_ID))
        events = list(session.scalars(sa.select(SubscriptionEvent)))
        audits = list(
            session.scalars(
                sa.select(PlatformAuditLog).where(
                    PlatformAuditLog.action == "platform.subscription.adjust",
                    PlatformAuditLog.outcome == "succeeded",
                )
            )
        )
        assert subscription.row_version == 6
        assert len(events) == 1
        assert len(audits) == 1
        assert audits[0].target_resource_id == events[0].id


def test_stale_preview_does_not_consume_factor(harness):
    database, client, csrf, action_code, _ = harness
    preview = _preview(client, csrf).get_json()["data"]
    with database.transaction() as session:
        subscription = session.get(Subscription, str(SUBSCRIPTION_ID))
        subscription.row_version += 1

    response = _commit(client, csrf, preview, action_code)
    assert response.status_code == 409
    with database.new_session() as session:
        code = session.scalar(
            sa.select(PlatformAdminRecoveryCode).where(
                PlatformAdminRecoveryCode.token_digest_sha256
                == hashlib.sha256(action_code.encode("ascii")).digest()
            )
        )
        assert code.state == "active"
        assert not list(session.scalars(sa.select(SubscriptionEvent)))


def test_bad_factor_rolls_back_adjustment_and_persists_throttle(harness):
    database, client, csrf, _, _ = harness
    preview = _preview(client, csrf).get_json()["data"]

    response = _commit(client, csrf, preview, "wrong-recovery-code")
    assert response.status_code == 401
    with database.new_session() as session:
        subscription = session.get(Subscription, str(SUBSCRIPTION_ID))
        assert subscription.row_version == 5
        assert not list(session.scalars(sa.select(SubscriptionEvent)))
        assert len(list(session.scalars(sa.select(PlatformAdminRateLimitCounter)))) == 3
        rejected = list(
            session.scalars(
                sa.select(PlatformAuditLog).where(
                    PlatformAuditLog.safe_reason_code
                    == "subscription_adjustment.factor_rejected"
                )
            )
        )
        assert len(rejected) == 1


def test_routes_reject_unknown_target_expiry_and_missing_csrf(harness):
    _, client, csrf, _, _ = harness
    response = _preview(client, csrf, target_expires_at="2030-01-01T00:00:00Z")
    assert response.status_code == 400
    response = client.post(
        f"/platform/api/tenants/{TENANT_ID}/subscription-adjustments/preview",
        base_url="https://localhost",
        json=_payload(),
    )
    assert response.status_code == 403
