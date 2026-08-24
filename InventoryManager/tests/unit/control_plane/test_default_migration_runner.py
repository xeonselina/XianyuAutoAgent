from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

import pytest

from inventory_control.default_migration import (
    DefaultMigrationRunner,
    DefaultTenantMigrationManifest,
    MigrationEvidenceError,
    MigrationExecutionMode,
    MigrationJournalFileStore,
    MigrationJournalPersistenceError,
    MigrationOrderError,
    MigrationPhase,
    MigrationPhaseExecutionResult,
    MigrationPhaseRunOutcome,
    ReconciliationObservation,
    ReconciliationPolicy,
    ReconciliationRequirement,
    ReconciliationScope,
    ReconciliationValueKind,
    evaluate_reconciliation,
)


NOW = datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest() -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="default-tenant-runner-v1",
        tenant_uuid=UUID("00000000-0000-4000-8000-000000000601"),
        database_uuid=UUID("00000000-0000-4000-8000-000000000602"),
        source_schema_name="inventory_management",
        baseline_migration_id="initial-baseline-v1",
        core_plan_revision_uuid=UUID(
            "00000000-0000-4000-8000-000000000603"
        ),
        control_schema_head="202608220026",
        tenant_schema_head="20260823_shipping_contract",
        source_snapshot_digest=_digest("source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=_digest("keyed-name"),
        first_admin_phone_input_commitment=_digest("keyed-phone"),
    )


class _Executor:
    def __init__(self) -> None:
        self.invocations = []

    def execute(self, invocation):
        self.invocations.append(invocation)
        return MigrationPhaseExecutionResult(
            phase=invocation.plan.phase,
            manifest_digest=invocation.manifest.digest,
            input_state_digest=_digest(f"{invocation.plan.phase.value}:input"),
            result_state_digest=_digest(f"{invocation.plan.phase.value}:result"),
            executor_reference=f"isolated-test:{invocation.plan.phase.value}",
        )


def _runner(tmp_path):
    manifest = _manifest()
    store = MigrationJournalFileStore(tmp_path / "journal.json")
    store.initialize(manifest)
    return manifest, store, DefaultMigrationRunner(store, clock=lambda: NOW)


def _reconciliation_policy() -> ReconciliationPolicy:
    expected_by_scope = {
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
            expected=expected_by_scope[scope],
            tolerance=0,
            disposition_allowed=False,
        )
        for scope in sorted(ReconciliationScope, key=lambda item: item.value)
    )
    return ReconciliationPolicy(policy_version=1, requirements=requirements)


def test_dry_run_never_calls_executor_or_mutates_journal(tmp_path):
    manifest, store, runner = _runner(tmp_path)
    executor = _Executor()
    before = store.path.read_bytes()

    result = runner.run_phase(
        manifest,
        phase=MigrationPhase.EXPAND,
        mode=MigrationExecutionMode.DRY_RUN,
        executor=executor,
    )

    assert result.outcome is MigrationPhaseRunOutcome.PLANNED
    assert result.plan is not None
    assert result.plan.mutations_allowed is False
    assert result.plan.provider_or_print_side_effects_allowed is False
    assert executor.invocations == []
    assert store.path.read_bytes() == before


def test_apply_requires_explicit_executor(tmp_path):
    manifest, _store, runner = _runner(tmp_path)

    with pytest.raises(MigrationEvidenceError, match="explicit phase executor"):
        runner.run_phase(
            manifest,
            phase=MigrationPhase.EXPAND,
            mode=MigrationExecutionMode.APPLY,
        )


def test_apply_persists_one_phase_and_response_loss_replay_is_noop(tmp_path):
    manifest, store, runner = _runner(tmp_path)
    executor = _Executor()

    completed = runner.run_phase(
        manifest,
        phase=MigrationPhase.EXPAND,
        mode=MigrationExecutionMode.APPLY,
        executor=executor,
    )
    after_completion = store.path.read_bytes()
    replayed = runner.run_phase(
        manifest,
        phase=MigrationPhase.EXPAND,
        mode=MigrationExecutionMode.APPLY,
        executor=executor,
    )

    assert completed.outcome is MigrationPhaseRunOutcome.COMPLETED
    assert replayed.outcome is MigrationPhaseRunOutcome.REPLAYED
    assert replayed.evidence == completed.evidence
    assert replayed.phase_execution_key == completed.phase_execution_key
    assert len(executor.invocations) == 1
    assert store.path.read_bytes() == after_completion


def test_stable_execution_key_allows_crash_before_journal_write_to_resume(tmp_path):
    manifest, store, runner = _runner(tmp_path)
    executor = _Executor()
    original_compare_and_swap = store.compare_and_swap
    failed = False

    def crash_once(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise MigrationJournalPersistenceError("simulated crash")
        return original_compare_and_swap(*args, **kwargs)

    store.compare_and_swap = crash_once  # type: ignore[method-assign]
    with pytest.raises(MigrationJournalPersistenceError, match="simulated crash"):
        runner.run_phase(
            manifest,
            phase=MigrationPhase.EXPAND,
            mode=MigrationExecutionMode.APPLY,
            executor=executor,
        )
    resumed = runner.run_phase(
        manifest,
        phase=MigrationPhase.EXPAND,
        mode=MigrationExecutionMode.APPLY,
        executor=executor,
    )

    assert resumed.outcome is MigrationPhaseRunOutcome.COMPLETED
    assert len(executor.invocations) == 2
    assert (
        executor.invocations[0].phase_execution_key
        == executor.invocations[1].phase_execution_key
    )


def test_dependency_order_is_enforced_before_executor_call(tmp_path):
    manifest, _store, runner = _runner(tmp_path)
    executor = _Executor()

    with pytest.raises(MigrationOrderError, match="next dependency"):
        runner.run_phase(
            manifest,
            phase=MigrationPhase.APPLICATION_ENFORCE,
            mode=MigrationExecutionMode.APPLY,
            executor=executor,
        )
    assert executor.invocations == []


def test_executor_result_must_match_manifest_and_phase(tmp_path):
    manifest, _store, runner = _runner(tmp_path)

    class WrongExecutor:
        def execute(self, invocation):
            result = _Executor().execute(invocation)
            return replace(result, phase=MigrationPhase.CONTRACT)

    with pytest.raises(MigrationOrderError, match="another phase"):
        runner.run_phase(
            manifest,
            phase=MigrationPhase.EXPAND,
            mode=MigrationExecutionMode.APPLY,
            executor=WrongExecutor(),
        )


def test_backfill_result_cannot_bypass_reconciliation(tmp_path):
    with pytest.raises(MigrationEvidenceError, match="reconciliation evidence"):
        MigrationPhaseExecutionResult(
            phase=MigrationPhase.BACKFILL_VERIFY,
            manifest_digest=_manifest().digest,
            input_state_digest=_digest("input"),
            result_state_digest=_digest("result"),
            executor_reference="isolated-test:backfill",
        )


def test_passed_reconciliation_completes_backfill_through_special_boundary(
    tmp_path,
):
    manifest, store, runner = _runner(tmp_path)
    runner.run_phase(
        manifest,
        phase=MigrationPhase.EXPAND,
        mode=MigrationExecutionMode.APPLY,
        executor=_Executor(),
    )
    policy = _reconciliation_policy()
    report = evaluate_reconciliation(
        manifest,
        policy,
        tuple(
            ReconciliationObservation(key=item.key, observed=item.expected)
            for item in policy.requirements
        ),
    )

    class BackfillExecutor:
        def execute(self, invocation):
            return MigrationPhaseExecutionResult(
                phase=MigrationPhase.BACKFILL_VERIFY,
                manifest_digest=manifest.digest,
                input_state_digest=policy.digest,
                result_state_digest=report.report_digest,
                executor_reference="isolated-test:backfill",
                reconciliation_policy=policy,
                reconciliation_report=report,
            )

    result = runner.run_phase(
        manifest,
        phase=MigrationPhase.BACKFILL_VERIFY,
        mode=MigrationExecutionMode.APPLY,
        executor=BackfillExecutor(),
    )

    assert result.outcome is MigrationPhaseRunOutcome.COMPLETED
    assert result.evidence is not None
    assert result.evidence.input_state_digest == policy.digest
    assert result.evidence.result_state_digest == report.report_digest
    assert store.load().next_phase is MigrationPhase.APPLICATION_ENFORCE
