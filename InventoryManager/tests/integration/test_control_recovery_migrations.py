from __future__ import annotations

from io import StringIO
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from inventory_control.models import ControlBase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"
RECOVERY_TABLES = {
    "disaster_recovery_release_actions",
    "disaster_recovery_runs",
    "tenant_recovery_holds",
}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_recovery_migration_round_trip_matches_current_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    config = _alembic_config(database_url)

    command.upgrade(config, "202608220011")
    engine = sa.create_engine(database_url)
    try:
        assert RECOVERY_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220012")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        assert RECOVERY_TABLES <= set(inspector.get_table_names())
        run_columns = {
            column["name"]
            for column in inspector.get_columns("disaster_recovery_runs")
        }
        assert {
            "current_run_marker",
            "sealed_coverage_digest",
            "host_installation_fingerprint",
            "deployment_marker_fingerprint",
        } <= run_columns
        hold_foreign_keys = inspector.get_foreign_keys("tenant_recovery_holds")
        assert {foreign_key["referred_table"] for foreign_key in hold_foreign_keys} == {
            "disaster_recovery_runs"
        }
        assert all(
            foreign_key["referred_table"] != "tenants"
            for foreign_key in hold_foreign_keys
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

    command.downgrade(config, "202608220011")
    engine = sa.create_engine(database_url)
    try:
        assert RECOVERY_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220012")
    engine = sa.create_engine(database_url)
    try:
        assert RECOVERY_TABLES <= set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_recovery_migration_emits_mysql_8_compatible_offline_ddl():
    output = StringIO()
    config = _alembic_config("mysql+pymysql://unused:unused@localhost/control")
    config.output_buffer = output

    command.upgrade(config, "202608220011:202608220012", sql=True)
    ddl = output.getvalue()

    assert "CREATE TABLE disaster_recovery_runs" in ddl
    assert "CREATE TABLE tenant_recovery_holds" in ddl
    assert "CREATE TABLE disaster_recovery_release_actions" in ddl
    assert "BINARY(32)" in ddl
    assert "GENERATED ALWAYS AS" in ddl
    assert "FOREIGN KEY(recovery_run_id)" in ddl
    assert "FOREIGN KEY(tenant_id) REFERENCES tenants" not in ddl
