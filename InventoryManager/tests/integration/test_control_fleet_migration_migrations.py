from __future__ import annotations

from io import StringIO
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.dialects import mysql

from inventory_control.models import ControlBase
from inventory_control.models.fleet_migrations import TenantFleetMigration
from inventory_control.models.foundation import DatabaseIdentityControlRecord


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"
TABLE_NAME = "tenant_fleet_migrations"
IDENTITY_TABLE = "database_identity_control_records"


def _config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_fleet_migration_upgrade_downgrade_and_head_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    config = _config(database_url)

    command.upgrade(config, "202608220021")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        assert TABLE_NAME not in inspector.get_table_names()
        assert "expected_schema_revision" not in {
            column["name"] for column in inspector.get_columns(IDENTITY_TABLE)
        }
    finally:
        engine.dispose()

    command.upgrade(config, "202608220022")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        assert TABLE_NAME in inspector.get_table_names()
        assert inspector.get_pk_constraint(TABLE_NAME)["constrained_columns"] == [
            "migration_uuid"
        ]
        foreign_keys = inspector.get_foreign_keys(TABLE_NAME)
        assert len(foreign_keys) == 1
        assert foreign_keys[0]["constrained_columns"] == [
            "tenant_id",
            "database_uuid",
        ]
        columns = {
            column["name"]: column
            for column in inspector.get_columns(TABLE_NAME)
        }
        assert set(columns) == {
            column.name for column in TenantFleetMigration.__table__.columns
        }
        identity_columns = {
            column["name"]: column
            for column in inspector.get_columns(IDENTITY_TABLE)
        }
        assert set(identity_columns) == {
            column.name
            for column in DatabaseIdentityControlRecord.__table__.columns
        }
        assert columns["source_schema_sha256"]["type"].python_type is bytes
        assert columns["source_schema_sha256"]["type"].length == 32
        assert columns["last_request_digest"]["type"].python_type is bytes
        assert columns["last_request_digest"]["type"].length == 32
        assert identity_columns["expected_schema_sha256"]["type"].python_type is bytes
        assert identity_columns["expected_schema_sha256"]["type"].length == 32
        assert (
            TenantFleetMigration.__table__.c.source_schema_sha256.type.length
            == 32
        )
    finally:
        engine.dispose()

    # Concurrent later revisions may already contribute mapped tables.  The
    # full metadata comparison therefore belongs at the actual branch head.
    command.upgrade(config, "head")
    engine = sa.create_engine(database_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert compare_metadata(context, ControlBase.metadata) == []
    finally:
        engine.dispose()

    command.downgrade(config, "202608220021")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        assert TABLE_NAME not in inspector.get_table_names()
        identity_columns = {
            column["name"] for column in inspector.get_columns(IDENTITY_TABLE)
        }
        assert "expected_schema_revision" not in identity_columns
        assert "expected_schema_sha256" not in identity_columns
        assert "observed_schema_revision" not in identity_columns
        assert "observed_schema_sha256" not in identity_columns
        assert "row_version" not in identity_columns
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = sa.create_engine(database_url)
    try:
        assert TABLE_NAME in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_fleet_migration_model_uses_mysql_binary32_and_datetime6():
    table = TenantFleetMigration.__table__
    for name in (
        "source_schema_sha256",
        "target_schema_sha256",
        "last_observed_schema_sha256",
        "queue_request_digest",
        "last_request_digest",
    ):
        assert isinstance(
            table.c[name].type.dialect_impl(mysql.dialect()),
            mysql.BINARY,
        )
        assert table.c[name].type.dialect_impl(mysql.dialect()).length == 32
    for name in (
        "queued_at",
        "started_at",
        "completed_at",
        "last_observed_at",
        "created_at",
        "updated_at",
    ):
        selected = table.c[name].type.dialect_impl(mysql.dialect())
        assert isinstance(selected, mysql.DATETIME)
        assert selected.fsp == 6
    for name in ("expected_schema_sha256", "observed_schema_sha256"):
        selected = DatabaseIdentityControlRecord.__table__.c[
            name
        ].type.dialect_impl(mysql.dialect())
        assert isinstance(selected, mysql.BINARY)
        assert selected.length == 32


def test_fleet_migration_emits_non_secret_mysql8_offline_ddl():
    output = StringIO()
    config = _config(
        "mysql+pymysql://unused:unused@localhost/inventory_control"
    )
    config.output_buffer = output

    command.upgrade(config, "202608220021:202608220022", sql=True)
    ddl = output.getvalue()
    lower_ddl = ddl.lower()

    assert f"CREATE TABLE {TABLE_NAME}" in ddl
    assert "source_schema_sha256 BINARY(32) NOT NULL" in ddl
    assert "target_schema_sha256 BINARY(32) NOT NULL" in ddl
    assert "last_request_digest BINARY(32) NOT NULL" in ddl
    assert "expected_schema_sha256 BINARY(32)" in ddl
    assert "observed_schema_sha256 BINARY(32)" in ddl
    assert "queued_at DATETIME(6) NOT NULL" in ddl
    assert "updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)" in ddl
    assert "uq_fleet_migrations_target_generation" in ddl
    assert "fk_fleet_migrations_route_identity" in ddl
    assert all(len(name) <= 64 for name in _constraint_names(ddl))
    for forbidden in (
        "password",
        "password_hash",
        "ciphertext",
        "credential_secret",
        "connection_url",
        "dsn",
    ):
        assert forbidden not in lower_ddl


def _constraint_names(ddl: str) -> tuple[str, ...]:
    names: list[str] = []
    words = ddl.replace("\n", " ").replace("`", "").split()
    for index, word in enumerate(words[:-1]):
        if word.upper() == "CONSTRAINT":
            names.append(words[index + 1])
    return tuple(names)
