from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_tenant_identity_migration_round_trip_matches_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    config = _alembic_config(database_url)
    identity_tables = {"users", "tenant_memberships", "tenant_user_sessions"}

    command.upgrade(config, "202608220002")
    engine = sa.create_engine(database_url)
    try:
        assert identity_tables.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220003")
    engine = sa.create_engine(database_url)
    try:
        assert identity_tables <= set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.downgrade(config, "202608220002")
    engine = sa.create_engine(database_url)
    try:
        tables = set(sa.inspect(engine).get_table_names())
        assert identity_tables.isdisjoint(tables)
        assert {"background_jobs", "control_outbox_events"} <= tables
    finally:
        engine.dispose()

    command.upgrade(config, "202608220003")
    engine = sa.create_engine(database_url)
    try:
        assert identity_tables <= set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()
