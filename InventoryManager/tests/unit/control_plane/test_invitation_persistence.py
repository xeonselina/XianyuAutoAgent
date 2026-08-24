from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa

from inventory_control import ControlBase
from inventory_control.crypto.root_key import RootKey
from inventory_control.invitations import (
    AdminInvitationPermissionProof,
    INVITATION_DEFAULT_LIFETIME,
    InvitationChallengeSubmission,
    InvitationConflictError,
    InvitationCredentialError,
    InvitationJoinGateFacts,
    InvitationPersistenceService,
    InvitationRole,
    InvitationSeatLimitError,
    InvitationStaleRevisionError,
    InvitationToken,
    InvitationTransactionError,
    accept_invitation_challenge_context,
    admin_invitation_challenge_context,
)
from inventory_control.invitations import persistence as persistence_module
from inventory_control.models.foundation import Tenant
from inventory_control.models.identity import (
    TenantMembership,
    TenantUserSession,
    User,
)
from inventory_control.models.invitations import TenantInvitation
from inventory_control.models.sms import SmsChallenge
from inventory_control.models.subscriptions import MemberSeatGuard
from inventory_control.sms import (
    CanonicalSmsPhone,
    SmsChallengeService,
    SmsDeliveryOutcome,
    SmsPolicy,
    TrustedSourceBucket,
)
from tests.support.test_database import (
    clear_guarded_mysql_test_rows,
    guarded_mysql_control_database,
)


NOW = datetime(2026, 8, 22, 12, 0, 0, 654321, tzinfo=timezone.utc)
TENANT_A = UUID("41000000-0000-4000-8000-000000000001")
TENANT_B = UUID("41000000-0000-4000-8000-000000000002")
USER = UUID("41000000-0000-4000-8000-000000000003")
INVITATION_A = UUID("41000000-0000-4000-8000-000000000004")
INVITATION_B = UUID("41000000-0000-4000-8000-000000000005")
MEMBERSHIP = UUID("41000000-0000-4000-8000-000000000006")
PHONE = "+8613812345678"
ACTOR_PHONE = "+8613700000000"
ACTOR_SESSION = UUID("41000000-0000-4000-8000-000000000007")
ACTOR_USER = UUID("41000000-0000-4000-8000-000000000008")
TOKEN_A = InvitationToken("A" * 43)
TOKEN_B = InvitationToken("B" * 43)
TOKEN_C = InvitationToken("C" * 43)
ROOT_KEY = RootKey(version=1, material=b"k" * 32)


@dataclass
class GateReader:
    calls: list[str]

    def __call__(self, session, *, tenant, database_now):
        del session, database_now
        self.calls.append(tenant.id)
        return InvitationJoinGateFacts(
            tenant_uuid=UUID(tenant.id),
            access_version=tenant.access_version,
            join_allowed=tenant.status == "active",
        )


@pytest.fixture(scope="module")
def database_schema():
    with guarded_mysql_control_database(ControlBase.metadata) as database:
        yield database


@pytest.fixture
def database(database_schema):
    clear_guarded_mysql_test_rows(database_schema.engine, ControlBase.metadata)
    value = database_schema
    with value.transaction() as session:
        for tenant_id in (TENANT_A, TENANT_B):
            session.add(
                Tenant(
                    id=str(tenant_id),
                    name=f"Tenant {tenant_id}",
                    status="active",
                    access_version=1,
                    row_version=1,
                    created_at=NOW - timedelta(days=1),
                    updated_at=NOW - timedelta(days=1),
                )
            )
            session.add(
                MemberSeatGuard(
                    tenant_id=str(tenant_id),
                    quota_key="member_seats",
                    row_version=1,
                    created_at=NOW - timedelta(days=1),
                    updated_at=NOW - timedelta(days=1),
                )
            )
        session.add(
            User(
                id=str(ACTOR_USER),
                phone_e164=ACTOR_PHONE,
                phone_normalization_version=1,
                phone_metadata_version="cn-mobile-v1-2026-07",
                phone_verified_at=NOW - timedelta(days=1),
                status="active",
                auth_version=1,
                created_at=NOW - timedelta(days=1),
                updated_at=NOW - timedelta(days=1),
            )
        )
        session.flush()
        session.add(
            TenantUserSession(
                id=str(ACTOR_SESSION),
                user_id=str(ACTOR_USER),
                token_digest_sha256=b"a" * 32,
                csrf_digest_sha256=b"b" * 32,
                auth_version_at_issue=1,
                tenant_access_version_at_issue=1,
                policy_version=1,
                csrf_generation=1,
                idle_timeout_seconds=3600,
                created_at=NOW - timedelta(minutes=1),
                last_seen_at=NOW - timedelta(minutes=1),
                idle_expires_at=NOW + timedelta(hours=1),
                absolute_expires_at=NOW + timedelta(hours=8),
            )
        )
    return value


@pytest.fixture
def gate():
    return GateReader([])


@pytest.fixture
def sms():
    return SmsChallengeService(code_generator=lambda: "123456")


@pytest.fixture
def service(gate, sms):
    return InvitationPersistenceService(
        join_gate_current_read=gate,
        sms_challenge_service=sms,
        database_clock=lambda session: NOW,
    )


def _create(
    database,
    service,
    *,
    tenant=TENANT_A,
    invitation=INVITATION_A,
    user=USER,
    phone=PHONE,
    token=TOKEN_A,
    expected=None,
    role=InvitationRole.OPERATOR,
):
    with database.transaction() as session:
        return service.create_or_resend(
            session,
            tenant_uuid=tenant,
            raw_phone=phone,
            role=role,
            proposed_token=token,
            proposed_invitation_uuid=invitation,
            proposed_user_uuid=user,
            expected_tenant_access_version=1,
            expected_invitation_row_version=expected,
        )


def _issue_admin_challenge(database, sms):
    actor_phone = CanonicalSmsPhone.from_input(ACTOR_PHONE)
    with database.transaction() as session:
        prepared = sms.prepare_delivery(
            session,
            context=admin_invitation_challenge_context(
                actor_phone=actor_phone,
                target_phone=CanonicalSmsPhone.from_input(PHONE),
                tenant_uuid=TENANT_A,
                actor_session_uuid=ACTOR_SESSION,
                expected_tenant_access_version=1,
            ),
            trusted_source=TrustedSourceBucket.unknown(),
            root_key=ROOT_KEY,
            policy=SmsPolicy(),
            now=NOW,
        )
    with database.transaction() as session:
        sms.record_delivery(
            session,
            challenge_id=prepared.challenge_id,
            outcome=SmsDeliveryOutcome.SENT,
            now=NOW,
        )
    return InvitationChallengeSubmission(
        challenge_uuid=UUID(prepared.challenge_id),
        plaintext_code="123456",
        root_key=ROOT_KEY,
        actor_session_uuid=ACTOR_SESSION,
    ), actor_phone


def test_admin_invitation_challenge_is_sent_to_actor_not_target(
    database, service, sms
):
    challenge, actor_phone = _issue_admin_challenge(database, sms)
    with database.transaction() as session:
        result = service.create_or_resend(
            session,
            tenant_uuid=TENANT_A,
            raw_phone=PHONE,
            role=InvitationRole.ADMIN,
            proposed_token=TOKEN_A,
            proposed_invitation_uuid=INVITATION_A,
            proposed_user_uuid=USER,
            expected_tenant_access_version=1,
            expected_invitation_row_version=None,
            admin_challenge=challenge,
            admin_actor_phone=actor_phone,
        )

    assert result.role is InvitationRole.ADMIN
    with database.new_session() as session:
        row = session.get(SmsChallenge, str(challenge.challenge_uuid))
        assert row.canonical_phone_e164 == ACTOR_PHONE
        assert row.verification_state == "consumed"


def test_admin_invitation_rejects_target_phone_challenge(
    database, service, sms
):
    target_phone = CanonicalSmsPhone.from_input(PHONE)
    with database.transaction() as session:
        prepared = sms.prepare_delivery(
            session,
            context=admin_invitation_challenge_context(
                actor_phone=target_phone,
                target_phone=target_phone,
                tenant_uuid=TENANT_A,
                actor_session_uuid=ACTOR_SESSION,
                expected_tenant_access_version=1,
            ),
            trusted_source=TrustedSourceBucket.unknown(),
            root_key=ROOT_KEY,
            policy=SmsPolicy(),
            now=NOW,
        )
    with database.transaction() as session:
        sms.record_delivery(
            session,
            challenge_id=prepared.challenge_id,
            outcome=SmsDeliveryOutcome.SENT,
            now=NOW,
        )
    submission = InvitationChallengeSubmission(
        challenge_uuid=UUID(prepared.challenge_id),
        plaintext_code="123456",
        root_key=ROOT_KEY,
        actor_session_uuid=ACTOR_SESSION,
    )
    with database.transaction() as session:
        with pytest.raises(InvitationCredentialError):
            service.create_or_resend(
                session,
                tenant_uuid=TENANT_A,
                raw_phone=PHONE,
                role=InvitationRole.ADMIN,
                proposed_token=TOKEN_A,
                proposed_invitation_uuid=INVITATION_A,
                proposed_user_uuid=USER,
                expected_tenant_access_version=1,
                expected_invitation_row_version=None,
                admin_challenge=submission,
                admin_actor_phone=CanonicalSmsPhone.from_input(ACTOR_PHONE),
            )


def test_admin_invitation_accepts_only_exact_internal_d48_proof(
    database, service
):
    proof = AdminInvitationPermissionProof(
        tenant_uuid=TENANT_A,
        actor_user_uuid=USER,
        actor_session_uuid=ACTOR_SESSION,
        invitation_uuid=INVITATION_A,
        target_phone_e164=PHONE,
        expected_tenant_access_version=1,
    )
    with database.transaction() as session:
        result = service.create_or_resend(
            session,
            tenant_uuid=TENANT_A,
            raw_phone=PHONE,
            role=InvitationRole.ADMIN,
            proposed_token=TOKEN_A,
            proposed_invitation_uuid=INVITATION_A,
            proposed_user_uuid=USER,
            expected_tenant_access_version=1,
            expected_invitation_row_version=None,
            admin_authorizer=lambda _session, database_now: proof,
        )

    assert result.role is InvitationRole.ADMIN


def test_admin_invitation_rejects_d48_proof_for_another_target(
    database, service
):
    rebound = AdminInvitationPermissionProof(
        tenant_uuid=TENANT_A,
        actor_user_uuid=USER,
        actor_session_uuid=ACTOR_SESSION,
        invitation_uuid=INVITATION_B,
        target_phone_e164=PHONE,
        expected_tenant_access_version=1,
    )
    with pytest.raises(InvitationCredentialError):
        with database.transaction() as session:
            service.create_or_resend(
                session,
                tenant_uuid=TENANT_A,
                raw_phone=PHONE,
                role=InvitationRole.ADMIN,
                proposed_token=TOKEN_A,
                proposed_invitation_uuid=INVITATION_A,
                proposed_user_uuid=USER,
                expected_tenant_access_version=1,
                expected_invitation_row_version=None,
                admin_authorizer=lambda _session, database_now: rebound,
            )


def _issue_accept_challenge(
    database,
    sms,
    *,
    invitation_id=INVITATION_A,
    code="123456",
):
    sms._code_generator = lambda: code
    with database.transaction() as session:
        invitation = session.get(TenantInvitation, str(invitation_id))
        user = session.scalar(
            sa.select(User).where(User.phone_e164 == invitation.phone_e164)
        )
        context = accept_invitation_challenge_context(
            phone=CanonicalSmsPhone(
                e164=user.phone_e164,
                normalization_version=user.phone_normalization_version,
                metadata_version=user.phone_metadata_version,
            ),
            user_uuid=UUID(user.id),
            tenant_uuid=UUID(invitation.tenant_id),
            invitation_uuid=UUID(invitation.id),
            token_generation=invitation.token_generation,
            invitation_row_version=invitation.row_version,
        )
        prepared = sms.prepare_delivery(
            session,
            context=context,
            trusted_source=TrustedSourceBucket.unknown(),
            root_key=ROOT_KEY,
            policy=SmsPolicy(),
            now=NOW - timedelta(minutes=1),
        )
    with database.transaction() as session:
        sms.record_delivery(
            session,
            challenge_id=prepared.challenge_id,
            outcome=SmsDeliveryOutcome.SENT,
            now=NOW - timedelta(seconds=30),
        )
    return InvitationChallengeSubmission(
        challenge_uuid=UUID(prepared.challenge_id),
        plaintext_code=code,
        root_key=ROOT_KEY,
    )


def _accept(
    database,
    service,
    challenge,
    *,
    invitation=INVITATION_A,
    token=TOKEN_A.value,
    generation=1,
    expected=1,
    membership=MEMBERSHIP,
):
    with database.transaction() as session:
        return service.accept(
            session,
            invitation_uuid=invitation,
            submitted_token=token,
            submitted_generation=generation,
            expected_invitation_row_version=expected,
            expected_winning_tenant_access_version=1,
            proposed_membership_uuid=membership,
            challenge=challenge,
        )


def test_initial_create_is_seven_days_and_exact_replay_stores_only_digest(
    database, service
):
    first = _create(database, service)
    retry = _create(database, service)

    assert first.created is True
    assert first.token_generation == 1
    assert first.expires_at - NOW == INVITATION_DEFAULT_LIFETIME
    assert first.expires_at.microsecond == 654321
    assert retry.idempotent is True
    assert retry.invitation_uuid == first.invitation_uuid
    with database.new_session() as session:
        row = session.get(TenantInvitation, str(INVITATION_A))
        assert row.token_hash == TOKEN_A.digest_sha256
        assert TOKEN_A.value.encode() not in bytes(row.token_hash)
        assert session.scalar(
            sa.select(sa.func.count()).select_from(TenantInvitation)
        ) == 1


def test_resend_rotates_generation_without_a_second_reservation_and_blocks_aba(
    database, service
):
    _create(database, service)
    rotated = _create(database, service, token=TOKEN_B, expected=1)
    retry = _create(database, service, token=TOKEN_B, expected=1)

    assert rotated.rotated is True
    assert rotated.token_generation == 2
    assert rotated.expires_at == NOW + INVITATION_DEFAULT_LIFETIME
    assert retry.idempotent is True
    with pytest.raises(InvitationStaleRevisionError):
        _create(database, service, token=TOKEN_A, expected=1)
    with pytest.raises(InvitationStaleRevisionError):
        _create(
            database,
            service,
            invitation=UUID("41000000-0000-4000-8000-000000000099"),
            token=TOKEN_C,
        )
    with database.new_session() as session:
        assert session.scalar(
            sa.select(sa.func.count())
            .select_from(TenantInvitation)
            .where(TenantInvitation.status == "pending")
        ) == 1


def test_resend_at_full_capacity_does_not_allocate_another_seat(database, service):
    _create(database, service)
    with database.transaction() as session:
        for index in range(9):
            user = User(
                id=f"42000000-0000-4000-8000-{index:012d}",
                phone_e164=f"+86139{index:08d}",
                phone_normalization_version=1,
                phone_metadata_version="cn-mobile-v1",
                phone_verified_at=NOW,
                status="active",
            )
            session.add(user)
            session.add(
                TenantMembership(
                    id=f"43000000-0000-4000-8000-{index:012d}",
                    tenant_id=str(TENANT_A),
                    user_id=user.id,
                    role_key="operator",
                    status="active",
                    source_type="migration",
                    row_version=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )

    assert _create(database, service, token=TOKEN_B, expected=1).rotated
    with pytest.raises(InvitationSeatLimitError):
        _create(
            database,
            service,
            invitation=UUID("44000000-0000-4000-8000-000000000001"),
            user=UUID("44000000-0000-4000-8000-000000000002"),
            phone="+8613712345678",
            token=TOKEN_C,
        )


def test_revoke_and_due_expiry_release_realtime_reservations(database, service):
    _create(database, service)
    with database.transaction() as session:
        result = service.revoke(
            session,
            invitation_uuid=INVITATION_A,
            expected_invitation_row_version=1,
        )
    assert result.status == "revoked"
    with database.transaction() as session:
        retry = service.revoke(
            session,
            invitation_uuid=INVITATION_A,
            expected_invitation_row_version=1,
        )
    assert retry.idempotent is True

    created = _create(
        database,
        service,
        invitation=INVITATION_B,
        token=TOKEN_B,
    )
    with database.transaction() as session:
        row = session.get(TenantInvitation, str(created.invitation_uuid))
        row.expires_at = NOW - timedelta(microseconds=1)
    with database.transaction() as session:
        expired = service.expire(
            session,
            invitation_uuid=created.invitation_uuid,
            expected_invitation_row_version=1,
        )
    assert expired.status == "expired"
    with database.new_session() as session:
        rows = list(session.scalars(sa.select(TenantInvitation)))
        assert all(row.user_id is None for row in rows)


def test_create_replaces_a_due_pending_row_in_one_guarded_transaction(
    database, service
):
    _create(database, service)
    with database.transaction() as session:
        row = session.get(TenantInvitation, str(INVITATION_A))
        row.expires_at = NOW - timedelta(seconds=1)

    replacement = _create(
        database,
        service,
        invitation=INVITATION_B,
        token=TOKEN_B,
        expected=1,
    )
    assert replacement.created is True
    with database.new_session() as session:
        old = session.get(TenantInvitation, str(INVITATION_A))
        new = session.get(TenantInvitation, str(INVITATION_B))
        assert (old.status, old.user_id) == ("expired", None)
        assert (new.status, new.user_id) == ("pending", str(USER))


def test_resend_makes_old_token_and_generation_immediately_unusable(
    database, service, sms
):
    _create(database, service)
    _create(database, service, token=TOKEN_B, expected=1)
    challenge = _issue_accept_challenge(database, sms)

    with pytest.raises(InvitationCredentialError):
        _accept(
            database,
            service,
            challenge,
            token=TOKEN_A.value,
            generation=1,
            expected=2,
        )
    accepted = _accept(
        database,
        service,
        challenge,
        token=TOKEN_B.value,
        generation=2,
        expected=2,
    )
    assert accepted.created is True


def test_acceptance_first_membership_wins_and_supersedes_other_tenant(
    database, service, sms, gate
):
    _create(database, service)
    _create(
        database,
        service,
        tenant=TENANT_B,
        invitation=INVITATION_B,
        token=TOKEN_B,
    )
    # Losing-tenant lifecycle state is not a gate for monotonic supersede.
    with database.transaction() as session:
        losing = session.get(Tenant, str(TENANT_B))
        losing.status = "suspended"
    gate.calls.clear()
    challenge = _issue_accept_challenge(database, sms)
    result = _accept(database, service, challenge)

    assert result.created is True
    assert result.superseded_count == 1
    assert gate.calls == [str(TENANT_A), str(TENANT_A)]
    with database.new_session() as session:
        winner = session.get(TenantInvitation, str(INVITATION_A))
        loser = session.get(TenantInvitation, str(INVITATION_B))
        membership = session.get(TenantMembership, str(MEMBERSHIP))
        user = session.get(User, str(USER))
        assert (winner.status, winner.user_id, winner.accepted_at is not None) == (
            "accepted",
            None,
            True,
        )
        assert (
            loser.status,
            loser.user_id,
            loser.terminal_reason_code,
        ) == ("superseded", None, "membership_claimed_elsewhere")
        assert membership.source_type == "invitation"
        assert membership.source_uuid == str(INVITATION_A)
        assert user.status == "active"
        assert user.phone_verified_at is not None


def test_acceptance_exact_replay_uses_membership_source_and_loser_cannot_win(
    database, service, sms
):
    _create(database, service)
    _create(
        database,
        service,
        tenant=TENANT_B,
        invitation=INVITATION_B,
        token=TOKEN_B,
    )
    challenge = _issue_accept_challenge(database, sms)
    first = _accept(database, service, challenge)
    retry = _accept(database, service, challenge)
    assert first.created is True
    assert retry.idempotent is True

    with pytest.raises(InvitationCredentialError):
        _accept(database, service, challenge, token=TOKEN_C.value)

    wrong_replay_challenge = InvitationChallengeSubmission(
        challenge_uuid=UUID("45000000-0000-4000-8000-000000000009"),
        plaintext_code="123456",
        root_key=ROOT_KEY,
    )
    with pytest.raises(InvitationConflictError):
        _accept(database, service, wrong_replay_challenge)

    losing_challenge = InvitationChallengeSubmission(
        challenge_uuid=UUID("45000000-0000-4000-8000-000000000001"),
        plaintext_code="123456",
        root_key=ROOT_KEY,
    )
    with pytest.raises(InvitationCredentialError):
        _accept(
            database,
            service,
            losing_challenge,
            invitation=INVITATION_B,
            token=TOKEN_B.value,
            membership=UUID("45000000-0000-4000-8000-000000000002"),
        )
    with database.new_session() as session:
        assert session.scalar(
            sa.select(sa.func.count())
            .select_from(TenantMembership)
            .where(TenantMembership.status != "released")
        ) == 1


def test_wrong_otp_can_commit_attempt_counter_without_invitation_mutation(
    database, service, sms
):
    _create(database, service)
    challenge = _issue_accept_challenge(database, sms)
    wrong = InvitationChallengeSubmission(
        challenge_uuid=challenge.challenge_uuid,
        plaintext_code="000000",
        root_key=ROOT_KEY,
    )
    with database.transaction() as session:
        with pytest.raises(InvitationCredentialError):
            service.accept(
                session,
                invitation_uuid=INVITATION_A,
                submitted_token=TOKEN_A.value,
                submitted_generation=1,
                expected_invitation_row_version=1,
                expected_winning_tenant_access_version=1,
                proposed_membership_uuid=MEMBERSHIP,
                challenge=wrong,
            )
    with database.new_session() as session:
        invitation = session.get(TenantInvitation, str(INVITATION_A))
        challenge_row = session.get(SmsChallenge, str(challenge.challenge_uuid))
        assert invitation.status == "pending"
        assert invitation.row_version == 1
        assert challenge_row.wrong_attempt_count == 1
        assert session.get(TenantMembership, str(MEMBERSHIP)) is None


def test_database_clock_runs_after_d47_locks_and_preserves_microseconds(
    database, gate, sms
):
    trace: list[str] = []

    @sa.event.listens_for(database.engine, "before_cursor_execute")
    def record_sql(connection, cursor, statement, parameters, context, executemany):
        del connection, cursor, parameters, context, executemany
        normalized = statement.lower()
        for table in (
            "users",
            "tenant_invitations",
            "tenants",
            "tenant_quota_guards",
            "sms_challenges",
            "tenant_memberships",
        ):
            if normalized.lstrip().startswith("select") and table in normalized:
                trace.append(table)

    def clock(session):
        del session
        trace.append("clock")
        return NOW

    service = InvitationPersistenceService(
        join_gate_current_read=gate,
        sms_challenge_service=sms,
        database_clock=clock,
    )
    result = _create(database, service)
    assert result.expires_at.microsecond == NOW.microsecond
    clock_index = trace.index("clock")
    assert trace.index("users") < trace.index("tenant_invitations")
    assert trace.index("tenant_invitations") < trace.index("tenants")
    assert trace.index("tenants") < trace.index("tenant_quota_guards")
    assert trace.index("tenant_quota_guards") < trace.index("tenant_memberships")
    assert trace.index("tenant_memberships") < clock_index


def test_acceptance_rechecks_expiry_after_gate_lock_wait(database, gate, sms):
    base = InvitationPersistenceService(
        join_gate_current_read=gate,
        sms_challenge_service=sms,
        database_clock=lambda session: NOW,
    )
    _create(database, base)
    challenge = _issue_accept_challenge(database, sms)
    times = iter(
        (
            NOW + INVITATION_DEFAULT_LIFETIME - timedelta(microseconds=1),
            NOW + INVITATION_DEFAULT_LIFETIME + timedelta(microseconds=1),
        )
    )
    waited = InvitationPersistenceService(
        join_gate_current_read=gate,
        sms_challenge_service=sms,
        database_clock=lambda session: next(times),
    )
    with pytest.raises(InvitationCredentialError):
        _accept(database, waited, challenge)
    with database.new_session() as session:
        assert session.get(TenantInvitation, str(INVITATION_A)).status == "pending"
        assert (
            session.get(SmsChallenge, str(challenge.challenge_uuid)).verification_state
            == "active"
        )


def test_acceptance_executes_the_shared_d47_lock_order(database, gate, sms):
    base = InvitationPersistenceService(
        join_gate_current_read=gate,
        sms_challenge_service=sms,
        database_clock=lambda session: NOW,
    )
    _create(database, base)
    _create(
        database,
        base,
        tenant=TENANT_B,
        invitation=INVITATION_B,
        token=TOKEN_B,
    )
    challenge = _issue_accept_challenge(database, sms)
    trace: list[str] = []

    class TracedInvitationService(InvitationPersistenceService):
        def _lock_user_by_phone(self, session, phone):
            trace.append("user")
            return super()._lock_user_by_phone(session, phone)

        def _lock_phone_invitations(self, session, phone):
            trace.append("invitations")
            rows = super()._lock_phone_invitations(session, phone)
            assert [row.id for row in rows] == sorted(row.id for row in rows)
            return rows

        def _lock_tenants(self, session, tenant_ids):
            trace.append("tenants")
            assert tenant_ids == tuple(sorted(tenant_ids))
            return super()._lock_tenants(session, tenant_ids)

        def _lock_guards(self, session, tenant_ids):
            trace.append("guards")
            assert tenant_ids == tuple(sorted(tenant_ids))
            return super()._lock_guards(session, tenant_ids)

        def _lock_challenges(self, session, **kwargs):
            trace.append("challenge")
            return super()._lock_challenges(session, **kwargs)

        def _lock_user_memberships(self, session, user_id):
            trace.append("membership")
            return super()._lock_user_memberships(session, user_id)

        def _now(self, session):
            trace.append("clock")
            return super()._now(session)

    traced = TracedInvitationService(
        join_gate_current_read=gate,
        sms_challenge_service=sms,
        database_clock=lambda session: NOW,
    )
    _accept(database, traced, challenge)
    assert trace == [
        "user",
        "invitations",
        "tenants",
        "guards",
        "challenge",
        "membership",
        "clock",
        "clock",
    ]


@pytest.mark.parametrize("dialect_name", ["mysql", "mariadb"])
def test_mysql_family_clock_uses_microsecond_utc_server_time(dialect_name):
    statement = persistence_module._database_utc_now_statement(dialect_name)
    assert str(statement) == "SELECT UTC_TIMESTAMP(6)"


def test_service_requires_explicit_clean_caller_transaction(database, service):
    session = database.new_session()
    try:
        with pytest.raises(InvitationTransactionError):
            service.create_or_resend(
                session,
                tenant_uuid=TENANT_A,
                raw_phone=PHONE,
                role=InvitationRole.OPERATOR,
                proposed_token=TOKEN_A,
                proposed_invitation_uuid=INVITATION_A,
                proposed_user_uuid=USER,
                expected_tenant_access_version=1,
                expected_invitation_row_version=None,
            )
    finally:
        session.close()


def test_admin_creation_fails_closed_without_action_challenge(database, service):
    with pytest.raises(InvitationCredentialError):
        _create(database, service, role=InvitationRole.ADMIN)
    with database.new_session() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(TenantInvitation)
        ) == 0
