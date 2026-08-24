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
BACKUP_TABLES = {
    "platform_backup_leases",
    "backup_attempts",
    "completed_backup_artifacts",
}
NOW = datetime(2026, 8, 22, 4, 0, tzinfo=timezone.utc)
ZERO_DIGEST = b"0" * 32


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_backup_migration_0016_to_0017_round_trip_and_head_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    config = _alembic_config(database_url)

    command.upgrade(config, "202608220016")
    engine = sa.create_engine(database_url)
    try:
        assert BACKUP_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220017")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        assert BACKUP_TABLES <= set(inspector.get_table_names())
        lease = sa.Table(
            "platform_backup_leases",
            sa.MetaData(),
            autoload_with=engine,
        )
        with engine.connect() as connection:
            seeded = connection.execute(sa.select(lease)).mappings().one()
        assert seeded["lease_key"] == "fleet_full_backup"
        assert seeded["status"] == "available"
        assert seeded["generation"] == 0
        assert seeded["fencing_token"] == 0
        artifact_columns = {
            column["name"]: column
            for column in inspector.get_columns("completed_backup_artifacts")
        }
        for digest_column in (
            "artifact_sha256",
            "manifest_sha256",
            "record_sha256",
            "marker_sha256",
        ):
            assert artifact_columns[digest_column]["type"].python_type is bytes
            assert artifact_columns[digest_column]["type"].length == 32
        assert artifact_columns["canonical_manifest_bytes"]["type"].python_type is bytes
    finally:
        engine.dispose()

    command.downgrade(config, "202608220016")
    engine = sa.create_engine(database_url)
    try:
        assert BACKUP_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220017")
    command.upgrade(config, "head")
    engine = sa.create_engine(database_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert compare_metadata(context, ControlBase.metadata) == []
    finally:
        engine.dispose()


def test_backup_migration_enforces_singleton_fences_and_immutable_identity(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    command.upgrade(_alembic_config(database_url), "202608220017")
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    metadata.reflect(engine, only=tuple(BACKUP_TABLES))
    leases = metadata.tables["platform_backup_leases"]
    attempts = metadata.tables["backup_attempts"]
    artifacts = metadata.tables["completed_backup_artifacts"]

    attempt_id = "11111111-1111-4111-8111-111111111111"
    try:
        with pytest.raises((IntegrityError, OperationalError)):
            with engine.begin() as connection:
                connection.execute(
                    sa.insert(leases).values(
                        lease_key="another_scope",
                        status="available",
                        generation=0,
                        fencing_token=0,
                        observed_at=NOW,
                    )
                )

        with pytest.raises((IntegrityError, OperationalError)):
            with engine.begin() as connection:
                connection.execute(
                    sa.update(leases)
                    .where(leases.c.lease_key == "fleet_full_backup")
                    .values(
                        status="held",
                        generation=1,
                        fencing_token=1,
                    )
                )

        with engine.begin() as connection:
            connection.execute(
                sa.insert(attempts).values(
                    attempt_id=attempt_id,
                    acquisition_id=(
                        "22222222-2222-4222-8222-222222222222"
                    ),
                    lease_generation=1,
                    fencing_token=1,
                    partial_name=(
                        "backup-33333333-3333-4333-8333-333333333333"
                        ".sql.gz.partial"
                    ),
                    started_at=NOW,
                )
            )

        valid_artifact = {
            "artifact_id": "33333333-3333-4333-8333-333333333333",
            "attempt_id": attempt_id,
            "published_name": (
                "backup-33333333-3333-4333-8333-333333333333.sql.gz"
            ),
            "canonical_manifest_bytes": b"{}",
            "artifact_sha256": ZERO_DIGEST,
            "manifest_sha256": b"1" * 32,
            "record_sha256": b"2" * 32,
            "size_bytes": 4096,
            "snapshot_at": NOW,
            "completed_at": NOW,
            "installation_id": "44444444-4444-4444-8444-444444444444",
            "recovery_run_id": "55555555-5555-4555-8555-555555555555",
            "marker_generation": 1,
            "marker_sha256": b"3" * 32,
        }
        with engine.begin() as connection:
            connection.execute(sa.insert(artifacts).values(**valid_artifact))

        with pytest.raises((IntegrityError, OperationalError)):
            with engine.begin() as connection:
                connection.execute(
                    sa.insert(artifacts).values(
                        **{
                            **valid_artifact,
                            "artifact_id": (
                                "66666666-6666-4666-8666-666666666666"
                            ),
                        }
                    )
                )

        with engine.begin() as connection:
            connection.execute(
                sa.update(artifacts)
                .where(
                    artifacts.c.artifact_id == valid_artifact["artifact_id"]
                )
                .values(record_sha256=b"short")
            )
            stored_length = connection.scalar(
                sa.select(sa.func.length(artifacts.c.record_sha256)).where(
                    artifacts.c.artifact_id == valid_artifact["artifact_id"]
                )
            )
        assert stored_length == 32
    finally:
        engine.dispose()


def test_backup_migration_emits_mysql_8_non_secret_offline_ddl():
    output = StringIO()
    config = _alembic_config(
        "mysql+pymysql://unused:unused@localhost/inventory_control"
    )
    config.output_buffer = output

    command.upgrade(config, "202608220016:202608220017", sql=True)
    ddl = output.getvalue()
    lower_ddl = ddl.lower()

    assert "CREATE TABLE platform_backup_leases" in ddl
    assert "CREATE TABLE backup_attempts" in ddl
    assert "CREATE TABLE completed_backup_artifacts" in ddl
    assert "canonical_manifest_bytes MEDIUMBLOB NOT NULL" in ddl
    assert ddl.count("BINARY(32) NOT NULL") >= 4
    assert ddl.count("DATETIME(6)") == 6
    assert "INSERT INTO platform_backup_leases" in ddl
    assert "uq_completed_backup_artifacts_attempt" in ddl
    assert "uq_completed_backup_artifacts_name" in ddl
    assert "fk_completed_backup_artifacts_attempt" in ddl
    assert all(len(name) <= 64 for name in _constraint_names(ddl))
    for forbidden in (
        "key_material",
        "password",
        "filesystem_path",
        "database_path",
        "dsn",
        "secret_value",
    ):
        assert forbidden not in lower_ddl
    assert " json" not in lower_ddl


def _constraint_names(ddl: str) -> tuple[str, ...]:
    names: list[str] = []
    words = ddl.replace("\n", " ").replace("`", "").split()
    for index, word in enumerate(words[:-1]):
        if word.upper() == "CONSTRAINT":
            names.append(words[index + 1])
    return tuple(names)
