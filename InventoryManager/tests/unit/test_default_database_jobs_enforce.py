from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.services.migration.default_database_jobs_enforce import (
    DefaultDatabaseJobsEnforcementEvidence,
    DefaultDatabaseJobsEnforcementInputError,
)
from app.services.migration.default_phase_adapters import (
    DefaultMigrationDatabaseJobsEnforcementBundle,
    build_default_migration_database_jobs_enforce_executor,
)
from inventory_control.default_migration import (
    DefaultMigrationRunner,
    DefaultTenantMigrationManifest,
    MigrationExecutionMode,
    MigrationJournal,
    MigrationJournalFileStore,
    MigrationPhase,
    MigrationPhaseEvidence,
    MigrationPhaseRunOutcome,
    journal_to_document,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest() -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="database-jobs-enforce-v1",
        tenant_uuid=UUID("85000000-0000-4000-8000-000000000001"),
        database_uuid=UUID("85000000-0000-4000-8000-000000000002"),
        source_schema_name="inventory_management_test",
        baseline_migration_id="baseline-v1",
        core_plan_revision_uuid=UUID(
            "85000000-0000-4000-8000-000000000003"
        ),
        control_schema_head="202608220026",
        tenant_schema_head="20260823_shipping_contract",
        source_snapshot_digest=_digest("source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=_digest("name"),
        first_admin_phone_input_commitment=_digest("phone"),
    )


def _evidence(manifest):
    return DefaultDatabaseJobsEnforcementEvidence(
        manifest_digest=manifest.digest,
        implementation_identity_digest=(
            manifest.implementation_identity_digest
        ),
        migration_bundle_digest=manifest.migration_bundle_digest,
        database_grants_matrix_digest=_digest("database-grants"),
        schema_fleet_matrix_digest=_digest("schema-fleet"),
        scheduler_negative_matrix_digest=_digest("scheduler-negative"),
        durable_worker_matrix_digest=_digest("durable-worker"),
        outbox_provider_fence_matrix_digest=_digest("outbox-fence"),
        cross_schema_negative_matrix_digest=_digest("cross-schema-negative"),
    )


class _Verifier:
    def __init__(self, evidence):
        self.evidence = evidence
        self.calls = []

    def verify(self, invocation):
        self.calls.append(invocation)
        return self.evidence


def _persist_application_journal(path, manifest):
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
            )
        ),
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


def test_database_jobs_phase_records_all_bound_matrix_evidence(tmp_path):
    manifest = _manifest()
    journal_path = tmp_path / "journal.json"
    _persist_application_journal(journal_path, manifest)
    verifier = _Verifier(_evidence(manifest))
    executor = build_default_migration_database_jobs_enforce_executor(
        bundle=DefaultMigrationDatabaseJobsEnforcementBundle(
            verifier=verifier
        )
    )

    completed = DefaultMigrationRunner(
        MigrationJournalFileStore(journal_path),
        clock=lambda: NOW,
    ).run_phase(
        manifest,
        phase=MigrationPhase.DATABASE_JOBS_ENFORCE,
        mode=MigrationExecutionMode.APPLY,
        executor=executor,
    )

    assert completed.outcome is MigrationPhaseRunOutcome.COMPLETED
    assert completed.evidence.result_state_digest != bytes(32)
    assert len(verifier.calls) == 1
    journal = MigrationJournalFileStore(journal_path).load()
    assert journal.next_phase is MigrationPhase.CONTRACT
    assert journal.tenant_aware_writes_enabled_at is None


@pytest.mark.parametrize(
    "changes",
    [
        {"production_write_identity_used": True},
        {"provider_side_effect_count": 1},
        {"print_side_effect_count": 1},
    ],
)
def test_database_jobs_evidence_rejects_forbidden_test_authority(changes):
    manifest = _manifest()
    values = {
        "manifest_digest": manifest.digest,
        "implementation_identity_digest": (
            manifest.implementation_identity_digest
        ),
        "migration_bundle_digest": manifest.migration_bundle_digest,
        "database_grants_matrix_digest": _digest("database-grants"),
        "schema_fleet_matrix_digest": _digest("schema-fleet"),
        "scheduler_negative_matrix_digest": _digest("scheduler-negative"),
        "durable_worker_matrix_digest": _digest("durable-worker"),
        "outbox_provider_fence_matrix_digest": _digest("outbox-fence"),
        "cross_schema_negative_matrix_digest": _digest(
            "cross-schema-negative"
        ),
    }
    values.update(changes)

    with pytest.raises(DefaultDatabaseJobsEnforcementInputError):
        DefaultDatabaseJobsEnforcementEvidence(**values)


def test_database_jobs_evidence_cannot_cross_migration_bundle():
    manifest = _manifest()
    evidence = _evidence(manifest)
    object.__setattr__(evidence, "migration_bundle_digest", _digest("other"))

    with pytest.raises(DefaultDatabaseJobsEnforcementInputError):
        evidence.require_manifest(manifest)
