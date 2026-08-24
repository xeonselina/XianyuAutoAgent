"""Concrete phase-step adapters for resolved default-tenant backfills.

Each step opens a fresh, explicitly-owned control or tenant transaction,
invokes the already implemented idempotent domain backfill, commits only on a
complete result, and returns replay-stable evidence to the resumable migration
runner.  The adapters never call providers or printers.

The module supports both the strictly empty-history case and D68's approved
non-empty ``legacy_unattributed`` adapter.  Neither path gives legacy rows a
credential revision or provider/printing authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from sqlalchemy.orm import Session

from inventory_control.default_migration import (
    DefaultMigrationBundleEvidence,
    DefaultMigrationPhaseStep,
    DefaultMigrationReconciliationRunner,
    DefaultMigrationStepInvocation,
    DefaultMigrationStepResult,
    DefaultTenantIdentityInputs,
    MigrationJournalFileStore,
    MigrationEvidenceError,
    MigrationPhase,
    OrderedDefaultMigrationPhaseExecutor,
    ReconciledDefaultMigrationBackfillExecutor,
    ReconciliationPolicy,
)
from inventory_control.default_migration.historical_boundary import (
    DefaultHistoricalBoundaryError,
    DefaultHistoricalSnapshotBoundaryEvidence,
    DefaultSourceMigrationPreflightEvidence,
    HistoricalSnapshotDisposition,
)

from .default_tenant_registration import (
    DefaultTenantInPlaceRegistrationService,
    DefaultTenantRouteRegistration,
)
from .default_application_enforce import (
    DefaultApplicationEnforcementEvidence,
    DefaultTenantApplicationEnforcementService,
)
from .default_database_jobs_enforce import (
    DefaultDatabaseJobsEnforcementEvidence,
)
from .default_contract_enforce import DefaultContractEnforcementEvidence
from .default_expand_enforce import (
    DefaultControlExpandEvidence,
    DefaultTenantExpandEvidence,
)
from .default_source_baseline import DefaultSourceBaselineEvidence
from .default_warehouse_backfill import (
    DefaultWarehouseBackfillService,
    DefaultWarehouseProfile,
)
from .express_type_backfill import (
    ExpressTypeBackfillManifest,
    ExpressTypeBackfillService,
)
from .empty_historical_snapshot import EmptyHistoricalSnapshotVerifier
from .legacy_unattributed_history import (
    LEGACY_UNATTRIBUTED_HISTORY_POLICY_REVISION,
    LegacyUnattributedHistoryBackfillService,
)
from .integration_metadata_backfill import (
    IntegrationMetadataBackfillPlan,
    IntegrationMetadataBackfillService,
)
from .logical_accessory_backfill import (
    LogicalAccessoryBackfillPlan,
    LogicalAccessoryBackfillService,
)
from .planned_logistics_backfill import (
    PlannedLogisticsBackfillPlan,
    PlannedLogisticsBackfillService,
)
from .structured_address_backfill import (
    StructuredAddressBackfillPlan,
    StructuredAddressBackfillService,
)


SessionFactory = Callable[[], Session]


class _WarehouseService(Protocol):
    def backfill(self, session: Session, **kwargs: Any) -> Any: ...


class _BackfillService(Protocol):
    def backfill(self, session: Session, **kwargs: Any) -> Any: ...


class _RegistrationService(Protocol):
    def write_tenant_database_identity(
        self,
        session: Session,
        **kwargs: Any,
    ) -> Any: ...

    def write_control_registration(
        self,
        session: Session,
        **kwargs: Any,
    ) -> Any: ...


class _EmptyHistoricalSnapshotVerifier(Protocol):
    def verify(self, session: Session, **kwargs: Any) -> Any: ...


class _LegacyUnattributedHistoryService(Protocol):
    def backfill(self, session: Session, **kwargs: Any) -> Any: ...


class _ApplicationEnforcementVerifier(Protocol):
    def verify(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultApplicationEnforcementEvidence: ...


class _ApplicationEnforcementService(Protocol):
    def publish(self, session: Session, **kwargs: Any) -> Any: ...


class _DatabaseJobsEnforcementVerifier(Protocol):
    def verify(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultDatabaseJobsEnforcementEvidence: ...


class _ContractEnforcementVerifier(Protocol):
    def verify(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultContractEnforcementEvidence: ...


class _ControlExpandVerifier(Protocol):
    def verify(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultControlExpandEvidence: ...


class _TenantExpandVerifier(Protocol):
    def verify(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultTenantExpandEvidence: ...


class _SourceBaselineVerifier(Protocol):
    def verify(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultSourceBaselineEvidence: ...


class _SourcePreflightVerifier(Protocol):
    def verify(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultSourceMigrationPreflightEvidence: ...


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultMigrationRegistrationBundle:
    """Bound sessions and controlled inputs for in-place expand registration."""

    tenant_session_factory: SessionFactory = field(repr=False)
    control_session_factory: SessionFactory = field(repr=False)
    identity_inputs: DefaultTenantIdentityInputs = field(repr=False)
    route: DefaultTenantRouteRegistration
    registration_service: _RegistrationService = field(
        default_factory=DefaultTenantInPlaceRegistrationService,
        repr=False,
    )

    def __post_init__(self) -> None:
        if (
            not callable(self.tenant_session_factory)
            or not callable(self.control_session_factory)
            or not isinstance(self.identity_inputs, DefaultTenantIdentityInputs)
            or not isinstance(self.route, DefaultTenantRouteRegistration)
            or not callable(
                getattr(
                    self.registration_service,
                    "write_tenant_database_identity",
                    None,
                )
            )
            or not callable(
                getattr(
                    self.registration_service,
                    "write_control_registration",
                    None,
                )
            )
        ):
            raise MigrationEvidenceError(
                "default migration registration bundle is invalid"
            )

    def __repr__(self) -> str:
        return (
            "DefaultMigrationRegistrationBundle("
            f"schema_generation={self.route.schema_generation!r}, "
            "identity_inputs='<redacted>', sessions='<bound>')"
        )


@dataclass(frozen=True, slots=True)
class DefaultTenantInPlaceRegistrationStep:
    bundle: DefaultMigrationRegistrationBundle
    name: str = "in_place_registration"

    def execute(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultMigrationStepResult:
        manifest = invocation.phase_invocation.manifest
        tenant_identity = _run_in_transaction(
            self.bundle.tenant_session_factory,
            lambda session: (
                self.bundle.registration_service.write_tenant_database_identity(
                    session,
                    manifest=manifest,
                    schema_generation=self.bundle.route.schema_generation,
                )
            ),
        )
        control_registration = _run_in_transaction(
            self.bundle.control_session_factory,
            lambda session: (
                self.bundle.registration_service.write_control_registration(
                    session,
                    manifest=manifest,
                    identity_inputs=self.bundle.identity_inputs,
                    tenant_identity=tenant_identity,
                    route=self.bundle.route,
                )
            ),
        )
        return _result(
            invocation,
            self.name,
            _canonical_digest(
                {
                    "admin_membership_uuid": str(
                        control_registration.admin_membership_uuid
                    ),
                    "admin_user_uuid": str(
                        control_registration.admin_user_uuid
                    ),
                    "database_uuid": str(control_registration.database_uuid),
                    "identity_created_at": (
                        tenant_identity.identity_created_at.isoformat()
                    ),
                    "route_version": control_registration.route_version,
                    "schema_generation": tenant_identity.schema_generation,
                    "tenant_uuid": str(control_registration.tenant_uuid),
                }
            ),
            executor_prefix="expand",
        )


def build_default_migration_expand_executor(
    *,
    control_schema_expand_step: DefaultMigrationPhaseStep,
    tenant_schema_expand_step: DefaultMigrationPhaseStep,
    registration_bundle: DefaultMigrationRegistrationBundle,
) -> OrderedDefaultMigrationPhaseExecutor:
    """Compose schema expansion then crash-resumable in-place registration."""

    if (
        getattr(control_schema_expand_step, "name", None)
        != "control_schema_expand"
        or getattr(tenant_schema_expand_step, "name", None)
        != "tenant_schema_expand"
    ):
        raise MigrationEvidenceError(
            "explicit control and tenant schema expand steps are required"
        )
    return OrderedDefaultMigrationPhaseExecutor(
        phase=MigrationPhase.EXPAND,
        steps=(
            control_schema_expand_step,
            tenant_schema_expand_step,
            DefaultTenantInPlaceRegistrationStep(registration_bundle),
        ),
    )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultMigrationExpandInfrastructureBundle:
    control_verifier: _ControlExpandVerifier = field(repr=False)
    tenant_verifier: _TenantExpandVerifier = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not callable(getattr(self.control_verifier, "verify", None))
            or not callable(getattr(self.tenant_verifier, "verify", None))
        ):
            raise MigrationEvidenceError(
                "expand infrastructure bundle is invalid"
            )

    def __repr__(self) -> str:
        return (
            "DefaultMigrationExpandInfrastructureBundle("
            "control='<bound>', tenant='<bound>')"
        )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultMigrationSourceBaselineBundle:
    verifier: _SourceBaselineVerifier = field(repr=False)

    def __post_init__(self) -> None:
        if not callable(getattr(self.verifier, "verify", None)):
            raise MigrationEvidenceError("source baseline bundle is invalid")

    def __repr__(self) -> str:
        return "DefaultMigrationSourceBaselineBundle(verifier='<bound>')"


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultMigrationSourcePreflightBundle:
    verifier: _SourcePreflightVerifier = field(repr=False)

    def __post_init__(self) -> None:
        if not callable(getattr(self.verifier, "verify", None)):
            raise MigrationEvidenceError("source preflight bundle is invalid")

    def __repr__(self) -> str:
        return "DefaultMigrationSourcePreflightBundle(verifier='<bound>')"


@dataclass(frozen=True, slots=True)
class DefaultSourceBaselineStep:
    bundle: DefaultMigrationSourceBaselineBundle
    name: str = "source_baseline"

    def execute(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultMigrationStepResult:
        evidence = self.bundle.verifier.verify(invocation)
        if not isinstance(evidence, DefaultSourceBaselineEvidence):
            raise MigrationEvidenceError(
                "source baseline verifier returned invalid evidence"
            )
        evidence.require_manifest(invocation.phase_invocation.manifest)
        return _result(
            invocation,
            self.name,
            evidence.digest,
            executor_prefix="expand-source",
        )


@dataclass(frozen=True, slots=True)
class DefaultSourceMigrationPreflightStep:
    bundle: DefaultMigrationSourcePreflightBundle
    name: str = "source_migration_preflight"

    def execute(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultMigrationStepResult:
        evidence = self.bundle.verifier.verify(invocation)
        if not isinstance(evidence, DefaultSourceMigrationPreflightEvidence):
            raise MigrationEvidenceError(
                "source preflight verifier returned invalid evidence"
            )
        evidence.require_manifest(invocation.phase_invocation.manifest)
        return _result(
            invocation,
            self.name,
            evidence.digest,
            executor_prefix="expand-source",
        )


@dataclass(frozen=True, slots=True)
class DefaultMigrationBundleStep:
    evidence: DefaultMigrationBundleEvidence
    name: str = "migration_bundle"

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, DefaultMigrationBundleEvidence):
            raise MigrationEvidenceError("migration bundle step is invalid")

    def execute(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultMigrationStepResult:
        self.evidence.require_manifest(invocation.phase_invocation.manifest)
        return _result(
            invocation,
            self.name,
            self.evidence.bundle_digest,
            executor_prefix="expand-bundle",
        )


@dataclass(frozen=True, slots=True)
class DefaultControlSchemaExpandStep:
    bundle: DefaultMigrationExpandInfrastructureBundle
    name: str = "control_schema_expand"

    def execute(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultMigrationStepResult:
        evidence = self.bundle.control_verifier.verify(invocation)
        if not isinstance(evidence, DefaultControlExpandEvidence):
            raise MigrationEvidenceError(
                "control expand verifier returned invalid evidence"
            )
        evidence.require_manifest(invocation.phase_invocation.manifest)
        return _result(
            invocation,
            self.name,
            evidence.digest,
            executor_prefix="expand-infrastructure",
        )


@dataclass(frozen=True, slots=True)
class DefaultTenantSchemaExpandStep:
    bundle: DefaultMigrationExpandInfrastructureBundle
    name: str = "tenant_schema_expand"

    def execute(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultMigrationStepResult:
        evidence = self.bundle.tenant_verifier.verify(invocation)
        if not isinstance(evidence, DefaultTenantExpandEvidence):
            raise MigrationEvidenceError(
                "tenant expand verifier returned invalid evidence"
            )
        evidence.require_manifest(invocation.phase_invocation.manifest)
        return _result(
            invocation,
            self.name,
            evidence.digest,
            executor_prefix="expand-infrastructure",
        )


def build_verified_default_migration_expand_executor(
    *,
    source_preflight_bundle: DefaultMigrationSourcePreflightBundle,
    migration_bundle_evidence: DefaultMigrationBundleEvidence,
    infrastructure_bundle: DefaultMigrationExpandInfrastructureBundle,
    registration_bundle: DefaultMigrationRegistrationBundle,
) -> OrderedDefaultMigrationPhaseExecutor:
    if (
        not isinstance(
            source_preflight_bundle,
            DefaultMigrationSourcePreflightBundle,
        )
        or not isinstance(
            migration_bundle_evidence,
            DefaultMigrationBundleEvidence,
        )
        or not isinstance(
            infrastructure_bundle,
            DefaultMigrationExpandInfrastructureBundle,
        )
    ):
        raise MigrationEvidenceError("verified expand bundle is invalid")
    expand = build_default_migration_expand_executor(
        control_schema_expand_step=DefaultControlSchemaExpandStep(
            infrastructure_bundle
        ),
        tenant_schema_expand_step=DefaultTenantSchemaExpandStep(
            infrastructure_bundle
        ),
        registration_bundle=registration_bundle,
    )
    return OrderedDefaultMigrationPhaseExecutor(
        phase=MigrationPhase.EXPAND,
        steps=(
            DefaultSourceMigrationPreflightStep(source_preflight_bundle),
            DefaultMigrationBundleStep(migration_bundle_evidence),
            *expand.steps,
        ),
    )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class ResolvedDefaultMigrationBackfillBundle:
    """Reviewed inputs for every currently resolved backfill slice."""

    tenant_session_factory: SessionFactory = field(repr=False)
    control_session_factory: SessionFactory = field(repr=False)
    expected_schema_generation: int
    warehouse_profile: DefaultWarehouseProfile
    express_type_manifest: ExpressTypeBackfillManifest
    planned_logistics_plan: PlannedLogisticsBackfillPlan
    structured_address_plan: StructuredAddressBackfillPlan
    logical_accessory_plan: LogicalAccessoryBackfillPlan
    integration_metadata_plan: IntegrationMetadataBackfillPlan
    express_type_service: _BackfillService = field(repr=False)
    warehouse_service: _WarehouseService = field(
        default_factory=DefaultWarehouseBackfillService,
        repr=False,
    )
    planned_logistics_service: _BackfillService = field(
        default_factory=PlannedLogisticsBackfillService,
        repr=False,
    )
    structured_address_service: _BackfillService = field(
        default_factory=StructuredAddressBackfillService,
        repr=False,
    )
    logical_accessory_service: _BackfillService = field(
        default_factory=LogicalAccessoryBackfillService,
        repr=False,
    )
    integration_metadata_service: _BackfillService = field(
        default_factory=IntegrationMetadataBackfillService,
        repr=False,
    )

    def __post_init__(self) -> None:
        if (
            not callable(self.tenant_session_factory)
            or not callable(self.control_session_factory)
            or isinstance(self.expected_schema_generation, bool)
            or not isinstance(self.expected_schema_generation, int)
            or self.expected_schema_generation <= 0
            or not isinstance(self.warehouse_profile, DefaultWarehouseProfile)
            or not isinstance(
                self.express_type_manifest,
                ExpressTypeBackfillManifest,
            )
            or not isinstance(
                self.planned_logistics_plan,
                PlannedLogisticsBackfillPlan,
            )
            or not isinstance(
                self.structured_address_plan,
                StructuredAddressBackfillPlan,
            )
            or not isinstance(
                self.logical_accessory_plan,
                LogicalAccessoryBackfillPlan,
            )
            or not isinstance(
                self.integration_metadata_plan,
                IntegrationMetadataBackfillPlan,
            )
            or any(
                not callable(getattr(service, "backfill", None))
                for service in (
                    self.warehouse_service,
                    self.express_type_service,
                    self.planned_logistics_service,
                    self.structured_address_service,
                    self.logical_accessory_service,
                    self.integration_metadata_service,
                )
            )
        ):
            raise MigrationEvidenceError(
                "resolved default migration backfill bundle is invalid"
            )

    def __repr__(self) -> str:
        return (
            "ResolvedDefaultMigrationBackfillBundle("
            f"expected_schema_generation={self.expected_schema_generation!r}, "
            "inputs='<reviewed>', sessions='<bound>')"
        )


@dataclass(frozen=True, slots=True)
class _WarehouseBackfillStep:
    bundle: ResolvedDefaultMigrationBackfillBundle
    name: str = "warehouse_backfill"

    def execute(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultMigrationStepResult:
        manifest = invocation.phase_invocation.manifest
        result = _run_in_transaction(
            self.bundle.tenant_session_factory,
            lambda session: self.bundle.warehouse_service.backfill(
                session,
                tenant_uuid=manifest.tenant_uuid,
                database_uuid=manifest.database_uuid,
                expected_schema_generation=(
                    self.bundle.expected_schema_generation
                ),
                baseline_migration_id=manifest.baseline_migration_id,
                profile=self.bundle.warehouse_profile,
            ),
        )
        result_digest = _canonical_digest(
            {
                "device_count": len(result.assigned_device_ids)
                + result.preserved_assigned_device_count,
                "setup_state": result.setup_state,
                "warehouse_id": result.warehouse_id,
                "warehouse_uuid": str(result.warehouse_uuid),
            }
        )
        return _result(invocation, self.name, result_digest)


@dataclass(frozen=True, slots=True)
class _ExpressTypeBackfillStep:
    bundle: ResolvedDefaultMigrationBackfillBundle
    name: str = "express_type_backfill"

    def execute(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultMigrationStepResult:
        result = _run_in_transaction(
            self.bundle.tenant_session_factory,
            lambda session: self.bundle.express_type_service.backfill(
                session,
                manifest=self.bundle.express_type_manifest,
            ),
        )
        if result.verification_passed is not True:
            raise MigrationEvidenceError(
                "express type backfill has unsupported source states"
            )
        return _result(invocation, self.name, _digest(result.report_digest))


@dataclass(frozen=True, slots=True)
class _PlannedLogisticsBackfillStep:
    bundle: ResolvedDefaultMigrationBackfillBundle
    name: str = "planned_logistics_backfill"

    def execute(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultMigrationStepResult:
        manifest = invocation.phase_invocation.manifest
        result = _run_in_transaction(
            self.bundle.tenant_session_factory,
            lambda session: self.bundle.planned_logistics_service.backfill(
                session,
                manifest=manifest,
                expected_schema_generation=(
                    self.bundle.expected_schema_generation
                ),
                plan=self.bundle.planned_logistics_plan,
            ),
        )
        return _result(invocation, self.name, _digest(result.result_digest))


@dataclass(frozen=True, slots=True)
class _StructuredAddressBackfillStep:
    bundle: ResolvedDefaultMigrationBackfillBundle
    name: str = "structured_address_backfill"

    def execute(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultMigrationStepResult:
        manifest = invocation.phase_invocation.manifest
        result = _run_in_transaction(
            self.bundle.tenant_session_factory,
            lambda session: self.bundle.structured_address_service.backfill(
                session,
                manifest=manifest,
                expected_schema_generation=(
                    self.bundle.expected_schema_generation
                ),
                plan=self.bundle.structured_address_plan,
            ),
        )
        return _result(invocation, self.name, _digest(result.result_digest))


@dataclass(frozen=True, slots=True)
class _LogicalAccessoryBackfillStep:
    bundle: ResolvedDefaultMigrationBackfillBundle
    name: str = "logical_accessory_backfill"

    def execute(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultMigrationStepResult:
        manifest = invocation.phase_invocation.manifest
        result = _run_in_transaction(
            self.bundle.tenant_session_factory,
            lambda session: self.bundle.logical_accessory_service.backfill(
                session,
                manifest=manifest,
                expected_schema_generation=(
                    self.bundle.expected_schema_generation
                ),
                plan=self.bundle.logical_accessory_plan,
            ),
        )
        return _result(invocation, self.name, _digest(result.result_digest))


@dataclass(frozen=True, slots=True)
class _IntegrationMetadataBackfillStep:
    bundle: ResolvedDefaultMigrationBackfillBundle
    name: str = "integration_metadata_backfill"

    def execute(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultMigrationStepResult:
        manifest = invocation.phase_invocation.manifest
        result = _run_in_transaction(
            self.bundle.control_session_factory,
            lambda session: self.bundle.integration_metadata_service.backfill(
                session,
                manifest=manifest,
                plan=self.bundle.integration_metadata_plan,
            ),
        )
        integrations = []
        for item in result.integrations:
            if item.current_secret_revision_uuid is not None:
                raise MigrationEvidenceError(
                    "metadata backfill attempted to bind a credential revision"
                )
            integrations.append(
                {
                    "integration_uuid": item.integration_uuid,
                    "name": item.name,
                    "provider": item.provider,
                    "row_version": item.row_version,
                    "status": item.status,
                    "tenant_uuid": item.tenant_uuid,
                }
            )
        return _result(
            invocation,
            self.name,
            _canonical_digest(
                {
                    "integrations": sorted(
                        integrations,
                        key=lambda item: item["integration_uuid"],
                    ),
                    "plan_digest": _digest(result.plan_digest).hex(),
                }
            ),
        )


def resolved_default_migration_backfill_steps(
    bundle: ResolvedDefaultMigrationBackfillBundle,
) -> tuple[DefaultMigrationPhaseStep, ...]:
    """Return the resolved dependency prefix; no snapshot step is implied."""

    if not isinstance(bundle, ResolvedDefaultMigrationBackfillBundle):
        raise MigrationEvidenceError("resolved backfill bundle is invalid")
    return (
        _WarehouseBackfillStep(bundle),
        _ExpressTypeBackfillStep(bundle),
        _PlannedLogisticsBackfillStep(bundle),
        _StructuredAddressBackfillStep(bundle),
        _LogicalAccessoryBackfillStep(bundle),
        _IntegrationMetadataBackfillStep(bundle),
    )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class VerifiedEmptyHistoricalSnapshotsStep:
    """Approved historical step only when every durable hint is absent."""

    tenant_session_factory: SessionFactory = field(repr=False)
    expected_schema_generation: int
    verifier: _EmptyHistoricalSnapshotVerifier = field(
        default_factory=EmptyHistoricalSnapshotVerifier,
        repr=False,
    )
    name: str = "historical_snapshots"

    def __post_init__(self) -> None:
        if (
            not callable(self.tenant_session_factory)
            or isinstance(self.expected_schema_generation, bool)
            or not isinstance(self.expected_schema_generation, int)
            or self.expected_schema_generation < 1
            or not callable(getattr(self.verifier, "verify", None))
            or self.name != "historical_snapshots"
        ):
            raise MigrationEvidenceError(
                "verified empty historical snapshot step is invalid"
            )

    def execute(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultMigrationStepResult:
        result = _run_in_transaction(
            self.tenant_session_factory,
            lambda session: self.verifier.verify(
                session,
                manifest=invocation.phase_invocation.manifest,
                expected_schema_generation=(
                    self.expected_schema_generation
                ),
            ),
        )
        if result.verification_passed is not True or any(
            count != 0 for _key, count in result.counts
        ):
            raise MigrationEvidenceError(
                "empty historical snapshot verification did not pass"
            )
        return _result(
            invocation,
            self.name,
            _digest(result.result_digest),
            executor_prefix="verified-empty-history",
        )

    def __repr__(self) -> str:
        return (
            "VerifiedEmptyHistoricalSnapshotsStep("
            f"expected_schema_generation="
            f"{self.expected_schema_generation!r}, session='<bound>')"
        )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class VerifiedLegacyUnattributedHistoricalSnapshotsStep:
    """D68 boundary-bound, provider-free non-empty history adapter."""

    tenant_session_factory: SessionFactory = field(repr=False)
    expected_schema_generation: int
    historical_boundary: DefaultHistoricalSnapshotBoundaryEvidence
    approved_historical_boundary_digest: bytes
    approved_policy_revision: int = (
        LEGACY_UNATTRIBUTED_HISTORY_POLICY_REVISION
    )
    service: _LegacyUnattributedHistoryService = field(
        default_factory=LegacyUnattributedHistoryBackfillService,
        repr=False,
    )
    name: str = "historical_snapshots"

    def __post_init__(self) -> None:
        if (
            not callable(self.tenant_session_factory)
            or isinstance(self.expected_schema_generation, bool)
            or not isinstance(self.expected_schema_generation, int)
            or self.expected_schema_generation < 1
            or not isinstance(
                self.historical_boundary,
                DefaultHistoricalSnapshotBoundaryEvidence,
            )
            or self.historical_boundary.disposition
            is not HistoricalSnapshotDisposition.REQUIRES_APPROVED_NONEMPTY_ADAPTER
            or not isinstance(self.approved_historical_boundary_digest, bytes)
            or self.approved_historical_boundary_digest
            != self.historical_boundary.digest
            or self.approved_policy_revision
            != LEGACY_UNATTRIBUTED_HISTORY_POLICY_REVISION
            or not callable(getattr(self.service, "backfill", None))
            or self.name != "historical_snapshots"
        ):
            raise MigrationEvidenceError(
                "verified legacy-unattributed historical step is invalid"
            )

    def execute(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultMigrationStepResult:
        manifest = invocation.phase_invocation.manifest
        try:
            self.historical_boundary.require_manifest(manifest)
        except DefaultHistoricalBoundaryError:
            raise MigrationEvidenceError(
                "historical boundary does not match migration manifest"
            ) from None
        result = _run_in_transaction(
            self.tenant_session_factory,
            lambda session: self.service.backfill(
                session,
                manifest=manifest,
                expected_schema_generation=(
                    self.expected_schema_generation
                ),
                historical_boundary=self.historical_boundary,
            ),
        )
        if result.verification_passed is not True:
            raise MigrationEvidenceError(
                "legacy-unattributed historical verification did not pass"
            )
        return _result(
            invocation,
            self.name,
            _digest(result.result_digest),
            executor_prefix="verified-legacy-unattributed-history",
        )

    def __repr__(self) -> str:
        return (
            "VerifiedLegacyUnattributedHistoricalSnapshotsStep("
            f"expected_schema_generation="
            f"{self.expected_schema_generation!r}, "
            f"boundary_digest="
            f"{self.approved_historical_boundary_digest.hex()!r}, "
            "session='<bound>')"
        )


def build_default_migration_backfill_executor(
    *,
    bundle: ResolvedDefaultMigrationBackfillBundle,
    historical_boundary: DefaultHistoricalSnapshotBoundaryEvidence,
    historical_snapshot_step: DefaultMigrationPhaseStep,
    policy: ReconciliationPolicy,
    reconciliation_runner: DefaultMigrationReconciliationRunner,
) -> ReconciledDefaultMigrationBackfillExecutor:
    """Compose the complete backfill only with an approved snapshot adapter."""

    _require_historical_snapshot_step(
        historical_boundary,
        historical_snapshot_step,
    )
    return ReconciledDefaultMigrationBackfillExecutor(
        steps=(
            *resolved_default_migration_backfill_steps(bundle),
            historical_snapshot_step,
        ),
        policy=policy,
        reconciliation_runner=reconciliation_runner,
    )


def _require_historical_snapshot_step(
    boundary: DefaultHistoricalSnapshotBoundaryEvidence,
    step: DefaultMigrationPhaseStep,
) -> None:
    if (
        not isinstance(boundary, DefaultHistoricalSnapshotBoundaryEvidence)
        or getattr(step, "name", None) != "historical_snapshots"
    ):
        raise MigrationEvidenceError(
            "approved historical snapshot migration step is required"
        )
    if boundary.disposition is HistoricalSnapshotDisposition.EMPTY:
        if not isinstance(step, VerifiedEmptyHistoricalSnapshotsStep):
            raise MigrationEvidenceError(
                "empty history requires the verified empty adapter"
            )
        return
    approval_revision = getattr(step, "approved_policy_revision", None)
    if (
        isinstance(step, VerifiedEmptyHistoricalSnapshotsStep)
        or getattr(step, "approved_historical_boundary_digest", None)
        != boundary.digest
        or isinstance(approval_revision, bool)
        or not isinstance(approval_revision, int)
        or approval_revision < 1
    ):
        raise MigrationEvidenceError(
            "nonempty history requires an approved boundary-bound adapter"
        )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultMigrationApplicationEnforcementBundle:
    """Bound control transaction plus current isolated runtime verifier."""

    control_session_factory: SessionFactory = field(repr=False)
    journal_store: MigrationJournalFileStore = field(repr=False)
    verifier: _ApplicationEnforcementVerifier = field(repr=False)
    service: _ApplicationEnforcementService = field(
        default_factory=DefaultTenantApplicationEnforcementService,
        repr=False,
    )

    def __post_init__(self) -> None:
        if (
            not callable(self.control_session_factory)
            or not isinstance(self.journal_store, MigrationJournalFileStore)
            or not callable(getattr(self.verifier, "verify", None))
            or not callable(getattr(self.service, "publish", None))
        ):
            raise MigrationEvidenceError(
                "application enforcement bundle is invalid"
            )

    def __repr__(self) -> str:
        return (
            "DefaultMigrationApplicationEnforcementBundle("
            "journal='<private>', verifier='<bound>', session='<bound>')"
        )


@dataclass(frozen=True, slots=True)
class DefaultTenantApplicationEnforcementStep:
    bundle: DefaultMigrationApplicationEnforcementBundle
    name: str = "application_enforcement"

    def execute(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultMigrationStepResult:
        evidence = self.bundle.verifier.verify(invocation)
        if not isinstance(evidence, DefaultApplicationEnforcementEvidence):
            raise MigrationEvidenceError(
                "application verifier returned invalid evidence"
            )
        journal = self.bundle.journal_store.load()
        result = _run_in_transaction(
            self.bundle.control_session_factory,
            lambda session: self.bundle.service.publish(
                session,
                manifest=invocation.phase_invocation.manifest,
                journal=journal,
                evidence=evidence,
            ),
        )
        return _result(
            invocation,
            self.name,
            _digest(result.digest),
            executor_prefix="application-enforce",
        )


def build_default_migration_application_enforce_executor(
    *,
    bundle: DefaultMigrationApplicationEnforcementBundle,
) -> OrderedDefaultMigrationPhaseExecutor:
    if not isinstance(bundle, DefaultMigrationApplicationEnforcementBundle):
        raise MigrationEvidenceError(
            "application enforcement bundle is invalid"
        )
    return OrderedDefaultMigrationPhaseExecutor(
        phase=MigrationPhase.APPLICATION_ENFORCE,
        steps=(DefaultTenantApplicationEnforcementStep(bundle),),
    )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultMigrationDatabaseJobsEnforcementBundle:
    verifier: _DatabaseJobsEnforcementVerifier = field(repr=False)

    def __post_init__(self) -> None:
        if not callable(getattr(self.verifier, "verify", None)):
            raise MigrationEvidenceError(
                "database/jobs enforcement bundle is invalid"
            )

    def __repr__(self) -> str:
        return (
            "DefaultMigrationDatabaseJobsEnforcementBundle("
            "verifier='<bound>')"
        )


@dataclass(frozen=True, slots=True)
class DefaultDatabaseJobsEnforcementStep:
    bundle: DefaultMigrationDatabaseJobsEnforcementBundle
    name: str = "database_jobs_enforcement"

    def execute(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultMigrationStepResult:
        evidence = self.bundle.verifier.verify(invocation)
        if not isinstance(evidence, DefaultDatabaseJobsEnforcementEvidence):
            raise MigrationEvidenceError(
                "database/jobs verifier returned invalid evidence"
            )
        evidence.require_manifest(invocation.phase_invocation.manifest)
        return _result(
            invocation,
            self.name,
            evidence.digest,
            executor_prefix="database-jobs-enforce",
        )


def build_default_migration_database_jobs_enforce_executor(
    *,
    bundle: DefaultMigrationDatabaseJobsEnforcementBundle,
) -> OrderedDefaultMigrationPhaseExecutor:
    if not isinstance(bundle, DefaultMigrationDatabaseJobsEnforcementBundle):
        raise MigrationEvidenceError(
            "database/jobs enforcement bundle is invalid"
        )
    return OrderedDefaultMigrationPhaseExecutor(
        phase=MigrationPhase.DATABASE_JOBS_ENFORCE,
        steps=(DefaultDatabaseJobsEnforcementStep(bundle),),
    )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultMigrationContractEnforcementBundle:
    verifier: _ContractEnforcementVerifier = field(repr=False)

    def __post_init__(self) -> None:
        if not callable(getattr(self.verifier, "verify", None)):
            raise MigrationEvidenceError("contract enforcement bundle is invalid")

    def __repr__(self) -> str:
        return "DefaultMigrationContractEnforcementBundle(verifier='<bound>')"


@dataclass(frozen=True, slots=True)
class DefaultContractEnforcementStep:
    bundle: DefaultMigrationContractEnforcementBundle
    name: str = "contract_enforcement"

    def execute(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultMigrationStepResult:
        evidence = self.bundle.verifier.verify(invocation)
        if not isinstance(evidence, DefaultContractEnforcementEvidence):
            raise MigrationEvidenceError(
                "contract verifier returned invalid evidence"
            )
        evidence.require_manifest(invocation.phase_invocation.manifest)
        return _result(
            invocation,
            self.name,
            evidence.digest,
            executor_prefix="contract-enforce",
        )


def build_default_migration_contract_executor(
    *,
    bundle: DefaultMigrationContractEnforcementBundle,
) -> OrderedDefaultMigrationPhaseExecutor:
    if not isinstance(bundle, DefaultMigrationContractEnforcementBundle):
        raise MigrationEvidenceError("contract enforcement bundle is invalid")
    return OrderedDefaultMigrationPhaseExecutor(
        phase=MigrationPhase.CONTRACT,
        steps=(DefaultContractEnforcementStep(bundle),),
    )


def _run_in_transaction(
    session_factory: SessionFactory,
    operation: Callable[[Session], Any],
) -> Any:
    session = session_factory()
    if not isinstance(session, Session):
        raise MigrationEvidenceError("migration session factory is invalid")
    try:
        with session.begin():
            return operation(session)
    finally:
        session.close()


def _result(
    invocation: DefaultMigrationStepInvocation,
    step_name: str,
    result_digest: bytes,
    *,
    executor_prefix: str = "resolved-backfill",
) -> DefaultMigrationStepResult:
    return DefaultMigrationStepResult(
        step_name=step_name,
        manifest_digest=invocation.phase_invocation.manifest.digest,
        result_digest=_digest(result_digest),
        executor_reference=f"{executor_prefix}:{step_name}",
    )


def _canonical_digest(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise MigrationEvidenceError("migration step evidence is invalid") from None
    return hashlib.sha256(encoded).digest()


def _digest(value: object) -> bytes:
    if not isinstance(value, bytes) or len(value) != 32:
        raise MigrationEvidenceError("migration step digest is invalid")
    return value


__all__ = [
    "DefaultControlSchemaExpandStep",
    "DefaultContractEnforcementStep",
    "DefaultDatabaseJobsEnforcementStep",
    "DefaultMigrationApplicationEnforcementBundle",
    "DefaultMigrationDatabaseJobsEnforcementBundle",
    "DefaultMigrationContractEnforcementBundle",
    "DefaultMigrationExpandInfrastructureBundle",
    "DefaultMigrationBundleStep",
    "DefaultMigrationRegistrationBundle",
    "DefaultMigrationSourceBaselineBundle",
    "DefaultMigrationSourcePreflightBundle",
    "DefaultSourceBaselineStep",
    "DefaultSourceMigrationPreflightStep",
    "DefaultTenantApplicationEnforcementStep",
    "DefaultTenantInPlaceRegistrationStep",
    "DefaultTenantSchemaExpandStep",
    "ResolvedDefaultMigrationBackfillBundle",
    "VerifiedEmptyHistoricalSnapshotsStep",
    "VerifiedLegacyUnattributedHistoricalSnapshotsStep",
    "build_default_migration_backfill_executor",
    "build_default_migration_application_enforce_executor",
    "build_default_migration_database_jobs_enforce_executor",
    "build_default_migration_contract_executor",
    "build_default_migration_expand_executor",
    "build_verified_default_migration_expand_executor",
    "resolved_default_migration_backfill_steps",
]
