"""Opt-in representative non-empty default-tenant D68 migration slice.

The caller restores the approved ``inventory_management`` segment from the
versioned dump into Docker MySQL 8's exact ``inventory_management_test``
schema.  This test then proves the immutable source identity, forward tenant
expand, in-place identity/control registration, metadata-only integrations,
default warehouse, approved express canonicalization, main-authoritative
planned logistics, deterministic structured-address availability, logical
accessories, D68 legacy history, full twelve-scope reconciliation and exact
replay without invoking a provider or printer.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import db
from app.models.accessory_inventory import (
    AccessoryType,
    AccessoryUnit,
    RentalAccessoryRequest,
    RentalAccessoryUnitLink,
)
from app.models.legacy_unattributed_history import (
    LegacyUnattributedPrintSnapshot,
    LegacyUnattributedShipmentSnapshot,
)
from app.models.rental import Rental
from app.models.shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
    WaybillPrintJob,
)
from app.models.warehouse import Warehouse
from app.services.migration import (
    DefaultApplicationEnforcementEvidence,
    DefaultContractEnforcementEvidence,
    DefaultDatabaseJobsEnforcementEvidence,
    DefaultMigrationApplicationEnforcementBundle,
    DefaultMigrationContractEnforcementBundle,
    DefaultMigrationDatabaseJobsEnforcementBundle,
    DefaultSourceBackfillPlanBuilder,
    DefaultTenantInPlaceRegistrationService,
    DefaultTenantRouteRegistration,
    DefaultWarehouseBackfillService,
    DefaultWarehouseProfile,
    ExpressTypeBackfillManifest,
    ExpressTypeBackfillService,
    IntegrationMetadataBackfillEntry,
    IntegrationMetadataBackfillPlan,
    LegacyUnattributedHistoryBackfillService,
    LegacyUnattributedHistoryBoundaryError,
    LegacyUnattributedHistoryConflictError,
    LogicalAccessoryBackfillService,
    ResolvedDefaultMigrationBackfillBundle,
    SqlAlchemyDefaultSourceBaselineObserver,
    TenantSchemaAuthorityFacts,
    VerifiedLegacyUnattributedHistoricalSnapshotsStep,
    build_default_migration_application_enforce_executor,
    build_default_migration_backfill_executor,
    build_default_migration_contract_executor,
    build_default_migration_database_jobs_enforce_executor,
    build_express_type_source_snapshot,
    tenant_database_identity_digest,
)
from inventory_control import ControlBase
from inventory_control.crypto import RootKey
from inventory_control.default_migration import (
    DefaultLegacyAuthorityBoundaryEvidence,
    DefaultLegacyDoubleCountCollector,
    DefaultMigrationCommand,
    DefaultMigrationReconciliationRunner,
    DefaultMigrationStepResult,
    DefaultTenantMigrationManifest,
    DefaultTenantReconciliationExpectedFacts,
    DefaultTenantReconciliationSqlRegistry,
    HistoricalSnapshotDisposition,
    MigrationJournalFileStore,
    MigrationPhase,
    OrderedDefaultMigrationPhaseExecutor,
    bind_default_tenant_identity_inputs,
    build_default_migration_bundle_evidence,
    build_default_tenant_reconciliation_policy,
    compose_default_tenant_reconciliation_collectors,
)
from inventory_control.models import (
    PlanRevision,
    Subscription,
    SubscriptionEvent,
    Tenant,
    TenantDatabase,
    TenantIntegration,
    TenantIntegrationSecretRevision,
)
from inventory_control.subscriptions import parse_core_entitlements
from tests.support.default_backfill import CurrentTestSchemaCollector
from tests.support.test_database import (
    assert_test_database_url,
    guarded_mysql_test_schema_migration,
    observe_test_database_schema,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TENANT_MIGRATIONS = PROJECT_ROOT / "migrations"
TENANT_HEAD = "20260824_legacy_history"
BASELINE_MIGRATION_ID = "representative-backup-20260824-080001-v1"
SOURCE_READER_URL_ENV = "DEFAULT_SOURCE_BASELINE_TEST_URL"
TENANT_UUID = UUID("95000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("95000000-0000-4000-8000-000000000002")
PLAN_UUID = UUID("95000000-0000-4000-8000-000000000003")
NOW = datetime(2026, 8, 24, 8, 0, 1, tzinfo=timezone.utc)

EXPECTED_SOURCE_SCHEMA_DIGEST = bytes.fromhex("4a26bfa5b6c55c85d9d8302bf42c1df9973dd1f3b78c6de3b670f1f70712b093")
EXPECTED_SOURCE_ROW_COUNT_DIGEST = bytes.fromhex("f2ce83bbc0636959eda51edb2a5ccacf51af45b4ae798b825e306bb36480f3dc")
EXPECTED_SOURCE_SNAPSHOT_DIGEST = bytes.fromhex("2c03aaad9323dfe788113ce2cbd19ab302ecf21f2451dc76c7291fe5ea592313")
EXPECTED_BOUNDARY_COUNTS = (
    ("legacy_historical_rentals", 2100),
    ("legacy_print_audits", 0),
    ("legacy_tracking_rows", 2079),
    ("outbound_shipments", 0),
    ("provider_operation_attempts", 0),
    ("waybill_print_jobs", 0),
)

_ENABLED = (
    os.environ.get("RUN_REPRESENTATIVE_DEFAULT_MIGRATION_TESTS", "").lower() == "true"
    and os.environ.get("ALLOW_REAL_TEST_DATABASE", "").lower() == "true"
    and bool(os.environ.get("TEST_DATABASE_URL"))
    and bool(os.environ.get(SOURCE_READER_URL_ENV))
)
pytestmark = pytest.mark.skipif(
    not _ENABLED,
    reason=("representative migration requires explicit opt-in plus exact writer " "and source-reader URLs"),
)


def test_representative_nonempty_legacy_history_migrates_and_reconciles(tmp_path):
    writer_url = assert_test_database_url(os.environ["TEST_DATABASE_URL"])
    reader_url = make_url(os.environ[SOURCE_READER_URL_ENV])
    if reader_url.get_backend_name() != "mysql" or reader_url.database != "inventory_management_test":
        pytest.fail("representative source reader must select the exact test DB")

    writer = sa.create_engine(writer_url.render_as_string(hide_password=False))
    reader = sa.create_engine(reader_url.render_as_string(hide_password=False))
    try:
        source_baseline, historical_boundary = _observe_source(reader)
        replay_baseline, replay_boundary = _observe_source(reader)
        assert (replay_baseline, replay_boundary) == (
            source_baseline,
            historical_boundary,
        )
        _assert_expected_source(source_baseline, historical_boundary)
        source_facts = _source_facts(reader)

        bundle = build_default_migration_bundle_evidence(PROJECT_ROOT)
        identity_inputs = bind_default_tenant_identity_inputs(
            root_key=RootKey(version=1, material=bytes(range(32))),
            tenant_uuid=TENANT_UUID,
            database_uuid=DATABASE_UUID,
            migration_idempotency_key=BASELINE_MIGRATION_ID,
            display_name="默认租户代表性迁移演练",
            first_admin_phone="13800138000",
        )
        manifest = _manifest(
            bundle=bundle,
            identity_inputs=identity_inputs,
        )
        source_baseline.require_manifest(manifest)
        historical_boundary.require_manifest(manifest)
        bundle.require_manifest(manifest)
        initial_schema = observe_test_database_schema(
            writer.url,
            lambda _parsed: writer.connect(),
        )
        context = _RepresentativeMigrationContext()
        journal_store = MigrationJournalFileStore(tmp_path / "journal.json")
        journal_store.initialize(manifest)
        command_runner = DefaultMigrationCommand(
            journal_store,
            executors=_representative_executors(
                writer=writer,
                reader_url=reader_url,
                writer_url=writer_url,
                initial_schema_digest=initial_schema.preflight_digest,
                identity_inputs=identity_inputs,
                manifest=manifest,
                historical_boundary=historical_boundary,
                source_facts=source_facts,
                journal_store=journal_store,
                context=context,
            ),
            clock=lambda: NOW,
        )

        first_run = command_runner.run_to_authoritative_boundary(manifest)
        assert tuple(item.phase for item in first_run.runs) == (
            MigrationPhase.EXPAND,
            MigrationPhase.BACKFILL_VERIFY,
            MigrationPhase.APPLICATION_ENFORCE,
            MigrationPhase.DATABASE_JOBS_ENFORCE,
        )
        assert first_run.journal.next_phase is MigrationPhase.CONTRACT
        assert first_run.journal.tenant_aware_writes_enabled_at is None
        assert first_run.journal.legacy_rollback_allowed is True
        replay_run = command_runner.run_to_authoritative_boundary(manifest)
        assert replay_run.runs == ()
        assert replay_run.journal == first_run.journal

        assert context.plans is not None
        assert dict(context.plans.audit.safe_summary()) == {
            "active_main_rental_count": 262,
            "linked_logical_request_count": 8,
            "logical_request_count": 24,
            "logical_unit_count": 12,
            "logistics_source_counts": {
                "legacy_ship_out": 257,
                "legacy_ship_in": 1,
                "scheduled_ship": 0,
                "legacy_ui_1": 4,
            },
            "policy_revision": 1,
            "reliable_logical_unit_count": 8,
            "structured_address_count": 178,
            "unavailable_address_count": 84,
            "unavailable_logical_unit_count": 4,
        }
        assert context.backfill_result is not None
        report = context.backfill_result.reconciliation_report
        assert report is not None and report.passed is True
        assert all(finding.blocking is False for finding in report.findings)
        assert context.factory is not None
        _assert_application_enforced(context.factory, manifest=manifest)
        _assert_express_type_completed(context.factory)
        _assert_zero_anomalies(context.factory, manifest=manifest)
        _assert_source_drift_is_rejected(
            context.factory,
            manifest=manifest,
            historical_boundary=historical_boundary,
        )
        _assert_core_ledger_is_rejected(
            context.factory,
            manifest=manifest,
            historical_boundary=historical_boundary,
        )
        _assert_zero_anomalies(context.factory, manifest=manifest)
    finally:
        reader.dispose()
        writer.dispose()


def _observe_source(engine):
    observer = SqlAlchemyDefaultSourceBaselineObserver()
    with engine.connect() as connection:
        return observer.observe_with_historical_boundary(
            connection,
            source_schema_name="inventory_management_test",
            baseline_migration_id=BASELINE_MIGRATION_ID,
        )


def _assert_expected_source(source_baseline, historical_boundary) -> None:
    assert source_baseline.database_profile == "mysql-8.0.30+"
    assert source_baseline.server_version == "8.0.46"
    assert source_baseline.table_count == 12
    assert source_baseline.total_rows == 8536
    assert source_baseline.schema_inventory_digest == (EXPECTED_SOURCE_SCHEMA_DIGEST)
    assert source_baseline.row_count_digest == EXPECTED_SOURCE_ROW_COUNT_DIGEST
    assert source_baseline.source_snapshot_digest == (EXPECTED_SOURCE_SNAPSHOT_DIGEST)
    assert historical_boundary.counts == EXPECTED_BOUNDARY_COUNTS
    assert historical_boundary.disposition is (HistoricalSnapshotDisposition.REQUIRES_APPROVED_NONEMPTY_ADAPTER)


class _SourceFacts:
    __slots__ = (
        "device_rows",
        "historical_waybills",
        "rental_device_links",
        "rental_total_minor",
    )

    def __init__(
        self,
        *,
        device_rows: int,
        historical_waybills: int,
        rental_device_links: int,
        rental_total_minor: int,
    ) -> None:
        self.device_rows = device_rows
        self.historical_waybills = historical_waybills
        self.rental_device_links = rental_device_links
        self.rental_total_minor = rental_total_minor


def _source_facts(engine) -> _SourceFacts:
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT "
            "(SELECT COUNT(*) FROM devices), "
            "(SELECT COUNT(*) FROM rentals "
            " WHERE ship_out_tracking_no IS NOT NULL), "
            "(SELECT COUNT(*) FROM rentals AS r "
            " JOIN devices AS d ON d.id = r.device_id), "
            "(SELECT CAST(COALESCE(SUM(CAST(COALESCE(order_amount, 0) "
            " * 100 AS SIGNED)), 0) AS SIGNED) FROM rentals)"
        ).one()
    values = tuple(row)
    assert all(isinstance(value, int) and value >= 0 for value in values)
    return _SourceFacts(
        device_rows=values[0],
        historical_waybills=values[1],
        rental_device_links=values[2],
        rental_total_minor=values[3],
    )


def _expand_control_and_tenant(connection) -> None:
    ControlBase.metadata.create_all(bind=connection)
    config = Config(str(TENANT_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(TENANT_MIGRATIONS))
    config.attributes["connection"] = connection
    config.attributes["target_metadata"] = db.metadata
    command.upgrade(config, TENANT_HEAD)
    connection.commit()
    assert MigrationContext.configure(connection).get_current_revision() == (TENANT_HEAD)


def _manifest(*, bundle, identity_inputs) -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key=BASELINE_MIGRATION_ID,
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        source_schema_name="inventory_management_test",
        baseline_migration_id=BASELINE_MIGRATION_ID,
        core_plan_revision_uuid=PLAN_UUID,
        control_schema_head=bundle.control_schema_head,
        tenant_schema_head=bundle.tenant_schema_head,
        source_snapshot_digest=EXPECTED_SOURCE_SNAPSHOT_DIGEST,
        implementation_identity_digest=_digest("git:34a6201644a90ea2a3a80b7975d00ccd0af28a35"),
        migration_bundle_digest=bundle.bundle_digest,
        display_name_input_commitment=(identity_inputs.display_name_commitment),
        first_admin_phone_input_commitment=(identity_inputs.first_admin_phone_commitment),
    )


class _RepresentativeMigrationContext:
    __slots__ = (
        "backfill_result",
        "factory",
        "identity_created_at",
        "plans",
        "schema_digest",
    )

    def __init__(self) -> None:
        self.backfill_result = None
        self.factory = None
        self.identity_created_at = None
        self.plans = None
        self.schema_digest = None

    def new_session(self):
        assert self.factory is not None
        return self.factory()


class _StaticVerifier:
    def __init__(self, evidence) -> None:
        self._evidence = evidence

    def verify(self, _invocation):
        return self._evidence


class _RepresentativeExpandStep:
    name = "representative_expand"

    def __init__(
        self,
        *,
        writer,
        writer_url,
        reader_url,
        initial_schema_digest,
        identity_inputs,
        context,
    ) -> None:
        self._writer = writer
        self._writer_url = writer_url
        self._reader_url = reader_url
        self._initial_schema_digest = initial_schema_digest
        self._identity_inputs = identity_inputs
        self._context = context

    def execute(self, invocation):
        manifest = invocation.phase_invocation.manifest
        with guarded_mysql_test_schema_migration(
            self._writer,
            expected_preflight_digest=self._initial_schema_digest,
        ) as (migration_connection, pinned_schema):
            assert pinned_schema.preflight_digest == self._initial_schema_digest
            _expand_control_and_tenant(migration_connection)

        factory = sessionmaker(bind=self._writer, expire_on_commit=False)
        registration = DefaultTenantInPlaceRegistrationService(clock=lambda: NOW)
        tenant_identity = _write_tenant_identity(
            factory,
            registration=registration,
            manifest=manifest,
        )
        replay_identity = _write_tenant_identity(
            factory,
            registration=registration,
            manifest=manifest,
        )
        assert tenant_identity.created is True
        assert replay_identity.created is False
        assert replay_identity.identity_created_at == tenant_identity.identity_created_at

        expanded_schema = observe_test_database_schema(
            self._writer.url,
            lambda _parsed: self._writer.connect(),
        )
        assert expanded_schema.alembic_versions == (TENANT_HEAD,)
        assert expanded_schema.identity_generations == ((1, 1),)
        assert expanded_schema.is_drifted is False
        schema_digest = bytes.fromhex(expanded_schema.preflight_digest)
        assert self._writer_url.username != self._reader_url.username
        route = DefaultTenantRouteRegistration(
            database_instance_key="docker-mysql8-representative",
            schema_generation=1,
            schema_digest=schema_digest,
            dml_username=self._writer_url.username,
            dml_credential_generation=1,
            dml_root_key_version=1,
            dml_derivation_version=1,
            platform_read_username=self._reader_url.username,
            platform_read_credential_generation=1,
            platform_read_root_key_version=1,
            platform_read_derivation_version=1,
        )
        first_control = _write_control_registration(
            factory,
            registration=registration,
            manifest=manifest,
            identity_inputs=self._identity_inputs,
            tenant_identity=tenant_identity,
            route=route,
        )
        replay_control = _write_control_registration(
            factory,
            registration=registration,
            manifest=manifest,
            identity_inputs=self._identity_inputs,
            tenant_identity=replay_identity,
            route=route,
        )
        assert first_control.created is True
        assert replay_control.created is False
        _ensure_core_plan(factory)

        self._context.factory = factory
        self._context.identity_created_at = tenant_identity.identity_created_at
        self._context.schema_digest = schema_digest
        return DefaultMigrationStepResult(
            step_name=self.name,
            manifest_digest=manifest.digest,
            result_digest=hashlib.sha256(
                schema_digest
                + tenant_database_identity_digest(
                    tenant_uuid=manifest.tenant_uuid,
                    database_uuid=manifest.database_uuid,
                    created_at=tenant_identity.identity_created_at,
                    schema_generation=1,
                )
            ).digest(),
            executor_reference="representative-expand",
        )


class _RepresentativeBackfillExecutor:
    def __init__(
        self,
        *,
        writer,
        historical_boundary,
        source_facts,
        context,
    ) -> None:
        self._writer = writer
        self._historical_boundary = historical_boundary
        self._source_facts = source_facts
        self._context = context

    def execute(self, invocation):
        manifest = invocation.manifest
        factory = self._context.factory
        identity_created_at = self._context.identity_created_at
        schema_digest = self._context.schema_digest
        assert factory is not None
        assert identity_created_at is not None
        assert schema_digest is not None

        warehouse = _backfill_default_warehouse(factory, manifest)
        assert len(warehouse.assigned_device_ids) == self._source_facts.device_rows
        plans = _build_source_plans(factory, manifest, warehouse.warehouse_id)
        express_manifest, express_service = _express_type_inputs(
            factory,
            manifest=manifest,
            identity_created_at=identity_created_at,
            schema_digest=schema_digest,
        )
        policy, runner, sessions = _reconciliation_inputs(
            writer=self._writer,
            factory=factory,
            manifest=manifest,
            source_facts=self._source_facts,
            schema_digest=schema_digest,
            accessory_links=plans.audit.linked_logical_request_count,
        )
        try:
            executor = build_default_migration_backfill_executor(
                bundle=ResolvedDefaultMigrationBackfillBundle(
                    tenant_session_factory=factory,
                    control_session_factory=factory,
                    expected_schema_generation=1,
                    warehouse_profile=DefaultWarehouseProfile(),
                    express_type_manifest=express_manifest,
                    planned_logistics_plan=plans.planned_logistics,
                    structured_address_plan=plans.structured_addresses,
                    logical_accessory_plan=plans.logical_accessories,
                    integration_metadata_plan=_integration_metadata_plan(manifest),
                    express_type_service=express_service,
                    logical_accessory_service=LogicalAccessoryBackfillService(clock=lambda: NOW),
                ),
                historical_boundary=self._historical_boundary,
                historical_snapshot_step=(
                    VerifiedLegacyUnattributedHistoricalSnapshotsStep(
                        tenant_session_factory=factory,
                        expected_schema_generation=1,
                        historical_boundary=self._historical_boundary,
                        approved_historical_boundary_digest=(self._historical_boundary.digest),
                    )
                ),
                policy=policy,
                reconciliation_runner=runner,
            )
            first = executor.execute(invocation)
            replay = executor.execute(invocation)
            assert replay.input_state_digest == first.input_state_digest
            assert replay.result_state_digest == first.result_state_digest
            assert replay.executor_reference == first.executor_reference
            self._context.plans = plans
            self._context.backfill_result = first
            return first
        finally:
            for session in reversed(sessions):
                session.close()


def _representative_executors(
    *,
    writer,
    writer_url,
    reader_url,
    initial_schema_digest,
    identity_inputs,
    manifest,
    historical_boundary,
    source_facts,
    journal_store,
    context,
):
    expand = OrderedDefaultMigrationPhaseExecutor(
        phase=MigrationPhase.EXPAND,
        steps=(
            _RepresentativeExpandStep(
                writer=writer,
                writer_url=writer_url,
                reader_url=reader_url,
                initial_schema_digest=initial_schema_digest,
                identity_inputs=identity_inputs,
                context=context,
            ),
        ),
    )
    application_evidence = DefaultApplicationEnforcementEvidence(
        manifest_digest=manifest.digest,
        implementation_identity_digest=manifest.implementation_identity_digest,
        migration_bundle_digest=manifest.migration_bundle_digest,
        trusted_route_matrix_digest=_digest("representative-trusted-route"),
        identity_namespace_matrix_digest=_digest("representative-namespace"),
        effective_gate_matrix_digest=_digest("representative-gates"),
        legacy_surface_negative_digest=_digest("representative-legacy-negative"),
    )
    database_jobs_evidence = DefaultDatabaseJobsEnforcementEvidence(
        manifest_digest=manifest.digest,
        implementation_identity_digest=manifest.implementation_identity_digest,
        migration_bundle_digest=manifest.migration_bundle_digest,
        database_grants_matrix_digest=_digest("representative-grants"),
        schema_fleet_matrix_digest=_digest("representative-schema-fleet"),
        scheduler_negative_matrix_digest=_digest("representative-scheduler"),
        durable_worker_matrix_digest=_digest("representative-worker"),
        outbox_provider_fence_matrix_digest=_digest("representative-outbox"),
        cross_schema_negative_matrix_digest=_digest("representative-cross-schema"),
    )
    contract_evidence = DefaultContractEnforcementEvidence(
        manifest_digest=manifest.digest,
        implementation_identity_digest=manifest.implementation_identity_digest,
        migration_bundle_digest=manifest.migration_bundle_digest,
        observation_window_digest=_digest("representative-observation"),
        legacy_schema_surface_negative_digest=_digest("representative-schema"),
        route_config_bundle_negative_digest=_digest("representative-route-config"),
        recovery_path_negative_digest=_digest("representative-recovery"),
        provider_snapshot_preservation_digest=_digest("representative-snapshots"),
    )
    return {
        MigrationPhase.EXPAND: expand,
        MigrationPhase.BACKFILL_VERIFY: _RepresentativeBackfillExecutor(
            writer=writer,
            historical_boundary=historical_boundary,
            source_facts=source_facts,
            context=context,
        ),
        MigrationPhase.APPLICATION_ENFORCE: (
            build_default_migration_application_enforce_executor(
                bundle=DefaultMigrationApplicationEnforcementBundle(
                    control_session_factory=context.new_session,
                    journal_store=journal_store,
                    verifier=_StaticVerifier(application_evidence),
                )
            )
        ),
        MigrationPhase.DATABASE_JOBS_ENFORCE: (
            build_default_migration_database_jobs_enforce_executor(
                bundle=DefaultMigrationDatabaseJobsEnforcementBundle(verifier=_StaticVerifier(database_jobs_evidence))
            )
        ),
        MigrationPhase.CONTRACT: build_default_migration_contract_executor(
            bundle=DefaultMigrationContractEnforcementBundle(verifier=_StaticVerifier(contract_evidence))
        ),
    }


def _write_tenant_identity(factory, *, registration, manifest):
    with factory.begin() as session:
        return registration.write_tenant_database_identity(
            session,
            manifest=manifest,
            schema_generation=1,
        )


def _write_control_registration(
    factory,
    *,
    registration,
    manifest,
    identity_inputs,
    tenant_identity,
    route,
):
    with factory.begin() as session:
        return registration.write_control_registration(
            session,
            manifest=manifest,
            identity_inputs=identity_inputs,
            tenant_identity=tenant_identity,
            route=route,
        )


def _ensure_core_plan(factory) -> None:
    entitlements = {
        "features": {"xianyu_sync": True},
        "limits": {"member_seats": 10},
    }
    snapshot = parse_core_entitlements(
        schema_version=1,
        entitlements=entitlements,
    )
    with factory.begin() as session:
        existing = session.get(PlanRevision, str(PLAN_UUID))
        if existing is None:
            session.add(
                PlanRevision(
                    id=str(PLAN_UUID),
                    code="core",
                    revision=1,
                    name="Core",
                    entitlements_schema_version=1,
                    entitlements_json=entitlements,
                    entitlements_digest=snapshot.digest_sha256,
                    active=True,
                )
            )
        else:
            assert existing.entitlements_digest == snapshot.digest_sha256


def _backfill_default_warehouse(factory, manifest):
    with factory.begin() as session:
        return DefaultWarehouseBackfillService().backfill(
            session,
            tenant_uuid=manifest.tenant_uuid,
            database_uuid=manifest.database_uuid,
            expected_schema_generation=1,
            baseline_migration_id=manifest.baseline_migration_id,
            profile=DefaultWarehouseProfile(),
        )


def _build_source_plans(factory, manifest, warehouse_id):
    with factory() as session:
        return DefaultSourceBackfillPlanBuilder().build(
            session,
            manifest=manifest,
            expected_warehouse_id=warehouse_id,
        )


def _integration_metadata_plan(manifest):
    return IntegrationMetadataBackfillPlan(
        parent_manifest_digest=manifest.digest,
        migration_idempotency_key=manifest.migration_idempotency_key,
        entries=tuple(
            IntegrationMetadataBackfillEntry(provider=provider, name=name, config={})
            for provider, name in (
                ("kuaimai", "默认快麦"),
                ("sf", "默认顺丰"),
                ("xianyu", "默认闲鱼"),
            )
        ),
    )


def _express_type_inputs(
    factory,
    *,
    manifest,
    identity_created_at,
    schema_digest,
):
    with factory() as session:
        rows = tuple(
            tuple(row) for row in session.execute(sa.select(Rental.id, Rental.express_type_id).order_by(Rental.id))
        )
    source_snapshot = build_express_type_source_snapshot(
        rows,
        legacy_6_to_2_rental_ids=(778,),
    )
    assert dict(source_snapshot.state_counts) == {
        "canonical_1": 0,
        "canonical_2": 2089,
        "canonical_263": 12,
        "historical_null": 2,
        "legacy_6": 1,
        "unsupported": 0,
    }
    express_manifest = ExpressTypeBackfillManifest(
        migration_idempotency_key=(f"{manifest.migration_idempotency_key}.express-type.v2"),
        parent_manifest_digest=manifest.digest,
        tenant_uuid=manifest.tenant_uuid,
        database_uuid=manifest.database_uuid,
        schema_generation=1,
        tenant_identity_digest=tenant_database_identity_digest(
            tenant_uuid=manifest.tenant_uuid,
            database_uuid=manifest.database_uuid,
            created_at=identity_created_at,
            schema_generation=1,
        ),
        schema_revision=TENANT_HEAD,
        schema_digest=schema_digest,
        source_snapshot=source_snapshot,
        legacy_6_to_2_rental_ids=(778,),
    )
    facts = TenantSchemaAuthorityFacts(
        tenant_uuid=manifest.tenant_uuid,
        database_uuid=manifest.database_uuid,
        schema_generation=1,
        schema_revision=TENANT_HEAD,
        schema_digest=schema_digest,
    )

    return express_manifest, ExpressTypeBackfillService(lambda _session, _identity: facts)


def _assert_express_type_completed(factory) -> None:
    with factory() as session:
        rows = tuple(
            tuple(row) for row in session.execute(sa.select(Rental.id, Rental.express_type_id).order_by(Rental.id))
        )
    snapshot = build_express_type_source_snapshot(rows)
    assert snapshot.total_count == 2104
    assert dict(snapshot.state_counts) == {
        "canonical_1": 0,
        "canonical_2": 2092,
        "canonical_263": 12,
        "historical_null": 0,
        "legacy_6": 0,
        "unsupported": 0,
    }


def _reconciliation_inputs(
    *,
    writer,
    factory,
    manifest,
    source_facts,
    schema_digest,
    accessory_links,
):
    policy = build_default_tenant_reconciliation_policy(
        DefaultTenantReconciliationExpectedFacts(
            accessory_links=accessory_links,
            credential_revisions=0,
            device_warehouse_links=source_facts.device_rows,
            legacy_double_count=0,
            rental_total_minor=source_facts.rental_total_minor,
            orphan_count=0,
            rental_device_links=source_facts.rental_device_links,
            schema_digest=schema_digest,
            schema_generation=1,
            historical_waybills=source_facts.historical_waybills,
            device_rows=source_facts.device_rows,
            default_warehouse_count=1,
        )
    )
    tenant_session = factory(autoflush=False)
    control_session = factory(autoflush=False)
    registry = DefaultTenantReconciliationSqlRegistry(
        manifest=manifest,
        tenant_session=tenant_session,
        control_session=control_session,
    )
    collectors = compose_default_tenant_reconciliation_collectors(
        policy=policy,
        sql_registry=registry,
        supplemental_collectors=(
            DefaultLegacyDoubleCountCollector(_legacy_authority_evidence(manifest)),
            CurrentTestSchemaCollector("schema.digest", writer),
            CurrentTestSchemaCollector("schema.generation", writer),
        ),
    )
    return (
        policy,
        DefaultMigrationReconciliationRunner(collectors),
        (tenant_session, control_session),
    )


def _legacy_authority_evidence(manifest):
    return DefaultLegacyAuthorityBoundaryEvidence(
        manifest_digest=manifest.digest,
        source_snapshot_digest=manifest.source_snapshot_digest,
        implementation_identity_digest=(manifest.implementation_identity_digest),
        migration_bundle_digest=manifest.migration_bundle_digest,
        legacy_quantity_negative_digest=_digest("quantity-negative"),
        legacy_child_rental_negative_digest=_digest("child-negative"),
        legacy_global_provider_negative_digest=_digest("provider-negative"),
        legacy_shipment_writer_negative_digest=_digest("shipment-negative"),
    )


def _assert_application_enforced(factory, *, manifest) -> None:
    tenant_id = str(manifest.tenant_uuid)
    with factory() as session:
        tenant = session.get(Tenant, tenant_id)
        route = session.scalar(sa.select(TenantDatabase).where(TenantDatabase.tenant_id == tenant_id))
        subscription = session.scalar(sa.select(Subscription).where(Subscription.tenant_id == tenant_id))
        events = tuple(
            session.scalars(
                sa.select(SubscriptionEvent)
                .where(SubscriptionEvent.tenant_id == tenant_id)
                .order_by(SubscriptionEvent.created_at, SubscriptionEvent.id)
            )
        )
    assert tenant is not None and tenant.status == "active"
    assert route is not None and route.status == "ready"
    assert subscription is not None
    assert subscription.plan_revision_uuid == str(PLAN_UUID)
    assert subscription.entitlements_json["limits"]["member_seats"] == 10
    assert len(events) == 1
    assert events[0].event_type == "migration_granted"
    assert events[0].source_type == "migration_grant"


def _assert_zero_anomalies(factory, *, manifest) -> None:
    with factory() as session:
        duplicate_shipments = session.scalar(
            sa.select(sa.func.count()).select_from(
                sa.select(LegacyUnattributedShipmentSnapshot.source_rental_id)
                .group_by(LegacyUnattributedShipmentSnapshot.source_rental_id)
                .having(sa.func.count() > 1)
                .subquery()
            )
        )
        duplicate_prints = session.scalar(
            sa.select(sa.func.count()).select_from(
                sa.select(LegacyUnattributedPrintSnapshot.source_audit_id)
                .group_by(LegacyUnattributedPrintSnapshot.source_audit_id)
                .having(sa.func.count() > 1)
                .subquery()
            )
        )
        orphan_shipments = session.scalar(
            sa.select(sa.func.count())
            .select_from(LegacyUnattributedShipmentSnapshot)
            .outerjoin(
                Rental,
                Rental.id == LegacyUnattributedShipmentSnapshot.rental_id,
            )
            .where(Rental.id.is_(None))
        )
        core_counts = tuple(
            session.scalar(sa.select(sa.func.count()).select_from(model))
            for model in (
                OutboundShipment,
                ProviderOperationAttempt,
                WaybillPrintJob,
            )
        )
        revision_count = session.scalar(
            sa.select(sa.func.count())
            .select_from(TenantIntegrationSecretRevision)
            .where(TenantIntegrationSecretRevision.tenant_id == str(manifest.tenant_uuid))
        )
        integrations = tuple(
            session.scalars(
                sa.select(TenantIntegration).where(TenantIntegration.tenant_id == str(manifest.tenant_uuid))
            )
        )
        accessory_counts = tuple(
            session.scalar(sa.select(sa.func.count()).select_from(model))
            for model in (
                AccessoryType,
                AccessoryUnit,
                RentalAccessoryRequest,
                RentalAccessoryUnitLink,
            )
        )
    assert (duplicate_shipments, duplicate_prints, orphan_shipments) == (0, 0, 0)
    assert core_counts == (0, 0, 0)
    assert revision_count == 0
    assert len(integrations) == 3
    assert all(item.current_secret_revision_id is None for item in integrations)
    assert accessory_counts == (2, 12, 24, 8)


def _assert_source_drift_is_rejected(
    factory,
    *,
    manifest,
    historical_boundary,
) -> None:
    with factory() as session:
        rental_id = session.scalar(
            sa.select(Rental.id).where(Rental.ship_out_tracking_no.is_not(None)).order_by(Rental.id).limit(1)
        )
    assert isinstance(rental_id, int)
    with pytest.raises(LegacyUnattributedHistoryConflictError), factory.begin() as session:
        session.execute(
            sa.update(Rental).where(Rental.id == rental_id).values(ship_out_tracking_no="D68-DRIFT-NEGATIVE")
        )
        LegacyUnattributedHistoryBackfillService().backfill(
            session,
            manifest=manifest,
            expected_schema_generation=1,
            historical_boundary=historical_boundary,
        )


def _assert_core_ledger_is_rejected(
    factory,
    *,
    manifest,
    historical_boundary,
) -> None:
    with factory() as session:
        rental_id = session.scalar(sa.select(Rental.id).order_by(Rental.id).limit(1))
        warehouse = session.scalar(sa.select(Warehouse).where(Warehouse.is_default.is_(True)))
    assert isinstance(rental_id, int)
    assert warehouse is not None
    with pytest.raises(LegacyUnattributedHistoryBoundaryError), factory.begin() as session:
        session.execute(
            sa.insert(OutboundShipment).values(
                id="95000000-0000-4000-8000-000000000010",
                provider="sf",
                rental_id=rental_id,
                origin_warehouse_id=warehouse.id,
                origin_warehouse_uuid=warehouse.warehouse_uuid,
                integration_uuid="95000000-0000-4000-8000-000000000011",
                provider_account_uuid="95000000-0000-4000-8000-000000000012",
                integration_secret_revision_uuid=("95000000-0000-4000-8000-000000000013"),
                provider_account_secret_revision_uuid=("95000000-0000-4000-8000-000000000014"),
                binding_revision=1,
                account_masked_hint="negative-only",
                sender_snapshot={},
                receiver_snapshot={},
                cargo_snapshot={"items": []},
                tracking_check_phone_last4="0000",
                express_type_id=2,
                scheduled_dispatch_at=NOW.replace(tzinfo=None),
                provider_order_id="D68-NEGATIVE-ONLY",
                request_hash="0" * 64,
                status="prepared",
                prepared_at=NOW.replace(tzinfo=None),
                created_at=NOW.replace(tzinfo=None),
                updated_at=NOW.replace(tzinfo=None),
            )
        )
        LegacyUnattributedHistoryBackfillService().backfill(
            session,
            manifest=manifest,
            expected_schema_generation=1,
            historical_boundary=historical_boundary,
        )


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()
