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
DELETION_TABLES = {
    "tenant_deletion_actions",
    "tenant_deletion_effects",
    "tenant_deletion_evidence_receipts",
    "tenant_deletion_requests",
    "tenant_deletion_tombstones",
}


def _config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_deletion_migration_round_trip_matches_current_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    config = _config(database_url)

    command.upgrade(config, "202608220014")
    engine = sa.create_engine(database_url)
    try:
        assert DELETION_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220015")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        assert DELETION_TABLES <= set(inspector.get_table_names())
        request_columns = {
            column["name"]
            for column in inspector.get_columns("tenant_deletion_requests")
        }
        assert {
            "active_tenant_id",
            "execution_generation",
            "executor_fencing_token",
            "executor_lease_token_digest",
            "executor_lease_recovery_run_id",
        } <= request_columns
        tombstone_foreign_keys = inspector.get_foreign_keys(
            "tenant_deletion_tombstones"
        )
        assert tombstone_foreign_keys == []
        effect_uniques = {
            item["name"]: tuple(item["column_names"])
            for item in inspector.get_unique_constraints(
                "tenant_deletion_effects"
            )
        }
        assert effect_uniques[
            "uq_tenant_deletion_effects_generation_kind"
        ] == (
            "deletion_request_id",
            "action_id",
            "execution_generation",
            "effect_kind",
            "tombstone_sequence",
        )

        def include_deletion_objects(object_, name, type_, reflected, compare_to):
            if type_ == "table":
                return name in DELETION_TABLES
            table = getattr(object_, "table", None)
            return table is None or table.name in DELETION_TABLES

        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={"include_object": include_deletion_objects},
            )
            assert compare_metadata(context, ControlBase.metadata) == []
    finally:
        engine.dispose()

    command.downgrade(config, "202608220014")
    engine = sa.create_engine(database_url)
    try:
        assert DELETION_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220015")
    engine = sa.create_engine(database_url)
    try:
        assert DELETION_TABLES <= set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_deletion_migration_emits_mysql_8_compatible_offline_ddl():
    output = StringIO()
    config = _config("mysql+pymysql://unused:unused@localhost/control")
    config.output_buffer = output

    command.upgrade(config, "202608220014:202608220015", sql=True)
    ddl = output.getvalue()

    assert "CREATE TABLE tenant_deletion_requests" in ddl
    assert "CREATE TABLE tenant_deletion_actions" in ddl
    assert "CREATE TABLE tenant_deletion_effects" in ddl
    assert "CREATE TABLE tenant_deletion_evidence_receipts" in ddl
    assert "CREATE TABLE tenant_deletion_tombstones" in ddl
    assert "'releasing_claims'" in ddl
    assert "GENERATED ALWAYS AS" in ddl
    assert "BINARY(32)" in ddl
    assert (
        "UNIQUE (deletion_request_id, action_id, execution_generation, "
        "effect_kind, tombstone_sequence)" in ddl
    )
    tombstone_ddl = ddl.split("CREATE TABLE tenant_deletion_tombstones", 1)[1]
    tombstone_ddl = tombstone_ddl.split(";", 1)[0]
    assert "FOREIGN KEY" not in tombstone_ddl
