from __future__ import annotations

from pathlib import Path

import pytest
from types import SimpleNamespace

from inventory_control import ControlBase
from inventory_control.default_migration import (
    DefaultSchemaQualificationInputError,
    DefaultSchemaQualificationTarget,
    DefaultSchemaQualificationTargetError,
    ExplicitConnectionAlembicQualificationRunner,
)
from inventory_control.default_migration import schema_qualification as _schema


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"
CONTROL_HEAD = "202608230038"


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self.rows


class _SqliteTargetStub:
    dialect = SimpleNamespace(name="sqlite")

    def __init__(self, file_name: str) -> None:
        self.file_name = file_name

    def exec_driver_sql(self, statement):
        assert statement == "PRAGMA database_list"
        return _Rows(({"name": "main", "file": self.file_name},))


@pytest.mark.parametrize("file_name", ["", "outside.sqlite"])
def test_sqlite_target_stub_fails_closed_without_opening_a_database(
    tmp_path,
    file_name,
):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = DefaultSchemaQualificationTarget(
        sqlite_scratch_root=allowed.resolve()
    )
    selected = "" if not file_name else str(tmp_path / file_name)
    with pytest.raises(DefaultSchemaQualificationTargetError):
        _schema._require_target(_SqliteTargetStub(selected), target)


def test_real_mysql_target_has_one_literal_name_and_explicit_authority(tmp_path):
    with pytest.raises(DefaultSchemaQualificationInputError):
        DefaultSchemaQualificationTarget(
            mysql_database_name="inventory_management",
            real_test_database_authorized=True,
        )
    with pytest.raises(DefaultSchemaQualificationInputError):
        DefaultSchemaQualificationTarget(
            mysql_database_name="inventory_management_test",
            real_test_database_authorized=False,
        )
    selected = DefaultSchemaQualificationTarget(
        mysql_database_name="inventory_management_test",
        real_test_database_authorized=True,
    )
    assert "inventory_management_test" not in repr(selected)


def test_configured_head_must_be_the_script_directories_only_head():
    with pytest.raises(DefaultSchemaQualificationInputError):
        ExplicitConnectionAlembicQualificationRunner(
            script_location=CONTROL_MIGRATIONS,
            target_metadata=ControlBase.metadata,
            schema_head="202608220024",
        )


class _MySqlOne:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def one(self):
        return self.row


class _MySqlTargetConnection:
    dialect = SimpleNamespace(name="mysql")

    def __init__(self, **extra):
        self.row = {
            "database_name": "inventory_management_test",
            "server_version": "8.0.36",
            "version_comment": "MySQL Community Server",
            "server_uuid": "89000000-0000-4000-8000-000000000099",
        }
        self.row.update(extra)

    def execute(self, statement):
        assert "@@server_uuid" in str(statement)
        return _MySqlOne(self.row)


def test_mysql_target_identity_is_bound_to_exact_server_and_test_schema():
    target = DefaultSchemaQualificationTarget(
        mysql_database_name="inventory_management_test",
        real_test_database_authorized=True,
    )
    dialect, first = _schema._require_target(
        _MySqlTargetConnection(),
        target,
    )
    _, replay = _schema._require_target(_MySqlTargetConnection(), target)
    _, another_server = _schema._require_target(
        _MySqlTargetConnection(
            server_uuid="89000000-0000-4000-8000-000000000098"
        ),
        target,
    )
    assert dialect == "mysql"
    assert first == replay
    assert first != another_server
    assert len(first) == 32


@pytest.mark.parametrize(
    "extra",
    [
        {"database_name": "inventory_management"},
        {"server_version": "8.0.29"},
        {
            "server_version": "8.0.36-MariaDB",
            "version_comment": "MariaDB Server",
        },
        {"server_uuid": "not-canonical"},
        {"server_uuid": "89000000-0000-4000-8000-000000000099 ",},
    ],
)
def test_mysql_target_profile_drift_is_rejected(extra):
    target = DefaultSchemaQualificationTarget(
        mysql_database_name="inventory_management_test",
        real_test_database_authorized=True,
    )
    with pytest.raises(DefaultSchemaQualificationTargetError):
        _schema._require_target(_MySqlTargetConnection(**extra), target)
