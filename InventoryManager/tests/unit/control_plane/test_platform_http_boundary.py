from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask, Response, request

from inventory_control import ControlDatabase
from inventory_control.domain import Capability, PlatformRole
from inventory_control.models import (
    ControlBase,
    PlatformAdmin,
    PlatformAdminSession,
    PlatformAdminTotpCredential,
)
from inventory_control.platform_http import (
    PLATFORM_CSRF_HEADER_NAME,
    PLATFORM_DEVICE_COOKIE_NAME,
    PLATFORM_SESSION_COOKIE_NAME,
    PlatformAuthenticationRequired,
    PlatformCsrfDenied,
    PlatformHttpBoundary,
    clear_platform_session_cookie,
    platform_http_error_response,
    resolve_platform_device_id,
    set_platform_device_cookie,
    set_platform_session_cookie,
)
from inventory_control.platform_identity import (
    PlatformAdminSessionService,
    issue_platform_csrf_token,
    issue_platform_session_token,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def flask_app():
    return Flask(__name__)


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


def test_platform_cookie_builds_separate_fixed_role_context(
    flask_app, control_database
):
    session_token, csrf_token, admin_id, session_id = _seed_session(
        control_database
    )
    boundary = PlatformHttpBoundary(PlatformAdminSessionService())
    headers = {
        "Cookie": f"{PLATFORM_SESSION_COOKIE_NAME}={session_token}",
    }
    with flask_app.test_request_context(
        "/platform/api/session", headers=headers
    ), control_database.transaction() as session:
        context = boundary.authorize(
            session,
            request,
            capability=Capability.PLATFORM_TENANTS_READ,
            now=NOW + timedelta(minutes=1),
        )
    assert context.platform_admin_id == admin_id
    assert context.session_id == session_id
    assert context.role is PlatformRole.PLATFORM_ADMIN
    assert context.username_canonical == "root.admin"
    assert session_token not in repr(context)
    assert csrf_token not in repr(context)


def test_platform_mutation_requires_its_own_csrf_and_rejects_tenant_names(
    flask_app, control_database
):
    session_token, csrf_token, _admin_id, _session_id = _seed_session(
        control_database
    )
    boundary = PlatformHttpBoundary(PlatformAdminSessionService())
    cookie = f"{PLATFORM_SESSION_COOKIE_NAME}={session_token}"
    for presented in (None, session_token, "tenant-csrf-value"):
        headers = {"Cookie": cookie}
        if presented is not None:
            headers[PLATFORM_CSRF_HEADER_NAME] = presented
        with flask_app.test_request_context(
            "/platform/api/logout", method="POST", headers=headers
        ), control_database.new_session() as session:
            with pytest.raises(PlatformCsrfDenied):
                boundary.authorize(
                    session,
                    request,
                    capability=Capability.SESSION_LOGOUT,
                    now=NOW + timedelta(minutes=1),
                )

    with flask_app.test_request_context(
        "/platform/api/logout",
        method="POST",
        headers={
            "Cookie": cookie,
            PLATFORM_CSRF_HEADER_NAME: csrf_token,
        },
    ), control_database.transaction() as session:
        assert boundary.authorize(
            session,
            request,
            capability=Capability.SESSION_LOGOUT,
            now=NOW + timedelta(minutes=1),
        ).session_id


def test_tenant_cookie_or_duplicate_platform_cookie_is_fixed_401(
    flask_app, control_database
):
    session_token, _csrf_token, _admin_id, _session_id = _seed_session(
        control_database
    )
    boundary = PlatformHttpBoundary(PlatformAdminSessionService())
    cases = (
        "__Host-inventory_tenant_session=tenant-value",
        (
            f"{PLATFORM_SESSION_COOKIE_NAME}={session_token}; "
            f"{PLATFORM_SESSION_COOKIE_NAME}={session_token}"
        ),
    )
    for cookie in cases:
        with flask_app.test_request_context(
            "/platform/api/session", headers={"Cookie": cookie}
        ), control_database.new_session() as session:
            with pytest.raises(PlatformAuthenticationRequired) as caught:
                boundary.authenticate(
                    session,
                    request,
                    now=NOW + timedelta(minutes=1),
                )
        response = platform_http_error_response(caught.value)
        assert response.status_code == 401
        assert response.get_json()["error"]["code"] == "PLATFORM_SESSION_INVALID"
        assert response.headers["Cache-Control"] == "private, no-store"


def test_platform_session_and_device_cookies_are_host_only_scoped_and_secure(
    flask_app,
):
    session_token = issue_platform_session_token().plaintext
    response = set_platform_session_cookie(Response(), session_token)
    session_header = response.headers.getlist("Set-Cookie")[0]
    assert f"{PLATFORM_SESSION_COOKIE_NAME}=" in session_header
    assert "Secure" in session_header
    assert "HttpOnly" in session_header
    assert "SameSite=Lax" in session_header
    assert "Path=/platform" in session_header
    assert "Domain=" not in session_header

    with flask_app.test_request_context("/platform/api/login"):
        device_id, created = resolve_platform_device_id(request)
    assert created
    response = set_platform_device_cookie(
        Response(), device_id, max_age_seconds=86_400
    )
    device_header = response.headers.getlist("Set-Cookie")[0]
    assert f"{PLATFORM_DEVICE_COOKIE_NAME}={device_id}" in device_header
    assert "Secure" in device_header
    assert "HttpOnly" in device_header
    assert "Path=/platform" in device_header
    assert "Domain=" not in device_header

    cleared = clear_platform_session_cookie(Response())
    clear_header = cleared.headers.getlist("Set-Cookie")[0]
    assert f"{PLATFORM_SESSION_COOKIE_NAME}=" in clear_header
    assert "Expires=" in clear_header
    assert "Path=/platform" in clear_header


def _seed_session(control_database):
    bearer = issue_platform_session_token()
    csrf = issue_platform_csrf_token()
    with control_database.transaction() as session:
        admin = PlatformAdmin(
            username_canonical="root.admin",
            status="active",
            password_hash_encoded="$test-v1$not-a-real-password-hash",
            password_hash_algorithm="test",
            password_hash_version=1,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(admin)
        session.flush()
        credential = PlatformAdminTotpCredential(
            platform_admin_id=admin.id,
            generation=admin.totp_generation,
            secret_revision=1,
            status="confirmed",
            seed_nonce=b"n" * 12,
            seed_ciphertext=b"c" * 32,
            root_key_version=1,
            crypto_version=1,
            aad_version=1,
            last_accepted_time_step=1,
            created_at=NOW,
            confirmed_at=NOW,
        )
        session.add(credential)
        session.flush()
        row = PlatformAdminSession(
            platform_admin_id=admin.id,
            token_digest_sha256=bearer.digest_sha256,
            csrf_digest_sha256=csrf.digest_sha256,
            auth_version_at_issue=admin.auth_version,
            setup_version_at_issue=admin.setup_version,
            mfa_method="totp",
            mfa_verified_at=NOW,
            totp_credential_id=credential.id,
            totp_time_step=1,
            policy_version=1,
            csrf_generation=1,
            idle_timeout_seconds=1800,
            created_at=NOW,
            last_seen_at=NOW,
            idle_expires_at=NOW + timedelta(minutes=30),
            absolute_expires_at=NOW + timedelta(hours=8),
        )
        session.add(row)
        session.flush()
        return bearer.plaintext, csrf.plaintext, admin.id, row.id
