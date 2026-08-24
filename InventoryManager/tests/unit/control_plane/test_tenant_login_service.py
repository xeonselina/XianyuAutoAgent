from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from inventory_control import (
    SmsChallenge,
    Tenant,
    TenantAuthSecurityEvent,
    TenantMembership,
    TenantUserSession,
    User,
)
from inventory_control.crypto import RootKey
from inventory_control.domain import EffectiveTenantGate, TenantGateDecision
from inventory_control.identity import (
    CN_MOBILE_METADATA_VERSION,
    PHONE_NORMALIZATION_VERSION,
    SessionService,
    TenantBrowserSessionPolicy,
    TenantLoginService,
    build_tenant_login_sms_context,
)
from inventory_control.sms import (
    CanonicalSmsPhone,
    SmsChallengeService,
    SmsDeliveryOutcome,
    SmsPolicy,
    TrustedSourceBucket,
)

NOW = datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc)
ROOT_KEY = RootKey(version=3, material=bytes(range(32)))
SESSION_POLICY = TenantBrowserSessionPolicy(
    version=7,
    idle_timeout=timedelta(minutes=45),
    absolute_timeout=timedelta(hours=12),
)


@pytest.fixture
def database(mysql_control_database):
    return mysql_control_database


@pytest.fixture
def identity(database):
    with database.transaction() as session:
        tenant = Tenant(status="active", access_version=5)
        user = User(
            phone_e164="+8613800138001",
            phone_normalization_version=PHONE_NORMALIZATION_VERSION,
            phone_metadata_version=CN_MOBILE_METADATA_VERSION,
            phone_verified_at=None,
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
        return tenant.id, user.id


def _gate(_session, _tenant, _now):
    return TenantGateDecision(
        gate=EffectiveTenantGate.ACTIVE,
        error_code=None,
    )


def _services():
    sms = SmsChallengeService(code_generator=lambda: "123456")
    sessions = SessionService(gate_current_read=_gate)
    return (
        sms,
        sessions,
        TenantLoginService(
            sms_challenge_service=sms,
            session_service=sessions,
        ),
    )


def _prepare_login(database, sms, *, tenant_id, user_id, now=NOW):
    phone = CanonicalSmsPhone.from_input("13800138001")
    context = build_tenant_login_sms_context(
        phone=phone,
        user_id=user_id,
        tenant_id=tenant_id,
        user_auth_version=1,
    )
    with database.transaction() as session:
        prepared = sms.prepare_delivery(
            session,
            context=context,
            trusted_source=TrustedSourceBucket.unknown(),
            root_key=ROOT_KEY,
            policy=SmsPolicy(),
            now=now,
        )
    with database.transaction() as session:
        sms.record_delivery(
            session,
            challenge_id=prepared.challenge_id,
            outcome=SmsDeliveryOutcome.SENT,
            now=now,
        )
    return phone, prepared.challenge_id


def test_login_consumes_challenge_verifies_migrated_phone_and_anchors_session(
    database,
    identity,
) -> None:
    tenant_id, user_id = identity
    sms, _sessions, login = _services()
    phone, challenge_id = _prepare_login(
        database,
        sms,
        tenant_id=tenant_id,
        user_id=user_id,
    )

    with database.transaction() as session:
        result = login.complete(
            session,
            challenge_id=challenge_id,
            phone=phone,
            plaintext_code="123456",
            root_key=ROOT_KEY,
            session_policy=SESSION_POLICY,
            device_name="Office browser",
            now=NOW + timedelta(seconds=1),
        )

    assert result.accepted is True
    assert result.issued_session is not None
    assert result.issued_session.auth.effective_gate is EffectiveTenantGate.ACTIVE
    assert result.issued_session.auth.idle_expires_at == (
        NOW + timedelta(seconds=1, minutes=45)
    )
    with database.new_session() as session:
        challenge = session.get(SmsChallenge, challenge_id)
        row = session.get(
            TenantUserSession,
            result.issued_session.auth.session_id,
        )
        assert challenge.verification_state == "consumed"
        assert row.created_from_challenge_id == challenge_id
        assert row.policy_version == SESSION_POLICY.version
        assert session.get(User, user_id).phone_verified_at is not None
        event = session.scalars(select(TenantAuthSecurityEvent)).one()
        assert event.tenant_id == tenant_id
        assert event.user_id == user_id
        assert event.actor_session_id == row.id
        assert event.target_session_id == row.id
        assert event.event_type == "login_session_created"
        assert event.reason_code == "otp_login"


def test_same_login_challenge_cannot_issue_a_second_session(
    database,
    identity,
) -> None:
    tenant_id, user_id = identity
    sms, _sessions, login = _services()
    phone, challenge_id = _prepare_login(
        database,
        sms,
        tenant_id=tenant_id,
        user_id=user_id,
    )

    with database.transaction() as session:
        first = login.complete(
            session,
            challenge_id=challenge_id,
            phone=phone,
            plaintext_code="123456",
            root_key=ROOT_KEY,
            session_policy=SESSION_POLICY,
            now=NOW + timedelta(seconds=1),
        )
    with database.transaction() as session:
        replay = login.complete(
            session,
            challenge_id=challenge_id,
            phone=phone,
            plaintext_code="123456",
            root_key=ROOT_KEY,
            session_policy=SESSION_POLICY,
            now=NOW + timedelta(seconds=2),
        )

    assert first.accepted is True
    assert replay.accepted is False
    with database.new_session() as session:
        assert session.scalar(select(func.count(TenantUserSession.id))) == 1
        assert session.scalar(select(func.count(TenantAuthSecurityEvent.id))) == 1


def test_successful_login_rotates_only_same_user_presented_session(
    database,
    identity,
) -> None:
    tenant_id, user_id = identity
    sms, sessions, login = _services()
    with database.transaction() as session:
        old = sessions.issue(
            session,
            user_id=user_id,
            idle_timeout=timedelta(minutes=30),
            absolute_timeout=timedelta(hours=8),
            now=NOW,
        )
    phone, challenge_id = _prepare_login(
        database,
        sms,
        tenant_id=tenant_id,
        user_id=user_id,
        now=NOW + timedelta(minutes=1),
    )

    with database.transaction() as session:
        result = login.complete(
            session,
            challenge_id=challenge_id,
            phone=phone,
            plaintext_code="123456",
            root_key=ROOT_KEY,
            session_policy=SESSION_POLICY,
            presented_session_token=old.session_token,
            now=NOW + timedelta(minutes=1, seconds=1),
        )

    assert result.issued_session is not None
    with database.new_session() as session:
        old_row = session.get(TenantUserSession, old.auth.session_id)
        new_row = session.get(
            TenantUserSession,
            result.issued_session.auth.session_id,
        )
        assert old_row.revoked_reason_code == "login_replaced"
        assert old_row.replaced_by_session_id == new_row.id
        assert old_row.revoked_by_session_id == new_row.id
        assert new_row.rotated_from_session_id == old_row.id
        event = session.scalars(select(TenantAuthSecurityEvent)).one()
        assert event.actor_session_id == new_row.id
        assert event.target_session_id == old_row.id
        assert event.event_type == "login_session_rotated"
        assert event.reason_code == "login_replaced"


def test_wrong_code_commits_attempt_without_session_or_phone_verification(
    database,
    identity,
) -> None:
    tenant_id, user_id = identity
    sms, _sessions, login = _services()
    phone, challenge_id = _prepare_login(
        database,
        sms,
        tenant_id=tenant_id,
        user_id=user_id,
    )

    with database.transaction() as session:
        result = login.complete(
            session,
            challenge_id=challenge_id,
            phone=phone,
            plaintext_code="000000",
            root_key=ROOT_KEY,
            session_policy=SESSION_POLICY,
            now=NOW + timedelta(seconds=1),
        )

    assert result.accepted is False
    with database.new_session() as session:
        assert session.get(SmsChallenge, challenge_id).wrong_attempt_count == 1
        assert session.get(User, user_id).phone_verified_at is None
        assert session.scalar(select(func.count(TenantUserSession.id))) == 0
        assert session.scalar(select(func.count(TenantAuthSecurityEvent.id))) == 0
