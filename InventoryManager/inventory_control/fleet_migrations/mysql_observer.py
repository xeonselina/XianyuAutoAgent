"""MySQL 8 observation adapter for an already-bound tenant connection.

The adapter accepts no schema name, DSN, credential, or SQL.  Every query is
module-owned and scopes information-schema reads to ``DATABASE()``.  It is a
read-only companion to :class:`TenantMigrationRunner`: the runner owns the
advisory-lock lifecycle and fence checks, while this adapter turns the actual
current database identity, Alembic revision, and schema inventory into one
trusted :class:`FleetMigrationObservation`.

The inventory digest is an observation, not a desired-manifest digest.  A
well-formed but unexpected table, trigger, view, option, revision, generation,
or definition therefore produces a different observation for the fleet state
machine to hold as drift.  A malformed/missing identity, damaged Alembic
version cardinality, unsupported server profile, incomplete metadata result,
or query failure is rejected with a fixed non-sensitive error.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from itertools import islice
from typing import Final, Protocol, runtime_checkable
from uuid import UUID

import sqlalchemy as sa

from .domain import FleetMigrationObservation, FleetSchemaIdentity
from .runner import (
    TenantMigrationConnection,
    TenantMigrationExecutionContext,
    TenantMigrationObservationError,
    TenantMigrationObservationPhase,
)


MYSQL8_SCHEMA_INVENTORY_FORMAT: Final = (
    "inventory-manager/mysql8-schema-inventory/v3"
)
MYSQL8_SCHEMA_INVENTORY_MINIMUM_PATCH: Final = 30
MAX_SCHEMA_INVENTORY_ROWS_PER_SECTION: Final = 100_000
_INVENTORY_DOMAIN = (
    MYSQL8_SCHEMA_INVENTORY_FORMAT.encode("ascii") + b"\x00"
)
_MYSQL_VERSION = re.compile(
    r"^8\.0\.(?P<patch>[0-9]+)(?:[-+].*)?$",
    re.ASCII,
)
_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$", re.ASCII)
_POSITIVE_DECIMAL = re.compile(r"^[1-9][0-9]*$", re.ASCII)


@runtime_checkable
class MySql8SchemaObservationConnection(Protocol):
    """The extra fixed-query surface required from the runner connection."""

    def execute(self, statement: object) -> object: ...


@dataclass(frozen=True, slots=True)
class _ServerProfile:
    observed_at: datetime
    current_database: str
    lower_case_table_names: int

    @property
    def digest_profile(self) -> dict[str, object]:
        return {
            "family": "mysql",
            "information_schema_profile": "mysql-8.0.30+",
            "lower_case_table_names": self.lower_case_table_names,
            "series": "8.0",
        }


@dataclass(frozen=True, slots=True)
class _InventoryQuery:
    name: str
    statement: object
    fields: tuple[str, ...]
    required_text_fields: tuple[str, ...] = ()


_PROFILE_SQL = sa.text(
    """
    SELECT
        CAST(@@version AS CHAR) AS server_version,
        CAST(@@version_comment AS CHAR) AS version_comment,
        CAST(@@lower_case_table_names AS CHAR) AS lower_case_table_names,
        CAST(@@show_gipk_in_create_table_and_information_schema AS CHAR)
            AS show_generated_invisible_primary_keys,
        UTC_TIMESTAMP(6) AS observed_at,
        DATABASE() AS current_database
    WHERE DATABASE() IS NOT NULL
    """
)

_CORE_BASE_TABLES_SQL = sa.text(
    """
    SELECT
        TABLE_NAME AS table_name,
        TABLE_TYPE AS table_type
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME IN ('alembic_version', 'database_identity')
    ORDER BY TABLE_NAME
    """
)

_IDENTITY_SQL = sa.text(
    """
    SELECT
        CAST(singleton_key AS CHAR) AS singleton_key,
        tenant_id AS tenant_id,
        database_uuid AS database_uuid,
        CAST(schema_generation AS CHAR) AS schema_generation
    FROM database_identity
    WHERE DATABASE() IS NOT NULL
    ORDER BY singleton_key
    LIMIT 2
    """
)

_ALEMBIC_VERSION_SQL = sa.text(
    """
    SELECT version_num AS version_num
    FROM alembic_version
    WHERE DATABASE() IS NOT NULL
    ORDER BY version_num
    LIMIT 2
    """
)

_VISIBILITY_SQL = sa.text(
    """
    SELECT
        'global' AS privilege_scope,
        UPPER(PRIVILEGE_TYPE) AS privilege_type
    FROM information_schema.USER_PRIVILEGES
    WHERE REPLACE(GRANTEE, '''', '') = CURRENT_USER()
      AND DATABASE() IS NOT NULL
    UNION ALL
    SELECT
        'schema' AS privilege_scope,
        UPPER(PRIVILEGE_TYPE) AS privilege_type
    FROM information_schema.SCHEMA_PRIVILEGES
    WHERE REPLACE(GRANTEE, '''', '') = CURRENT_USER()
      AND TABLE_SCHEMA = DATABASE()
    ORDER BY privilege_scope, privilege_type
    """
)

_INVENTORY_QUERIES: Final = (
    _InventoryQuery(
        name="schema",
        statement=sa.text(
            """
            SELECT
                s.DEFAULT_CHARACTER_SET_NAME AS default_character_set_name,
                s.DEFAULT_COLLATION_NAME AS default_collation_name,
                s.SQL_PATH AS sql_path,
                s.DEFAULT_ENCRYPTION AS default_encryption,
                CAST(sx.OPTIONS AS CHAR) AS schema_options
            FROM information_schema.SCHEMATA AS s
            LEFT JOIN information_schema.SCHEMATA_EXTENSIONS AS sx
              ON sx.CATALOG_NAME = s.CATALOG_NAME
             AND sx.SCHEMA_NAME = s.SCHEMA_NAME
            WHERE s.SCHEMA_NAME = DATABASE()
            """
        ),
        fields=(
            "default_character_set_name",
            "default_collation_name",
            "sql_path",
            "default_encryption",
            "schema_options",
        ),
        required_text_fields=(
            "default_character_set_name",
            "default_collation_name",
            "default_encryption",
        ),
    ),
    _InventoryQuery(
        name="tables",
        statement=sa.text(
            """
            SELECT
                t.TABLE_NAME AS table_name,
                t.TABLE_TYPE AS table_type,
                t.ENGINE AS engine,
                t.ROW_FORMAT AS row_format,
                t.TABLE_COLLATION AS table_collation,
                t.CREATE_OPTIONS AS create_options,
                t.TABLE_COMMENT AS table_comment,
                CAST(tx.ENGINE_ATTRIBUTE AS CHAR) AS engine_attribute,
                CAST(tx.SECONDARY_ENGINE_ATTRIBUTE AS CHAR)
                    AS secondary_engine_attribute
            FROM information_schema.TABLES AS t
            LEFT JOIN information_schema.TABLES_EXTENSIONS AS tx
              ON tx.TABLE_CATALOG = t.TABLE_CATALOG
             AND tx.TABLE_SCHEMA = t.TABLE_SCHEMA
             AND tx.TABLE_NAME = t.TABLE_NAME
            WHERE t.TABLE_SCHEMA = DATABASE()
              AND t.TABLE_TYPE = 'BASE TABLE'
            ORDER BY t.TABLE_NAME
            """
        ),
        fields=(
            "table_name",
            "table_type",
            "engine",
            "row_format",
            "table_collation",
            "create_options",
            "table_comment",
            "engine_attribute",
            "secondary_engine_attribute",
        ),
        required_text_fields=("table_name", "table_type", "engine"),
    ),
    _InventoryQuery(
        name="partitions",
        statement=sa.text(
            """
            SELECT
                TABLE_NAME AS table_name,
                CAST(PARTITION_ORDINAL_POSITION AS CHAR)
                    AS partition_ordinal_position,
                PARTITION_NAME AS partition_name,
                PARTITION_METHOD AS partition_method,
                PARTITION_EXPRESSION AS partition_expression,
                PARTITION_DESCRIPTION AS partition_description,
                CAST(SUBPARTITION_ORDINAL_POSITION AS CHAR)
                    AS subpartition_ordinal_position,
                SUBPARTITION_NAME AS subpartition_name,
                SUBPARTITION_METHOD AS subpartition_method,
                SUBPARTITION_EXPRESSION AS subpartition_expression,
                PARTITION_COMMENT AS partition_comment,
                NODEGROUP AS nodegroup,
                TABLESPACE_NAME AS tablespace_name
            FROM information_schema.PARTITIONS
            WHERE TABLE_SCHEMA = DATABASE()
            ORDER BY
                TABLE_NAME,
                PARTITION_ORDINAL_POSITION,
                SUBPARTITION_ORDINAL_POSITION
            """
        ),
        fields=(
            "table_name",
            "partition_ordinal_position",
            "partition_name",
            "partition_method",
            "partition_expression",
            "partition_description",
            "subpartition_ordinal_position",
            "subpartition_name",
            "subpartition_method",
            "subpartition_expression",
            "partition_comment",
            "nodegroup",
            "tablespace_name",
        ),
        required_text_fields=(
            "table_name",
        ),
    ),
    _InventoryQuery(
        name="columns",
        statement=sa.text(
            """
            SELECT
                c.TABLE_NAME AS table_name,
                CAST(c.ORDINAL_POSITION AS CHAR) AS ordinal_position,
                c.COLUMN_NAME AS column_name,
                c.COLUMN_DEFAULT AS column_default,
                c.IS_NULLABLE AS is_nullable,
                c.DATA_TYPE AS data_type,
                c.COLUMN_TYPE AS column_type,
                CAST(c.CHARACTER_MAXIMUM_LENGTH AS CHAR)
                    AS character_maximum_length,
                CAST(c.NUMERIC_PRECISION AS CHAR) AS numeric_precision,
                CAST(c.NUMERIC_SCALE AS CHAR) AS numeric_scale,
                CAST(c.DATETIME_PRECISION AS CHAR) AS datetime_precision,
                c.CHARACTER_SET_NAME AS character_set_name,
                c.COLLATION_NAME AS collation_name,
                c.COLUMN_KEY AS column_key,
                c.EXTRA AS extra,
                c.COLUMN_COMMENT AS column_comment,
                c.GENERATION_EXPRESSION AS generation_expression,
                CAST(c.SRS_ID AS CHAR) AS srs_id,
                CAST(cx.ENGINE_ATTRIBUTE AS CHAR) AS engine_attribute,
                CAST(cx.SECONDARY_ENGINE_ATTRIBUTE AS CHAR)
                    AS secondary_engine_attribute
            FROM information_schema.COLUMNS AS c
            LEFT JOIN information_schema.COLUMNS_EXTENSIONS AS cx
              ON cx.TABLE_CATALOG = c.TABLE_CATALOG
             AND cx.TABLE_SCHEMA = c.TABLE_SCHEMA
             AND cx.TABLE_NAME = c.TABLE_NAME
             AND cx.COLUMN_NAME = c.COLUMN_NAME
            WHERE c.TABLE_SCHEMA = DATABASE()
            ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
            """
        ),
        fields=(
            "table_name",
            "ordinal_position",
            "column_name",
            "column_default",
            "is_nullable",
            "data_type",
            "column_type",
            "character_maximum_length",
            "numeric_precision",
            "numeric_scale",
            "datetime_precision",
            "character_set_name",
            "collation_name",
            "column_key",
            "extra",
            "column_comment",
            "generation_expression",
            "srs_id",
            "engine_attribute",
            "secondary_engine_attribute",
        ),
        required_text_fields=(
            "table_name",
            "ordinal_position",
            "column_name",
            "is_nullable",
            "data_type",
            "column_type",
        ),
    ),
    _InventoryQuery(
        name="indexes",
        statement=sa.text(
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
                INDEX_TYPE AS index_type,
                COMMENT AS comment,
                INDEX_COMMENT AS index_comment,
                IS_VISIBLE AS is_visible,
                EXPRESSION AS expression
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
            ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
            """
        ),
        fields=(
            "table_name",
            "index_name",
            "non_unique",
            "seq_in_index",
            "column_name",
            "collation",
            "sub_part",
            "nullable",
            "index_type",
            "comment",
            "index_comment",
            "is_visible",
            "expression",
        ),
        required_text_fields=(
            "table_name",
            "index_name",
            "non_unique",
            "seq_in_index",
            "index_type",
            "is_visible",
        ),
    ),
    _InventoryQuery(
        name="constraints",
        statement=sa.text(
            """
            SELECT
                TABLE_NAME AS table_name,
                CONSTRAINT_NAME AS constraint_name,
                CONSTRAINT_TYPE AS constraint_type,
                ENFORCED AS enforced
            FROM information_schema.TABLE_CONSTRAINTS
            WHERE CONSTRAINT_SCHEMA = DATABASE()
            ORDER BY TABLE_NAME, CONSTRAINT_NAME, CONSTRAINT_TYPE
            """
        ),
        fields=(
            "table_name",
            "constraint_name",
            "constraint_type",
            "enforced",
        ),
        required_text_fields=(
            "table_name",
            "constraint_name",
            "constraint_type",
            "enforced",
        ),
    ),
    _InventoryQuery(
        name="constraint_columns",
        statement=sa.text(
            """
            SELECT
                TABLE_NAME AS table_name,
                CONSTRAINT_NAME AS constraint_name,
                CAST(ORDINAL_POSITION AS CHAR) AS ordinal_position,
                COLUMN_NAME AS column_name,
                CAST(POSITION_IN_UNIQUE_CONSTRAINT AS CHAR)
                    AS position_in_unique_constraint,
                CASE
                    WHEN REFERENCED_TABLE_SCHEMA IS NULL THEN NULL
                    WHEN REFERENCED_TABLE_SCHEMA = DATABASE() THEN 'current'
                    ELSE 'external'
                END AS referenced_schema_scope,
                REFERENCED_TABLE_NAME AS referenced_table_name,
                REFERENCED_COLUMN_NAME AS referenced_column_name
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE CONSTRAINT_SCHEMA = DATABASE()
            ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION
            """
        ),
        fields=(
            "table_name",
            "constraint_name",
            "ordinal_position",
            "column_name",
            "position_in_unique_constraint",
            "referenced_schema_scope",
            "referenced_table_name",
            "referenced_column_name",
        ),
        required_text_fields=(
            "table_name",
            "constraint_name",
            "ordinal_position",
            "column_name",
        ),
    ),
    _InventoryQuery(
        name="foreign_keys",
        statement=sa.text(
            """
            SELECT
                TABLE_NAME AS table_name,
                CONSTRAINT_NAME AS constraint_name,
                UNIQUE_CONSTRAINT_NAME AS unique_constraint_name,
                CASE
                    WHEN UNIQUE_CONSTRAINT_SCHEMA = DATABASE() THEN 'current'
                    ELSE 'external'
                END AS unique_constraint_schema_scope,
                REFERENCED_TABLE_NAME AS referenced_table_name,
                MATCH_OPTION AS match_option,
                UPDATE_RULE AS update_rule,
                DELETE_RULE AS delete_rule
            FROM information_schema.REFERENTIAL_CONSTRAINTS
            WHERE CONSTRAINT_SCHEMA = DATABASE()
            ORDER BY TABLE_NAME, CONSTRAINT_NAME
            """
        ),
        fields=(
            "table_name",
            "constraint_name",
            "unique_constraint_name",
            "unique_constraint_schema_scope",
            "referenced_table_name",
            "match_option",
            "update_rule",
            "delete_rule",
        ),
        required_text_fields=(
            "table_name",
            "constraint_name",
            "unique_constraint_name",
            "unique_constraint_schema_scope",
            "referenced_table_name",
            "match_option",
            "update_rule",
            "delete_rule",
        ),
    ),
    _InventoryQuery(
        name="checks",
        statement=sa.text(
            """
            SELECT
                tc.TABLE_NAME AS table_name,
                cc.CONSTRAINT_NAME AS constraint_name,
                cc.CHECK_CLAUSE AS check_clause,
                tc.ENFORCED AS enforced
            FROM information_schema.TABLE_CONSTRAINTS AS tc
            JOIN information_schema.CHECK_CONSTRAINTS AS cc
              ON cc.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA
             AND cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
            WHERE tc.CONSTRAINT_SCHEMA = DATABASE()
              AND tc.CONSTRAINT_TYPE = 'CHECK'
            ORDER BY tc.TABLE_NAME, cc.CONSTRAINT_NAME
            """
        ),
        fields=("table_name", "constraint_name", "check_clause", "enforced"),
        required_text_fields=(
            "table_name",
            "constraint_name",
            "check_clause",
            "enforced",
        ),
    ),
    _InventoryQuery(
        name="views",
        statement=sa.text(
            """
            SELECT
                TABLE_NAME AS view_name,
                VIEW_DEFINITION AS view_definition,
                CHECK_OPTION AS check_option,
                IS_UPDATABLE AS is_updatable,
                DEFINER AS definer,
                SECURITY_TYPE AS security_type,
                CHARACTER_SET_CLIENT AS character_set_client,
                COLLATION_CONNECTION AS collation_connection
            FROM information_schema.VIEWS
            WHERE TABLE_SCHEMA = DATABASE()
            ORDER BY TABLE_NAME
            """
        ),
        fields=(
            "view_name",
            "view_definition",
            "check_option",
            "is_updatable",
            "definer",
            "security_type",
            "character_set_client",
            "collation_connection",
        ),
        required_text_fields=(
            "view_name",
            "view_definition",
            "check_option",
            "is_updatable",
            "definer",
            "security_type",
        ),
    ),
    _InventoryQuery(
        name="triggers",
        statement=sa.text(
            """
            SELECT
                TRIGGER_NAME AS trigger_name,
                EVENT_MANIPULATION AS event_manipulation,
                EVENT_OBJECT_TABLE AS event_object_table,
                CAST(ACTION_ORDER AS CHAR) AS action_order,
                ACTION_CONDITION AS action_condition,
                ACTION_STATEMENT AS action_statement,
                ACTION_ORIENTATION AS action_orientation,
                ACTION_TIMING AS action_timing,
                ACTION_REFERENCE_OLD_ROW AS action_reference_old_row,
                ACTION_REFERENCE_NEW_ROW AS action_reference_new_row,
                SQL_MODE AS sql_mode,
                DEFINER AS definer,
                CHARACTER_SET_CLIENT AS character_set_client,
                COLLATION_CONNECTION AS collation_connection,
                DATABASE_COLLATION AS database_collation
            FROM information_schema.TRIGGERS
            WHERE TRIGGER_SCHEMA = DATABASE()
            ORDER BY TRIGGER_NAME
            """
        ),
        fields=(
            "trigger_name",
            "event_manipulation",
            "event_object_table",
            "action_order",
            "action_condition",
            "action_statement",
            "action_orientation",
            "action_timing",
            "action_reference_old_row",
            "action_reference_new_row",
            "sql_mode",
            "definer",
            "character_set_client",
            "collation_connection",
            "database_collation",
        ),
        required_text_fields=(
            "trigger_name",
            "event_manipulation",
            "event_object_table",
            "action_order",
            "action_statement",
            "action_orientation",
            "action_timing",
            "sql_mode",
            "definer",
        ),
    ),
    _InventoryQuery(
        name="routines",
        statement=sa.text(
            """
            SELECT
                ROUTINE_NAME AS routine_name,
                SPECIFIC_NAME AS specific_name,
                ROUTINE_TYPE AS routine_type,
                DATA_TYPE AS data_type,
                DTD_IDENTIFIER AS dtd_identifier,
                ROUTINE_BODY AS routine_body,
                ROUTINE_DEFINITION AS routine_definition,
                EXTERNAL_NAME AS external_name,
                EXTERNAL_LANGUAGE AS external_language,
                PARAMETER_STYLE AS parameter_style,
                IS_DETERMINISTIC AS is_deterministic,
                SQL_DATA_ACCESS AS sql_data_access,
                SQL_PATH AS sql_path,
                SECURITY_TYPE AS security_type,
                SQL_MODE AS sql_mode,
                ROUTINE_COMMENT AS routine_comment,
                DEFINER AS definer,
                CHARACTER_SET_CLIENT AS character_set_client,
                COLLATION_CONNECTION AS collation_connection,
                DATABASE_COLLATION AS database_collation
            FROM information_schema.ROUTINES
            WHERE ROUTINE_SCHEMA = DATABASE()
            ORDER BY ROUTINE_TYPE, SPECIFIC_NAME
            """
        ),
        fields=(
            "routine_name",
            "specific_name",
            "routine_type",
            "data_type",
            "dtd_identifier",
            "routine_body",
            "routine_definition",
            "external_name",
            "external_language",
            "parameter_style",
            "is_deterministic",
            "sql_data_access",
            "sql_path",
            "security_type",
            "sql_mode",
            "routine_comment",
            "definer",
            "character_set_client",
            "collation_connection",
            "database_collation",
        ),
        required_text_fields=(
            "routine_name",
            "specific_name",
            "routine_type",
            "routine_body",
            "routine_definition",
            "parameter_style",
            "is_deterministic",
            "sql_data_access",
            "security_type",
            "sql_mode",
            "definer",
        ),
    ),
    _InventoryQuery(
        name="routine_parameters",
        statement=sa.text(
            """
            SELECT
                SPECIFIC_NAME AS specific_name,
                CAST(ORDINAL_POSITION AS CHAR) AS ordinal_position,
                PARAMETER_MODE AS parameter_mode,
                PARAMETER_NAME AS parameter_name,
                DATA_TYPE AS data_type,
                DTD_IDENTIFIER AS dtd_identifier,
                CHARACTER_SET_NAME AS character_set_name,
                COLLATION_NAME AS collation_name
            FROM information_schema.PARAMETERS
            WHERE SPECIFIC_SCHEMA = DATABASE()
            ORDER BY SPECIFIC_NAME, ORDINAL_POSITION
            """
        ),
        fields=(
            "specific_name",
            "ordinal_position",
            "parameter_mode",
            "parameter_name",
            "data_type",
            "dtd_identifier",
            "character_set_name",
            "collation_name",
        ),
        required_text_fields=(
            "specific_name",
            "ordinal_position",
            "data_type",
            "dtd_identifier",
        ),
    ),
    _InventoryQuery(
        name="events",
        statement=sa.text(
            """
            SELECT
                EVENT_NAME AS event_name,
                EVENT_BODY AS event_body,
                EVENT_DEFINITION AS event_definition,
                EVENT_TYPE AS event_type,
                CAST(EXECUTE_AT AS CHAR) AS execute_at,
                INTERVAL_VALUE AS interval_value,
                INTERVAL_FIELD AS interval_field,
                SQL_MODE AS sql_mode,
                CAST(STARTS AS CHAR) AS starts,
                CAST(ENDS AS CHAR) AS ends,
                STATUS AS status,
                ON_COMPLETION AS on_completion,
                EVENT_COMMENT AS event_comment,
                CHARACTER_SET_CLIENT AS character_set_client,
                COLLATION_CONNECTION AS collation_connection,
                DATABASE_COLLATION AS database_collation,
                DEFINER AS definer,
                TIME_ZONE AS time_zone
            FROM information_schema.EVENTS
            WHERE EVENT_SCHEMA = DATABASE()
            ORDER BY EVENT_NAME
            """
        ),
        fields=(
            "event_name",
            "event_body",
            "event_definition",
            "event_type",
            "execute_at",
            "interval_value",
            "interval_field",
            "sql_mode",
            "starts",
            "ends",
            "status",
            "on_completion",
            "event_comment",
            "character_set_client",
            "collation_connection",
            "database_collation",
            "definer",
            "time_zone",
        ),
        required_text_fields=(
            "event_name",
            "event_body",
            "event_definition",
            "event_type",
            "sql_mode",
            "status",
            "on_completion",
            "definer",
            "time_zone",
        ),
    ),
)


class MySql8TenantSchemaObserver:
    """Observe the actual current MySQL 8 tenant schema using fixed SQL."""

    __slots__ = ()

    def observe(
        self,
        connection: TenantMigrationConnection,
        *,
        phase: TenantMigrationObservationPhase,
        context: TenantMigrationExecutionContext,
    ) -> FleetMigrationObservation:
        try:
            if (
                not isinstance(connection, MySql8SchemaObservationConnection)
                or not isinstance(phase, TenantMigrationObservationPhase)
                or not isinstance(context, TenantMigrationExecutionContext)
            ):
                raise TenantMigrationObservationError()
            profile = _read_profile(connection)
            _require_core_base_tables(connection)
            tenant_uuid, database_uuid, generation = _read_identity(connection)
            if (
                tenant_uuid != context.source.tenant_uuid
                or database_uuid != context.source.database_uuid
            ):
                raise TenantMigrationObservationError()
            revision = _read_alembic_revision(connection)
            _require_complete_metadata_visibility(connection)
            sections = {
                query.name: _canonical_inventory_rows(
                    _read_rows(connection, query.statement),
                    query=query,
                )
                for query in _INVENTORY_QUERIES
            }
            digest = _inventory_digest(profile=profile, sections=sections)
            return FleetMigrationObservation(
                identity=FleetSchemaIdentity(
                    tenant_uuid=tenant_uuid,
                    database_uuid=database_uuid,
                    schema_generation=generation,
                    schema_revision=revision,
                    schema_sha256=digest,
                ),
                observed_at=profile.observed_at,
            )
        except TenantMigrationObservationError:
            raise
        except Exception:
            raise TenantMigrationObservationError() from None


def _read_profile(connection: MySql8SchemaObservationConnection) -> _ServerProfile:
    row = _exactly_one(_read_rows(connection, _PROFILE_SQL))
    _require_exact_fields(
        row,
        (
            "server_version",
            "version_comment",
            "lower_case_table_names",
            "show_generated_invisible_primary_keys",
            "observed_at",
            "current_database",
        ),
    )
    version = _required_text(row["server_version"])
    comment = _required_text(row["version_comment"])
    selected = _MYSQL_VERSION.fullmatch(version)
    if (
        selected is None
        or int(selected.group("patch"))
        < MYSQL8_SCHEMA_INVENTORY_MINIMUM_PATCH
        or "mariadb" in version.lower()
        or "mariadb" in comment.lower()
    ):
        raise TenantMigrationObservationError()
    lower_case = _decimal_integer(row["lower_case_table_names"], positive=False)
    if lower_case not in {0, 1, 2}:
        raise TenantMigrationObservationError()
    if row["show_generated_invisible_primary_keys"] != "1":
        raise TenantMigrationObservationError()
    current_database = _required_text(row["current_database"])
    if (
        len(current_database) > 64
        or "\x00" in current_database
        or current_database.strip() != current_database
    ):
        raise TenantMigrationObservationError()
    return _ServerProfile(
        observed_at=_utc(row["observed_at"]),
        current_database=current_database,
        lower_case_table_names=lower_case,
    )


def _require_core_base_tables(
    connection: MySql8SchemaObservationConnection,
) -> None:
    rows = _read_rows(connection, _CORE_BASE_TABLES_SQL)
    if len(rows) != 2:
        raise TenantMigrationObservationError()
    observed: dict[str, str] = {}
    for row in rows:
        _require_exact_fields(row, ("table_name", "table_type"))
        table_name = _required_text(row["table_name"])
        table_type = _required_text(row["table_type"])
        if table_name in observed:
            raise TenantMigrationObservationError()
        observed[table_name] = table_type
    if observed != {
        "alembic_version": "BASE TABLE",
        "database_identity": "BASE TABLE",
    }:
        raise TenantMigrationObservationError()


def _read_identity(
    connection: MySql8SchemaObservationConnection,
) -> tuple[UUID, UUID, int]:
    row = _exactly_one(_read_rows(connection, _IDENTITY_SQL))
    _require_exact_fields(
        row,
        (
            "singleton_key",
            "tenant_id",
            "database_uuid",
            "schema_generation",
        ),
    )
    if _decimal_integer(row["singleton_key"], positive=True) != 1:
        raise TenantMigrationObservationError()
    tenant_uuid = _canonical_uuid(row["tenant_id"])
    database_uuid = _canonical_uuid(row["database_uuid"])
    if tenant_uuid == database_uuid:
        raise TenantMigrationObservationError()
    generation = _decimal_integer(row["schema_generation"], positive=True)
    return tenant_uuid, database_uuid, generation


def _read_alembic_revision(
    connection: MySql8SchemaObservationConnection,
) -> str:
    row = _exactly_one(_read_rows(connection, _ALEMBIC_VERSION_SQL))
    _require_exact_fields(row, ("version_num",))
    revision = _required_text(row["version_num"])
    if _REVISION.fullmatch(revision) is None:
        raise TenantMigrationObservationError()
    return revision


def _require_complete_metadata_visibility(
    connection: MySql8SchemaObservationConnection,
) -> None:
    rows = _read_rows(connection, _VISIBILITY_SQL)
    global_privileges: set[str] = set()
    schema_privileges: set[str] = set()
    for row in rows:
        _require_exact_fields(row, ("privilege_scope", "privilege_type"))
        scope = _required_text(row["privilege_scope"])
        privilege = _required_text(row["privilege_type"])
        if scope == "global":
            global_privileges.add(privilege)
        elif scope == "schema":
            schema_privileges.add(privilege)
        else:
            raise TenantMigrationObservationError()
    # Do not infer schema visibility from a global grant: MySQL partial
    # revokes are not represented by the positive USER_PRIVILEGES rows and
    # could otherwise hide drift in this database.  Explicit schema grants
    # make completeness conservative and mechanically observable.
    if not {"ALTER", "SHOW VIEW", "TRIGGER", "EVENT"}.issubset(
        schema_privileges
    ):
        raise TenantMigrationObservationError()
    if "SHOW_ROUTINE" not in global_privileges:
        raise TenantMigrationObservationError()


def _read_rows(
    connection: MySql8SchemaObservationConnection,
    statement: object,
) -> tuple[Mapping[str, object], ...]:
    try:
        result = connection.execute(statement)
        mappings = result.mappings()
        selected = tuple(
            islice(mappings, MAX_SCHEMA_INVENTORY_ROWS_PER_SECTION + 1)
        )
    except Exception:
        raise TenantMigrationObservationError() from None
    if len(selected) > MAX_SCHEMA_INVENTORY_ROWS_PER_SECTION:
        raise TenantMigrationObservationError()
    if not all(isinstance(row, Mapping) for row in selected):
        raise TenantMigrationObservationError()
    return selected


def _canonical_inventory_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    query: _InventoryQuery,
) -> tuple[dict[str, object], ...]:
    selected: list[dict[str, object]] = []
    for row in rows:
        _require_exact_fields(row, query.fields)
        for field in query.required_text_fields:
            _required_text(row[field])
        if query.name == "constraint_columns" and row[
            "referenced_schema_scope"
        ] not in {None, "current"}:
            raise TenantMigrationObservationError()
        if query.name == "foreign_keys" and row[
            "unique_constraint_schema_scope"
        ] != "current":
            raise TenantMigrationObservationError()
        selected.append(
            {
                field: _canonical_scalar(row[field])
                for field in query.fields
            }
        )
    selected.sort(key=_canonical_json)
    if query.name == "schema" and len(selected) != 1:
        raise TenantMigrationObservationError()
    return tuple(selected)


def _inventory_digest(
    *,
    profile: _ServerProfile,
    sections: Mapping[str, tuple[dict[str, object], ...]],
) -> bytes:
    payload = {
        "format": MYSQL8_SCHEMA_INVENTORY_FORMAT,
        "profile": profile.digest_profile,
        "sections": sections,
    }
    return hashlib.sha256(
        _INVENTORY_DOMAIN + _canonical_json(payload).encode("ascii")
    ).digest()


def _exactly_one(
    rows: tuple[Mapping[str, object], ...],
) -> Mapping[str, object]:
    if len(rows) != 1:
        raise TenantMigrationObservationError()
    return rows[0]


def _require_exact_fields(
    row: Mapping[str, object],
    fields: tuple[str, ...],
) -> None:
    if set(row) != set(fields):
        raise TenantMigrationObservationError()


def _required_text(value: object) -> str:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            raise TenantMigrationObservationError() from None
    if not isinstance(value, str) or not value or "\x00" in value:
        raise TenantMigrationObservationError()
    return value


def _canonical_uuid(value: object) -> UUID:
    selected = _required_text(value)
    try:
        parsed = UUID(selected)
    except ValueError:
        raise TenantMigrationObservationError() from None
    if parsed.int == 0 or str(parsed) != selected:
        raise TenantMigrationObservationError()
    return parsed


def _decimal_integer(value: object, *, positive: bool) -> int:
    selected = _required_text(value)
    if _POSITIVE_DECIMAL.fullmatch(selected) is None:
        if not positive and selected == "0":
            return 0
        raise TenantMigrationObservationError()
    return int(selected)


def _canonical_scalar(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            raise TenantMigrationObservationError() from None
    if isinstance(value, str):
        return value.replace("\r\n", "\n").replace("\r", "\n")
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise TenantMigrationObservationError()
        return format(value, "f")
    if isinstance(value, datetime):
        return _utc(value).isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        if value.tzinfo is not None:
            raise TenantMigrationObservationError()
        return value.isoformat(timespec="microseconds")
    raise TenantMigrationObservationError()


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        raise TenantMigrationObservationError() from None


def _utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TenantMigrationObservationError()
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "MAX_SCHEMA_INVENTORY_ROWS_PER_SECTION",
    "MYSQL8_SCHEMA_INVENTORY_FORMAT",
    "MYSQL8_SCHEMA_INVENTORY_MINIMUM_PATCH",
    "MySql8SchemaObservationConnection",
    "MySql8TenantSchemaObserver",
]
