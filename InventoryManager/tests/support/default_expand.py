"""Reusable end-to-end expand composition for isolated SQL databases."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app import db
from app.models.database_identity import TenantDatabaseIdentity
from app.services.migration import (
    DefaultControlInstallationMarkerObserver,
    DefaultExpandAlembicBinding,
    DefaultMigrationExpandInfrastructureBundle,
    DefaultMigrationRegistrationBundle,
    DefaultMigrationSourcePreflightBundle,
    DefaultSourceBaselineEvidence,
    DefaultTenantDatabaseIdentityEstablisher,
    DefaultTenantRouteRegistration,
    QualifiedDefaultControlExpandVerifier,
    QualifiedDefaultTenantExpandVerifier,
    build_verified_default_migration_expand_executor,
)
from inventory_control import ControlBase
from inventory_control.crypto import RootKey
from inventory_control.default_migration import (
    DefaultMigrationRunner,
    DefaultMySqlTenantGrantMatrixObservation,
    DefaultSchemaQualificationTarget,
    DefaultTenantMigrationManifest,
    ExplicitConnectionAlembicQualificationRunner,
    MigrationExecutionMode,
    MigrationJournalFileStore,
    MigrationPhase,
    MigrationPhaseRunOutcome,
    bind_default_tenant_identity_inputs,
    build_default_migration_bundle_evidence,
)
from inventory_control.default_migration.historical_boundary import (
    HISTORICAL_BOUNDARY_COUNT_KEYS,
    DefaultHistoricalSnapshotBoundaryEvidence,
    DefaultSourceMigrationPreflightEvidence,
    HistoricalSnapshotDisposition,
)
from inventory_control.models import Installation, Tenant, TenantDatabase
from tests.support.tenant_migration import build_migration_segment_baseline


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"
TENANT_MIGRATIONS = PROJECT_ROOT / "migrations"
CONTROL_HEAD = "202608230038"
TENANT_BASELINE = "20260807_damage_notes"
TENANT_HEAD = "20260824_legacy_history"
NOW = datetime(2026, 8, 22, 16, 0, tzinfo=timezone.utc)
TENANT_UUID = UUID("8a000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("8a000000-0000-4000-8000-000000000002")
PLAN_UUID = UUID("8a000000-0000-4000-8000-000000000003")
INSTALLATION_UUID = "8a000000-0000-4000-8000-000000000004"
INSTALLATION_FINGERPRINT = "a" * 64


class TenantGrantMatrixVerifier(Protocol):
    def verify(self) -> DefaultMySqlTenantGrantMatrixObservation: ...


class _PinnedSourcePreflightVerifier:
    """Synthetic source fact for the isolated expand composition only."""

    def verify(self, invocation):
        manifest = invocation.phase_invocation.manifest
        source_baseline = DefaultSourceBaselineEvidence(
            source_schema_name=manifest.source_schema_name,
            baseline_migration_id=manifest.baseline_migration_id,
            database_profile="mysql-8.0.30+",
            server_version="8.0.46",
            table_count=0,
            total_rows=0,
            schema_inventory_digest=_digest("synthetic-source-schema"),
            row_count_digest=_digest("synthetic-source-counts"),
            source_snapshot_digest=manifest.source_snapshot_digest,
        )
        return DefaultSourceMigrationPreflightEvidence(
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


@dataclass(frozen=True, slots=True)
class CompleteExpandObservation:
    phase_result_digest: bytes
    tenant_uuid: UUID
    database_uuid: UUID
    schema_generation: int
    tenant_status: str
    route_status: str
    route_schema_version: str


def run_complete_expand_composition(
    *,
    control_qualification_engine: Engine,
    control_apply_engine: Engine,
    tenant_qualification_engine: Engine,
    tenant_apply_engine: Engine,
    qualification_target: DefaultSchemaQualificationTarget,
    grant_matrix_verifier: TenantGrantMatrixVerifier,
    journal_path: Path,
    database_instance_key: str,
) -> CompleteExpandObservation:
    """Run control/tenant expand, identity establishment and registration."""

    engines = (
        control_qualification_engine,
        control_apply_engine,
        tenant_qualification_engine,
        tenant_apply_engine,
    )
    if (
        len({id(engine) for engine in engines}) != len(engines)
        or not isinstance(qualification_target, DefaultSchemaQualificationTarget)
        or not callable(getattr(grant_matrix_verifier, "verify", None))
        or not isinstance(journal_path, Path)
        or not journal_path.is_absolute()
        or not isinstance(database_instance_key, str)
        or not database_instance_key
    ):
        raise TypeError("complete expand composition inputs are invalid")

    control_runner = ExplicitConnectionAlembicQualificationRunner(
        script_location=CONTROL_MIGRATIONS,
        target_metadata=ControlBase.metadata,
        schema_head=CONTROL_HEAD,
    )
    tenant_runner = ExplicitConnectionAlembicQualificationRunner(
        script_location=TENANT_MIGRATIONS,
        target_metadata=db.metadata,
        schema_head=TENANT_HEAD,
        baseline_revision=TENANT_BASELINE,
    )
    for engine in (
        control_qualification_engine,
        control_apply_engine,
    ):
        build_migration_segment_baseline(
            engine,
            script_location=CONTROL_MIGRATIONS,
            target_metadata=ControlBase.metadata,
            schema_head=CONTROL_HEAD,
            baseline_revision=None,
        )
    for engine in (
        tenant_qualification_engine,
        tenant_apply_engine,
    ):
        build_migration_segment_baseline(
            engine,
            script_location=TENANT_MIGRATIONS,
            target_metadata=db.metadata,
            schema_head=TENANT_HEAD,
            baseline_revision=TENANT_BASELINE,
        )

    with control_apply_engine.connect() as connection:
        control_runner.apply(connection, target=qualification_target)
    with control_apply_engine.begin() as connection:
        connection.execute(
            sa.insert(Installation).values(
                id=INSTALLATION_UUID,
                marker_fingerprint=INSTALLATION_FINGERPRINT,
                row_version=1,
                created_at=NOW.replace(tzinfo=None),
            )
        )

    identity_inputs = bind_default_tenant_identity_inputs(
        root_key=RootKey(version=1, material=bytes(range(32))),
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        migration_idempotency_key="complete-expand-composition-v1",
        display_name="现有公司",
        first_admin_phone="13800138000",
    )
    migration_bundle = build_default_migration_bundle_evidence(PROJECT_ROOT)
    manifest = DefaultTenantMigrationManifest(
        migration_idempotency_key="complete-expand-composition-v1",
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        source_schema_name="inventory_management_test",
        baseline_migration_id=TENANT_BASELINE,
        core_plan_revision_uuid=PLAN_UUID,
        control_schema_head=migration_bundle.control_schema_head,
        tenant_schema_head=migration_bundle.tenant_schema_head,
        source_snapshot_digest=_digest("source-snapshot"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=migration_bundle.bundle_digest,
        display_name_input_commitment=identity_inputs.display_name_commitment,
        first_admin_phone_input_commitment=(
            identity_inputs.first_admin_phone_commitment
        ),
    )
    control_factory = sessionmaker(
        bind=control_apply_engine,
        expire_on_commit=False,
    )
    tenant_factory = sessionmaker(
        bind=tenant_apply_engine,
        expire_on_commit=False,
    )
    infrastructure = DefaultMigrationExpandInfrastructureBundle(
        control_verifier=QualifiedDefaultControlExpandVerifier(
            alembic=DefaultExpandAlembicBinding(
                qualification_connection_factory=(
                    lambda: control_qualification_engine.connect()
                ),
                qualification_target=qualification_target,
                apply_connection_factory=(
                    lambda: control_apply_engine.connect()
                ),
                apply_target=qualification_target,
                runner=control_runner,
            ),
            control_account_grants_observer=lambda: _digest(
                "control-grants-and-denial"
            ),
            installation_marker_observer=(
                DefaultControlInstallationMarkerObserver(
                    expected_installation_fingerprint=(
                        INSTALLATION_FINGERPRINT
                    )
                )
            ),
        ),
        tenant_verifier=QualifiedDefaultTenantExpandVerifier(
            alembic=DefaultExpandAlembicBinding(
                qualification_connection_factory=(
                    lambda: tenant_qualification_engine.connect()
                ),
                qualification_target=qualification_target,
                apply_connection_factory=lambda: tenant_apply_engine.connect(),
                apply_target=qualification_target,
                runner=tenant_runner,
            ),
            database_identity_establisher=(
                DefaultTenantDatabaseIdentityEstablisher(schema_generation=1)
            ),
            grant_matrix_verifier=grant_matrix_verifier,
        ),
    )
    route = DefaultTenantRouteRegistration(
        database_instance_key=database_instance_key,
        schema_generation=1,
        schema_digest=_digest("tenant-schema"),
        dml_username="tenant_dml_g1",
        dml_credential_generation=1,
        dml_root_key_version=1,
        dml_derivation_version=1,
        platform_read_username="platform_read_g1",
        platform_read_credential_generation=1,
        platform_read_root_key_version=1,
        platform_read_derivation_version=1,
    )
    executor = build_verified_default_migration_expand_executor(
        source_preflight_bundle=DefaultMigrationSourcePreflightBundle(
            verifier=_PinnedSourcePreflightVerifier()
        ),
        migration_bundle_evidence=migration_bundle,
        infrastructure_bundle=infrastructure,
        registration_bundle=DefaultMigrationRegistrationBundle(
            tenant_session_factory=tenant_factory,
            control_session_factory=control_factory,
            identity_inputs=identity_inputs,
            route=route,
        ),
    )
    journal_store = MigrationJournalFileStore(journal_path)
    journal_store.initialize(manifest)
    migration_runner = DefaultMigrationRunner(journal_store, clock=lambda: NOW)
    completed = migration_runner.run_phase(
        manifest,
        phase=MigrationPhase.EXPAND,
        mode=MigrationExecutionMode.APPLY,
        executor=executor,
    )
    replayed = migration_runner.run_phase(
        manifest,
        phase=MigrationPhase.EXPAND,
        mode=MigrationExecutionMode.APPLY,
        executor=executor,
    )
    if (
        completed.evidence is None
        or replayed.outcome is not MigrationPhaseRunOutcome.REPLAYED
        or replayed.evidence != completed.evidence
        or journal_store.load().next_phase is not MigrationPhase.BACKFILL_VERIFY
    ):
        raise AssertionError("complete expand composition did not replay")

    with tenant_factory() as session:
        identity = session.scalar(sa.select(TenantDatabaseIdentity))
        if identity is None:
            raise AssertionError("tenant identity was not established")
        tenant_uuid = UUID(identity.tenant_id)
        database_uuid = UUID(identity.database_uuid)
        schema_generation = identity.schema_generation
    with control_factory() as session:
        tenant = session.get(Tenant, str(TENANT_UUID))
        route_row = session.get(TenantDatabase, str(TENANT_UUID))
        if tenant is None or route_row is None:
            raise AssertionError("control registration was not established")
        observation = CompleteExpandObservation(
            phase_result_digest=completed.evidence.result_state_digest,
            tenant_uuid=tenant_uuid,
            database_uuid=database_uuid,
            schema_generation=schema_generation,
            tenant_status=tenant.status,
            route_status=route_row.status,
            route_schema_version=route_row.schema_version,
        )
    if (
        observation.tenant_uuid != TENANT_UUID
        or observation.database_uuid != DATABASE_UUID
        or observation.schema_generation != 1
        or observation.tenant_status != "provisioning"
        or observation.route_status != "provisional"
        or observation.route_schema_version != TENANT_HEAD
    ):
        raise AssertionError("complete expand composition facts are invalid")
    return observation


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


__all__ = [
    "CompleteExpandObservation",
    "run_complete_expand_composition",
]
