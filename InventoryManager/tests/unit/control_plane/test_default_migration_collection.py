from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.default_migration import (
    DefaultMigrationReconciliationRunner,
    DefaultTenantMigrationManifest,
    MigrationReconciliationBlockedError,
    MigrationReconciliationCollectionError,
    ReconciliationObservation,
    ReconciliationPolicy,
    ReconciliationRequirement,
    ReconciliationScope,
    ReconciliationValueKind,
    SqlAlchemyScalarReconciliationCollector,
)
from inventory_control.models import Tenant


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest() -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="default-tenant-collection-v1",
        tenant_uuid=UUID("40000000-0000-4000-8000-000000000001"),
        database_uuid=UUID("40000000-0000-4000-8000-000000000002"),
        source_schema_name="inventory_management",
        baseline_migration_id="initial-baseline-v1",
        core_plan_revision_uuid=UUID(
            "40000000-0000-4000-8000-000000000003"
        ),
        control_schema_head="202608220026",
        tenant_schema_head="20260823_shipping_contract",
        source_snapshot_digest=_digest("source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=_digest("keyed-name"),
        first_admin_phone_input_commitment=_digest("keyed-phone"),
    )


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
    calls: list[str]

    def collect(self, *, manifest, requirement):
        assert manifest == _manifest()
        self.calls.append(requirement.key)
        return ReconciliationObservation(key=self.key, observed=self.observed)


def _collectors(policy, calls):
    return tuple(
        _Collector(key=item.key, observed=item.expected, calls=calls)
        for item in policy.requirements
    )


def test_exact_collectors_run_in_policy_order_and_return_passed_report() -> None:
    policy = _policy()
    calls: list[str] = []
    runner = DefaultMigrationReconciliationRunner(_collectors(policy, calls))

    report = runner.collect_and_evaluate(manifest=_manifest(), policy=policy)

    assert report.passed is True
    assert calls == [item.key for item in policy.requirements]


def test_missing_or_duplicate_collector_fails_before_any_collection() -> None:
    policy = _policy()
    calls: list[str] = []
    complete = _collectors(policy, calls)

    with pytest.raises(MigrationReconciliationCollectionError):
        DefaultMigrationReconciliationRunner(complete[:-1]).collect_and_evaluate(
            manifest=_manifest(),
            policy=policy,
        )
    with pytest.raises(MigrationReconciliationCollectionError):
        DefaultMigrationReconciliationRunner(
            (complete[0], complete[0])
        )
    assert calls == []


def test_unknown_observation_blocks_with_only_redacted_summary() -> None:
    policy = _policy()
    calls: list[str] = []
    collectors = list(_collectors(policy, calls))
    collectors[0].observed = None
    runner = DefaultMigrationReconciliationRunner(tuple(collectors))

    with pytest.raises(MigrationReconciliationBlockedError) as caught:
        runner.collect_and_evaluate(manifest=_manifest(), policy=policy)

    assert caught.value.report.passed is False
    summary = dict(caught.value.redacted_summary())
    assert summary["passed"] is False
    assert summary["finding_counts"]["unknown"] == 1
    assert str(caught.value) == "MIGRATION_RECONCILIATION_BLOCKED"


def test_collector_exception_and_wrong_key_are_stable_safe_failures() -> None:
    policy = _policy()
    calls: list[str] = []
    collectors = list(_collectors(policy, calls))

    class SecretFailureCollector:
        key = collectors[0].key

        def collect(self, *, manifest, requirement):
            raise RuntimeError("customer phone 13800138000")

    with pytest.raises(MigrationReconciliationCollectionError) as caught:
        DefaultMigrationReconciliationRunner(
            (SecretFailureCollector(), *collectors[1:])
        ).collect_and_evaluate(manifest=_manifest(), policy=policy)
    assert "13800138000" not in str(caught.value)

    collectors[0] = _Collector(
        key=collectors[0].key,
        observed=collectors[0].observed,
        calls=calls,
    )
    original_collect = collectors[0].collect

    def wrong_key(**kwargs):
        original_collect(**kwargs)
        return ReconciliationObservation(key="wrong.key", observed=0)

    collectors[0].collect = wrong_key  # type: ignore[method-assign]
    with pytest.raises(MigrationReconciliationCollectionError):
        DefaultMigrationReconciliationRunner(
            tuple(collectors)
        ).collect_and_evaluate(manifest=_manifest(), policy=policy)


def test_sqlalchemy_scalar_collector_reads_one_value_without_commit_or_flush(
    mysql_control_database,
) -> None:
    engine = mysql_control_database.engine
    with Session(engine) as seed_session, seed_session.begin():
        seed_session.add(
            Tenant(
                id="40000000-0000-4000-8000-000000000010",
                name="collector fixture",
                status="active",
            )
        )
    with Session(engine, autoflush=False) as session:
        collector = SqlAlchemyScalarReconciliationCollector(
            key="check.table_row_count",
            session=session,
            statement=sa.select(sa.func.count()).select_from(Tenant),
        )
        requirement = ReconciliationRequirement(
            key="check.table_row_count",
            scope=ReconciliationScope.TABLE_ROW_COUNT,
            value_kind=ReconciliationValueKind.NONNEGATIVE_INTEGER,
            expected=1,
            tolerance=0,
            disposition_allowed=False,
        )

        observation = collector.collect(
            manifest=_manifest(),
            requirement=requirement,
        )

        assert observation.observed == 1
        assert not session.new
        assert not session.dirty


def test_sqlalchemy_collector_rejects_locking_select_and_pending_writes(
    mysql_control_database,
) -> None:
    engine = mysql_control_database.engine
    with Session(engine, autoflush=False) as session:
        with pytest.raises(MigrationReconciliationCollectionError):
            SqlAlchemyScalarReconciliationCollector(
                key="check.table_row_count",
                session=session,
                statement=sa.select(Tenant.id).with_for_update(),
            )
        session.add(
            Tenant(
                id="40000000-0000-4000-8000-000000000011",
                name="pending collector fixture",
                status="active",
            )
        )
        collector = SqlAlchemyScalarReconciliationCollector(
            key="check.table_row_count",
            session=session,
            statement=sa.select(sa.func.count()).select_from(Tenant),
        )
        requirement = ReconciliationRequirement(
            key="check.table_row_count",
            scope=ReconciliationScope.TABLE_ROW_COUNT,
            value_kind=ReconciliationValueKind.NONNEGATIVE_INTEGER,
            expected=0,
            tolerance=0,
            disposition_allowed=False,
        )
        with pytest.raises(MigrationReconciliationCollectionError):
            collector.collect(manifest=_manifest(), requirement=requirement)
        assert session.scalar(sa.select(sa.func.count()).select_from(Tenant)) == 0
