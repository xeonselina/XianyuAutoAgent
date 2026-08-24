from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from inventory_control.models.schema_operations import (
    PlatformSchemaOperationLease,
)
from inventory_control.schema_operations import (
    SCHEMA_OPERATION_LEASE_KEY,
    SchemaOperationLeasePersistenceService,
    SchemaOperationLeaseState,
    SchemaOperationPurpose,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"
TABLE_NAME = "platform_schema_operation_leases"
NOW = datetime(2026, 8, 22, 12, 0, 0, 123456, tzinfo=timezone.utc)
CLAIM_ID = UUID("94000000-0000-4000-8000-000000000001")


def _config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_schema_operation_migration_round_trip_seed_and_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    config = _config(database_url)

    command.upgrade(config, "202608220019")
    engine = sa.create_engine(database_url)
    try:
        assert TABLE_NAME not in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(config, "202608220020")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        assert TABLE_NAME in inspector.get_table_names()
        assert inspector.get_pk_constraint(TABLE_NAME)[
            "constrained_columns"
        ] == ["lease_key"]
        assert inspector.get_foreign_keys(TABLE_NAME) == []
        columns = {
            column["name"]: column
            for column in inspector.get_columns(TABLE_NAME)
        }
        assert set(columns) == {
            column.name
            for column in PlatformSchemaOperationLease.__table__.columns
        }
        assert columns["last_request_digest"]["type"].python_type is bytes
        assert columns["last_request_digest"]["type"].length == 32
        assert (
            PlatformSchemaOperationLease.__table__
            .c.last_request_digest.type.length
            == 32
        )
        with engine.connect() as connection:
            seeded = connection.execute(
                sa.select(PlatformSchemaOperationLease)
            ).mappings().one()
        assert seeded["lease_key"] == SCHEMA_OPERATION_LEASE_KEY
        assert seeded["state"] == SchemaOperationLeaseState.AVAILABLE.value
        assert seeded["generation"] == 0
        assert seeded["fencing_token"] == 0
        assert seeded["row_version"] == 1
    finally:
        engine.dispose()

    command.downgrade(config, "202608220019")
    engine = sa.create_engine(database_url)
    try:
        assert TABLE_NAME not in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(config, "202608220020")
    engine = sa.create_engine(database_url)
    try:
        assert TABLE_NAME in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_schema_operation_migrated_service_round_trip(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    command.upgrade(_config(database_url), "202608220020")
    engine = sa.create_engine(database_url)
    try:
        with engine.connect() as connection:
            seeded_observed_at = connection.scalar(
                sa.select(PlatformSchemaOperationLease.observed_at)
            )
        assert isinstance(seeded_observed_at, datetime)
        database_now = (
            seeded_observed_at.replace(tzinfo=timezone.utc)
            if seeded_observed_at.tzinfo is None
            else seeded_observed_at.astimezone(timezone.utc)
        ) + timedelta(seconds=1)
        first_expiry = database_now + timedelta(
            minutes=10,
            microseconds=111111,
        )
        renewed_expiry = database_now + timedelta(
            minutes=20,
            microseconds=222222,
        )
        with Session(engine) as session, session.begin():
            claimed = SchemaOperationLeasePersistenceService(
                session,
                database_clock=lambda _: database_now,
            ).claim(
                claim_id=CLAIM_ID,
                owner_id="backup-worker",
                purpose=SchemaOperationPurpose.BACKUP,
                expected_row_version=1,
                lease_expires_at=first_expiry,
            )
        assert claimed.lease.expires_at == first_expiry

        with Session(engine) as session, session.begin():
            renewed = SchemaOperationLeasePersistenceService(
                session,
                database_clock=lambda _: database_now + timedelta(minutes=1),
            ).renew(
                claim_id=CLAIM_ID,
                owner_id="backup-worker",
                purpose=SchemaOperationPurpose.BACKUP,
                fencing_token=claimed.lease.fencing_token,
                expected_row_version=claimed.lease.row_version,
                lease_expires_at=renewed_expiry,
            )
        assert renewed.lease.expires_at == renewed_expiry

        with Session(engine) as session, session.begin():
            released = SchemaOperationLeasePersistenceService(
                session,
                database_clock=lambda _: database_now + timedelta(minutes=2),
            ).release(
                claim_id=CLAIM_ID,
                owner_id="backup-worker",
                purpose=SchemaOperationPurpose.BACKUP,
                fencing_token=renewed.lease.fencing_token,
                expected_row_version=renewed.lease.row_version,
            )
        assert released.lease.state is SchemaOperationLeaseState.AVAILABLE
        assert released.lease.row_version == 4
    finally:
        engine.dispose()


def test_schema_operation_migration_enforces_singleton_and_state_facts(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    command.upgrade(_config(database_url), "202608220020")
    engine = sa.create_engine(database_url)
    table = sa.Table(TABLE_NAME, sa.MetaData(), autoload_with=engine)
    try:
        with pytest.raises((IntegrityError, OperationalError)):
            with engine.begin() as connection:
                connection.execute(
                    sa.insert(table).values(
                        lease_key="another_scope",
                        state="available",
                        generation=0,
                        fencing_token=0,
                        row_version=1,
                        observed_at=NOW,
                    )
                )

        with engine.connect() as connection:
            window_start = connection.scalar(
                sa.select(table.c.observed_at).where(
                    table.c.lease_key == SCHEMA_OPERATION_LEASE_KEY
                )
            )
        window_end = window_start + timedelta(minutes=5)

        invalid_updates = (
            {
                "state": "held",
                "generation": 1,
                "fencing_token": 1,
                "row_version": 2,
                "owner_id": "worker",
                "claim_id": str(CLAIM_ID),
                "purpose": "unknown",
                "acquired_at": window_start,
                "expires_at": window_end,
                "last_claim_id": str(CLAIM_ID),
                "last_effect": "claimed",
                "last_request_digest": b"x" * 32,
            },
            {
                "state": "held",
                "generation": 1,
                "fencing_token": 0,
                "row_version": 2,
                "owner_id": "worker",
                "claim_id": str(CLAIM_ID),
                "purpose": "restore",
                "acquired_at": window_start,
                "expires_at": window_end,
                "last_claim_id": str(CLAIM_ID),
                "last_effect": "claimed",
                "last_request_digest": b"x" * 32,
            },
        )
        for invalid in invalid_updates:
            with pytest.raises((IntegrityError, OperationalError)):
                with engine.begin() as connection:
                    connection.execute(
                        sa.update(table)
                        .where(
                            table.c.lease_key == SCHEMA_OPERATION_LEASE_KEY
                        )
                        .values(**invalid)
                    )

        with engine.begin() as connection:
            connection.execute(
                sa.update(table)
                .where(table.c.lease_key == SCHEMA_OPERATION_LEASE_KEY)
                .values(
                    state="held",
                    generation=1,
                    fencing_token=1,
                    row_version=2,
                    owner_id="worker",
                    claim_id=str(CLAIM_ID),
                    purpose="restore",
                    acquired_at=window_start,
                    expires_at=window_end,
                    last_claim_id=str(CLAIM_ID),
                    last_effect="claimed",
                    last_request_digest=b"short",
                )
            )
            stored_length = connection.scalar(
                sa.select(sa.func.length(table.c.last_request_digest)).where(
                    table.c.lease_key == SCHEMA_OPERATION_LEASE_KEY
                )
            )
        assert stored_length == 32
    finally:
        engine.dispose()


def test_schema_operation_migration_emits_mysql8_non_secret_offline_ddl():
    output = StringIO()
    config = _config(
        "mysql+pymysql://unused:unused@localhost/inventory_control"
    )
    config.output_buffer = output

    command.upgrade(config, "202608220019:202608220020", sql=True)
    ddl = output.getvalue()
    lower_ddl = ddl.lower()

    assert f"CREATE TABLE {TABLE_NAME}" in ddl
    assert (
        "observed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)"
        in ddl
    )
    assert "acquired_at DATETIME(6)" in ddl
    assert "expires_at DATETIME(6)" in ddl
    assert "last_request_digest BINARY(32)" in ddl
    assert "PRIMARY KEY (lease_key)" in ddl
    assert "fleet_schema_operation" in ddl
    assert "INSERT INTO platform_schema_operation_leases" in ddl
    assert "FOREIGN KEY" not in ddl
    assert all(len(name) <= 64 for name in _constraint_names(ddl))
    for forbidden in (
        "password",
        "password_hash",
        "ciphertext",
        "credential_secret",
        "dsn",
        "connection_url",
        "filesystem_path",
    ):
        assert forbidden not in lower_ddl


def _constraint_names(ddl: str) -> tuple[str, ...]:
    names: list[str] = []
    words = ddl.replace("\n", " ").replace("`", "").split()
    for index, word in enumerate(words[:-1]):
        if word.upper() == "CONSTRAINT":
            names.append(words[index + 1])
    return tuple(names)
