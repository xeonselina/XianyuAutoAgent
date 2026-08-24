from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

from inventory_control import ControlDatabase
from inventory_control.crypto import CryptoAuthenticationError, RootKey
from inventory_control.models import (
    ControlBase,
    PlatformAdmin,
    PlatformAdminRateLimitCounter,
    PlatformAdminRecoveryCode,
    PlatformAdminSession,
    PlatformAdminSetupChallenge,
    PlatformAdminTotpCredential,
    PlatformAuditLog,
)
from inventory_control.platform_identity import (
    PLATFORM_TOKEN_ENTROPY_BITS,
    IssuedPlatformToken,
    PlatformAdminSessionService,
    PlatformAdminSetupService,
    PlatformAdminHostService,
    PlatformCredentialError,
    PlatformCsrfAuthenticationError,
    PlatformFactorRejected,
    PlatformHostOperationRejected,
    PlatformPasswordError,
    PlatformPasswordHasher,
    PlatformRecoveryCodeService,
    PlatformSessionAuthenticationError,
    PlatformSessionIssueError,
    PlatformSessionTargetUnavailable,
    PlatformTotpService,
    PlatformUsernameError,
    activate_admin_if_ready,
    canonicalize_platform_username,
    decrypt_totp_seed,
    digest_platform_csrf_token,
    digest_platform_session_token,
    digest_recovery_code,
    digest_setup_token,
    encrypt_totp_seed,
    generate_totp_code,
    issue_platform_csrf_token,
    issue_platform_session_token,
    issue_recovery_code,
    issue_setup_token,
    totp_time_step,
    verify_platform_csrf_token,
    verify_platform_session_token,
    verify_recovery_code,
    verify_setup_token,
)


NOW = datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc)
SEED = b"12345678901234567890"
ROOT_KEY = RootKey(version=7, material=bytes(range(32)))
PASSWORD = "correct horse battery staple"


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


def test_username_canonicalization_is_platform_only_and_non_enumerating():
    assert canonicalize_platform_username("  Root.Admin-1  ") == "root.admin-1"

    for invalid in (None, "ab", "+8613800138000", "root admin", "管理员", "root\t"):
        with pytest.raises(PlatformUsernameError) as caught:
            canonicalize_platform_username(invalid)
        assert str(invalid) not in str(caught.value)
        assert caught.value.code == "PLATFORM_CREDENTIAL_INVALID"


def test_platform_bearers_are_high_entropy_namespaced_and_repr_safe():
    issuers = (
        (issue_setup_token, digest_setup_token, verify_setup_token, "imps1_"),
        (
            issue_platform_session_token,
            digest_platform_session_token,
            verify_platform_session_token,
            "impa1_",
        ),
        (
            issue_platform_csrf_token,
            digest_platform_csrf_token,
            verify_platform_csrf_token,
            "impc1_",
        ),
        (issue_recovery_code, digest_recovery_code, verify_recovery_code, "impr1_"),
    )
    issued: list[IssuedPlatformToken] = []
    for issue, digest, verify, prefix in issuers:
        token = issue()
        issued.append(token)
        assert token.plaintext.startswith(prefix)
        assert PLATFORM_TOKEN_ENTROPY_BITS == 256
        assert token.digest_sha256 == hashlib.sha256(
            token.plaintext.encode("ascii")
        ).digest()
        assert digest(token.plaintext) == token.digest_sha256
        assert verify(token.plaintext, token.digest_sha256)
        assert token.plaintext not in repr(token)

    assert len({token.plaintext for token in issued}) == len(issued)
    for token, (_, _, verify, _) in zip(issued, issuers):
        for other in issued:
            assert verify(other.plaintext, token.digest_sha256) is (other is token)

    malformed = "impa1_do-not-echo"
    with pytest.raises(PlatformCredentialError) as caught:
        digest_platform_session_token(malformed)
    assert malformed not in str(caught.value)


def test_password_hashing_is_versioned_memory_hard_and_safe():
    hasher = PlatformPasswordHasher()
    password_hash = hasher.hash(PASSWORD)

    assert password_hash.algorithm in {"argon2id", "scrypt"}
    assert password_hash.version == 1
    assert password_hash.encoded.startswith(
        f"${password_hash.algorithm}-v1$"
    )
    assert PASSWORD not in password_hash.encoded
    assert password_hash.encoded not in repr(password_hash)
    assert hasher.verify(PASSWORD, password_hash.encoded)
    assert not hasher.verify("wrong password value", password_hash.encoded)
    assert not hasher.verify(PASSWORD, "$scrypt-v1$n=1,r=8,p=1$bad$bad")
    assert not hasher.needs_rehash(password_hash.encoded)

    for invalid in (None, "short"):
        with pytest.raises(PlatformPasswordError) as caught:
            hasher.hash(invalid)
        assert str(invalid) not in str(caught.value)


def test_rfc6238_vector_and_strict_time_step_behavior():
    # RFC 6238 Appendix B, SHA-1, T=59, eight digits.
    assert generate_totp_code(SEED, 1, digits=8) == "94287082"
    code = generate_totp_code(SEED, 1234)
    from inventory_control.platform_identity import find_accepted_totp_step

    assert (
        find_accepted_totp_step(
            seed=SEED,
            presented_code=code,
            current_time_step=1234,
            last_accepted_time_step=1233,
            allowed_drift_steps=0,
        )
        == 1234
    )
    assert (
        find_accepted_totp_step(
            seed=SEED,
            presented_code=code,
            current_time_step=1234,
            last_accepted_time_step=1234,
            allowed_drift_steps=0,
        )
        is None
    )


def test_totp_envelope_has_independent_domain_and_immutable_aad():
    credential_id = str(uuid4())
    admin_id = str(uuid4())
    envelope = encrypt_totp_seed(
        root_key=ROOT_KEY,
        credential_id=credential_id,
        platform_admin_id=admin_id,
        secret_revision=1,
        seed=SEED,
    )
    assert SEED not in envelope.ciphertext
    assert decrypt_totp_seed(
        root_key=ROOT_KEY,
        credential_id=credential_id,
        platform_admin_id=admin_id,
        secret_revision=1,
        envelope=envelope,
    ) == SEED

    for changed in ("credential", "admin", "revision"):
        kwargs = {
            "root_key": ROOT_KEY,
            "credential_id": credential_id,
            "platform_admin_id": admin_id,
            "secret_revision": 1,
            "envelope": envelope,
        }
        if changed == "credential":
            kwargs["credential_id"] = str(uuid4())
        elif changed == "admin":
            kwargs["platform_admin_id"] = str(uuid4())
        else:
            kwargs["secret_revision"] = 2
        with pytest.raises(CryptoAuthenticationError):
            decrypt_totp_seed(**kwargs)


def test_setup_totp_recovery_activation_and_single_use(control_database):
    setup = PlatformAdminSetupService()
    totp = PlatformTotpService(seed_generator=lambda: SEED)
    recovery = PlatformRecoveryCodeService()
    hasher = PlatformPasswordHasher()

    with control_database.transaction() as session:
        challenge = setup.create_pending_admin(
            session, username=" Platform.Root ", now=NOW
        )
        admin_id = challenge.platform_admin_id
        setup_token = challenge.plaintext_token
        assert setup_token not in repr(challenge)

    with control_database.transaction() as session:
        consumed = setup.consume(
            session, presented_token=setup_token, now=NOW + timedelta(seconds=1)
        )
        assert consumed.accepted and consumed.platform_admin_id == admin_id
        setup.set_password(
            session,
            platform_admin_id=admin_id,
            expected_setup_version=1,
            password=PASSWORD,
            hasher=hasher,
            now=NOW + timedelta(seconds=1),
        )
        pending_seed = totp.create_pending_binding(
            session,
            platform_admin_id=admin_id,
            root_key=ROOT_KEY,
            now=NOW + timedelta(seconds=1),
        )
        credential_id = pending_seed.credential_id
        base32_seed = pending_seed.take_base32_seed()
        assert base64.b32decode(base32_seed) == SEED
        assert base32_seed not in repr(pending_seed)
        with pytest.raises(RuntimeError):
            pending_seed.take_base32_seed()

    with control_database.transaction() as session:
        replay = setup.consume(
            session, presented_token=setup_token, now=NOW + timedelta(seconds=2)
        )
        assert not replay.accepted
        assert replay.platform_admin_id is None

    confirmation_time = NOW + timedelta(seconds=2)
    confirmation_step = totp_time_step(int(confirmation_time.timestamp()))
    confirmation_code = generate_totp_code(SEED, confirmation_step)
    with control_database.transaction() as session:
        proof = totp.confirm_pending(
            session,
            credential_id=credential_id,
            presented_code=confirmation_code,
            root_key=ROOT_KEY,
            now=confirmation_time,
            allowed_drift_steps=0,
        )
        assert confirmation_code not in repr(proof)
        batch = recovery.issue_codes(
            session, platform_admin_id=admin_id, count=6, now=confirmation_time
        )
        codes = batch.take_plaintext_codes()
        assert all(code not in repr(batch) for code in codes)
        with pytest.raises(RuntimeError):
            batch.take_plaintext_codes()
        activate_admin_if_ready(
            session,
            platform_admin_id=admin_id,
            expected_setup_version=1,
            now=confirmation_time,
        )

    with control_database.new_session() as session:
        admin = session.get(PlatformAdmin, admin_id)
        assert admin.status == "active"
        assert admin.username_canonical == "platform.root"
        rows = list(
            session.scalars(
                sa.select(PlatformAdminRecoveryCode).where(
                    PlatformAdminRecoveryCode.platform_admin_id == admin_id
                )
            )
        )
        assert len(rows) == 6
        assert not hasattr(rows[0], "plaintext_code")
        assert {row.token_digest_sha256 for row in rows} == {
            digest_recovery_code(code) for code in codes
        }

    with control_database.new_session() as session:
        with pytest.raises(PlatformFactorRejected):
            totp.confirm_pending(
                session,
                credential_id=credential_id,
                presented_code=confirmation_code,
                root_key=ROOT_KEY,
                now=confirmation_time,
                allowed_drift_steps=0,
            )

    with control_database.transaction() as session:
        recovery_proof = recovery.consume(
            session,
            platform_admin_id=admin_id,
            presented_code=codes[0],
            now=NOW + timedelta(minutes=1),
        )
        assert codes[0] not in repr(recovery_proof)
    with control_database.new_session() as session:
        with pytest.raises(PlatformFactorRejected):
            recovery.consume(
                session,
                platform_admin_id=admin_id,
                presented_code=codes[0],
                now=NOW + timedelta(minutes=1),
            )


def test_setup_challenge_rejects_unconsumed_expired_revoked_and_stale_versions(
    control_database,
):
    setup = PlatformAdminSetupService()
    hasher = PlatformPasswordHasher()
    with control_database.transaction() as session:
        expired = setup.create_pending_admin(
            session,
            username="expired.root",
            ttl=timedelta(minutes=1),
            now=NOW,
        )
        revoked = setup.create_pending_admin(
            session, username="revoked.root", now=NOW
        )
        stale = setup.create_pending_admin(
            session, username="stale.root", now=NOW
        )
        with pytest.raises(RuntimeError):
            setup.set_password(
                session,
                platform_admin_id=expired.platform_admin_id,
                expected_setup_version=1,
                password=PASSWORD,
                hasher=hasher,
                now=NOW,
            )

    with control_database.transaction() as session:
        revoked_row = session.scalar(
            sa.select(PlatformAdminSetupChallenge).where(
                PlatformAdminSetupChallenge.id == revoked.challenge_id
            )
        )
        revoked_row.state = "revoked"
        revoked_row.revoked_at = NOW + timedelta(seconds=1)
        stale_admin = session.get(PlatformAdmin, stale.platform_admin_id)
        stale_admin.setup_version += 1
        stale_admin.row_version += 1

    with control_database.new_session() as session:
        for token, checked_at in (
            (expired.plaintext_token, NOW + timedelta(minutes=1)),
            (revoked.plaintext_token, NOW + timedelta(seconds=2)),
            (stale.plaintext_token, NOW + timedelta(seconds=2)),
        ):
            result = setup.consume(
                session, presented_token=token, now=checked_at
            )
            assert not result.accepted
            assert result.platform_admin_id is None


def test_recovery_rotation_invalidates_previous_generation(control_database):
    admin_id, _, _, original_codes = _activate_admin(control_database)
    recovery = PlatformRecoveryCodeService()
    with control_database.transaction() as session:
        replacement = recovery.issue_codes(
            session,
            platform_admin_id=admin_id,
            count=6,
            now=NOW + timedelta(minutes=2),
        )
        replacement_codes = replacement.take_plaintext_codes()
        assert replacement.generation == 2

    with control_database.new_session() as session:
        with pytest.raises(PlatformFactorRejected):
            recovery.consume(
                session,
                platform_admin_id=admin_id,
                presented_code=original_codes[0],
                now=NOW + timedelta(minutes=3),
            )

    with control_database.transaction() as session:
        proof = recovery.consume(
            session,
            platform_admin_id=admin_id,
            presented_code=replacement_codes[0],
            now=NOW + timedelta(minutes=3),
        )
        assert proof.method == "recovery_code"


def test_totp_replacement_keeps_old_seed_until_atomic_confirmation(
    control_database,
):
    admin_id, old_seed, old_step, _codes = _activate_admin(control_database)
    replacement_seed = b"replacement-seed-123"
    totp = PlatformTotpService(seed_generator=lambda: replacement_seed)

    with control_database.transaction() as session:
        first = totp.create_pending_replacement(
            session,
            platform_admin_id=admin_id,
            root_key=ROOT_KEY,
            now=_time_for_step(old_step + 1),
        )
        first_id = first.credential_id
        assert base64.b32decode(first.take_base32_seed()) == replacement_seed

    # Restarting a lost enrollment only revokes the unconfirmed candidate.
    with control_database.transaction() as session:
        second = totp.create_pending_replacement(
            session,
            platform_admin_id=admin_id,
            root_key=ROOT_KEY,
            now=_time_for_step(old_step + 2),
        )
        replacement_id = second.credential_id
        second.take_base32_seed()

    with control_database.new_session() as session:
        admin = session.get(PlatformAdmin, admin_id)
        first_row = session.get(PlatformAdminTotpCredential, first_id)
        current = session.scalar(
            sa.select(PlatformAdminTotpCredential).where(
                PlatformAdminTotpCredential.platform_admin_id == admin_id,
                PlatformAdminTotpCredential.status == "confirmed",
            )
        )
        assert admin.totp_generation == 1
        assert first_row.status == "revoked"
        assert current.generation == 1

    # The current credential remains usable before the replacement confirms.
    with control_database.transaction() as session:
        proof = totp.verify_current(
            session,
            platform_admin_id=admin_id,
            presented_code=generate_totp_code(old_seed, old_step + 3),
            root_key=ROOT_KEY,
            now=_time_for_step(old_step + 3),
            allowed_drift_steps=0,
        )
        assert proof.method == "totp"

    replacement_step = old_step + 4
    with control_database.transaction() as session:
        generation = totp.confirm_replacement(
            session,
            platform_admin_id=admin_id,
            credential_id=replacement_id,
            presented_code=generate_totp_code(
                replacement_seed, replacement_step
            ),
            root_key=ROOT_KEY,
            now=_time_for_step(replacement_step),
            allowed_drift_steps=0,
        )
        assert generation == 3

    with control_database.new_session() as session:
        admin = session.get(PlatformAdmin, admin_id)
        live = list(
            session.scalars(
                sa.select(PlatformAdminTotpCredential)
                .where(
                    PlatformAdminTotpCredential.platform_admin_id == admin_id,
                    PlatformAdminTotpCredential.status.in_(
                        ("pending", "confirmed")
                    ),
                )
                .order_by(PlatformAdminTotpCredential.generation)
            )
        )
        assert admin.totp_generation == 3
        assert [(row.id, row.status) for row in live] == [
            (replacement_id, "confirmed")
        ]

    with control_database.new_session() as session:
        with pytest.raises(PlatformFactorRejected):
            totp.verify_current(
                session,
                platform_admin_id=admin_id,
                presented_code=generate_totp_code(old_seed, old_step + 5),
                root_key=ROOT_KEY,
                now=_time_for_step(old_step + 5),
                allowed_drift_steps=0,
            )


def test_platform_sessions_are_digest_only_versioned_expiring_and_revocable(
    control_database,
):
    admin_id, seed, confirmation_step, _ = _activate_admin(control_database)
    totp = PlatformTotpService()
    service = PlatformAdminSessionService()

    first = _issue_session(
        control_database,
        totp=totp,
        service=service,
        admin_id=admin_id,
        seed=seed,
        time_step=confirmation_step + 1,
    )
    second = _issue_session(
        control_database,
        totp=totp,
        service=service,
        admin_id=admin_id,
        seed=seed,
        time_step=confirmation_step + 2,
    )
    assert first.session_token not in repr(first)
    assert first.csrf_token not in repr(first)

    with control_database.new_session() as session:
        row = session.get(PlatformAdminSession, first.auth.session_id)
        assert row.token_digest_sha256 == digest_platform_session_token(
            first.session_token
        )
        assert row.csrf_digest_sha256 == digest_platform_csrf_token(
            first.csrf_token
        )
        assert "session_token" not in row.__table__.columns
        assert "csrf_token" not in row.__table__.columns
        assert all(
            forbidden not in row.__table__.columns
            for forbidden in ("tenant_id", "membership_id", "phone_e164")
        )

    first_time = _time_for_step(confirmation_step + 1)
    with control_database.transaction() as session:
        resolved = service.resolve(
            session,
            first.session_token,
            now=first_time + timedelta(minutes=1),
        )
        service.verify_csrf(
            session,
            auth=resolved,
            presented_csrf=first.csrf_token,
            now=first_time + timedelta(minutes=1),
        )
        with pytest.raises(PlatformCsrfAuthenticationError):
            service.verify_csrf(
                session,
                auth=resolved,
                presented_csrf=second.csrf_token,
                now=first_time + timedelta(minutes=1),
            )

    with control_database.transaction() as session:
        assert service.revoke_one(
            session,
            platform_admin_id=admin_id,
            target_session_id=second.auth.session_id,
            reason_code="admin_revoked_device",
            revoked_by_session_id=first.auth.session_id,
            now=first_time + timedelta(minutes=2),
        )
    with control_database.new_session() as session:
        with pytest.raises(PlatformSessionAuthenticationError):
            service.resolve(
                session,
                second.session_token,
                now=first_time + timedelta(minutes=3),
            )

    with control_database.transaction() as session:
        result = service.revoke_all(
            session,
            platform_admin_id=admin_id,
            reason_code="credential_reset",
            revoked_by_session_id=first.auth.session_id,
            now=first_time + timedelta(minutes=4),
        )
        assert result.revoked_count == 1
        assert result.new_auth_version == 2
    with control_database.new_session() as session:
        with pytest.raises(PlatformSessionAuthenticationError) as caught:
            service.resolve(
                session,
                first.session_token,
                now=first_time + timedelta(minutes=5),
            )
        assert first.session_token not in str(caught.value)
        with pytest.raises(PlatformSessionTargetUnavailable):
            service.revoke_one(
                session,
                platform_admin_id=str(uuid4()),
                target_session_id=first.auth.session_id,
                reason_code="cross_admin_attempt",
            )


def test_session_issue_proof_is_single_use_and_idle_expiry_is_exclusive(
    control_database,
):
    admin_id, seed, confirmation_step, _ = _activate_admin(control_database)
    totp = PlatformTotpService()
    service = PlatformAdminSessionService()
    time_step = confirmation_step + 1
    login_time = _time_for_step(time_step)
    code = generate_totp_code(seed, time_step)
    with control_database.transaction() as session:
        factor = totp.verify_current(
            session,
            platform_admin_id=admin_id,
            presented_code=code,
            root_key=ROOT_KEY,
            now=login_time,
            allowed_drift_steps=0,
        )
        issued = service.issue(
            session,
            factor=factor,
            idle_timeout=timedelta(minutes=5),
            absolute_timeout=timedelta(hours=1),
            now=login_time,
        )
        with pytest.raises(PlatformSessionIssueError):
            service.issue(
                session,
                factor=factor,
                idle_timeout=timedelta(minutes=5),
                absolute_timeout=timedelta(hours=1),
                now=login_time,
            )

    with control_database.new_session() as session:
        for token in (None, "malformed", issued.csrf_token):
            with pytest.raises(PlatformSessionAuthenticationError):
                service.resolve(
                    session, token, now=login_time + timedelta(minutes=1)
                )
        with pytest.raises(PlatformSessionAuthenticationError):
            service.resolve(
                session,
                issued.session_token,
                now=login_time + timedelta(minutes=5),
            )

    with control_database.transaction() as session:
        admin = session.get(PlatformAdmin, admin_id)
        admin.setup_version += 1
        admin.row_version += 1
        admin.updated_at = login_time + timedelta(minutes=1)
    with control_database.new_session() as session:
        with pytest.raises(PlatformSessionAuthenticationError):
            service.resolve(
                session,
                issued.session_token,
                now=login_time + timedelta(minutes=1),
            )


def test_host_bootstrap_creates_one_setup_challenge_and_safe_audit(
    control_database,
):
    service = PlatformAdminHostService()
    with control_database.transaction() as session:
        issued = service.create_pending_admin(
            session,
            username="new.root",
            setup_ttl=timedelta(minutes=10),
            os_operator_reference="ops:jim",
            command_id="command:bootstrap:1",
            now=NOW,
        )
    with control_database.new_session() as session:
        admin = session.get(PlatformAdmin, issued.platform_admin_id)
        audit = session.scalar(sa.select(PlatformAuditLog))
        assert admin.status == "setup_pending"
        assert audit.actor_type == "cli_break_glass"
        assert audit.action == "platform_admin.bootstrap"
        assert audit.target_platform_admin_id == admin.id
        serialized = " ".join(str(value) for value in audit.__dict__.values())
        assert issued.plaintext_token not in serialized


def test_host_credential_recovery_revokes_old_authority_and_is_consumable(
    control_database,
):
    admin_id, seed, confirmation_step, recovery_codes = _activate_admin(
        control_database
    )
    sessions = PlatformAdminSessionService()
    totp = PlatformTotpService()
    issued_session = _issue_session(
        control_database,
        totp=totp,
        service=sessions,
        admin_id=admin_id,
        seed=seed,
        time_step=confirmation_step + 1,
    )
    with control_database.new_session() as session:
        username = session.get(PlatformAdmin, admin_id).username_canonical
    reset_at = _time_for_step(confirmation_step + 2)
    service = PlatformAdminHostService()
    with control_database.transaction() as session:
        challenge = service.begin_credential_recovery(
            session,
            username=username,
            setup_ttl=timedelta(minutes=10),
            os_operator_reference="ops:jim",
            command_id="command:reset:1",
            now=reset_at,
        )

    with control_database.new_session() as session:
        admin = session.get(PlatformAdmin, admin_id)
        assert admin.status == "recovery_pending"
        assert admin.password_hash_encoded is None
        assert admin.auth_version == 2
        assert admin.setup_version == 2
        assert admin.totp_generation == 2
        assert admin.recovery_code_generation == 2
        assert session.get(
            PlatformAdminSession, issued_session.auth.session_id
        ).revoked_reason_code == "credential_recovery"
        assert session.scalar(
            sa.select(sa.func.count(PlatformAdminTotpCredential.id)).where(
                PlatformAdminTotpCredential.status == "confirmed"
            )
        ) == 0
        assert session.scalar(
            sa.select(sa.func.count(PlatformAdminRecoveryCode.id)).where(
                PlatformAdminRecoveryCode.state == "active"
            )
        ) == 0
        audit = session.scalar(
            sa.select(PlatformAuditLog).where(
                PlatformAuditLog.action
                == "platform_admin.credential_recovery"
            )
        )
        assert audit.target_platform_admin_id == admin_id
        assert recovery_codes[0] not in " ".join(
            str(value) for value in audit.__dict__.values()
        )
        with pytest.raises(PlatformSessionAuthenticationError):
            sessions.resolve(
                session,
                issued_session.session_token,
                now=reset_at + timedelta(seconds=1),
            )

    setup = PlatformAdminSetupService()
    with control_database.transaction() as session:
        result = setup.consume(
            session,
            presented_token=challenge.plaintext_token,
            now=reset_at + timedelta(seconds=1),
        )
        assert result.accepted
        assert result.platform_admin_id == admin_id


def test_host_disable_requires_a_fully_active_successor_and_revokes_authority(
    control_database,
):
    target_id, seed, step, _codes = _activate_admin(control_database)
    sessions = PlatformAdminSessionService()
    issued_session = _issue_session(
        control_database,
        totp=PlatformTotpService(),
        service=sessions,
        admin_id=target_id,
        seed=seed,
        time_step=step + 1,
    )
    with control_database.new_session() as session:
        username = session.get(PlatformAdmin, target_id).username_canonical

    service = PlatformAdminHostService()
    with pytest.raises(PlatformHostOperationRejected):
        with control_database.transaction() as session:
            service.disable_admin(
                session,
                username=username,
                os_operator_reference="ops:jim",
                command_id="command:disable:rejected",
                now=_time_for_step(step + 2),
            )

    successor_id, _seed, _step, _codes = _activate_admin(control_database)
    with control_database.transaction() as session:
        result = service.disable_admin(
            session,
            username=username,
            os_operator_reference="ops:jim",
            command_id="command:disable:1",
            now=_time_for_step(step + 3),
        )
        assert result.platform_admin_id == target_id
        assert result.revoked_session_count == 1

    with control_database.new_session() as session:
        target = session.get(PlatformAdmin, target_id)
        successor = session.get(PlatformAdmin, successor_id)
        old_session = session.get(
            PlatformAdminSession, issued_session.auth.session_id
        )
        assert target.status == "disabled"
        assert target.disabled_at is not None
        assert target.auth_version == 2
        assert successor.status == "active"
        assert old_session.revoked_reason_code == "platform_admin_disabled"
        assert session.scalar(
            sa.select(sa.func.count(PlatformAdminTotpCredential.id)).where(
                PlatformAdminTotpCredential.platform_admin_id == target_id,
                PlatformAdminTotpCredential.status == "confirmed",
            )
        ) == 0
        assert session.scalar(
            sa.select(sa.func.count(PlatformAdminRecoveryCode.id)).where(
                PlatformAdminRecoveryCode.platform_admin_id == target_id,
                PlatformAdminRecoveryCode.state == "active",
            )
        ) == 0
        audit = session.scalar(
            sa.select(PlatformAuditLog).where(
                PlatformAuditLog.action == "platform_admin.disable"
            )
        )
        assert audit.target_platform_admin_id == target_id


def test_database_constraints_enforce_factor_uniqueness_and_isolation(
    control_database,
):
    platform_tables = [
        table
        for table in ControlBase.metadata.tables.values()
        if table.name.startswith("platform_admin")
    ]
    assert len(platform_tables) == 6
    for table in platform_tables:
        assert all(
            forbidden not in column.name
            for column in table.columns
            for forbidden in ("tenant", "membership", "phone")
        )
        for foreign_key in table.foreign_keys:
            assert foreign_key.column.table.name.startswith("platform_admin")

    with control_database.new_session() as session:
        admin = PlatformAdmin(
            username_canonical="unique.root",
            status="setup_pending",
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(admin)
        session.flush()
        for generation in (1, 2):
            session.add(
                PlatformAdminTotpCredential(
                    platform_admin_id=admin.id,
                    generation=generation,
                    secret_revision=1,
                    status="confirmed",
                    seed_nonce=b"n" * 12,
                    seed_ciphertext=b"c" * 32,
                    root_key_version=1,
                    crypto_version=1,
                    aad_version=1,
                    last_accepted_time_step=generation,
                    created_at=NOW,
                    confirmed_at=NOW,
                )
            )
        with pytest.raises(DBAPIError):
            session.flush()
        session.rollback()

    with control_database.new_session() as session:
        session.add(
            PlatformAdminRateLimitCounter(
                scope="mfa",
                subject_digest_sha256=b"s" * 32,
                window_kind="rolling_hour",
                window_started_at=NOW,
                attempt_count=0,
                policy_version=1,
                expires_at=NOW + timedelta(hours=1),
                created_at=NOW,
                updated_at=NOW,
            )
        )
        with pytest.raises(DBAPIError):
            session.flush()
        session.rollback()


def _activate_admin(control_database):
    setup = PlatformAdminSetupService()
    totp = PlatformTotpService(seed_generator=lambda: SEED)
    recovery = PlatformRecoveryCodeService()
    hasher = PlatformPasswordHasher()
    with control_database.transaction() as session:
        challenge = setup.create_pending_admin(
            session,
            username=f"root.{uuid4().hex[:10]}",
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
    confirmation_time = NOW + timedelta(seconds=2)
    confirmation_step = totp_time_step(int(confirmation_time.timestamp()))
    with control_database.transaction() as session:
        totp.confirm_pending(
            session,
            credential_id=credential_id,
            presented_code=generate_totp_code(SEED, confirmation_step),
            root_key=ROOT_KEY,
            now=confirmation_time,
            allowed_drift_steps=0,
        )
        batch = recovery.issue_codes(
            session,
            platform_admin_id=admin_id,
            count=6,
            now=confirmation_time,
        )
        recovery_codes = batch.take_plaintext_codes()
        activate_admin_if_ready(
            session,
            platform_admin_id=admin_id,
            expected_setup_version=1,
            now=confirmation_time,
        )
    return admin_id, SEED, confirmation_step, recovery_codes


def _issue_session(
    control_database,
    *,
    totp,
    service,
    admin_id,
    seed,
    time_step,
):
    login_time = _time_for_step(time_step)
    with control_database.transaction() as session:
        factor = totp.verify_current(
            session,
            platform_admin_id=admin_id,
            presented_code=generate_totp_code(seed, time_step),
            root_key=ROOT_KEY,
            now=login_time,
            allowed_drift_steps=0,
        )
        return service.issue(
            session,
            factor=factor,
            idle_timeout=timedelta(minutes=30),
            absolute_timeout=timedelta(hours=8),
            now=login_time,
        )


def _time_for_step(time_step: int) -> datetime:
    return datetime.fromtimestamp(time_step * 30 + 1, tz=timezone.utc)
