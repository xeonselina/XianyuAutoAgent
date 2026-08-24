from __future__ import annotations

from datetime import datetime, timezone
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
TABLE_NAME = "platform_root_key_versions"
NOW = datetime(2026, 8, 22, 3, 30, tzinfo=timezone.utc)


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_root_key_migration_0015_to_0016_round_trip_and_head_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    config = _alembic_config(database_url)

    command.upgrade(config, "202608220015")
    engine = sa.create_engine(database_url)
    try:
        assert TABLE_NAME not in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(config, "202608220016")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        assert TABLE_NAME in inspector.get_table_names()
        columns = {column["name"]: column for column in inspector.get_columns(TABLE_NAME)}
        assert set(columns) == {
            "version",
            "fingerprint_sha256",
            "status",
            "active_slot",
            "activated_at",
            "retired_at",
        }
        assert columns["fingerprint_sha256"]["type"].python_type is bytes
        assert columns["fingerprint_sha256"]["type"].length == 32
        assert columns["active_slot"]["computed"]["persisted"] is True
        checks = inspector.get_check_constraints(TABLE_NAME)
        assert any(
            "length(fingerprint_sha256) = 32"
            in check["sqltext"]
            .lower()
            .replace("`", "")
            .replace("octet_length(", "length(")
            for check in checks
        )
    finally:
        engine.dispose()

    command.downgrade(config, "202608220015")
    engine = sa.create_engine(database_url)
    try:
        assert TABLE_NAME not in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(config, "202608220016")
    command.upgrade(config, "head")
    engine = sa.create_engine(database_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert compare_metadata(context, ControlBase.metadata) == []
    finally:
        engine.dispose()


def test_root_key_migration_enforces_lifecycle_and_non_secret_identity(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    command.upgrade(_alembic_config(database_url), "202608220016")
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    metadata.reflect(engine, only=(TABLE_NAME,))
    versions = metadata.tables[TABLE_NAME]

    active = {
        "version": 1,
        "fingerprint_sha256": b"a" * 32,
        "status": "active",
        "activated_at": NOW,
    }
    try:
        assert {
            "version",
            "fingerprint_sha256",
            "status",
            "active_slot",
            "activated_at",
            "retired_at",
        } == set(versions.c.keys())

        with engine.begin() as connection:
            connection.execute(sa.insert(versions).values(**active))
            stored = connection.execute(
                sa.select(versions.c.active_slot).where(versions.c.version == 1)
            ).scalar_one()
            assert stored == 1

        with pytest.raises((IntegrityError, OperationalError)):
            with engine.begin() as connection:
                connection.execute(
                    sa.insert(versions).values(
                        version=2,
                        fingerprint_sha256=b"b" * 32,
                        status="active",
                        activated_at=NOW,
                    )
                )

        with engine.begin() as connection:
            connection.execute(
                sa.insert(versions).values(
                    version=2,
                    fingerprint_sha256=b"b" * 32,
                    status="legacy",
                    activated_at=NOW,
                )
            )

        invalid_rows = (
            {
                "version": 3,
                "fingerprint_sha256": b"c" * 32,
                "status": "retired",
                "activated_at": NOW,
            },
            {
                "version": 3,
                "fingerprint_sha256": b"c" * 32,
                "status": "legacy",
                "activated_at": NOW,
                "retired_at": NOW,
            },
        )
        for row in invalid_rows:
            with pytest.raises((IntegrityError, OperationalError)):
                with engine.begin() as connection:
                    connection.execute(sa.insert(versions).values(**row))

        with engine.begin() as connection:
            connection.execute(
                sa.insert(versions).values(
                    version=3,
                    fingerprint_sha256=b"c" * 32,
                    status="retired",
                    activated_at=NOW,
                    retired_at=NOW,
                )
            )

        with engine.begin() as connection:
            connection.execute(
                sa.insert(versions).values(
                    version=4,
                    fingerprint_sha256=b"d" * 31,
                    status="legacy",
                    activated_at=NOW,
                )
            )
            stored_length = connection.scalar(
                sa.select(sa.func.length(versions.c.fingerprint_sha256)).where(
                    versions.c.version == 4
                )
            )
        assert stored_length == 32
    finally:
        engine.dispose()


def test_root_key_migration_emits_mysql_8_compatible_non_secret_offline_ddl():
    output = StringIO()
    config = _alembic_config(
        "mysql+pymysql://unused:unused@localhost/inventory_control"
    )
    config.output_buffer = output

    command.upgrade(config, "202608220015:202608220016", sql=True)
    ddl = output.getvalue()
    lower_ddl = ddl.lower()

    assert "CREATE TABLE platform_root_key_versions" in ddl
    assert "fingerprint_sha256 BINARY(32) NOT NULL" in ddl
    assert "active_slot SMALLINT GENERATED ALWAYS AS" in ddl
    assert "STORED" in ddl
    assert "uq_root_key_versions_active_slot" in ddl
    assert "length(fingerprint_sha256) = 32" in ddl
    assert "retired_at" in ddl
    assert all(len(name) <= 64 for name in _constraint_names(ddl))
    for forbidden in (
        "key_material",
        "key_path",
        "filesystem_path",
        "ciphertext",
        "secret_value",
    ):
        assert forbidden not in lower_ddl


def _constraint_names(ddl: str) -> tuple[str, ...]:
    names: list[str] = []
    words = ddl.replace("\n", " ").replace("`", "").split()
    for index, word in enumerate(words[:-1]):
        if word.upper() == "CONSTRAINT":
            names.append(words[index + 1])
    return tuple(names)
