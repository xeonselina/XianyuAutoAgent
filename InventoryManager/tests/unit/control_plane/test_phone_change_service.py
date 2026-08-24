from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa

from inventory_control import ControlBase, ControlDatabase
from inventory_control.action_payload import CanonicalActionPayload
from inventory_control.crypto import RootKey
from inventory_control.identity import (
    PhoneChangeAuthorizationProof,
    PhoneChangeConflictError,
    TenantPhoneChangeService,
)
from inventory_control.invitations import accept_invitation_challenge_context
from inventory_control.models import (
    MemberSeatGuard,
    SmsChallenge,
    Tenant,
    TenantInvitation,
    TenantMembership,
    TenantSensitiveActionIntent,
    TenantUserSession,
    User,
)
from inventory_control.sensitive_actions import (
    SensitiveActionContext,
    SensitiveActionIntentService,
)
from inventory_control.sms import (
    CanonicalSmsPhone,
    SmsChallengeService,
    SmsDeliveryOutcome,
    SmsPolicy,
    SmsPurpose,
    TrustedSourceBucket,
)


NOW = datetime(2026, 8, 23, 3, 15, tzinfo=timezone.utc)
ROOT_KEY = RootKey(version=2, material=b"p" * 32)
OLD_PHONE = CanonicalSmsPhone.from_input("13800138000")
NEW_PHONE = CanonicalSmsPhone.from_input("13900139000")
TENANT_A = UUID("73000000-0000-4000-8000-000000000001")
TENANT_B = UUID("73000000-0000-4000-8000-000000000002")
CURRENT_USER = UUID("73000000-0000-4000-8000-000000000003")
COORDINATOR = UUID("73000000-0000-4000-8000-000000000004")
MEMBERSHIP = UUID("73000000-0000-4000-8000-000000000005")
SESSION = UUID("73000000-0000-4000-8000-000000000006")
CHANGE = UUID("73000000-0000-4000-8000-000000000007")
INVITATION_A = UUID("73000000-0000-4000-8000-000000000008")
INVITATION_B = UUID("73000000-0000-4000-8000-000000000009")


@pytest.fixture
def database(mysql_control_database):
    with mysql_control_database.transaction() as session:
        for tenant_id in (TENANT_A, TENANT_B):
            session.add(
                Tenant(
                    id=str(tenant_id),
                    name=f"tenant-{tenant_id}",
                    status="active",
                    access_version=1,
                    row_version=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.add(
                MemberSeatGuard(
                    tenant_id=str(tenant_id),
                    quota_key="member_seats",
                    row_version=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        current = User(
            id=str(CURRENT_USER),
            phone_e164=OLD_PHONE.e164,
            phone_normalization_version=OLD_PHONE.normalization_version,
            phone_metadata_version=OLD_PHONE.metadata_version,
            phone_verified_at=NOW - timedelta(days=1),
            status="active",
            auth_version=1,
            created_at=NOW - timedelta(days=2),
            updated_at=NOW - timedelta(days=1),
        )
        coordinator = User(
            id=str(COORDINATOR),
            phone_e164=NEW_PHONE.e164,
            phone_normalization_version=NEW_PHONE.normalization_version,
            phone_metadata_version=NEW_PHONE.metadata_version,
            phone_verified_at=None,
            status="unverified",
            auth_version=1,
            created_at=NOW - timedelta(hours=1),
            updated_at=NOW - timedelta(hours=1),
        )
        session.add_all((current, coordinator))
        session.flush()
        session.add(
            TenantMembership(
                id=str(MEMBERSHIP),
                tenant_id=str(TENANT_A),
                user_id=str(CURRENT_USER),
                role_key="admin",
                status="active",
                source_type="registration",
                row_version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            TenantUserSession(
                id=str(SESSION),
                user_id=str(CURRENT_USER),
                token_digest_sha256=b"s" * 32,
                csrf_digest_sha256=b"c" * 32,
                auth_version_at_issue=1,
                tenant_access_version_at_issue=1,
                policy_version=1,
                csrf_generation=1,
                idle_timeout_seconds=3600,
                created_at=NOW,
                last_seen_at=NOW,
                idle_expires_at=NOW + timedelta(hours=1),
                absolute_expires_at=NOW + timedelta(hours=8),
            )
        )
        for invitation_id, tenant_id, token in (
            (INVITATION_A, TENANT_A, b"a"),
            (INVITATION_B, TENANT_B, b"b"),
        ):
            session.add(
                TenantInvitation(
                    id=str(invitation_id),
                    tenant_id=str(tenant_id),
                    user_id=str(COORDINATOR),
                    phone_e164=NEW_PHONE.e164,
                    phone_normalization_version=NEW_PHONE.normalization_version,
                    role_key="operator",
                    token_hash=hashlib.sha256(token).digest(),
                    token_generation=1,
                    status="pending",
                    expires_at=NOW + timedelta(days=7),
                    row_version=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
    return mysql_control_database


def _context() -> SensitiveActionContext:
    return SensitiveActionContext(
        intent_uuid=CHANGE,
        tenant_uuid=TENANT_A,
        actor_user_uuid=CURRENT_USER,
        actor_session_uuid=SESSION,
        purpose=SmsPurpose.PHONE_CHANGE_OLD,
        action_subtype="identity.phone_change",
        target_type="tenant_user",
        target_uuid=CURRENT_USER,
        expected_target_revision="auth:1",
        action_payload=CanonicalActionPayload.from_value(
            {
                "new_phone_e164": NEW_PHONE.e164,
                "old_phone_e164": OLD_PHONE.e164,
            }
        ),
        idempotency_key=f"phone-change:{CHANGE}",
    )


def _prepare_phone_change(database):
    codes = iter(("314159", "271828"))
    sms = SmsChallengeService(code_generator=lambda: next(codes))
    intents = SensitiveActionIntentService(sms_challenge_service=sms)
    with database.transaction() as session:
        prepared = intents.prepare_phone_change(
            session,
            context=_context(),
            old_phone=OLD_PHONE,
            new_phone=NEW_PHONE,
            trusted_source=TrustedSourceBucket.unknown(),
            root_key=ROOT_KEY,
            sms_policy=SmsPolicy(),
            database_now=NOW,
        )
    with database.transaction() as session:
        for challenge_id in (
            prepared.old_challenge_uuid,
            prepared.new_challenge_uuid,
        ):
            sms.record_delivery(
                session,
                challenge_id=str(challenge_id),
                outcome=SmsDeliveryOutcome.SENT,
                now=NOW + timedelta(seconds=1),
            )
    return intents, prepared


def _prepare_acceptance_challenge(database):
    sms = SmsChallengeService(code_generator=lambda: "123456")
    issued_at = NOW - timedelta(minutes=2)
    with database.transaction() as session:
        prepared = sms.prepare_delivery(
            session,
            context=accept_invitation_challenge_context(
                phone=NEW_PHONE,
                user_uuid=COORDINATOR,
                tenant_uuid=TENANT_A,
                invitation_uuid=INVITATION_A,
                token_generation=1,
                invitation_row_version=1,
            ),
            trusted_source=TrustedSourceBucket.unknown(),
            root_key=ROOT_KEY,
            policy=SmsPolicy(),
            now=issued_at,
        )
    with database.transaction() as session:
        sms.record_delivery(
            session,
            challenge_id=prepared.challenge_id,
            outcome=SmsDeliveryOutcome.SENT,
            now=issued_at + timedelta(seconds=1),
        )
    return prepared.challenge_id


def test_phone_change_claims_placeholder_and_monotonically_releases_invitations(
    database,
):
    acceptance_challenge_id = _prepare_acceptance_challenge(database)
    intents, prepared = _prepare_phone_change(database)
    service = TenantPhoneChangeService()

    with database.transaction() as session:
        scope = service.lock_scope(
            session,
            tenant_uuid=TENANT_A,
            current_user_uuid=CURRENT_USER,
            actor_session_uuid=SESSION,
            change_uuid=CHANGE,
            expected_auth_version=1,
            expected_tenant_access_version=1,
            old_phone=OLD_PHONE,
            new_phone=NEW_PHONE,
            old_challenge_uuid=prepared.old_challenge_uuid,
            new_challenge_uuid=prepared.new_challenge_uuid,
            database_now=NOW + timedelta(seconds=2),
        )
        authorized = intents.authorize_phone_change(
            session,
            context=_context(),
            old_phone=OLD_PHONE,
            new_phone=NEW_PHONE,
            old_challenge_uuid=prepared.old_challenge_uuid,
            old_plaintext_code="314159",
            new_challenge_uuid=prepared.new_challenge_uuid,
            new_plaintext_code="271828",
            root_key=ROOT_KEY,
            database_now=NOW + timedelta(seconds=2),
        )
        assert authorized.authorization is not None
        result = service.apply_locked(
            session,
            scope=scope,
            proof=PhoneChangeAuthorizationProof(
                tenant_uuid=TENANT_A,
                user_uuid=CURRENT_USER,
                actor_session_uuid=SESSION,
                change_uuid=CHANGE,
                old_challenge_uuid=prepared.old_challenge_uuid,
                new_challenge_uuid=prepared.new_challenge_uuid,
                expected_auth_version=1,
                old_phone_e164=OLD_PHONE.e164,
                new_phone_e164=NEW_PHONE.e164,
            ),
            new_phone=NEW_PHONE,
            database_now=NOW + timedelta(seconds=2),
        )
        intents.mark_succeeded(
            session,
            authorization=authorized.authorization,
            safe_result_code="phone_changed",
            database_now=NOW + timedelta(seconds=2),
        )

    assert result.user_uuid == CURRENT_USER
    assert result.auth_version == 2
    assert result.sessions_revoked == 1
    assert result.invitations_superseded == 2
    with database.new_session() as session:
        user = session.get(User, str(CURRENT_USER))
        assert user.phone_e164 == NEW_PHONE.e164
        assert user.phone_verified_at.replace(tzinfo=timezone.utc) == (
            NOW + timedelta(seconds=2)
        )
        assert session.get(User, str(COORDINATOR)) is None
        invitations = list(
            session.scalars(sa.select(TenantInvitation).order_by(TenantInvitation.id))
        )
        assert all(
            (row.status, row.user_id, row.terminal_reason_code)
            == ("superseded", None, "phone_claimed")
            for row in invitations
        )
        acceptance = session.get(SmsChallenge, acceptance_challenge_id)
        assert acceptance.verification_state == "invalidated"
        assert acceptance.user_id is None
        browser = session.get(TenantUserSession, str(SESSION))
        assert browser.revoked_reason_code == "phone_changed"
        intent = session.get(TenantSensitiveActionIntent, str(CHANGE))
        assert intent.status == "succeeded"


def test_issue_check_rejects_verified_or_historical_identity(database):
    service = TenantPhoneChangeService()
    with database.transaction() as session:
        candidate = session.get(User, str(COORDINATOR))
        candidate.phone_verified_at = NOW
        candidate.status = "active"

    with database.new_session() as session, pytest.raises(
        PhoneChangeConflictError
    ):
        service.ensure_candidate_available(
            session,
            current_user_uuid=CURRENT_USER,
            new_phone=NEW_PHONE,
        )
