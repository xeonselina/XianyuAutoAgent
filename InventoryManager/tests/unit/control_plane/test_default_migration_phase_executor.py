from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import pytest

from inventory_control.default_migration import (
    DefaultMigrationReconciliationRunner,
    DefaultMigrationRunner,
    DefaultMigrationStepResult,
    DefaultTenantMigrationManifest,
    MigrationExecutionMode,
    MigrationJournalFileStore,
    MigrationPhase,
    MigrationPhaseRunOutcome,
    MigrationReconciliationBlockedError,
    OrderedDefaultMigrationPhaseExecutor,
    ReconciledDefaultMigrationBackfillExecutor,
    ReconciliationObservation,
    ReconciliationPolicy,
    ReconciliationRequirement,
    ReconciliationScope,
    ReconciliationValueKind,
)


NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest() -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="default-phase-executor-v1",
        tenant_uuid=UUID("70000000-0000-4000-8000-000000000001"),
        database_uuid=UUID("70000000-0000-4000-8000-000000000002"),
        source_schema_name="inventory_management",
        baseline_migration_id="initial-baseline-v1",
        core_plan_revision_uuid=UUID(
            "70000000-0000-4000-8000-000000000003"
        ),
        control_schema_head="202608220026",
        tenant_schema_head="20260824_legacy_history",
        source_snapshot_digest=_digest("source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=_digest("name"),
        first_admin_phone_input_commitment=_digest("phone"),
    )


@dataclass
class _Step:
    name: str
    calls: list
    fail_once: bool = False

    def execute(self, invocation):
        self.calls.append(invocation)
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("simulated crash")
        return DefaultMigrationStepResult(
            step_name=self.name,
            manifest_digest=invocation.phase_invocation.manifest.digest,
            result_digest=_digest(f"{self.name}:result"),
            executor_reference=f"test:{self.name}",
        )


def _runner(tmp_path):
    manifest = _manifest()
    store = MigrationJournalFileStore(tmp_path / "journal.json")
    store.initialize(manifest)
    return manifest, store, DefaultMigrationRunner(store, clock=lambda: NOW)


def _policy() -> ReconciliationPolicy:
    expected = {
        ReconciliationScope.TABLE_ROW_COUNT: 10,
        ReconciliationScope.MONETARY_AMOUNT: 100,
        ReconciliationScope.DEVICE_ASSOCIATION: 9,
        ReconciliationScope.RENTAL_ASSOCIATION: 8,
        ReconciliationScope.ACCESSORY_ASSOCIATION: 7,
        ReconciliationScope.ORPHAN_COUNT: 0,
        ReconciliationScope.HISTORICAL_WAYBILL: 6,
        ReconciliationScope.CREDENTIAL_REVISION: 5,
        ReconciliationScope.DEFAULT_WAREHOUSE: 1,
        ReconciliationScope.LEGACY_DOUBLE_COUNT: 0,
        ReconciliationScope.SCHEMA_GENERATION: 4,
        ReconciliationScope.SCHEMA_DIGEST: _digest("schema"),
    }
    return ReconciliationPolicy(
        policy_version=1,
        requirements=tuple(
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
                expected=expected[scope],
                tolerance=0,
                disposition_allowed=False,
            )
            for scope in sorted(ReconciliationScope, key=lambda item: item.value)
        ),
    )


@dataclass
class _Collector:
    key: str
    observed: object

    def collect(self, *, manifest, requirement):
        return ReconciliationObservation(key=self.key, observed=self.observed)


def test_ordered_executor_runs_every_step_and_journals_aggregate_result(tmp_path):
    manifest, store, runner = _runner(tmp_path)
    calls = []
    steps = (
        _Step("schema_expand", calls),
        _Step("identity_register", calls),
    )
    executor = OrderedDefaultMigrationPhaseExecutor(
        phase=MigrationPhase.EXPAND,
        steps=steps,
    )

    result = runner.run_phase(
        manifest,
        phase=MigrationPhase.EXPAND,
        mode=MigrationExecutionMode.APPLY,
        executor=executor,
    )

    assert result.outcome is MigrationPhaseRunOutcome.COMPLETED
    assert [item.step_name for item in calls] == [
        "schema_expand",
        "identity_register",
    ]
    assert calls[0].step_execution_key != calls[1].step_execution_key
    assert store.load().next_phase is MigrationPhase.BACKFILL_VERIFY


def test_crash_retries_each_step_with_the_same_stable_key(tmp_path):
    manifest, store, runner = _runner(tmp_path)
    first_calls = []
    second = _Step("identity_register", first_calls, fail_once=True)
    executor = OrderedDefaultMigrationPhaseExecutor(
        phase=MigrationPhase.EXPAND,
        steps=(_Step("schema_expand", first_calls), second),
    )

    with pytest.raises(RuntimeError, match="simulated crash"):
        runner.run_phase(
            manifest,
            phase=MigrationPhase.EXPAND,
            mode=MigrationExecutionMode.APPLY,
            executor=executor,
        )
    completed = runner.run_phase(
        manifest,
        phase=MigrationPhase.EXPAND,
        mode=MigrationExecutionMode.APPLY,
        executor=executor,
    )

    assert completed.outcome is MigrationPhaseRunOutcome.COMPLETED
    schema_calls = [item for item in first_calls if item.step_name == "schema_expand"]
    identity_calls = [
        item for item in first_calls if item.step_name == "identity_register"
    ]
    assert len(schema_calls) == len(identity_calls) == 2
    assert schema_calls[0].step_execution_key == schema_calls[1].step_execution_key
    assert (
        identity_calls[0].step_execution_key
        == identity_calls[1].step_execution_key
    )
    assert len(store.load().completed) == 1


def test_reconciled_backfill_journals_only_after_steps_and_full_report(tmp_path):
    manifest, store, runner = _runner(tmp_path)
    runner.run_phase(
        manifest,
        phase=MigrationPhase.EXPAND,
        mode=MigrationExecutionMode.APPLY,
        executor=OrderedDefaultMigrationPhaseExecutor(
            phase=MigrationPhase.EXPAND,
            steps=(_Step("schema_expand", []),),
        ),
    )
    policy = _policy()
    collectors = tuple(
        _Collector(item.key, item.expected) for item in policy.requirements
    )
    executor = ReconciledDefaultMigrationBackfillExecutor(
        steps=(_Step("warehouse_backfill", []),),
        policy=policy,
        reconciliation_runner=DefaultMigrationReconciliationRunner(collectors),
    )

    result = runner.run_phase(
        manifest,
        phase=MigrationPhase.BACKFILL_VERIFY,
        mode=MigrationExecutionMode.APPLY,
        executor=executor,
    )

    assert result.outcome is MigrationPhaseRunOutcome.COMPLETED
    assert result.evidence.input_state_digest == policy.digest
    assert store.load().next_phase is MigrationPhase.APPLICATION_ENFORCE
    assert len(result.evidence.result_state_digest) == 32


def test_blocked_reconciliation_leaves_backfill_uncompleted(tmp_path):
    manifest, store, runner = _runner(tmp_path)
    runner.run_phase(
        manifest,
        phase=MigrationPhase.EXPAND,
        mode=MigrationExecutionMode.APPLY,
        executor=OrderedDefaultMigrationPhaseExecutor(
            phase=MigrationPhase.EXPAND,
            steps=(_Step("schema_expand", []),),
        ),
    )
    policy = _policy()
    collectors = [
        _Collector(item.key, item.expected) for item in policy.requirements
    ]
    collectors[0].observed = None
    executor = ReconciledDefaultMigrationBackfillExecutor(
        steps=(_Step("warehouse_backfill", []),),
        policy=policy,
        reconciliation_runner=DefaultMigrationReconciliationRunner(
            tuple(collectors)
        ),
    )

    with pytest.raises(MigrationReconciliationBlockedError):
        runner.run_phase(
            manifest,
            phase=MigrationPhase.BACKFILL_VERIFY,
            mode=MigrationExecutionMode.APPLY,
            executor=executor,
        )

    assert store.load().next_phase is MigrationPhase.BACKFILL_VERIFY
