"""Fail-closed MariaDB 10.11 to MySQL 8 dump/restore test runner."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import tempfile

import sqlalchemy as sa
from sqlalchemy.engine import Engine, URL

from tests.support.test_database import (
    assert_current_user_has_test_only_grants,
    assert_test_database_url,
)


PORTABILITY_TABLES = ("audit_logs", "devices", "rentals")
_MYSQL_8 = re.compile(r"^8\.0\.(?P<patch>[0-9]+)(?:[-+].*)?$")
_MARIADB_10_11 = re.compile(r"^10\.11\.[0-9]+(?:[-+].*)?MariaDB.*$")
_CONTAINER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_MARIADB_SANDBOX_LINE = r"/*M!999999\- enable the sandbox mode */"
_FORBIDDEN_DUMP_LINE = re.compile(
    r"^\s*(?:CREATE\s+DATABASE|USE\s+|GRANT\s+|REVOKE\s+|"
    r"CREATE\s+USER|ALTER\s+USER|LOAD\s+DATA|SOURCE\s+|DELIMITER\s+|"
    r"\\!|.*\bINTO\s+(?:OUTFILE|DUMPFILE)\b)",
    re.IGNORECASE,
)
_MAX_DUMP_BYTES = 16 * 1024 * 1024


class DefaultPortabilityTestError(RuntimeError):
    code = "DEFAULT_MIGRATION_PORTABILITY_TEST_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class DefaultPortabilityObservation:
    source_version: str
    target_version: str
    source_character_set: str
    source_collation: str
    target_character_set: str
    target_collation: str
    table_counts: tuple[tuple[str, int], ...]
    dump_size_bytes: int


def run_default_mariadb_mysql_portability(
    *,
    source_read_engine: Engine,
    target_write_engine: Engine,
    docker_binary: Path,
    source_dump_container: str,
    mysql_binary: Path,
) -> DefaultPortabilityObservation:
    """Dump three fixed synthetic tables, restore, and convert to utf8mb4."""

    source_url = _validated_engine(source_read_engine)
    target_url = _validated_engine(target_write_engine)
    if _endpoint(source_url) == _endpoint(target_url):
        raise DefaultPortabilityTestError()
    docker = _binary(docker_binary, "docker")
    dump_container = _container_name(source_dump_container)
    restore_binary = _binary(mysql_binary, "mysql")

    with source_read_engine.connect() as source_connection:
        assert_current_user_has_test_only_grants(
            source_connection,
            source_url.database,
        )
        _require_source_read_only_grants(source_connection)
        source_profile = _source_profile(source_connection)
        source_counts = _table_counts(source_connection)
    with target_write_engine.connect() as target_connection:
        assert_current_user_has_test_only_grants(
            target_connection,
            target_url.database,
        )
        target_profile = _target_profile(target_connection)
        if _base_tables(target_connection):
            raise DefaultPortabilityTestError()

    with tempfile.TemporaryDirectory(
        prefix="inventory-default-portability-"
    ) as temporary:
        root = Path(temporary)
        os.chmod(root, 0o700)
        target_defaults = root / "target.cnf"
        dump_path = root / "legacy.sql"
        _write_defaults(target_defaults, target_url)
        _run_dump(
            docker_binary=docker,
            source_container=dump_container,
            source_url=source_url,
            database=source_url.database,
            dump_path=dump_path,
        )
        dump_size = dump_path.stat().st_size
        dump_size = _normalize_and_validate_dump(
            dump_path,
            dump_size=dump_size,
        )
        _run_restore(
            binary=restore_binary,
            defaults_file=target_defaults,
            database=target_url.database,
            dump_path=dump_path,
        )

    with target_write_engine.begin() as target_connection:
        if _table_counts(target_connection) != source_counts:
            raise DefaultPortabilityTestError()
        _convert_target_to_utf8mb4(target_connection)
    with target_write_engine.connect() as target_connection:
        target_character_set, target_collation = _target_collation(
            target_connection
        )
        if _table_counts(target_connection) != source_counts:
            raise DefaultPortabilityTestError()

    return DefaultPortabilityObservation(
        source_version=source_profile[0],
        target_version=target_profile[0],
        source_character_set=source_profile[1],
        source_collation=source_profile[2],
        target_character_set=target_character_set,
        target_collation=target_collation,
        table_counts=source_counts,
        dump_size_bytes=dump_size,
    )


def require_empty_scoped_test_database(engine: Engine) -> None:
    """Authorize a fixed synthetic setup only while the exact schema is empty."""

    url = _validated_engine(engine)
    with engine.connect() as connection:
        assert_current_user_has_test_only_grants(connection, url.database)
        if _base_tables(connection):
            raise DefaultPortabilityTestError()


def _validated_engine(engine: Engine) -> URL:
    if not isinstance(engine, Engine) or engine.dialect.name != "mysql":
        raise DefaultPortabilityTestError()
    try:
        return assert_test_database_url(
            engine.url.render_as_string(hide_password=False)
        )
    except Exception:
        raise DefaultPortabilityTestError() from None


def _endpoint(url: URL) -> tuple[str, int, str]:
    if (
        not isinstance(url.host, str)
        or not url.host
        or isinstance(url.port, bool)
        or not isinstance(url.port, int)
        or url.port < 1
        or not isinstance(url.database, str)
    ):
        raise DefaultPortabilityTestError()
    return url.host, url.port, url.database


def _binary(path: Path, expected_name: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise DefaultPortabilityTestError()
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise DefaultPortabilityTestError() from None
    if not resolved.is_file() or resolved.name != expected_name:
        raise DefaultPortabilityTestError()
    return resolved


def _container_name(value: str) -> str:
    if not isinstance(value, str) or _CONTAINER_NAME.fullmatch(value) is None:
        raise DefaultPortabilityTestError()
    return value


def _source_profile(connection) -> tuple[str, str, str]:
    row = connection.exec_driver_sql(
        "SELECT CAST(@@version AS CHAR), "
        "CAST(@@version_comment AS CHAR), "
        "CAST(@@character_set_database AS CHAR), "
        "CAST(@@collation_database AS CHAR)"
    ).one()
    version, comment, character_set, collation = tuple(row)
    if (
        not isinstance(version, str)
        or _MARIADB_10_11.fullmatch(version) is None
        or not isinstance(comment, str)
        or "mariadb" not in comment.lower()
        or character_set not in {"utf8", "utf8mb3"}
        or collation != "utf8mb3_general_ci"
    ):
        raise DefaultPortabilityTestError()
    return version, "utf8mb3", collation


def _target_profile(connection) -> tuple[str]:
    row = connection.exec_driver_sql(
        "SELECT CAST(@@version AS CHAR), CAST(@@version_comment AS CHAR)"
    ).one()
    version, comment = tuple(row)
    matched = _MYSQL_8.fullmatch(version) if isinstance(version, str) else None
    if (
        matched is None
        or int(matched.group("patch")) < 30
        or not isinstance(comment, str)
        or "mariadb" in comment.lower()
    ):
        raise DefaultPortabilityTestError()
    return (version,)


def _require_source_read_only_grants(connection) -> None:
    rows = tuple(connection.exec_driver_sql("SHOW GRANTS FOR CURRENT_USER"))
    grants = tuple(tuple(row)[0].upper() for row in rows)
    if (
        len(grants) != 2
        or not any(grant.startswith("GRANT USAGE ON *.*") for grant in grants)
        or not any(
            "GRANT SELECT, SHOW VIEW ON `INVENTORY_MANAGEMENT_TEST`.*"
            in grant
            for grant in grants
        )
        or any(
            token in grant
            for grant in grants
            for token in (
                " INSERT",
                " UPDATE",
                " DELETE",
                " CREATE",
                " ALTER",
                " DROP",
                " GRANT OPTION",
            )
        )
    ):
        raise DefaultPortabilityTestError()


def _base_tables(connection) -> tuple[str, ...]:
    return tuple(
        row[0]
        for row in connection.exec_driver_sql(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME"
        )
    )


def _table_counts(connection) -> tuple[tuple[str, int], ...]:
    if _base_tables(connection) != PORTABILITY_TABLES:
        raise DefaultPortabilityTestError()
    counts = []
    for table in PORTABILITY_TABLES:
        value = connection.exec_driver_sql(
            f"SELECT COUNT(*) FROM `{table}`"
        ).scalar_one()
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise DefaultPortabilityTestError()
        counts.append((table, value))
    return tuple(counts)


def _write_defaults(path: Path, url: URL) -> None:
    text = _defaults_text(url)
    try:
        with path.open("x", encoding="utf-8") as handle:
            os.chmod(path, 0o600)
            handle.write(text)
    except OSError:
        raise DefaultPortabilityTestError() from None


def _defaults_text(
    url: URL,
    *,
    host: str | None = None,
    port: int | None = None,
) -> str:
    if (
        not isinstance(url.username, str)
        or not url.username
        or not isinstance(url.password, str)
    ):
        raise DefaultPortabilityTestError()
    url_host, url_port, _database = _endpoint(url)
    selected_host = url_host if host is None else host
    selected_port = url_port if port is None else port
    if (
        not isinstance(selected_host, str)
        or not selected_host
        or isinstance(selected_port, bool)
        or not isinstance(selected_port, int)
        or selected_port < 1
    ):
        raise DefaultPortabilityTestError()
    values = {
        "user": url.username,
        "password": url.password,
        "host": selected_host,
        "port": str(selected_port),
    }
    lines = ["[client]"]
    lines.extend(
        f'{key}="{_option_value(value)}"' for key, value in values.items()
    )
    lines.extend(("protocol=tcp", "default-character-set=utf8mb4"))
    return "\n".join(lines) + "\n"


def _option_value(value: str) -> str:
    if not isinstance(value, str) or "\x00" in value or "\n" in value or "\r" in value:
        raise DefaultPortabilityTestError()
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _run_dump(
    *,
    docker_binary: Path,
    source_container: str,
    source_url: URL,
    database: str,
    dump_path: Path,
) -> None:
    defaults = _defaults_text(
        source_url,
        host="127.0.0.1",
        port=3306,
    ).encode("utf-8")
    command = (
        str(docker_binary),
        "exec",
        "-i",
        source_container,
        "mariadb-dump",
        "--defaults-extra-file=/dev/stdin",
        "--single-transaction",
        "--skip-lock-tables",
        "--skip-add-locks",
        "--skip-disable-keys",
        "--skip-triggers",
        "--skip-routines",
        "--skip-events",
        "--skip-comments",
        "--skip-dump-date",
        database,
        *PORTABILITY_TABLES,
    )
    try:
        with dump_path.open("xb") as output:
            os.chmod(dump_path, 0o600)
            completed = subprocess.run(
                command,
                input=defaults,
                stdout=output,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=60,
            )
    except (OSError, subprocess.SubprocessError):
        raise DefaultPortabilityTestError() from None
    if completed.returncode != 0:
        raise DefaultPortabilityTestError()


def _normalize_and_validate_dump(path: Path, *, dump_size: int) -> int:
    if dump_size < 1 or dump_size > _MAX_DUMP_BYTES:
        raise DefaultPortabilityTestError()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise DefaultPortabilityTestError() from None
    lines = text.splitlines()
    if lines and lines[0].strip() == _MARIADB_SANDBOX_LINE:
        lines = lines[1:]
        text = "\n".join(lines) + "\n"
        try:
            path.write_text(text, encoding="utf-8")
            os.chmod(path, 0o600)
        except OSError:
            raise DefaultPortabilityTestError() from None
        dump_size = path.stat().st_size
    if "/*M!" in text or "DEFINER=" in text.upper():
        raise DefaultPortabilityTestError()
    for line in lines:
        if _FORBIDDEN_DUMP_LINE.search(line):
            raise DefaultPortabilityTestError()
    for table in PORTABILITY_TABLES:
        if f"CREATE TABLE `{table}`" not in text:
            raise DefaultPortabilityTestError()
    if dump_size < 1 or dump_size > _MAX_DUMP_BYTES:
        raise DefaultPortabilityTestError()
    return dump_size


def _run_restore(
    *,
    binary: Path,
    defaults_file: Path,
    database: str,
    dump_path: Path,
) -> None:
    command = (
        str(binary),
        f"--defaults-extra-file={defaults_file}",
        "--binary-mode=1",
        f"--database={database}",
    )
    try:
        with dump_path.open("rb") as source:
            completed = subprocess.run(
                command,
                stdin=source,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=60,
            )
    except (OSError, subprocess.SubprocessError):
        raise DefaultPortabilityTestError() from None
    if completed.returncode != 0:
        raise DefaultPortabilityTestError()


def _convert_target_to_utf8mb4(connection) -> None:
    connection.exec_driver_sql(
        "ALTER DATABASE `inventory_management_test` "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
    )
    for table in PORTABILITY_TABLES:
        connection.exec_driver_sql(
            f"ALTER TABLE `{table}` CONVERT TO CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_0900_ai_ci"
        )


def _target_collation(connection) -> tuple[str, str]:
    database_row = connection.exec_driver_sql(
        "SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME "
        "FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = DATABASE()"
    ).one()
    table_rows = tuple(
        connection.exec_driver_sql(
            "SELECT TABLE_COLLATION FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME"
        )
    )
    column_rows = tuple(
        connection.exec_driver_sql(
            "SELECT CHARACTER_SET_NAME, COLLATION_NAME "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND CHARACTER_SET_NAME IS NOT NULL "
            "ORDER BY TABLE_NAME, ORDINAL_POSITION"
        )
    )
    if (
        tuple(database_row) != ("utf8mb4", "utf8mb4_0900_ai_ci")
        or any(tuple(row) != ("utf8mb4_0900_ai_ci",) for row in table_rows)
        or not column_rows
        or any(
            tuple(row) != ("utf8mb4", "utf8mb4_0900_ai_ci")
            for row in column_rows
        )
    ):
        raise DefaultPortabilityTestError()
    return "utf8mb4", "utf8mb4_0900_ai_ci"


__all__ = [
    "DefaultPortabilityObservation",
    "DefaultPortabilityTestError",
    "PORTABILITY_TABLES",
    "require_empty_scoped_test_database",
    "run_default_mariadb_mysql_portability",
]
