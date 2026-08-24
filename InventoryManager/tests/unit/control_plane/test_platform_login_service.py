from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from inventory_control import ControlDatabase
from inventory_control.crypto import (
    RootKey,
    RootKeyLifecycle,
    RootKeyRing,
    derive_platform_auth_subject_digest,
)
from inventory_control.models import (
    ControlBase,
    PlatformAdminRateLimitCounter,
    PlatformAdminSession,
    PlatformAdminTotpCredential,
    PlatformAuditLog,
)
from inventory_control.platform_identity import (
    PlatformAdminLoginService,
    PlatformAdminSetupService,
    PlatformLoginPolicy,
    PlatformLoginRejected,
    PlatformPasswordHasher,
    PlatformRateLimitPolicy,
    PlatformRateLimitRule,
    PlatformRecoveryCodeService,
    SqlAlchemyPlatformLoginAuditRecorder,
    PlatformTotpService,
    activate_admin_if_ready,
    generate_totp_code,
    totp_time_step,
)


NOW = datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc)
LOGIN_AT = NOW + timedelta(seconds=33)
SEED = b"12345678901234567890"
ROOT_KEY = RootKey(version=7, material=bytes(range(32)))
PASSWORD = "correct horse battery staple"


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


class RecordingAudit:
    def __init__(self, *, fail_outcome: str | None = None) -> None:
        self.events = []
        self.fail_outcome = fail_outcome

    def record(self, session, *, event) -> None:
        assert session.in_transaction()
        if event.outcome == self.fail_outcome:
            raise RuntimeError("audit unavailable")
        self.events.append(event)


def test_successful_totp_login_issues_independent_session(control_database):
    admin_id, _recovery_codes, initial_step = _activate_admin(control_database)
    audit = RecordingAudit()
    service = _service(control_database, audit=audit)
    login_step = totp_time_step(int(LOGIN_AT.timestamp()))

    issued = service.login(
        username=" ROOT.ADMIN ",
        password=PASSWORD,
        factor_method="totp",
        factor_value=generate_totp_code(SEED, login_step),
        source_ip="203.0.113.9",
        device_id="browser-device-1",
        request_id="request-login-1",
        device_name="Safari",
        user_agent_summary="desktop-browser",
    )

    assert issued.auth.platform_admin_id == admin_id
    assert issued.auth.username_canonical == "root.admin"
    assert issued.auth.mfa_method == "totp"
    assert issued.session_token.startswith("impa1_")
    assert issued.csrf_token.startswith("impc1_")
    assert [(event.stage, event.outcome) for event in audit.events] == [
        ("complete", "succeeded")
    ]
    with control_database.new_session() as session:
        row = session.scalar(sa.select(PlatformAdminSession))
        credential = session.scalar(sa.select(PlatformAdminTotpCredential))
        assert row is not None
        assert row.first_ip_summary == "203.0.113.9"
        assert credential.last_accepted_time_step == login_step
        assert credential.last_accepted_time_step > initial_step
        assert session.scalar(
            sa.select(sa.func.count(PlatformAdminRateLimitCounter.id))
        ) == 0


def test_sqlalchemy_login_audit_is_credential_free_and_session_bound(
    control_database,
):
    admin_id, _recovery_codes, _initial_step = _activate_admin(
        control_database
    )
    service = _service(
        control_database,
        audit=SqlAlchemyPlatformLoginAuditRecorder(),
    )
    login_step = totp_time_step(int(LOGIN_AT.timestamp()))

    issued = service.login(
        username="root.admin",
        password=PASSWORD,
        factor_method="totp",
        factor_value=generate_totp_code(SEED, login_step),
        source_ip="203.0.113.9",
        device_id="browser-device-1",
        request_id="request-audited-login",
    )

    with control_database.new_session() as session:
        audit = session.scalar(sa.select(PlatformAuditLog))
        assert audit.actor_type == "platform_admin"
        assert audit.actor_platform_admin_id == admin_id
        assert audit.actor_platform_session_id == issued.auth.session_id
        assert audit.target_platform_admin_id == admin_id
        assert audit.action == "platform.login"
        assert audit.outcome == "succeeded"
        assert audit.authentication_factor == "totp"
        serialized = " ".join(
            str(value) for value in audit.__dict__.values()
        )
        assert PASSWORD not in serialized
        assert generate_totp_code(SEED, login_step) not in serialized


def test_recovery_code_login_consumes_code_once(control_database):
    admin_id, recovery_codes, _ = _activate_admin(control_database)
    audit = RecordingAudit()
    service = _service(control_database, audit=audit)

    issued = service.login(
        username="root.admin",
        password=PASSWORD,
        factor_method="recovery_code",
        factor_value=recovery_codes[0],
        source_ip="203.0.113.9",
        device_id="browser-device-1",
        request_id="request-recovery-1",
    )
    assert issued.auth.platform_admin_id == admin_id
    assert issued.auth.mfa_method == "recovery_code"

    with pytest.raises(PlatformLoginRejected) as caught:
        service.login(
            username="root.admin",
            password=PASSWORD,
            factor_method="recovery_code",
            factor_value=recovery_codes[0],
            source_ip="203.0.113.9",
            device_id="browser-device-1",
            request_id="request-recovery-replay",
        )
    assert caught.value.code == "PLATFORM_CREDENTIAL_INVALID"


def test_password_failures_are_atomic_and_block_before_mfa(control_database):
    _activate_admin(control_database)
    audit = RecordingAudit()
    service = _service(control_database, audit=audit, threshold=2)

    for sequence in (1, 2):
        with pytest.raises(PlatformLoginRejected):
            service.login(
                username="root.admin",
                password="this is the wrong password",
                factor_method="totp",
                factor_value="000000",
                source_ip="203.0.113.9",
                device_id="browser-device-1",
                request_id=f"request-password-{sequence}",
            )

    login_step = totp_time_step(int(LOGIN_AT.timestamp()))
    with pytest.raises(PlatformLoginRejected):
        service.login(
            username="root.admin",
            password=PASSWORD,
            factor_method="totp",
            factor_value=generate_totp_code(SEED, login_step),
            source_ip="203.0.113.9",
            device_id="browser-device-1",
            request_id="request-password-blocked",
        )

    with control_database.new_session() as session:
        rows = list(
            session.scalars(
                sa.select(PlatformAdminRateLimitCounter).where(
                    PlatformAdminRateLimitCounter.scope == "password"
                )
            )
        )
        assert len(rows) == 3
        assert {row.attempt_count for row in rows} == {2}
        assert all(row.blocked_until == row.expires_at for row in rows)
        assert session.scalar(
            sa.select(sa.func.count(PlatformAdminSession.id))
        ) == 0
    assert audit.events[-1].outcome == "rate_limited"
    assert audit.events[-1].stage == "password"


def test_mfa_failure_does_not_advance_totp_replay_cursor(control_database):
    _admin_id, _codes, initial_step = _activate_admin(control_database)
    audit = RecordingAudit()
    service = _service(control_database, audit=audit)

    with pytest.raises(PlatformLoginRejected):
        service.login(
            username="root.admin",
            password=PASSWORD,
            factor_method="totp",
            factor_value="000000",
            source_ip="203.0.113.9",
            device_id="browser-device-1",
            request_id="request-mfa-invalid",
        )

    with control_database.new_session() as session:
        credential = session.scalar(sa.select(PlatformAdminTotpCredential))
        assert credential.last_accepted_time_step == initial_step
        rows = list(
            session.scalars(
                sa.select(PlatformAdminRateLimitCounter).where(
                    PlatformAdminRateLimitCounter.scope == "mfa"
                )
            )
        )
        assert len(rows) == 3
        assert {row.attempt_count for row in rows} == {1}


def test_success_audit_failure_rolls_back_factor_and_session(control_database):
    _admin_id, _codes, initial_step = _activate_admin(control_database)
    login_step = totp_time_step(int(LOGIN_AT.timestamp()))
    failing = _service(
        control_database,
        audit=RecordingAudit(fail_outcome="succeeded"),
    )

    with pytest.raises(RuntimeError, match="audit unavailable"):
        failing.login(
            username="root.admin",
            password=PASSWORD,
            factor_method="totp",
            factor_value=generate_totp_code(SEED, login_step),
            source_ip="203.0.113.9",
            device_id="browser-device-1",
            request_id="request-audit-failure",
        )

    with control_database.new_session() as session:
        credential = session.scalar(sa.select(PlatformAdminTotpCredential))
        assert credential.last_accepted_time_step == initial_step
        assert session.scalar(
            sa.select(sa.func.count(PlatformAdminSession.id))
        ) == 0

    retry = _service(control_database, audit=RecordingAudit())
    assert retry.login(
        username="root.admin",
        password=PASSWORD,
        factor_method="totp",
        factor_value=generate_totp_code(SEED, login_step),
        source_ip="203.0.113.9",
        device_id="browser-device-1",
        request_id="request-audit-retry",
    ).auth.mfa_method == "totp"


def test_unknown_identity_and_wrong_factor_share_public_error(control_database):
    _activate_admin(control_database)
    service = _service(control_database, audit=RecordingAudit())
    attempts = (
        dict(
            username="missing.admin",
            password=PASSWORD,
            factor_method="totp",
            factor_value="000000",
        ),
        dict(
            username="root.admin",
            password=PASSWORD,
            factor_method="unsupported",
            factor_value="credential-material",
        ),
    )
    messages = []
    for sequence, attempt in enumerate(attempts, start=1):
        with pytest.raises(PlatformLoginRejected) as caught:
            service.login(
                **attempt,
                source_ip=f"203.0.113.{sequence}",
                device_id=f"browser-device-{sequence}",
                request_id=f"request-uniform-{sequence}",
            )
        messages.append((caught.value.code, str(caught.value)))
    assert messages[0] == messages[1]


def test_platform_auth_subject_digest_is_keyed_and_purpose_separated():
    username = derive_platform_auth_subject_digest(
        root_key=ROOT_KEY,
        subject_type="username",
        subject_value="root.admin",
    )
    assert len(username) == 32
    assert username == derive_platform_auth_subject_digest(
        root_key=ROOT_KEY,
        subject_type="username",
        subject_value="root.admin",
    )
    assert username != derive_platform_auth_subject_digest(
        root_key=ROOT_KEY,
        subject_type="device",
        subject_value="root.admin",
    )
    assert username != derive_platform_auth_subject_digest(
        root_key=RootKey(version=8, material=b"z" * 32),
        subject_type="username",
        subject_value="root.admin",
    )


def test_login_reads_legacy_totp_key_while_new_throttles_use_active_key(
    control_database,
):
    admin_id, _recovery_codes, _initial_step = _activate_admin(
        control_database
    )
    active_key = RootKey(version=8, material=b"z" * 32)
    ring = RootKeyRing(
        active_version=active_key.version,
        keys={ROOT_KEY.version: ROOT_KEY, active_key.version: active_key},
        statuses={
            ROOT_KEY.version: RootKeyLifecycle.LEGACY,
            active_key.version: RootKeyLifecycle.ACTIVE,
        },
    )
    service = _service(
        control_database,
        audit=RecordingAudit(),
        root_key_ring=ring,
    )
    login_step = totp_time_step(int(LOGIN_AT.timestamp()))
    issued = service.login(
        username="root.admin",
        password=PASSWORD,
        factor_method="totp",
        factor_value=generate_totp_code(SEED, login_step),
        source_ip="203.0.113.9",
        device_id="browser-device-1",
        request_id="request-legacy-totp-key",
    )
    assert issued.auth.platform_admin_id == admin_id


def _activate_admin(control_database):
    setup = PlatformAdminSetupService()
    totp = PlatformTotpService(seed_generator=lambda: SEED)
    recovery = PlatformRecoveryCodeService()
    hasher = PlatformPasswordHasher()
    with control_database.transaction() as session:
        challenge = setup.create_pending_admin(
            session,
            username="root.admin",
            now=NOW,
        )
        admin_id = challenge.platform_admin_id
        token = challenge.plaintext_token
    with control_database.transaction() as session:
        assert setup.consume(
            session,
            presented_token=token,
            now=NOW + timedelta(seconds=1),
        ).accepted
        setup.set_password(
            session,
            platform_admin_id=admin_id,
            expected_setup_version=1,
            password=PASSWORD,
            hasher=hasher,
            now=NOW + timedelta(seconds=1),
        )
        pending = totp.create_pending_binding(
            session,
            platform_admin_id=admin_id,
            root_key=ROOT_KEY,
            now=NOW + timedelta(seconds=1),
        )
        credential_id = pending.credential_id
        pending.take_base32_seed()
    confirmation_at = NOW + timedelta(seconds=2)
    confirmation_step = totp_time_step(int(confirmation_at.timestamp()))
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
    return admin_id, recovery_codes, confirmation_step


def _service(
    control_database,
    *,
    audit,
    threshold=5,
    root_key_ring=None,
):
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
            max_failures=threshold,
        )
        for scope in ("password", "mfa")
        for subject_type in ("username", "ip", "device")
    )
    policy = PlatformLoginPolicy(
        rate_limit=PlatformRateLimitPolicy(
            version=1,
            calendar_timezone="Asia/Shanghai",
            rules=rules,
        ),
        idle_timeout=timedelta(minutes=30),
        absolute_timeout=timedelta(hours=8),
        factor_max_age=timedelta(minutes=1),
        session_policy_version=1,
        allowed_totp_drift_steps=0,
    )
    selected_ring = root_key_ring or RootKeyRing(
        active_version=ROOT_KEY.version,
        keys={ROOT_KEY.version: ROOT_KEY},
        statuses={ROOT_KEY.version: RootKeyLifecycle.ACTIVE},
    )
    return PlatformAdminLoginService(
        control_database=control_database,
        root_key_provider=lambda _session: selected_ring,
        policy=policy,
        audit_recorder=audit,
        database_clock=lambda _session: LOGIN_AT,
    )
