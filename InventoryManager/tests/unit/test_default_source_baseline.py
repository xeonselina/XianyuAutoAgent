from __future__ import annotations

import hashlib
from collections import OrderedDict
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.services.migration.default_source_baseline import (
    BoundDefaultSourceBaselineVerifier,
    BoundDefaultSourceMigrationPreflightVerifier,
    DefaultHistoricalBoundaryRejected,
    DefaultSourceBaselineInputError,
    DefaultSourceBaselineRejected,
    DefaultSourceMigrationPreflightEvidence,
    HistoricalSnapshotDisposition,
    SqlAlchemyDefaultSourceBaselineObserver,
    source_baseline_evidence_from_document,
    source_baseline_evidence_to_document,
    source_migration_preflight_from_document,
    source_migration_preflight_to_document,
)
from inventory_control.default_migration import (
    DefaultMigrationStepInvocation,
    DefaultTenantMigrationManifest,
    MigrationExecutionMode,
    MigrationExecutionPlan,
    MigrationPhase,
    MigrationPhaseInvocation,
)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


class _Result:
    def __init__(self, *, mappings=(), rows=(), scalar=None):
        self._mappings = list(mappings)
        self._rows = list(rows)
        self._scalar = scalar

    def mappings(self):
        return self

    def all(self):
        return list(self._mappings or self._rows)

    def scalar_one(self):
        return self._scalar


class _ReadOnlySourceConnection:
    def __init__(
        self,
        *,
        broad_grant=False,
        drift=False,
        historical_schema=False,
        historical_counts=None,
        missing_lifecycle=False,
    ):
        self.transaction = False
        self.closed = False
        self.broad_grant = broad_grant
        self.drift = drift
        self.historical_schema = historical_schema
        self.historical_counts = historical_counts or {}
        self.missing_lifecycle = missing_lifecycle
        self.table_reads = 0
        self.driver_statements = []

    def in_transaction(self):
        return self.transaction

    def rollback(self):
        self.transaction = False

    def close(self):
        self.closed = True

    def execute(self, statement):
        self.transaction = True
        sql = str(statement)
        if "CURRENT_USER() AS current_account" in sql:
            return _Result(mappings=(OrderedDict((
                ("database_name", "inventory_management_test"),
                ("current_account", "source_reader@%"),
                ("active_role", None),
                ("server_version", "10.11.6-MariaDB-log"),
                ("version_comment", "MariaDB Server"),
                ("lower_case_table_names", "0"),
                ("character_set_database", "utf8mb3"),
                ("collation_database", "utf8mb3_general_ci"),
            )),))
        if "FROM information_schema.TABLES" in sql:
            self.table_reads += 1
            rows = [
                OrderedDict((
                    ("table_name", "devices"),
                    ("table_type", "BASE TABLE"),
                    ("engine", "InnoDB"),
                    ("row_format", "Dynamic"),
                    ("table_collation", "utf8mb3_general_ci"),
                    ("create_options", ""),
                )),
                OrderedDict((
                    ("table_name", "rentals"),
                    ("table_type", "BASE TABLE"),
                    ("engine", "InnoDB"),
                    ("row_format", "Dynamic"),
                    ("table_collation", "utf8mb3_general_ci"),
                    ("create_options", ""),
                )),
            ]
            if self.historical_schema:
                rows.extend(
                    [
                        OrderedDict((
                            ("table_name", "audit_logs"),
                            ("table_type", "BASE TABLE"),
                            ("engine", "InnoDB"),
                            ("row_format", "Dynamic"),
                            ("table_collation", "utf8mb3_general_ci"),
                            ("create_options", ""),
                        )),
                    ]
                )
                rows.sort(key=lambda item: item["table_name"])
            if self.drift and self.table_reads > 1:
                rows.append(OrderedDict((
                    ("table_name", "unexpected"),
                    ("table_type", "BASE TABLE"),
                    ("engine", "InnoDB"),
                    ("row_format", "Dynamic"),
                    ("table_collation", "utf8mb3_general_ci"),
                    ("create_options", ""),
                )))
            return _Result(mappings=rows)
        if "FROM information_schema.COLUMNS" in sql:
            rows = [OrderedDict((
                ("table_name", "devices"),
                ("ordinal_position", "1"),
                ("column_name", "id"),
                ("column_default", None),
                ("is_nullable", "NO"),
                ("data_type", "int"),
                ("column_type", "int(11)"),
                ("character_set_name", None),
                ("collation_name", None),
                ("column_key", "PRI"),
                ("extra", "auto_increment"),
                ("generation_expression", ""),
            ))]
            if self.historical_schema:
                columns = [
                    ("audit_logs", "action", "varchar"),
                    ("rentals", "status", "varchar"),
                    ("rentals", "ship_out_tracking_no", "varchar"),
                    ("rentals", "ship_in_tracking_no", "varchar"),
                    ("rentals", "ship_in_time", "datetime"),
                ]
                if not self.missing_lifecycle:
                    columns.append(("rentals", "ship_out_time", "datetime"))
                for position, (table, column, data_type) in enumerate(
                    columns,
                    start=1,
                ):
                    rows.append(OrderedDict((
                        ("table_name", table),
                        ("ordinal_position", str(position)),
                        ("column_name", column),
                        ("column_default", None),
                        ("is_nullable", "YES"),
                        ("data_type", data_type),
                        ("column_type", data_type),
                        ("character_set_name", None),
                        ("collation_name", None),
                        ("column_key", ""),
                        ("extra", ""),
                        ("generation_expression", ""),
                    )))
                rows.sort(
                    key=lambda item: (
                        item["table_name"],
                        int(item["ordinal_position"]),
                    )
                )
            return _Result(mappings=rows)
        if "FROM information_schema.STATISTICS" in sql:
            return _Result(mappings=())
        if "FROM information_schema.TABLE_CONSTRAINTS" in sql:
            return _Result(mappings=())
        if "FROM information_schema.VIEWS" in sql:
            return _Result(mappings=())
        raise AssertionError("unexpected fixed source-baseline query")

    def exec_driver_sql(self, statement):
        self.transaction = True
        self.driver_statements.append(statement)
        if statement == "SHOW GRANTS FOR CURRENT_USER":
            grants = [
                ("GRANT USAGE ON *.* TO `source_reader`@`%`",),
                (
                    "GRANT SELECT, SHOW VIEW ON "
                    "`inventory_management_test`.* TO `source_reader`@`%`",
                ),
            ]
            if self.broad_grant:
                grants.append(
                    ("GRANT SELECT ON `inventory_management`.* "
                     "TO `source_reader`@`%`",)
                )
            return _Result(rows=grants)
        if statement == "SHOW GRANTS FOR PUBLIC":
            return _Result(rows=())
        if statement == "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY":
            return _Result()
        if statement == "SELECT COUNT(*) FROM `devices`":
            return _Result(scalar=3)
        if statement == "SELECT COUNT(*) FROM `rentals`":
            return _Result(scalar=5)
        if statement == "SELECT COUNT(*) FROM `audit_logs`":
            return _Result(scalar=0)
        normalized = " ".join(statement.split())
        if normalized.startswith("SELECT COUNT(*) FROM `rentals` WHERE"):
            key = (
                "legacy_tracking_rows"
                if "tracking_no" in normalized
                else "legacy_historical_rentals"
            )
            return _Result(scalar=self.historical_counts.get(key, 0))
        if normalized.startswith("SELECT COUNT(*) FROM `audit_logs` WHERE"):
            return _Result(
                scalar=self.historical_counts.get("legacy_print_audits", 0)
            )
        raise AssertionError("unexpected driver SQL")


def _manifest(source_snapshot_digest):
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="source-baseline-v1",
        tenant_uuid=UUID("9a000000-0000-4000-8000-000000000001"),
        database_uuid=UUID("9a000000-0000-4000-8000-000000000002"),
        source_schema_name="inventory_management_test",
        baseline_migration_id="legacy-source-2026-08-23",
        core_plan_revision_uuid=UUID(
            "9a000000-0000-4000-8000-000000000003"
        ),
        control_schema_head="202608220029",
        tenant_schema_head="20260823_shipping_contract",
        source_snapshot_digest=source_snapshot_digest,
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=_digest("display"),
        first_admin_phone_input_commitment=_digest("phone"),
    )


def _invocation(manifest):
    plan = MigrationExecutionPlan(
        phase=MigrationPhase.EXPAND,
        mode=MigrationExecutionMode.APPLY,
        manifest_digest=manifest.digest,
        prerequisites=(),
        completion_conditions=(),
        stop_conditions=(),
        rollback_action="retain expand facts",
        mutations_allowed=True,
    )
    phase_key = "default-migration:" + hashlib.sha256(
        b"default-tenant-migration-phase-v1\x00"
        + manifest.digest
        + b"\x00expand"
    ).hexdigest()
    phase = MigrationPhaseInvocation(
        manifest=manifest,
        plan=plan,
        phase_execution_key=phase_key,
    )
    step_key = "default-step:" + hashlib.sha256(
        b"default-migration-step-v1\x00"
        + phase_key.encode("ascii")
        + b"\x00source_baseline"
    ).hexdigest()
    return DefaultMigrationStepInvocation(
        phase_invocation=phase,
        step_name="source_baseline",
        step_execution_key=step_key,
    )


def test_observer_captures_only_schema_and_row_count_digests():
    connection = _ReadOnlySourceConnection()
    observed = SqlAlchemyDefaultSourceBaselineObserver().observe(
        connection,
        source_schema_name="inventory_management_test",
        baseline_migration_id="legacy-source-2026-08-23",
    )

    assert observed.database_profile == "mariadb-10.11"
    assert observed.table_count == 2
    assert observed.total_rows == 8
    assert observed.source_snapshot_digest not in {
        observed.schema_inventory_digest,
        observed.row_count_digest,
    }
    assert connection.in_transaction() is False
    assert "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY" in (
        connection.driver_statements
    )
    observed.require_manifest(_manifest(observed.source_snapshot_digest))
    assert "source_reader" not in repr(observed)

    document = source_baseline_evidence_to_document(observed)
    assert source_baseline_evidence_from_document(document) == observed
    assert document["source_snapshot_digest"] == (
        observed.source_snapshot_digest.hex()
    )


def test_source_baseline_document_requires_exact_versioned_shape():
    connection = _ReadOnlySourceConnection()
    observed = SqlAlchemyDefaultSourceBaselineObserver().observe(
        connection,
        source_schema_name="inventory_management_test",
        baseline_migration_id="legacy-source-2026-08-23",
    )
    document = source_baseline_evidence_to_document(observed)

    with pytest.raises(DefaultSourceBaselineInputError) as extra:
        source_baseline_evidence_from_document(
            {**document, "database_url": "mysql://must-not-be-accepted"}
        )
    assert "mysql://" not in str(extra.value)

    with pytest.raises(DefaultSourceBaselineInputError):
        source_baseline_evidence_from_document(
            {**document, "format_version": "future-version"}
        )


def test_observer_rejects_broad_grants_before_opening_snapshot():
    connection = _ReadOnlySourceConnection(broad_grant=True)
    with pytest.raises(DefaultSourceBaselineRejected):
        SqlAlchemyDefaultSourceBaselineObserver().observe(
            connection,
            source_schema_name="inventory_management_test",
            baseline_migration_id="legacy-source-2026-08-23",
        )
    assert "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY" not in (
        connection.driver_statements
    )


def test_observer_rejects_schema_drift_during_snapshot():
    with pytest.raises(DefaultSourceBaselineRejected):
        SqlAlchemyDefaultSourceBaselineObserver().observe(
            _ReadOnlySourceConnection(drift=True),
            source_schema_name="inventory_management_test",
            baseline_migration_id="legacy-source-2026-08-23",
        )


def test_bound_verifier_requires_manifest_digest_and_closes_connection():
    first_connection = _ReadOnlySourceConnection()
    first = SqlAlchemyDefaultSourceBaselineObserver().observe(
        first_connection,
        source_schema_name="inventory_management_test",
        baseline_migration_id="legacy-source-2026-08-23",
    )
    bound_connection = _ReadOnlySourceConnection()
    verifier = BoundDefaultSourceBaselineVerifier(
        connection_factory=lambda: bound_connection
    )
    observed = verifier.verify(_invocation(_manifest(first.source_snapshot_digest)))
    assert observed.source_snapshot_digest == first.source_snapshot_digest
    assert bound_connection.closed is True

    mismatch_connection = _ReadOnlySourceConnection()
    mismatch = BoundDefaultSourceBaselineVerifier(
        connection_factory=lambda: mismatch_connection
    )
    with pytest.raises(DefaultSourceBaselineRejected):
        mismatch.verify(_invocation(_manifest(_digest("wrong-source"))))
    assert mismatch_connection.closed is True


def test_atomic_preflight_classifies_empty_and_nonempty_history():
    observer = SqlAlchemyDefaultSourceBaselineObserver()
    empty_connection = _ReadOnlySourceConnection(historical_schema=True)
    baseline, boundary = observer.observe_with_historical_boundary(
        empty_connection,
        source_schema_name="inventory_management_test",
        baseline_migration_id="legacy-source-2026-08-23",
    )

    assert boundary.disposition is HistoricalSnapshotDisposition.EMPTY
    assert dict(boundary.counts) == {
        "legacy_historical_rentals": 0,
        "legacy_print_audits": 0,
        "legacy_tracking_rows": 0,
        "outbound_shipments": 0,
        "provider_operation_attempts": 0,
        "waybill_print_jobs": 0,
    }
    boundary.require_source_baseline(baseline)
    assert empty_connection.in_transaction() is False
    preflight = DefaultSourceMigrationPreflightEvidence(
        source_baseline=baseline,
        historical_boundary=boundary,
    )
    assert source_migration_preflight_from_document(
        source_migration_preflight_to_document(preflight)
    ) == preflight

    nonempty_connection = _ReadOnlySourceConnection(
        historical_schema=True,
        historical_counts={"legacy_tracking_rows": 2},
    )
    nonempty_baseline, nonempty = observer.observe_with_historical_boundary(
        nonempty_connection,
        source_schema_name="inventory_management_test",
        baseline_migration_id="legacy-source-2026-08-23",
    )
    assert nonempty.disposition is (
        HistoricalSnapshotDisposition.REQUIRES_APPROVED_NONEMPTY_ADAPTER
    )
    assert dict(nonempty.counts)["legacy_tracking_rows"] == 2
    nonempty.require_source_baseline(nonempty_baseline)


def test_historical_preflight_rejects_unknown_legacy_shape():
    with pytest.raises(DefaultHistoricalBoundaryRejected):
        SqlAlchemyDefaultSourceBaselineObserver().observe_with_historical_boundary(
            _ReadOnlySourceConnection(
                historical_schema=True,
                missing_lifecycle=True,
            ),
            source_schema_name="inventory_management_test",
            baseline_migration_id="legacy-source-2026-08-23",
        )


def test_bound_preflight_rechecks_manifest_and_closes_connection():
    first_connection = _ReadOnlySourceConnection(historical_schema=True)
    source_baseline, _boundary = (
        SqlAlchemyDefaultSourceBaselineObserver().observe_with_historical_boundary(
            first_connection,
            source_schema_name="inventory_management_test",
            baseline_migration_id="legacy-source-2026-08-23",
        )
    )
    bound_connection = _ReadOnlySourceConnection(historical_schema=True)
    verifier = BoundDefaultSourceMigrationPreflightVerifier(
        connection_factory=lambda: bound_connection
    )

    evidence = verifier.verify(
        _invocation(_manifest(source_baseline.source_snapshot_digest))
    )
    assert evidence.historical_boundary.disposition is (
        HistoricalSnapshotDisposition.EMPTY
    )
    assert bound_connection.closed is True
