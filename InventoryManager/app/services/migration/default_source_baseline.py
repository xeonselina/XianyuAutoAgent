"""Read-only, versioned source baseline for default-tenant migration.

The observer accepts one already-authenticated, already-selected SQLAlchemy
connection.  It owns no DSN or credential, requires exact schema-only read
grants, runs a consistent read-only snapshot, and hashes only schema metadata
and per-table row counts.  Customer/provider values never leave the server or
enter migration evidence.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Callable, Final, Mapping, Protocol, runtime_checkable

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from inventory_control.default_migration.phase_executor import (
    DefaultMigrationStepInvocation,
)
from inventory_control.default_migration.historical_boundary import (
    HISTORICAL_BOUNDARY_COUNT_KEYS,
    DefaultHistoricalBoundaryError,
    DefaultHistoricalBoundaryRejected,
    DefaultHistoricalSnapshotBoundaryEvidence,
    DefaultSourceMigrationPreflightEvidence,
    HistoricalSnapshotDisposition,
    historical_boundary_evidence_from_document,
    historical_boundary_evidence_to_document,
    source_migration_preflight_from_document,
    source_migration_preflight_to_document,
)
from inventory_control.default_migration.source_baseline import (
    DEFAULT_SOURCE_BASELINE_FORMAT,
    DefaultSourceBaselineError,
    DefaultSourceBaselineEvidence,
    DefaultSourceBaselineInputError,
    DefaultSourceBaselineRejected,
    source_baseline_evidence_from_document,
    source_baseline_evidence_to_document,
    source_baseline_payload_digest as _digest_document,
)


_SCHEMA = re.compile(r"^[A-Za-z0-9_]{1,64}$", re.ASCII)
_BASELINE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}$", re.ASCII)
_TABLE = re.compile(r"^[A-Za-z0-9_$]{1,64}$", re.ASCII)
_MYSQL = re.compile(r"^8\.0\.(?P<patch>[0-9]+)(?:[-+].*)?$", re.ASCII)
_MARIADB = re.compile(
    r"^10\.11\.(?P<patch>[0-9]+)-MariaDB(?:[-+].*)?$",
    re.ASCII,
)
_MAX_TABLES: Final = 512
_MAX_INVENTORY_ROWS: Final = 100_000

_LEGACY_LIFECYCLE_COUNT_SQL: Final = """
    SELECT COUNT(*)
    FROM `rentals`
    WHERE `status` IN ('shipped', 'returned', 'completed')
       OR `ship_out_time` IS NOT NULL
       OR `ship_in_time` IS NOT NULL
"""
_CURRENT_LIFECYCLE_COUNT_SQL: Final = """
    SELECT COUNT(*)
    FROM `rentals`
    WHERE `status` IN ('shipped', 'returned', 'completed')
       OR `actual_shipped_at` IS NOT NULL
       OR `actual_returned_at` IS NOT NULL
"""
_COMBINED_LIFECYCLE_COUNT_SQL: Final = """
    SELECT COUNT(*)
    FROM `rentals`
    WHERE `status` IN ('shipped', 'returned', 'completed')
       OR `ship_out_time` IS NOT NULL
       OR `ship_in_time` IS NOT NULL
       OR `actual_shipped_at` IS NOT NULL
       OR `actual_returned_at` IS NOT NULL
"""
_TRACKING_COUNT_SQL: Final = """
    SELECT COUNT(*)
    FROM `rentals`
    WHERE `ship_out_tracking_no` IS NOT NULL
       OR `ship_in_tracking_no` IS NOT NULL
"""
_PRINT_AUDIT_COUNT_SQL: Final = """
    SELECT COUNT(*)
    FROM `audit_logs`
    WHERE LOWER(`action`) LIKE '%%print%%'
       OR `action` LIKE '%%打印%%'
"""


@runtime_checkable
class DefaultSourceBaselineConnection(Protocol):
    def execute(self, statement: object) -> object: ...

    def exec_driver_sql(self, statement: str) -> object: ...

    def in_transaction(self) -> bool: ...

    def rollback(self) -> None: ...


_PROFILE_SQL = sa.text(
    """
    SELECT
        DATABASE() AS database_name,
        CURRENT_USER() AS current_account,
        CURRENT_ROLE() AS active_role,
        CAST(@@version AS CHAR) AS server_version,
        CAST(@@version_comment AS CHAR) AS version_comment,
        CAST(@@lower_case_table_names AS CHAR) AS lower_case_table_names,
        CAST(@@character_set_database AS CHAR) AS character_set_database,
        CAST(@@collation_database AS CHAR) AS collation_database
    """
)

_TABLES_SQL = sa.text(
    """
    SELECT
        TABLE_NAME AS table_name,
        TABLE_TYPE AS table_type,
        ENGINE AS engine,
        ROW_FORMAT AS row_format,
        TABLE_COLLATION AS table_collation,
        CREATE_OPTIONS AS create_options
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = DATABASE()
    ORDER BY TABLE_NAME
    """
)

_COLUMNS_SQL = sa.text(
    """
    SELECT
        TABLE_NAME AS table_name,
        CAST(ORDINAL_POSITION AS CHAR) AS ordinal_position,
        COLUMN_NAME AS column_name,
        COLUMN_DEFAULT AS column_default,
        IS_NULLABLE AS is_nullable,
        DATA_TYPE AS data_type,
        COLUMN_TYPE AS column_type,
        CHARACTER_SET_NAME AS character_set_name,
        COLLATION_NAME AS collation_name,
        COLUMN_KEY AS column_key,
        EXTRA AS extra,
        GENERATION_EXPRESSION AS generation_expression
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
    ORDER BY TABLE_NAME, ORDINAL_POSITION
    """
)

_INDEXES_SQL = sa.text(
    """
    SELECT
        TABLE_NAME AS table_name,
        INDEX_NAME AS index_name,
        CAST(NON_UNIQUE AS CHAR) AS non_unique,
        CAST(SEQ_IN_INDEX AS CHAR) AS seq_in_index,
        COLUMN_NAME AS column_name,
        COLLATION AS collation,
        CAST(SUB_PART AS CHAR) AS sub_part,
        NULLABLE AS nullable,
        INDEX_TYPE AS index_type
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
    ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
    """
)

_CONSTRAINTS_SQL = sa.text(
    """
    SELECT
        tc.TABLE_NAME AS table_name,
        tc.CONSTRAINT_NAME AS constraint_name,
        tc.CONSTRAINT_TYPE AS constraint_type,
        kcu.COLUMN_NAME AS column_name,
        CAST(kcu.ORDINAL_POSITION AS CHAR) AS ordinal_position,
        kcu.REFERENCED_TABLE_NAME AS referenced_table_name,
        kcu.REFERENCED_COLUMN_NAME AS referenced_column_name
    FROM information_schema.TABLE_CONSTRAINTS AS tc
    LEFT JOIN information_schema.KEY_COLUMN_USAGE AS kcu
      ON kcu.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA
     AND kcu.TABLE_NAME = tc.TABLE_NAME
     AND kcu.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
    WHERE tc.CONSTRAINT_SCHEMA = DATABASE()
    ORDER BY
        tc.TABLE_NAME,
        tc.CONSTRAINT_NAME,
        kcu.ORDINAL_POSITION
    """
)

_OBJECTS_SQL = sa.text(
    """
    SELECT 'VIEW' AS object_type, TABLE_NAME AS object_name, NULL AS detail
    FROM information_schema.VIEWS
    WHERE TABLE_SCHEMA = DATABASE()
    UNION ALL
    SELECT 'TRIGGER', TRIGGER_NAME, EVENT_MANIPULATION
    FROM information_schema.TRIGGERS
    WHERE TRIGGER_SCHEMA = DATABASE()
    UNION ALL
    SELECT 'ROUTINE', ROUTINE_NAME, ROUTINE_TYPE
    FROM information_schema.ROUTINES
    WHERE ROUTINE_SCHEMA = DATABASE()
    UNION ALL
    SELECT 'EVENT', EVENT_NAME, STATUS
    FROM information_schema.EVENTS
    WHERE EVENT_SCHEMA = DATABASE()
    ORDER BY object_type, object_name
    """
)


class SqlAlchemyDefaultSourceBaselineObserver:
    """Capture a stable schema/count baseline without any data mutation."""

    __slots__ = ()

    def observe(
        self,
        connection: DefaultSourceBaselineConnection,
        *,
        source_schema_name: str,
        baseline_migration_id: str,
    ) -> DefaultSourceBaselineEvidence:
        evidence, _historical_boundary = self._observe(
            connection,
            source_schema_name=source_schema_name,
            baseline_migration_id=baseline_migration_id,
            include_historical_boundary=False,
        )
        return evidence

    def observe_with_historical_boundary(
        self,
        connection: DefaultSourceBaselineConnection,
        *,
        source_schema_name: str,
        baseline_migration_id: str,
    ) -> tuple[
        DefaultSourceBaselineEvidence,
        DefaultHistoricalSnapshotBoundaryEvidence,
    ]:
        evidence, historical_boundary = self._observe(
            connection,
            source_schema_name=source_schema_name,
            baseline_migration_id=baseline_migration_id,
            include_historical_boundary=True,
        )
        if historical_boundary is None:
            raise DefaultHistoricalBoundaryRejected()
        return evidence, historical_boundary

    def _observe(
        self,
        connection: DefaultSourceBaselineConnection,
        *,
        source_schema_name: str,
        baseline_migration_id: str,
        include_historical_boundary: bool,
    ) -> tuple[
        DefaultSourceBaselineEvidence,
        DefaultHistoricalSnapshotBoundaryEvidence | None,
    ]:
        if (
            not isinstance(connection, DefaultSourceBaselineConnection)
            or connection.in_transaction()
            or not isinstance(source_schema_name, str)
            or _SCHEMA.fullmatch(source_schema_name) is None
            or not isinstance(baseline_migration_id, str)
            or _BASELINE.fullmatch(baseline_migration_id) is None
        ):
            raise DefaultSourceBaselineInputError()
        try:
            profile = _one_mapping(connection.execute(_PROFILE_SQL))
            database_profile = _database_profile(profile)
            if (
                profile.get("database_name") != source_schema_name
                or (
                    profile.get("active_role") is not None
                    and str(profile.get("active_role")).upper() != "NONE"
                )
            ):
                raise DefaultSourceBaselineRejected()
            connection.rollback()
            _require_read_only_grants(
                connection,
                schema_name=source_schema_name,
                database_profile=database_profile,
            )
            connection.rollback()

            connection.exec_driver_sql(
                "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY"
            )
            first_inventory = _schema_inventory(connection, profile)
            table_names = tuple(
                row[0]
                for row in first_inventory["tables"]
                if len(row) >= 2 and row[1] == "BASE TABLE"
            )
            if (
                len(table_names) > _MAX_TABLES
                or len(table_names) != len(set(table_names))
                or any(_TABLE.fullmatch(name) is None for name in table_names)
            ):
                raise DefaultSourceBaselineRejected()
            row_counts = tuple(
                (table_name, _table_count(connection, table_name))
                for table_name in table_names
            )
            historical_counts = (
                _collect_historical_boundary_counts(
                    connection,
                    inventory=first_inventory,
                    table_names=table_names,
                )
                if include_historical_boundary
                else None
            )
            second_profile = _one_mapping(connection.execute(_PROFILE_SQL))
            second_inventory = _schema_inventory(connection, second_profile)
            if profile != second_profile or first_inventory != second_inventory:
                raise DefaultSourceBaselineRejected()

            schema_digest = _digest_document(first_inventory)
            row_count_digest = _digest_document(
                {"row_counts": row_counts}
            )
            snapshot_digest = _digest_document(
                {
                    "baseline_migration_id": baseline_migration_id,
                    "database_profile": database_profile,
                    "format_version": DEFAULT_SOURCE_BASELINE_FORMAT,
                    "row_count_digest": row_count_digest.hex(),
                    "schema_inventory_digest": schema_digest.hex(),
                    "server_version": profile["server_version"],
                    "source_schema_name": source_schema_name,
                }
            )
            evidence = DefaultSourceBaselineEvidence(
                source_schema_name=source_schema_name,
                baseline_migration_id=baseline_migration_id,
                database_profile=database_profile,
                server_version=profile["server_version"],
                table_count=len(table_names),
                total_rows=sum(count for _name, count in row_counts),
                schema_inventory_digest=schema_digest,
                row_count_digest=row_count_digest,
                source_snapshot_digest=snapshot_digest,
            )
            historical_boundary = (
                None
                if historical_counts is None
                else DefaultHistoricalSnapshotBoundaryEvidence(
                    source_schema_name=source_schema_name,
                    baseline_migration_id=baseline_migration_id,
                    source_snapshot_digest=snapshot_digest,
                    counts=historical_counts,
                    disposition=(
                        HistoricalSnapshotDisposition.EMPTY
                        if all(
                            count == 0
                            for _key, count in historical_counts
                        )
                        else HistoricalSnapshotDisposition.REQUIRES_APPROVED_NONEMPTY_ADAPTER
                    ),
                )
            )
            if historical_boundary is not None:
                historical_boundary.require_source_baseline(evidence)
            return evidence, historical_boundary
        except (DefaultSourceBaselineError, DefaultHistoricalBoundaryError):
            raise
        except (SQLAlchemyError, KeyError, TypeError, ValueError):
            raise DefaultSourceBaselineRejected() from None
        finally:
            if connection.in_transaction():
                connection.rollback()


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class BoundDefaultSourceBaselineVerifier:
    """Bind the read-only observer to an explicit source connection factory."""

    connection_factory: Callable[[], DefaultSourceBaselineConnection]
    observer: SqlAlchemyDefaultSourceBaselineObserver = (
        SqlAlchemyDefaultSourceBaselineObserver()
    )

    def __post_init__(self) -> None:
        if (
            not callable(self.connection_factory)
            or not isinstance(
                self.observer,
                SqlAlchemyDefaultSourceBaselineObserver,
            )
        ):
            raise DefaultSourceBaselineInputError()

    def verify(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultSourceBaselineEvidence:
        if not isinstance(invocation, DefaultMigrationStepInvocation):
            raise DefaultSourceBaselineInputError()
        manifest = invocation.phase_invocation.manifest
        connection = self.connection_factory()
        if not isinstance(connection, DefaultSourceBaselineConnection):
            raise DefaultSourceBaselineInputError()
        try:
            evidence = self.observer.observe(
                connection,
                source_schema_name=manifest.source_schema_name,
                baseline_migration_id=manifest.baseline_migration_id,
            )
            evidence.require_manifest(manifest)
            return evidence
        finally:
            close = getattr(connection, "close", None)
            if callable(close):
                close()

    def __repr__(self) -> str:
        return "BoundDefaultSourceBaselineVerifier(connection='<bound>')"


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class BoundDefaultSourceMigrationPreflightVerifier:
    """Re-observe source structure and historical disposition atomically."""

    connection_factory: Callable[[], DefaultSourceBaselineConnection]
    observer: SqlAlchemyDefaultSourceBaselineObserver = (
        SqlAlchemyDefaultSourceBaselineObserver()
    )

    def __post_init__(self) -> None:
        if (
            not callable(self.connection_factory)
            or not isinstance(
                self.observer,
                SqlAlchemyDefaultSourceBaselineObserver,
            )
        ):
            raise DefaultSourceBaselineInputError()

    def verify(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultSourceMigrationPreflightEvidence:
        if not isinstance(invocation, DefaultMigrationStepInvocation):
            raise DefaultSourceBaselineInputError()
        manifest = invocation.phase_invocation.manifest
        connection = self.connection_factory()
        if not isinstance(connection, DefaultSourceBaselineConnection):
            raise DefaultSourceBaselineInputError()
        try:
            source_baseline, historical_boundary = (
                self.observer.observe_with_historical_boundary(
                    connection,
                    source_schema_name=manifest.source_schema_name,
                    baseline_migration_id=manifest.baseline_migration_id,
                )
            )
            evidence = DefaultSourceMigrationPreflightEvidence(
                source_baseline=source_baseline,
                historical_boundary=historical_boundary,
            )
            evidence.require_manifest(manifest)
            return evidence
        finally:
            close = getattr(connection, "close", None)
            if callable(close):
                close()

    def __repr__(self) -> str:
        return (
            "BoundDefaultSourceMigrationPreflightVerifier("
            "connection='<bound>')"
        )


def _database_profile(profile: Mapping[str, object]) -> str:
    version = profile.get("server_version")
    comment = profile.get("version_comment")
    if not isinstance(version, str) or not isinstance(comment, str):
        raise DefaultSourceBaselineRejected()
    mariadb = _MARIADB.fullmatch(version)
    # Some MariaDB packages expose the generic version comment
    # ``Source distribution``; the version token itself is unambiguous.
    if mariadb is not None:
        return "mariadb-10.11"
    mysql = _MYSQL.fullmatch(version)
    if (
        mysql is not None
        and int(mysql.group("patch")) >= 30
        and "mysql" in comment.lower()
    ):
        return "mysql-8.0.30+"
    raise DefaultSourceBaselineRejected()


def _collect_historical_boundary_counts(
    connection: DefaultSourceBaselineConnection,
    *,
    inventory: Mapping[str, tuple[tuple[object, ...], ...]],
    table_names: tuple[str, ...],
) -> tuple[tuple[str, int], ...]:
    try:
        columns = {
            (row[0], row[2])
            for row in inventory["columns"]
            if len(row) >= 3
            and isinstance(row[0], str)
            and isinstance(row[2], str)
        }
    except (KeyError, TypeError, IndexError):
        raise DefaultHistoricalBoundaryRejected() from None
    required_columns = {
        ("rentals", "status"),
        ("rentals", "ship_out_tracking_no"),
        ("rentals", "ship_in_tracking_no"),
        ("audit_logs", "action"),
    }
    if (
        not {"rentals", "audit_logs"}.issubset(table_names)
        or not required_columns.issubset(columns)
    ):
        raise DefaultHistoricalBoundaryRejected()
    legacy_lifecycle = {
        ("rentals", "ship_out_time"),
        ("rentals", "ship_in_time"),
    }
    current_lifecycle = {
        ("rentals", "actual_shipped_at"),
        ("rentals", "actual_returned_at"),
    }
    if legacy_lifecycle.issubset(columns) and current_lifecycle.issubset(
        columns
    ):
        lifecycle_sql = _COMBINED_LIFECYCLE_COUNT_SQL
    elif legacy_lifecycle.issubset(columns):
        lifecycle_sql = _LEGACY_LIFECYCLE_COUNT_SQL
    elif current_lifecycle.issubset(columns):
        lifecycle_sql = _CURRENT_LIFECYCLE_COUNT_SQL
    else:
        raise DefaultHistoricalBoundaryRejected()

    statements = {
        "legacy_historical_rentals": lifecycle_sql,
        "legacy_print_audits": _PRINT_AUDIT_COUNT_SQL,
        "legacy_tracking_rows": _TRACKING_COUNT_SQL,
        "outbound_shipments": (
            "SELECT COUNT(*) FROM `outbound_shipments`"
            if "outbound_shipments" in table_names
            else None
        ),
        "provider_operation_attempts": (
            "SELECT COUNT(*) FROM `provider_operation_attempts`"
            if "provider_operation_attempts" in table_names
            else None
        ),
        "waybill_print_jobs": (
            "SELECT COUNT(*) FROM `waybill_print_jobs`"
            if "waybill_print_jobs" in table_names
            else None
        ),
    }
    if tuple(sorted(statements)) != HISTORICAL_BOUNDARY_COUNT_KEYS:
        raise DefaultHistoricalBoundaryRejected()
    return tuple(
        (key, 0 if statement is None else _scalar_count(connection, statement))
        for key, statement in sorted(statements.items())
    )


def _require_read_only_grants(
    connection: DefaultSourceBaselineConnection,
    *,
    schema_name: str,
    database_profile: str,
) -> None:
    grants = _single_column_rows(
        connection.exec_driver_sql("SHOW GRANTS FOR CURRENT_USER")
    )
    parsed = tuple(_parse_grant(item) for item in grants)
    expected_target = f"`{schema_name}`.*"
    if (
        not parsed
        or any(item is None for item in parsed)
        or not any(
            item == (frozenset({"SELECT", "SHOW VIEW"}), expected_target)
            for item in parsed
        )
        or any(
            item
            not in {
                (frozenset({"USAGE"}), "*.*"),
                (frozenset({"SELECT", "SHOW VIEW"}), expected_target),
            }
            for item in parsed
        )
    ):
        raise DefaultSourceBaselineRejected()
    if database_profile == "mariadb-10.11":
        public = _single_column_rows(
            connection.exec_driver_sql("SHOW GRANTS FOR PUBLIC")
        )
        if any(
            _parse_grant(item) != (frozenset({"USAGE"}), "*.*")
            for item in public
        ):
            raise DefaultSourceBaselineRejected()


def _parse_grant(value: str):
    normalized = value.replace("\\_", "_").replace("\\%", "%")
    upper = normalized.upper()
    if "WITH GRANT OPTION" in upper or not upper.startswith("GRANT "):
        return None
    on_index = upper.find(" ON ", len("GRANT "))
    to_index = upper.find(" TO ", on_index + 4)
    if on_index < 0 or to_index < 0:
        return None
    privileges = frozenset(
        item.strip().upper()
        for item in normalized[len("GRANT ") : on_index].split(",")
        if item.strip()
    )
    target = normalized[on_index + 4 : to_index].strip()
    return (privileges, target) if privileges and target else None


def _schema_inventory(connection, profile):
    sections = {
        "profile": tuple(
            sorted(
                (str(key), _canonical_scalar(value))
                for key, value in profile.items()
                if key not in {"current_account", "active_role"}
            )
        ),
        "tables": _mapping_rows(connection.execute(_TABLES_SQL)),
        "columns": _mapping_rows(connection.execute(_COLUMNS_SQL)),
        "indexes": _mapping_rows(connection.execute(_INDEXES_SQL)),
        "constraints": _mapping_rows(connection.execute(_CONSTRAINTS_SQL)),
        "objects": _mapping_rows(connection.execute(_OBJECTS_SQL)),
    }
    if sum(len(rows) for rows in sections.values()) > _MAX_INVENTORY_ROWS:
        raise DefaultSourceBaselineRejected()
    return sections


def _mapping_rows(result) -> tuple[tuple[object, ...], ...]:
    rows = result.mappings().all()
    return tuple(
        tuple(_canonical_scalar(value) for value in row.values())
        for row in rows
    )


def _one_mapping(result) -> dict[str, object]:
    rows = result.mappings().all()
    if len(rows) != 1:
        raise DefaultSourceBaselineRejected()
    return dict(rows[0])


def _single_column_rows(result) -> tuple[str, ...]:
    rows = result.all()
    values = []
    for row in rows:
        selected = tuple(row)
        if len(selected) != 1 or not isinstance(selected[0], str):
            raise DefaultSourceBaselineRejected()
        values.append(selected[0])
    return tuple(values)


def _table_count(connection, table_name: str) -> int:
    if _TABLE.fullmatch(table_name) is None:
        raise DefaultSourceBaselineRejected()
    value = connection.exec_driver_sql(
        f"SELECT COUNT(*) FROM `{table_name}`"
    ).scalar_one()
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DefaultSourceBaselineRejected()
    return value


def _scalar_count(
    connection: DefaultSourceBaselineConnection,
    statement: str,
) -> int:
    value = connection.exec_driver_sql(statement).scalar_one()
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DefaultHistoricalBoundaryRejected()
    return value


def _canonical_scalar(value: object) -> object:
    if value is None or (
        isinstance(value, (str, int)) and not isinstance(value, bool)
    ):
        return value
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest()}
    return str(value)


__all__ = [
    "DEFAULT_SOURCE_BASELINE_FORMAT",
    "BoundDefaultSourceBaselineVerifier",
    "BoundDefaultSourceMigrationPreflightVerifier",
    "DefaultHistoricalSnapshotBoundaryEvidence",
    "DefaultSourceBaselineConnection",
    "DefaultSourceBaselineError",
    "DefaultSourceBaselineEvidence",
    "DefaultSourceBaselineInputError",
    "DefaultSourceBaselineRejected",
    "DefaultSourceMigrationPreflightEvidence",
    "HistoricalSnapshotDisposition",
    "SqlAlchemyDefaultSourceBaselineObserver",
    "source_baseline_evidence_from_document",
    "source_baseline_evidence_to_document",
    "historical_boundary_evidence_from_document",
    "historical_boundary_evidence_to_document",
    "source_migration_preflight_from_document",
    "source_migration_preflight_to_document",
]
