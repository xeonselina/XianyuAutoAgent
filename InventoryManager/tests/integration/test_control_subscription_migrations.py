from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from inventory_control.models import ControlBase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_subscription_migration_upgrade_downgrade_upgrade_matches_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    config = _alembic_config(database_url)
    subscription_tables = {
        "plans",
        "tenant_quota_guards",
        "subscriptions",
        "subscription_events",
    }

    command.upgrade(config, "202608220004")
    engine = sa.create_engine(database_url)
    try:
        assert subscription_tables.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220005")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        assert subscription_tables <= set(inspector.get_table_names())
        assert {
            index["name"] for index in inspector.get_indexes("subscriptions")
        } >= {"ix_subscriptions_status_expiry"}
        assert {
            index["name"]
            for index in inspector.get_indexes("subscription_events")
        } >= {"ix_subscription_events_tenant_effective"}
        event_columns = {
            column["name"]
            for column in inspector.get_columns("subscription_events")
        }
        assert {
            "amount",
            "currency",
            "payment_status",
            "refund_status",
        }.isdisjoint(event_columns)
    finally:
        engine.dispose()

    command.downgrade(config, "202608220004")
    engine = sa.create_engine(database_url)
    try:
        tables = set(sa.inspect(engine).get_table_names())
        assert subscription_tables.isdisjoint(tables)
        assert {"sms_challenges", "sms_rate_limit_subjects"} <= tables
    finally:
        engine.dispose()

    command.upgrade(config, "202608220005")
    engine = sa.create_engine(database_url)
    try:
        assert subscription_tables <= set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    # Compare the live models only after later migrations reach the current head.
    command.upgrade(config, "head")
    engine = sa.create_engine(database_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert compare_metadata(context, ControlBase.metadata) == []
    finally:
        engine.dispose()
