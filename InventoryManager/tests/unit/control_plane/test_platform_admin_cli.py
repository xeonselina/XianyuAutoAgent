from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

from inventory_control import ControlDatabase
from inventory_control.models import (
    ControlBase,
    PlatformAdmin,
    PlatformAdminRecoveryCode,
    PlatformAdminSetupChallenge,
    PlatformAdminTotpCredential,
    PlatformAuditLog,
    User,
)
from inventory_control.platform_identity import PlatformAdminCliApplication


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


def test_cli_create_accepts_only_nonsecret_inputs_and_emits_token_once(
    control_database,
):
    stdout = io.StringIO()
    stderr = io.StringIO()
    application = PlatformAdminCliApplication(
        control_database=control_database
    )
    exit_code = application.execute(
        [
            "platform-admin",
            "create",
            "--username",
            "root.admin",
            "--setup-ttl-seconds",
            "600",
            "--os-operator-reference",
            "ops:jim",
            "--command-id",
            "command:bootstrap:1",
        ],
        stdout=stdout,
        stderr=stderr,
    )
    assert exit_code == 0
    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert payload["setup_token"].startswith("imps1_")
    with control_database.new_session() as session:
        admin = session.scalar(sa.select(PlatformAdmin))
        challenge = session.scalar(sa.select(PlatformAdminSetupChallenge))
        audit = session.scalar(sa.select(PlatformAuditLog))
        assert admin.id == payload["platform_admin_id"]
        assert challenge.platform_admin_id == admin.id
        assert audit.action == "platform_admin.bootstrap"
        persisted = " ".join(
            str(value)
            for row in (admin, challenge, audit)
            for value in row.__dict__.values()
        )
        assert payload["setup_token"] not in persisted


def test_cli_parser_rejects_password_seed_and_recovery_code_arguments(
    control_database,
):
    application = PlatformAdminCliApplication(
        control_database=control_database
    )
    for forbidden_option in ("--password", "--totp-seed", "--recovery-code"):
        stdout = io.StringIO()
        stderr = io.StringIO()
        exit_code = application.execute(
            [
                "platform-admin",
                "create",
                "--username",
                "root.admin",
                "--setup-ttl-seconds",
                "600",
                "--os-operator-reference",
                "ops:jim",
                "--command-id",
                "command:bootstrap:1",
                forbidden_option,
                "credential-material",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        assert exit_code == 2
        assert "credential-material" not in stdout.getvalue()
        assert "credential-material" not in stderr.getvalue()
    with control_database.new_session() as session:
        assert session.scalar(sa.select(sa.func.count(PlatformAdmin.id))) == 0


@pytest.mark.parametrize(
    "forbidden_arguments",
    [
        ["tenant-user", "change-phone"],
        ["platform-admin", "impersonate", "--username", "root.admin"],
        ["platform-admin", "phone-override", "--username", "root.admin"],
        ["platform-admin", "submit-tenant-otp", "--username", "root.admin"],
        ["platform-admin", "recover-last-admin", "--username", "root.admin"],
    ],
)
def test_cli_has_no_tenant_identity_recovery_commands(
    control_database,
    forbidden_arguments,
):
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert PlatformAdminCliApplication(
        control_database=control_database
    ).execute(
        forbidden_arguments,
        stdout=stdout,
        stderr=stderr,
    ) == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue().endswith("inventoryctl: invalid arguments\n")
    with control_database.new_session() as session:
        assert session.scalar(sa.select(sa.func.count(User.id))) == 0


def test_cli_duplicate_create_fails_without_echoing_username(control_database):
    application = PlatformAdminCliApplication(
        control_database=control_database
    )
    arguments = [
        "platform-admin",
        "create",
        "--username",
        "root.admin",
        "--setup-ttl-seconds",
        "600",
        "--os-operator-reference",
        "ops:jim",
        "--command-id",
        "command:bootstrap:1",
    ]
    assert application.execute(
        arguments,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    ) == 0
    stdout = io.StringIO()
    stderr = io.StringIO()
    assert application.execute(
        arguments,
        stdout=stdout,
        stderr=stderr,
    ) == 1
    assert stdout.getvalue() == ""
    assert "root.admin" not in stderr.getvalue()
    with control_database.new_session() as session:
        assert session.scalar(sa.select(sa.func.count(PlatformAdmin.id))) == 1
        assert session.scalar(
            sa.select(sa.func.count(PlatformAuditLog.id))
        ) == 1


def test_cli_disable_refuses_last_active_admin_then_accepts_active_successor(
    control_database,
):
    with control_database.transaction() as session:
        target_id = _add_active_admin(session, "root.admin", marker=b"a")
    application = PlatformAdminCliApplication(
        control_database=control_database
    )
    arguments = [
        "platform-admin",
        "disable",
        "--username",
        "root.admin",
        "--os-operator-reference",
        "ops:jim",
        "--command-id",
        "command:disable:1",
    ]
    assert application.execute(
        arguments, stdout=io.StringIO(), stderr=io.StringIO()
    ) == 1

    with control_database.transaction() as session:
        _add_active_admin(session, "successor.admin", marker=b"b")
    stdout = io.StringIO()
    stderr = io.StringIO()
    assert application.execute(
        arguments, stdout=stdout, stderr=stderr
    ) == 0
    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert payload == {
        "platform_admin_id": target_id,
        "revoked_session_count": 0,
        "status": "disabled",
    }
    assert "setup_token" not in payload
    with control_database.new_session() as session:
        target = session.get(PlatformAdmin, target_id)
        assert target.status == "disabled"
        assert session.scalar(
            sa.select(sa.func.count(PlatformAuditLog.id)).where(
                PlatformAuditLog.action == "platform_admin.disable"
            )
        ) == 1


def _add_active_admin(session, username: str, *, marker: bytes) -> str:
    now = datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc)
    admin = PlatformAdmin(
        username_canonical=username,
        status="active",
        password_hash_encoded="encoded-password-hash",
        password_hash_algorithm="argon2id",
        password_hash_version=1,
        created_at=now,
        updated_at=now,
    )
    session.add(admin)
    session.flush()
    session.add_all(
        [
            PlatformAdminTotpCredential(
                platform_admin_id=admin.id,
                generation=1,
                secret_revision=1,
                status="confirmed",
                seed_nonce=marker * 12,
                seed_ciphertext=marker * 32,
                root_key_version=1,
                crypto_version=1,
                aad_version=1,
                totp_algorithm="SHA1",
                totp_digits=6,
                totp_period_seconds=30,
                row_version=1,
                created_at=now,
                confirmed_at=now,
            ),
            PlatformAdminRecoveryCode(
                platform_admin_id=admin.id,
                generation=1,
                ordinal=1,
                token_digest_sha256=marker * 32,
                state="active",
                row_version=1,
                created_at=now,
            ),
        ]
    )
    session.flush()
    return admin.id
