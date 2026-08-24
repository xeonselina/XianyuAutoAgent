from __future__ import annotations

from datetime import datetime, timedelta, timezone
import base64
from uuid import uuid4

import pytest
from flask import Flask
import sqlalchemy as sa

from app.routes.tenant_identity_api import bp as tenant_identity_api_bp
from app.services.tenant_identity import (
    TENANT_IDENTITY_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyTenantIdentityHttpRuntime,
)
from inventory_control import (
    ControlBase,
    ControlDatabase,
    SmsChallenge,
    Tenant,
    TenantAuthSecurityEvent,
    TenantMembership,
    TenantUserSession,
    User,
    PlatformRootKeyVersion,
)
from inventory_control.models import MemberSeatGuard
from inventory_control.crypto import RootKey
from inventory_control.database import read_database_utc_value
from inventory_control.domain import (
    EffectiveTenantGate,
    TenantGateDecision,
)
from inventory_control.identity import (
    CN_MOBILE_METADATA_VERSION,
    PHONE_NORMALIZATION_VERSION,
    SessionService,
    TenantBrowserSessionPolicy,
)
from inventory_control.sms import (
    SmsDeliveryOutcome,
    SmsPolicy,
    TrustedSourceBucket,
)
from inventory_control.tenant_http import (
    TENANT_CSRF_HEADER_NAME,
    TENANT_SESSION_COOKIE_NAME,
    TenantHttpBoundary,
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _gate_from_tenant(_session, tenant, _now) -> TenantGateDecision:
    gate = {
        "active": EffectiveTenantGate.ACTIVE,
        "expired": EffectiveTenantGate.EXPIRED,
        "suspended": EffectiveTenantGate.SUSPENDED,
    }.get(tenant.status, EffectiveTenantGate.RECOVERY_HOLD)
    return TenantGateDecision(
        gate=gate,
        error_code=None if gate is EffectiveTenantGate.ACTIVE else gate.value,
    )


@pytest.fixture
def identity_harness(mysql_control_database):
    database = mysql_control_database
    service = SessionService(gate_current_read=_gate_from_tenant)
    boundary = TenantHttpBoundary(service)
    runtime = SqlAlchemyTenantIdentityHttpRuntime(
        control_database=database,
        tenant_http_boundary=boundary,
        session_service=service,
    )
    app = Flask(__name__)
    app.register_blueprint(tenant_identity_api_bp)
    app.extensions[TENANT_IDENTITY_HTTP_RUNTIME_EXTENSION] = runtime

    with database.transaction() as session:
        now = _as_utc(read_database_utc_value(session))
        tenant = Tenant(status="active", access_version=4)
        user = User(
            phone_e164="+8613800138001",
            phone_normalization_version=PHONE_NORMALIZATION_VERSION,
            phone_metadata_version=CN_MOBILE_METADATA_VERSION,
            phone_verified_at=now,
            status="active",
        )
        session.add_all([tenant, user])
        session.flush()
        session.add(MemberSeatGuard(tenant_id=tenant.id))
        membership = TenantMembership(
            tenant_id=tenant.id,
            user_id=user.id,
            role_key="admin",
            status="active",
            source_type="migration",
        )
        session.add(membership)
        session.flush()
        issued = service.issue(
            session,
            user_id=user.id,
            idle_timeout=timedelta(minutes=30),
            absolute_timeout=timedelta(hours=8),
            now=now,
        )

    yield app, database, issued


def _authenticated_client(app: Flask, issued):
    client = app.test_client()
    client.set_cookie(
        TENANT_SESSION_COOKIE_NAME,
        issued.session_token,
        secure=True,
    )
    return client


class _RecordingSmsProvider:
    def __init__(self) -> None:
        self.codes: list[str] = []
        self.phones: list[str] = []

    def send_verification(self, request):
        self.phones.append(request.canonical_phone_e164)
        self.codes.append(request.take_plaintext_code())
        return SmsDeliveryOutcome.SENT


@pytest.fixture
def login_harness(tmp_path, mysql_control_database):
    database = mysql_control_database
    service = SessionService(gate_current_read=_gate_from_tenant)
    boundary = TenantHttpBoundary(service)
    provider = _RecordingSmsProvider()
    root_key = RootKey(version=9, material=bytes(range(32)))
    key_file = tmp_path / "v9"
    key_file.write_bytes(
        base64.b64encode(root_key._material_bytes()) + b"\n"
    )
    key_file.chmod(0o400)

    with database.transaction() as session:
        now = _as_utc(read_database_utc_value(session))
        session.add(
            PlatformRootKeyVersion(
                version=root_key.version,
                fingerprint_sha256=bytes.fromhex(
                    root_key.fingerprint_sha256
                ),
                status="active",
                activated_at=now,
            )
        )
        tenant = Tenant(status="active", access_version=3)
        user = User(
            phone_e164="+8613800138001",
            phone_normalization_version=PHONE_NORMALIZATION_VERSION,
            phone_metadata_version=CN_MOBILE_METADATA_VERSION,
            phone_verified_at=None,
            status="unverified",
        )
        session.add_all([tenant, user])
        session.flush()
        session.add(
            TenantMembership(
                tenant_id=tenant.id,
                user_id=user.id,
                role_key="admin",
                status="active",
                source_type="migration",
            )
        )
        session.flush()
        user_id = user.id

    runtime = SqlAlchemyTenantIdentityHttpRuntime(
        control_database=database,
        tenant_http_boundary=boundary,
        session_service=service,
        root_key_directory=tmp_path,
        sms_provider=provider,
        sms_policy=SmsPolicy(),
        session_policy=TenantBrowserSessionPolicy(
            version=2,
            idle_timeout=timedelta(minutes=45),
            absolute_timeout=timedelta(hours=12),
        ),
        trusted_source_resolver=lambda _request: (
            TrustedSourceBucket.unknown()
        ),
    )
    app = Flask(__name__)
    app.register_blueprint(tenant_identity_api_bp)
    app.extensions[TENANT_IDENTITY_HTTP_RUNTIME_EXTENSION] = runtime
    yield app, database, provider, user_id


@pytest.fixture
def phone_change_harness(tmp_path, mysql_control_database):
    database = mysql_control_database
    service = SessionService(gate_current_read=_gate_from_tenant)
    boundary = TenantHttpBoundary(service)
    provider = _RecordingSmsProvider()
    root_key = RootKey(version=10, material=b"q" * 32)
    key_file = tmp_path / "v10"
    key_file.write_bytes(
        base64.b64encode(root_key._material_bytes()) + b"\n"
    )
    key_file.chmod(0o400)

    with database.transaction() as session:
        now = _as_utc(read_database_utc_value(session))
        session.add(
            PlatformRootKeyVersion(
                version=root_key.version,
                fingerprint_sha256=bytes.fromhex(
                    root_key.fingerprint_sha256
                ),
                status="active",
                activated_at=now,
            )
        )
        tenant = Tenant(status="active", access_version=2)
        user = User(
            phone_e164="+8613800138001",
            phone_normalization_version=PHONE_NORMALIZATION_VERSION,
            phone_metadata_version=CN_MOBILE_METADATA_VERSION,
            phone_verified_at=now,
            status="active",
        )
        session.add_all((tenant, user))
        session.flush()
        session.add_all(
            (
                MemberSeatGuard(tenant_id=tenant.id),
                TenantMembership(
                    tenant_id=tenant.id,
                    user_id=user.id,
                    role_key="admin",
                    status="active",
                    source_type="registration",
                ),
            )
        )
        session.flush()
        issued = service.issue(
            session,
            user_id=user.id,
            idle_timeout=timedelta(minutes=30),
            absolute_timeout=timedelta(hours=8),
            now=now,
        )

    runtime = SqlAlchemyTenantIdentityHttpRuntime(
        control_database=database,
        tenant_http_boundary=boundary,
        session_service=service,
        root_key_directory=tmp_path,
        sms_provider=provider,
        sms_policy=SmsPolicy(),
        session_policy=TenantBrowserSessionPolicy(
            version=2,
            idle_timeout=timedelta(minutes=45),
            absolute_timeout=timedelta(hours=12),
        ),
        trusted_source_resolver=lambda _request: (
            TrustedSourceBucket.unknown()
        ),
    )
    app = Flask(__name__)
    app.register_blueprint(tenant_identity_api_bp)
    app.extensions[TENANT_IDENTITY_HTTP_RUNTIME_EXTENSION] = runtime
    yield app, database, provider, issued


def _issue_another_session(
    database: ControlDatabase,
    runtime: SqlAlchemyTenantIdentityHttpRuntime,
    *,
    user_id: str,
    device_name: str,
):
    with database.transaction() as session:
        now = _as_utc(read_database_utc_value(session))
        return runtime.session_service.issue(
            session,
            user_id=user_id,
            idle_timeout=timedelta(minutes=30),
            absolute_timeout=timedelta(hours=8),
            device_name=device_name,
            user_agent_summary="browser-family",
            ip_summary="masked-source",
            now=now,
        )


def test_session_status_reads_current_control_identity(identity_harness) -> None:
    app, _database, issued = identity_harness
    client = _authenticated_client(app, issued)

    response = client.get("/api/auth/session")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.get_json() == {
        "success": True,
        "data": {
            "authenticated": True,
            "session_id": issued.auth.session_id,
            "tenant_id": issued.auth.tenant_id,
            "role": "admin",
            "effective_gate": "active",
            "tenant_timezone": "Asia/Shanghai",
        },
    }


def test_logout_requires_csrf_then_revokes_current_session(
    identity_harness,
) -> None:
    app, database, issued = identity_harness
    client = _authenticated_client(app, issued)

    denied = client.post("/api/auth/logout")

    assert denied.status_code == 403
    assert denied.get_json()["data"]["code"] == "CSRF_INVALID"
    with database.new_session() as session:
        assert session.get(
            TenantUserSession, issued.auth.session_id
        ).revoked_at is None

    response = client.post(
        "/api/auth/logout",
        headers={TENANT_CSRF_HEADER_NAME: issued.csrf_token},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "data": {"logged_out": True, "revoked": True},
    }
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Set-Cookie"].startswith(
        f"{TENANT_SESSION_COOKIE_NAME}=;"
    )
    with database.new_session() as session:
        assert session.get(
            TenantUserSession, issued.auth.session_id
        ).revoked_at is not None
        event = session.scalars(
            sa.select(TenantAuthSecurityEvent)
        ).one()
        assert event.actor_session_id == issued.auth.session_id
        assert event.target_session_id == issued.auth.session_id
        assert event.event_type == "logout_current"
        assert event.reason_code == "user_logout"
    assert client.get("/api/auth/session").status_code == 401


def test_session_list_returns_only_safe_current_user_device_fields(
    identity_harness,
) -> None:
    app, database, issued = identity_harness
    runtime = app.extensions[TENANT_IDENTITY_HTTP_RUNTIME_EXTENSION]
    other = _issue_another_session(
        database,
        runtime,
        user_id=issued.auth.user_id,
        device_name="Office browser",
    )
    client = _authenticated_client(app, issued)

    response = client.get("/api/auth/sessions")

    assert response.status_code == 200
    rows = response.get_json()["data"]["sessions"]
    assert {row["session_id"] for row in rows} == {
        issued.auth.session_id,
        other.auth.session_id,
    }
    assert sum(row["is_current"] for row in rows) == 1
    assert next(
        row for row in rows if row["session_id"] == other.auth.session_id
    )["device_summary"] == "Office browser"
    serialized = response.get_data(as_text=True)
    assert issued.session_token not in serialized
    assert issued.csrf_token not in serialized
    assert "token_digest" not in serialized
    assert "ip_summary" not in serialized


def test_revoke_one_owned_device_is_idempotent_and_keeps_caller_active(
    identity_harness,
) -> None:
    app, database, issued = identity_harness
    runtime = app.extensions[TENANT_IDENTITY_HTTP_RUNTIME_EXTENSION]
    target = _issue_another_session(
        database,
        runtime,
        user_id=issued.auth.user_id,
        device_name="Tablet browser",
    )
    client = _authenticated_client(app, issued)
    headers = {TENANT_CSRF_HEADER_NAME: issued.csrf_token}

    first = client.post(
        f"/api/auth/sessions/{target.auth.session_id}/revoke",
        headers=headers,
    )
    replay = client.post(
        f"/api/auth/sessions/{target.auth.session_id}/revoke",
        headers=headers,
    )

    assert first.status_code == 200
    assert first.get_json()["data"] == {
        "revoked": True,
        "current_session_revoked": False,
    }
    assert replay.status_code == 200
    assert replay.get_json()["data"]["revoked"] is False
    assert client.get("/api/auth/session").status_code == 200
    with database.new_session() as session:
        events = session.scalars(
            sa.select(TenantAuthSecurityEvent)
        ).all()
        assert len(events) == 1
        assert events[0].actor_session_id == issued.auth.session_id
        assert events[0].target_session_id == target.auth.session_id
        assert events[0].event_type == "revoke_target"
        assert events[0].reason_code == "user_revoke_device"


def test_revoke_target_authenticates_before_parsing_and_hides_ownership(
    identity_harness,
) -> None:
    app, database, issued = identity_harness
    runtime = app.extensions[TENANT_IDENTITY_HTTP_RUNTIME_EXTENSION]
    with database.transaction() as session:
        now = _as_utc(read_database_utc_value(session))
        other_user = User(
            phone_e164="+8613900138002",
            phone_normalization_version=PHONE_NORMALIZATION_VERSION,
            phone_metadata_version=CN_MOBILE_METADATA_VERSION,
            phone_verified_at=now,
            status="active",
        )
        session.add(other_user)
        session.flush()
        session.add(
            TenantMembership(
                tenant_id=issued.auth.tenant_id,
                user_id=other_user.id,
                role_key="operator",
                status="active",
                source_type="invitation",
            )
        )
        session.flush()
        foreign = runtime.session_service.issue(
            session,
            user_id=other_user.id,
            idle_timeout=timedelta(minutes=30),
            absolute_timeout=timedelta(hours=8),
            now=now,
        )

    unauthenticated = app.test_client().post(
        "/api/auth/sessions/not-a-uuid/revoke"
    )
    client = _authenticated_client(app, issued)
    headers = {TENANT_CSRF_HEADER_NAME: issued.csrf_token}
    malformed = client.post(
        "/api/auth/sessions/not-a-uuid/revoke",
        headers=headers,
    )
    cross_user = client.post(
        f"/api/auth/sessions/{foreign.auth.session_id}/revoke",
        headers=headers,
    )

    assert unauthenticated.status_code == 401
    assert malformed.status_code == cross_user.status_code == 404
    assert malformed.get_json() == cross_user.get_json()
    with database.new_session() as session:
        assert session.get(
            TenantUserSession, foreign.auth.session_id
        ).revoked_at is None


def test_revoke_all_increments_auth_version_and_clears_all_devices(
    identity_harness,
) -> None:
    app, database, issued = identity_harness
    runtime = app.extensions[TENANT_IDENTITY_HTTP_RUNTIME_EXTENSION]
    another = _issue_another_session(
        database,
        runtime,
        user_id=issued.auth.user_id,
        device_name="Second browser",
    )
    client = _authenticated_client(app, issued)

    response = client.post(
        "/api/auth/sessions/revoke-all",
        headers={TENANT_CSRF_HEADER_NAME: issued.csrf_token},
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "revoked_count": 2,
        "all_sessions_revoked": True,
    }
    assert response.headers["Set-Cookie"].startswith(
        f"{TENANT_SESSION_COOKIE_NAME}=;"
    )
    with database.new_session() as session:
        assert session.get(
            TenantUserSession, issued.auth.session_id
        ).revoked_at is not None
        assert session.get(
            TenantUserSession, another.auth.session_id
        ).revoked_at is not None
        assert session.get(User, issued.auth.user_id).auth_version == 2
        event = session.scalars(
            sa.select(TenantAuthSecurityEvent)
        ).one()
        assert event.actor_session_id == issued.auth.session_id
        assert event.target_session_id is None
        assert event.event_type == "revoke_all"
        assert event.reason_code == "user_revoke_all_devices"


def test_phone_change_dual_code_revokes_session_and_requires_new_login(
    phone_change_harness,
) -> None:
    app, database, provider, issued = phone_change_harness
    client = _authenticated_client(app, issued)
    headers = {TENANT_CSRF_HEADER_NAME: issued.csrf_token}
    action_id = str(uuid4())

    requested = client.post(
        "/api/auth/phone-change/challenges",
        headers=headers,
        json={"action_id": action_id, "new_phone": "13900139000"},
    )

    assert requested.status_code == 202
    challenge = requested.get_json()["data"]
    assert provider.phones == ["+8613800138001", "+8613900139000"]
    rejected = client.post(
        "/api/auth/phone-change/confirm",
        headers=headers,
        json={
            "action_id": action_id,
            "new_phone": "13900139000",
            "old_challenge_id": challenge["old_challenge_id"],
            "old_code": provider.codes[0],
            "new_challenge_id": challenge["new_challenge_id"],
            "new_code": "000000",
        },
    )
    assert rejected.status_code == 403
    assert rejected.get_json()["data"]["code"] == (
        "PHONE_CHANGE_VERIFICATION_REJECTED"
    )
    with database.new_session() as session:
        old_challenge = session.get(
            SmsChallenge, challenge["old_challenge_id"]
        )
        new_challenge = session.get(
            SmsChallenge, challenge["new_challenge_id"]
        )
        assert old_challenge.verification_state == "active"
        assert old_challenge.wrong_attempt_count == 0
        assert new_challenge.wrong_attempt_count == 1
        assert session.get(User, issued.auth.user_id).phone_e164 == (
            "+8613800138001"
        )

    confirmed = client.post(
        "/api/auth/phone-change/confirm",
        headers=headers,
        json={
            "action_id": action_id,
            "new_phone": "13900139000",
            "old_challenge_id": challenge["old_challenge_id"],
            "old_code": provider.codes[0],
            "new_challenge_id": challenge["new_challenge_id"],
            "new_code": provider.codes[1],
        },
    )

    assert confirmed.status_code == 200
    assert confirmed.get_json()["data"]["login_required"] is True
    assert confirmed.headers["Set-Cookie"].startswith(
        f"{TENANT_SESSION_COOKIE_NAME}=;"
    )
    assert client.get("/api/auth/session").status_code == 401
    with database.new_session() as session:
        user = session.get(User, issued.auth.user_id)
        assert user.phone_e164 == "+8613900139000"
        assert user.auth_version == 2
        assert session.get(
            TenantUserSession, issued.auth.session_id
        ).revoked_reason_code == "phone_changed"
        assert session.scalar(
            sa.select(sa.func.count(User.id)).where(
                User.phone_e164 == "+8613800138001"
            )
        ) == 0


def test_phone_change_rejects_an_existing_verified_identity_before_sms(
    phone_change_harness,
) -> None:
    app, database, provider, issued = phone_change_harness
    with database.transaction() as session:
        now = _as_utc(read_database_utc_value(session))
        session.add(
            User(
                phone_e164="+8613900139000",
                phone_normalization_version=PHONE_NORMALIZATION_VERSION,
                phone_metadata_version=CN_MOBILE_METADATA_VERSION,
                phone_verified_at=now,
                status="active",
            )
        )
    client = _authenticated_client(app, issued)

    response = client.post(
        "/api/auth/phone-change/challenges",
        headers={TENANT_CSRF_HEADER_NAME: issued.csrf_token},
        json={"action_id": str(uuid4()), "new_phone": "13900139000"},
    )

    assert response.status_code == 409
    assert response.get_json()["data"]["code"] == "PHONE_CHANGE_CONFLICT"
    assert provider.phones == []


@pytest.mark.parametrize("tenant_status", ["expired", "suspended"])
def test_logout_remains_available_in_restricted_tenant_gates(
    identity_harness,
    tenant_status: str,
) -> None:
    app, database, issued = identity_harness
    with database.transaction() as session:
        session.get(Tenant, issued.auth.tenant_id).status = tenant_status
    client = _authenticated_client(app, issued)

    status = client.get("/api/auth/session")
    response = client.post(
        "/api/auth/logout",
        headers={TENANT_CSRF_HEADER_NAME: issued.csrf_token},
    )

    assert status.status_code == 200
    assert status.get_json()["data"]["effective_gate"] == tenant_status
    assert response.status_code == 200


def test_absent_runtime_fails_closed_without_echoing_cookie() -> None:
    app = Flask(__name__)
    app.register_blueprint(tenant_identity_api_bp)
    client = app.test_client()
    client.set_cookie(
        TENANT_SESSION_COOKIE_NAME,
        "not-a-valid-session-token",
        secure=True,
    )

    response = client.get("/api/auth/session")

    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "not-a-valid-session-token" not in response.get_data(as_text=True)


def test_login_send_and_verify_issues_cookie_csrf_and_activates_migrated_user(
    login_harness,
) -> None:
    app, database, provider, user_id = login_harness
    client = app.test_client()

    sent = client.post(
        "/api/auth/login/challenges",
        json={"phone": "138 0013-8001"},
    )

    assert sent.status_code == 202
    assert sent.headers["Cache-Control"] == "private, no-store"
    challenge_id = sent.get_json()["data"]["challenge_id"]
    assert provider.phones == ["+8613800138001"]
    assert len(provider.codes) == 1

    verified = client.post(
        "/api/auth/login/verify",
        json={
            "phone": "13800138001",
            "challenge_id": challenge_id,
            "code": provider.codes[0],
            "device_name": "Office browser",
        },
    )

    assert verified.status_code == 200
    body = verified.get_json()["data"]
    assert body["role"] == "admin"
    assert body["effective_gate"] == "active"
    assert body["csrf_token"].startswith("imc1_")
    assert "ims1_" not in verified.get_data(as_text=True)
    cookie = verified.headers["Set-Cookie"]
    assert cookie.startswith(f"{TENANT_SESSION_COOKIE_NAME}=ims1_")
    assert "; Secure; HttpOnly; Path=/; SameSite=Lax" in cookie
    assert client.get("/api/auth/session").status_code == 200
    with database.new_session() as session:
        user = session.get(User, user_id)
        row = session.scalar(
            sa.select(TenantUserSession).where(
                TenantUserSession.created_from_challenge_id == challenge_id
            )
        )
        assert user.status == "active"
        assert user.phone_verified_at is not None
        assert row.device_name == "Office browser"
        assert row.policy_version == 2


def test_login_wrong_code_commits_attempt_and_returns_fixed_rejection(
    login_harness,
) -> None:
    app, database, _provider, _user_id = login_harness
    client = app.test_client()
    sent = client.post(
        "/api/auth/login/challenges",
        json={"phone": "13800138001"},
    )
    challenge_id = sent.get_json()["data"]["challenge_id"]

    rejected = client.post(
        "/api/auth/login/verify",
        json={
            "phone": "13800138001",
            "challenge_id": challenge_id,
            "code": "000000",
        },
    )

    assert rejected.status_code == 401
    assert rejected.get_json()["data"]["code"] == "TENANT_LOGIN_REJECTED"
    with database.new_session() as session:
        assert session.get(SmsChallenge, challenge_id).wrong_attempt_count == 1
        assert session.scalar(
            sa.select(sa.func.count(TenantUserSession.id))
        ) == 0


def test_login_send_is_non_enumerating_and_rate_limit_has_retry_after(
    login_harness,
) -> None:
    app, _database, provider, _user_id = login_harness
    client = app.test_client()
    existing = client.post(
        "/api/auth/login/challenges",
        json={"phone": "13800138001"},
    )
    missing = client.post(
        "/api/auth/login/challenges",
        json={"phone": "13900138002"},
    )

    assert existing.status_code == missing.status_code == 202
    assert existing.get_json()["message"] == missing.get_json()["message"]
    assert provider.phones == ["+8613800138001", "+8613900138002"]

    limited = client.post(
        "/api/auth/login/challenges",
        json={"phone": "13800138001"},
    )
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1


def test_login_endpoints_fail_closed_when_provider_policy_is_not_configured(
    identity_harness,
) -> None:
    app, _database, _issued = identity_harness
    response = app.test_client().post(
        "/api/auth/login/challenges",
        json={"phone": "13800138001"},
    )

    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "private, no-store"
