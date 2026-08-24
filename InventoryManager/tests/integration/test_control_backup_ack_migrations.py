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
from inventory_control.models.backups import BackupArtifactAcknowledgementRecord


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"
ACK_TABLE = "backup_artifact_acknowledgements"
NOW = datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc)


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_backup_ack_migration_0022_to_0023_round_trip_and_head_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    config = _alembic_config(database_url)

    command.upgrade(config, "202608220022")
    engine = sa.create_engine(database_url)
    try:
        assert ACK_TABLE not in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(config, "202608220023")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        assert ACK_TABLE in inspector.get_table_names()
        columns = {
            column["name"]: column for column in inspector.get_columns(ACK_TABLE)
        }
        assert set(columns) == {
            "artifact_id",
            "ack_kind",
            "manifest_sha256",
            "artifact_sha256",
            "source_generation",
            "idempotency_key",
            "request_digest",
            "safe_result",
            "reported_at",
            "received_at",
            "row_version",
        }
        for name in (
            "manifest_sha256",
            "artifact_sha256",
            "request_digest",
        ):
            assert columns[name]["type"].python_type is bytes
            assert columns[name]["type"].length == 32
        foreign_keys = inspector.get_foreign_keys(ACK_TABLE)
        assert len(foreign_keys) == 1
        assert foreign_keys[0]["referred_table"] == "completed_backup_artifacts"
        assert foreign_keys[0]["options"].get("ondelete") in {None, "RESTRICT"}
        unique_columns = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints(ACK_TABLE)
        }
        assert ("ack_kind", "idempotency_key") in unique_columns
    finally:
        engine.dispose()

    command.downgrade(config, "202608220022")
    engine = sa.create_engine(database_url)
    try:
        assert ACK_TABLE not in sa.inspect(engine).get_table_names()
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


def test_backup_ack_migration_enforces_independent_slots_and_safe_shape(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    command.upgrade(_alembic_config(database_url), "202608220023")
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    metadata.reflect(
        engine,
        only=("backup_attempts", "completed_backup_artifacts", ACK_TABLE),
    )
    attempts = metadata.tables["backup_attempts"]
    artifacts = metadata.tables["completed_backup_artifacts"]
    acknowledgements = metadata.tables[ACK_TABLE]
    artifact_id = "33333333-3333-4333-8333-333333333333"
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.insert(attempts).values(
                    attempt_id="11111111-1111-4111-8111-111111111111",
                    acquisition_id="22222222-2222-4222-8222-222222222222",
                    lease_generation=1,
                    fencing_token=1,
                    partial_name=f"backup-{artifact_id}.sql.gz.partial",
                    started_at=NOW,
                )
            )
            connection.execute(
                sa.insert(artifacts).values(
                    artifact_id=artifact_id,
                    attempt_id="11111111-1111-4111-8111-111111111111",
                    published_name=f"backup-{artifact_id}.sql.gz",
                    canonical_manifest_bytes=b"{}",
                    artifact_sha256=b"a" * 32,
                    manifest_sha256=b"m" * 32,
                    record_sha256=b"r" * 32,
                    size_bytes=4096,
                    snapshot_at=NOW,
                    completed_at=NOW,
                    installation_id="44444444-4444-4444-8444-444444444444",
                    recovery_run_id="55555555-5555-4555-8555-555555555555",
                    marker_generation=1,
                    marker_sha256=b"k" * 32,
                )
            )

        backup_ack = {
            "artifact_id": artifact_id,
            "ack_kind": "backup-status-ack",
            "manifest_sha256": b"m" * 32,
            "artifact_sha256": b"a" * 32,
            "source_generation": 1,
            "idempotency_key": "backup-status-1",
            "request_digest": b"q" * 32,
            "safe_result": "verified",
            "reported_at": NOW,
            "received_at": NOW,
            "row_version": 1,
        }
        with engine.begin() as connection:
            connection.execute(sa.insert(acknowledgements).values(**backup_ack))
            connection.execute(
                sa.insert(acknowledgements).values(
                    **{
                        **backup_ack,
                        "ack_kind": "sync-status-ack",
                        "idempotency_key": "sync-status-1",
                        "safe_result": "synced",
                    }
                )
            )

        with pytest.raises((IntegrityError, OperationalError)):
            with engine.begin() as connection:
                connection.execute(
                    sa.insert(acknowledgements).values(
                        **{
                            **backup_ack,
                            "ack_kind": "unexpected",
                            "idempotency_key": "unexpected-kind",
                        }
                    )
                )
        with pytest.raises((IntegrityError, OperationalError)):
            with engine.begin() as connection:
                connection.execute(
                    sa.update(acknowledgements)
                    .where(
                        acknowledgements.c.artifact_id == artifact_id,
                        acknowledgements.c.ack_kind == "sync-status-ack",
                    )
                    .values(safe_result="verified")
                )
        with engine.begin() as connection:
            connection.execute(
                sa.update(acknowledgements)
                .where(
                    acknowledgements.c.artifact_id == artifact_id,
                    acknowledgements.c.ack_kind == "backup-status-ack",
                )
                .values(request_digest=b"short")
            )
            stored_length = connection.scalar(
                sa.select(sa.func.length(acknowledgements.c.request_digest)).where(
                    acknowledgements.c.artifact_id == artifact_id,
                    acknowledgements.c.ack_kind == "backup-status-ack",
                )
            )
        assert stored_length == 32
        with pytest.raises((IntegrityError, OperationalError)):
            with engine.begin() as connection:
                connection.execute(
                    sa.update(acknowledgements)
                    .where(
                        acknowledgements.c.artifact_id == artifact_id,
                        acknowledgements.c.ack_kind == "backup-status-ack",
                    )
                    .values(row_version=2)
                )
    finally:
        engine.dispose()


def test_backup_ack_migration_emits_mysql_8_microsecond_non_secret_ddl():
    output = StringIO()
    config = _alembic_config(
        "mysql+pymysql://unused:unused@localhost/inventory_control"
    )
    config.output_buffer = output

    command.upgrade(config, "202608220022:202608220023", sql=True)
    ddl = output.getvalue()
    lower_ddl = ddl.lower()

    assert "CREATE TABLE backup_artifact_acknowledgements" in ddl
    assert ddl.count("BINARY(32) NOT NULL") == 3
    assert ddl.count("DATETIME(6) NOT NULL") == 2
    assert "DEFAULT CURRENT_TIMESTAMP(6)" in ddl
    assert "fk_backup_artifact_acks_completed" in ddl
    assert "uq_backup_artifact_acks_kind_idempotency" in ddl
    assert "ix_backup_artifact_acks_kind_received" in ddl
    assert all(len(name) <= 64 for name in _constraint_names(ddl))
    for forbidden in (
        "password",
        "secret",
        "credential",
        "nas_address",
        "cloud_address",
        "filesystem_path",
        "customer",
        "tenant_id",
        "provider_name",
    ):
        assert forbidden not in lower_ddl
    assert " json" not in lower_ddl


def test_backup_ack_model_mysql_default_is_microsecond():
    mysql_ddl = str(
        sa.schema.CreateTable(BackupArtifactAcknowledgementRecord.__table__).compile(
            dialect=sa.create_mock_engine(
                "mysql+pymysql://unused:unused@localhost/inventory_control",
                lambda *_args, **_kwargs: None,
            ).dialect
        )
    )
    assert "DATETIME(6)" in mysql_ddl
    assert "DEFAULT CURRENT_TIMESTAMP(6)" in mysql_ddl


def _constraint_names(ddl: str) -> tuple[str, ...]:
    names: list[str] = []
    words = ddl.replace("\n", " ").replace("`", "").split()
    for index, word in enumerate(words[:-1]):
        if word.upper() == "CONSTRAINT":
            names.append(words[index + 1])
    return tuple(names)
