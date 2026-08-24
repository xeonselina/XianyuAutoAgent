from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

import pytest

from inventory_control.default_migration import (
    DefaultTenantMigrationManifest,
    MigrationEvidenceError,
    MigrationExecutionMode,
    MigrationJournal,
    MigrationManifestMismatchError,
    MigrationReconciliationError,
    ReconciliationDisposition,
    ReconciliationFindingStatus,
    ReconciliationObservation,
    ReconciliationPolicy,
    ReconciliationRequirement,
    ReconciliationScope,
    ReconciliationValueKind,
    build_execution_plan,
    evaluate_reconciliation,
    record_backfill_verification_completion,
    record_phase_completion,
)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest() -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="default-tenant-reconciliation-v1",
        tenant_uuid=UUID("00000000-0000-4000-8000-000000000301"),
        database_uuid=UUID("00000000-0000-4000-8000-000000000302"),
        source_schema_name="inventory_management",
        baseline_migration_id="initial-baseline-v1",
        core_plan_revision_uuid=UUID(
            "00000000-0000-4000-8000-000000000303"
        ),
        control_schema_head="202608220023",
        tenant_schema_head="20260823_shipping_contract",
        source_snapshot_digest=_digest("source-snapshot"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=_digest("keyed-name"),
        first_admin_phone_input_commitment=_digest("keyed-phone"),
    )


def _requirement(
    key: str,
    scope: ReconciliationScope,
    *,
    expected: int | bytes,
    value_kind: ReconciliationValueKind = (
        ReconciliationValueKind.NONNEGATIVE_INTEGER
    ),
    tolerance: int = 0,
    disposition_allowed: bool = False,
) -> ReconciliationRequirement:
    return ReconciliationRequirement(
        key=key,
        scope=scope,
        value_kind=value_kind,
        expected=expected,
        tolerance=tolerance,
        disposition_allowed=disposition_allowed,
    )


def _policy() -> ReconciliationPolicy:
    requirements = (
        _requirement(
            "accessories.links",
            ReconciliationScope.ACCESSORY_ASSOCIATION,
            expected=18,
        ),
        _requirement(
            "credentials.revisions",
            ReconciliationScope.CREDENTIAL_REVISION,
            expected=4,
        ),
        _requirement(
            "devices.warehouse_links",
            ReconciliationScope.DEVICE_ASSOCIATION,
            expected=100,
        ),
        _requirement(
            "legacy.double_count",
            ReconciliationScope.LEGACY_DOUBLE_COUNT,
            expected=0,
        ),
        _requirement(
            "money.rental_total_minor",
            ReconciliationScope.MONETARY_AMOUNT,
            expected=991234,
        ),
        _requirement(
            "orphans.foreign_keys",
            ReconciliationScope.ORPHAN_COUNT,
            expected=0,
            disposition_allowed=True,
        ),
        _requirement(
            "rentals.device_links",
            ReconciliationScope.RENTAL_ASSOCIATION,
            expected=72,
        ),
        _requirement(
            "schema.digest",
            ReconciliationScope.SCHEMA_DIGEST,
            expected=_digest("tenant-schema"),
            value_kind=ReconciliationValueKind.SHA256_DIGEST,
        ),
        _requirement(
            "schema.generation",
            ReconciliationScope.SCHEMA_GENERATION,
            expected=23,
            value_kind=ReconciliationValueKind.POSITIVE_INTEGER,
        ),
        _requirement(
            "shipments.historical_waybills",
            ReconciliationScope.HISTORICAL_WAYBILL,
            expected=31,
        ),
        _requirement(
            "tables.devices.rows",
            ReconciliationScope.TABLE_ROW_COUNT,
            expected=100,
        ),
        _requirement(
            "warehouses.default_count",
            ReconciliationScope.DEFAULT_WAREHOUSE,
            expected=1,
        ),
    )
    return ReconciliationPolicy(policy_version=1, requirements=requirements)


def _observations(policy: ReconciliationPolicy):
    return tuple(
        ReconciliationObservation(key=item.key, observed=item.expected)
        for item in policy.requirements
    )


def _backfill_plan(
    manifest: DefaultTenantMigrationManifest,
    *,
    mode: MigrationExecutionMode = MigrationExecutionMode.APPLY,
):
    journal = MigrationJournal.for_manifest(manifest)
    expand_plan = build_execution_plan(
        manifest,
        journal,
        mode=MigrationExecutionMode.APPLY,
    )
    journal = record_phase_completion(
        manifest,
        journal,
        plan=expand_plan,
        input_state_digest=_digest("expand-input"),
        result_state_digest=_digest("expand-result"),
        completed_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
        executor_reference="offline-test:expand",
    )
    return (
        journal,
        build_execution_plan(manifest, journal, mode=mode),
    )


def test_exact_full_coverage_passes_and_report_is_deterministic() -> None:
    manifest = _manifest()
    policy = _policy()

    first = evaluate_reconciliation(manifest, policy, _observations(policy))
    second = evaluate_reconciliation(manifest, policy, _observations(policy))

    assert first.passed
    assert first == second
    assert first.report_digest == second.report_digest
    assert all(
        item.status is ReconciliationFindingStatus.MATCHED
        for item in first.findings
    )
    assert first.manifest_digest == manifest.digest
    assert first.source_snapshot_digest == manifest.source_snapshot_digest


def test_missing_extra_and_duplicate_observations_are_rejected() -> None:
    manifest = _manifest()
    policy = _policy()
    observations = _observations(policy)

    with pytest.raises(MigrationReconciliationError, match="exactly cover"):
        evaluate_reconciliation(manifest, policy, observations[:-1])
    with pytest.raises(MigrationReconciliationError, match="exactly cover"):
        evaluate_reconciliation(
            manifest,
            policy,
            observations
            + (ReconciliationObservation(key="unexpected.key", observed=0),),
        )
    with pytest.raises(MigrationReconciliationError, match="duplicated"):
        evaluate_reconciliation(manifest, policy, observations + (observations[0],))


def test_unknown_value_blocks_even_when_a_disposition_is_present() -> None:
    manifest = _manifest()
    policy = _policy()
    observations = list(_observations(policy))
    index = next(
        index
        for index, item in enumerate(observations)
        if item.key == "orphans.foreign_keys"
    )
    observations[index] = ReconciliationObservation(
        key="orphans.foreign_keys",
        observed=None,
        disposition=ReconciliationDisposition(
            reason_code="known_source_exception",
            evidence_digest=_digest("evidence"),
        ),
    )

    report = evaluate_reconciliation(manifest, policy, tuple(observations))

    finding = report.findings[index]
    assert finding.status is ReconciliationFindingStatus.UNKNOWN
    assert finding.blocking
    assert not report.passed


def test_policy_allowed_known_difference_requires_evidence_disposition() -> None:
    manifest = _manifest()
    policy = _policy()
    observations = list(_observations(policy))
    index = next(
        index
        for index, item in enumerate(observations)
        if item.key == "orphans.foreign_keys"
    )
    observations[index] = ReconciliationObservation(
        key="orphans.foreign_keys",
        observed=2,
        disposition=ReconciliationDisposition(
            reason_code="source_rows_quarantined",
            evidence_digest=_digest("quarantine-proof"),
        ),
    )

    report = evaluate_reconciliation(manifest, policy, tuple(observations))

    finding = report.findings[index]
    assert finding.status is ReconciliationFindingStatus.DISPOSITIONED
    assert not finding.blocking
    assert report.passed


def test_same_difference_without_disposition_blocks() -> None:
    manifest = _manifest()
    policy = _policy()
    observations = list(_observations(policy))
    index = next(
        index
        for index, item in enumerate(observations)
        if item.key == "orphans.foreign_keys"
    )
    observations[index] = ReconciliationObservation(
        key="orphans.foreign_keys",
        observed=2,
    )

    report = evaluate_reconciliation(manifest, policy, tuple(observations))

    assert report.findings[index].safe_reason_code == "undispositioned_difference"
    assert not report.passed


@pytest.mark.parametrize("key", ["schema.digest", "schema.generation", "legacy.double_count"])
def test_schema_and_legacy_authority_differences_are_non_waivable(key: str) -> None:
    manifest = _manifest()
    policy = _policy()
    observations = list(_observations(policy))
    index = next(index for index, item in enumerate(observations) if item.key == key)
    expected = policy.requirements[index].expected
    changed = (
        _digest("drifted")
        if isinstance(expected, bytes)
        else expected + 1
    )
    observations[index] = ReconciliationObservation(
        key=key,
        observed=changed,
        disposition=ReconciliationDisposition(
            reason_code="operator_acceptance",
            evidence_digest=_digest("operator-note"),
        ),
    )

    report = evaluate_reconciliation(manifest, policy, tuple(observations))

    assert report.findings[index].safe_reason_code == "disposition_not_allowed"
    assert report.findings[index].blocking
    assert not report.passed


def test_observation_type_mismatch_blocks_instead_of_coercing() -> None:
    manifest = _manifest()
    policy = _policy()
    observations = list(_observations(policy))
    index = next(
        index
        for index, item in enumerate(observations)
        if item.key == "schema.digest"
    )
    observations[index] = ReconciliationObservation(
        key="schema.digest",
        observed=23,
    )

    report = evaluate_reconciliation(manifest, policy, tuple(observations))

    assert report.findings[index].safe_reason_code == "observation_type_mismatch"
    assert not report.passed


def test_policy_must_cover_every_scope_with_sorted_unique_keys() -> None:
    policy = _policy()
    with pytest.raises(MigrationReconciliationError, match="every required"):
        ReconciliationPolicy(
            policy_version=1,
            requirements=policy.requirements[:-1],
        )
    with pytest.raises(MigrationReconciliationError, match="unique and sorted"):
        ReconciliationPolicy(
            policy_version=1,
            requirements=tuple(reversed(policy.requirements)),
        )


def test_policy_cannot_make_schema_or_legacy_check_waivable() -> None:
    policy = _policy()
    requirement = next(
        item
        for item in policy.requirements
        if item.scope is ReconciliationScope.SCHEMA_DIGEST
    )
    with pytest.raises(MigrationReconciliationError, match="non-waivable"):
        replace(requirement, disposition_allowed=True)


@pytest.mark.parametrize(
    "key",
    ["schema.generation", "legacy.double_count", "orphans.foreign_keys"],
)
def test_policy_cannot_tolerate_schema_drift_or_nonzero_anomalies(key: str) -> None:
    policy = _policy()
    requirement = next(item for item in policy.requirements if item.key == key)

    with pytest.raises(MigrationReconciliationError, match="tolerance must be zero"):
        replace(requirement, tolerance=1)


def test_redacted_summary_contains_no_values_or_evidence_digest() -> None:
    policy = _policy()
    evidence = _digest("sensitive-ops-reference")
    observations = list(_observations(policy))
    index = next(
        index
        for index, item in enumerate(observations)
        if item.key == "orphans.foreign_keys"
    )
    observations[index] = ReconciliationObservation(
        key="orphans.foreign_keys",
        observed=1,
        disposition=ReconciliationDisposition(
            reason_code="source_rows_quarantined",
            evidence_digest=evidence,
        ),
    )
    report = evaluate_reconciliation(_manifest(), policy, tuple(observations))

    rendered = repr(dict(report.redacted_summary()))
    assert evidence.hex() not in rendered
    assert "991234" not in rendered
    assert "finding_counts" in rendered


def test_passed_report_records_digest_only_evidence_in_fixed_order() -> None:
    manifest = _manifest()
    policy = _policy()
    report = evaluate_reconciliation(manifest, policy, _observations(policy))
    journal, plan = _backfill_plan(manifest)

    completed = record_backfill_verification_completion(
        manifest,
        journal,
        plan=plan,
        policy=policy,
        report=report,
        completed_at=datetime(2026, 8, 22, 0, 1, tzinfo=timezone.utc),
        executor_reference="offline-test:backfill_verify",
    )

    evidence = completed.completed[-1]
    assert evidence.phase.value == "backfill_verify"
    assert evidence.manifest_digest == manifest.digest
    assert evidence.input_state_digest == policy.digest
    assert evidence.result_state_digest == report.report_digest
    assert completed.next_phase.value == "application_enforce"
    rendered = repr(evidence)
    assert "991234" not in rendered
    assert "tables.devices.rows" not in rendered


def test_generic_completion_cannot_bypass_reconciliation_report() -> None:
    manifest = _manifest()
    journal, plan = _backfill_plan(manifest)

    with pytest.raises(MigrationEvidenceError, match="reconciliation report"):
        record_phase_completion(
            manifest,
            journal,
            plan=plan,
            input_state_digest=_digest("unbound-policy"),
            result_state_digest=_digest("unbound-result"),
            completed_at=datetime(2026, 8, 22, 0, 1, tzinfo=timezone.utc),
            executor_reference="offline-test:unbound",
        )


@pytest.mark.parametrize("kind", ["failed", "unknown"])
def test_failed_or_unknown_report_cannot_complete_backfill(kind: str) -> None:
    manifest = _manifest()
    policy = _policy()
    observations = list(_observations(policy))
    observations[0] = ReconciliationObservation(
        key=observations[0].key,
        observed=None if kind == "unknown" else 999,
    )
    report = evaluate_reconciliation(manifest, policy, tuple(observations))
    journal, plan = _backfill_plan(manifest)

    with pytest.raises(MigrationEvidenceError, match=kind):
        record_backfill_verification_completion(
            manifest,
            journal,
            plan=plan,
            policy=policy,
            report=report,
            completed_at=datetime(2026, 8, 22, 0, 1, tzinfo=timezone.utc),
            executor_reference="offline-test:blocked",
        )


def test_fabricated_disposition_cannot_waive_policy_identity() -> None:
    manifest = _manifest()
    policy = _policy()
    report = evaluate_reconciliation(manifest, policy, _observations(policy))
    index = next(
        index
        for index, requirement in enumerate(policy.requirements)
        if not requirement.disposition_allowed
    )
    findings = list(report.findings)
    findings[index] = replace(
        findings[index],
        status=ReconciliationFindingStatus.DISPOSITIONED,
        safe_reason_code="fabricated_waiver",
    )
    report = replace(report, findings=tuple(findings))
    journal, plan = _backfill_plan(manifest)

    with pytest.raises(MigrationEvidenceError, match="non-waivable"):
        record_backfill_verification_completion(
            manifest,
            journal,
            plan=plan,
            policy=policy,
            report=report,
            completed_at=datetime(2026, 8, 22, 0, 1, tzinfo=timezone.utc),
            executor_reference="offline-test:fabricated-waiver",
        )


def test_report_must_match_manifest_snapshot_and_policy_identity() -> None:
    manifest = _manifest()
    policy = _policy()
    report = evaluate_reconciliation(manifest, policy, _observations(policy))
    changed_manifest = replace(
        manifest,
        migration_bundle_digest=_digest("changed-bundle"),
    )
    journal, plan = _backfill_plan(changed_manifest)

    with pytest.raises(MigrationManifestMismatchError, match="another immutable"):
        record_backfill_verification_completion(
            changed_manifest,
            journal,
            plan=plan,
            policy=policy,
            report=report,
            completed_at=datetime(2026, 8, 22, 0, 1, tzinfo=timezone.utc),
            executor_reference="offline-test:mismatch",
        )

    changed_policy = replace(policy, policy_version=2)
    journal, plan = _backfill_plan(manifest)
    with pytest.raises(MigrationReconciliationError, match="another policy"):
        record_backfill_verification_completion(
            manifest,
            journal,
            plan=plan,
            policy=changed_policy,
            report=report,
            completed_at=datetime(2026, 8, 22, 0, 1, tzinfo=timezone.utc),
            executor_reference="offline-test:mismatch",
        )


def test_dry_run_and_missing_report_identity_are_rejected() -> None:
    manifest = _manifest()
    policy = _policy()
    report = evaluate_reconciliation(manifest, policy, _observations(policy))
    journal, dry_run = _backfill_plan(
        manifest,
        mode=MigrationExecutionMode.DRY_RUN,
    )

    with pytest.raises(MigrationEvidenceError, match="dry-run"):
        record_backfill_verification_completion(
            manifest,
            journal,
            plan=dry_run,
            policy=policy,
            report=report,
            completed_at=datetime(2026, 8, 22, 0, 1, tzinfo=timezone.utc),
            executor_reference="offline-test:dry-run",
        )

    for missing_policy, missing_report in ((None, report), (policy, None)):
        with pytest.raises(MigrationReconciliationError, match="identity"):
            record_backfill_verification_completion(
                manifest,
                journal,
                plan=dry_run,
                policy=missing_policy,  # type: ignore[arg-type]
                report=missing_report,  # type: ignore[arg-type]
                completed_at=datetime(2026, 8, 22, 0, 1, tzinfo=timezone.utc),
                executor_reference="offline-test:missing",
            )
