from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.exc import IntegrityError, OperationalError

from inventory_control.models import ControlBase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"
ACCOUNT_TABLES = {
    "tenant_provider_accounts",
    "tenant_provider_account_secret_revisions",
    "tenant_provider_account_secret_envelope_events",
}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_provider_account_migration_round_trip_matches_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    config = _alembic_config(database_url)

    command.upgrade(config, "202608220028")
    engine = sa.create_engine(database_url)
    try:
        assert ACCOUNT_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220029")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        assert ACCOUNT_TABLES <= set(inspector.get_table_names())
        account_columns = {
            item["name"] for item in inspector.get_columns("tenant_provider_accounts")
        }
        revision_columns = {
            item["name"]
            for item in inspector.get_columns(
                "tenant_provider_account_secret_revisions"
            )
        }
        assert {
            "current_secret_revision_id",
            "current_global_claim_id",
            "current_claim_generation",
            "masked_hint",
            "row_version",
        } <= account_columns
        assert {
            "crypto_context_uuid",
            "account_secret_ciphertext",
            "account_secret_nonce",
            "provider_account_claim_id",
            "account_fingerprint",
            "expected_claim_generation",
            "expected_claim_row_version",
            "target_binding_revision",
            "expected_account_absent",
            "expected_warehouse_binding_revision",
            "activated_claim_generation",
            "validation_integration_secret_revision_id",
            "current_provider_account_id",
        } <= revision_columns
        assert {
            "monthly_account",
            "account_plaintext",
            "password",
            "secret_value",
        }.isdisjoint(account_columns | revision_columns)
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

    command.downgrade(config, "202608220028")
    engine = sa.create_engine(database_url)
    try:
        assert ACCOUNT_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220029")
    engine = sa.create_engine(database_url)
    try:
        assert ACCOUNT_TABLES <= set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_provider_account_revision_allows_only_one_current_row(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    command.upgrade(_alembic_config(database_url), "head")
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    metadata.reflect(engine)
    tenants = metadata.tables["tenants"]
    integrations = metadata.tables["tenant_integrations"]
    claims = metadata.tables["provider_account_claims"]
    accounts = metadata.tables["tenant_provider_accounts"]
    revisions = metadata.tables["tenant_provider_account_secret_revisions"]
    tenant_uuid = "11111111-1111-4111-8111-111111111111"
    integration_uuid = "22222222-2222-4222-8222-222222222222"
    claim_uuid = "33333333-3333-4333-8333-333333333333"
    account_uuid = "44444444-4444-4444-8444-444444444444"
    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.insert(tenants).values(id=tenant_uuid, status="provisioning")
            )
            connection.execute(
                sa.insert(integrations).values(
                    id=integration_uuid,
                    tenant_id=tenant_uuid,
                    provider="sf",
                    name="default-sf",
                    config_json="{}",
                    status="unconfigured",
                    row_version=1,
                )
            )
            connection.execute(
                sa.insert(claims).values(
                    id=claim_uuid,
                    provider="sf",
                    account_fingerprint=b"f" * 32,
                    fingerprint_version=1,
                    fingerprint_root_key_version=1,
                    claim_status="released",
                    claim_generation=1,
                    event_sequence=0,
                    event_head_hash=b"\x00" * 32,
                    row_version=1,
                )
            )
            connection.execute(
                sa.insert(accounts).values(
                    id=account_uuid,
                    tenant_id=tenant_uuid,
                    provider="sf",
                    integration_id=integration_uuid,
                    label="Main warehouse",
                    masked_hint="****1234",
                    status="pending",
                    row_version=1,
                )
            )

            def current_revision(number: int) -> dict[str, object]:
                return {
                    "id": f"55555555-5555-4555-8555-{number:012d}",
                    "tenant_provider_account_id": account_uuid,
                    "tenant_id": tenant_uuid,
                    "provider": "sf",
                    "integration_id": integration_uuid,
                    "revision_no": number,
                    "crypto_context_uuid": f"66666666-6666-4666-8666-{number:012d}",
                    "account_secret_schema_version": 1,
                    "account_secret_bundle_version": 1,
                    "canonical_semantics_digest": b"s" * 32,
                    "account_secret_ciphertext": b"c" * 16,
                    "account_secret_nonce": b"n" * 12,
                    "root_key_version": 1,
                    "crypto_version": 1,
                    "aad_version": 1,
                    "provider_account_claim_id": claim_uuid,
                    "account_fingerprint": b"f" * 32,
                    "fingerprint_version": 1,
                    "fingerprint_root_key_version": 1,
                    "expected_claim_generation": number,
                    "expected_claim_row_version": number,
                    "target_binding_revision": 1,
                    "expected_warehouse_provider_account_id": None,
                    "expected_warehouse_binding_revision": None,
                    "activated_claim_generation": number + 1,
                    "masked_hint": "****1234",
                    "status": "current",
                    "created_from_action_uuid": (
                        f"77777777-7777-4777-8777-{number:012d}"
                    ),
                    "created_by_user_uuid": (
                        "88888888-8888-4888-8888-888888888888"
                    ),
                    "request_idempotency_key": f"provider-account-{number}",
                    "request_digest": bytes([number]) * 32,
                    "expected_account_absent": True,
                    "expected_account_row_version": number,
                    "expected_integration_row_version": 1,
                    "validation_integration_secret_revision_id": (
                        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
                    ),
                    "verification_status": "succeeded",
                    "verification_attempt_uuid": (
                        f"99999999-9999-4999-8999-{number:012d}"
                    ),
                    "verification_result_digest": bytes([number + 10]) * 32,
                    "verification_safe_code": "VALID",
                    "verification_completed_at": now,
                    "activated_at": now,
                    "row_version": 1,
                }

            connection.execute(sa.insert(revisions).values(**current_revision(1)))

        with pytest.raises((IntegrityError, OperationalError)):
            with engine.begin() as connection:
                connection.execute(sa.insert(revisions).values(**current_revision(2)))
    finally:
        engine.dispose()


def test_provider_account_migration_emits_mysql_compatible_offline_ddl():
    output = StringIO()
    config = _alembic_config("mysql+pymysql://unused:unused@localhost/control")
    config.output_buffer = output

    command.upgrade(config, "202608220028:202608220029", sql=True)
    ddl = output.getvalue()
    lower_ddl = ddl.lower()

    assert "CREATE TABLE tenant_provider_accounts" in ddl
    assert "CREATE TABLE tenant_provider_account_secret_revisions" in ddl
    assert "CREATE TABLE tenant_provider_account_secret_envelope_events" in ddl
    assert "GENERATED ALWAYS AS" in ddl
    assert "BINARY(32)" in ddl
    assert "BINARY(12)" in ddl
    assert "fk_account_secret_revisions_claim" in ddl
    assert "FOREIGN KEY(current_provider_account_id)" not in ddl
    assert all(len(name) <= 64 for name in _constraint_names(ddl))
    for forbidden in ("account_plaintext", "monthly_account", "password", "secret_value"):
        assert forbidden not in lower_ddl


def _constraint_names(ddl: str) -> tuple[str, ...]:
    names: list[str] = []
    words = ddl.replace("\n", " ").replace("`", "").split()
    for index, word in enumerate(words[:-1]):
        if word.upper() == "CONSTRAINT":
            names.append(words[index + 1])
    return tuple(names)
