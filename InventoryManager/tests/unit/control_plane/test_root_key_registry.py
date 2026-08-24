from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import event

from inventory_control import (
    ControlBase,
    ControlDatabase,
    PlatformRootKeyVersion,
)
from inventory_control.crypto import (
    RootKeyLifecycle,
    RootKeyLoadError,
    RootKeyRegistryTransactionError,
    SqlAlchemyRootKeyRegistry,
)


KEY_V1 = bytes(range(32))
KEY_V2 = bytes(range(1, 33))
KEY_V3 = b"r" * 32
NOW = datetime(2026, 8, 22, 3, 30, tzinfo=timezone.utc)


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


def _write_key(directory: Path, version: int, material: bytes) -> None:
    path = directory / f"v{version}"
    path.write_bytes(base64.b64encode(material) + b"\n")
    path.chmod(0o400)


def _version(
    version: int,
    material: bytes,
    status: RootKeyLifecycle,
) -> PlatformRootKeyVersion:
    return PlatformRootKeyVersion(
        version=version,
        fingerprint_sha256=hashlib.sha256(material).digest(),
        status=status.value,
        activated_at=NOW,
        retired_at=NOW if status is RootKeyLifecycle.RETIRED else None,
    )


def _seed_registry(control_database: ControlDatabase) -> None:
    with control_database.transaction() as session:
        session.add_all(
            [
                _version(1, KEY_V1, RootKeyLifecycle.LEGACY),
                _version(2, KEY_V2, RootKeyLifecycle.ACTIVE),
                _version(3, KEY_V3, RootKeyLifecycle.RETIRED),
            ]
        )


def test_registry_adapter_locking_reads_active_and_legacy_without_writes(
    control_database,
    tmp_path,
):
    _seed_registry(control_database)
    _write_key(tmp_path, 1, KEY_V1)
    _write_key(tmp_path, 2, KEY_V2)

    executed: list[str] = []
    locking_reads: list[bool] = []

    def capture_sql(_connection, _cursor, statement, _parameters, _context, _many):
        executed.append(statement)

    event.listen(
        control_database.engine,
        "before_cursor_execute",
        capture_sql,
    )
    try:
        with control_database.transaction() as session:
            @event.listens_for(session, "do_orm_execute")
            def capture_orm(execute_state):
                if execute_state.is_select:
                    locking_reads.append(
                        execute_state.statement._for_update_arg is not None
                    )

            adapter = SqlAlchemyRootKeyRegistry(session=session)
            ring = adapter.load_root_key_ring(tmp_path)

            assert ring.active_version == 2
            assert ring.loaded_versions == (1, 2)
            assert ring.active_key.fingerprint_sha256 == hashlib.sha256(
                KEY_V2
            ).hexdigest()
            assert ring.key_for_existing_reference(1).version == 1
            with pytest.raises(RootKeyLoadError, match="unavailable"):
                ring.key_for_existing_reference(3)
            assert not session.new
            assert not session.dirty
            assert not session.deleted
    finally:
        event.remove(
            control_database.engine,
            "before_cursor_execute",
            capture_sql,
        )

    assert locking_reads == [True]
    assert executed
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in executed)


def test_registry_adapter_rejects_missing_and_autobegun_transactions(
    control_database,
    tmp_path,
):
    with control_database.new_session() as session:
        adapter = SqlAlchemyRootKeyRegistry(session=session)
        with pytest.raises(
            RootKeyRegistryTransactionError,
            match="caller-owned",
        ):
            adapter.load(tmp_path)

    with control_database.new_session() as session:
        session.scalar(sa.select(sa.literal(1)))
        adapter = SqlAlchemyRootKeyRegistry(session=session)
        with pytest.raises(
            RootKeyRegistryTransactionError,
            match="caller-owned",
        ):
            adapter.load(tmp_path)


def test_registry_adapter_rejects_dirty_explicit_transaction(
    control_database,
    tmp_path,
):
    _seed_registry(control_database)
    with control_database.new_session() as session:
        transaction = session.begin()
        row = session.get(PlatformRootKeyVersion, 1)
        assert row is not None
        row.status = RootKeyLifecycle.ACTIVE.value

        adapter = SqlAlchemyRootKeyRegistry(session=session)
        with pytest.raises(
            RootKeyRegistryTransactionError,
            match="caller-owned",
        ):
            adapter.load(tmp_path)
        assert row in session.dirty
        transaction.rollback()


def test_registry_adapter_fingerprint_mismatch_fails_closed(
    control_database,
    tmp_path,
):
    with control_database.transaction() as session:
        session.add(_version(1, KEY_V2, RootKeyLifecycle.ACTIVE))
    _write_key(tmp_path, 1, KEY_V1)

    with control_database.transaction() as session:
        adapter = SqlAlchemyRootKeyRegistry(session=session)
        with pytest.raises(RootKeyLoadError, match="fingerprint"):
            adapter.load(tmp_path)


def test_root_key_registry_model_contains_no_material_or_path_columns():
    columns = set(PlatformRootKeyVersion.__table__.c.keys())
    assert columns == {
        "version",
        "fingerprint_sha256",
        "status",
        "active_slot",
        "activated_at",
        "retired_at",
    }
    fingerprint_type = PlatformRootKeyVersion.__table__.c.fingerprint_sha256.type
    assert isinstance(fingerprint_type, sa.LargeBinary)
    assert fingerprint_type.length == 32
    assert "material" not in " ".join(columns)
    assert "path" not in " ".join(columns)
