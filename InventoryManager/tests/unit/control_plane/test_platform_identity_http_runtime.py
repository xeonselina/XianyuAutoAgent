from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from flask import Flask

from app.routes.platform_identity_api import bp
from app.services.platform_identity import (
    PlatformLoginRuntimeSettings,
    SqlAlchemyPlatformIdentityHttpRuntime,
    install_platform_identity_http_runtime,
)
from inventory_control import ControlDatabase
from inventory_control.crypto import RootKey
from inventory_control.database import read_database_utc_value
from inventory_control.models import (
    ControlBase,
    PlatformAdminSession,
    PlatformAdmin,
    PlatformAdminRecoveryCode,
    PlatformAdminTotpCredential,
    PlatformAuditLog,
    PlatformRootKeyVersion,
    Tenant,
)
from inventory_control.platform_http import (
    PLATFORM_CSRF_HEADER_NAME,
    PLATFORM_DEVICE_COOKIE_NAME,
    PLATFORM_SESSION_COOKIE_NAME,
    PLATFORM_SETUP_HEADER_NAME,
)
from inventory_control.platform_identity import (
    PlatformAdminSetupService,
    PlatformAdminHostService,
    PlatformLoginPolicy,
    PlatformPasswordHasher,
    PlatformRateLimitPolicy,
    PlatformRateLimitRule,
    PlatformRecoveryCodeService,
    PlatformTotpService,
    activate_admin_if_ready,
    generate_totp_code,
    issue_platform_csrf_token,
    issue_platform_session_token,
    totp_time_step,
)
from inventory_control.sms import TrustedSourceBucket


ROOT_KEY = RootKey(version=7, material=bytes(range(32)))
SEED = b"12345678901234567890"
PASSWORD = "correct horse battery staple"


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


def test_platform_login_session_and_logout_routes_are_independent(
    tmp_path,
    control_database,
):
    root_directory = _install_root_key(tmp_path, control_database)
    login_time, login_step, recovery_codes = _activate_admin(control_database)
    app = Flask(__name__)
    app.config.update(TESTING=True)
    runtime = SqlAlchemyPlatformIdentityHttpRuntime(
        control_database=control_database,
        root_key_directory=root_directory,
        login_settings=_settings(),
    )
    install_platform_identity_http_runtime(app, runtime=runtime)
    app.register_blueprint(bp)
    client = app.test_client()

    response = client.post(
        "/platform/api/login",
        base_url="https://localhost",
        json={
            "username": "root.admin",
            "password": PASSWORD,
            "factor_method": "totp",
            "factor": generate_totp_code(SEED, login_step),
            "device_name": "test browser",
        },
    )
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()["data"]
    csrf = payload["csrf_token"]
    assert payload["role"] == "platform_admin"
    cookie_headers = response.headers.getlist("Set-Cookie")
    assert any(PLATFORM_SESSION_COOKIE_NAME in value for value in cookie_headers)
    assert any(PLATFORM_DEVICE_COOKIE_NAME in value for value in cookie_headers)
    assert all("Domain=" not in value for value in cookie_headers)
    assert response.headers["Cache-Control"] == "private, no-store"

    response = client.get(
        "/platform/api/session", base_url="https://localhost"
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"]["username"] == "root.admin"

    other_bearer = issue_platform_session_token()
    other_csrf = issue_platform_csrf_token()
    with control_database.transaction() as session:
        current = session.scalar(
            sa.select(PlatformAdminSession).where(
                PlatformAdminSession.id == payload["session_id"]
            )
        )
        other = PlatformAdminSession(
            platform_admin_id=current.platform_admin_id,
            token_digest_sha256=other_bearer.digest_sha256,
            csrf_digest_sha256=other_csrf.digest_sha256,
            auth_version_at_issue=current.auth_version_at_issue,
            setup_version_at_issue=current.setup_version_at_issue,
            mfa_method="totp",
            mfa_verified_at=current.mfa_verified_at,
            totp_credential_id=current.totp_credential_id,
            totp_time_step=current.totp_time_step,
            policy_version=current.policy_version,
            csrf_generation=1,
            idle_timeout_seconds=current.idle_timeout_seconds,
            created_at=current.created_at,
            last_seen_at=current.last_seen_at,
            idle_expires_at=current.idle_expires_at,
            absolute_expires_at=current.absolute_expires_at,
            device_name="other browser",
        )
        session.add(other)
        session.flush()
        other_session_id = other.id

    response = client.get(
        "/platform/api/sessions", base_url="https://localhost"
    )
    assert response.status_code == 200, response.get_json()
    listed = response.get_json()["data"]["sessions"]
    assert {row["session_id"] for row in listed} == {
        payload["session_id"],
        other_session_id,
    }
    assert all("token" not in row and "ip" not in row for row in listed)
    response = client.post(
        f"/platform/api/sessions/{other_session_id}/revoke",
        base_url="https://localhost",
        headers={PLATFORM_CSRF_HEADER_NAME: csrf},
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"] == {
        "current_session_revoked": False,
        "revoked": True,
    }
    response = client.post(
        "/platform/api/sessions/not-a-uuid/revoke",
        base_url="https://localhost",
        headers={PLATFORM_CSRF_HEADER_NAME: csrf},
    )
    assert response.status_code == 404

    response = client.post(
        "/platform/api/logout", base_url="https://localhost"
    )
    assert response.status_code == 403
    response = client.post(
        "/platform/api/logout",
        base_url="https://localhost",
        headers={PLATFORM_CSRF_HEADER_NAME: csrf},
    )
    assert response.status_code == 200
    assert response.get_json()["data"] == {"revoked": True}

    response = client.get(
        "/platform/api/session", base_url="https://localhost"
    )
    assert response.status_code == 401

    second_client = app.test_client()
    response = second_client.post(
        "/platform/api/login",
        base_url="https://localhost",
        json={
            "username": "root.admin",
            "password": PASSWORD,
            "factor_method": "recovery_code",
            "factor": recovery_codes[0],
        },
    )
    assert response.status_code == 200, response.get_json()
    second_csrf = response.get_json()["data"]["csrf_token"]
    response = second_client.post(
        "/platform/api/sessions/revoke-all",
        base_url="https://localhost",
        headers={PLATFORM_CSRF_HEADER_NAME: second_csrf},
    )
    assert response.status_code == 200
    assert response.get_json()["data"] == {"revoked_count": 1}
    assert second_client.get(
        "/platform/api/session", base_url="https://localhost"
    ).status_code == 401
    with control_database.new_session() as session:
        assert session.scalar(
            sa.select(sa.func.count(PlatformAdminSession.id))
        ) == 3
        audits = list(
            session.scalars(
                sa.select(PlatformAuditLog).order_by(
                    PlatformAuditLog.created_at,
                    PlatformAuditLog.id,
                )
            )
        )
        assert len(audits) == 5
        assert [row.action for row in audits].count("platform.login") == 2
        assert {
            "platform.session.revoke",
            "platform.session.revoke_all",
            "platform.logout",
        } <= {row.action for row in audits}
        serialized = " ".join(
            str(value)
            for row in audits
            for value in row.__dict__.values()
        )
        assert PASSWORD not in serialized
        assert generate_totp_code(SEED, login_step) not in serialized
        assert all(row.created_at is not None for row in audits)
    assert login_time.tzinfo is not None


def test_rejected_login_sets_only_non_authority_device_cookie(
    tmp_path,
    control_database,
):
    root_directory = _install_root_key(tmp_path, control_database)
    _login_time, login_step, _recovery_codes = _activate_admin(
        control_database
    )
    app = Flask(__name__)
    app.config.update(TESTING=True)
    runtime = SqlAlchemyPlatformIdentityHttpRuntime(
        control_database=control_database,
        root_key_directory=root_directory,
        login_settings=_settings(),
    )
    install_platform_identity_http_runtime(app, runtime=runtime)
    app.register_blueprint(bp)

    response = app.test_client().post(
        "/platform/api/login",
        base_url="https://localhost",
        json={
            "username": "root.admin",
            "password": "this password is incorrect",
            "factor_method": "totp",
            "factor": generate_totp_code(SEED, login_step),
        },
    )
    assert response.status_code == 401
    assert response.get_json()["data"]["code"] == "PLATFORM_CREDENTIAL_INVALID"
    cookie_headers = response.headers.getlist("Set-Cookie")
    assert any(PLATFORM_DEVICE_COOKIE_NAME in value for value in cookie_headers)
    assert all(PLATFORM_SESSION_COOKIE_NAME not in value for value in cookie_headers)


def test_authenticated_step_up_rotates_session_and_consumes_factor_atomically(
    tmp_path,
    control_database,
):
    root_directory = _install_root_key(tmp_path, control_database)
    _login_time, login_step, recovery_codes = _activate_admin(control_database)
    app = Flask(__name__)
    app.config.update(TESTING=True)
    runtime = SqlAlchemyPlatformIdentityHttpRuntime(
        control_database=control_database,
        root_key_directory=root_directory,
        login_settings=_settings(),
    )
    install_platform_identity_http_runtime(app, runtime=runtime)
    app.register_blueprint(bp)
    client = app.test_client()

    response = client.post(
        "/platform/api/login",
        base_url="https://localhost",
        json={
            "username": "root.admin",
            "password": PASSWORD,
            "factor_method": "totp",
            "factor": generate_totp_code(SEED, login_step),
            "device_name": "step-up browser",
        },
    )
    assert response.status_code == 200
    old_payload = response.get_json()["data"]
    with control_database.new_session() as session:
        old_absolute_expiry = session.get(
            PlatformAdminSession, old_payload["session_id"]
        ).absolute_expires_at

    response = client.post(
        "/platform/api/step-up",
        base_url="https://localhost",
        headers={PLATFORM_CSRF_HEADER_NAME: old_payload["csrf_token"]},
        json={
            "factor_method": "recovery_code",
            "factor": recovery_codes[0],
        },
    )
    assert response.status_code == 200, response.get_json()
    replacement = response.get_json()["data"]
    assert replacement["session_id"] != old_payload["session_id"]
    assert replacement["csrf_token"] != old_payload["csrf_token"]
    assert replacement["mfa_method"] == "recovery_code"
    assert client.get(
        "/platform/api/session", base_url="https://localhost"
    ).get_json()["data"]["session_id"] == replacement["session_id"]

    with control_database.new_session() as session:
        old_row = session.get(PlatformAdminSession, old_payload["session_id"])
        new_row = session.get(PlatformAdminSession, replacement["session_id"])
        consumed = session.scalar(
            sa.select(PlatformAdminRecoveryCode).where(
                PlatformAdminRecoveryCode.state == "consumed",
                PlatformAdminRecoveryCode.id == new_row.recovery_code_id,
            )
        )
        audit = session.scalar(
            sa.select(PlatformAuditLog).where(
                PlatformAuditLog.action == "platform.step_up"
            )
        )
        assert old_row.revoked_reason_code == "step_up_rotated"
        assert old_row.revoked_by_session_id == new_row.id
        assert new_row.device_name == "step-up browser"
        assert new_row.absolute_expires_at <= old_absolute_expiry
        assert consumed is not None
        assert audit.outcome == "succeeded"
        assert audit.authentication_factor == "recovery_code"
        serialized = " ".join(str(value) for value in audit.__dict__.values())
        assert recovery_codes[0] not in serialized


def test_rejected_step_up_keeps_current_session_and_records_bounded_failures(
    tmp_path,
    control_database,
):
    root_directory = _install_root_key(tmp_path, control_database)
    _login_time, login_step, _recovery_codes = _activate_admin(control_database)
    app = Flask(__name__)
    app.config.update(TESTING=True)
    runtime = SqlAlchemyPlatformIdentityHttpRuntime(
        control_database=control_database,
        root_key_directory=root_directory,
        login_settings=_settings(),
    )
    install_platform_identity_http_runtime(app, runtime=runtime)
    app.register_blueprint(bp)
    client = app.test_client()
    login = client.post(
        "/platform/api/login",
        base_url="https://localhost",
        json={
            "username": "root.admin",
            "password": PASSWORD,
            "factor_method": "totp",
            "factor": generate_totp_code(SEED, login_step),
        },
    ).get_json()["data"]

    response = client.post(
        "/platform/api/step-up",
        base_url="https://localhost",
        headers={PLATFORM_CSRF_HEADER_NAME: login["csrf_token"]},
        json={"factor_method": "recovery_code", "factor": "impr1_invalid"},
    )
    assert response.status_code == 401
    assert response.get_json()["data"]["code"] == "PLATFORM_FACTOR_INVALID"
    assert client.get(
        "/platform/api/session", base_url="https://localhost"
    ).status_code == 200
    with control_database.new_session() as session:
        assert session.scalar(
            sa.select(sa.func.count(PlatformAdminSession.id))
        ) == 1
        audit = session.scalar(
            sa.select(PlatformAuditLog).where(
                PlatformAuditLog.action == "platform.step_up"
            )
        )
        assert audit.outcome == "rejected"
        assert audit.result_count == 0


def test_logged_in_factor_rotation_is_atomic_and_recovery_codes_are_one_time(
    tmp_path,
    control_database,
):
    root_directory = _install_root_key(tmp_path, control_database)
    _login_time, login_step, recovery_codes = _activate_admin(control_database)
    app = Flask(__name__)
    app.config.update(TESTING=True)
    runtime = SqlAlchemyPlatformIdentityHttpRuntime(
        control_database=control_database,
        root_key_directory=root_directory,
        login_settings=_settings(),
    )
    install_platform_identity_http_runtime(app, runtime=runtime)
    app.register_blueprint(bp)
    client = app.test_client()
    login = client.post(
        "/platform/api/login",
        base_url="https://localhost",
        json={
            "username": "root.admin",
            "password": PASSWORD,
            "factor_method": "totp",
            "factor": generate_totp_code(SEED, login_step),
        },
    ).get_json()["data"]
    headers = {PLATFORM_CSRF_HEADER_NAME: login["csrf_token"]}

    response = client.post(
        "/platform/api/factors/recovery-codes/regenerate",
        base_url="https://localhost",
        headers=headers,
        json={
            "factor_method": "recovery_code",
            "factor": recovery_codes[0],
        },
    )
    assert response.status_code == 200
    regenerated = response.get_json()["data"]
    assert regenerated["recovery_code_generation"] == 2
    assert len(regenerated["recovery_codes"]) == 6
    assert client.get(
        "/platform/api/session", base_url="https://localhost"
    ).status_code == 200

    response = client.post(
        "/platform/api/factors/totp/replacement",
        base_url="https://localhost",
        headers=headers,
        json={
            "factor_method": "recovery_code",
            "factor": regenerated["recovery_codes"][0],
        },
    )
    assert response.status_code == 200
    pending = response.get_json()["data"]
    padded = pending["base32_seed"] + "=" * (
        -len(pending["base32_seed"]) % 8
    )
    replacement_seed = base64.b32decode(padded)

    response = client.post(
        "/platform/api/factors/totp/replacement/complete",
        base_url="https://localhost",
        headers=headers,
        json={
            "credential_id": pending["credential_id"],
            "totp_code": "000000",
        },
    )
    assert response.status_code == 401
    assert client.get(
        "/platform/api/session", base_url="https://localhost"
    ).status_code == 200

    with control_database.new_session() as session:
        replacement_now = read_database_utc_value(session)
    if replacement_now.tzinfo is None:
        replacement_now = replacement_now.replace(tzinfo=timezone.utc)
    replacement_step = totp_time_step(int(replacement_now.timestamp()))
    response = client.post(
        "/platform/api/factors/totp/replacement/complete",
        base_url="https://localhost",
        headers=headers,
        json={
            "credential_id": pending["credential_id"],
            "totp_code": generate_totp_code(
                replacement_seed, replacement_step
            ),
        },
    )
    assert response.status_code == 200
    completed = response.get_json()["data"]
    assert completed["totp_generation"] == 2
    assert completed["recovery_code_generation"] == 3
    assert completed["revoked_session_count"] == 1
    assert len(completed["recovery_codes"]) == 6
    assert any(
        f"{PLATFORM_SESSION_COOKIE_NAME}=;" in value
        for value in response.headers.getlist("Set-Cookie")
    )
    assert client.get(
        "/platform/api/session", base_url="https://localhost"
    ).status_code == 401

    with control_database.new_session() as session:
        credentials = list(
            session.scalars(
                sa.select(PlatformAdminTotpCredential).order_by(
                    PlatformAdminTotpCredential.generation
                )
            )
        )
        sessions = list(session.scalars(sa.select(PlatformAdminSession)))
        audits = list(
            session.scalars(
                sa.select(PlatformAuditLog).where(
                    PlatformAuditLog.action.like("platform.factor.%")
                )
            )
        )
        assert [row.status for row in credentials] == [
            "replaced",
            "confirmed",
        ]
        assert all(row.revoked_at is not None for row in sessions)
        assert [row.outcome for row in audits].count("rejected") == 1
        persisted = " ".join(
            str(value)
            for row in audits
            for value in row.__dict__.values()
        )
        assert pending["base32_seed"] not in persisted
        assert all(
            code not in persisted for code in completed["recovery_codes"]
        )

    relogin = client.post(
        "/platform/api/login",
        base_url="https://localhost",
        json={
            "username": "root.admin",
            "password": PASSWORD,
            "factor_method": "recovery_code",
            "factor": completed["recovery_codes"][0],
        },
    )
    assert relogin.status_code == 200, relogin.get_json()


def test_platform_tenant_directory_is_minimized_paginated_and_audited(
    tmp_path,
    control_database,
):
    root_directory = _install_root_key(tmp_path, control_database)
    _login_time, login_step, _recovery_codes = _activate_admin(control_database)
    tenant_ids = (
        "31000000-0000-4000-8000-000000000001",
        "31000000-0000-4000-8000-000000000002",
    )
    with control_database.transaction() as session:
        session.add_all(
            [
                Tenant(
                    id=tenant_ids[0],
                    name="甲租户",
                    slug="tenant-a",
                    status="active",
                    settings_json={"private": "must-not-leak"},
                ),
                Tenant(
                    id=tenant_ids[1],
                    name="乙租户",
                    slug="tenant-b",
                    status="suspended",
                    settings_json={"private": "must-not-leak"},
                ),
            ]
        )

    app = Flask(__name__)
    app.config.update(TESTING=True)
    runtime = SqlAlchemyPlatformIdentityHttpRuntime(
        control_database=control_database,
        root_key_directory=root_directory,
        login_settings=_settings(),
    )
    install_platform_identity_http_runtime(app, runtime=runtime)
    app.register_blueprint(bp)
    client = app.test_client()

    assert client.get(
        "/platform/api/tenants?page=nope",
        base_url="https://localhost",
    ).status_code == 401
    login = client.post(
        "/platform/api/login",
        base_url="https://localhost",
        json={
            "username": "root.admin",
            "password": PASSWORD,
            "factor_method": "totp",
            "factor": generate_totp_code(SEED, login_step),
        },
    )
    assert login.status_code == 200

    response = client.get(
        "/platform/api/tenants?page=1&page_size=1&status=active",
        base_url="https://localhost",
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["page"] == 1
    assert data["page_size"] == 1
    assert data["has_more"] is False
    assert data["status_filter"] == "active"
    assert data["items"][0]["tenant_id"] == tenant_ids[0]
    serialized = str(data)
    assert "must-not-leak" not in serialized
    assert "settings_json" not in serialized
    assert "database_name" not in serialized

    response = client.get(
        f"/platform/api/tenants/{tenant_ids[0]}",
        base_url="https://localhost",
    )
    assert response.status_code == 200
    detail = response.get_json()["data"]
    assert detail["tenant_id"] == tenant_ids[0]
    assert detail["subscription"] is None
    assert detail["database_route"] is None
    assert client.get(
        "/platform/api/tenants/not-a-uuid",
        base_url="https://localhost",
    ).status_code == 404
    assert client.get(
        "/platform/api/tenants?unexpected=1",
        base_url="https://localhost",
    ).status_code == 400

    with control_database.new_session() as session:
        audits = list(
            session.scalars(
                sa.select(PlatformAuditLog).where(
                    PlatformAuditLog.action.in_(
                        ("platform.tenants.list", "platform.tenants.get")
                    )
                )
            )
        )
        assert {row.action for row in audits} == {
            "platform.tenants.list",
            "platform.tenants.get",
        }
        assert all(row.pii_revealed is False for row in audits)
        detail_audit = next(
            row for row in audits if row.action == "platform.tenants.get"
        )
        assert detail_audit.target_tenant_id == tenant_ids[0]


def test_setup_token_completes_password_totp_and_one_time_recovery_codes(
    tmp_path,
    control_database,
):
    root_directory = _install_root_key(tmp_path, control_database)
    with control_database.new_session() as session:
        database_now = read_database_utc_value(session)
    if database_now.tzinfo is None:
        database_now = database_now.replace(tzinfo=timezone.utc)
    with control_database.transaction() as session:
        challenge = PlatformAdminHostService().create_pending_admin(
            session,
            username="setup.root",
            setup_ttl=timedelta(minutes=10),
            os_operator_reference="ops:jim",
            command_id="command:setup-http:1",
            now=database_now,
        )

    app = Flask(__name__)
    app.config.update(TESTING=True)
    runtime = SqlAlchemyPlatformIdentityHttpRuntime(
        control_database=control_database,
        root_key_directory=root_directory,
        login_settings=_settings(),
    )
    install_platform_identity_http_runtime(app, runtime=runtime)
    app.register_blueprint(bp)
    client = app.test_client()

    response = client.post(
        "/platform/api/setup/consume",
        base_url="https://localhost",
        json={"setup_token": challenge.plaintext_token},
    )
    assert response.status_code == 200
    setup_headers = {PLATFORM_SETUP_HEADER_NAME: challenge.plaintext_token}

    response = client.post(
        "/platform/api/setup/password",
        base_url="https://localhost",
        headers=setup_headers,
        json={"password": PASSWORD},
    )
    assert response.status_code == 200
    response = client.post(
        "/platform/api/setup/totp",
        base_url="https://localhost",
        headers=setup_headers,
    )
    assert response.status_code == 200
    totp_payload = response.get_json()["data"]
    encoded_seed = totp_payload["base32_seed"]
    padded_seed = encoded_seed + "=" * (-len(encoded_seed) % 8)
    seed = base64.b32decode(padded_seed)
    with control_database.new_session() as session:
        complete_now = read_database_utc_value(session)
    if complete_now.tzinfo is None:
        complete_now = complete_now.replace(tzinfo=timezone.utc)
    complete_step = totp_time_step(int(complete_now.timestamp()))
    response = client.post(
        "/platform/api/setup/complete",
        base_url="https://localhost",
        headers=setup_headers,
        json={
            "credential_id": totp_payload["credential_id"],
            "totp_code": generate_totp_code(seed, complete_step),
        },
    )
    assert response.status_code == 200
    recovery_codes = response.get_json()["data"]["recovery_codes"]
    assert len(recovery_codes) == 6
    assert len(set(recovery_codes)) == 6
    assert all(code.startswith("impr1_") for code in recovery_codes)
    assert all(
        PLATFORM_SESSION_COOKIE_NAME not in value
        for value in response.headers.getlist("Set-Cookie")
    )

    response = client.post(
        "/platform/api/setup/password",
        base_url="https://localhost",
        headers=setup_headers,
        json={"password": "another valid password value"},
    )
    assert response.status_code == 401
    with control_database.new_session() as session:
        admin = session.get(PlatformAdmin, challenge.platform_admin_id)
        assert admin.status == "active"
        rows = list(session.scalars(sa.select(PlatformAdminRecoveryCode)))
        assert len(rows) == 6
        persisted = " ".join(
            str(value)
            for row in rows
            for value in row.__dict__.values()
        )
        assert all(code not in persisted for code in recovery_codes)
        actions = set(session.scalars(sa.select(PlatformAuditLog.action)))
        assert {
            "platform_admin.bootstrap",
            "platform_admin.setup_token_consumed",
            "platform_admin.setup_password_set",
            "platform_admin.setup_totp_started",
            "platform_admin.setup_completed",
        } <= actions


def _install_root_key(tmp_path, control_database):
    root_directory = tmp_path / "root-keys"
    root_directory.mkdir()
    key_file = root_directory / "v7"
    key_file.write_bytes(base64.b64encode(bytes(range(32))) + b"\n")
    key_file.chmod(0o400)
    with control_database.transaction() as session:
        session.add(
            PlatformRootKeyVersion(
                version=7,
                fingerprint_sha256=bytes.fromhex(
                    ROOT_KEY.fingerprint_sha256
                ),
                status="active",
                activated_at=datetime.now(timezone.utc),
            )
        )
    return str(root_directory)


def _activate_admin(control_database):
    with control_database.new_session() as session:
        database_now = read_database_utc_value(session)
    if database_now.tzinfo is None:
        database_now = database_now.replace(tzinfo=timezone.utc)
    login_step = totp_time_step(int(database_now.timestamp()))
    confirmation_step = login_step - 1
    confirmation_at = datetime.fromtimestamp(
        confirmation_step * 30 + 1,
        tz=timezone.utc,
    )
    setup = PlatformAdminSetupService()
    totp = PlatformTotpService(seed_generator=lambda: SEED)
    recovery = PlatformRecoveryCodeService()
    with control_database.transaction() as session:
        challenge = setup.create_pending_admin(
            session,
            username="root.admin",
            now=confirmation_at - timedelta(seconds=2),
        )
        admin_id = challenge.platform_admin_id
        token = challenge.plaintext_token
    with control_database.transaction() as session:
        assert setup.consume(
            session,
            presented_token=token,
            now=confirmation_at - timedelta(seconds=1),
        ).accepted
        setup.set_password(
            session,
            platform_admin_id=admin_id,
            expected_setup_version=1,
            password=PASSWORD,
            hasher=PlatformPasswordHasher(),
            now=confirmation_at - timedelta(seconds=1),
        )
        pending = totp.create_pending_binding(
            session,
            platform_admin_id=admin_id,
            root_key=ROOT_KEY,
            now=confirmation_at - timedelta(seconds=1),
        )
        credential_id = pending.credential_id
        pending.take_base32_seed()
    with control_database.transaction() as session:
        totp.confirm_pending(
            session,
            credential_id=credential_id,
            presented_code=generate_totp_code(SEED, confirmation_step),
            root_key=ROOT_KEY,
            now=confirmation_at,
            allowed_drift_steps=0,
        )
        batch = recovery.issue_codes(
            session,
            platform_admin_id=admin_id,
            count=6,
            now=confirmation_at,
        )
        recovery_codes = batch.take_plaintext_codes()
        activate_admin_if_ready(
            session,
            platform_admin_id=admin_id,
            expected_setup_version=1,
            now=confirmation_at,
        )
    return database_now, login_step, recovery_codes


def _settings():
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
            factor_max_age=timedelta(minutes=1),
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
