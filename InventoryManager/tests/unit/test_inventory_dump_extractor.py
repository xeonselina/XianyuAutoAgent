import pytest

from scripts.extract_inventory_dump import (
    UnsafeDatabaseError,
    extract_database,
)
from tests.support.test_database import assert_test_database_names


def test_extracts_only_inventory_management(tmp_path):
    source = tmp_path / "backup.sql"
    source.write_text(
        "CREATE DATABASE `mysql`;\nUSE `mysql`;\nCREATE TABLE secret(id int);\n"
        "CREATE DATABASE `inventory_management`;\nUSE `inventory_management`;\n"
        "CREATE TABLE devices(id int);\n",
        encoding="utf-8",
    )
    target = tmp_path / "restore.sql"

    summary = extract_database(
        source,
        target,
        target_database="inventory_management_restore_test",
    )

    text = target.read_text(encoding="utf-8")
    assert "CREATE TABLE devices" in text
    assert "secret" not in text
    assert "USE `inventory_management_restore_test`" in text
    assert "CREATE DATABASE `inventory_management_restore_test`" in text
    assert summary.source_database == "inventory_management"
    assert summary.target_database == "inventory_management_restore_test"
    assert "devices" not in repr(summary)


def test_refuses_system_database(tmp_path):
    with pytest.raises(UnsafeDatabaseError):
        extract_database(
            tmp_path / "backup.sql",
            tmp_path / "mysql.sql",
            target_database="mysql",
        )


def test_preserves_delimiter_and_trigger_in_source_database(tmp_path):
    source = tmp_path / "backup.sql"
    source.write_text(
        "-- Current Database: `inventory_management`\n"
        "CREATE DATABASE `inventory_management`;\n"
        "USE `inventory_management`;\n"
        "DELIMITER $$\n"
        "CREATE TRIGGER device_before_insert BEFORE INSERT ON devices\n"
        "FOR EACH ROW BEGIN\n"
        "  SET NEW.created_at = NOW();\n"
        "END$$\n"
        "DELIMITER ;\n"
        "-- Current Database: `mysql`\n"
        "USE `mysql`;\n"
        "CREATE TABLE secret(id int);\n",
        encoding="utf-8",
    )
    target = tmp_path / "restore.sql"

    extract_database(
        source,
        target,
        target_database="inventory_management_trigger_test",
    )

    text = target.read_text(encoding="utf-8")
    assert "DELIMITER $$" in text
    assert "CREATE TRIGGER device_before_insert" in text
    assert "END$$" in text
    assert "secret" not in text
    assert "USE `mysql`" not in text


def test_rejects_missing_source_without_replacing_existing_output(tmp_path):
    source = tmp_path / "backup.sql"
    source.write_text("USE `mysql`;\nCREATE TABLE secret(id int);\n", encoding="utf-8")
    target = tmp_path / "restore.sql"
    target.write_text("keep this file", encoding="utf-8")

    with pytest.raises(UnsafeDatabaseError, match="inventory_management"):
        extract_database(
            source,
            target,
            target_database="inventory_management_restore_test",
        )

    assert target.read_text(encoding="utf-8") == "keep this file"
    assert list(tmp_path.glob(".restore.sql.*.tmp")) == []


@pytest.mark.parametrize(
    "unsafe_statement",
    [
        "DROP DATABASE `mysql`;\n",
        "CREATE TABLE `mysql`.`stolen_devices` (id int);\n",
        "DROP TABLE `mysql`.stolen_devices;\n",
        "INSERT INTO mysql.`stolen_devices` (id) VALUES (1);\n",
        "RENAME TABLE mysql.stolen_devices TO inventory_management_restore_test.stolen_devices;\n",
    ],
)
def test_rejects_cross_database_sql_without_replacing_existing_output(
    tmp_path, unsafe_statement
):
    source = tmp_path / "backup.sql"
    source.write_text(
        "USE `inventory_management`;\n"
        "CREATE TABLE devices(id int);\n"
        f"{unsafe_statement}",
        encoding="utf-8",
    )
    target = tmp_path / "restore.sql"
    target.write_text("keep this file", encoding="utf-8")

    with pytest.raises(UnsafeDatabaseError, match="其他数据库"):
        extract_database(
            source,
            target,
            target_database="inventory_management_restore_test",
        )

    assert target.read_text(encoding="utf-8") == "keep this file"
    assert list(tmp_path.glob(".restore.sql.*.tmp")) == []


def test_preserves_cross_database_looking_text_in_literals_and_comments(tmp_path):
    source = tmp_path / "backup.sql"
    source.write_text(
        "USE `inventory_management`;\n"
        "CREATE TABLE devices(id int, note varchar(255));\n"
        "INSERT INTO devices(note) VALUES ('first line `mysql`.`x`\n"
        "second line still literal');\n"
        'INSERT INTO devices(note) VALUES ("first line `mysql`.`x`\n'
        'second line still literal");\n'
        "-- ordinary comment mentioning `mysql`.`x`\n"
        "/* block comment mentioning `mysql`.`x`\n"
        "   and continuing on the next line */\n"
        "DELIMITER $$\n"
        "CREATE TRIGGER device_before_insert BEFORE INSERT ON devices\n"
        "FOR EACH ROW BEGIN\n"
        "  SET NEW.note = 'trigger text: `mysql`.`x`';\n"
        "END$$\n"
        "DELIMITER ;\n",
        encoding="utf-8",
    )
    target = tmp_path / "restore.sql"

    extract_database(
        source,
        target,
        target_database="inventory_management_restore_test",
    )

    text = target.read_text(encoding="utf-8")
    assert "second line still literal" in text
    assert "ordinary comment mentioning `mysql`.`x`" in text
    assert "block comment mentioning `mysql`.`x`" in text
    assert "trigger text: `mysql`.`x`" in text


def test_preserves_identifiers_that_match_database_keywords(tmp_path):
    source = tmp_path / "backup.sql"
    source.write_text(
        "USE `inventory_management`;\n"
        "CREATE TABLE devices (`database` int);\n",
        encoding="utf-8",
    )
    target = tmp_path / "restore.sql"

    extract_database(
        source,
        target,
        target_database="inventory_management_restore_test",
    )

    assert "CREATE TABLE devices (`database` int);" in target.read_text(
        encoding="utf-8"
    )


def test_rejects_targets_that_are_not_explicit_test_databases(tmp_path):
    with pytest.raises(UnsafeDatabaseError):
        extract_database(
            tmp_path / "backup.sql",
            tmp_path / "restore.sql",
            target_database="inventory_management_restore",
        )

    with pytest.raises(RuntimeError):
        assert_test_database_names(
            "control_test",
            "inventory_management",
        )


def test_accepts_only_explicit_test_database_names():
    assert_test_database_names(
        "control_test",
        "tenant_a_test",
        "tenant_b_test",
    )
