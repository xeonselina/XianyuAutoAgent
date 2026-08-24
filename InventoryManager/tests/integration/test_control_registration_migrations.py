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


def config_for(url: str) -> Config:
    value = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    value.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    value.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return value


def test_registration_migration_roundtrip_and_metadata(
    mysql_control_migration_url,
):
    url = mysql_control_migration_url
    config = config_for(url)
    tables = {
        "tenant_registration_attempts",
        "tenant_registration_commits",
        "redemption_code_replacements",
        "registration_integrity_incidents",
    }

    command.upgrade(config, "202608220009")
    engine = sa.create_engine(url)
    try:
        assert tables.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220010")
    engine = sa.create_engine(url)
    try:
        inspector = sa.inspect(engine)
        assert tables <= set(inspector.get_table_names())
    finally:
        engine.dispose()

    command.downgrade(config, "202608220009")
    engine = sa.create_engine(url)
    try:
        assert tables.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220010")
    command.upgrade(config, "head")
    engine = sa.create_engine(url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert compare_metadata(context, ControlBase.metadata) == []
    finally:
        engine.dispose()


def test_registration_migration_emits_microsecond_mysql_lease_expiry():
    output = StringIO()
    config = config_for(
        "mysql+pymysql://unused:unused@localhost/inventory_control"
    )
    config.output_buffer = output

    command.upgrade(config, "202608220009:202608220010", sql=True)
    ddl = output.getvalue()

    assert "lease_expires_at DATETIME(6)" in ddl
    assert "request_digest BINARY(32) NOT NULL" in ddl


def test_registration_provisioning_proof_migration_roundtrip(
    mysql_control_migration_url,
):
    url = mysql_control_migration_url
    config = config_for(url)
    table = "tenant_registration_provisioning_proofs"

    command.upgrade(config, "202608220020")
    engine = sa.create_engine(url)
    try:
        assert table not in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(config, "202608220021")
    engine = sa.create_engine(url)
    try:
        inspector = sa.inspect(engine)
        assert table in inspector.get_table_names()
        columns = {column["name"] for column in inspector.get_columns(table)}
        assert "worker_lease_token_digest" in columns
        assert "worker_lease_token" not in columns
    finally:
        engine.dispose()

    command.downgrade(config, "202608220020")
    engine = sa.create_engine(url)
    try:
        assert table not in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_registration_proof_emits_mysql_binary_digests_and_microseconds():
    output = StringIO()
    config = config_for(
        "mysql+pymysql://unused:unused@localhost/inventory_control"
    )
    config.output_buffer = output

    command.upgrade(config, "202608220020:202608220021", sql=True)
    ddl = output.getvalue()

    assert "worker_lease_token_digest BINARY(32) NOT NULL" in ddl
    assert "result_request_digest BINARY(32) NOT NULL" in ddl
    assert "worker_lease_expires_at DATETIME(6) NOT NULL" in ddl
    assert "recorded_at DATETIME(6) NOT NULL" in ddl
    assert "worker_lease_token VARCHAR" not in ddl
