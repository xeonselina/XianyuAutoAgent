from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import db as tenant_db
from inventory_control import ControlBase, ControlDatabase, Installation
from inventory_control.database import (
    read_database_utc_datetime,
    read_database_utc_value,
)
from inventory_control.transactions import require_caller_transaction


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


def test_control_metadata_and_session_are_independent(control_database):
    assert ControlBase.metadata is not tenant_db.metadata
    assert "control_installations" in ControlBase.metadata.tables
    assert "devices" not in ControlBase.metadata.tables
    assert "control_installations" not in tenant_db.metadata.tables

    with control_database.transaction() as session:
        session.add(Installation(marker_fingerprint="a" * 64))

    with control_database.new_session() as session:
        count = session.scalar(select(func.count()).select_from(Installation))

    assert count == 1


def test_control_transaction_rolls_back_and_closes(control_database):
    with pytest.raises(RuntimeError, match="force rollback"):
        with control_database.transaction() as session:
            session.add(Installation(marker_fingerprint="b" * 64))
            raise RuntimeError("force rollback")

    with control_database.new_session() as session:
        count = session.scalar(select(func.count()).select_from(Installation))

    assert count == 0


def test_shared_transaction_primitive_requires_caller_begin(control_database):
    with control_database.new_session() as session:
        with pytest.raises(RuntimeError):
            require_caller_transaction(session, RuntimeError)

        with session.begin():
            transaction = require_caller_transaction(session, RuntimeError)
            assert transaction is session.get_transaction()

        session.scalar(select(func.count()).select_from(Installation))
        with pytest.raises(RuntimeError):
            require_caller_transaction(session, RuntimeError)


def test_shared_transaction_primitive_can_accept_nested_scope(control_database):
    with control_database.new_session() as session:
        session.scalar(select(func.count()).select_from(Installation))
        with session.begin_nested():
            transaction = require_caller_transaction(
                session,
                RuntimeError,
                accept_nested=True,
            )
            assert transaction is session.get_nested_transaction()


def test_shared_transaction_primitive_rejects_invalid_or_dirty_session(
    control_database,
):
    with pytest.raises(ValueError):
        require_caller_transaction(
            None,
            RuntimeError,
            invalid_session_error=ValueError,
        )

    with pytest.raises(RuntimeError):
        with control_database.transaction() as session:
            session.add(Installation(marker_fingerprint="c" * 64))
            require_caller_transaction(session, RuntimeError, clean=True)

    with pytest.raises(ValueError):
        with control_database.transaction() as session:
            session.add(Installation(marker_fingerprint="d" * 64))
            require_caller_transaction(
                session,
                RuntimeError,
                clean=True,
                dirty_error=ValueError,
            )


def test_empty_control_database_url_is_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        ControlDatabase.from_url("  ")


def test_database_utc_clock_returns_datetime(control_database):
    with control_database.new_session() as session:
        value = read_database_utc_value(session)

    assert isinstance(value, datetime)


@pytest.mark.parametrize("dialect_name", ["mysql", "mariadb"])
def test_database_utc_clock_uses_microsecond_utc_on_mysql(dialect_name):
    session = Session()
    statements = []
    session.get_bind = lambda: SimpleNamespace(
        dialect=SimpleNamespace(name=dialect_name)
    )
    session.scalar = lambda statement: statements.append(str(statement)) or datetime(
        2026, 8, 22, 12, 0
    )
    try:
        value = read_database_utc_value(session)
    finally:
        session.close()

    assert value == datetime(2026, 8, 22, 12, 0)
    assert statements == ["SELECT UTC_TIMESTAMP(6)"]


def test_database_utc_datetime_normalizes_naive_mysql_value():
    session = Session()
    session.get_bind = lambda: SimpleNamespace(dialect=SimpleNamespace(name="mysql"))
    session.scalar = lambda _statement: datetime(2026, 8, 22, 12, 0)
    try:
        value = read_database_utc_datetime(session)
    finally:
        session.close()

    assert value == datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
