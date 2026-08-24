from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from inventory_control import ControlBase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_sms_migration_upgrade_downgrade_upgrade_matches_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    config = _alembic_config(database_url)
    sms_tables = {"sms_challenges", "sms_rate_limit_subjects"}

    command.upgrade(config, "202608220003")
    engine = sa.create_engine(database_url)
    try:
        assert sms_tables.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220004")
    engine = sa.create_engine(database_url)
    try:
        assert sms_tables <= set(sa.inspect(engine).get_table_names())
        inspector = sa.inspect(engine)
        assert {
            index["name"] for index in inspector.get_indexes("sms_challenges")
        } >= {
            "ix_sms_challenges_phone_purpose_current",
            "ix_sms_challenges_phone_rate_window",
            "ix_sms_challenges_source_rate_window",
        }
    finally:
        engine.dispose()

    command.downgrade(config, "202608220003")
    engine = sa.create_engine(database_url)
    try:
        tables = set(sa.inspect(engine).get_table_names())
        assert sms_tables.isdisjoint(tables)
        assert {"users", "tenant_memberships", "tenant_user_sessions"} <= tables
    finally:
        engine.dispose()

    command.upgrade(config, "202608220004")
    command.upgrade(config, "head")
    engine = sa.create_engine(database_url)
    try:
        assert sms_tables <= set(sa.inspect(engine).get_table_names())
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert compare_metadata(context, ControlBase.metadata) == []
    finally:
        engine.dispose()
