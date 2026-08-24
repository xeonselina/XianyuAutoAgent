from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.services.migration.default_phase_adapters import (
    DefaultMigrationApplicationEnforcementBundle,
    DefaultMigrationContractEnforcementBundle,
    DefaultMigrationDatabaseJobsEnforcementBundle,
    DefaultMigrationExpandInfrastructureBundle,
    DefaultMigrationRegistrationBundle,
    DefaultMigrationSourcePreflightBundle,
    ResolvedDefaultMigrationBackfillBundle,
    VerifiedEmptyHistoricalSnapshotsStep,
    build_default_migration_backfill_executor,
    build_default_migration_expand_executor,
    build_verified_default_migration_expand_executor,
    resolved_default_migration_backfill_steps,
)
from app.services.migration.default_executor_registry import (
    build_default_migration_executor_registry,
)
from app.services.migration.default_source_baseline import (
    DefaultSourceBaselineEvidence,
    DefaultSourceBaselineRejected,
)
from app.services.migration.default_tenant_registration import (
    DefaultTenantRouteRegistration,
)
from app.services.migration.default_warehouse_backfill import (
    DefaultWarehouseProfile,
)
from app.services.migration.express_type_backfill import (
    ExpressTypeBackfillManifest,
    build_express_type_source_snapshot,
)
from app.services.migration.integration_metadata_backfill import (
    IntegrationMetadataBackfillEntry,
    IntegrationMetadataBackfillPlan,
)
from app.services.migration.logical_accessory_backfill import (
    LegacyAccessoryUnitEntry,
    LogicalAccessoryBackfillPlan,
)
from app.services.migration.planned_logistics_backfill import (
    PlannedLogisticsBackfillEntry,
    PlannedLogisticsBackfillPlan,
)
from app.services.migration.structured_address_backfill import (
    StructuredAddressBackfillPlan,
    StructuredRentalAddressEntry,
    legacy_destination_digest,
)
from inventory_control.default_migration import (
    HISTORICAL_BOUNDARY_COUNT_KEYS,
    DefaultHistoricalSnapshotBoundaryEvidence,
    DefaultMigrationReconciliationRunner,
    DefaultMigrationStepInvocation,
    DefaultMigrationStepResult,
    DefaultSourceMigrationPreflightEvidence,
    HistoricalSnapshotDisposition,
    DefaultTenantMigrationManifest,
    DefaultTenantIdentityInputs,
    MigrationEvidenceError,
    MigrationBundleMismatchError,
    MigrationExecutionMode,
    MigrationExecutionPlan,
    MigrationJournalFileStore,
    MigrationPhase,
    MigrationPhaseInvocation,
    ReconciliationObservation,
    ReconciliationPolicy,
    ReconciliationRequirement,
    ReconciliationScope,
    ReconciliationValueKind,
    build_default_migration_bundle_evidence,
)
from inventory_control.models import Tenant


TENANT_UUID = UUID("81000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("81000000-0000-4000-8000-000000000002")
PLAN_UUID = UUID("81000000-0000-4000-8000-000000000003")
WAREHOUSE_UUID = UUID("81000000-0000-4000-8000-000000000004")


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest():
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="resolved-adapters-v1",
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        source_schema_name="inventory_management_test",
        baseline_migration_id="baseline-v1",
        core_plan_revision_uuid=PLAN_UUID,
        control_schema_head="202608220026",
        tenant_schema_head="20260823_shipping_contract",
        source_snapshot_digest=_digest("source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=_digest("display-name"),
        first_admin_phone_input_commitment=_digest("phone"),
    )


def _phase_invocation(manifest):
    plan = MigrationExecutionPlan(
        phase=MigrationPhase.BACKFILL_VERIFY,
        mode=MigrationExecutionMode.APPLY,
        manifest_digest=manifest.digest,
        prerequisites=(),
        completion_conditions=(),
        stop_conditions=(),
        rollback_action="retain reversible facts",
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


def _expand_phase_invocation(manifest):
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
    return MigrationPhaseInvocation(
        manifest=manifest,
        plan=plan,
        phase_execution_key=phase_key,
    )


def _step_invocation(phase_invocation, step_name):
    step_key = "default-step:" + hashlib.sha256(
        b"default-migration-step-v1\x00"
        + phase_invocation.phase_execution_key.encode("ascii")
        + b"\x00"
        + step_name.encode("ascii")
    ).hexdigest()
    return DefaultMigrationStepInvocation(
        phase_invocation=phase_invocation,
        step_name=step_name,
        step_execution_key=step_key,
    )


class _RecordingFactory:
    def __init__(self, engine=None):
        self.engine = engine
        self.factory = sessionmaker(bind=engine, expire_on_commit=False)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.factory()


class _WarehouseService:
    def __init__(self):
        self.calls = []

    def backfill(self, session, **kwargs):
        assert session.in_transaction()
        self.calls.append(kwargs)
        replay = len(self.calls) > 1
        return SimpleNamespace(
            warehouse_id=7,
            warehouse_uuid=WAREHOUSE_UUID,
            setup_state="pending",
            assigned_device_ids=(() if replay else (10, 11)),
            preserved_assigned_device_count=(3 if replay else 1),
        )


class _StableDigestService:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def backfill(self, session, **kwargs):
        assert session.in_transaction()
        self.calls.append(kwargs)
        return self.result


class _IntegrationService:
    def __init__(self, plan_digest):
        self.plan_digest = plan_digest
        self.calls = 0

    def backfill(self, session, **kwargs):
        assert session.in_transaction()
        self.calls += 1
        return SimpleNamespace(
            plan_digest=self.plan_digest,
            integrations=(
                SimpleNamespace(
                    integration_uuid=(
                        "81000000-0000-4000-8000-000000000005"
                    ),
                    tenant_uuid=str(TENANT_UUID),
                    provider="sf",
                    name="默认顺丰",
                    status="inactive",
                    current_secret_revision_uuid=None,
                    row_version=1,
                    idempotent_replay=self.calls > 1,
                ),
            ),
        )


def _bundle(manifest, tenant_factory, control_factory, *, express_passes=True):
    snapshot = build_express_type_source_snapshot(((1, None),))
    express_manifest = ExpressTypeBackfillManifest(
        migration_idempotency_key=manifest.migration_idempotency_key,
        parent_manifest_digest=manifest.digest,
        tenant_uuid=manifest.tenant_uuid,
        database_uuid=manifest.database_uuid,
        schema_generation=3,
        tenant_identity_digest=_digest("tenant-identity"),
        schema_revision=manifest.tenant_schema_head,
        schema_digest=_digest("tenant-schema"),
        source_snapshot=snapshot,
    )
    planned = PlannedLogisticsBackfillPlan(
        parent_manifest_digest=manifest.digest,
        migration_idempotency_key=manifest.migration_idempotency_key,
        entries=(
            PlannedLogisticsBackfillEntry(
                rental_id=1,
                expected_device_id=1,
                expected_start_date=date(2026, 9, 1),
                expected_end_date=date(2026, 9, 3),
                expected_status="not_shipped",
                logistics_days=1,
            ),
        ),
    )
    structured = StructuredAddressBackfillPlan(
        parent_manifest_digest=manifest.digest,
        migration_idempotency_key=manifest.migration_idempotency_key,
        entries=(
            StructuredRentalAddressEntry(
                rental_id=1,
                expected_parent_rental_id=None,
                expected_legacy_destination_digest=(
                    legacy_destination_digest("旧地址")
                ),
                province="广东省",
                city="深圳市",
                district="南山区",
                address_detail="测试地址 1 号",
            ),
        ),
    )
    logical = LogicalAccessoryBackfillPlan(
        parent_manifest_digest=manifest.digest,
        migration_idempotency_key=manifest.migration_idempotency_key,
        units=(
            LegacyAccessoryUnitEntry(
                legacy_device_id=2,
                accessory_type_id=1,
                expected_warehouse_id=7,
                expected_lifecycle_status="active",
                reliable_and_available=True,
            ),
        ),
        requests=(),
    )
    integration = IntegrationMetadataBackfillPlan(
        parent_manifest_digest=manifest.digest,
        migration_idempotency_key=manifest.migration_idempotency_key,
        entries=(
            IntegrationMetadataBackfillEntry(
                provider="sf",
                name="默认顺丰",
                config={},
            ),
        ),
    )
    return ResolvedDefaultMigrationBackfillBundle(
        tenant_session_factory=tenant_factory,
        control_session_factory=control_factory,
        expected_schema_generation=3,
        warehouse_profile=DefaultWarehouseProfile(),
        express_type_manifest=express_manifest,
        planned_logistics_plan=planned,
        structured_address_plan=structured,
        logical_accessory_plan=logical,
        integration_metadata_plan=integration,
        warehouse_service=_WarehouseService(),
        express_type_service=_StableDigestService(
            SimpleNamespace(
                verification_passed=express_passes,
                report_digest=_digest("express-result"),
            )
        ),
        planned_logistics_service=_StableDigestService(
            SimpleNamespace(result_digest=_digest("planned-result"))
        ),
        structured_address_service=_StableDigestService(
            SimpleNamespace(result_digest=_digest("address-result"))
        ),
        logical_accessory_service=_StableDigestService(
            SimpleNamespace(result_digest=_digest("accessory-result"))
        ),
        integration_metadata_service=_IntegrationService(integration.digest),
    )


def test_resolved_steps_use_bound_databases_in_dependency_order_and_replay_stably():
    manifest = _manifest()
    phase_invocation = _phase_invocation(manifest)
    tenant_factory = _RecordingFactory()
    control_factory = _RecordingFactory()
    bundle = _bundle(manifest, tenant_factory, control_factory)
    steps = resolved_default_migration_backfill_steps(bundle)

    first = tuple(
        step.execute(_step_invocation(phase_invocation, step.name))
        for step in steps
    )
    replay = tuple(
        step.execute(_step_invocation(phase_invocation, step.name))
        for step in steps
    )

    assert [step.name for step in steps] == [
        "warehouse_backfill",
        "express_type_backfill",
        "planned_logistics_backfill",
        "structured_address_backfill",
        "logical_accessory_backfill",
        "integration_metadata_backfill",
    ]
    assert [item.result_digest for item in replay] == [
        item.result_digest for item in first
    ]
    assert tenant_factory.calls == 10
    assert control_factory.calls == 2
    assert bundle.warehouse_service.calls[0]["tenant_uuid"] == TENANT_UUID
    assert (
        bundle.planned_logistics_service.calls[0]["manifest"].digest
        == manifest.digest
    )
    assert "测试地址" not in repr(bundle)


def test_each_step_rolls_back_its_database_transaction_on_failure(
    mysql_control_database,
):
    manifest = _manifest()
    phase_invocation = _phase_invocation(manifest)
    tenant_factory = _RecordingFactory(mysql_control_database.engine)
    control_factory = _RecordingFactory(mysql_control_database.engine)
    bundle = _bundle(manifest, tenant_factory, control_factory)

    class FailingWarehouse:
        def backfill(self, session, **kwargs):
            session.add(
                Tenant(
                    id="81000000-0000-4000-8000-000000000099",
                    name="rollback probe",
                    status="active",
                )
            )
            session.flush()
            raise RuntimeError("simulated crash")

    object.__setattr__(bundle, "warehouse_service", FailingWarehouse())
    step = resolved_default_migration_backfill_steps(bundle)[0]

    with pytest.raises(RuntimeError, match="simulated crash"):
        step.execute(_step_invocation(phase_invocation, step.name))

    with mysql_control_database.new_session() as session:
        assert session.scalar(select(Tenant).limit(1)) is None


def test_unsafe_express_states_block_phase_evidence():
    manifest = _manifest()
    phase_invocation = _phase_invocation(manifest)
    bundle = _bundle(
        manifest,
        _RecordingFactory(),
        _RecordingFactory(),
        express_passes=False,
    )
    step = resolved_default_migration_backfill_steps(bundle)[1]

    with pytest.raises(MigrationEvidenceError, match="unsupported source"):
        step.execute(_step_invocation(phase_invocation, step.name))


@dataclass
class _Collector:
    key: str
    observed: object

    def collect(self, *, manifest, requirement):
        return ReconciliationObservation(key=self.key, observed=self.observed)


@dataclass
class _HistoricalStep:
    name: str = "historical_snapshots"

    def execute(self, invocation):
        return DefaultMigrationStepResult(
            step_name=self.name,
            manifest_digest=invocation.phase_invocation.manifest.digest,
            result_digest=_digest("approved-historical-snapshots"),
            executor_reference="approved:historical-snapshots",
        )


@dataclass
class _ApprovedNonemptyHistoricalStep(_HistoricalStep):
    approved_historical_boundary_digest: bytes = b""
    approved_policy_revision: int = 1


def _historical_boundary(manifest, *, nonempty=False):
    return DefaultHistoricalSnapshotBoundaryEvidence(
        source_schema_name=manifest.source_schema_name,
        baseline_migration_id=manifest.baseline_migration_id,
        source_snapshot_digest=manifest.source_snapshot_digest,
        counts=tuple(
            (key, 1 if nonempty and key == "legacy_tracking_rows" else 0)
            for key in HISTORICAL_BOUNDARY_COUNT_KEYS
        ),
        disposition=(
            HistoricalSnapshotDisposition.REQUIRES_APPROVED_NONEMPTY_ADAPTER
            if nonempty
            else HistoricalSnapshotDisposition.EMPTY
        ),
    )


def _policy_and_runner():
    requirements = tuple(
        ReconciliationRequirement(
            key=f"check.{scope.value}",
            scope=scope,
            value_kind=(
                ReconciliationValueKind.SHA256_DIGEST
                if scope is ReconciliationScope.SCHEMA_DIGEST
                else (
                    ReconciliationValueKind.POSITIVE_INTEGER
                    if scope is ReconciliationScope.SCHEMA_GENERATION
                    else ReconciliationValueKind.NONNEGATIVE_INTEGER
                )
            ),
            expected=(
                _digest("schema")
                if scope is ReconciliationScope.SCHEMA_DIGEST
                else (3 if scope is ReconciliationScope.SCHEMA_GENERATION else 0)
            ),
            tolerance=0,
            disposition_allowed=False,
        )
        for scope in sorted(ReconciliationScope, key=lambda item: item.value)
    )
    policy = ReconciliationPolicy(policy_version=1, requirements=requirements)
    runner = DefaultMigrationReconciliationRunner(
        tuple(
            _Collector(requirement.key, requirement.expected)
            for requirement in requirements
        )
    )
    return policy, runner


def test_complete_builder_requires_explicit_historical_step():
    manifest = _manifest()
    bundle = _bundle(manifest, _RecordingFactory(), _RecordingFactory())
    policy, runner = _policy_and_runner()

    with pytest.raises(MigrationEvidenceError, match="historical snapshot"):
        build_default_migration_backfill_executor(
            bundle=bundle,
            historical_boundary=_historical_boundary(manifest),
            historical_snapshot_step=_HistoricalStep(name="placeholder"),
            policy=policy,
            reconciliation_runner=runner,
        )

    with pytest.raises(MigrationEvidenceError, match="verified empty"):
        build_default_migration_backfill_executor(
            bundle=bundle,
            historical_boundary=_historical_boundary(manifest),
            historical_snapshot_step=_HistoricalStep(),
            policy=policy,
            reconciliation_runner=runner,
        )

    executor = build_default_migration_backfill_executor(
        bundle=bundle,
        historical_boundary=_historical_boundary(manifest),
        historical_snapshot_step=VerifiedEmptyHistoricalSnapshotsStep(
            tenant_session_factory=_RecordingFactory(),
            expected_schema_generation=3,
        ),
        policy=policy,
        reconciliation_runner=runner,
    )
    assert [step.name for step in executor.steps][-2:] == [
        "integration_metadata_backfill",
        "historical_snapshots",
    ]

    nonempty = _historical_boundary(manifest, nonempty=True)
    with pytest.raises(MigrationEvidenceError, match="boundary-bound"):
        build_default_migration_backfill_executor(
            bundle=bundle,
            historical_boundary=nonempty,
            historical_snapshot_step=_HistoricalStep(),
            policy=policy,
            reconciliation_runner=runner,
        )
    approved = _ApprovedNonemptyHistoricalStep(
        approved_historical_boundary_digest=nonempty.digest,
    )
    nonempty_executor = build_default_migration_backfill_executor(
        bundle=bundle,
        historical_boundary=nonempty,
        historical_snapshot_step=approved,
        policy=policy,
        reconciliation_runner=runner,
    )
    assert nonempty_executor.steps[-1] is approved


class _RegistrationService:
    def __init__(self, *, fail_control_once=False):
        self.tenant_calls = []
        self.control_calls = []
        self.fail_control_once = fail_control_once

    def write_tenant_database_identity(self, session, **kwargs):
        assert session.in_transaction()
        self.tenant_calls.append(kwargs)
        return SimpleNamespace(
            manifest_digest=kwargs["manifest"].digest,
            tenant_uuid=TENANT_UUID,
            database_uuid=DATABASE_UUID,
            schema_generation=3,
            identity_created_at=datetime(
                2026,
                8,
                22,
                tzinfo=timezone.utc,
            ),
            created=len(self.tenant_calls) == 1,
        )

    def write_control_registration(self, session, **kwargs):
        assert session.in_transaction()
        self.control_calls.append(kwargs)
        if self.fail_control_once:
            self.fail_control_once = False
            raise RuntimeError("control registration crash")
        return SimpleNamespace(
            tenant_uuid=TENANT_UUID,
            database_uuid=DATABASE_UUID,
            admin_user_uuid=UUID(
                "81000000-0000-4000-8000-000000000006"
            ),
            admin_membership_uuid=UUID(
                "81000000-0000-4000-8000-000000000007"
            ),
            route_version=1,
            created=len(self.control_calls) == 1,
        )


def _registration_bundle(manifest, service):
    return DefaultMigrationRegistrationBundle(
        tenant_session_factory=_RecordingFactory(),
        control_session_factory=_RecordingFactory(),
        identity_inputs=DefaultTenantIdentityInputs(
            display_name="现有公司",
            first_admin_phone_e164="+8613800138000",
            display_name_commitment=manifest.display_name_input_commitment,
            first_admin_phone_commitment=(
                manifest.first_admin_phone_input_commitment
            ),
            commitment_root_key_version=1,
        ),
        route=DefaultTenantRouteRegistration(
            database_instance_key="local-mysql",
            schema_generation=3,
            schema_digest=_digest("tenant-schema"),
            dml_username="tenant_dml",
            dml_credential_generation=1,
            dml_root_key_version=1,
            dml_derivation_version=1,
            platform_read_username="platform_read",
            platform_read_credential_generation=1,
            platform_read_root_key_version=1,
            platform_read_derivation_version=1,
        ),
        registration_service=service,
    )


@dataclass
class _SchemaStep:
    name: str

    def execute(self, invocation):
        return DefaultMigrationStepResult(
            step_name=self.name,
            manifest_digest=invocation.phase_invocation.manifest.digest,
            result_digest=_digest(self.name),
            executor_reference=f"schema:{self.name}",
        )


class _StaticVerifier:
    def __init__(self, evidence):
        self.evidence = evidence
        self.calls = 0

    def verify(self, invocation):
        self.calls += 1
        return self.evidence


def test_expand_builder_orders_schema_then_crash_resumable_in_place_registration():
    manifest = _manifest()
    service = _RegistrationService(fail_control_once=True)
    bundle = _registration_bundle(manifest, service)
    registration_step = build_default_migration_expand_executor(
        control_schema_expand_step=_SchemaStep("control_schema_expand"),
        tenant_schema_expand_step=_SchemaStep("tenant_schema_expand"),
        registration_bundle=bundle,
    ).steps[-1]

    assert repr(bundle) == (
        "DefaultMigrationRegistrationBundle(schema_generation=3, "
        "identity_inputs='<redacted>', sessions='<bound>')"
    )
    phase_invocation = _expand_phase_invocation(manifest)
    invocation = _step_invocation(
        phase_invocation,
        "in_place_registration",
    )

    with pytest.raises(RuntimeError, match="control registration crash"):
        registration_step.execute(invocation)
    completed = registration_step.execute(invocation)

    assert len(service.tenant_calls) == 2
    assert len(service.control_calls) == 2
    assert completed.manifest_digest == manifest.digest
    assert completed.executor_reference == "expand:in_place_registration"
    assert [
        step.name
        for step in build_default_migration_expand_executor(
            control_schema_expand_step=_SchemaStep(
                "control_schema_expand"
            ),
            tenant_schema_expand_step=_SchemaStep("tenant_schema_expand"),
            registration_bundle=bundle,
        ).steps
    ] == [
        "control_schema_expand",
        "tenant_schema_expand",
        "in_place_registration",
    ]


def test_verified_expand_observes_source_before_any_schema_verifier():
    migration_bundle = build_default_migration_bundle_evidence(
        Path(__file__).resolve().parents[2]
    )
    manifest = replace(
        _manifest(),
        control_schema_head=migration_bundle.control_schema_head,
        tenant_schema_head=migration_bundle.tenant_schema_head,
        migration_bundle_digest=migration_bundle.bundle_digest,
    )
    source_baseline = DefaultSourceBaselineEvidence(
        source_schema_name=manifest.source_schema_name,
        baseline_migration_id=manifest.baseline_migration_id,
        database_profile="mariadb-10.11",
        server_version="10.11.6-MariaDB-log",
        table_count=9,
        total_rows=6264,
        schema_inventory_digest=_digest("source-schema"),
        row_count_digest=_digest("source-rows"),
        source_snapshot_digest=_digest("different-source"),
    )
    source_verifier = _StaticVerifier(
        DefaultSourceMigrationPreflightEvidence(
            source_baseline=source_baseline,
            historical_boundary=DefaultHistoricalSnapshotBoundaryEvidence(
                source_schema_name=manifest.source_schema_name,
                baseline_migration_id=manifest.baseline_migration_id,
                source_snapshot_digest=source_baseline.source_snapshot_digest,
                counts=tuple(
                    (key, 0) for key in HISTORICAL_BOUNDARY_COUNT_KEYS
                ),
                disposition=HistoricalSnapshotDisposition.EMPTY,
            ),
        )
    )
    control_verifier = _StaticVerifier(object())
    tenant_verifier = _StaticVerifier(object())
    executor = build_verified_default_migration_expand_executor(
        source_preflight_bundle=DefaultMigrationSourcePreflightBundle(
            verifier=source_verifier
        ),
        migration_bundle_evidence=migration_bundle,
        infrastructure_bundle=DefaultMigrationExpandInfrastructureBundle(
            control_verifier=control_verifier,
            tenant_verifier=tenant_verifier,
        ),
        registration_bundle=_registration_bundle(
            manifest,
            _RegistrationService(),
        ),
    )

    assert [step.name for step in executor.steps] == [
        "source_migration_preflight",
        "migration_bundle",
        "control_schema_expand",
        "tenant_schema_expand",
        "in_place_registration",
    ]
    with pytest.raises(DefaultSourceBaselineRejected):
        executor.execute(_expand_phase_invocation(manifest))

    assert source_verifier.calls == 1
    assert control_verifier.calls == 0
    assert tenant_verifier.calls == 0


def test_verified_expand_rejects_bundle_drift_before_schema_verifiers():
    manifest = _manifest()
    migration_bundle = build_default_migration_bundle_evidence(
        Path(__file__).resolve().parents[2]
    )
    source_baseline = DefaultSourceBaselineEvidence(
        source_schema_name=manifest.source_schema_name,
        baseline_migration_id=manifest.baseline_migration_id,
        database_profile="mariadb-10.11",
        server_version="10.11.6-MariaDB-log",
        table_count=9,
        total_rows=6264,
        schema_inventory_digest=_digest("source-schema"),
        row_count_digest=_digest("source-rows"),
        source_snapshot_digest=manifest.source_snapshot_digest,
    )
    source_verifier = _StaticVerifier(
        DefaultSourceMigrationPreflightEvidence(
            source_baseline=source_baseline,
            historical_boundary=DefaultHistoricalSnapshotBoundaryEvidence(
                source_schema_name=manifest.source_schema_name,
                baseline_migration_id=manifest.baseline_migration_id,
                source_snapshot_digest=manifest.source_snapshot_digest,
                counts=tuple(
                    (key, 0) for key in HISTORICAL_BOUNDARY_COUNT_KEYS
                ),
                disposition=HistoricalSnapshotDisposition.EMPTY,
            ),
        )
    )
    control_verifier = _StaticVerifier(object())
    tenant_verifier = _StaticVerifier(object())
    executor = build_verified_default_migration_expand_executor(
        source_preflight_bundle=DefaultMigrationSourcePreflightBundle(
            verifier=source_verifier
        ),
        migration_bundle_evidence=migration_bundle,
        infrastructure_bundle=DefaultMigrationExpandInfrastructureBundle(
            control_verifier=control_verifier,
            tenant_verifier=tenant_verifier,
        ),
        registration_bundle=_registration_bundle(
            manifest,
            _RegistrationService(),
        ),
    )

    with pytest.raises(MigrationBundleMismatchError):
        executor.execute(_expand_phase_invocation(manifest))

    assert source_verifier.calls == 1
    assert control_verifier.calls == 0
    assert tenant_verifier.calls == 0


def test_complete_registry_builder_accepts_all_concrete_phase_bundles(
    tmp_path,
):
    manifest = _manifest()
    tenant_factory = _RecordingFactory()
    control_factory = _RecordingFactory()
    policy, reconciliation_runner = _policy_and_runner()

    registry = build_default_migration_executor_registry(
        source_preflight_bundle=DefaultMigrationSourcePreflightBundle(
            verifier=_StaticVerifier(object()),
        ),
        migration_bundle_evidence=build_default_migration_bundle_evidence(
            Path(__file__).resolve().parents[2]
        ),
        infrastructure_bundle=DefaultMigrationExpandInfrastructureBundle(
            control_verifier=_StaticVerifier(object()),
            tenant_verifier=_StaticVerifier(object()),
        ),
        registration_bundle=_registration_bundle(
            manifest,
            _RegistrationService(),
        ),
        backfill_bundle=_bundle(
            manifest,
            tenant_factory,
            control_factory,
        ),
        historical_boundary=_historical_boundary(manifest),
        historical_snapshot_step=VerifiedEmptyHistoricalSnapshotsStep(
            tenant_session_factory=tenant_factory,
            expected_schema_generation=3,
        ),
        reconciliation_policy=policy,
        reconciliation_runner=reconciliation_runner,
        application_enforcement_bundle=(
            DefaultMigrationApplicationEnforcementBundle(
                control_session_factory=control_factory,
                journal_store=MigrationJournalFileStore(
                    tmp_path / "journal.json"
                ),
                verifier=_StaticVerifier(object()),
            )
        ),
        database_jobs_enforcement_bundle=(
            DefaultMigrationDatabaseJobsEnforcementBundle(
                verifier=_StaticVerifier(object()),
            )
        ),
        contract_enforcement_bundle=(
            DefaultMigrationContractEnforcementBundle(
                verifier=_StaticVerifier(object()),
            )
        ),
    )

    assert tuple(registry) == tuple(MigrationPhase)
    assert [step.name for step in registry.expand.steps] == [
        "source_migration_preflight",
        "migration_bundle",
        "control_schema_expand",
        "tenant_schema_expand",
        "in_place_registration",
    ]
    assert [step.name for step in registry.backfill_verify.steps] == [
        "warehouse_backfill",
        "express_type_backfill",
        "planned_logistics_backfill",
        "structured_address_backfill",
        "logical_accessory_backfill",
        "integration_metadata_backfill",
        "historical_snapshots",
    ]
    assert registry.application_enforce.steps[0].name == (
        "application_enforcement"
    )
    assert registry.database_jobs_enforce.steps[0].name == (
        "database_jobs_enforcement"
    )
    assert registry.contract.steps[0].name == "contract_enforcement"
