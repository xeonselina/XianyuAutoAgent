from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from inventory_control import ControlBase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"
INTENT_TABLE = "tenant_sensitive_action_intents"
LINK_TABLE = "tenant_sensitive_action_intent_challenges"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_sensitive_action_migration_round_trip_matches_metadata(
    mysql_control_migration_url,
) -> None:
    database_url = mysql_control_migration_url
    config = _alembic_config(database_url)

    command.upgrade(config, "202608220026")
    engine = sa.create_engine(database_url)
    try:
        assert {INTENT_TABLE, LINK_TABLE}.isdisjoint(
            sa.inspect(engine).get_table_names()
        )
    finally:
        engine.dispose()

    command.upgrade(config, "202608220027")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        assert {INTENT_TABLE, LINK_TABLE} <= set(inspector.get_table_names())
        intent_unique_sets = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints(INTENT_TABLE)
        }
        link_unique_sets = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints(LINK_TABLE)
        }
        assert ("tenant_id", "idempotency_key") in intent_unique_sets
        assert ("challenge_id",) in link_unique_sets
        assert {
            "ix_sensitive_action_intents_actor_created",
            "ix_sensitive_action_intents_tenant_status_expiry",
        } <= {
            item["name"] for item in inspector.get_indexes(INTENT_TABLE)
        }
    finally:
        engine.dispose()

    command.downgrade(config, "202608220026")
    engine = sa.create_engine(database_url)
    try:
        assert {INTENT_TABLE, LINK_TABLE}.isdisjoint(
            sa.inspect(engine).get_table_names()
        )
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
