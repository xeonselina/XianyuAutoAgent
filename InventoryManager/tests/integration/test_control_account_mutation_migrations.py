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
from inventory_control.models.account_mutations import (
    TenantDatabaseAccountMutationLease,
    TenantDatabaseAccountRotation,
)

# Register the concurrently introduced 0017 models until root-level exports
# are merged.  This test never modifies those shared export files.
import inventory_control.models.backups  # noqa: F401, E402


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"
LEASE_TABLE = "tenant_database_account_mutation_leases"
ROTATION_TABLE = "tenant_database_account_rotations"
TABLES = {LEASE_TABLE, ROTATION_TABLE}
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
DIGEST = b"r" * 32


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_account_mutation_migration_round_trip_and_head_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    config = _alembic_config(database_url)

    command.upgrade(config, "202608220017")
    engine = sa.create_engine(database_url)
    try:
        assert TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220018")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        assert TABLES <= set(inspector.get_table_names())
        lease_pk = inspector.get_pk_constraint(LEASE_TABLE)
        assert lease_pk["constrained_columns"] == [
            "tenant_id",
            "account_kind",
        ]
        assert inspector.get_foreign_keys(LEASE_TABLE) == []
        assert inspector.get_foreign_keys(ROTATION_TABLE) == []
        rotation_columns = {
            column["name"]: column
            for column in inspector.get_columns(ROTATION_TABLE)
        }
        assert set(rotation_columns) == {
            column.name
            for column in TenantDatabaseAccountRotation.__table__.columns
        }
        assert rotation_columns["last_request_digest"]["type"].python_type is bytes
        assert rotation_columns["last_request_digest"]["type"].length == 32
        assert (
            TenantDatabaseAccountRotation.__table__
            .c.last_request_digest.type.length
            == 32
        )
    finally:
        engine.dispose()

    command.downgrade(config, "202608220017")
    engine = sa.create_engine(database_url)
    try:
        assert TABLES.isdisjoint(sa.inspect(engine).get_table_names())
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


def test_account_mutation_migration_enforces_lease_and_rotation_facts(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    command.upgrade(_alembic_config(database_url), "202608220018")
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    metadata.reflect(engine, only=tuple(TABLES))
    leases = metadata.tables[LEASE_TABLE]
    rotations = metadata.tables[ROTATION_TABLE]

    lease = {
        "tenant_id": "82000000-0000-4000-8000-000000000001",
        "account_kind": "dml",
        "fencing_token": 1,
        "lease_owner": "worker-a",
        "lease_purpose": "suspension_resolve",
        "lease_expires_at": NOW,
        "row_version": 2,
    }
    rotation = {
        "id": "82000000-0000-4000-8000-000000000002",
        "rotation_id": "82000000-0000-4000-8000-000000000003",
        "tenant_id": lease["tenant_id"],
        "database_uuid": "82000000-0000-4000-8000-000000000004",
        "account_kind": "dml",
        "purpose": "suspension_resolve",
        "from_username": "tenant_dml_g1",
        "from_credential_generation": 1,
        "from_root_key_version": 1,
        "from_derivation_version": 1,
        "to_username": "tenant_dml_g2",
        "to_credential_generation": 2,
        "to_root_key_version": 2,
        "to_derivation_version": 1,
        "inherited_desired_login_state": "locked",
        "expected_tenant_access_version": 3,
        "expected_route_version": 4,
        "expected_login_state_version": 5,
        "lease_owner": "worker-a",
        "lease_purpose": "suspension_resolve",
        "lease_fencing_token": 1,
        "state": "preparing",
        "candidate_locked": True,
        "candidate_published": False,
        "previous_locked": True,
        "previous_revoked": False,
        "transition_sequence": 1,
        "last_action": "start",
        "last_request_digest": DIGEST,
        "row_version": 1,
    }
    try:
        with engine.begin() as connection:
            connection.execute(sa.insert(leases).values(**lease))
            connection.execute(sa.insert(rotations).values(**rotation))

        invalid_leases = (
            {
                **lease,
                "tenant_id": "82000000-0000-4000-8000-000000000005",
                "lease_purpose": None,
            },
            {
                **lease,
                "tenant_id": "82000000-0000-4000-8000-000000000006",
                "fencing_token": 0,
            },
            {
                **lease,
                "tenant_id": "82000000-0000-4000-8000-000000000007",
                "account_kind": "backup",
            },
        )
        for invalid in invalid_leases:
            with pytest.raises((IntegrityError, OperationalError)):
                with engine.begin() as connection:
                    connection.execute(sa.insert(leases).values(**invalid))

        invalid_rotations = (
            {
                **rotation,
                "id": "82000000-0000-4000-8000-000000000008",
                "rotation_id": "82000000-0000-4000-8000-000000000009",
                "to_credential_generation": 3,
                "candidate_published": True,
            },
            {
                **rotation,
                "id": "82000000-0000-4000-8000-00000000000a",
                "rotation_id": "82000000-0000-4000-8000-00000000000b",
                "to_credential_generation": 4,
                "state": "unknown",
            },
        )
        for invalid in invalid_rotations:
            with pytest.raises((IntegrityError, OperationalError)):
                with engine.begin() as connection:
                    connection.execute(sa.insert(rotations).values(**invalid))

        padded_digest_rotation = {
            **rotation,
            "id": "82000000-0000-4000-8000-00000000000c",
            "rotation_id": "82000000-0000-4000-8000-00000000000d",
            "to_credential_generation": 5,
            "last_request_digest": b"short",
        }
        with engine.begin() as connection:
            connection.execute(
                sa.insert(rotations).values(**padded_digest_rotation)
            )
            stored_length = connection.scalar(
                sa.select(sa.func.length(rotations.c.last_request_digest)).where(
                    rotations.c.id == padded_digest_rotation["id"]
                )
            )
        assert stored_length == 32

        with pytest.raises((IntegrityError, OperationalError)):
            with engine.begin() as connection:
                connection.execute(
                    sa.insert(rotations).values(
                        **{
                            **rotation,
                            "id": "82000000-0000-4000-8000-00000000000e",
                            "rotation_id": (
                                "82000000-0000-4000-8000-00000000000f"
                            ),
                        }
                    )
                )
    finally:
        engine.dispose()


def test_account_mutation_migration_emits_mysql8_non_secret_offline_ddl():
    output = StringIO()
    config = _alembic_config(
        "mysql+pymysql://unused:unused@localhost/inventory_control"
    )
    config.output_buffer = output

    command.upgrade(config, "202608220017:202608220018", sql=True)
    ddl = output.getvalue()
    lower_ddl = ddl.lower()

    assert f"CREATE TABLE {LEASE_TABLE}" in ddl
    assert f"CREATE TABLE {ROTATION_TABLE}" in ddl
    assert "lease_expires_at DATETIME(6)" in ddl
    assert "last_request_digest BINARY(32) NOT NULL" in ddl
    assert "PRIMARY KEY (tenant_id, account_kind)" in ddl
    assert "uq_account_rotations_rotation_id" in ddl
    assert "uq_account_rotations_candidate_generation" in ddl
    assert "FOREIGN KEY" not in ddl
    assert all(len(name) <= 64 for name in _constraint_names(ddl))
    for forbidden in (
        "password",
        "password_hash",
        "ciphertext",
        "credential_secret",
        "dsn",
        "connection_url",
    ):
        assert forbidden not in lower_ddl


def _constraint_names(ddl: str) -> tuple[str, ...]:
    names: list[str] = []
    words = ddl.replace("\n", " ").replace("`", "").split()
    for index, word in enumerate(words[:-1]):
        if word.upper() == "CONSTRAINT":
            names.append(words[index + 1])
    return tuple(names)
