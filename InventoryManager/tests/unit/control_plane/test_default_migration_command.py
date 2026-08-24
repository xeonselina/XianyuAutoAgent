from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import pytest

import app.services.migration.default_executor_registry as registry_module
from app.services.migration import (
    DefaultMigrationExecutorRegistry,
    build_default_migration_executor_registry,
)
from inventory_control.default_migration import (
    DefaultMigrationCommand,
    DefaultMigrationReconciliationRunner,
    DefaultMigrationStepResult,
    DefaultTenantMigrationManifest,
    DefaultTenantReconciliationExpectedFacts,
    MigrationBoundaryError,
    MigrationEvidenceError,
    MigrationJournalFileStore,
    MigrationPhase,
    OrderedDefaultMigrationPhaseExecutor,
    ReconciledDefaultMigrationBackfillExecutor,
    ReconciliationObservation,
    build_default_tenant_reconciliation_policy,
    manifest_to_document,
)
from inventory_control.default_migration.cli import main


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest():
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="complete-command-v1",
        tenant_uuid=UUID("88000000-0000-4000-8000-000000000001"),
        database_uuid=UUID("88000000-0000-4000-8000-000000000002"),
        source_schema_name="inventory_management_test",
        baseline_migration_id="baseline-v1",
        core_plan_revision_uuid=UUID(
            "88000000-0000-4000-8000-000000000003"
        ),
        control_schema_head="202608220026",
        tenant_schema_head="20260823_shipping_contract",
        source_snapshot_digest=_digest("source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=_digest("name"),
        first_admin_phone_input_commitment=_digest("phone"),
    )


@dataclass
class _Step:
    name: str
    calls: list[str]

    def execute(self, invocation):
        self.calls.append(self.name)
        return DefaultMigrationStepResult(
            step_name=self.name,
            manifest_digest=invocation.phase_invocation.manifest.digest,
            result_digest=_digest(self.name),
            executor_reference=f"isolated:{self.name}",
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


def _registry(tmp_path, calls):
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
    return DefaultMigrationExecutorRegistry(
        expand=OrderedDefaultMigrationPhaseExecutor(
            phase=MigrationPhase.EXPAND,
            steps=(_Step("expand", calls),),
        ),
        backfill_verify=ReconciledDefaultMigrationBackfillExecutor(
            steps=(_Step("backfill", calls),),
            policy=policy,
            reconciliation_runner=DefaultMigrationReconciliationRunner(
                tuple(
                    _Collector(item.key, item.expected)
                    for item in policy.requirements
                )
            ),
        ),
        application_enforce=OrderedDefaultMigrationPhaseExecutor(
            phase=MigrationPhase.APPLICATION_ENFORCE,
            steps=(_Step("application", calls),),
        ),
        database_jobs_enforce=OrderedDefaultMigrationPhaseExecutor(
            phase=MigrationPhase.DATABASE_JOBS_ENFORCE,
            steps=(_Step("database_jobs", calls),),
        ),
        contract=OrderedDefaultMigrationPhaseExecutor(
            phase=MigrationPhase.CONTRACT,
            steps=(_Step("contract", calls),),
        ),
    )


def test_registry_builder_wires_all_reviewed_phase_inputs(monkeypatch, tmp_path):
    expected = _registry(tmp_path, [])
    inputs = {
        "source_preflight_bundle": object(),
        "migration_bundle_evidence": object(),
        "infrastructure_bundle": object(),
        "registration_bundle": object(),
        "backfill_bundle": object(),
        "historical_boundary": object(),
        "historical_snapshot_step": object(),
        "reconciliation_policy": object(),
        "reconciliation_runner": object(),
        "application_enforcement_bundle": object(),
        "database_jobs_enforcement_bundle": object(),
        "contract_enforcement_bundle": object(),
    }
    calls = []

    def bind(name, result):
        def builder(**kwargs):
            calls.append((name, kwargs))
            return result

        return builder

    monkeypatch.setattr(
        registry_module,
        "build_verified_default_migration_expand_executor",
        bind("expand", expected.expand),
    )
    monkeypatch.setattr(
        registry_module,
        "build_default_migration_backfill_executor",
        bind("backfill_verify", expected.backfill_verify),
    )
    monkeypatch.setattr(
        registry_module,
        "build_default_migration_application_enforce_executor",
        bind("application_enforce", expected.application_enforce),
    )
    monkeypatch.setattr(
        registry_module,
        "build_default_migration_database_jobs_enforce_executor",
        bind("database_jobs_enforce", expected.database_jobs_enforce),
    )
    monkeypatch.setattr(
        registry_module,
        "build_default_migration_contract_executor",
        bind("contract", expected.contract),
    )

    registry = build_default_migration_executor_registry(**inputs)

    assert tuple(registry) == tuple(MigrationPhase)
    assert [name for name, _kwargs in calls] == [
        "expand",
        "backfill_verify",
        "application_enforce",
        "database_jobs_enforce",
        "contract",
    ]
    assert calls[0][1] == {
        "source_preflight_bundle": inputs["source_preflight_bundle"],
        "migration_bundle_evidence": inputs["migration_bundle_evidence"],
        "infrastructure_bundle": inputs["infrastructure_bundle"],
        "registration_bundle": inputs["registration_bundle"],
    }
    assert calls[1][1] == {
        "bundle": inputs["backfill_bundle"],
        "historical_boundary": inputs["historical_boundary"],
        "historical_snapshot_step": inputs["historical_snapshot_step"],
        "policy": inputs["reconciliation_policy"],
        "reconciliation_runner": inputs["reconciliation_runner"],
    }
    assert calls[2][1] == {
        "bundle": inputs["application_enforcement_bundle"]
    }
    assert calls[3][1] == {
        "bundle": inputs["database_jobs_enforcement_bundle"]
    }
    assert calls[4][1] == {
        "bundle": inputs["contract_enforcement_bundle"]
    }


def test_command_stops_before_authority_and_contract_is_separate(tmp_path):
    manifest = _manifest()
    store = MigrationJournalFileStore(tmp_path / "journal.json")
    store.initialize(manifest)
    calls: list[str] = []
    command = DefaultMigrationCommand(
        store,
        executors=_registry(tmp_path, calls),
        clock=lambda: NOW,
    )

    pre_authority = command.run_to_authoritative_boundary(manifest)

    assert [item.phase for item in pre_authority.runs] == [
        MigrationPhase.EXPAND,
        MigrationPhase.BACKFILL_VERIFY,
        MigrationPhase.APPLICATION_ENFORCE,
        MigrationPhase.DATABASE_JOBS_ENFORCE,
    ]
    assert pre_authority.journal.next_phase is MigrationPhase.CONTRACT
    assert pre_authority.journal.tenant_aware_writes_enabled_at is None
    assert pre_authority.journal.legacy_rollback_allowed is True
    with pytest.raises(MigrationBoundaryError):
        command.run_contract(manifest)
    with pytest.raises(MigrationBoundaryError, match="future"):
        command.mark_tenant_aware_writes_authoritative(
            manifest,
            enabled_at=NOW.replace(hour=13),
        )

    marked = command.mark_tenant_aware_writes_authoritative(
        manifest,
        enabled_at=NOW,
    )
    assert marked.legacy_rollback_allowed is False
    contracted = command.run_contract(manifest)

    assert contracted.journal.next_phase is None
    assert [item.phase for item in contracted.runs] == [
        MigrationPhase.CONTRACT
    ]
    assert calls == [
        "expand",
        "backfill",
        "application",
        "database_jobs",
        "contract",
    ]
    assert command.run_to_authoritative_boundary(manifest).runs == ()
    assert command.run_contract(manifest).runs == ()


def test_command_requires_a_complete_registry_before_any_phase(tmp_path):
    manifest = _manifest()
    store = MigrationJournalFileStore(tmp_path / "journal.json")
    store.initialize(manifest)

    with pytest.raises(MigrationEvidenceError, match="complete"):
        DefaultMigrationCommand(store, executors={})

    assert store.load().next_phase is MigrationPhase.EXPAND


def test_cli_boundary_and_contract_commands_use_injected_registry(tmp_path):
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            manifest_to_document(manifest),
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="ascii",
    )
    journal_path = tmp_path / "journal.json"
    MigrationJournalFileStore(journal_path).initialize(manifest)
    registry = _registry(tmp_path, [])
    stdout = io.StringIO()

    assert main(
        [
            "run-to-authoritative-boundary",
            "--manifest",
            str(manifest_path),
            "--journal",
            str(journal_path),
        ],
        stdout=stdout,
        stderr=io.StringIO(),
        phase_executors=registry,
        clock=lambda: NOW,
    ) == 0
    boundary = json.loads(stdout.getvalue())
    assert boundary["next_phase"] == "contract"
    assert boundary["tenant_aware_writes_authoritative"] is False
    assert len(boundary["executed"]) == 4

    assert main(
        [
            "mark-tenant-aware-writes-authoritative",
            "--manifest",
            str(manifest_path),
            "--journal",
            str(journal_path),
            "--enabled-at",
            "2026-08-22T12:00:00Z",
        ],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    ) == 0
    contract_stdout = io.StringIO()
    assert main(
        [
            "run-contract",
            "--manifest",
            str(manifest_path),
            "--journal",
            str(journal_path),
        ],
        stdout=contract_stdout,
        stderr=io.StringIO(),
        phase_executors=registry,
        clock=lambda: NOW,
    ) == 0
    assert json.loads(contract_stdout.getvalue())["next_phase"] is None
