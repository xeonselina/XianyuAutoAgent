"""Exact five-phase executor registry for the default migration command."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

from inventory_control.default_migration import (
    DefaultHistoricalSnapshotBoundaryEvidence,
    DefaultMigrationBundleEvidence,
    DefaultMigrationPhaseExecutor,
    DefaultMigrationPhaseStep,
    DefaultMigrationReconciliationRunner,
    MigrationEvidenceError,
    MigrationPhase,
    OrderedDefaultMigrationPhaseExecutor,
    ReconciledDefaultMigrationBackfillExecutor,
    ReconciliationPolicy,
)

from .default_phase_adapters import (
    DefaultMigrationApplicationEnforcementBundle,
    DefaultMigrationContractEnforcementBundle,
    DefaultMigrationDatabaseJobsEnforcementBundle,
    DefaultMigrationExpandInfrastructureBundle,
    DefaultMigrationRegistrationBundle,
    DefaultMigrationSourcePreflightBundle,
    ResolvedDefaultMigrationBackfillBundle,
    build_default_migration_application_enforce_executor,
    build_default_migration_backfill_executor,
    build_default_migration_contract_executor,
    build_default_migration_database_jobs_enforce_executor,
    build_verified_default_migration_expand_executor,
)


@dataclass(frozen=True, slots=True, repr=False)
class DefaultMigrationExecutorRegistry(
    Mapping[MigrationPhase, DefaultMigrationPhaseExecutor]
):
    expand: OrderedDefaultMigrationPhaseExecutor = field(repr=False)
    backfill_verify: ReconciledDefaultMigrationBackfillExecutor = field(
        repr=False
    )
    application_enforce: OrderedDefaultMigrationPhaseExecutor = field(
        repr=False
    )
    database_jobs_enforce: OrderedDefaultMigrationPhaseExecutor = field(
        repr=False
    )
    contract: OrderedDefaultMigrationPhaseExecutor = field(repr=False)

    def __post_init__(self) -> None:
        expected = (
            (self.expand, MigrationPhase.EXPAND),
            (self.application_enforce, MigrationPhase.APPLICATION_ENFORCE),
            (
                self.database_jobs_enforce,
                MigrationPhase.DATABASE_JOBS_ENFORCE,
            ),
            (self.contract, MigrationPhase.CONTRACT),
        )
        if (
            not isinstance(
                self.backfill_verify,
                ReconciledDefaultMigrationBackfillExecutor,
            )
            or any(
                not isinstance(executor, OrderedDefaultMigrationPhaseExecutor)
                or executor.phase is not phase
                for executor, phase in expected
            )
        ):
            raise MigrationEvidenceError(
                "default migration executor registry is invalid"
            )

    def __getitem__(
        self,
        phase: MigrationPhase,
    ) -> DefaultMigrationPhaseExecutor:
        if not isinstance(phase, MigrationPhase):
            raise KeyError(phase)
        return {
            MigrationPhase.EXPAND: self.expand,
            MigrationPhase.BACKFILL_VERIFY: self.backfill_verify,
            MigrationPhase.APPLICATION_ENFORCE: self.application_enforce,
            MigrationPhase.DATABASE_JOBS_ENFORCE: (
                self.database_jobs_enforce
            ),
            MigrationPhase.CONTRACT: self.contract,
        }[phase]

    def __iter__(self) -> Iterator[MigrationPhase]:
        return iter(MigrationPhase)

    def __len__(self) -> int:
        return len(MigrationPhase)

    def __repr__(self) -> str:
        return "DefaultMigrationExecutorRegistry(phases=5, executors='<bound>')"


def build_default_migration_executor_registry(
    *,
    source_preflight_bundle: DefaultMigrationSourcePreflightBundle,
    migration_bundle_evidence: DefaultMigrationBundleEvidence,
    infrastructure_bundle: DefaultMigrationExpandInfrastructureBundle,
    registration_bundle: DefaultMigrationRegistrationBundle,
    backfill_bundle: ResolvedDefaultMigrationBackfillBundle,
    historical_boundary: DefaultHistoricalSnapshotBoundaryEvidence,
    historical_snapshot_step: DefaultMigrationPhaseStep,
    reconciliation_policy: ReconciliationPolicy,
    reconciliation_runner: DefaultMigrationReconciliationRunner,
    application_enforcement_bundle: (
        DefaultMigrationApplicationEnforcementBundle
    ),
    database_jobs_enforcement_bundle: (
        DefaultMigrationDatabaseJobsEnforcementBundle
    ),
    contract_enforcement_bundle: DefaultMigrationContractEnforcementBundle,
) -> DefaultMigrationExecutorRegistry:
    """Build the command's exact five phases from reviewed adapter inputs.

    The individual phase builders remain the only owners of phase-specific
    validation.  This function fixes their dependency order in one place and
    prevents hosts from omitting a phase or substituting an unverified expand
    executor while wiring the CLI.
    """

    return DefaultMigrationExecutorRegistry(
        expand=build_verified_default_migration_expand_executor(
            source_preflight_bundle=source_preflight_bundle,
            migration_bundle_evidence=migration_bundle_evidence,
            infrastructure_bundle=infrastructure_bundle,
            registration_bundle=registration_bundle,
        ),
        backfill_verify=build_default_migration_backfill_executor(
            bundle=backfill_bundle,
            historical_boundary=historical_boundary,
            historical_snapshot_step=historical_snapshot_step,
            policy=reconciliation_policy,
            reconciliation_runner=reconciliation_runner,
        ),
        application_enforce=(
            build_default_migration_application_enforce_executor(
                bundle=application_enforcement_bundle,
            )
        ),
        database_jobs_enforce=(
            build_default_migration_database_jobs_enforce_executor(
                bundle=database_jobs_enforcement_bundle,
            )
        ),
        contract=build_default_migration_contract_executor(
            bundle=contract_enforcement_bundle,
        ),
    )


__all__ = [
    "DefaultMigrationExecutorRegistry",
    "build_default_migration_executor_registry",
]
