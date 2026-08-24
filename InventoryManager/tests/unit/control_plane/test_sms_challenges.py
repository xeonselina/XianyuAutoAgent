from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from inventory_control import (
    ControlBase,
    SmsChallenge,
    Tenant,
    TenantUserSession,
    User,
)
from inventory_control.crypto import RootKey
from inventory_control.identity import (
    CN_MOBILE_METADATA_VERSION,
    PHONE_NORMALIZATION_VERSION,
)
from inventory_control.sms import (
    CanonicalActionPayload,
    CanonicalSmsPhone,
    SmsChallengeContext,
    SmsChallengeService,
    SmsDeliveryOutcome,
    SmsDeliveryStateError,
    SmsPolicy,
    SmsPurpose,
    SmsSendRejected,
    TrustedSourceBucket,
    calculate_code_hmac,
    verify_code_hmac,
)
from tests.support.test_database import (
    clear_guarded_mysql_test_rows,
    guarded_mysql_control_database,
)


NOW = datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc)
ROOT_KEY = RootKey(version=7, material=bytes(range(32)))
OTHER_ROOT_KEY = RootKey(version=8, material=bytes(range(32)))


@pytest.fixture(scope="module")
def control_database_schema():
    with guarded_mysql_control_database(ControlBase.metadata) as database:
        yield database


@pytest.fixture
def control_database(control_database_schema):
    clear_guarded_mysql_test_rows(
        control_database_schema.engine,
        ControlBase.metadata,
    )
    return control_database_schema


class RecordingSmsProvider:
    def __init__(self, result="provider-accepted"):
        self.result = result
        self.requests = []
        self.plaintext_codes = []

    def send_verification(self, request):
        self.requests.append(request)
        self.plaintext_codes.append(request.take_plaintext_code())
        return self.result


def _phone(national="13800138000"):
    return CanonicalSmsPhone.from_input(national)


def _context(
    *,
    national="13800138000",
    purpose=SmsPurpose.LOGIN,
    payload=None,
    revision="user-auth:1",
    user_id=None,
    tenant_id=None,
    actor_session_id=None,
):
    return SmsChallengeContext(
        purpose=purpose,
        phone=_phone(national),
        action_payload=CanonicalActionPayload.from_value(
            {"action": purpose.value} if payload is None else payload
        ),
        authoritative_revision=revision,
        user_id=user_id,
        tenant_id=tenant_id,
        actor_session_id=actor_session_id,
    )


def _prepare(
    database,
    service,
    *,
    context=None,
    source=None,
    policy=None,
    now=NOW,
):
    with database.transaction() as session:
        return service.prepare_delivery(
            session,
            context=context or _context(),
            trusted_source=source or TrustedSourceBucket.from_trusted_ip("192.0.2.10"),
            root_key=ROOT_KEY,
            policy=policy or SmsPolicy(),
            now=now,
        )


def _record(database, service, prepared, outcome, *, now=NOW):
    with database.transaction() as session:
        return service.record_delivery(
            session,
            challenge_id=prepared.challenge_id,
            outcome=outcome,
            now=now,
        )


def _prepare_sent(
    database,
    service,
    *,
    context=None,
    source=None,
    policy=None,
    now=NOW,
):
    prepared = _prepare(
        database,
        service,
        context=context,
        source=source,
        policy=policy,
        now=now,
    )
    provider = RecordingSmsProvider()
    assert prepared.dispatch_once(provider) == "provider-accepted"
    _record(database, service, prepared, SmsDeliveryOutcome.SENT, now=now)
    return prepared, provider


def _seed_context_authorities(control_database, context):
    assert context.user_id is not None
    assert context.tenant_id is not None
    assert context.actor_session_id is not None
    with control_database.transaction() as session:
        session.add(
            Tenant(
                id=context.tenant_id,
                status="active",
                access_version=1,
            )
        )
        session.add(
            User(
                id=context.user_id,
                phone_e164=context.phone.e164,
                phone_normalization_version=PHONE_NORMALIZATION_VERSION,
                phone_metadata_version=CN_MOBILE_METADATA_VERSION,
                phone_verified_at=NOW,
                status="active",
                auth_version=1,
            )
        )
        session.flush()
        session.add(
            TenantUserSession(
                id=context.actor_session_id,
                user_id=context.user_id,
                token_digest_sha256=b"c" * 32,
                csrf_digest_sha256=b"d" * 32,
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


def test_sms_boundary_requires_versioned_canonical_phone_and_trusted_source(
    control_database,
):
    canonical = CanonicalSmsPhone.from_input("+86 138-0013-8000")
    assert canonical.e164 == "+8613800138000"
    assert canonical.normalization_version == PHONE_NORMALIZATION_VERSION
    assert canonical.metadata_version == CN_MOBILE_METADATA_VERSION
    assert "+8613800138000" not in repr(canonical)

    with pytest.raises(ValueError):
        CanonicalSmsPhone(
            e164="13800138000",
            normalization_version=PHONE_NORMALIZATION_VERSION,
            metadata_version=CN_MOBILE_METADATA_VERSION,
        )
    with pytest.raises(ValueError):
        CanonicalSmsPhone(
            e164="+8613800138000",
            normalization_version=PHONE_NORMALIZATION_VERSION + 1,
            metadata_version=CN_MOBILE_METADATA_VERSION,
        )

    source = TrustedSourceBucket.from_trusted_ip("2001:0db8::1")
    assert source.value == "ip6:2001:db8::1"
    assert "2001:db8::1" not in repr(source)
    with pytest.raises(TypeError, match="trusted request boundary"):
        with control_database.transaction() as session:
            SmsChallengeService().prepare_delivery(
                session,
                context=_context(),
                trusted_source="X-Forwarded-For: 203.0.113.9",
                root_key=ROOT_KEY,
                policy=SmsPolicy(),
                now=NOW,
            )


def test_canonical_action_payload_is_stable_and_rejects_ambiguous_values():
    first = CanonicalActionPayload.from_value(
        {"target": {"revision": 3, "enabled": True}, "items": [2, 1]}
    )
    second = CanonicalActionPayload.from_value(
        {"items": [2, 1], "target": {"enabled": True, "revision": 3}}
    )

    assert first.digest_sha256 == second.digest_sha256
    assert "target" not in repr(first)
    with pytest.raises(ValueError, match="unsupported"):
        CanonicalActionPayload.from_value({"price": 1.5})
    with pytest.raises(ValueError, match="keys"):
        CanonicalActionPayload.from_value({1: "not-a-string-key"})


def test_sms_hmac_fixed_vector_locks_purpose_separated_context_protocol():
    context = _context()

    digest = calculate_code_hmac(
        root_key=ROOT_KEY,
        challenge_id="12345678-1234-4567-89ab-123456789abc",
        context=context,
        plaintext_code="042731",
    )

    assert digest.hex() == (
        "bb824ec2bce85ab4a9fa0446134796b2"
        "5c0813347b41606a249b5688d94df404"
    )
    changed_purpose = replace(context, purpose=SmsPurpose.REGISTER)
    assert calculate_code_hmac(
        root_key=ROOT_KEY,
        challenge_id="12345678-1234-4567-89ab-123456789abc",
        context=changed_purpose,
        plaintext_code="042731",
    ) != digest


def test_sms_hmac_verifier_never_accepts_invalid_inputs_as_zero_mac():
    assert not verify_code_hmac(
        root_key=ROOT_KEY,
        challenge_id="12345678-1234-4567-89ab-123456789abc",
        context=_context(),
        plaintext_code="042731",
        expected_hmac=bytes(32),
        protocol_version=999,
    )


def test_prepare_persists_only_bound_hmac_and_dispatches_plaintext_once(
    control_database,
):
    service = SmsChallengeService(code_generator=lambda: "042731")
    context = _context(
        purpose=SmsPurpose.SF_ACCOUNT_BIND,
        payload={"warehouse_id": "warehouse-7", "account_revision": 4},
        revision="sf-binding:4",
        user_id=str(uuid4()),
        tenant_id=str(uuid4()),
        actor_session_id=str(uuid4()),
    )
    _seed_context_authorities(control_database, context)
    prepared = _prepare(control_database, service, context=context)

    assert "042731" not in repr(prepared)
    with control_database.new_session() as session:
        row = session.get(SmsChallenge, prepared.challenge_id)
        assert row.delivery_state == "committed"
        assert row.verification_state == "pending_delivery"
        assert row.purpose == "sf_account_bind"
        assert row.user_id == context.user_id
        assert row.tenant_id == context.tenant_id
        assert row.actor_session_id == context.actor_session_id
        assert row.authoritative_revision == "sf-binding:4"
        assert row.action_payload_digest_sha256 == context.action_payload.digest_sha256
        assert row.code_hmac_sha256 != hashlib.sha256(b"042731").digest()
        assert set(row.__table__.columns.keys()).isdisjoint(
            {"plaintext_code", "verification_code", "code"}
        )

    provider = RecordingSmsProvider(result={"status": "accepted"})
    assert prepared.dispatch_once(provider) == {"status": "accepted"}
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.canonical_phone_e164 == context.phone.e164
    assert provider.plaintext_codes == ["042731"]
    assert "042731" not in repr(request)
    assert context.phone.e164 not in repr(request)
    with pytest.raises(RuntimeError, match="no longer available"):
        request.take_plaintext_code()
    with pytest.raises(RuntimeError, match="no longer available"):
        prepared.dispatch_once(provider)


@pytest.mark.parametrize(
    ("outcome", "verification_state"),
    [
        (SmsDeliveryOutcome.SENT, "active"),
        (SmsDeliveryOutcome.SEND_UNKNOWN, "active"),
        (SmsDeliveryOutcome.FAILED, "invalidated"),
    ],
)
def test_delivery_states_are_explicit_and_idempotent(
    control_database, outcome, verification_state
):
    service = SmsChallengeService(code_generator=lambda: "123456")
    prepared = _prepare(control_database, service)

    assert _record(control_database, service, prepared, outcome) is True
    assert _record(control_database, service, prepared, outcome) is False
    with control_database.new_session() as session:
        row = session.get(SmsChallenge, prepared.challenge_id)
        assert row.delivery_state == outcome.value
        assert row.verification_state == verification_state

    conflicting = (
        SmsDeliveryOutcome.SEND_UNKNOWN
        if outcome is not SmsDeliveryOutcome.SEND_UNKNOWN
        else SmsDeliveryOutcome.SENT
    )
    with pytest.raises(SmsDeliveryStateError):
        _record(control_database, service, prepared, conflicting)


def test_verification_binds_every_context_field_and_consumes_once(
    control_database,
):
    service = SmsChallengeService(code_generator=lambda: "123456")
    context = _context(
        purpose=SmsPurpose.INTEGRATION_CREDENTIAL_CHANGE,
        payload={"integration_id": "i-7", "secret_revision": 3},
        revision="integration:3",
        user_id=str(uuid4()),
        tenant_id=str(uuid4()),
        actor_session_id=str(uuid4()),
    )
    _seed_context_authorities(control_database, context)
    prepared, _ = _prepare_sent(control_database, service, context=context)

    variants = (
        replace(context, purpose=SmsPurpose.SF_ACCOUNT_BIND),
        replace(
            context,
            action_payload=CanonicalActionPayload.from_value(
                {"integration_id": "i-7", "secret_revision": 4}
            ),
        ),
        replace(context, authoritative_revision="integration:4"),
        replace(context, user_id=str(uuid4())),
        replace(context, tenant_id=str(uuid4())),
        replace(context, actor_session_id=str(uuid4())),
    )
    rejection_codes = set()
    for changed_context in variants:
        with control_database.transaction() as session:
            result = service.verify_and_consume(
                session,
                challenge_id=prepared.challenge_id,
                context=changed_context,
                plaintext_code="123456",
                root_key=ROOT_KEY,
                now=NOW + timedelta(seconds=1),
            )
            assert result.accepted is False
            rejection_codes.add(result.reason_code)

    with control_database.transaction() as session:
        wrong_root = service.verify_and_consume(
            session,
            challenge_id=prepared.challenge_id,
            context=context,
            plaintext_code="123456",
            root_key=OTHER_ROOT_KEY,
            now=NOW + timedelta(seconds=1),
        )
        assert wrong_root.accepted is False
        rejection_codes.add(wrong_root.reason_code)

    with control_database.transaction() as session:
        accepted = service.verify_and_consume(
            session,
            challenge_id=prepared.challenge_id,
            context=context,
            plaintext_code="123456",
            root_key=ROOT_KEY,
            now=NOW + timedelta(seconds=1),
        )
        assert accepted.accepted is True

    with control_database.transaction() as session:
        replay = service.verify_and_consume(
            session,
            challenge_id=prepared.challenge_id,
            context=context,
            plaintext_code="123456",
            root_key=ROOT_KEY,
            now=NOW + timedelta(seconds=2),
        )
        missing = service.verify_and_consume(
            session,
            challenge_id=str(uuid4()),
            context=context,
            plaintext_code="123456",
            root_key=ROOT_KEY,
            now=NOW + timedelta(seconds=2),
        )
        assert replay == missing
        assert replay.accepted is False
        rejection_codes.add(replay.reason_code)

    assert rejection_codes == {"SMS_CHALLENGE_REJECTED"}
    with control_database.new_session() as session:
        row = session.get(SmsChallenge, prepared.challenge_id)
        assert row.verification_state == "consumed"
        assert row.consumed_at is not None
        assert row.wrong_attempt_count == 0


def test_fifth_wrong_attempt_atomically_locks_challenge(control_database):
    service = SmsChallengeService(code_generator=lambda: "123456")
    context = _context()
    prepared, _ = _prepare_sent(control_database, service, context=context)

    for attempt in range(1, 6):
        with control_database.transaction() as session:
            result = service.verify_and_consume(
                session,
                challenge_id=prepared.challenge_id,
                context=context,
                plaintext_code="654321",
                root_key=ROOT_KEY,
                now=NOW + timedelta(seconds=attempt),
            )
            assert result.accepted is False
        with control_database.new_session() as session:
            row = session.get(SmsChallenge, prepared.challenge_id)
            assert row.wrong_attempt_count == attempt
            assert row.verification_state == (
                "locked" if attempt == 5 else "active"
            )

    with control_database.transaction() as session:
        result = service.verify_and_consume(
            session,
            challenge_id=prepared.challenge_id,
            context=context,
            plaintext_code="123456",
            root_key=ROOT_KEY,
            now=NOW + timedelta(seconds=6),
        )
        assert result.accepted is False


def test_challenge_expires_exactly_five_minutes_after_creation(control_database):
    service = SmsChallengeService(code_generator=lambda: "123456")
    context = _context()
    prepared, _ = _prepare_sent(control_database, service, context=context)

    with control_database.transaction() as session:
        result = service.verify_and_consume(
            session,
            challenge_id=prepared.challenge_id,
            context=context,
            plaintext_code="123456",
            root_key=ROOT_KEY,
            now=NOW + timedelta(minutes=5),
        )
        assert result.accepted is False


def test_resend_cooldown_and_newer_same_purpose_invalidation(control_database):
    service = SmsChallengeService(code_generator=lambda: "123456")
    context = _context()
    first, _ = _prepare_sent(control_database, service, context=context)

    with pytest.raises(SmsSendRejected) as caught:
        _prepare(
            control_database,
            service,
            context=context,
            now=NOW + timedelta(seconds=59),
        )
    assert caught.value.reason_code == "SMS_RESEND_COOLDOWN"
    assert caught.value.retry_after_seconds == 1
    assert context.phone.e164 not in str(caught.value)

    second, _ = _prepare_sent(
        control_database,
        service,
        context=context,
        now=NOW + timedelta(seconds=60),
    )
    with control_database.new_session() as session:
        assert session.get(SmsChallenge, first.challenge_id).verification_state == (
            "invalidated"
        )
        assert session.get(SmsChallenge, second.challenge_id).verification_state == (
            "active"
        )


def test_committed_reservation_blocks_parallel_send_and_failed_send_frees_quota(
    control_database,
):
    policy = SmsPolicy(phone_rolling_hour_limit=1)
    service = SmsChallengeService(code_generator=lambda: "123456")
    first = _prepare(control_database, service, policy=policy)

    with pytest.raises(SmsSendRejected) as caught:
        _prepare(control_database, service, policy=policy, now=NOW + timedelta(seconds=1))
    assert caught.value.reason_code == "SMS_SEND_IN_PROGRESS"

    _record(
        control_database,
        service,
        first,
        SmsDeliveryOutcome.FAILED,
        now=NOW + timedelta(seconds=2),
    )
    second = _prepare(
        control_database,
        service,
        policy=policy,
        now=NOW + timedelta(seconds=3),
    )
    assert second.challenge_id != first.challenge_id


def test_phone_limit_is_cross_purpose_and_source_limit_is_cross_phone(
    control_database,
):
    service = SmsChallengeService(code_generator=lambda: "123456")
    source = TrustedSourceBucket.from_trusted_ip("192.0.2.50")
    phone_policy = SmsPolicy(
        phone_rolling_hour_limit=2,
        phone_shanghai_day_limit=10,
        source_rolling_hour_limit=30,
        source_shanghai_day_limit=200,
    )
    purposes = (
        SmsPurpose.LOGIN,
        SmsPurpose.REGISTER,
        SmsPurpose.ACCEPT_INVITATION,
    )
    for offset, purpose in zip((0, 61), purposes[:2]):
        _prepare_sent(
            control_database,
            service,
            context=_context(purpose=purpose, revision=f"identity:{offset}"),
            source=source,
            policy=phone_policy,
            now=NOW + timedelta(seconds=offset),
        )
    with pytest.raises(SmsSendRejected) as caught:
        _prepare(
            control_database,
            service,
            context=_context(purpose=purposes[2], revision="invitation:1"),
            source=source,
            policy=phone_policy,
            now=NOW + timedelta(seconds=122),
        )
    assert caught.value.reason_code == "SMS_PHONE_HOURLY_LIMIT"

    source_policy = SmsPolicy(
        phone_rolling_hour_limit=5,
        phone_shanghai_day_limit=10,
        source_rolling_hour_limit=2,
        source_shanghai_day_limit=200,
    )
    isolated_source = TrustedSourceBucket.from_trusted_ip("198.51.100.40")
    for suffix in (1, 2):
        _prepare_sent(
            control_database,
            service,
            context=_context(national=f"13900138{suffix:03d}"),
            source=isolated_source,
            policy=source_policy,
            now=NOW,
        )
    with pytest.raises(SmsSendRejected) as caught:
        _prepare(
            control_database,
            service,
            context=_context(national="13900138003"),
            source=isolated_source,
            policy=source_policy,
            now=NOW,
        )
    assert caught.value.reason_code == "SMS_SOURCE_HOURLY_LIMIT"


def test_daily_limit_uses_asia_shanghai_calendar_boundary(control_database):
    service = SmsChallengeService(code_generator=lambda: "123456")
    policy = SmsPolicy(
        phone_rolling_hour_limit=5,
        phone_shanghai_day_limit=1,
        source_rolling_hour_limit=30,
        source_shanghai_day_limit=1,
    )
    before_midnight = datetime(2026, 8, 22, 15, 59, tzinfo=timezone.utc)
    _prepare_sent(
        control_database,
        service,
        policy=policy,
        now=before_midnight,
    )

    with pytest.raises(SmsSendRejected) as caught:
        _prepare(
            control_database,
            service,
            policy=policy,
            now=before_midnight + timedelta(seconds=30),
        )
    assert caught.value.reason_code == "SMS_RESEND_COOLDOWN"

    next_day = _prepare(
        control_database,
        service,
        policy=policy,
        now=before_midnight + timedelta(minutes=1),
    )
    assert next_day.challenge_id


def test_default_policy_locks_confirmed_core_thresholds():
    policy = SmsPolicy()

    assert policy.challenge_ttl_seconds == 300
    assert policy.resend_cooldown_seconds == 60
    assert policy.max_wrong_attempts == 5
    assert policy.phone_rolling_hour_limit == 5
    assert policy.phone_shanghai_day_limit == 10
    assert policy.source_rolling_hour_limit == 30
    assert policy.source_shanghai_day_limit == 200

    weakening_changes = (
        {"challenge_ttl_seconds": 301},
        {"resend_cooldown_seconds": 59},
        {"max_wrong_attempts": 6},
        {"phone_rolling_hour_limit": 6},
        {"phone_shanghai_day_limit": 11},
        {"source_rolling_hour_limit": 31},
        {"source_shanghai_day_limit": 201},
    )
    for change in weakening_changes:
        with pytest.raises(ValueError, match="may not weaken"):
            SmsPolicy(**change)
