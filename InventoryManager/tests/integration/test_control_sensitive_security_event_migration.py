from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from inventory_control import ControlBase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"
TABLE = "tenant_auth_security_events"
EXPANDED_COLUMNS = {
    "target_resource_type",
    "target_resource_id",
    "expected_target_revision",
    "challenge_id",
    "intent_id",
    "action_subtype",
    "idempotency_reference",
    "safe_outcome",
}


def _config(database_url: str) -> Config:
    value = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    value.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    value.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return value


def test_sensitive_security_event_expansion_round_trip(
    mysql_control_migration_url,
) -> None:
    database_url = mysql_control_migration_url
    config = _config(database_url)
    command.upgrade(config, "202608220027")
    engine = sa.create_engine(database_url)
    try:
        columns = {
            item["name"] for item in sa.inspect(engine).get_columns(TABLE)
        }
        assert EXPANDED_COLUMNS.isdisjoint(columns)
    finally:
        engine.dispose()

    command.upgrade(config, "202608220028")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        columns = {item["name"] for item in inspector.get_columns(TABLE)}
        foreign_columns = {
            tuple(item["constrained_columns"])
            for item in inspector.get_foreign_keys(TABLE)
        }
        assert EXPANDED_COLUMNS <= columns
        assert {("challenge_id",), ("intent_id",)} <= foreign_columns
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

    command.downgrade(config, "202608220027")
    engine = sa.create_engine(database_url)
    try:
        columns = {
            item["name"] for item in sa.inspect(engine).get_columns(TABLE)
        }
        assert EXPANDED_COLUMNS.isdisjoint(columns)
    finally:
        engine.dispose()

    command.upgrade(config, "head")
