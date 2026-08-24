from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
import hashlib
import json
import logging
import os
import re
from typing import Callable

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError, OperationalError

from config import TestingConfig


WRITABLE_TEST_DATABASE_NAME = "inventory_management_test"
REAL_TEST_DATABASE_OPT_IN = "ALLOW_REAL_TEST_DATABASE"
GLOBAL_DBA_TEST_ACCOUNT_OPT_IN = "ALLOW_GLOBAL_DBA_TEST_ACCOUNT"
TEST_SCHEMA_INVENTORY_ROW_LIMIT = 20_000
TEST_GENERATION_ROW_LIMIT = 128
TEST_SCHEMA_ADVISORY_LOCK_NAME = "inventory_management_test:pytest:metadata:v1"
TEST_CURRENT_ROLE_SQL = "SELECT COALESCE(CURRENT_ROLE(), 'NONE')"
TEST_DATABASE_PROFILE_SQL = "SELECT VERSION(), @@version_comment"
TEST_MARIADB_PUBLIC_GRANTS_SQL = "SHOW GRANTS FOR PUBLIC"
TEST_SCHEMA_ACQUIRE_LOCK_SQL = (
    "SELECT GET_LOCK('inventory_management_test:pytest:metadata:v1', 0)"
)
TEST_SCHEMA_RELEASE_LOCK_SQL = (
    "SELECT RELEASE_LOCK('inventory_management_test:pytest:metadata:v1')"
)
DATABASE_CONSTRAINT_ERRORS = (IntegrityError, OperationalError)


class RedactedTestDatabaseUrl(str):
    """A usable SQLAlchemy URL whose diagnostics never reveal credentials."""

    def __repr__(self) -> str:
        return "RedactedTestDatabaseUrl('<redacted>')"


def alembic_config_database_url(value: str) -> str:
    """Escape URL percent-encoding for Alembic's interpolating parser."""

    if not isinstance(value, str) or not value:
        raise TypeError("database URL 必须是非空字符串")
    return value.replace("%", "%%")


TEST_SCHEMA_INVENTORY_SQL = (
    "SELECT TABLE_NAME, TABLE_TYPE, ENGINE, TABLE_COLLATION "
    "FROM INFORMATION_SCHEMA.TABLES "
    "WHERE TABLE_SCHEMA = DATABASE() ORDER BY TABLE_NAME "
    "LIMIT 20001"
)
TEST_SCHEMA_COLUMN_INVENTORY_SQL = (
    "SELECT TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, COLUMN_TYPE, "
    "IS_NULLABLE, COLUMN_DEFAULT, EXTRA "
    "FROM INFORMATION_SCHEMA.COLUMNS "
    "WHERE TABLE_SCHEMA = DATABASE() "
    "ORDER BY TABLE_NAME, ORDINAL_POSITION LIMIT 20001"
)
TEST_SCHEMA_INDEX_INVENTORY_SQL = (
    "SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME, "
    "COLLATION, SUB_PART, NULLABLE, INDEX_TYPE, COMMENT, INDEX_COMMENT "
    "FROM INFORMATION_SCHEMA.STATISTICS "
    "WHERE TABLE_SCHEMA = DATABASE() "
    "ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX LIMIT 20001"
)
TEST_SCHEMA_CONSTRAINT_INVENTORY_SQL = (
    "SELECT TABLE_NAME, CONSTRAINT_NAME, CONSTRAINT_TYPE "
    "FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
    "WHERE TABLE_SCHEMA = DATABASE() "
    "ORDER BY TABLE_NAME, CONSTRAINT_NAME LIMIT 20001"
)
TEST_SCHEMA_FOREIGN_KEY_INVENTORY_SQL = (
    "SELECT k.TABLE_NAME, k.CONSTRAINT_NAME, k.COLUMN_NAME, "
    "k.ORDINAL_POSITION, k.REFERENCED_TABLE_SCHEMA, "
    "k.REFERENCED_TABLE_NAME, k.REFERENCED_COLUMN_NAME, "
    "r.MATCH_OPTION, r.UPDATE_RULE, r.DELETE_RULE "
    "FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS k "
    "LEFT JOIN INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS AS r "
    "ON r.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA "
    "AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME "
    "AND r.TABLE_NAME = k.TABLE_NAME "
    "WHERE k.TABLE_SCHEMA = DATABASE() "
    "AND k.REFERENCED_TABLE_NAME IS NOT NULL "
    "ORDER BY k.TABLE_NAME, k.CONSTRAINT_NAME, k.ORDINAL_POSITION "
    "LIMIT 20001"
)
TEST_SCHEMA_CHECK_INVENTORY_SQL = (
    "SELECT tc.TABLE_NAME, cc.CONSTRAINT_NAME, cc.CHECK_CLAUSE "
    "FROM INFORMATION_SCHEMA.CHECK_CONSTRAINTS AS cc "
    "JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS tc "
    "ON tc.CONSTRAINT_SCHEMA = cc.CONSTRAINT_SCHEMA "
    "AND tc.CONSTRAINT_NAME = cc.CONSTRAINT_NAME "
    "WHERE cc.CONSTRAINT_SCHEMA = DATABASE() "
    "AND tc.TABLE_SCHEMA = DATABASE() AND tc.CONSTRAINT_TYPE = 'CHECK' "
    "ORDER BY tc.TABLE_NAME, cc.CONSTRAINT_NAME LIMIT 20001"
)
TEST_SCHEMA_PARTITION_INVENTORY_SQL = (
    "SELECT TABLE_NAME, PARTITION_NAME, SUBPARTITION_NAME, "
    "PARTITION_ORDINAL_POSITION, SUBPARTITION_ORDINAL_POSITION, "
    "PARTITION_METHOD, SUBPARTITION_METHOD, PARTITION_EXPRESSION, "
    "SUBPARTITION_EXPRESSION, PARTITION_DESCRIPTION "
    "FROM INFORMATION_SCHEMA.PARTITIONS "
    "WHERE TABLE_SCHEMA = DATABASE() "
    "ORDER BY TABLE_NAME, PARTITION_ORDINAL_POSITION, "
    "SUBPARTITION_ORDINAL_POSITION LIMIT 20001"
)
TEST_SCHEMA_VIEW_INVENTORY_SQL = (
    "SELECT TABLE_NAME, VIEW_DEFINITION, CHECK_OPTION, IS_UPDATABLE, "
    "DEFINER, SECURITY_TYPE, CHARACTER_SET_CLIENT, COLLATION_CONNECTION "
    "FROM INFORMATION_SCHEMA.VIEWS WHERE TABLE_SCHEMA = DATABASE() "
    "ORDER BY TABLE_NAME LIMIT 20001"
)
TEST_SCHEMA_TRIGGER_INVENTORY_SQL = (
    "SELECT TRIGGER_NAME, EVENT_MANIPULATION, EVENT_OBJECT_TABLE, "
    "ACTION_ORDER, ACTION_CONDITION, ACTION_STATEMENT, ACTION_ORIENTATION, "
    "ACTION_TIMING, SQL_MODE, DEFINER, CHARACTER_SET_CLIENT, "
    "COLLATION_CONNECTION, DATABASE_COLLATION "
    "FROM INFORMATION_SCHEMA.TRIGGERS "
    "WHERE TRIGGER_SCHEMA = DATABASE() "
    "ORDER BY TRIGGER_NAME LIMIT 20001"
)
TEST_SCHEMA_ROUTINE_INVENTORY_SQL = (
    "SELECT ROUTINE_NAME, ROUTINE_TYPE, DATA_TYPE, DTD_IDENTIFIER, "
    "ROUTINE_DEFINITION, IS_DETERMINISTIC, SQL_DATA_ACCESS, SECURITY_TYPE, "
    "SQL_MODE, DEFINER, CHARACTER_SET_CLIENT, COLLATION_CONNECTION, "
    "DATABASE_COLLATION FROM INFORMATION_SCHEMA.ROUTINES "
    "WHERE ROUTINE_SCHEMA = DATABASE() "
    "ORDER BY ROUTINE_NAME, ROUTINE_TYPE LIMIT 20001"
)
TEST_SCHEMA_PARAMETER_INVENTORY_SQL = (
    "SELECT SPECIFIC_NAME, ORDINAL_POSITION, PARAMETER_MODE, PARAMETER_NAME, "
    "DATA_TYPE, DTD_IDENTIFIER, CHARACTER_SET_NAME, COLLATION_NAME "
    "FROM INFORMATION_SCHEMA.PARAMETERS "
    "WHERE SPECIFIC_SCHEMA = DATABASE() "
    "ORDER BY SPECIFIC_NAME, ORDINAL_POSITION LIMIT 20001"
)
TEST_SCHEMA_EVENT_INVENTORY_SQL = (
    "SELECT EVENT_NAME, EVENT_DEFINITION, EVENT_TYPE, EXECUTE_AT, "
    "INTERVAL_VALUE, INTERVAL_FIELD, STARTS, ENDS, STATUS, ON_COMPLETION, "
    "SQL_MODE, DEFINER, CHARACTER_SET_CLIENT, COLLATION_CONNECTION, "
    "DATABASE_COLLATION FROM INFORMATION_SCHEMA.EVENTS "
    "WHERE EVENT_SCHEMA = DATABASE() ORDER BY EVENT_NAME LIMIT 20001"
)
TEST_ALEMBIC_GENERATION_SQL = (
    "SELECT version_num FROM alembic_version ORDER BY version_num LIMIT 129"
)
TEST_IDENTITY_GENERATION_SQL = (
    "SELECT singleton_key, schema_generation FROM database_identity "
    "ORDER BY singleton_key LIMIT 129"
)
TEST_SCHEMA_EXTENSION_INVENTORY_STATEMENTS = (
    TEST_SCHEMA_INDEX_INVENTORY_SQL,
    TEST_SCHEMA_CONSTRAINT_INVENTORY_SQL,
    TEST_SCHEMA_FOREIGN_KEY_INVENTORY_SQL,
    TEST_SCHEMA_CHECK_INVENTORY_SQL,
    TEST_SCHEMA_PARTITION_INVENTORY_SQL,
    TEST_SCHEMA_VIEW_INVENTORY_SQL,
    TEST_SCHEMA_TRIGGER_INVENTORY_SQL,
    TEST_SCHEMA_ROUTINE_INVENTORY_SQL,
    TEST_SCHEMA_PARAMETER_INVENTORY_SQL,
    TEST_SCHEMA_EVENT_INVENTORY_SQL,
)
_FIXED_TEST_SCHEMA_READ_STATEMENTS = {
    TEST_SCHEMA_INVENTORY_SQL: (4, TEST_SCHEMA_INVENTORY_ROW_LIMIT),
    TEST_SCHEMA_COLUMN_INVENTORY_SQL: (7, TEST_SCHEMA_INVENTORY_ROW_LIMIT),
    TEST_SCHEMA_INDEX_INVENTORY_SQL: (11, TEST_SCHEMA_INVENTORY_ROW_LIMIT),
    TEST_SCHEMA_CONSTRAINT_INVENTORY_SQL: (
        3,
        TEST_SCHEMA_INVENTORY_ROW_LIMIT,
    ),
    TEST_SCHEMA_FOREIGN_KEY_INVENTORY_SQL: (
        10,
        TEST_SCHEMA_INVENTORY_ROW_LIMIT,
    ),
    TEST_SCHEMA_CHECK_INVENTORY_SQL: (3, TEST_SCHEMA_INVENTORY_ROW_LIMIT),
    TEST_SCHEMA_PARTITION_INVENTORY_SQL: (
        10,
        TEST_SCHEMA_INVENTORY_ROW_LIMIT,
    ),
    TEST_SCHEMA_VIEW_INVENTORY_SQL: (8, TEST_SCHEMA_INVENTORY_ROW_LIMIT),
    TEST_SCHEMA_TRIGGER_INVENTORY_SQL: (
        13,
        TEST_SCHEMA_INVENTORY_ROW_LIMIT,
    ),
    TEST_SCHEMA_ROUTINE_INVENTORY_SQL: (
        13,
        TEST_SCHEMA_INVENTORY_ROW_LIMIT,
    ),
    TEST_SCHEMA_PARAMETER_INVENTORY_SQL: (
        8,
        TEST_SCHEMA_INVENTORY_ROW_LIMIT,
    ),
    TEST_SCHEMA_EVENT_INVENTORY_SQL: (15, TEST_SCHEMA_INVENTORY_ROW_LIMIT),
    TEST_ALEMBIC_GENERATION_SQL: (1, TEST_GENERATION_ROW_LIMIT),
    TEST_IDENTITY_GENERATION_SQL: (2, TEST_GENERATION_ROW_LIMIT),
}
_SCHEMA_INVENTORY_STATEMENTS = (
    TEST_SCHEMA_INVENTORY_SQL,
    TEST_SCHEMA_COLUMN_INVENTORY_SQL,
    *TEST_SCHEMA_EXTENSION_INVENTORY_STATEMENTS,
)
_READ_ONLY_PRIVILEGES = frozenset({"SELECT", "SHOW VIEW"})
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_LOGGER = logging.getLogger(__name__)


class DatabaseWriteDisposition(str, Enum):
    """Explicit outcome selected after observing a real test schema."""

    FAIL_CLOSED = "fail_closed"
    METADATA_REBUILD = "metadata_rebuild"
    MIGRATE = "migrate"


class ProductionReadCapability(str, Enum):
    """Closed, versioned production observation surface."""

    SCHEMA_METADATA_AND_GENERATIONS_V1 = "schema_metadata_and_generations.v1"


class DatabaseObservationProfile(str, Enum):
    MYSQL_8 = "mysql-8.v1"
    MARIADB_10_11 = "mariadb-10.11.v1"


@dataclass(frozen=True)
class DatabaseSchemaPreflight:
    """Immutable actual-schema evidence captured before a test DB write."""

    database_name: str
    database_profile: DatabaseObservationProfile
    database_version: str
    database_version_comment: str
    disposition: DatabaseWriteDisposition
    table_inventory: tuple[tuple[object, ...], ...]
    column_inventory: tuple[tuple[object, ...], ...]
    index_inventory: tuple[tuple[object, ...], ...]
    constraint_inventory: tuple[tuple[object, ...], ...]
    foreign_key_inventory: tuple[tuple[object, ...], ...]
    check_inventory: tuple[tuple[object, ...], ...]
    partition_inventory: tuple[tuple[object, ...], ...]
    view_inventory: tuple[tuple[object, ...], ...]
    trigger_inventory: tuple[tuple[object, ...], ...]
    routine_inventory: tuple[tuple[object, ...], ...]
    parameter_inventory: tuple[tuple[object, ...], ...]
    event_inventory: tuple[tuple[object, ...], ...]
    alembic_versions: tuple[object, ...]
    identity_generations: tuple[tuple[object, ...], ...]
    drift_reasons: tuple[str, ...]
    preflight_digest: str

    @property
    def is_empty(self) -> bool:
        return not self.table_inventory

    @property
    def is_drifted(self) -> bool:
        return bool(self.drift_reasons)


class DatabaseWriteRefused(RuntimeError):
    """Fail-closed result that retains the read-only preflight evidence."""

    def __init__(self, message: str, preflight: DatabaseSchemaPreflight):
        super().__init__(message)
        self.preflight = preflight


@dataclass(frozen=True)
class ProductionSchemaObservation:
    capability: ProductionReadCapability
    schema: DatabaseSchemaPreflight


def assert_test_database_url(url: str):
    """只允许测试进程写入明确指定的隔离 MySQL schema。"""
    if os.environ.get("TESTING", "").lower() != "true":
        raise RuntimeError("必须设置 TESTING=true")
    if os.environ.get(REAL_TEST_DATABASE_OPT_IN, "").lower() != "true":
        raise RuntimeError("必须显式设置 ALLOW_REAL_TEST_DATABASE=true")

    parsed = make_url(url)
    if parsed.get_backend_name() != "mysql":
        raise RuntimeError("TEST_DATABASE_URL 必须使用 MySQL")
    if parsed.database != WRITABLE_TEST_DATABASE_NAME:
        raise RuntimeError("测试写入只允许数据库 inventory_management_test")
    _assert_safe_mysql_url_query(parsed)
    return parsed


def assert_current_user_has_test_only_grants(connection, database_name: str):
    """Confirm schema-only grants or one explicitly approved manual DBA."""
    if database_name != WRITABLE_TEST_DATABASE_NAME:
        raise RuntimeError("测试授权检查只允许 inventory_management_test")
    selected_database = connection.exec_driver_sql("SELECT DATABASE()").scalar_one()
    if selected_database != WRITABLE_TEST_DATABASE_NAME:
        raise RuntimeError("测试连接未选择 inventory_management_test")
    _assert_no_active_database_roles(connection, production=False)
    profile, _version, _comment = _detect_database_observation_profile(connection)
    _assert_mariadb_public_has_usage_only(connection, profile)
    grants = _read_current_user_grants(connection)
    if not grants:
        raise RuntimeError("无法验证测试数据库账号权限")
    allowed_database_targets = {
        f"`{database_name}`.*",
        f"{database_name}.*",
    }

    global_dba_enabled = _global_dba_test_account_enabled()
    saw_global_dba = False
    for grant in grants:
        if global_dba_enabled and _is_global_dba_grant(grant):
            saw_global_dba = True
            continue
        parsed_grant = _parse_direct_grant(grant)
        if parsed_grant is None:
            raise RuntimeError("测试数据库账号拥有授权转授权限")
        privileges, target = parsed_grant
        if privileges == frozenset({"USAGE"}) and target == "*.*":
            continue
        if target not in allowed_database_targets:
            raise RuntimeError("测试数据库账号拥有测试库以外的权限")
    if global_dba_enabled and not saw_global_dba:
        raise RuntimeError("显式 DBA 测试模式未命中全局 ALL + GRANT OPTION")


def _is_global_dba_grant(grant: object) -> bool:
    if not isinstance(grant, str):
        return False
    normalized = " ".join(grant.upper().split())
    return (
        normalized.startswith("GRANT ALL PRIVILEGES ON *.* TO ")
        and " WITH GRANT OPTION" in normalized
    )


def _global_dba_test_account_enabled() -> bool:
    return os.environ.get(GLOBAL_DBA_TEST_ACCOUNT_OPT_IN, "").lower() == "true"


def _assert_no_active_database_roles(connection, *, production: bool) -> None:
    """Reject effective privileges that direct SHOW GRANTS cannot expand."""

    try:
        current_role = connection.exec_driver_sql(TEST_CURRENT_ROLE_SQL).scalar_one()
    except Exception as exc:
        message = (
            "无法验证生产数据库账号 active roles" if production else "无法验证测试数据库账号 active roles"
        )
        raise RuntimeError(message) from exc
    if not isinstance(current_role, str) or current_role.upper() != "NONE":
        message = (
            "生产数据库账号启用了 role，无法证明为目标库专用只读账号"
            if production
            else "测试数据库账号启用了 role，无法证明权限仅限测试库"
        )
        raise RuntimeError(message)


def _read_current_user_grants(connection) -> tuple[str, ...]:
    return _read_fixed_grants(
        connection,
        "SHOW GRANTS FOR CURRENT_USER",
        error_message="无法验证当前数据库账号权限",
    )


def _read_fixed_grants(
    connection,
    statement: str,
    *,
    error_message: str,
) -> tuple[str, ...]:
    if statement not in {
        "SHOW GRANTS FOR CURRENT_USER",
        TEST_MARIADB_PUBLIC_GRANTS_SQL,
    }:
        raise RuntimeError("数据库授权检查不允许任意 SQL")
    try:
        result = connection.exec_driver_sql(statement)
        rows = _materialize_bounded_result(result, maximum_rows=128)
    except Exception as exc:
        raise RuntimeError(error_message) from exc
    grants = []
    for row in rows:
        values = tuple(row)
        if len(values) != 1 or not isinstance(values[0], str):
            raise RuntimeError("数据库账号权限返回格式无效")
        grants.append(values[0])
    return tuple(grants)


def _assert_mariadb_public_has_usage_only(
    connection,
    profile: DatabaseObservationProfile,
) -> None:
    if profile is not DatabaseObservationProfile.MARIADB_10_11:
        return
    grants = _read_fixed_grants(
        connection,
        TEST_MARIADB_PUBLIC_GRANTS_SQL,
        error_message="无法验证 MariaDB PUBLIC role 权限",
    )
    # MariaDB returns only explicit ``GRANT ... TO PUBLIC`` rows here.  An
    # empty successful result therefore means the implicit role contributes
    # no privilege; query failure is already rejected by _read_fixed_grants.
    for grant in grants:
        parsed_grant = _parse_direct_grant(grant)
        if parsed_grant != (frozenset({"USAGE"}), "*.*"):
            raise RuntimeError("MariaDB PUBLIC role 拥有数据或管理权限")


def _parse_direct_grant(
    grant: str,
) -> tuple[frozenset[str], str] | None:
    normalized = grant.replace("\\_", "_").replace("\\%", "%")
    upper = normalized.upper()
    if "WITH GRANT OPTION" in upper or not upper.startswith("GRANT "):
        return None
    on_index = upper.find(" ON ", len("GRANT "))
    to_index = upper.find(" TO ", on_index + len(" ON "))
    if on_index < 0 or to_index < 0:
        return None
    privilege_text = normalized[len("GRANT ") : on_index]
    target = normalized[on_index + len(" ON ") : to_index].strip()
    privileges = frozenset(
        privilege.strip().upper()
        for privilege in privilege_text.split(",")
        if privilege.strip()
    )
    if not privileges or not target:
        return None
    return privileges, target


def preflight_test_database_write(
    url,
    connector: Callable[[object], object],
    *,
    disposition: str | DatabaseWriteDisposition | None = None,
    expected_preflight_digest: str | None = None,
) -> DatabaseSchemaPreflight:
    """Observe and authorize one class of real-MySQL test schema write.

    The URL is checked before ``connector`` can open a connection.  The
    selected schema and current account grants are then checked before the
    fixed read-only inventory queries run.  This helper never performs DDL or
    accepts caller-provided SQL.
    """

    if not callable(connector):
        raise TypeError("connector 必须可调用")
    parsed = assert_test_database_url(url)
    selected_disposition = _database_write_disposition(disposition)
    _validate_expected_preflight_digest(
        selected_disposition,
        expected_preflight_digest,
    )

    connection = connector(parsed)
    try:
        assert_current_user_has_test_only_grants(
            connection,
            parsed.database,
        )
        preflight = _observe_test_database_schema(
            connection,
            parsed.database,
            selected_disposition,
        )

        if (
            expected_preflight_digest is not None
            and preflight.preflight_digest != expected_preflight_digest
        ):
            raise DatabaseWriteRefused(
                "测试数据库 actual schema 与钉住的 preflight digest 不一致",
                preflight,
            )
        if selected_disposition is DatabaseWriteDisposition.FAIL_CLOSED:
            raise DatabaseWriteRefused(
                "测试数据库写入 disposition=fail_closed",
                preflight,
            )

        if selected_disposition is DatabaseWriteDisposition.METADATA_REBUILD:
            _LOGGER.warning(
                "test_database_preflight disposition=%s schema=%s "
                "digest=%s drifted=%s",
                selected_disposition.value,
                preflight.database_name,
                preflight.preflight_digest,
                preflight.is_drifted,
            )
        else:
            _LOGGER.info(
                "test_database_preflight disposition=%s schema=%s "
                "digest=%s drifted=%s",
                selected_disposition.value,
                preflight.database_name,
                preflight.preflight_digest,
                preflight.is_drifted,
            )
        return preflight
    finally:
        connection.close()


def observe_test_database_schema(
    url,
    connector: Callable[[object], object],
) -> DatabaseSchemaPreflight:
    """Return a read-only actual-schema identity before a guarded migration.

    This is the observation half of the ``migrate`` disposition.  It never
    authorizes a write: callers must pin the returned digest and enter
    :func:`guarded_mysql_test_schema_migration` before applying DDL or DML.
    Keeping observation and authorization on the shared guard avoids using
    ``metadata_rebuild`` merely to obtain a digest for an in-place migration.
    """

    if not callable(connector):
        raise TypeError("connector 必须可调用")
    parsed = assert_test_database_url(url)
    connection = connector(parsed)
    try:
        assert_current_user_has_test_only_grants(
            connection,
            parsed.database,
        )
        return _observe_test_database_schema(
            connection,
            parsed.database,
            DatabaseWriteDisposition.FAIL_CLOSED,
        )
    finally:
        connection.close()


def _database_write_disposition(
    disposition: str | DatabaseWriteDisposition | None,
) -> DatabaseWriteDisposition:
    if disposition is None:
        return DatabaseWriteDisposition.FAIL_CLOSED
    try:
        return DatabaseWriteDisposition(disposition)
    except (TypeError, ValueError):
        raise RuntimeError(
            "测试数据库 disposition 必须是 " "fail_closed、metadata_rebuild 或 migrate"
        ) from None


def _validate_expected_preflight_digest(
    disposition: DatabaseWriteDisposition,
    expected_preflight_digest: str | None,
) -> None:
    if expected_preflight_digest is not None and (
        not isinstance(expected_preflight_digest, str)
        or _SHA256_HEX.fullmatch(expected_preflight_digest) is None
    ):
        raise RuntimeError("expected_preflight_digest 必须是小写 SHA-256")
    if (
        disposition is DatabaseWriteDisposition.MIGRATE
        and expected_preflight_digest is None
    ):
        raise RuntimeError("migrate disposition 必须钉住 actual schema preflight digest")


def _observe_test_database_schema(
    connection,
    database_name: str,
    disposition: DatabaseWriteDisposition,
) -> DatabaseSchemaPreflight:
    (
        database_profile,
        database_version,
        database_version_comment,
    ) = _detect_database_observation_profile(connection)
    tables = _read_fixed_schema_rows(connection, TEST_SCHEMA_INVENTORY_SQL)
    columns = _read_fixed_schema_rows(connection, TEST_SCHEMA_COLUMN_INVENTORY_SQL)
    indexes = _read_fixed_schema_rows(connection, TEST_SCHEMA_INDEX_INVENTORY_SQL)
    constraints = _read_fixed_schema_rows(
        connection, TEST_SCHEMA_CONSTRAINT_INVENTORY_SQL
    )
    foreign_keys = _read_fixed_schema_rows(
        connection, TEST_SCHEMA_FOREIGN_KEY_INVENTORY_SQL
    )
    checks = _read_fixed_schema_rows(connection, TEST_SCHEMA_CHECK_INVENTORY_SQL)
    partitions = _read_fixed_schema_rows(
        connection, TEST_SCHEMA_PARTITION_INVENTORY_SQL
    )
    views = _read_fixed_schema_rows(connection, TEST_SCHEMA_VIEW_INVENTORY_SQL)
    triggers = _read_fixed_schema_rows(connection, TEST_SCHEMA_TRIGGER_INVENTORY_SQL)
    routines = _read_fixed_schema_rows(connection, TEST_SCHEMA_ROUTINE_INVENTORY_SQL)
    parameters = _read_fixed_schema_rows(
        connection, TEST_SCHEMA_PARAMETER_INVENTORY_SQL
    )
    events = _read_fixed_schema_rows(connection, TEST_SCHEMA_EVENT_INVENTORY_SQL)

    table_names = [row[0] for row in tables]
    if any(not isinstance(name, str) or not name for name in table_names):
        raise RuntimeError("actual schema inventory 包含无效表名")
    column_names_by_table: dict[str, set[object]] = {}
    for row in columns:
        table_name, column_name = row[:2]
        if not isinstance(table_name, str) or not isinstance(column_name, str):
            raise RuntimeError("actual schema inventory 包含无效列名")
        column_names_by_table.setdefault(table_name, set()).add(column_name)

    drift_reasons: list[str] = []
    inventory_names_unique = len(set(table_names)) == len(table_names)
    if not inventory_names_unique:
        drift_reasons.append("duplicate_table_inventory")
    unknown_column_tables = sorted(set(column_names_by_table) - set(table_names))
    if unknown_column_tables:
        drift_reasons.append("columns_without_table_inventory")

    alembic_versions: tuple[object, ...] = ()
    identity_generations: tuple[tuple[object, ...], ...] = ()
    if tables:
        alembic_tables = [row for row in tables if row[0] == "alembic_version"]
        identity_tables = [row for row in tables if row[0] == "database_identity"]
        if not alembic_tables:
            drift_reasons.append("missing_alembic_generation")
        elif (
            len(alembic_tables) != 1
            or alembic_tables[0][1] != "BASE TABLE"
            or str(alembic_tables[0][2]).upper() != "INNODB"
        ):
            drift_reasons.append("invalid_alembic_generation_table_inventory")
        if not identity_tables:
            drift_reasons.append("missing_identity_generation")
        elif (
            len(identity_tables) != 1
            or identity_tables[0][1] != "BASE TABLE"
            or str(identity_tables[0][2]).upper() != "INNODB"
        ):
            drift_reasons.append("invalid_identity_generation_table_inventory")

        generation_tables_are_safe = (
            inventory_names_unique
            and len(alembic_tables) == 1
            and alembic_tables[0][1] == "BASE TABLE"
            and str(alembic_tables[0][2]).upper() == "INNODB"
            and len(identity_tables) == 1
            and identity_tables[0][1] == "BASE TABLE"
            and str(identity_tables[0][2]).upper() == "INNODB"
        )
        if generation_tables_are_safe:
            if "version_num" not in column_names_by_table.get("alembic_version", set()):
                drift_reasons.append("invalid_alembic_generation_inventory")
            else:
                alembic_rows = _read_fixed_schema_rows(
                    connection,
                    TEST_ALEMBIC_GENERATION_SQL,
                )
                alembic_versions = tuple(row[0] for row in alembic_rows)
                if not alembic_versions or any(
                    not isinstance(version, str) or not version
                    for version in alembic_versions
                ):
                    drift_reasons.append("invalid_alembic_generation")

            identity_columns = column_names_by_table.get("database_identity", set())
            if not {"singleton_key", "schema_generation"} <= identity_columns:
                drift_reasons.append("invalid_identity_generation_inventory")
            else:
                identity_generations = _read_fixed_schema_rows(
                    connection,
                    TEST_IDENTITY_GENERATION_SQL,
                )
                if not _valid_identity_generation(identity_generations):
                    drift_reasons.append("invalid_identity_generation")

    digest_payload = {
        "alembic_versions": alembic_versions,
        "check_inventory": checks,
        "column_inventory": columns,
        "constraint_inventory": constraints,
        "database_name": database_name,
        "database_profile": database_profile.value,
        "database_version": database_version,
        "database_version_comment": database_version_comment,
        "event_inventory": events,
        "foreign_key_inventory": foreign_keys,
        "identity_generations": identity_generations,
        "index_inventory": indexes,
        "parameter_inventory": parameters,
        "partition_inventory": partitions,
        "routine_inventory": routines,
        "table_inventory": tables,
        "trigger_inventory": triggers,
        "view_inventory": views,
    }
    digest = hashlib.sha256(
        json.dumps(
            digest_payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return DatabaseSchemaPreflight(
        database_name=database_name,
        database_profile=database_profile,
        database_version=database_version,
        database_version_comment=database_version_comment,
        disposition=disposition,
        table_inventory=tables,
        column_inventory=columns,
        index_inventory=indexes,
        constraint_inventory=constraints,
        foreign_key_inventory=foreign_keys,
        check_inventory=checks,
        partition_inventory=partitions,
        view_inventory=views,
        trigger_inventory=triggers,
        routine_inventory=routines,
        parameter_inventory=parameters,
        event_inventory=events,
        alembic_versions=alembic_versions,
        identity_generations=identity_generations,
        drift_reasons=tuple(drift_reasons),
        preflight_digest=digest,
    )


def _detect_database_observation_profile(
    connection,
) -> tuple[DatabaseObservationProfile, str, str]:
    try:
        result = connection.exec_driver_sql(TEST_DATABASE_PROFILE_SQL)
        rows = _materialize_bounded_result(result, maximum_rows=1)
    except Exception as exc:
        raise RuntimeError("无法判定数据库 observation profile") from exc
    if len(rows) != 1:
        raise RuntimeError("数据库 observation profile 返回行数无效")
    values = tuple(rows[0])
    if (
        len(values) != 2
        or not isinstance(values[0], str)
        or not isinstance(values[1], str)
    ):
        raise RuntimeError("数据库 observation profile 返回格式无效")
    version, comment = values
    version_lower = version.lower()
    comment_lower = comment.lower()
    maria_in_version = "mariadb" in version_lower
    maria_in_comment = "mariadb" in comment_lower
    alternate_vendor_markers = ("percona", "aurora", "tidb")
    if any(
        marker in version_lower or marker in comment_lower
        for marker in alternate_vendor_markers
    ):
        raise RuntimeError("替代数据库 vendor 不受 observation profile 支持")
    if maria_in_version:
        if "mysql" in comment_lower and not maria_in_comment:
            raise RuntimeError("数据库版本标识互相矛盾")
        if re.match(r"^10\.11\.\d+(?:[-+].*)?$", version, re.I) is None:
            raise RuntimeError("不支持的 MariaDB observation profile")
        return DatabaseObservationProfile.MARIADB_10_11, version, comment
    if maria_in_comment:
        raise RuntimeError("数据库版本标识互相矛盾")
    allowed_mysql_comment_prefixes = (
        "mysql community server",
        "mysql enterprise",
        "ubuntu",
        "debian",
        "source distribution",
    )
    if not any(
        comment_lower == prefix
        or comment_lower.startswith(prefix + " ")
        or comment_lower.startswith(prefix + "-")
        for prefix in allowed_mysql_comment_prefixes
    ):
        raise RuntimeError("未知数据库 vendor，拒绝 observation")
    mysql_match = re.match(r"^8\.0\.(\d+)(?:[-+].*)?$", version, re.I)
    if mysql_match is None or int(mysql_match.group(1)) < 30:
        raise RuntimeError("不支持的 MySQL observation profile")
    return DatabaseObservationProfile.MYSQL_8, version, comment


def _read_fixed_schema_rows(
    connection,
    statement: str,
) -> tuple[tuple[object, ...], ...]:
    statement_spec = _FIXED_TEST_SCHEMA_READ_STATEMENTS.get(statement)
    if statement_spec is None:
        raise RuntimeError("测试数据库 preflight 不允许任意 SQL")
    expected_width, maximum_rows = statement_spec
    try:
        result = connection.exec_driver_sql(statement)
        rows = _materialize_bounded_result(
            result,
            maximum_rows=maximum_rows,
        )
    except Exception as exc:
        raise RuntimeError("无法只读观察测试数据库 actual schema") from exc

    normalized_rows = []
    for row in rows:
        try:
            values = tuple(row)
        except TypeError:
            raise RuntimeError("actual schema inventory 返回了无效行") from None
        if len(values) != expected_width:
            raise RuntimeError("actual schema inventory 返回了无效列数")
        normalized_rows.append(
            tuple(_canonical_schema_value(value) for value in values)
        )
    return tuple(normalized_rows)


def _materialize_bounded_result(result, *, maximum_rows: int):
    try:
        fetchmany = getattr(result, "fetchmany", None)
        if callable(fetchmany):
            rows = list(fetchmany(maximum_rows + 1))
        else:
            rows = list(result.all())
        if len(rows) > maximum_rows:
            raise RuntimeError("数据库只读观察结果超过固定上限")
        return rows
    finally:
        close = getattr(result, "close", None)
        if callable(close):
            close()


def _canonical_schema_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, Decimal):
        return {"decimal": format(value, "f")}
    if isinstance(value, (date, datetime, time)):
        return {"temporal": value.isoformat()}
    raise RuntimeError("actual schema inventory 包含不支持的数据类型")


def _valid_identity_generation(
    rows: tuple[tuple[object, ...], ...],
) -> bool:
    if len(rows) != 1:
        return False
    singleton_key, generation = rows[0]
    return (
        singleton_key == 1
        and not isinstance(generation, bool)
        and isinstance(generation, int)
        and generation >= 1
    )


def assert_production_read_database_url(url: str):
    """Validate an explicit production URL used only by read-only probes."""

    if os.environ.get("ALLOW_PRODUCTION_READ_ONLY", "").lower() != "true":
        raise RuntimeError("必须显式设置 ALLOW_PRODUCTION_READ_ONLY=true")
    parsed = make_url(url)
    if parsed.get_backend_name() != "mysql" or not parsed.database:
        raise RuntimeError("生产只读连接必须指向明确的 MySQL 数据库")
    if parsed.database == WRITABLE_TEST_DATABASE_NAME:
        raise RuntimeError("测试库不能伪装成生产只读库")
    _assert_safe_mysql_url_query(parsed)
    return parsed


def assert_current_user_has_production_read_only_grants(connection, database_name: str):
    """Reject a production probe account with any non-read database grant."""

    selected_database = connection.exec_driver_sql("SELECT DATABASE()").scalar_one()
    if selected_database != database_name:
        raise RuntimeError("生产只读连接的实际数据库与目标不一致")
    _assert_no_active_database_roles(connection, production=True)
    profile, _version, _comment = _detect_database_observation_profile(connection)
    _assert_mariadb_public_has_usage_only(connection, profile)
    grants = _read_current_user_grants(connection)
    if not grants:
        raise RuntimeError("无法验证生产只读账号权限")
    database_targets = {
        f"`{database_name}`.*",
        f"{database_name}.*",
    }
    saw_database_read = False
    for grant in grants:
        parsed_grant = _parse_direct_grant(grant)
        if parsed_grant is None:
            raise RuntimeError("生产数据库账号不是目标库专用只读账号")
        privileges, target = parsed_grant
        if privileges == frozenset({"USAGE"}) and target == "*.*":
            continue
        if target not in database_targets or not privileges <= _READ_ONLY_PRIVILEGES:
            raise RuntimeError("生产数据库账号不是目标库专用只读账号")
        saw_database_read = saw_database_read or "SELECT" in privileges
    if not saw_database_read:
        raise RuntimeError("生产数据库账号缺少目标库 SELECT 权限")


class ProductionReadOnlyProbe:
    """One-shot facade exposing only a fixed, versioned observation."""

    __slots__ = ("__connection", "__database_name", "__closed")

    def __init__(self, connection, database_name: str) -> None:
        assert_current_user_has_production_read_only_grants(
            connection,
            database_name,
        )
        self.__connection = connection
        self.__database_name = database_name
        self.__closed = False

    def observe(
        self,
        capability: ProductionReadCapability | str,
    ) -> ProductionSchemaObservation:
        if self.__closed:
            raise RuntimeError("生产只读连接已经关闭")
        try:
            try:
                selected_capability = ProductionReadCapability(capability)
            except (TypeError, ValueError):
                raise RuntimeError("生产只读 probe 不接受调用方 SQL") from None
            if selected_capability is not (
                ProductionReadCapability.SCHEMA_METADATA_AND_GENERATIONS_V1
            ):
                raise RuntimeError("生产只读 capability 不受支持")
            schema = _observe_test_database_schema(
                self.__connection,
                self.__database_name,
                DatabaseWriteDisposition.FAIL_CLOSED,
            )
            return ProductionSchemaObservation(
                capability=selected_capability,
                schema=schema,
            )
        finally:
            self.close()

    def close(self) -> None:
        if not self.__closed:
            self.__closed = True
            try:
                rollback = getattr(self.__connection, "rollback", None)
                if callable(rollback):
                    rollback()
            finally:
                self.__connection.close()

    def __enter__(self):
        if self.__closed:
            raise RuntimeError("生产只读连接已经关闭")
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def __repr__(self) -> str:
        return "ProductionReadOnlyProbe(connection='<redacted>')"


def open_production_read_only_probe(
    url: str,
    connector: Callable[[object], object],
) -> ProductionReadOnlyProbe:
    """Validate the URL, then expose only one guarded observation.

    ``connector`` is a trusted connect-only test seam.  It MUST only open and
    return the connection represented by ``url``; it MUST NOT execute SQL,
    install connection hooks, switch schemas, or mutate session state.
    """

    if not callable(connector):
        raise TypeError("connector 必须可调用")
    parsed = assert_production_read_database_url(url)
    connection = connector(parsed)
    try:
        return ProductionReadOnlyProbe(connection, parsed.database)
    except Exception:
        try:
            rollback = getattr(connection, "rollback", None)
            if callable(rollback):
                rollback()
        finally:
            try:
                connection.close()
            finally:
                raise


@contextmanager
def guarded_mysql_test_metadata(
    engine,
    metadata,
    *,
    disposition: str
    | DatabaseWriteDisposition = (DatabaseWriteDisposition.METADATA_REBUILD),
):
    """Own one locked MySQL metadata lifecycle for an isolated test schema.

    MySQL DDL implicitly commits.  This helper makes no transaction-atomicity
    claim: it holds one connection-scoped advisory lock across setup, the test,
    and teardown, and re-observes the fixed schema digest immediately before
    each metadata DDL operation.
    """

    parsed = assert_test_database_url(engine.url)
    dialect_name = getattr(getattr(engine, "dialect", None), "name", None)
    if dialect_name != "mysql":
        raise RuntimeError("真实测试数据库 guard 只支持 MySQL")
    selected_disposition = _database_write_disposition(disposition)
    if selected_disposition is not DatabaseWriteDisposition.METADATA_REBUILD:
        raise RuntimeError("metadata DDL guard 只允许 metadata_rebuild")
    if not callable(getattr(metadata, "create_all", None)) or not callable(
        getattr(metadata, "drop_all", None)
    ):
        raise TypeError("metadata 必须提供 create_all/drop_all")

    statement_guard_installed = False
    if _global_dba_test_account_enabled():
        if not isinstance(engine, Engine):
            raise TypeError("全局 DBA 测试模式必须使用真实 SQLAlchemy Engine")
        event.listen(engine, "before_cursor_execute", _guard_test_statement)
        statement_guard_installed = True
    connection = None
    lock_acquired = False
    setup_completed = False
    try:
        connection = engine.connect()
        assert_current_user_has_test_only_grants(connection, parsed.database)
        _acquire_test_schema_advisory_lock(connection)
        lock_acquired = True

        pre_drop_preflight = _observe_and_authorize_test_schema(
            connection,
            parsed.database,
            selected_disposition,
        )
        _revalidate_test_schema_before_ddl(connection, pre_drop_preflight)
        _drop_metadata_tables_for_rebuild(connection, metadata)

        post_drop_preflight = _observe_and_authorize_test_schema(
            connection,
            parsed.database,
            selected_disposition,
        )
        _revalidate_test_schema_before_ddl(connection, post_drop_preflight)
        _assert_metadata_tables_absent(metadata, post_drop_preflight)
        metadata.create_all(bind=connection)

        setup_preflight = _observe_and_authorize_test_schema(
            connection,
            parsed.database,
            selected_disposition,
        )
        _revalidate_test_schema_before_ddl(connection, setup_preflight)
        _assert_metadata_tables_present(metadata, setup_preflight)
        # The preflight reads generation rows from application tables.  MySQL
        # retains their metadata locks until the transaction ends, while the
        # guarded body may intentionally run Alembic through another
        # connection.  Commit only the read transaction; GET_LOCK remains
        # connection-scoped and continues to protect the full lifecycle.
        connection.commit()
        setup_completed = True
        try:
            yield setup_preflight
        finally:
            if setup_completed:
                teardown_preflight = _observe_and_authorize_test_schema(
                    connection,
                    parsed.database,
                    selected_disposition,
                )
                _revalidate_test_schema_before_ddl(
                    connection,
                    teardown_preflight,
                )
                _drop_metadata_tables_for_rebuild(connection, metadata)
                post_teardown = _observe_and_authorize_test_schema(
                    connection,
                    parsed.database,
                    selected_disposition,
                )
                _revalidate_test_schema_before_ddl(connection, post_teardown)
                _assert_metadata_tables_absent(metadata, post_teardown)
    finally:
        try:
            if connection is not None and lock_acquired:
                _release_test_schema_advisory_lock(connection)
        finally:
            try:
                if connection is not None:
                    connection.close()
            finally:
                if statement_guard_installed:
                    event.remove(
                        engine,
                        "before_cursor_execute",
                        _guard_test_statement,
                    )


@contextmanager
def guarded_mysql_test_schema_migration(
    engine,
    *,
    expected_preflight_digest: str,
):
    """Hold the shared schema lock for one digest-pinned in-place migration.

    Unlike the metadata lifecycle helper, this guard never drops or creates
    tables itself.  It re-observes the full schema inventory after acquiring
    the connection-scoped advisory lock, refuses source drift, then yields the
    same selected connection to the caller's migration composition.
    """

    parsed = assert_test_database_url(engine.url)
    dialect_name = getattr(getattr(engine, "dialect", None), "name", None)
    if dialect_name != "mysql":
        raise RuntimeError("真实测试数据库 migration guard 只支持 MySQL")
    _validate_expected_preflight_digest(
        DatabaseWriteDisposition.MIGRATE,
        expected_preflight_digest,
    )

    statement_guard_installed = False
    if _global_dba_test_account_enabled():
        if not isinstance(engine, Engine):
            raise TypeError("全局 DBA 测试模式必须使用真实 SQLAlchemy Engine")
        event.listen(engine, "before_cursor_execute", _guard_test_statement)
        statement_guard_installed = True
    connection = None
    lock_acquired = False
    try:
        connection = engine.connect()
        assert_current_user_has_test_only_grants(
            connection,
            parsed.database,
        )
        _acquire_test_schema_advisory_lock(connection)
        lock_acquired = True
        preflight = _observe_test_database_schema(
            connection,
            parsed.database,
            DatabaseWriteDisposition.MIGRATE,
        )
        if preflight.preflight_digest != expected_preflight_digest:
            raise DatabaseWriteRefused(
                "测试数据库 actual schema 与钉住的 preflight digest 不一致",
                preflight,
            )
        # End metadata read locks without releasing connection-scoped GET_LOCK.
        connection.commit()
        yield connection, preflight
    finally:
        try:
            if connection is not None and lock_acquired:
                _release_test_schema_advisory_lock(connection)
        finally:
            try:
                if connection is not None:
                    connection.close()
            finally:
                if statement_guard_installed:
                    event.remove(
                        engine,
                        "before_cursor_execute",
                        _guard_test_statement,
                    )


@contextmanager
def guarded_mysql_control_database(
    metadata,
    *,
    engine_options: dict[str, object] | None = None,
):
    """Build one guarded ``ControlDatabase`` on the approved test schema.

    SQL-backed unit modules use this helper at module scope, then call
    :func:`clear_guarded_mysql_test_rows` before each case.  Keeping URL
    validation, grant revalidation, advisory locking, metadata lifecycle and
    disposal here prevents every migrated module from growing its own subtly
    different real-database fixture.
    """

    raw_url = os.environ.get("TEST_DATABASE_URL")
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise RuntimeError("缺少 TEST_DATABASE_URL")
    assert_test_database_url(raw_url)
    if engine_options is not None and not isinstance(engine_options, dict):
        raise TypeError("engine_options 必须是 dict")

    # Imported lazily so the low-level URL/grant guards remain usable without
    # importing the application package (for example in their own unit tests).
    from inventory_control import ControlDatabase

    database = ControlDatabase.from_url(
        raw_url,
        engine_options=(
            dict(engine_options)
            if engine_options is not None
            else {
                "pool_pre_ping": True,
                "pool_recycle": 300,
                "connect_args": {
                    "connect_timeout": 5,
                    "read_timeout": 30,
                    "write_timeout": 30,
                },
            }
        ),
    )
    try:
        with guarded_mysql_test_metadata(database.engine, metadata):
            yield database
    finally:
        database.dispose()


@contextmanager
def guarded_mysql_migration_database(metadata):
    """Yield the one approved URL with an empty, locked migration target.

    Revision-level integration tests need to start below the current ORM head,
    so the regular shared-metadata fixture cannot seed their initial state.
    This adapter reuses the same guarded schema lifecycle, removes only the
    caller's known tables plus Alembic's version marker, and never creates a
    database, account, grant, or alternate schema.
    """

    raw_url = os.environ.get("TEST_DATABASE_URL")
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise RuntimeError("缺少 TEST_DATABASE_URL")
    parsed = assert_test_database_url(raw_url)
    engine = create_engine(
        parsed.render_as_string(hide_password=False),
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={
            "connect_timeout": 5,
            "read_timeout": 120,
            "write_timeout": 120,
        },
    )
    try:
        with guarded_mysql_test_metadata(engine, metadata):
            _reset_mysql_migration_target(engine, metadata)
            try:
                yield RedactedTestDatabaseUrl(
                    parsed.render_as_string(hide_password=False)
                )
            finally:
                _reset_mysql_migration_target(engine, metadata)
    finally:
        engine.dispose()


def _reset_mysql_migration_target(engine, metadata) -> None:
    parsed = assert_test_database_url(engine.url)
    with engine.connect() as connection:
        assert_current_user_has_test_only_grants(connection, parsed.database)
        _drop_metadata_tables_for_rebuild(connection, metadata)
        connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        connection.commit()


def reset_guarded_mysql_migration_database(url: str, metadata) -> None:
    """Reset one already locked migration schema between serial test cases."""

    parsed = assert_test_database_url(url)
    engine = create_engine(
        parsed.render_as_string(hide_password=False),
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 5,
            "read_timeout": 120,
            "write_timeout": 120,
        },
    )
    try:
        _reset_mysql_migration_target(engine, metadata)
    finally:
        engine.dispose()


def clear_guarded_mysql_test_rows(engine, metadata) -> None:
    """Clear one guarded module fixture without rebuilding its schema.

    The caller must already own ``guarded_mysql_test_metadata`` for the same
    engine.  Keeping the metadata/advisory-lock lifecycle at module scope and
    deleting rows between cases avoids dozens of redundant MySQL DDL rebuilds
    while every test still uses the single approved schema serially.
    """

    parsed = assert_test_database_url(engine.url)
    dialect_name = getattr(getattr(engine, "dialect", None), "name", None)
    if dialect_name != "mysql":
        raise RuntimeError("真实测试数据库清理只支持 MySQL")
    if not hasattr(metadata, "sorted_tables"):
        raise TypeError("metadata 必须提供 sorted_tables")

    for attempt in range(3):
        try:
            with engine.connect() as connection:
                assert_current_user_has_test_only_grants(
                    connection,
                    parsed.database,
                )
                selected = connection.exec_driver_sql("SELECT DATABASE()").scalar_one()
                if selected != WRITABLE_TEST_DATABASE_NAME:
                    raise RuntimeError("测试连接未选择 inventory_management_test")
                connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
                try:
                    for table in reversed(metadata.sorted_tables):
                        connection.execute(table.delete())
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
                finally:
                    connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")
                    connection.commit()
            return
        except OperationalError as error:
            original = getattr(error, "orig", None)
            arguments = getattr(original, "args", ())
            error_number = arguments[0] if arguments else None
            if error_number not in {1205, 1213} or attempt == 2:
                raise


def _drop_metadata_tables_for_rebuild(connection, metadata) -> None:
    """Idempotently remove only the caller's validated metadata tables.

    MySQL DDL commits implicitly, so a killed test process can leave a
    partially completed ``MetaData.drop_all`` where a ``use_alter`` foreign
    key is already gone but its table remains.  Dropping the exact known table
    inventory with FK checks disabled is restart-safe and avoids replaying a
    separate ``DROP FOREIGN KEY`` against that partial state.
    """

    table_names = tuple(sorted(_metadata_table_names(metadata), reverse=True))
    preparer = connection.dialect.identifier_preparer
    connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
    try:
        for table_name in table_names:
            connection.exec_driver_sql(
                f"DROP TABLE IF EXISTS {preparer.quote(table_name)}"
            )
    finally:
        connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")
        connection.commit()


def _guard_test_statement(
    _connection,
    _cursor,
    statement,
    _parameters,
    _context,
    _executemany,
) -> None:
    """Keep even a global DBA test session inside the selected test schema."""

    if not isinstance(statement, str):
        raise RuntimeError("测试数据库 SQL 类型无效")
    normalized = " ".join(statement.strip().split())
    upper = normalized.upper()
    forbidden = (
        r"^(?:USE)\b",
        r"^(?:CREATE|DROP|ALTER)\s+(?:DATABASE|SCHEMA)\b",
        r"^(?:GRANT|REVOKE)\b",
        r"^(?:CREATE|ALTER|DROP|RENAME)\s+USER\b",
        r"^(?:LOAD\s+DATA|LOAD_FILE\s*\(|INSTALL\s+PLUGIN)\b",
    )
    if any(re.search(pattern, upper) for pattern in forbidden):
        raise RuntimeError("测试数据库拒绝实例级或账号级 SQL")
    if upper.startswith(("SELECT ", "SHOW ", "EXPLAIN ", "DESCRIBE ")):
        return
    schemas = {
        match.group(1) for match in re.finditer(r"`([^`]+)`\s*\.\s*`[^`]+`", statement)
    }
    if any(schema != WRITABLE_TEST_DATABASE_NAME for schema in schemas):
        raise RuntimeError("测试数据库拒绝显式跨 schema 写入")
    if re.search(r"(?<![A-Z0-9_])`?INVENTORY_MANAGEMENT`?\s*\.", upper):
        raise RuntimeError("测试数据库拒绝显式生产 schema 写入")


def _observe_and_authorize_test_schema(
    connection,
    database_name: str,
    disposition: DatabaseWriteDisposition,
) -> DatabaseSchemaPreflight:
    assert_current_user_has_test_only_grants(connection, database_name)
    preflight = _observe_test_database_schema(
        connection,
        database_name,
        disposition,
    )
    if disposition is DatabaseWriteDisposition.FAIL_CLOSED:
        raise DatabaseWriteRefused(
            "测试数据库写入 disposition=fail_closed",
            preflight,
        )
    return preflight


def _revalidate_test_schema_before_ddl(
    connection,
    expected: DatabaseSchemaPreflight,
) -> None:
    assert_current_user_has_test_only_grants(
        connection,
        expected.database_name,
    )
    actual = _observe_test_database_schema(
        connection,
        expected.database_name,
        expected.disposition,
    )
    if actual.identity_generations != expected.identity_generations:
        raise DatabaseWriteRefused(
            "DDL 前 database identity generation 已变化",
            actual,
        )
    if actual.alembic_versions != expected.alembic_versions:
        raise DatabaseWriteRefused(
            "DDL 前 alembic generation 已变化",
            actual,
        )
    if actual.preflight_digest != expected.preflight_digest:
        raise DatabaseWriteRefused(
            "DDL 前 actual schema digest 已变化",
            actual,
        )


def _metadata_table_names(metadata) -> frozenset[str]:
    tables = getattr(metadata, "tables", None)
    if tables is None or not hasattr(tables, "values"):
        raise TypeError("metadata 必须暴露固定 tables inventory")
    names = set()
    for table in tables.values():
        name = getattr(table, "name", None)
        schema = getattr(table, "schema", None)
        if not isinstance(name, str) or not name:
            raise TypeError("metadata tables inventory 包含无效表名")
        if schema not in (None, WRITABLE_TEST_DATABASE_NAME):
            raise RuntimeError("metadata 包含测试库以外的 schema")
        names.add(name)
    return frozenset(names)


def _base_table_names(preflight: DatabaseSchemaPreflight) -> frozenset[str]:
    return frozenset(
        row[0]
        for row in preflight.table_inventory
        if len(row) >= 2 and row[1] == "BASE TABLE"
    )


def _assert_metadata_tables_absent(
    metadata,
    preflight: DatabaseSchemaPreflight,
) -> None:
    remaining = _metadata_table_names(metadata) & _base_table_names(preflight)
    if remaining:
        raise DatabaseWriteRefused(
            "metadata_rebuild drop 后仍存在旧 metadata table",
            preflight,
        )
    if (
        preflight.view_inventory
        or preflight.trigger_inventory
        or preflight.routine_inventory
        or preflight.event_inventory
    ):
        raise DatabaseWriteRefused(
            "metadata_rebuild 后仍存在未知 view/trigger/routine/event",
            preflight,
        )


def _assert_metadata_tables_present(
    metadata,
    preflight: DatabaseSchemaPreflight,
) -> None:
    missing = _metadata_table_names(metadata) - _base_table_names(preflight)
    if missing:
        raise DatabaseWriteRefused(
            "metadata_rebuild create 后缺少 expected metadata table",
            preflight,
        )


def _acquire_test_schema_advisory_lock(connection) -> None:
    result = connection.exec_driver_sql(TEST_SCHEMA_ACQUIRE_LOCK_SQL)
    if result.scalar_one() != 1:
        raise RuntimeError("无法获取 inventory_management_test metadata lock")


def _release_test_schema_advisory_lock(connection) -> None:
    result = connection.exec_driver_sql(TEST_SCHEMA_RELEASE_LOCK_SQL)
    if result.scalar_one() != 1:
        raise RuntimeError("无法释放 inventory_management_test metadata lock")


def _assert_safe_mysql_url_query(parsed) -> None:
    """Reject driver hooks that run or load data before grant checks."""

    if set(parsed.query) - {"charset"}:
        raise RuntimeError("数据库连接包含不允许的连接选项")
    charset = parsed.query.get("charset")
    if charset is not None and (
        not isinstance(charset, str) or charset.lower() != "utf8mb4"
    ):
        raise RuntimeError("数据库连接字符集选项不受支持")


def build_mysql_test_config():
    """从显式 TEST_DATABASE_URL 构建隔离 MySQL 测试配置。"""
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if not raw_url:
        raise RuntimeError("缺少 TEST_DATABASE_URL")
    parsed = assert_test_database_url(raw_url)

    class MySQLTestingConfig(TestingConfig):
        SQLALCHEMY_DATABASE_URI = parsed.render_as_string(hide_password=False)
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "connect_args": {
                "connect_timeout": 5,
                "read_timeout": 30,
                "write_timeout": 30,
            },
        }

    return MySQLTestingConfig
