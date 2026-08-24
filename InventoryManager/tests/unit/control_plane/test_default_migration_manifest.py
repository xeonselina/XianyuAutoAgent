from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from inventory_control.default_migration import (
    MIGRATION_PHASE_ORDER,
    DefaultTenantMigrationManifest,
    MigrationBoundaryError,
    MigrationEvidenceError,
    MigrationExecutionMode,
    MigrationJournal,
    MigrationManifestError,
    MigrationManifestMismatchError,
    MigrationOrderError,
    MigrationPhase,
    ReconciliationObservation,
    ReconciliationPolicy,
    ReconciliationRequirement,
    ReconciliationScope,
    ReconciliationValueKind,
    build_execution_plan,
    evaluate_reconciliation,
    mark_tenant_aware_writes_authoritative,
    plan_legacy_rollback,
    record_backfill_verification_completion,
    record_phase_completion,
)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest(**overrides) -> DefaultTenantMigrationManifest:
    values = {
        "migration_idempotency_key": "default-tenant-2026-08-22",
        "tenant_uuid": UUID("00000000-0000-4000-8000-000000000101"),
        "database_uuid": UUID("00000000-0000-4000-8000-000000000102"),
        "source_schema_name": "inventory_management",
        "baseline_migration_id": "initial-baseline-v1",
        "core_plan_revision_uuid": UUID(
            "00000000-0000-4000-8000-000000000103"
        ),
        "control_schema_head": "202608220026",
        "tenant_schema_head": "20260823_shipping_contract",
        "source_snapshot_digest": _digest("source-snapshot"),
        "implementation_identity_digest": _digest("implementation"),
        "migration_bundle_digest": _digest("bundle"),
        "display_name_input_commitment": _digest("keyed-name-commitment"),
        "first_admin_phone_input_commitment": _digest(
            "keyed-phone-commitment"
        ),
    }
    values.update(overrides)
    return DefaultTenantMigrationManifest(**values)


def _complete_next(
    manifest: DefaultTenantMigrationManifest,
    journal: MigrationJournal,
    *,
    completed_at: datetime,
) -> MigrationJournal:
    plan = build_execution_plan(
        manifest,
        journal,
        mode=MigrationExecutionMode.APPLY,
    )
    if plan.phase is MigrationPhase.BACKFILL_VERIFY:
        requirements = tuple(
            ReconciliationRequirement(
                key=f"scope.{scope.value}",
                scope=scope,
                value_kind=(
                    ReconciliationValueKind.SHA256_DIGEST
                    if scope is ReconciliationScope.SCHEMA_DIGEST
                    else ReconciliationValueKind.POSITIVE_INTEGER
                    if scope is ReconciliationScope.SCHEMA_GENERATION
                    else ReconciliationValueKind.NONNEGATIVE_INTEGER
                ),
                expected=(
                    _digest("schema")
                    if scope is ReconciliationScope.SCHEMA_DIGEST
                    else 0
                    if scope
                    in {
                        ReconciliationScope.LEGACY_DOUBLE_COUNT,
                        ReconciliationScope.ORPHAN_COUNT,
                    }
                    else 1
                ),
                tolerance=0,
                disposition_allowed=False,
            )
            for scope in sorted(ReconciliationScope, key=lambda item: item.value)
        )
        policy = ReconciliationPolicy(
            policy_version=1,
            requirements=requirements,
        )
        report = evaluate_reconciliation(
            manifest,
            policy,
            tuple(
                ReconciliationObservation(
                    key=requirement.key,
                    observed=requirement.expected,
                )
                for requirement in requirements
            ),
        )
        return record_backfill_verification_completion(
            manifest,
            journal,
            plan=plan,
            policy=policy,
            report=report,
            completed_at=completed_at,
            executor_reference="local-test:backfill_verify",
        )
    return record_phase_completion(
        manifest,
        journal,
        plan=plan,
        input_state_digest=_digest(f"input-{plan.phase.value}"),
        result_state_digest=_digest(f"result-{plan.phase.value}"),
        completed_at=completed_at,
        executor_reference=f"local-test:{plan.phase.value}",
    )


def test_manifest_is_deterministic_and_redacts_identity_commitments():
    first = _manifest()
    second = _manifest()

    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.digest == second.digest
    summary = dict(first.redacted_summary())
    rendered = repr(summary)
    assert summary["sensitive_inputs_bound"] is True
    assert first.display_name_input_commitment.hex() not in rendered
    assert first.first_admin_phone_input_commitment.hex() not in rendered
    assert "phone" not in rendered.lower()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_schema_name", "inventory-management"),
        ("migration_idempotency_key", "contains whitespace"),
        ("control_schema_head", ""),
        ("migration_bundle_digest", b"short"),
    ],
)
def test_manifest_rejects_ambiguous_or_unversioned_inputs(field, value):
    with pytest.raises(MigrationManifestError):
        _manifest(**{field: value})


def test_manifest_rejects_reused_tenant_and_database_identity():
    tenant_uuid = UUID("00000000-0000-4000-8000-000000000101")
    with pytest.raises(MigrationManifestError, match="must differ"):
        _manifest(database_uuid=tenant_uuid)


def test_dry_run_exposes_contract_without_authorizing_mutation_or_side_effects():
    manifest = _manifest()
    journal = MigrationJournal.for_manifest(manifest)

    plan = build_execution_plan(
        manifest,
        journal,
        mode=MigrationExecutionMode.DRY_RUN,
    )

    assert plan.phase is MigrationPhase.EXPAND
    assert plan.mutations_allowed is False
    assert plan.provider_or_print_side_effects_allowed is False
    assert any("schema head" in value for value in plan.stop_conditions)
    with pytest.raises(MigrationEvidenceError, match="dry-run"):
        record_phase_completion(
            manifest,
            journal,
            plan=plan,
            input_state_digest=_digest("input"),
            result_state_digest=_digest("result"),
            completed_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
            executor_reference="local-test:dry-run",
        )


def test_phases_resume_in_exact_dependency_order():
    manifest = _manifest()
    journal = MigrationJournal.for_manifest(manifest)
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)

    for index, expected in enumerate(MIGRATION_PHASE_ORDER[:-1]):
        plan = build_execution_plan(
            manifest,
            journal,
            mode=MigrationExecutionMode.APPLY,
        )
        assert plan.phase is expected
        journal = _complete_next(
            manifest,
            journal,
            completed_at=now + timedelta(minutes=index),
        )

    assert journal.next_phase is MigrationPhase.CONTRACT
    with pytest.raises(MigrationBoundaryError, match="authoritative-write"):
        build_execution_plan(
            manifest,
            journal,
            mode=MigrationExecutionMode.APPLY,
        )


def test_requested_phase_cannot_skip_a_dependency():
    manifest = _manifest()
    journal = MigrationJournal.for_manifest(manifest)

    with pytest.raises(MigrationOrderError, match="next dependency"):
        build_execution_plan(
            manifest,
            journal,
            mode=MigrationExecutionMode.APPLY,
            requested_phase=MigrationPhase.BACKFILL_VERIFY,
        )


def test_changed_manifest_cannot_resume_existing_journal():
    manifest = _manifest()
    changed = _manifest(migration_bundle_digest=_digest("changed-bundle"))
    journal = MigrationJournal.for_manifest(manifest)

    with pytest.raises(MigrationManifestMismatchError):
        build_execution_plan(
            changed,
            journal,
            mode=MigrationExecutionMode.DRY_RUN,
        )


def test_stale_phase_plan_cannot_be_recorded_twice():
    manifest = _manifest()
    journal = MigrationJournal.for_manifest(manifest)
    plan = build_execution_plan(
        manifest,
        journal,
        mode=MigrationExecutionMode.APPLY,
    )
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)
    completed = record_phase_completion(
        manifest,
        journal,
        plan=plan,
        input_state_digest=_digest("input"),
        result_state_digest=_digest("result"),
        completed_at=now,
        executor_reference="local-test:expand",
    )

    with pytest.raises(MigrationOrderError, match="stale"):
        record_phase_completion(
            manifest,
            completed,
            plan=plan,
            input_state_digest=_digest("input"),
            result_state_digest=_digest("result"),
            completed_at=now,
            executor_reference="local-test:expand",
        )


def test_legacy_rollback_is_allowed_only_before_authoritative_writes():
    manifest = _manifest()
    journal = MigrationJournal.for_manifest(manifest)
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)
    for index in range(4):
        journal = _complete_next(
            manifest,
            journal,
            completed_at=now + timedelta(minutes=index),
        )

    rollback = plan_legacy_rollback(manifest, journal)
    assert rollback.preserves_expand_and_audit_facts is True
    assert rollback.reverses_business_data is False
    assert any("database_identity" in action for action in rollback.actions)

    journal = mark_tenant_aware_writes_authoritative(
        manifest,
        journal,
        enabled_at=now + timedelta(minutes=4),
    )
    assert journal.legacy_rollback_allowed is False
    with pytest.raises(MigrationBoundaryError, match="forbidden"):
        plan_legacy_rollback(manifest, journal)


def test_authoritative_write_marker_is_ordered_and_idempotent_only_exactly():
    manifest = _manifest()
    journal = MigrationJournal.for_manifest(manifest)
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)

    with pytest.raises(MigrationBoundaryError, match="enforcement"):
        mark_tenant_aware_writes_authoritative(
            manifest,
            journal,
            enabled_at=now,
        )

    for index in range(4):
        journal = _complete_next(
            manifest,
            journal,
            completed_at=now + timedelta(minutes=index),
        )
    enabled_at = now + timedelta(minutes=4)
    with pytest.raises(MigrationBoundaryError, match="predates"):
        mark_tenant_aware_writes_authoritative(
            manifest,
            journal,
            enabled_at=now + timedelta(minutes=2),
        )
    marked = mark_tenant_aware_writes_authoritative(
        manifest,
        journal,
        enabled_at=enabled_at,
    )
    assert (
        mark_tenant_aware_writes_authoritative(
            manifest,
            marked,
            enabled_at=enabled_at,
        )
        is marked
    )
    with pytest.raises(MigrationBoundaryError, match="immutable"):
        mark_tenant_aware_writes_authoritative(
            manifest,
            marked,
            enabled_at=enabled_at + timedelta(seconds=1),
        )


def test_contract_requires_marker_and_uses_tenant_aware_recovery_only():
    manifest = _manifest()
    journal = MigrationJournal.for_manifest(manifest)
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)
    for index in range(4):
        journal = _complete_next(
            manifest,
            journal,
            completed_at=now + timedelta(minutes=index),
        )
    journal = mark_tenant_aware_writes_authoritative(
        manifest,
        journal,
        enabled_at=now + timedelta(minutes=4),
    )

    plan = build_execution_plan(
        manifest,
        journal,
        mode=MigrationExecutionMode.APPLY,
    )

    assert plan.phase is MigrationPhase.CONTRACT
    assert "legacy-writer rollback is forbidden" in plan.rollback_action
    completed = record_phase_completion(
        manifest,
        journal,
        plan=plan,
        input_state_digest=_digest("contract-input"),
        result_state_digest=_digest("contract-result"),
        completed_at=now + timedelta(minutes=5),
        executor_reference="local-test:contract",
    )
    assert completed.next_phase is None
    with pytest.raises(MigrationOrderError, match="already complete"):
        build_execution_plan(
            manifest,
            completed,
            mode=MigrationExecutionMode.DRY_RUN,
        )
