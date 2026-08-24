"""Reusable complete default-backfill composition on the approved MySQL schema."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.accessory_inventory import AccessoryType, AccessoryUnit
from app.models.database_identity import TenantDatabaseIdentity
from app.models.device import Device
from app.models.rental import Rental
from app.models.warehouse import Warehouse
from app.services.migration import (
    DefaultWarehouseProfile,
    ExpressTypeBackfillManifest,
    ExpressTypeBackfillService,
    IntegrationMetadataBackfillEntry,
    IntegrationMetadataBackfillPlan,
    LegacyAccessoryUnitEntry,
    LogicalAccessoryBackfillPlan,
    PlannedLogisticsBackfillEntry,
    PlannedLogisticsBackfillPlan,
    ResolvedDefaultMigrationBackfillBundle,
    StructuredAddressBackfillPlan,
    StructuredRentalAddressEntry,
    TenantSchemaAuthorityFacts,
    VerifiedEmptyHistoricalSnapshotsStep,
    build_default_migration_backfill_executor,
    build_express_type_source_snapshot,
    legacy_destination_digest,
    tenant_database_identity_digest,
)
from inventory_control.default_migration import (
    DefaultLegacyAuthorityBoundaryEvidence,
    DefaultLegacyDoubleCountCollector,
    DefaultMigrationReconciliationRunner,
    MigrationReconciliationCollectionError,
    MigrationReconciliationBlockedError,
    DefaultTenantMigrationManifest,
    DefaultTenantReconciliationExpectedFacts,
    DefaultTenantReconciliationSqlRegistry,
    MigrationExecutionMode,
    MigrationExecutionPlan,
    MigrationPhase,
    MigrationPhaseInvocation,
    ReconciliationObservation,
    build_default_tenant_reconciliation_policy,
    compose_default_tenant_reconciliation_collectors,
)
from inventory_control.models import Tenant, TenantIntegration
from tests.support.test_database import preflight_test_database_write


TENANT_UUID = UUID("8b000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("8b000000-0000-4000-8000-000000000002")
PLAN_UUID = UUID("8b000000-0000-4000-8000-000000000003")
TENANT_HEAD = "20260824_legacy_history"
TENANT_BASELINE = "20260807_damage_notes"
SCHEMA_GENERATION = 2
NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class CompleteBackfillObservation:
    result_digest: bytes
    replay_result_digest: bytes
    device_rows: int
    device_warehouse_links: int
    default_warehouse_count: int
    logical_unit_count: int
    integration_count: int
    credential_revision_count: int
    rental_express_type_id: int
    schema_generation: int
    schema_digest: bytes
    crash_resume_verified: bool


@dataclass(frozen=True, slots=True)
class _SeededTenant:
    identity_created_at: datetime
    main_device_id: int
    accessory_device_id: int
    accessory_type_id: int
    rental_id: int


class _InjectedBackfillCrash(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _CrashAfterCommittedStep:
    step: object

    @property
    def name(self) -> str:
        return self.step.name

    def execute(self, invocation):
        self.step.execute(invocation)
        raise _InjectedBackfillCrash()


@dataclass(frozen=True, slots=True)
class _CurrentTestSchemaCollector:
    """Re-observe the one approved test schema after backfill mutations."""

    key: str
    engine: Engine

    def collect(self, *, manifest, requirement):
        if manifest != _manifest() or requirement.key != self.key:
            raise MigrationReconciliationCollectionError()
        preflight = _test_schema_preflight(self.engine)
        if self.key == "schema.generation":
            observed = _schema_generation(preflight)
        elif self.key == "schema.digest":
            observed = bytes.fromhex(preflight.preflight_digest)
        else:
            raise MigrationReconciliationCollectionError()
        return ReconciliationObservation(key=self.key, observed=observed)


def run_complete_default_backfill_composition(
    *,
    engine: Engine,
) -> CompleteBackfillObservation:
    """Execute every resolved backfill plus empty-history verification twice."""

    if (
        not isinstance(engine, Engine)
        or engine.dialect.name != "mysql"
    ):
        raise TypeError("complete backfill requires one bound MySQL engine")
    _install_tenant_revision(engine)
    manifest = _manifest()
    seeded = _seed_databases(
        tenant_engine=engine,
        control_engine=engine,
    )
    tenant_factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )
    control_factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    tenant_read_session = tenant_factory(autoflush=False)
    control_read_session = control_factory(autoflush=False)
    try:
        schema_preflight = _test_schema_preflight(engine)
        if (
            _schema_generation(schema_preflight) != SCHEMA_GENERATION
            or schema_preflight.alembic_versions != (TENANT_HEAD,)
        ):
            raise AssertionError("test tenant schema identity is invalid")
        schema_digest = bytes.fromhex(schema_preflight.preflight_digest)
        bundle = _bundle(
            manifest=manifest,
            seeded=seeded,
            schema_digest=schema_digest,
            tenant_factory=tenant_factory,
            control_factory=control_factory,
        )
        policy = build_default_tenant_reconciliation_policy(
            DefaultTenantReconciliationExpectedFacts(
                accessory_links=0,
                credential_revisions=0,
                device_warehouse_links=2,
                legacy_double_count=0,
                rental_total_minor=1234,
                orphan_count=0,
                rental_device_links=1,
                schema_digest=schema_digest,
                schema_generation=SCHEMA_GENERATION,
                historical_waybills=0,
                device_rows=2,
                default_warehouse_count=1,
            )
        )
        schema_collectors = (
            _CurrentTestSchemaCollector("schema.digest", engine),
            _CurrentTestSchemaCollector("schema.generation", engine),
        )
        registry = DefaultTenantReconciliationSqlRegistry(
            manifest=manifest,
            tenant_session=tenant_read_session,
            control_session=control_read_session,
        )
        collectors = compose_default_tenant_reconciliation_collectors(
            policy=policy,
            sql_registry=registry,
            supplemental_collectors=(
                DefaultLegacyDoubleCountCollector(
                    _legacy_boundary_evidence(manifest)
                ),
                *schema_collectors,
            ),
        )
        executor = build_default_migration_backfill_executor(
            bundle=bundle,
            historical_boundary=_empty_historical_boundary(manifest),
            historical_snapshot_step=VerifiedEmptyHistoricalSnapshotsStep(
                tenant_session_factory=tenant_factory,
                expected_schema_generation=SCHEMA_GENERATION,
            ),
            policy=policy,
            reconciliation_runner=DefaultMigrationReconciliationRunner(
                collectors
            ),
        )
        invocation = _phase_invocation(manifest)
        crash_executor = replace(
            executor,
            steps=tuple(
                _CrashAfterCommittedStep(step)
                if step.name == "logical_accessory_backfill"
                else step
                for step in executor.steps
            ),
        )
        try:
            crash_executor.execute(invocation)
        except _InjectedBackfillCrash:
            pass
        else:
            raise AssertionError("injected backfill crash did not occur")
        _assert_partial_crash_state(
            tenant_factory=tenant_factory,
            control_factory=control_factory,
            seeded=seeded,
        )
        try:
            first = executor.execute(invocation)
        except MigrationReconciliationBlockedError as exc:
            mismatched = tuple(
                finding.key
                for finding in exc.report.findings
                if finding.status.value != "matched"
            )
            raise AssertionError(
                "isolated reconciliation mismatched keys: "
                + ",".join(mismatched)
            ) from exc
        replay = executor.execute(invocation)
        if (
            first.result_state_digest != replay.result_state_digest
            or first.reconciliation_report is None
            or replay.reconciliation_report is None
            or not first.reconciliation_report.passed
            or not replay.reconciliation_report.passed
        ):
            raise AssertionError("complete backfill did not replay stably")
        return _observe_result(
            tenant_factory=tenant_factory,
            control_factory=control_factory,
            seeded=seeded,
            first_digest=first.result_state_digest,
            replay_digest=replay.result_state_digest,
            schema_digest=schema_digest,
        )
    finally:
        tenant_read_session.close()
        control_read_session.close()


def _install_tenant_revision(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version ("
            "version_num VARCHAR(128) NOT NULL PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "INSERT INTO alembic_version (version_num) VALUES (%s)",
            (TENANT_HEAD,),
        )


def _manifest() -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="complete-default-backfill-mysql-v1",
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        source_schema_name="inventory_management_test",
        baseline_migration_id=TENANT_BASELINE,
        core_plan_revision_uuid=PLAN_UUID,
        control_schema_head="202608230038",
        tenant_schema_head=TENANT_HEAD,
        source_snapshot_digest=_digest("isolated-backfill-source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("migration-bundle"),
        display_name_input_commitment=_digest("display-name"),
        first_admin_phone_input_commitment=_digest("admin-phone"),
    )


def _seed_databases(
    *,
    tenant_engine: Engine,
    control_engine: Engine,
) -> _SeededTenant:
    tenant_factory = sessionmaker(bind=tenant_engine, expire_on_commit=False)
    created_at = NOW.replace(tzinfo=None)
    with tenant_factory.begin() as session:
        identity = TenantDatabaseIdentity(
            singleton_key=1,
            tenant_id=str(TENANT_UUID),
            database_uuid=str(DATABASE_UUID),
            created_at=created_at,
            schema_generation=SCHEMA_GENERATION,
        )
        accessory_type = AccessoryType(
            name="migration-tripod",
            display_name="迁移三脚架",
            tracking_mode="logical_unit",
            is_active=True,
        )
        main_device = Device(
            name="migration-main-device",
            serial_number="migration-main-001",
            is_accessory=False,
        )
        accessory_device = Device(
            name="migration-accessory-device",
            serial_number="migration-accessory-001",
            is_accessory=True,
        )
        session.add_all(
            (identity, accessory_type, main_device, accessory_device)
        )
        session.flush()
        rental = Rental(
            device_id=main_device.id,
            start_date=date(2026, 10, 10),
            end_date=date(2026, 10, 12),
            customer_name="迁移测试客户",
            destination="旧地址",
            order_amount=Decimal("12.34"),
            express_type_id=2,
            status="not_shipped",
        )
        session.add(rental)
        session.flush()
        rental.express_type_id = None
        session.flush()
        seeded = _SeededTenant(
            identity_created_at=created_at,
            main_device_id=main_device.id,
            accessory_device_id=accessory_device.id,
            accessory_type_id=accessory_type.id,
            rental_id=rental.id,
        )
    control_factory = sessionmaker(bind=control_engine, expire_on_commit=False)
    with control_factory.begin() as session:
        session.add(
            Tenant(
                id=str(TENANT_UUID),
                name="默认租户迁移测试",
                status="provisioning",
            )
        )
    return seeded


def _test_schema_preflight(engine: Engine):
    return preflight_test_database_write(
        engine.url,
        lambda _parsed: engine.connect(),
        disposition="metadata_rebuild",
    )


def _schema_generation(preflight) -> int:
    if preflight.identity_generations != ((1, SCHEMA_GENERATION),):
        raise MigrationReconciliationCollectionError()
    return SCHEMA_GENERATION


def _bundle(
    *,
    manifest,
    seeded,
    schema_digest,
    tenant_factory,
    control_factory,
):
    identity_digest = tenant_database_identity_digest(
        tenant_uuid=manifest.tenant_uuid,
        database_uuid=manifest.database_uuid,
        created_at=seeded.identity_created_at,
        schema_generation=SCHEMA_GENERATION,
    )
    express_manifest = ExpressTypeBackfillManifest(
        migration_idempotency_key=manifest.migration_idempotency_key,
        parent_manifest_digest=manifest.digest,
        tenant_uuid=manifest.tenant_uuid,
        database_uuid=manifest.database_uuid,
        schema_generation=SCHEMA_GENERATION,
        tenant_identity_digest=identity_digest,
        schema_revision=manifest.tenant_schema_head,
        schema_digest=schema_digest,
        source_snapshot=build_express_type_source_snapshot(
            ((seeded.rental_id, None),)
        ),
    )
    schema_read = lambda _session, _identity: TenantSchemaAuthorityFacts(
        tenant_uuid=manifest.tenant_uuid,
        database_uuid=manifest.database_uuid,
        schema_generation=SCHEMA_GENERATION,
        schema_revision=manifest.tenant_schema_head,
        schema_digest=schema_digest,
    )
    return ResolvedDefaultMigrationBackfillBundle(
        tenant_session_factory=tenant_factory,
        control_session_factory=control_factory,
        expected_schema_generation=SCHEMA_GENERATION,
        warehouse_profile=DefaultWarehouseProfile(),
        express_type_manifest=express_manifest,
        planned_logistics_plan=PlannedLogisticsBackfillPlan(
            parent_manifest_digest=manifest.digest,
            migration_idempotency_key=manifest.migration_idempotency_key,
            entries=(
                PlannedLogisticsBackfillEntry(
                    rental_id=seeded.rental_id,
                    expected_device_id=seeded.main_device_id,
                    expected_start_date=date(2026, 10, 10),
                    expected_end_date=date(2026, 10, 12),
                    expected_status="not_shipped",
                    logistics_days=1,
                ),
            ),
        ),
        structured_address_plan=StructuredAddressBackfillPlan(
            parent_manifest_digest=manifest.digest,
            migration_idempotency_key=manifest.migration_idempotency_key,
            entries=(
                StructuredRentalAddressEntry(
                    rental_id=seeded.rental_id,
                    expected_parent_rental_id=None,
                    expected_legacy_destination_digest=(
                        legacy_destination_digest("旧地址")
                    ),
                    province="广东省",
                    city="深圳市",
                    district="南山区",
                    address_detail="隔离迁移测试地址",
                ),
            ),
        ),
        logical_accessory_plan=LogicalAccessoryBackfillPlan(
            parent_manifest_digest=manifest.digest,
            migration_idempotency_key=manifest.migration_idempotency_key,
            units=(
                LegacyAccessoryUnitEntry(
                    legacy_device_id=seeded.accessory_device_id,
                    accessory_type_id=seeded.accessory_type_id,
                    expected_warehouse_id=1,
                    expected_lifecycle_status="active",
                    reliable_and_available=True,
                ),
            ),
            requests=(),
        ),
        integration_metadata_plan=IntegrationMetadataBackfillPlan(
            parent_manifest_digest=manifest.digest,
            migration_idempotency_key=manifest.migration_idempotency_key,
            entries=(
                IntegrationMetadataBackfillEntry(
                    provider="kuaimai",
                    name="默认快麦",
                    config={},
                ),
                IntegrationMetadataBackfillEntry(
                    provider="sf",
                    name="默认顺丰",
                    config={},
                ),
                IntegrationMetadataBackfillEntry(
                    provider="xianyu",
                    name="默认闲鱼",
                    config={},
                ),
            ),
        ),
        express_type_service=ExpressTypeBackfillService(schema_read),
    )


def _empty_historical_boundary(manifest):
    from inventory_control.default_migration import (
        HISTORICAL_BOUNDARY_COUNT_KEYS,
        DefaultHistoricalSnapshotBoundaryEvidence,
        HistoricalSnapshotDisposition,
    )

    return DefaultHistoricalSnapshotBoundaryEvidence(
        source_schema_name=manifest.source_schema_name,
        baseline_migration_id=manifest.baseline_migration_id,
        source_snapshot_digest=manifest.source_snapshot_digest,
        counts=tuple(
            (key, 0) for key in HISTORICAL_BOUNDARY_COUNT_KEYS
        ),
        disposition=HistoricalSnapshotDisposition.EMPTY,
    )


def _legacy_boundary_evidence(manifest):
    return DefaultLegacyAuthorityBoundaryEvidence(
        manifest_digest=manifest.digest,
        source_snapshot_digest=manifest.source_snapshot_digest,
        implementation_identity_digest=(
            manifest.implementation_identity_digest
        ),
        migration_bundle_digest=manifest.migration_bundle_digest,
        legacy_quantity_negative_digest=_digest("quantity-negative"),
        legacy_child_rental_negative_digest=_digest("child-negative"),
        legacy_global_provider_negative_digest=_digest("provider-negative"),
        legacy_shipment_writer_negative_digest=_digest("shipment-negative"),
    )


def _phase_invocation(manifest):
    plan = MigrationExecutionPlan(
        phase=MigrationPhase.BACKFILL_VERIFY,
        mode=MigrationExecutionMode.APPLY,
        manifest_digest=manifest.digest,
        prerequisites=(),
        completion_conditions=(),
        stop_conditions=(),
        rollback_action="retain reversible backfill facts",
        mutations_allowed=True,
    )
    phase_key = "default-migration:" + hashlib.sha256(
        b"default-tenant-migration-phase-v1\x00"
        + manifest.digest
        + b"\x00backfill_verify"
    ).hexdigest()
    return MigrationPhaseInvocation(
        manifest=manifest,
        plan=plan,
        phase_execution_key=phase_key,
    )


def _observe_result(
    *,
    tenant_factory,
    control_factory,
    seeded,
    first_digest,
    replay_digest,
    schema_digest,
):
    with tenant_factory() as session:
        rental = session.get(Rental, seeded.rental_id)
        if rental is None:
            raise AssertionError("backfilled rental is missing")
        values = {
            "device_rows": session.scalar(
                sa.select(sa.func.count()).select_from(Device)
            ),
            "device_warehouse_links": session.scalar(
                sa.select(sa.func.count())
                .select_from(Device)
                .where(Device.warehouse_id.is_not(None))
            ),
            "default_warehouse_count": session.scalar(
                sa.select(sa.func.count())
                .select_from(Warehouse)
                .where(Warehouse.is_default.is_(True))
            ),
            "logical_unit_count": session.scalar(
                sa.select(sa.func.count()).select_from(AccessoryUnit)
            ),
        }
        express_type = rental.express_type_id
    with control_factory() as session:
        integration_count = session.scalar(
            sa.select(sa.func.count()).select_from(TenantIntegration)
        )
        from inventory_control.models import TenantIntegrationSecretRevision

        revision_count = session.scalar(
            sa.select(sa.func.count()).select_from(
                TenantIntegrationSecretRevision
            )
        )
    return CompleteBackfillObservation(
        result_digest=first_digest,
        replay_result_digest=replay_digest,
        device_rows=int(values["device_rows"]),
        device_warehouse_links=int(values["device_warehouse_links"]),
        default_warehouse_count=int(values["default_warehouse_count"]),
        logical_unit_count=int(values["logical_unit_count"]),
        integration_count=int(integration_count),
        credential_revision_count=int(revision_count),
        rental_express_type_id=int(express_type),
        schema_generation=SCHEMA_GENERATION,
        schema_digest=schema_digest,
        crash_resume_verified=True,
    )


def _assert_partial_crash_state(
    *,
    tenant_factory,
    control_factory,
    seeded,
) -> None:
    with tenant_factory() as session:
        rental = session.get(Rental, seeded.rental_id)
        if (
            rental is None
            or rental.express_type_id != 2
            or rental.planned_ship_out_date is None
            or rental.planned_return_date is None
            or rental.customer_province is None
            or session.scalar(
                sa.select(sa.func.count()).select_from(AccessoryUnit)
            )
            != 1
        ):
            raise AssertionError("committed pre-crash tenant facts are missing")
    with control_factory() as session:
        if session.scalar(
            sa.select(sa.func.count()).select_from(TenantIntegration)
        ) != 0:
            raise AssertionError("post-crash control step ran unexpectedly")


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


__all__ = [
    "CompleteBackfillObservation",
    "run_complete_default_backfill_composition",
]
