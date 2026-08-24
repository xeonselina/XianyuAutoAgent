from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from inventory_control.models import ControlBase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"


def config_for(url: str) -> Config:
    value = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    value.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    value.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return value


def test_redemption_migration_roundtrip_and_metadata(
    mysql_control_migration_url,
):
    url = mysql_control_migration_url
    config = config_for(url)
    tables = {"redemption_code_batches", "redemption_codes"}

    command.upgrade(config, "202608220008")
    engine = sa.create_engine(url)
    try:
        assert tables.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220009")
    engine = sa.create_engine(url)
    try:
        inspector = sa.inspect(engine)
        assert tables <= set(inspector.get_table_names())
        index_names = {
            index["name"]
            for index in inspector.get_indexes("redemption_codes")
        }
        assert index_names >= {
            "ix_redemption_codes_status_deadline",
            "ix_redemption_codes_batch",
        }
    finally:
        engine.dispose()

    command.downgrade(config, "202608220008")
    engine = sa.create_engine(url)
    try:
        assert tables.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220009")
    command.upgrade(config, "head")
    engine = sa.create_engine(url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert compare_metadata(context, ControlBase.metadata) == []
    finally:
        engine.dispose()
