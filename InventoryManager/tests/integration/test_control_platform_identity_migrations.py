from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from inventory_control.models import ControlBase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"
PLATFORM_TABLES = {
    "platform_admins",
    "platform_admin_totp_credentials",
    "platform_admin_recovery_codes",
    "platform_admin_setup_challenges",
    "platform_admin_sessions",
    "platform_admin_rate_limit_counters",
}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_platform_identity_migration_round_trip_then_latest_head_matches_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    config = _alembic_config(database_url)

    command.upgrade(config, "202608220005")
    engine = sa.create_engine(database_url)
    try:
        assert PLATFORM_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220006")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        assert PLATFORM_TABLES <= set(inspector.get_table_names())
        assert {
            index["name"]
            for index in inspector.get_indexes(
                "platform_admin_totp_credentials"
            )
        } >= {"ix_platform_admin_totp_admin_status_generation"}
        assert {
            index["name"]
            for index in inspector.get_indexes("platform_admin_sessions")
        } >= {"ix_platform_admin_sessions_admin_active_expiry"}
        totp_columns = {
            column["name"]: column
            for column in inspector.get_columns(
                "platform_admin_totp_credentials"
            )
        }
        assert totp_columns["current_confirmed_admin_id"].get("computed")
        platform_columns = {
            column["name"]
            for table_name in PLATFORM_TABLES
            for column in inspector.get_columns(table_name)
        }
        assert {"tenant_id", "membership_id", "phone_e164"}.isdisjoint(
            platform_columns
        )
    finally:
        engine.dispose()

    command.downgrade(config, "202608220005")
    engine = sa.create_engine(database_url)
    try:
        tables = set(sa.inspect(engine).get_table_names())
        assert PLATFORM_TABLES.isdisjoint(tables)
        assert {
            "plans",
            "subscriptions",
            "subscription_events",
            "tenant_quota_guards",
        } <= tables
    finally:
        engine.dispose()

    command.upgrade(config, "202608220006")
    engine = sa.create_engine(database_url)
    try:
        assert PLATFORM_TABLES <= set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    # Historical round trips stop at their own revision. Drift is meaningful
    # only after all later migrations have been applied.
    command.upgrade(config, "head")
    engine = sa.create_engine(database_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert compare_metadata(context, ControlBase.metadata) == []
    finally:
        engine.dispose()
