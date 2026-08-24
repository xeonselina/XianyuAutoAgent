from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.services.migration.default_contract_enforce import (
    DefaultContractEnforcementEvidence,
    DefaultContractEnforcementInputError,
)
from app.services.migration.default_executor_registry import (
    DefaultMigrationExecutorRegistry,
)
from app.services.migration.default_phase_adapters import (
    DefaultMigrationContractEnforcementBundle,
    build_default_migration_contract_executor,
)
from inventory_control.default_migration import (
    DefaultMigrationReconciliationRunner,
    DefaultMigrationRunner,
    DefaultMigrationStepResult,
    DefaultTenantMigrationManifest,
    DefaultTenantReconciliationExpectedFacts,
    MigrationEvidenceError,
    MigrationExecutionMode,
    MigrationJournal,
    MigrationJournalFileStore,
    MigrationPhase,
    MigrationPhaseEvidence,
    MigrationPhaseRunOutcome,
    OrderedDefaultMigrationPhaseExecutor,
    ReconciledDefaultMigrationBackfillExecutor,
    ReconciliationObservation,
    build_default_tenant_reconciliation_policy,
    journal_to_document,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest() -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="contract-registry-v1",
        tenant_uuid=UUID("86000000-0000-4000-8000-000000000001"),
        database_uuid=UUID("86000000-0000-4000-8000-000000000002"),
        source_schema_name="inventory_management_test",
        baseline_migration_id="baseline-v1",
        core_plan_revision_uuid=UUID(
            "86000000-0000-4000-8000-000000000003"
        ),
        control_schema_head="202608220026",
        tenant_schema_head="20260824_legacy_history",
        source_snapshot_digest=_digest("source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=_digest("name"),
        first_admin_phone_input_commitment=_digest("phone"),
    )


def _contract_evidence(manifest):
    return DefaultContractEnforcementEvidence(
        manifest_digest=manifest.digest,
        implementation_identity_digest=(
            manifest.implementation_identity_digest
        ),
        migration_bundle_digest=manifest.migration_bundle_digest,
        observation_window_digest=_digest("observation-window"),
        legacy_schema_surface_negative_digest=_digest("legacy-schema"),
        route_config_bundle_negative_digest=_digest("route-config-bundle"),
        recovery_path_negative_digest=_digest("recovery-path"),
        provider_snapshot_preservation_digest=_digest("provider-snapshot"),
    )


class _Verifier:
    def __init__(self, evidence):
        self.evidence = evidence

    def verify(self, _invocation):
        return self.evidence


def _persist_authoritative_journal(path, manifest):
    journal = MigrationJournal(
        manifest_digest=manifest.digest,
        completed=tuple(
            MigrationPhaseEvidence(
                phase=phase,
                manifest_digest=manifest.digest,
                input_state_digest=_digest(f"{phase.value}:input"),
                result_state_digest=_digest(f"{phase.value}:result"),
                completed_at=NOW,
                executor_reference=f"isolated:{phase.value}",
            )
            for phase in (
                MigrationPhase.EXPAND,
                MigrationPhase.BACKFILL_VERIFY,
                MigrationPhase.APPLICATION_ENFORCE,
                MigrationPhase.DATABASE_JOBS_ENFORCE,
            )
        ),
        tenant_aware_writes_enabled_at=NOW,
    )
    path.write_text(
        json.dumps(
            journal_to_document(journal),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n",
        encoding="ascii",
    )
    path.chmod(0o600)


def test_contract_phase_requires_authoritative_journal_and_negative_evidence(
    tmp_path,
) -> None:
    manifest = _manifest()
    journal_path = tmp_path / "journal.json"
    _persist_authoritative_journal(journal_path, manifest)
    executor = build_default_migration_contract_executor(
        bundle=DefaultMigrationContractEnforcementBundle(
            verifier=_Verifier(_contract_evidence(manifest))
        )
    )

    result = DefaultMigrationRunner(
        MigrationJournalFileStore(journal_path),
        clock=lambda: NOW,
    ).run_phase(
        manifest,
        phase=MigrationPhase.CONTRACT,
        mode=MigrationExecutionMode.APPLY,
        executor=executor,
    )

    assert result.outcome is MigrationPhaseRunOutcome.COMPLETED
    assert MigrationJournalFileStore(journal_path).load().next_phase is None


@pytest.mark.parametrize(
    "field",
    [
        "d61_legacy_authority_count",
        "legacy_writer_authority_count",
        "provider_side_effect_count",
        "print_side_effect_count",
    ],
)
def test_contract_evidence_rejects_any_remaining_authority_or_side_effect(
    field,
) -> None:
    manifest = _manifest()
    values = {
        "manifest_digest": manifest.digest,
        "implementation_identity_digest": (
            manifest.implementation_identity_digest
        ),
        "migration_bundle_digest": manifest.migration_bundle_digest,
        "observation_window_digest": _digest("observation-window"),
        "legacy_schema_surface_negative_digest": _digest("legacy-schema"),
        "route_config_bundle_negative_digest": _digest(
            "route-config-bundle"
        ),
        "recovery_path_negative_digest": _digest("recovery-path"),
        "provider_snapshot_preservation_digest": _digest(
            "provider-snapshot"
        ),
        field: 1,
    }

    with pytest.raises(DefaultContractEnforcementInputError):
        DefaultContractEnforcementEvidence(**values)


@dataclass
class _Step:
    name: str

    def execute(self, invocation):
        return DefaultMigrationStepResult(
            step_name=self.name,
            manifest_digest=invocation.phase_invocation.manifest.digest,
            result_digest=_digest(self.name),
            executor_reference=f"test:{self.name}",
        )


@dataclass
class _Collector:
    key: str
    observed: object

    def collect(self, *, manifest, requirement):
        return ReconciliationObservation(
            key=requirement.key,
            observed=self.observed,
        )


def _backfill_executor(tmp_path):
    policy = build_default_tenant_reconciliation_policy(
        DefaultTenantReconciliationExpectedFacts(
            accessory_links=0,
            credential_revisions=0,
            device_warehouse_links=0,
            legacy_double_count=0,
            rental_total_minor=0,
            orphan_count=0,
            rental_device_links=0,
            schema_digest=_digest("schema"),
            schema_generation=3,
            historical_waybills=0,
            device_rows=0,
            default_warehouse_count=1,
        )
    )
    return ReconciledDefaultMigrationBackfillExecutor(
        steps=(_Step("backfill"),),
        policy=policy,
        reconciliation_runner=DefaultMigrationReconciliationRunner(
            tuple(
                _Collector(item.key, item.expected)
                for item in policy.requirements
            )
        ),
    )


def _ordered(phase):
    return OrderedDefaultMigrationPhaseExecutor(
        phase=phase,
        steps=(_Step(phase.value),),
    )


def test_complete_registry_has_exactly_one_executor_for_each_phase(tmp_path):
    registry = DefaultMigrationExecutorRegistry(
        expand=_ordered(MigrationPhase.EXPAND),
        backfill_verify=_backfill_executor(tmp_path),
        application_enforce=_ordered(MigrationPhase.APPLICATION_ENFORCE),
        database_jobs_enforce=_ordered(
            MigrationPhase.DATABASE_JOBS_ENFORCE
        ),
        contract=_ordered(MigrationPhase.CONTRACT),
    )

    assert tuple(registry) == tuple(MigrationPhase)
    assert len(registry) == 5
    assert registry[MigrationPhase.BACKFILL_VERIFY] is (
        registry.backfill_verify
    )
    assert repr(registry) == (
        "DefaultMigrationExecutorRegistry(phases=5, executors='<bound>')"
    )


def test_registry_rejects_an_executor_bound_to_the_wrong_phase(tmp_path):
    with pytest.raises(MigrationEvidenceError, match="registry"):
        DefaultMigrationExecutorRegistry(
            expand=_ordered(MigrationPhase.APPLICATION_ENFORCE),
            backfill_verify=_backfill_executor(tmp_path),
            application_enforce=_ordered(
                MigrationPhase.APPLICATION_ENFORCE
            ),
            database_jobs_enforce=_ordered(
                MigrationPhase.DATABASE_JOBS_ENFORCE
            ),
            contract=_ordered(MigrationPhase.CONTRACT),
        )
