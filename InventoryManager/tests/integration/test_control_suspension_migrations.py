from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
import re

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.exc import IntegrityError, OperationalError

from inventory_control.models import ControlBase
from inventory_control.models.suspensions import (
    TenantSuspension,
    TenantSuspensionAction,
)

# Register the concurrently introduced 0020 model until root-level exports
# are merged.  This test does not modify that model or its migration.
import inventory_control.models.schema_operations  # noqa: F401, E402


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"
SUSPENSIONS = "tenant_suspensions"
ACTIONS = "tenant_suspension_actions"
TABLES = {SUSPENSIONS, ACTIONS}
NOW = datetime(2026, 8, 22, 12, 0, 0, 654321, tzinfo=timezone.utc)


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_suspension_migration_round_trip_and_head_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    config = _alembic_config(database_url)

    command.upgrade(config, "202608220018")
    engine = sa.create_engine(database_url)
    try:
        assert TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220019")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        assert TABLES <= set(inspector.get_table_names())
        assert {
            column["name"] for column in inspector.get_columns(SUSPENSIONS)
        } == {column.name for column in TenantSuspension.__table__.columns}
        assert {
            column["name"] for column in inspector.get_columns(ACTIONS)
        } == {column.name for column in TenantSuspensionAction.__table__.columns}
        assert inspector.get_pk_constraint(SUSPENSIONS)["constrained_columns"] == [
            "id"
        ]
        action_foreign_keys = {
            tuple(foreign_key["constrained_columns"])
            for foreign_key in inspector.get_foreign_keys(ACTIONS)
        }
        assert action_foreign_keys == {
            ("suspension_id",),
            ("platform_admin_id",),
            ("platform_session_id",),
        }
        assert TenantSuspensionAction.__table__.c.request_digest.type.length == 32
    finally:
        engine.dispose()

    command.downgrade(config, "202608220018")
    engine = sa.create_engine(database_url)
    try:
        assert TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = sa.create_engine(database_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert compare_metadata(context, ControlBase.metadata) == []
    finally:
        engine.dispose()


def test_suspension_migration_enforces_active_and_authority_facts(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    command.upgrade(_alembic_config(database_url), "202608220019")
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    metadata.reflect(
        engine,
        only=(
            *TABLES,
            "tenants",
            "platform_admins",
            "platform_admin_totp_credentials",
            "platform_admin_sessions",
        ),
    )
    suspensions = metadata.tables[SUSPENSIONS]
    actions = metadata.tables[ACTIONS]
    tenants = metadata.tables["tenants"]
    platform_admins = metadata.tables["platform_admins"]
    totp_credentials = metadata.tables["platform_admin_totp_credentials"]
    platform_sessions = metadata.tables["platform_admin_sessions"]

    aggregate = {
        "id": "19100000-0000-4000-8000-000000000001",
        "tenant_id": "19100000-0000-4000-8000-000000000002",
        "state": "freezing",
        "initial_reason_code": "security_incident",
        "barrier_generation": 1,
        "committed_tenant_row_version": 4,
        "committed_access_version": 8,
        "requested_at": NOW,
        "row_version": 1,
    }
    action = {
        "id": "19100000-0000-4000-8000-000000000003",
        "suspension_id": aggregate["id"],
        "direction": "freeze",
        "generation": 1,
        "actor_type": "platform_admin",
        "platform_admin_id": "19100000-0000-4000-8000-000000000004",
        "platform_session_id": "19100000-0000-4000-8000-000000000005",
        "recent_step_up_method": "totp",
        "recent_step_up_at": NOW,
        "authorization_source": "user_step_up",
        "reason_code": "security_incident",
        "idempotency_key": "freeze-191",
        "request_digest": b"d" * 32,
        "expected_suspension_row_version": 0,
        "expected_tenant_row_version": 3,
        "expected_access_version": 7,
        "state": "running",
        "requested_at": NOW,
        "started_at": NOW,
        "row_version": 1,
    }
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.insert(tenants).values(
                    id=aggregate["tenant_id"],
                    status="provisioning",
                )
            )
            connection.execute(
                sa.insert(platform_admins).values(
                    id=action["platform_admin_id"],
                    username_canonical="admin191",
                    status="setup_pending",
                )
            )
            connection.execute(
                sa.insert(totp_credentials).values(
                    id="19100000-0000-4000-8000-000000000006",
                    platform_admin_id=action["platform_admin_id"],
                    generation=1,
                    secret_revision=1,
                    status="pending",
                    seed_nonce=b"n" * 12,
                    seed_ciphertext=b"c" * 16,
                    root_key_version=1,
                    crypto_version=1,
                    aad_version=1,
                    created_at=NOW,
                )
            )
            connection.execute(
                sa.insert(platform_sessions).values(
                    id=action["platform_session_id"],
                    platform_admin_id=action["platform_admin_id"],
                    token_digest_sha256=b"t" * 32,
                    csrf_digest_sha256=b"c" * 32,
                    auth_version_at_issue=1,
                    setup_version_at_issue=1,
                    mfa_method="totp",
                    mfa_verified_at=NOW,
                    totp_credential_id=(
                        "19100000-0000-4000-8000-000000000006"
                    ),
                    totp_time_step=1,
                    policy_version=1,
                    idle_timeout_seconds=300,
                    created_at=NOW,
                    last_seen_at=NOW,
                    idle_expires_at=NOW + timedelta(minutes=5),
                    absolute_expires_at=NOW + timedelta(minutes=10),
                )
            )
            connection.execute(sa.insert(suspensions).values(**aggregate))
            connection.execute(sa.insert(actions).values(**action))

        with pytest.raises((IntegrityError, OperationalError)):
            with engine.begin() as connection:
                connection.execute(
                    sa.insert(suspensions).values(
                        **{
                            **aggregate,
                            "id": "19100000-0000-4000-8000-000000000006",
                        }
                    )
                )

        invalid_actions = (
            {
                **action,
                "id": "19100000-0000-4000-8000-000000000007",
                "generation": 2,
                "idempotency_key": "invalid-system-freeze",
                "actor_type": "system",
                "platform_admin_id": None,
                "platform_session_id": None,
                "recent_step_up_method": None,
                "recent_step_up_at": None,
                "authorization_source": "dr_recovery",
                "authorization_source_uuid": (
                    "19100000-0000-4000-8000-000000000008"
                ),
            },
            {
                **action,
                "id": "19100000-0000-4000-8000-000000000009",
                "generation": 3,
                "idempotency_key": "invalid-admin-enforce",
                "direction": "enforce_locked",
            },
        )
        for invalid in invalid_actions:
            with pytest.raises((IntegrityError, OperationalError)):
                with engine.begin() as connection:
                    connection.execute(sa.insert(actions).values(**invalid))

        padded_digest_action = {
            **action,
            "id": "19100000-0000-4000-8000-00000000000a",
            "generation": 4,
            "idempotency_key": "short-digest",
            "request_digest": b"short",
        }
        with engine.begin() as connection:
            connection.execute(sa.insert(actions).values(**padded_digest_action))
            stored_length = connection.scalar(
                sa.select(sa.func.length(actions.c.request_digest)).where(
                    actions.c.id == padded_digest_action["id"]
                )
            )
        assert stored_length == 32

        valid_system_action = {
            **action,
            "id": "19100000-0000-4000-8000-00000000000b",
            "generation": 2,
            "idempotency_key": "valid-enforce",
            "direction": "enforce_locked",
            "actor_type": "system",
            "platform_admin_id": None,
            "platform_session_id": None,
            "recent_step_up_method": None,
            "recent_step_up_at": None,
            "authorization_source": "deletion_request",
            "authorization_source_uuid": (
                "19100000-0000-4000-8000-00000000000c"
            ),
        }
        with engine.begin() as connection:
            connection.execute(sa.insert(actions).values(**valid_system_action))
    finally:
        engine.dispose()


def test_suspension_migration_emits_mysql8_microsecond_offline_ddl():
    output = StringIO()
    config = _alembic_config(
        "mysql+pymysql://unused:unused@localhost/inventory_control"
    )
    config.output_buffer = output

    command.upgrade(config, "202608220018:202608220019", sql=True)
    ddl = output.getvalue()
    lower_ddl = ddl.lower()

    assert f"CREATE TABLE {SUSPENSIONS}" in ddl
    assert f"CREATE TABLE {ACTIONS}" in ddl
    assert "active_tenant_id VARCHAR(36) GENERATED ALWAYS AS" in ddl
    assert "request_digest BINARY(32) NOT NULL" in ddl
    for column in (
        "requested_at",
        "frozen_at",
        "resolving_at",
        "resolved_at",
        "recent_step_up_at",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
    ):
        assert re.search(rf"\b{column} DATETIME\(6\)", ddl)
    for column in ("created_at", "updated_at"):
        assert len(
            re.findall(
                rf"\b{column} DATETIME\(6\) NOT NULL "
                r"DEFAULT CURRENT_TIMESTAMP\(6\)",
                ddl,
            )
        ) == 2
    assert "direction = 'enforce_locked' AND actor_type = 'system'" in ddl
    assert "authorization_source IN ('deletion_request', 'dr_recovery')" in ddl
    assert all(len(name) <= 64 for name in _constraint_names(ddl))
    for forbidden in (
        "password_hash",
        "ciphertext",
        "credential_secret",
        "connection_url",
        " dsn ",
    ):
        assert forbidden not in lower_ddl


def _constraint_names(ddl: str) -> tuple[str, ...]:
    return tuple(
        match.group(1).strip("`")
        for match in re.finditer(
            r"(?:CONSTRAINT|KEY|INDEX)\s+(`?[A-Za-z0-9_]+`?)",
            ddl,
            flags=re.IGNORECASE,
        )
    )
