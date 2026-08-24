from __future__ import annotations

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
CLAIM_TABLES = {
    "provider_account_claims",
    "provider_account_claim_events",
}
ZERO_HASH = b"\x00" * 32


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_provider_claim_migration_round_trip_matches_current_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    config = _alembic_config(database_url)

    command.upgrade(config, "202608220013")
    engine = sa.create_engine(database_url)
    try:
        assert CLAIM_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220014")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        assert CLAIM_TABLES <= set(inspector.get_table_names())
        claim_foreign_keys = inspector.get_foreign_keys(
            "provider_account_claims"
        )
        event_foreign_keys = inspector.get_foreign_keys(
            "provider_account_claim_events"
        )
        assert claim_foreign_keys == []
        assert {
            foreign_key["referred_table"] for foreign_key in event_foreign_keys
        } == {"provider_account_claims"}
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

    command.downgrade(config, "202608220013")
    engine = sa.create_engine(database_url)
    try:
        assert CLAIM_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220014")
    engine = sa.create_engine(database_url)
    try:
        assert CLAIM_TABLES <= set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_provider_claim_migration_enforces_permanent_unique_claim_state(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    command.upgrade(_alembic_config(database_url), "202608220014")
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    metadata.reflect(engine, only=tuple(CLAIM_TABLES))
    claims = metadata.tables["provider_account_claims"]

    released = {
        "id": "11111111-1111-4111-8111-111111111111",
        "provider": "sf",
        "account_fingerprint": b"f" * 32,
        "fingerprint_version": 1,
        "fingerprint_root_key_version": 1,
        "claim_status": "released",
        "claim_generation": 1,
        "event_sequence": 0,
        "event_head_hash": ZERO_HASH,
        "row_version": 1,
    }
    try:
        with engine.begin() as connection:
            connection.execute(sa.insert(claims).values(**released))

        with pytest.raises((IntegrityError, OperationalError)):
            with engine.begin() as connection:
                connection.execute(
                    sa.insert(claims).values(
                        **{
                            **released,
                            "id": "22222222-2222-4222-8222-222222222222",
                        }
                    )
                )

        with pytest.raises((IntegrityError, OperationalError)):
            with engine.begin() as connection:
                connection.execute(
                    sa.update(claims)
                    .where(claims.c.id == released["id"])
                    .values(
                        claim_status="active",
                        current_tenant_id=(
                            "33333333-3333-4333-8333-333333333333"
                        ),
                    )
                )
    finally:
        engine.dispose()


def test_provider_claim_migration_emits_mysql_8_compatible_offline_ddl():
    output = StringIO()
    config = _alembic_config("mysql+pymysql://unused:unused@localhost/control")
    config.output_buffer = output

    command.upgrade(config, "202608220013:202608220014", sql=True)
    ddl = output.getvalue()
    lower_ddl = ddl.lower()

    assert "CREATE TABLE provider_account_claims" in ddl
    assert "CREATE TABLE provider_account_claim_events" in ddl
    assert "BINARY(32)" in ddl
    assert "uq_provider_claims_provider_fingerprint" in ddl
    assert "uq_provider_claim_events_claim_generation" in ddl
    assert "FOREIGN KEY(provider_account_claim_id)" in ddl
    assert "FOREIGN KEY(current_tenant_id)" not in ddl
    assert all(len(name) <= 64 for name in _constraint_names(ddl))
    for forbidden in ("password", "ciphertext", "credential_secret", "dsn"):
        assert forbidden not in lower_ddl


def _constraint_names(ddl: str) -> tuple[str, ...]:
    names: list[str] = []
    words = ddl.replace("\n", " ").replace("`", "").split()
    for index, word in enumerate(words[:-1]):
        if word.upper() == "CONSTRAINT":
            names.append(words[index + 1])
    return tuple(names)
