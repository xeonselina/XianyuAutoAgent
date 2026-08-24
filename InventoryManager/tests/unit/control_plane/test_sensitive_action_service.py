from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from inventory_control import (
    ControlBase,
    ControlDatabase,
    SmsChallenge,
    Tenant,
    TenantSensitiveActionIntentChallenge,
    TenantSensitiveActionIntent,
    TenantUserSession,
    User,
)
from inventory_control.action_payload import CanonicalActionPayload
from inventory_control.crypto import RootKey
from inventory_control.identity import (
    CN_MOBILE_METADATA_VERSION,
    PHONE_NORMALIZATION_VERSION,
)
from inventory_control.sensitive_actions import (
    SensitiveActionConflictError,
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


NOW = datetime(2026, 8, 23, 2, 5, tzinfo=timezone.utc)
ROOT_KEY = RootKey(version=3, material=bytes(range(32)))
PHONE = CanonicalSmsPhone.from_input("13800138000")
NEW_PHONE = CanonicalSmsPhone.from_input("13900139000")
SOURCE = TrustedSourceBucket.from_trusted_ip("192.0.2.44")


@pytest.fixture
def database(mysql_control_database):
    return mysql_control_database


def _seed(database):
    with database.transaction() as session:
        tenant = Tenant(id=str(uuid4()), status="active")
        user = User(
            id=str(uuid4()),
            phone_e164=PHONE.e164,
            phone_normalization_version=PHONE_NORMALIZATION_VERSION,
            phone_metadata_version=CN_MOBILE_METADATA_VERSION,
            phone_verified_at=NOW,
            status="active",
            auth_version=1,
        )
        session.add_all([tenant, user])
        session.flush()
        actor_session = TenantUserSession(
            id=str(uuid4()),
            user_id=user.id,
            token_digest_sha256=b"a" * 32,
            csrf_digest_sha256=b"b" * 32,
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
        session.add(actor_session)
        session.flush()
        return {
            "tenant": UUID(tenant.id),
            "user": UUID(user.id),
            "session": UUID(actor_session.id),
            "target": uuid4(),
            "intent": uuid4(),
        }


def _context(ids) -> SensitiveActionContext:
    return SensitiveActionContext(
        intent_uuid=ids["intent"],
        tenant_uuid=ids["tenant"],
        actor_user_uuid=ids["user"],
        actor_session_uuid=ids["session"],
        purpose=SmsPurpose.GRANT_ADMIN,
        action_subtype="membership.change_role",
        target_type="tenant_membership",
        target_uuid=ids["target"],
        expected_target_revision="row:1",
        action_payload=CanonicalActionPayload.from_value(
            {"action": "change_role", "target_role": "admin"}
        ),
        idempotency_key="membership-admin:request-1",
    )


def _service() -> SensitiveActionIntentService:
    return SensitiveActionIntentService(
        sms_challenge_service=SmsChallengeService(
            code_generator=lambda: "042731"
        )
    )


def _phone_change_context(ids) -> SensitiveActionContext:
    return SensitiveActionContext(
        intent_uuid=ids["intent"],
        tenant_uuid=ids["tenant"],
        actor_user_uuid=ids["user"],
        actor_session_uuid=ids["session"],
        purpose=SmsPurpose.PHONE_CHANGE_OLD,
        action_subtype="user.change_phone",
        target_type="tenant_user",
        target_uuid=ids["user"],
        expected_target_revision="auth:1",
        action_payload=CanonicalActionPayload.from_value(
            {"new_phone_e164": NEW_PHONE.e164}
        ),
        idempotency_key=f"phone-change:{ids['intent']}",
    )


def _phone_change_service() -> SensitiveActionIntentService:
    codes = iter(("314159", "271828"))
    return SensitiveActionIntentService(
        sms_challenge_service=SmsChallengeService(
            code_generator=lambda: next(codes)
        )
    )


def _prepare(database, service, context):
    with database.transaction() as session:
        return service.prepare_primary(
            session,
            context=context,
            actor_phone=PHONE,
            trusted_source=SOURCE,
            root_key=ROOT_KEY,
            sms_policy=SmsPolicy(),
            database_now=NOW,
        )


def _deliver(database, challenge_uuid):
    with database.transaction() as session:
        SmsChallengeService().record_delivery(
            session,
            challenge_id=str(challenge_uuid),
            outcome=SmsDeliveryOutcome.SENT,
            now=NOW + timedelta(seconds=1),
        )


def test_prepare_persists_mac_only_and_exact_replay_has_no_second_delivery(
    database,
):
    ids = _seed(database)
    context = _context(ids)
    service = _service()

    first = _prepare(database, service, context)
    replay = _prepare(database, service, context)

    assert first.replayed is False
    assert first.delivery is not None
    assert replay.replayed is True
    assert replay.delivery is None
    assert replay.intent_uuid == first.intent_uuid
    assert replay.challenge_uuid == first.challenge_uuid
    with database.new_session() as session:
        row = session.get(TenantSensitiveActionIntent, str(ids["intent"]))
        assert bytes(row.request_context_mac_sha256) != (
            context.action_payload.digest_sha256
        )
        assert not hasattr(row, "payload")
        assert session.query(SmsChallenge).count() == 1


def test_idempotency_key_reuse_with_changed_payload_is_rejected(database):
    ids = _seed(database)
    context = _context(ids)
    service = _service()
    _prepare(database, service, context)

    changed = replace(
        context,
        action_payload=CanonicalActionPayload.from_value(
            {"action": "change_role", "target_role": "operator"}
        ),
    )
    with pytest.raises(SensitiveActionConflictError):
        _prepare(database, service, changed)


def test_wrong_code_commits_attempt_then_exact_code_authorizes_and_completes(
    database,
):
    ids = _seed(database)
    context = _context(ids)
    service = _service()
    prepared = _prepare(database, service, context)
    _deliver(database, prepared.challenge_uuid)

    with database.transaction() as session:
        rejected = service.authorize_primary(
            session,
            context=context,
            actor_phone=PHONE,
            challenge_uuid=prepared.challenge_uuid,
            plaintext_code="000000",
            root_key=ROOT_KEY,
            database_now=NOW + timedelta(seconds=2),
        )
        assert rejected.accepted is False

    with database.transaction() as session:
        accepted = service.authorize_primary(
            session,
            context=context,
            actor_phone=PHONE,
            challenge_uuid=prepared.challenge_uuid,
            plaintext_code="042731",
            root_key=ROOT_KEY,
            database_now=NOW + timedelta(seconds=3),
        )
        assert accepted.accepted is True
        assert accepted.authorization is not None
        service.mark_succeeded(
            session,
            authorization=accepted.authorization,
            safe_result_code="membership_changed",
            correlation_id=f"membership:{ids['target']}:row:2",
            database_now=NOW + timedelta(seconds=3),
        )

    with database.transaction() as session:
        replay = service.authorize_primary(
            session,
            context=context,
            actor_phone=PHONE,
            challenge_uuid=prepared.challenge_uuid,
            plaintext_code="not-reused",
            root_key=ROOT_KEY,
            database_now=NOW + timedelta(seconds=4),
        )
        assert replay.accepted is True
        assert replay.already_succeeded is True
        assert replay.authorization is None

    with database.new_session() as session:
        intent = session.get(TenantSensitiveActionIntent, str(ids["intent"]))
        challenge = session.get(SmsChallenge, str(prepared.challenge_uuid))
        assert intent.status == "succeeded"
        assert intent.safe_result_code == "membership_changed"
        assert intent.correlation_id == f"membership:{ids['target']}:row:2"
        assert challenge.verification_state == "consumed"
        assert challenge.wrong_attempt_count == 1


def test_context_or_challenge_rebinding_does_not_consume(database):
    ids = _seed(database)
    context = _context(ids)
    service = _service()
    prepared = _prepare(database, service, context)
    _deliver(database, prepared.challenge_uuid)

    with pytest.raises(SensitiveActionConflictError):
        with database.transaction() as session:
            service.authorize_primary(
                session,
                context=replace(
                    context, expected_target_revision="row:2"
                ),
                actor_phone=PHONE,
                challenge_uuid=prepared.challenge_uuid,
                plaintext_code="042731",
                root_key=ROOT_KEY,
                database_now=NOW + timedelta(seconds=2),
            )
    with pytest.raises(SensitiveActionConflictError):
        with database.transaction() as session:
            service.authorize_primary(
                session,
                context=context,
                actor_phone=PHONE,
                challenge_uuid=uuid4(),
                plaintext_code="042731",
                root_key=ROOT_KEY,
                database_now=NOW + timedelta(seconds=2),
            )

    with database.new_session() as session:
        challenge = session.get(SmsChallenge, str(prepared.challenge_uuid))
        assert challenge.verification_state == "active"
        assert challenge.wrong_attempt_count == 0


def test_phone_change_prepare_has_exact_old_new_roles_and_replays_without_send(
    database,
):
    ids = _seed(database)
    context = _phone_change_context(ids)
    service = _phone_change_service()

    with database.transaction() as session:
        first = service.prepare_phone_change(
            session,
            context=context,
            old_phone=PHONE,
            new_phone=NEW_PHONE,
            trusted_source=SOURCE,
            root_key=ROOT_KEY,
            sms_policy=SmsPolicy(),
            database_now=NOW,
        )
    with database.transaction() as session:
        replay = service.prepare_phone_change(
            session,
            context=context,
            old_phone=PHONE,
            new_phone=NEW_PHONE,
            trusted_source=SOURCE,
            root_key=ROOT_KEY,
            sms_policy=SmsPolicy(),
            database_now=NOW,
        )

    assert first.replayed is False
    assert len(first.deliveries) == 2
    assert {item.purpose for item in first.deliveries} == {
        SmsPurpose.PHONE_CHANGE_OLD,
        SmsPurpose.PHONE_CHANGE_NEW,
    }
    assert replay.replayed is True
    assert replay.deliveries == ()
    assert replay.old_challenge_uuid == first.old_challenge_uuid
    assert replay.new_challenge_uuid == first.new_challenge_uuid
    with database.new_session() as session:
        rows = tuple(
            session.query(TenantSensitiveActionIntentChallenge).all()
        )
        assert {row.challenge_role for row in rows} == {
            "old_phone",
            "new_phone",
        }
        challenges = tuple(session.query(SmsChallenge).all())
        assert {
            (row.purpose, row.canonical_phone_e164) for row in challenges
        } == {
            ("phone_change_old", PHONE.e164),
            ("phone_change_new", NEW_PHONE.e164),
        }


def test_phone_change_wrong_new_code_does_not_consume_correct_old_code(
    database,
):
    ids = _seed(database)
    context = _phone_change_context(ids)
    service = _phone_change_service()
    with database.transaction() as session:
        prepared = service.prepare_phone_change(
            session,
            context=context,
            old_phone=PHONE,
            new_phone=NEW_PHONE,
            trusted_source=SOURCE,
            root_key=ROOT_KEY,
            sms_policy=SmsPolicy(),
            database_now=NOW,
        )
    _deliver(database, prepared.old_challenge_uuid)
    _deliver(database, prepared.new_challenge_uuid)

    with database.transaction() as session:
        rejected = service.authorize_phone_change(
            session,
            context=context,
            old_phone=PHONE,
            new_phone=NEW_PHONE,
            old_challenge_uuid=prepared.old_challenge_uuid,
            old_plaintext_code="314159",
            new_challenge_uuid=prepared.new_challenge_uuid,
            new_plaintext_code="000000",
            root_key=ROOT_KEY,
            database_now=NOW + timedelta(seconds=2),
        )
        assert rejected.accepted is False

    with database.new_session() as session:
        old = session.get(SmsChallenge, str(prepared.old_challenge_uuid))
        new = session.get(SmsChallenge, str(prepared.new_challenge_uuid))
        assert (old.verification_state, old.wrong_attempt_count) == (
            "active",
            0,
        )
        assert (new.verification_state, new.wrong_attempt_count) == (
            "active",
            1,
        )

    with database.transaction() as session:
        accepted = service.authorize_phone_change(
            session,
            context=context,
            old_phone=PHONE,
            new_phone=NEW_PHONE,
            old_challenge_uuid=prepared.old_challenge_uuid,
            old_plaintext_code="314159",
            new_challenge_uuid=prepared.new_challenge_uuid,
            new_plaintext_code="271828",
            root_key=ROOT_KEY,
            database_now=NOW + timedelta(seconds=3),
        )
        assert accepted.accepted is True
        assert accepted.authorization is not None
        service.mark_succeeded(
            session,
            authorization=accepted.authorization,
            safe_result_code="phone_changed",
            correlation_id=f"user:{ids['user']}:auth:2",
            database_now=NOW + timedelta(seconds=3),
        )

    with database.new_session() as session:
        assert session.get(
            SmsChallenge, str(prepared.old_challenge_uuid)
        ).verification_state == "consumed"
        assert session.get(
            SmsChallenge, str(prepared.new_challenge_uuid)
        ).verification_state == "consumed"
        assert session.get(
            TenantSensitiveActionIntent, str(ids["intent"])
        ).status == "succeeded"


def test_phone_change_rejects_swapped_challenge_roles_without_consuming(
    database,
):
    ids = _seed(database)
    context = _phone_change_context(ids)
    service = _phone_change_service()
    with database.transaction() as session:
        prepared = service.prepare_phone_change(
            session,
            context=context,
            old_phone=PHONE,
            new_phone=NEW_PHONE,
            trusted_source=SOURCE,
            root_key=ROOT_KEY,
            sms_policy=SmsPolicy(),
            database_now=NOW,
        )
    _deliver(database, prepared.old_challenge_uuid)
    _deliver(database, prepared.new_challenge_uuid)

    with pytest.raises(SensitiveActionConflictError):
        with database.transaction() as session:
            service.authorize_phone_change(
                session,
                context=context,
                old_phone=PHONE,
                new_phone=NEW_PHONE,
                old_challenge_uuid=prepared.new_challenge_uuid,
                old_plaintext_code="314159",
                new_challenge_uuid=prepared.old_challenge_uuid,
                new_plaintext_code="271828",
                root_key=ROOT_KEY,
                database_now=NOW + timedelta(seconds=2),
            )

    with database.new_session() as session:
        rows = tuple(session.query(SmsChallenge).all())
        assert all(row.verification_state == "active" for row in rows)
        assert all(row.wrong_attempt_count == 0 for row in rows)
