from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.exc import IntegrityError, OperationalError

from inventory_control.models import ControlBase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"
ROUTE_COLUMNS = {
    "activated_by_registration_commit_uuid",
    "activation_route_version",
    "activation_credential_generation",
    "dml_username",
    "dml_credential_generation",
    "dml_root_key_version",
    "dml_derivation_version",
    "dml_desired_login_state",
    "dml_observed_login_state",
    "dml_login_state_version",
    "dml_desired_state_recovery_run_id",
    "platform_read_username",
    "platform_read_credential_generation",
    "platform_read_root_key_version",
    "platform_read_derivation_version",
    "platform_read_route_version",
    "row_version",
}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_tenant_route_migration_round_trip_matches_current_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    config = _alembic_config(database_url)

    command.upgrade(config, "202608220012")
    engine = sa.create_engine(database_url)
    try:
        before = {
            column["name"]
            for column in sa.inspect(engine).get_columns("tenant_databases")
        }
        assert ROUTE_COLUMNS.isdisjoint(before)
    finally:
        engine.dispose()

    command.upgrade(config, "202608220013")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        after = {
            column["name"]
            for column in inspector.get_columns("tenant_databases")
        }
        assert ROUTE_COLUMNS <= after
        foreign_keys = inspector.get_foreign_keys("tenant_databases")
        assert any(
            foreign_key["name"] == "fk_tenant_databases_dml_recovery_run"
            and foreign_key["referred_table"] == "disaster_recovery_runs"
            for foreign_key in foreign_keys
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

    command.downgrade(config, "202608220012")
    engine = sa.create_engine(database_url)
    try:
        downgraded = {
            column["name"]
            for column in sa.inspect(engine).get_columns("tenant_databases")
        }
        assert ROUTE_COLUMNS.isdisjoint(downgraded)
    finally:
        engine.dispose()

    command.upgrade(config, "202608220013")
    engine = sa.create_engine(database_url)
    try:
        upgraded_again = {
            column["name"]
            for column in sa.inspect(engine).get_columns("tenant_databases")
        }
        assert ROUTE_COLUMNS <= upgraded_again
    finally:
        engine.dispose()


def test_tenant_route_migration_enforces_complete_ready_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    command.upgrade(_alembic_config(database_url), "202608220013")
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    metadata.reflect(engine, only=("tenants", "tenant_databases"))
    tenants = metadata.tables["tenants"]
    routes = metadata.tables["tenant_databases"]
    tenant_id = "11111111-1111-4111-8111-111111111111"

    try:
        with engine.begin() as connection:
            connection.execute(sa.insert(tenants).values(id=tenant_id))
            connection.execute(
                sa.insert(routes).values(
                    tenant_id=tenant_id,
                    database_uuid="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    database_instance_key="primary",
                    database_name="tenant_inventory",
                    status="provisional",
                )
            )

        with pytest.raises((IntegrityError, OperationalError)):
            with engine.begin() as connection:
                connection.execute(
                    sa.update(routes)
                    .where(routes.c.tenant_id == tenant_id)
                    .values(status="ready")
                )

        complete_values = {
            "schema_version": "tenant-schema-1",
            "activated_by_registration_commit_uuid": (
                "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
            ),
            "activation_route_version": 1,
            "activation_credential_generation": 1,
            "dml_username": "tenant_dml_g1",
            "dml_credential_generation": 1,
            "dml_root_key_version": 1,
            "dml_derivation_version": 1,
            "dml_desired_login_state": "active",
            "dml_observed_login_state": "active",
            "dml_login_state_version": 1,
            "platform_read_username": "tenant_read_g1",
            "platform_read_credential_generation": 1,
            "platform_read_root_key_version": 1,
            "platform_read_derivation_version": 1,
            "platform_read_route_version": 1,
            "status": "ready",
        }
        with engine.begin() as connection:
            connection.execute(
                sa.update(routes)
                .where(routes.c.tenant_id == tenant_id)
                .values(**complete_values)
            )

        with pytest.raises((IntegrityError, OperationalError)):
            with engine.begin() as connection:
                connection.execute(
                    sa.update(routes)
                    .where(routes.c.tenant_id == tenant_id)
                    .values(platform_read_route_version=0)
                )

        stored_columns = {column.name for column in routes.columns}
        assert not any(
            marker in column_name
            for column_name in stored_columns
            for marker in ("password", "hash", "ciphertext", "secret", "dsn")
        )
    finally:
        engine.dispose()


def test_tenant_route_migration_emits_mysql_8_compatible_offline_ddl():
    output = StringIO()
    config = _alembic_config("mysql+pymysql://unused:unused@localhost/control")
    config.output_buffer = output

    command.upgrade(config, "202608220012:202608220013", sql=True)
    ddl = output.getvalue()

    assert "ALTER TABLE tenant_databases ADD COLUMN dml_username" in ddl
    assert "ADD COLUMN platform_read_username" in ddl
    assert "ADD COLUMN dml_desired_state_recovery_run_id" in ddl
    assert "fk_tenant_databases_dml_recovery_run" in ddl
    assert "ck_tenant_databases_ready_metadata_complete" in ddl
    assert "dml_credential_generation >= 1" in ddl
    assert "platform_read_route_version >= 1" in ddl
    assert all(len(name) <= 64 for name in _constraint_names(ddl))
    assert "password" not in ddl.lower()
    assert "ciphertext" not in ddl.lower()


def _constraint_names(ddl: str) -> tuple[str, ...]:
    names: list[str] = []
    words = ddl.replace("\n", " ").replace("`", "").split()
    for index, word in enumerate(words[:-1]):
        if word.upper() == "CONSTRAINT":
            names.append(words[index + 1])
    return tuple(names)
