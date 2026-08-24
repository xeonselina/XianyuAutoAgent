from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from inspect import signature
from typing import Mapping
from uuid import UUID

import pytest

from inventory_control.fleet_migrations.domain import (
    FleetRouteDisposition,
    FleetSchemaIdentity,
    SchemaCompatibilityWindow,
)
from inventory_control.fleet_migrations.mysql_observer import (
    MYSQL8_SCHEMA_INVENTORY_FORMAT,
    MySql8TenantSchemaObserver,
)
from inventory_control.fleet_migrations.persistence import (
    FleetSchemaOperationFence,
)
from inventory_control.fleet_migrations.runner import (
    TenantMigrationExecutionContext,
    TenantMigrationObservationError,
    TenantMigrationObservationPhase,
    TrustedTenantMigrationObserver,
)


TENANT_UUID = UUID("81000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("82000000-0000-4000-8000-000000000002")
MIGRATION_UUID = UUID("83000000-0000-4000-8000-000000000003")
CLAIM_UUID = UUID("84000000-0000-4000-8000-000000000004")
OBSERVED_AT = datetime(2026, 8, 22, 16, 4, 5, 654321)


class FakeMappingResult:
    def __init__(self, rows: list[Mapping[str, object]]) -> None:
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class FakeExecutionResult:
    def __init__(self, rows: list[Mapping[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> FakeMappingResult:
        return FakeMappingResult(self._rows)


class FakeMySqlConnection:
    def __init__(
        self,
        responses: dict[str, list[dict[str, object]]],
        *,
        fail_section: str | None = None,
    ) -> None:
        self.responses = deepcopy(responses)
        self.fail_section = fail_section
        self.calls: list[str] = []

    def execute(self, statement: object) -> FakeExecutionResult:
        sql = " ".join(str(statement).split())
        self.calls.append(sql)
        section = _section(sql)
        if section == self.fail_section:
            raise RuntimeError("UNTRUSTED_DATABASE_DIAGNOSTIC")
        return FakeExecutionResult(deepcopy(self.responses[section]))


def _section(sql: str) -> str:
    if "@@version AS CHAR" in sql:
        return "profile"
    if "TABLE_NAME IN ('alembic_version', 'database_identity')" in sql:
        return "core_tables"
    if "FROM database_identity" in sql:
        return "identity"
    if "FROM alembic_version" in sql:
        return "version"
    if "information_schema.USER_PRIVILEGES" in sql:
        return "visibility"
    if "information_schema.CHECK_CONSTRAINTS" in sql:
        return "checks"
    selected = {
        "information_schema.SCHEMATA": "schema",
        "information_schema.TABLES": "tables",
        "information_schema.PARTITIONS": "partitions",
        "information_schema.COLUMNS": "columns",
        "information_schema.STATISTICS": "indexes",
        "information_schema.TABLE_CONSTRAINTS": "constraints",
        "information_schema.KEY_COLUMN_USAGE": "constraint_columns",
        "information_schema.REFERENTIAL_CONSTRAINTS": "foreign_keys",
        "information_schema.VIEWS": "views",
        "information_schema.TRIGGERS": "triggers",
        "information_schema.ROUTINES": "routines",
        "information_schema.PARAMETERS": "routine_parameters",
        "information_schema.EVENTS": "events",
    }
    matches = [value for marker, value in selected.items() if marker in sql]
    assert len(matches) == 1, sql
    return matches[0]


def _responses() -> dict[str, list[dict[str, object]]]:
    return {
        "profile": [
            {
                "server_version": "8.0.43",
                "version_comment": "MySQL Community Server - GPL",
                "lower_case_table_names": "0",
                "show_generated_invisible_primary_keys": "1",
                "observed_at": OBSERVED_AT,
                "current_database": "opaque_bound_database",
            }
        ],
        "core_tables": [
            {"table_name": "alembic_version", "table_type": "BASE TABLE"},
            {"table_name": "database_identity", "table_type": "BASE TABLE"},
        ],
        "identity": [
            {
                "singleton_key": "1",
                "tenant_id": str(TENANT_UUID),
                "database_uuid": str(DATABASE_UUID),
                "schema_generation": "8",
            }
        ],
        "version": [{"version_num": "rev_8"}],
        "visibility": [
            {"privilege_scope": "global", "privilege_type": "SHOW_ROUTINE"},
            {"privilege_scope": "schema", "privilege_type": "ALTER"},
            {"privilege_scope": "schema", "privilege_type": "SHOW VIEW"},
            {"privilege_scope": "schema", "privilege_type": "TRIGGER"},
            {"privilege_scope": "schema", "privilege_type": "EVENT"},
        ],
        "schema": [
            {
                "default_character_set_name": "utf8mb4",
                "default_collation_name": "utf8mb4_0900_ai_ci",
                "sql_path": None,
                "default_encryption": "NO",
                "schema_options": None,
            }
        ],
        "tables": [
            {
                "table_name": "devices",
                "table_type": "BASE TABLE",
                "engine": "InnoDB",
                "row_format": "Dynamic",
                "table_collation": "utf8mb4_0900_ai_ci",
                "create_options": "",
                "table_comment": "",
                "engine_attribute": None,
                "secondary_engine_attribute": None,
            }
        ],
        "partitions": [
            {
                "table_name": "devices",
                "partition_ordinal_position": None,
                "partition_name": None,
                "partition_method": None,
                "partition_expression": None,
                "partition_description": None,
                "subpartition_ordinal_position": None,
                "subpartition_name": None,
                "subpartition_method": None,
                "subpartition_expression": None,
                "partition_comment": "",
                "nodegroup": "",
                "tablespace_name": None,
            }
        ],
        "columns": [
            {
                "table_name": "devices",
                "ordinal_position": "1",
                "column_name": "id",
                "column_default": None,
                "is_nullable": "NO",
                "data_type": "int",
                "column_type": "int",
                "character_maximum_length": None,
                "numeric_precision": "10",
                "numeric_scale": "0",
                "datetime_precision": None,
                "character_set_name": None,
                "collation_name": None,
                "column_key": "PRI",
                "extra": "auto_increment",
                "column_comment": "",
                "generation_expression": "",
                "srs_id": None,
                "engine_attribute": None,
                "secondary_engine_attribute": None,
            }
        ],
        "indexes": [
            {
                "table_name": "devices",
                "index_name": "PRIMARY",
                "non_unique": "0",
                "seq_in_index": "1",
                "column_name": "id",
                "collation": "A",
                "sub_part": None,
                "nullable": "",
                "index_type": "BTREE",
                "comment": "",
                "index_comment": "",
                "is_visible": "YES",
                "expression": None,
            }
        ],
        "constraints": [
            {
                "table_name": "devices",
                "constraint_name": "PRIMARY",
                "constraint_type": "PRIMARY KEY",
                "enforced": "YES",
            }
        ],
        "constraint_columns": [
            {
                "table_name": "devices",
                "constraint_name": "PRIMARY",
                "ordinal_position": "1",
                "column_name": "id",
                "position_in_unique_constraint": None,
                "referenced_schema_scope": None,
                "referenced_table_name": None,
                "referenced_column_name": None,
            }
        ],
        "foreign_keys": [],
        "checks": [],
        "views": [],
        "triggers": [],
        "routines": [],
        "routine_parameters": [],
        "events": [],
    }


def _identity(*, generation: int, revision: str, digest: bytes) -> FleetSchemaIdentity:
    return FleetSchemaIdentity(
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        schema_generation=generation,
        schema_revision=revision,
        schema_sha256=digest,
    )


def _context() -> TenantMigrationExecutionContext:
    return TenantMigrationExecutionContext(
        migration_uuid=MIGRATION_UUID,
        operation_generation=3,
        schema_operation_fence=FleetSchemaOperationFence(
            claim_id=CLAIM_UUID,
            owner_id="fleet-worker-01",
            generation=5,
            fencing_token=7,
            row_version=11,
        ),
        bundle_id="tenant-schema-n8-to-n9",
        bundle_revision="build-20260822.1",
        bundle_sha256=bytes.fromhex("44" * 32),
        source=_identity(
            generation=8,
            revision="rev_8",
            digest=bytes.fromhex("11" * 32),
        ),
        target=_identity(
            generation=9,
            revision="rev_9",
            digest=bytes.fromhex("22" * 32),
        ),
    )


def _observe(responses=None):
    connection = FakeMySqlConnection(responses or _responses())
    observation = MySql8TenantSchemaObserver().observe(
        connection,
        phase=TenantMigrationObservationPhase.BEFORE_DDL,
        context=_context(),
    )
    return observation, connection


def test_observer_implements_runner_contract_and_returns_actual_inventory() -> None:
    observer = MySql8TenantSchemaObserver()
    assert isinstance(observer, TrustedTenantMigrationObserver)

    observation, connection = _observe()

    assert observation.identity.tenant_uuid == TENANT_UUID
    assert observation.identity.database_uuid == DATABASE_UUID
    assert observation.identity.schema_generation == 8
    assert observation.identity.schema_revision == "rev_8"
    assert len(observation.identity.schema_sha256) == 32
    assert observation.identity.schema_sha256 != bytes.fromhex("11" * 32)
    assert observation.observed_at == OBSERVED_AT.replace(tzinfo=timezone.utc)
    assert len(connection.calls) == 19


@pytest.mark.parametrize("drift", ["trigger", "view", "table_options"])
def test_well_formed_schema_drift_returns_a_different_observation(
    drift: str,
) -> None:
    baseline, _ = _observe()
    changed = _responses()
    if drift == "trigger":
        changed["triggers"] = [
            {
                "trigger_name": "unexpected_trigger",
                "event_manipulation": "INSERT",
                "event_object_table": "devices",
                "action_order": "1",
                "action_condition": None,
                "action_statement": "SET NEW.id = NEW.id",
                "action_orientation": "ROW",
                "action_timing": "BEFORE",
                "action_reference_old_row": "OLD",
                "action_reference_new_row": "NEW",
                "sql_mode": "STRICT_TRANS_TABLES",
                "definer": "internal@localhost",
                "character_set_client": "utf8mb4",
                "collation_connection": "utf8mb4_0900_ai_ci",
                "database_collation": "utf8mb4_0900_ai_ci",
            }
        ]
    elif drift == "view":
        changed["views"] = [
            {
                "view_name": "unexpected_view",
                "view_definition": "select 1 AS value",
                "check_option": "NONE",
                "is_updatable": "NO",
                "definer": "internal@localhost",
                "security_type": "DEFINER",
                "character_set_client": "utf8mb4",
                "collation_connection": "utf8mb4_0900_ai_ci",
            }
        ]
    else:
        changed["tables"][0]["row_format"] = "Compressed"
        changed["tables"][0]["create_options"] = "key_block_size=8"

    observed, _ = _observe(changed)

    assert observed.identity.schema_generation == 8
    assert observed.identity.schema_revision == "rev_8"
    assert observed.identity.schema_sha256 != baseline.identity.schema_sha256
    assert (
        SchemaCompatibilityWindow(current=baseline.identity).evaluate(
            observed.identity
        )
        is FleetRouteDisposition.HOLD_SCHEMA_DRIFT
    )


def test_generated_column_index_constraint_and_partition_changes_affect_digest(
) -> None:
    baseline, _ = _observe()
    changed = _responses()
    changed["columns"][0]["extra"] = "VIRTUAL GENERATED"
    changed["columns"][0]["generation_expression"] = "(`id` + 1)"
    changed["indexes"][0]["is_visible"] = "NO"
    changed["constraints"][0]["enforced"] = "NO"
    changed["partitions"][0]["partition_name"] = "p0"
    changed["partitions"][0]["partition_ordinal_position"] = "1"
    changed["partitions"][0]["partition_method"] = "HASH"
    changed["partitions"][0]["partition_expression"] = "`id`"

    observed, _ = _observe(changed)

    assert observed.identity.schema_sha256 != baseline.identity.schema_sha256


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("schema", "schema_options", '{"read_only": true}'),
        ("tables", "engine_attribute", '{"tier": "hot"}'),
        ("columns", "secondary_engine_attribute", '{"encoding": "x"}'),
    ],
)
def test_mysql8_extension_metadata_changes_affect_digest(
    section: str,
    field: str,
    value: str,
) -> None:
    baseline, _ = _observe()
    changed = _responses()
    changed[section][0][field] = value

    observed, _ = _observe(changed)

    assert observed.identity.schema_sha256 != baseline.identity.schema_sha256


def test_inventory_order_is_canonical_and_not_result_order_dependent() -> None:
    changed = _responses()
    second = deepcopy(changed["columns"][0])
    second["ordinal_position"] = "2"
    second["column_name"] = "serial"
    second["column_key"] = "UNI"
    changed["columns"].append(second)
    forward, _ = _observe(changed)
    changed["columns"].reverse()

    reverse, _ = _observe(changed)

    assert reverse.identity.schema_sha256 == forward.identity.schema_sha256


@pytest.mark.parametrize("identity_state", ["missing", "duplicate", "mismatch"])
def test_damaged_or_mismatched_database_identity_is_a_fixed_error(
    identity_state: str,
) -> None:
    responses = _responses()
    if identity_state == "missing":
        responses["identity"] = []
    elif identity_state == "duplicate":
        responses["identity"].append(deepcopy(responses["identity"][0]))
    else:
        responses["identity"][0]["database_uuid"] = str(
            UUID("82000000-0000-4000-8000-000000000099")
        )
    connection = FakeMySqlConnection(responses)

    with pytest.raises(TenantMigrationObservationError) as raised:
        MySql8TenantSchemaObserver().observe(
            connection,
            phase=TenantMigrationObservationPhase.BEFORE_DDL,
            context=_context(),
        )

    assert str(DATABASE_UUID) not in str(raised.value)
    assert "opaque_bound_database" not in repr(raised.value)


@pytest.mark.parametrize("core_state", ["missing", "duplicate", "view"])
def test_identity_and_alembic_must_be_exact_current_database_base_tables(
    core_state: str,
) -> None:
    responses = _responses()
    if core_state == "missing":
        responses["core_tables"].pop()
    elif core_state == "duplicate":
        responses["core_tables"][1] = deepcopy(responses["core_tables"][0])
    else:
        responses["core_tables"][0]["table_type"] = "VIEW"
    connection = FakeMySqlConnection(responses)

    with pytest.raises(TenantMigrationObservationError):
        MySql8TenantSchemaObserver().observe(
            connection,
            phase=TenantMigrationObservationPhase.BEFORE_DDL,
            context=_context(),
        )

    assert len(connection.calls) == 2
    assert "information_schema.TABLES" in connection.calls[1]
    assert not any("FROM database_identity" in sql for sql in connection.calls)
    assert not any("FROM alembic_version" in sql for sql in connection.calls)


@pytest.mark.parametrize(
    "version_rows",
    [
        [],
        [{"version_num": "rev_8"}, {"version_num": "rev_7"}],
        [{"version_num": "contains whitespace"}],
        [{"version_num": None}],
    ],
)
def test_invalid_alembic_version_cardinality_or_value_is_rejected(
    version_rows: list[dict[str, object]],
) -> None:
    responses = _responses()
    responses["version"] = version_rows

    with pytest.raises(TenantMigrationObservationError):
        MySql8TenantSchemaObserver().observe(
            FakeMySqlConnection(responses),
            phase=TenantMigrationObservationPhase.BEFORE_DDL,
            context=_context(),
        )


def test_well_formed_unknown_revision_and_generation_are_observed_not_hidden() -> None:
    responses = _responses()
    responses["identity"][0]["schema_generation"] = "27"
    responses["version"][0]["version_num"] = "future_rev_27"

    observation, _ = _observe(responses)

    assert observation.identity.schema_generation == 27
    assert observation.identity.schema_revision == "future_rev_27"


def test_incomplete_information_schema_visibility_fails_closed() -> None:
    responses = _responses()
    responses["visibility"] = [
        row
        for row in responses["visibility"]
        if row["privilege_type"] != "TRIGGER"
    ]

    with pytest.raises(TenantMigrationObservationError):
        MySql8TenantSchemaObserver().observe(
            FakeMySqlConnection(responses),
            phase=TenantMigrationObservationPhase.BEFORE_DDL,
            context=_context(),
        )


def test_global_select_cannot_substitute_for_show_routine() -> None:
    responses = _responses()
    responses["visibility"][0]["privilege_type"] = "SELECT"

    with pytest.raises(TenantMigrationObservationError):
        _observe(responses)


def test_global_schema_privileges_are_rejected_as_partial_revoke_ambiguous() -> None:
    responses = _responses()
    responses["visibility"] = [
        {"privilege_scope": "global", "privilege_type": row["privilege_type"]}
        for row in responses["visibility"]
    ]

    with pytest.raises(TenantMigrationObservationError):
        _observe(responses)


@pytest.mark.parametrize("section", ["constraint_columns", "foreign_keys"])
def test_cross_schema_foreign_key_metadata_fails_closed(section: str) -> None:
    responses = _responses()
    if section == "constraint_columns":
        responses[section] = [
            {
                "table_name": "devices",
                "constraint_name": "fk_devices_external",
                "ordinal_position": "1",
                "column_name": "id",
                "position_in_unique_constraint": "1",
                "referenced_schema_scope": "external",
                "referenced_table_name": "parents",
                "referenced_column_name": "id",
            }
        ]
    else:
        responses[section] = [
            {
                "table_name": "devices",
                "constraint_name": "fk_devices_external",
                "unique_constraint_name": "PRIMARY",
                "unique_constraint_schema_scope": "external",
                "referenced_table_name": "parents",
                "match_option": "NONE",
                "update_rule": "RESTRICT",
                "delete_rule": "RESTRICT",
            }
        ]

    with pytest.raises(TenantMigrationObservationError):
        _observe(responses)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("server_version", "8.0.15"),
        ("server_version", "8.0.29"),
        ("server_version", "8.4.0"),
        ("server_version", "10.11.8-MariaDB"),
        ("version_comment", "MariaDB Server"),
        ("lower_case_table_names", "3"),
        ("show_generated_invisible_primary_keys", "0"),
        ("current_database", None),
    ],
)
def test_unsupported_mysql_family_or_profile_fails_closed(
    field: str,
    value: object,
) -> None:
    responses = _responses()
    responses["profile"][0][field] = value

    with pytest.raises(TenantMigrationObservationError):
        MySql8TenantSchemaObserver().observe(
            FakeMySqlConnection(responses),
            phase=TenantMigrationObservationPhase.BEFORE_DDL,
            context=_context(),
        )


def test_fixed_queries_are_current_database_scoped_and_accept_no_names() -> None:
    _, connection = _observe()

    assert signature(MySql8TenantSchemaObserver).parameters == {}
    assert MYSQL8_SCHEMA_INVENTORY_FORMAT.endswith("/v3")
    for sql in connection.calls:
        assert sql.upper().startswith("SELECT ")
        assert "DATABASE()" in sql
        assert "opaque_bound_database" not in sql
        assert str(TENANT_UUID) not in sql
        assert str(DATABASE_UUID) not in sql
        assert "rev_8" not in sql
        assert ":schema" not in sql.lower()
    inventory_sql = " ".join(connection.calls[5:]).upper()
    for required_extension in (
        "INFORMATION_SCHEMA.SCHEMATA_EXTENSIONS",
        "INFORMATION_SCHEMA.TABLES_EXTENSIONS",
        "INFORMATION_SCHEMA.COLUMNS_EXTENSIONS",
    ):
        assert required_extension in inventory_sql
    for excluded_volatile_field in (
        "TABLE_ROWS",
        "AUTO_INCREMENT AS",
        "CARDINALITY",
        "DATA_LENGTH",
        "INDEX_LENGTH",
        "CREATE_TIME",
        "UPDATE_TIME",
        "LAST_EXECUTED",
        "ORIGINATOR",
    ):
        assert excluded_volatile_field not in inventory_sql


def test_query_and_incomplete_definition_failures_never_echo_diagnostics() -> None:
    connection = FakeMySqlConnection(_responses(), fail_section="columns")

    with pytest.raises(TenantMigrationObservationError) as raised:
        MySql8TenantSchemaObserver().observe(
            connection,
            phase=TenantMigrationObservationPhase.AFTER_FAILED_DDL,
            context=_context(),
        )

    assert "UNTRUSTED_DATABASE_DIAGNOSTIC" not in str(raised.value)
    assert "UNTRUSTED_DATABASE_DIAGNOSTIC" not in repr(raised.value)

    responses = _responses()
    responses["views"] = [
        {
            "view_name": "hidden_definition",
            "view_definition": None,
            "check_option": "NONE",
            "is_updatable": "NO",
            "definer": "internal@localhost",
            "security_type": "DEFINER",
            "character_set_client": "utf8mb4",
            "collation_connection": "utf8mb4_0900_ai_ci",
        }
    ]
    with pytest.raises(TenantMigrationObservationError):
        MySql8TenantSchemaObserver().observe(
            FakeMySqlConnection(responses),
            phase=TenantMigrationObservationPhase.AFTER_DDL,
            context=_context(),
        )
