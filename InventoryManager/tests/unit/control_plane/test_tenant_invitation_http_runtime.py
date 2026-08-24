from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs
from uuid import uuid4

import pytest
from flask import Flask
import sqlalchemy as sa

from app.routes.tenant_invitation_api import bp as invitation_bp
from app.services.tenant_invitations import (
    TENANT_INVITATION_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyTenantInvitationHttpRuntime,
)
from inventory_control import (
    ControlBase,
    ControlDatabase,
)
from inventory_control.models import (
    MemberSeatGuard,
    PlatformRootKeyVersion,
    SmsChallenge,
    Tenant,
    TenantAuthSecurityEvent,
    TenantInvitation,
    TenantMembership,
    TenantSensitiveActionIntent,
    User,
)
from inventory_control.crypto import RootKey
from inventory_control.database import read_database_utc_value
from inventory_control.domain import EffectiveTenantGate, TenantGateDecision
from inventory_control.identity import (
    CN_MOBILE_METADATA_VERSION,
    PHONE_NORMALIZATION_VERSION,
    SessionService,
)
from inventory_control.invitations import InvitationJoinGateFacts
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


ADMIN_PHONE = "+8613800138001"
TARGET_PHONE = "+8613900138002"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _session_gate(_session, tenant, _now):
    return TenantGateDecision(
        EffectiveTenantGate.ACTIVE,
        None,
    )


def _join_gate(_session, *, tenant, database_now):
    del database_now
    return InvitationJoinGateFacts(
        tenant_uuid=tenant.id,
        access_version=tenant.access_version,
        join_allowed=tenant.status == "active",
    )


class RecordingSmsProvider:
    def __init__(self) -> None:
        self.phones: list[str] = []
        self.codes: list[str] = []

    def send_verification(self, request):
        self.phones.append(request.canonical_phone_e164)
        self.codes.append(request.take_plaintext_code())
        return SmsDeliveryOutcome.SENT


@pytest.fixture
def harness(tmp_path, mysql_control_database):
    database = mysql_control_database
    provider = RecordingSmsProvider()
    root_key = RootKey(version=7, material=b"i" * 32)
    key_file = tmp_path / "v7"
    key_file.write_bytes(base64.b64encode(root_key._material_bytes()) + b"\n")
    key_file.chmod(0o400)
    session_service = SessionService(gate_current_read=_session_gate)
    boundary = TenantHttpBoundary(session_service)

    with database.transaction() as session:
        now = _utc(read_database_utc_value(session))
        session.add(
            PlatformRootKeyVersion(
                version=7,
                fingerprint_sha256=bytes.fromhex(root_key.fingerprint_sha256),
                status="active",
                activated_at=now,
            )
        )
        tenant = Tenant(
            name="演示租户",
            status="active",
            access_version=3,
            row_version=1,
        )
        admin = User(
            phone_e164=ADMIN_PHONE,
            phone_normalization_version=PHONE_NORMALIZATION_VERSION,
            phone_metadata_version=CN_MOBILE_METADATA_VERSION,
            phone_verified_at=now,
            status="active",
        )
        session.add_all((tenant, admin))
        session.flush()
        session.add(
            TenantMembership(
                tenant_id=tenant.id,
                user_id=admin.id,
                role_key="admin",
                status="active",
                source_type="migration",
            )
        )
        session.add(MemberSeatGuard(tenant_id=tenant.id))
        session.flush()
        issued = session_service.issue(
            session,
            user_id=admin.id,
            idle_timeout=timedelta(hours=1),
            absolute_timeout=timedelta(hours=8),
            now=now,
        )

    runtime = SqlAlchemyTenantInvitationHttpRuntime(
        control_database=database,
        tenant_http_boundary=boundary,
        root_key_directory=tmp_path,
        sms_provider=provider,
        sms_policy=SmsPolicy(),
        trusted_source_resolver=lambda _request: TrustedSourceBucket.unknown(),
        join_gate_current_read=_join_gate,
    )
    app = Flask(__name__)
    app.register_blueprint(invitation_bp)
    app.extensions[TENANT_INVITATION_HTTP_RUNTIME_EXTENSION] = runtime
    client = app.test_client()
    client.set_cookie(
        TENANT_SESSION_COOKIE_NAME,
        issued.session_token,
        secure=True,
    )
    return app, database, provider, issued, client


def _headers(issued):
    return {TENANT_CSRF_HEADER_NAME: issued.csrf_token}


def _create_operator(client, issued):
    response = client.post(
        "/api/v1/members/invitations",
        json={"phone": TARGET_PHONE, "role": "operator"},
        headers=_headers(issued),
    )
    assert response.status_code == 200
    return response.get_json()["data"]


def _credential_from_path(path: str):
    fragment = path.partition("#")[2]
    values = parse_qs(fragment)
    return {
        "invitation_id": values["invitation"][0],
        "generation": int(values["generation"][0]),
        "token": values["token"][0],
    }


def test_operator_invitation_rotates_link_lists_usage_and_revokes(harness):
    _app, database, _provider, issued, client = harness
    created = _create_operator(client, issued)
    first_credential = _credential_from_path(created["invitation_path"])

    listing = client.get("/api/v1/members")
    assert listing.status_code == 200
    data = listing.get_json()["data"]
    assert data["seat_usage"] == {
        "active_members": 1,
        "pending_invitations": 1,
        "used": 2,
        "limit": 10,
    }
    assert data["invitations"][0]["masked_phone"] == "+8613****8002"

    rotated = client.post(
        "/api/v1/members/invitations",
        json={
            "phone": TARGET_PHONE,
            "role": "operator",
            "expected_row_version": created["row_version"],
        },
        headers=_headers(issued),
    )
    assert rotated.status_code == 200
    current = rotated.get_json()["data"]
    assert current["invitation_id"] == created["invitation_id"]
    assert current["token_generation"] == 2
    current_credential = _credential_from_path(current["invitation_path"])
    assert client.post(
        "/api/v1/invitations/inspect", json=first_credential
    ).status_code == 404
    assert client.post(
        "/api/v1/invitations/inspect", json=current_credential
    ).status_code == 200

    revoked = client.post(
        f"/api/v1/members/invitations/{created['invitation_id']}/revoke",
        json={"expected_row_version": current["row_version"]},
        headers=_headers(issued),
    )
    assert revoked.status_code == 200
    assert revoked.get_json()["data"]["status"] == "revoked"
    with database.new_session() as session:
        assert session.get(
            TenantInvitation, created["invitation_id"]
        ).status == "revoked"


def test_public_handoff_requires_bound_sms_then_accepts_membership(harness):
    _app, database, provider, issued, client = harness
    credential = _credential_from_path(
        _create_operator(client, issued)["invitation_path"]
    )
    public_client = client.application.test_client()

    inspected = public_client.post(
        "/api/v1/invitations/inspect", json=credential
    )
    assert inspected.status_code == 200
    assert inspected.get_json()["data"] == {
        "invitation_id": credential["invitation_id"],
        "tenant_name": "演示租户",
        "role": "operator",
        "masked_phone": "+8613****8002",
        "expires_at": inspected.get_json()["data"]["expires_at"],
    }
    challenge = public_client.post(
        "/api/v1/invitations/challenges", json=credential
    )
    assert challenge.status_code == 202
    assert provider.phones[-1] == TARGET_PHONE

    accepted = public_client.post(
        "/api/v1/invitations/accept",
        json={
            **credential,
            "challenge_id": challenge.get_json()["data"]["challenge_id"],
            "code": provider.codes[-1],
        },
    )
    assert accepted.status_code == 200
    assert accepted.get_json()["data"]["accepted"] is True
    with database.new_session() as session:
        invitation = session.get(TenantInvitation, credential["invitation_id"])
        membership = session.scalar(
            sa.select(TenantMembership).where(
                TenantMembership.source_uuid == credential["invitation_id"]
            )
        )
        assert invitation.status == "accepted"
        assert membership.status == "active"
        assert membership.role_key == "operator"


def test_admin_invitation_d48_sends_to_actor_and_wrong_code_rolls_back(harness):
    _app, database, provider, issued, client = harness
    action_id = str(uuid4())
    action = {"phone": TARGET_PHONE, "role": "admin", "action_id": action_id}
    challenge = client.post(
        "/api/v1/members/invitations/admin-challenge",
        json=action,
        headers=_headers(issued),
    )
    assert challenge.status_code == 202
    challenge_id = challenge.get_json()["data"]["challenge_id"]
    assert provider.phones[-1] == ADMIN_PHONE
    replayed_challenge = client.post(
        "/api/v1/members/invitations/admin-challenge",
        json=action,
        headers=_headers(issued),
    )
    assert replayed_challenge.status_code == 202
    assert replayed_challenge.get_json()["data"] == {
        **challenge.get_json()["data"],
        "replayed": True,
    }
    rebound = client.post(
        "/api/v1/members/invitations/admin-challenge",
        json={**action, "phone": "+8613700137000"},
        headers=_headers(issued),
    )
    assert rebound.status_code == 409
    assert provider.phones.count(ADMIN_PHONE) == 1

    rejected = client.post(
        "/api/v1/members/invitations",
        json={
            **action,
            "challenge_id": challenge_id,
            "code": "000000",
        },
        headers=_headers(issued),
    )
    assert rejected.status_code == 404
    with database.new_session() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(TenantInvitation)
        ) == 0
        assert session.scalar(
            sa.select(sa.func.count()).select_from(User).where(
                User.phone_e164 == TARGET_PHONE
            )
        ) == 0
        assert session.get(SmsChallenge, challenge_id).wrong_attempt_count == 1

    created = client.post(
        "/api/v1/members/invitations",
        json={
            **action,
            "challenge_id": challenge_id,
            "code": provider.codes[-1],
        },
        headers=_headers(issued),
    )
    assert created.status_code == 200
    assert created.get_json()["data"]["role"] == "admin"
    assert created.get_json()["data"]["invitation_id"] == action_id

    replay = client.post(
        "/api/v1/members/invitations",
        json={
            **action,
            "challenge_id": challenge_id,
            "code": "not-reused",
        },
        headers=_headers(issued),
    )
    assert replay.status_code == 200
    assert replay.get_json()["data"] == {
        **created.get_json()["data"],
        "idempotent": True,
    }
    with database.new_session() as session:
        intent = session.get(TenantSensitiveActionIntent, action_id)
        invitation = session.get(TenantInvitation, action_id)
        events = tuple(
            session.scalars(
                sa.select(TenantAuthSecurityEvent).where(
                    TenantAuthSecurityEvent.intent_id == action_id
                )
            )
        )
        assert intent.status == "succeeded"
        assert intent.purpose == "admin_invitation"
        assert invitation.role_key == "admin"
        assert {row.event_type for row in events} == {
            "sensitive_action_committed",
            "sensitive_challenge_rejected",
            "sensitive_challenge_requested",
            "sensitive_challenge_verified",
        }


def test_member_mutation_requires_session_and_csrf(harness):
    app, _database, _provider, issued, client = harness
    unauthenticated = app.test_client().post(
        "/api/v1/members/invitations",
        json={"phone": TARGET_PHONE, "role": "operator"},
    )
    missing_csrf = client.post(
        "/api/v1/members/invitations",
        json={"phone": TARGET_PHONE, "role": "operator"},
    )
    assert unauthenticated.status_code == 401
    assert missing_csrf.status_code == 403
    assert missing_csrf.get_json()["data"]["code"] == "CSRF_INVALID"
    assert _headers(issued)[TENANT_CSRF_HEADER_NAME]


def test_operator_member_can_be_disabled_without_d48(harness):
    _app, database, _provider, issued, client = harness
    with database.transaction() as session:
        tenant_id = session.scalar(sa.select(Tenant.id))
        operator = User(
            phone_e164=TARGET_PHONE,
            phone_normalization_version=PHONE_NORMALIZATION_VERSION,
            phone_metadata_version=CN_MOBILE_METADATA_VERSION,
            status="active",
        )
        session.add(operator)
        session.flush()
        membership = TenantMembership(
            tenant_id=tenant_id,
            user_id=operator.id,
            role_key="operator",
            status="active",
            source_type="invitation",
        )
        session.add(membership)
        session.flush()
        membership_id = membership.id

    response = client.post(
        f"/api/v1/members/{membership_id}/mutations",
        json={
            "action": "disable",
            "action_id": str(uuid4()),
            "expected_row_version": 1,
        },
        headers=_headers(issued),
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "membership_id": membership_id,
        "role": "operator",
        "status": "disabled",
        "row_version": 2,
        "sessions_revoked": 0,
        "idempotent": False,
    }
    with database.new_session() as session:
        assert session.get(TenantMembership, membership_id).status == "disabled"


def test_admin_member_mutation_requires_the_separate_d48_boundary(harness):
    _app, database, _provider, issued, client = harness
    with database.transaction() as session:
        tenant_id = session.scalar(sa.select(Tenant.id))
        second_admin = User(
            phone_e164=TARGET_PHONE,
            phone_normalization_version=PHONE_NORMALIZATION_VERSION,
            phone_metadata_version=CN_MOBILE_METADATA_VERSION,
            status="active",
        )
        session.add(second_admin)
        session.flush()
        membership = TenantMembership(
            tenant_id=tenant_id,
            user_id=second_admin.id,
            role_key="admin",
            status="active",
            source_type="invitation",
        )
        session.add(membership)
        session.flush()
        membership_id = membership.id

    response = client.post(
        f"/api/v1/members/{membership_id}/mutations",
        json={
            "action": "disable",
            "action_id": str(uuid4()),
            "expected_row_version": 1,
        },
        headers=_headers(issued),
    )

    assert response.status_code == 403
    assert response.get_json()["data"]["code"] == (
        "MEMBER_MUTATION_VERIFICATION_REQUIRED"
    )
    with database.new_session() as session:
        assert session.get(TenantMembership, membership_id).status == "active"


def test_admin_member_mutation_consumes_exact_d48_intent_and_replays(harness):
    _app, database, provider, issued, client = harness
    with database.transaction() as session:
        tenant_id = session.scalar(sa.select(Tenant.id))
        second_admin = User(
            phone_e164=TARGET_PHONE,
            phone_normalization_version=PHONE_NORMALIZATION_VERSION,
            phone_metadata_version=CN_MOBILE_METADATA_VERSION,
            status="active",
        )
        session.add(second_admin)
        session.flush()
        membership = TenantMembership(
            tenant_id=tenant_id,
            user_id=second_admin.id,
            role_key="admin",
            status="active",
            source_type="invitation",
        )
        session.add(membership)
        session.flush()
        membership_id = membership.id
    action_id = str(uuid4())
    payload = {
        "action": "disable",
        "action_id": action_id,
        "expected_row_version": 1,
    }

    challenge = client.post(
        f"/api/v1/members/{membership_id}/mutations/challenge",
        json=payload,
        headers=_headers(issued),
    )
    assert challenge.status_code == 202
    challenge_id = challenge.get_json()["data"]["challenge_id"]
    assert provider.phones[-1] == ADMIN_PHONE
    replayed_challenge = client.post(
        f"/api/v1/members/{membership_id}/mutations/challenge",
        json=payload,
        headers=_headers(issued),
    )
    assert replayed_challenge.status_code == 202
    assert replayed_challenge.get_json()["data"] == {
        **challenge.get_json()["data"],
        "replayed": True,
    }
    assert provider.phones.count(ADMIN_PHONE) == 1

    wrong = client.post(
        f"/api/v1/members/{membership_id}/mutations/confirm",
        json={**payload, "challenge_id": challenge_id, "code": "000000"},
        headers=_headers(issued),
    )
    assert wrong.status_code == 403
    assert wrong.get_json()["data"]["code"] == (
        "MEMBER_MUTATION_VERIFICATION_REJECTED"
    )
    with database.new_session() as session:
        assert session.get(TenantMembership, membership_id).status == "active"
        assert session.get(SmsChallenge, challenge_id).wrong_attempt_count == 1

    changed = client.post(
        f"/api/v1/members/{membership_id}/mutations/confirm",
        json={
            **payload,
            "challenge_id": challenge_id,
            "code": provider.codes[-1],
        },
        headers=_headers(issued),
    )
    assert changed.status_code == 200
    assert changed.get_json()["data"] == {
        "membership_id": membership_id,
        "role": "admin",
        "status": "disabled",
        "row_version": 2,
        "sessions_revoked": 0,
        "idempotent": False,
    }

    replay = client.post(
        f"/api/v1/members/{membership_id}/mutations/confirm",
        json={**payload, "challenge_id": challenge_id, "code": "not-reused"},
        headers=_headers(issued),
    )
    assert replay.status_code == 200
    assert replay.get_json()["data"] == {
        **changed.get_json()["data"],
        "idempotent": True,
    }
    with database.new_session() as session:
        intent = session.get(TenantSensitiveActionIntent, action_id)
        challenge_row = session.get(SmsChallenge, challenge_id)
        sensitive_events = tuple(
            session.scalars(
                sa.select(TenantAuthSecurityEvent)
                .where(TenantAuthSecurityEvent.intent_id == action_id)
                .order_by(TenantAuthSecurityEvent.event_type)
            )
        )
        assert intent.status == "succeeded"
        assert challenge_row.verification_state == "consumed"
        assert {row.event_type for row in sensitive_events} == {
            "sensitive_action_committed",
            "sensitive_challenge_rejected",
            "sensitive_challenge_requested",
            "sensitive_challenge_verified",
        }
        assert all(row.challenge_id == challenge_id for row in sensitive_events)
        assert all(TARGET_PHONE not in repr(row.__dict__) for row in sensitive_events)


def test_operator_promotion_uses_grant_admin_intent(harness):
    _app, database, provider, issued, client = harness
    with database.transaction() as session:
        tenant_id = session.scalar(sa.select(Tenant.id))
        operator = User(
            phone_e164=TARGET_PHONE,
            phone_normalization_version=PHONE_NORMALIZATION_VERSION,
            phone_metadata_version=CN_MOBILE_METADATA_VERSION,
            status="active",
        )
        session.add(operator)
        session.flush()
        membership = TenantMembership(
            tenant_id=tenant_id,
            user_id=operator.id,
            role_key="operator",
            status="active",
            source_type="invitation",
        )
        session.add(membership)
        session.flush()
        membership_id = membership.id
    action_id = str(uuid4())
    payload = {
        "action": "change_role",
        "action_id": action_id,
        "expected_row_version": 1,
        "target_role": "admin",
    }

    challenge = client.post(
        f"/api/v1/members/{membership_id}/mutations/challenge",
        json=payload,
        headers=_headers(issued),
    )
    changed = client.post(
        f"/api/v1/members/{membership_id}/mutations/confirm",
        json={
            **payload,
            "challenge_id": challenge.get_json()["data"]["challenge_id"],
            "code": provider.codes[-1],
        },
        headers=_headers(issued),
    )

    assert challenge.status_code == 202
    assert changed.status_code == 200
    assert changed.get_json()["data"]["role"] == "admin"
    with database.new_session() as session:
        assert session.get(TenantMembership, membership_id).role_key == "admin"
        assert session.get(TenantSensitiveActionIntent, action_id).purpose == (
            "grant_admin"
        )
