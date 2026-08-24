from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from flask import Flask, Response, request

from app.tenancy import TenantContext, TenantContextSource
from inventory_control import (
    ControlBase,
    ControlDatabase,
    Tenant,
    TenantMembership,
    TenantUserSession,
    User,
)
from inventory_control.domain import (
    Capability,
    EffectiveTenantGate,
    TenantGateDecision,
    TenantRole,
)
from inventory_control.identity import (
    CN_MOBILE_METADATA_VERSION,
    PHONE_NORMALIZATION_VERSION,
    SessionService,
    issue_session_token,
)
from inventory_control.tenant_http import (
    TENANT_CSRF_HEADER_NAME,
    TENANT_SESSION_COOKIE_NAME,
    AuthContext,
    TenantAuthenticationRequired,
    TenantCapabilityDenied,
    TenantCsrfDenied,
    TenantHttpBoundary,
    active_tenant_context,
    clear_tenant_session_cookie,
    mark_private_no_store,
    set_tenant_session_cookie,
    tenant_http_error_response,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def flask_app() -> Flask:
    return Flask(__name__)


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


@pytest.fixture
def identity_ids(control_database):
    with control_database.transaction() as session:
        tenant = Tenant(status="active", access_version=4)
        user = User(
            phone_e164="+8613800138001",
            phone_normalization_version=PHONE_NORMALIZATION_VERSION,
            phone_metadata_version=CN_MOBILE_METADATA_VERSION,
            phone_verified_at=NOW,
            status="active",
        )
        session.add_all([tenant, user])
        session.flush()
        membership = TenantMembership(
            tenant_id=tenant.id,
            user_id=user.id,
            role_key="admin",
            status="active",
            source_type="migration",
        )
        session.add(membership)
        session.flush()
        return tenant.id, user.id, membership.id


def _decision(gate: EffectiveTenantGate) -> TenantGateDecision:
    return TenantGateDecision(
        gate=gate,
        error_code=None if gate is EffectiveTenantGate.ACTIVE else gate.value,
    )


def _gate_from_tenant(_session, tenant, _now) -> TenantGateDecision:
    gate = {
        "active": EffectiveTenantGate.ACTIVE,
        "expired": EffectiveTenantGate.EXPIRED,
        "suspended": EffectiveTenantGate.SUSPENDED,
    }.get(tenant.status, EffectiveTenantGate.RECOVERY_HOLD)
    return _decision(gate)


def _services(gate_reader=_gate_from_tenant):
    session_service = SessionService(gate_current_read=gate_reader)
    return session_service, TenantHttpBoundary(session_service)


def _issue(control_database, user_id, session_service, *, now=NOW):
    with control_database.transaction() as session:
        return session_service.issue(
            session,
            user_id=user_id,
            idle_timeout=timedelta(minutes=30),
            absolute_timeout=timedelta(hours=8),
            now=now,
        )


def _request_headers(*, token: str | None, csrf: str | None = None):
    headers = []
    if token is not None:
        headers.append(("Cookie", f"{TENANT_SESSION_COOKIE_NAME}={token}"))
    if csrf is not None:
        headers.append((TENANT_CSRF_HEADER_NAME, csrf))
    return headers


def test_valid_cookie_builds_bearer_free_context_and_leaves_commit_to_caller(
    flask_app, control_database, identity_ids
) -> None:
    tenant_id, user_id, membership_id = identity_ids
    service, boundary = _services()
    issued = _issue(control_database, user_id, service)

    session = control_database.new_session()
    transaction = session.begin()
    try:
        with flask_app.test_request_context(
            "/api/inventory",
            headers=_request_headers(token=issued.session_token),
        ):
            context = boundary.authorize(
                session,
                request,
                capability=Capability.INVENTORY_READ,
                now=NOW + timedelta(minutes=5),
            )

        assert context == AuthContext(
            session_id=issued.auth.session_id,
            user_id=user_id,
            membership_id=membership_id,
            tenant_id=tenant_id,
            role=TenantRole.ADMIN,
            user_auth_version=1,
            tenant_access_version=4,
            tenant_timezone="Asia/Shanghai",
            effective_gate=EffectiveTenantGate.ACTIVE,
        )
        assert transaction.is_active
        assert session.in_transaction()
        transaction.rollback()
    finally:
        session.close()

    with control_database.new_session() as check:
        row = check.get(TenantUserSession, issued.auth.session_id)
        assert row.last_seen_at.replace(tzinfo=timezone.utc) == NOW


def test_missing_cookie_does_not_accept_authorization_bearer_and_returns_fixed_401(
    flask_app, control_database, identity_ids
) -> None:
    _, user_id, _ = identity_ids
    service, boundary = _services()
    issued = _issue(control_database, user_id, service)

    with flask_app.test_request_context(
        "/api/inventory",
        headers={"Authorization": f"Bearer {issued.session_token}"},
    ), control_database.new_session() as session:
        with pytest.raises(TenantAuthenticationRequired) as caught:
            boundary.authenticate(session, request, now=NOW + timedelta(minutes=1))

    response = tenant_http_error_response(caught.value)
    assert response.status_code == 401
    assert response.get_json() == {
        "error": {
            "code": "TENANT_SESSION_INVALID",
            "message": "Authentication is required.",
        }
    }
    assert response.headers["Cache-Control"] == "private, no-store"
    assert issued.session_token not in response.get_data(as_text=True)
    assert issued.session_token not in str(caught.value)


def test_revoked_cookie_and_duplicate_cookie_are_the_same_fixed_401(
    flask_app, control_database, identity_ids
) -> None:
    _, user_id, _ = identity_ids
    service, boundary = _services()
    issued = _issue(control_database, user_id, service)
    other = issue_session_token().plaintext
    with control_database.transaction() as session:
        row = session.get(TenantUserSession, issued.auth.session_id)
        row.revoked_at = NOW + timedelta(seconds=1)
        row.revoked_reason_code = "test_revoked"

    cases = [
        _request_headers(token=issued.session_token),
        [
            (
                "Cookie",
                f"{TENANT_SESSION_COOKIE_NAME}={issued.session_token}; "
                f"{TENANT_SESSION_COOKIE_NAME}={other}",
            )
        ],
    ]
    for headers in cases:
        with flask_app.test_request_context("/api/inventory", headers=headers), (
            control_database.new_session()
        ) as session:
            with pytest.raises(TenantAuthenticationRequired) as caught:
                boundary.authenticate(
                    session,
                    request,
                    now=NOW + timedelta(minutes=1),
                )
        assert caught.value.code == "TENANT_SESSION_INVALID"
        assert caught.value.status_code == 401


def test_active_operator_is_denied_admin_capability_after_authentication(
    flask_app, control_database, identity_ids
) -> None:
    _, user_id, membership_id = identity_ids
    with control_database.transaction() as session:
        session.get(TenantMembership, membership_id).role_key = "operator"
    service, boundary = _services()
    issued = _issue(control_database, user_id, service)

    with flask_app.test_request_context(
        "/api/members",
        headers=_request_headers(token=issued.session_token),
    ), control_database.new_session() as session:
        with pytest.raises(TenantCapabilityDenied) as caught:
            boundary.authorize(
                session,
                request,
                capability=Capability.TENANT_MEMBERS_MANAGE,
                now=NOW + timedelta(minutes=1),
            )

    response = tenant_http_error_response(caught.value)
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "TENANT_CAPABILITY_DENIED"


def test_expired_admin_can_redeem_but_expired_operator_cannot(
    flask_app, control_database, identity_ids
) -> None:
    tenant_id, user_id, membership_id = identity_ids
    with control_database.transaction() as session:
        session.get(Tenant, tenant_id).status = "expired"

    service, boundary = _services()
    admin = _issue(control_database, user_id, service)
    with flask_app.test_request_context(
        "/api/subscription/redeem",
        method="POST",
        headers=_request_headers(
            token=admin.session_token,
            csrf=admin.csrf_token,
        ),
    ), control_database.transaction() as session:
        context = boundary.authorize(
            session,
            request,
            capability=Capability.TENANT_SUBSCRIPTION_REDEEM,
            now=NOW + timedelta(minutes=1),
        )
        assert context.effective_gate is EffectiveTenantGate.EXPIRED
        assert context.role is TenantRole.ADMIN

    with control_database.transaction() as session:
        session.get(TenantMembership, membership_id).role_key = "operator"
    operator = _issue(control_database, user_id, service, now=NOW + timedelta(minutes=2))
    with flask_app.test_request_context(
        "/api/subscription/redeem",
        method="POST",
        headers=_request_headers(
            token=operator.session_token,
            csrf=operator.csrf_token,
        ),
    ), control_database.new_session() as session:
        with pytest.raises(TenantCapabilityDenied):
            boundary.authorize(
                session,
                request,
                capability=Capability.TENANT_SUBSCRIPTION_REDEEM,
                now=NOW + timedelta(minutes=3),
            )


@pytest.mark.parametrize("csrf_source", ["missing", "bearer", "malformed"])
def test_mutation_requires_the_independent_current_csrf_proof(
    flask_app, control_database, identity_ids, csrf_source
) -> None:
    _, user_id, _ = identity_ids
    service, boundary = _services()
    issued = _issue(control_database, user_id, service)
    csrf = {
        "missing": None,
        "bearer": issued.session_token,
        "malformed": "not-a-csrf-token",
    }[csrf_source]

    with flask_app.test_request_context(
        "/api/inventory",
        method="POST",
        headers=_request_headers(token=issued.session_token, csrf=csrf),
    ), control_database.new_session() as session:
        with pytest.raises(TenantCsrfDenied) as caught:
            boundary.authorize(
                session,
                request,
                capability=Capability.INVENTORY_WRITE,
                now=NOW + timedelta(minutes=1),
            )

    assert caught.value.status_code == 403
    assert caught.value.code == "CSRF_INVALID"
    assert issued.session_token not in str(caught.value)


def test_mutation_authorizes_against_fresh_gate_not_resolve_snapshot(
    flask_app, control_database, identity_ids
) -> None:
    _, user_id, _ = identity_ids
    phase = {"request": False, "reads": 0}

    def advancing_gate(_session, _tenant, _now):
        if not phase["request"]:
            return _decision(EffectiveTenantGate.ACTIVE)
        phase["reads"] += 1
        gate = (
            EffectiveTenantGate.ACTIVE
            if phase["reads"] == 1
            else EffectiveTenantGate.EXPIRED
        )
        return _decision(gate)

    service, boundary = _services(advancing_gate)
    issued = _issue(control_database, user_id, service)
    phase["request"] = True

    with flask_app.test_request_context(
        "/api/subscription/redeem",
        method="POST",
        headers=_request_headers(
            token=issued.session_token,
            csrf=issued.csrf_token,
        ),
    ), control_database.transaction() as session:
        context = boundary.authorize(
            session,
            request,
            capability=Capability.TENANT_SUBSCRIPTION_REDEEM,
            now=NOW + timedelta(minutes=1),
        )

    assert phase["reads"] == 2
    assert context.effective_gate is EffectiveTenantGate.EXPIRED


def test_gate_closing_during_csrf_recheck_fails_as_fixed_403(
    flask_app, control_database, identity_ids
) -> None:
    _, user_id, _ = identity_ids
    phase = {"request": False, "reads": 0}

    def closing_gate(_session, _tenant, _now):
        if not phase["request"]:
            return _decision(EffectiveTenantGate.ACTIVE)
        phase["reads"] += 1
        gate = (
            EffectiveTenantGate.ACTIVE
            if phase["reads"] == 1
            else EffectiveTenantGate.RECOVERY_HOLD
        )
        return _decision(gate)

    service, boundary = _services(closing_gate)
    issued = _issue(control_database, user_id, service)
    phase["request"] = True

    with flask_app.test_request_context(
        "/api/inventory",
        method="POST",
        headers=_request_headers(
            token=issued.session_token,
            csrf=issued.csrf_token,
        ),
    ), control_database.new_session() as session:
        with pytest.raises(TenantCsrfDenied) as caught:
            boundary.authorize(
                session,
                request,
                capability=Capability.INVENTORY_WRITE,
                now=NOW + timedelta(minutes=1),
            )

    assert caught.value.code == "CSRF_INVALID"
    assert phase["reads"] == 2


def test_gate_closed_before_authentication_fails_as_fixed_401(
    flask_app, control_database, identity_ids
) -> None:
    _, user_id, _ = identity_ids
    state = {"gate": EffectiveTenantGate.ACTIVE}
    service, boundary = _services(
        lambda _session, _tenant, _now: _decision(state["gate"])
    )
    issued = _issue(control_database, user_id, service)
    state["gate"] = EffectiveTenantGate.DELETION_COOLING_OFF

    with flask_app.test_request_context(
        "/api/inventory",
        headers=_request_headers(token=issued.session_token),
    ), control_database.new_session() as session:
        with pytest.raises(TenantAuthenticationRequired) as caught:
            boundary.authenticate(session, request, now=NOW + timedelta(minutes=1))
    assert caught.value.status_code == 401


def test_cookie_set_and_clear_helpers_enforce_host_prefix_attributes() -> None:
    token = issue_session_token().plaintext
    response = set_tenant_session_cookie(Response(), token, max_age=1800)
    header = response.headers.getlist("Set-Cookie")[0]

    assert header.startswith(f"{TENANT_SESSION_COOKIE_NAME}={token};")
    assert "Max-Age=1800" in header
    assert "Secure" in header
    assert "HttpOnly" in header
    assert "Path=/" in header
    assert "SameSite=Lax" in header
    assert "Domain=" not in header
    assert response.headers["Cache-Control"] == "private, no-store"

    cleared = clear_tenant_session_cookie(Response())
    clear_header = cleared.headers.getlist("Set-Cookie")[0]
    assert clear_header.startswith(f"{TENANT_SESSION_COOKIE_NAME}=;")
    assert "Max-Age=0" in clear_header
    assert "Secure" in clear_header
    assert "HttpOnly" in clear_header
    assert "Path=/" in clear_header
    assert "SameSite=Lax" in clear_header
    assert "Domain=" not in clear_header
    assert cleared.headers["Cache-Control"] == "private, no-store"


def test_context_errors_and_sensitive_helpers_do_not_leak_bearer(
    flask_app, control_database, identity_ids
) -> None:
    _, user_id, _ = identity_ids
    service, boundary = _services()
    issued = _issue(control_database, user_id, service)

    with flask_app.test_request_context(
        "/api/inventory",
        headers=_request_headers(token=issued.session_token),
    ), control_database.transaction() as session:
        context = boundary.authenticate(
            session,
            request,
            now=NOW + timedelta(minutes=1),
        )

    assert issued.session_token not in repr(context)
    assert issued.session_token not in str(asdict(context))
    assert "token" not in " ".join(asdict(context)).lower()

    sensitive = mark_private_no_store(Response("sensitive"))
    assert sensitive.headers["Cache-Control"] == "private, no-store"
    assert sensitive.headers["Pragma"] == "no-cache"

    with pytest.raises(ValueError) as caught:
        set_tenant_session_cookie(Response(), f"invalid-{issued.session_token}")
    assert issued.session_token not in str(caught.value)


def test_boundary_requires_typed_capability_before_touching_credentials(
    flask_app, control_database, identity_ids
) -> None:
    _, user_id, _ = identity_ids
    service, boundary = _services()
    issued = _issue(control_database, user_id, service)
    with flask_app.test_request_context(
        "/api/inventory",
        headers=_request_headers(token=issued.session_token),
    ), control_database.new_session() as session:
        with pytest.raises(TypeError, match="Capability"):
            boundary.authorize(
                session,
                request,
                capability="inventory.read",
                now=NOW + timedelta(minutes=1),
            )


def test_active_auth_context_creates_minimal_web_tenant_context(
    flask_app, control_database, identity_ids
) -> None:
    tenant_id, user_id, _ = identity_ids
    service, boundary = _services()
    issued = _issue(control_database, user_id, service)

    with flask_app.test_request_context(
        "/api/inventory",
        headers=_request_headers(token=issued.session_token),
    ), control_database.transaction() as session:
        auth_context = boundary.authorize(
            session,
            request,
            capability=Capability.INVENTORY_READ,
            now=NOW + timedelta(minutes=1),
        )

    tenant_context = active_tenant_context(
        auth_context,
        request_id="request-http-active",
    )
    assert tenant_context == TenantContext(
        tenant_id=UUID(tenant_id),
        access_version=4,
        source=TenantContextSource.WEB_SESSION,
        principal_ref=f"user:{user_id}",
        source_ref=f"session:{issued.auth.session_id}",
        request_id="request-http-active",
    )
    assert "membership" not in repr(tenant_context).lower()


@pytest.mark.parametrize(
    "gate",
    [EffectiveTenantGate.EXPIRED, EffectiveTenantGate.SUSPENDED],
)
def test_restricted_auth_context_cannot_become_tenant_database_authority(
    gate,
) -> None:
    context = AuthContext(
        session_id="22222222-2222-4222-8222-222222222222",
        user_id="33333333-3333-4333-8333-333333333333",
        membership_id="44444444-4444-4444-8444-444444444444",
        tenant_id="11111111-1111-4111-8111-111111111111",
        role=TenantRole.ADMIN,
        user_auth_version=1,
        tenant_access_version=4,
        tenant_timezone="Asia/Shanghai",
        effective_gate=gate,
    )

    with pytest.raises(TenantCapabilityDenied):
        active_tenant_context(context, request_id="request-restricted")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_id", "not-a-uuid"),
        ("user_id", "not-a-uuid"),
        ("session_id", "not-a-uuid"),
        ("tenant_access_version", 0),
    ],
)
def test_malformed_trusted_context_fails_closed_before_tenant_routing(
    field, value
) -> None:
    values = {
        "session_id": "22222222-2222-4222-8222-222222222222",
        "user_id": "33333333-3333-4333-8333-333333333333",
        "membership_id": "44444444-4444-4444-8444-444444444444",
        "tenant_id": "11111111-1111-4111-8111-111111111111",
        "role": TenantRole.ADMIN,
        "user_auth_version": 1,
        "tenant_access_version": 4,
        "tenant_timezone": "Asia/Shanghai",
        "effective_gate": EffectiveTenantGate.ACTIVE,
    }
    values[field] = value
    context = AuthContext(**values)

    with pytest.raises(TenantAuthenticationRequired):
        active_tenant_context(context, request_id="request-malformed")
