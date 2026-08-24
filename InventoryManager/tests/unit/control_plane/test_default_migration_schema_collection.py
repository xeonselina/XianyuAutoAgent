from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID

import pytest

from inventory_control.default_migration import (
    DefaultTenantMigrationManifest,
    MigrationReconciliationCollectionError,
    ReconciliationRequirement,
    ReconciliationScope,
    ReconciliationValueKind,
    TenantSchemaObservationCollectorSet,
)
from inventory_control.fleet_migrations import (
    FleetMigrationObservation,
    FleetSchemaIdentity,
    FleetSchemaOperationFence,
    TenantMigrationExecutionContext,
    TenantMigrationObservationPhase,
)


TENANT_UUID = UUID("52000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("52000000-0000-4000-8000-000000000002")


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _identity(generation: int, revision: str, digest: bytes):
    return FleetSchemaIdentity(
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        schema_generation=generation,
        schema_revision=revision,
        schema_sha256=digest,
    )


def _context() -> TenantMigrationExecutionContext:
    return TenantMigrationExecutionContext(
        migration_uuid=UUID("52000000-0000-4000-8000-000000000003"),
        operation_generation=1,
        schema_operation_fence=FleetSchemaOperationFence(
            claim_id=UUID("52000000-0000-4000-8000-000000000004"),
            owner_id="default-migration",
            generation=1,
            fencing_token=1,
            row_version=1,
        ),
        bundle_id="default-tenant-expand",
        bundle_revision="build-20260822.1",
        bundle_sha256=_digest("bundle-ref"),
        source=_identity(8, "rev_8", _digest("schema-8")),
        target=_identity(9, "rev_9", _digest("schema-9")),
    )


def _manifest() -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="default-schema-observer-v1",
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        source_schema_name="inventory_management",
        baseline_migration_id="initial-baseline-v1",
        core_plan_revision_uuid=UUID(
            "52000000-0000-4000-8000-000000000005"
        ),
        control_schema_head="202608220026",
        tenant_schema_head="rev_9",
        source_snapshot_digest=_digest("source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=_digest("name"),
        first_admin_phone_input_commitment=_digest("phone"),
    )


class _Observer:
    def __init__(self, observation=None, error=None):
        self.observation = observation
        self.error = error
        self.calls = []

    def observe(self, connection, *, phase, context):
        self.calls.append((connection, phase, context))
        if self.error is not None:
            raise self.error
        return self.observation


def _requirements():
    return {
        ReconciliationScope.SCHEMA_GENERATION: ReconciliationRequirement(
            key="schema.generation",
            scope=ReconciliationScope.SCHEMA_GENERATION,
            value_kind=ReconciliationValueKind.POSITIVE_INTEGER,
            expected=9,
            tolerance=0,
            disposition_allowed=False,
        ),
        ReconciliationScope.SCHEMA_DIGEST: ReconciliationRequirement(
            key="schema.digest",
            scope=ReconciliationScope.SCHEMA_DIGEST,
            value_kind=ReconciliationValueKind.SHA256_DIGEST,
            expected=_digest("schema-9"),
            tolerance=0,
            disposition_allowed=False,
        ),
    }


def test_collectors_share_one_post_ddl_observation() -> None:
    context = _context()
    observed = FleetMigrationObservation(
        identity=context.target,
        observed_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
    )
    observer = _Observer(observation=observed)
    connection = object()
    selected = TenantSchemaObservationCollectorSet(
        observer=observer,
        connection=connection,
        context=context,
    ).collectors(
        generation_key="schema.generation",
        digest_key="schema.digest",
    )
    requirements = _requirements()

    observations = tuple(
        item.collect(
            manifest=_manifest(),
            requirement=requirements[item.scope],
        )
        for item in selected
    )

    assert {item.key: item.observed for item in observations} == {
        "schema.digest": _digest("schema-9"),
        "schema.generation": 9,
    }
    assert observer.calls == [
        (connection, TenantMigrationObservationPhase.AFTER_DDL, context)
    ]


def test_manifest_requirement_and_observation_identity_fail_closed() -> None:
    context = _context()
    wrong_revision = FleetMigrationObservation(
        identity=_identity(9, "different", _digest("schema-9")),
        observed_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
    )
    collector = TenantSchemaObservationCollectorSet(
        observer=_Observer(observation=wrong_revision),
        connection=object(),
        context=context,
    ).collectors(
        generation_key="schema.generation",
        digest_key="schema.digest",
    )[1]

    with pytest.raises(MigrationReconciliationCollectionError):
        collector.collect(
            manifest=_manifest(),
            requirement=_requirements()[ReconciliationScope.SCHEMA_GENERATION],
        )

    wrong_manifest = _manifest()
    object.__setattr__(
        wrong_manifest,
        "database_uuid",
        UUID("52000000-0000-4000-8000-000000000099"),
    )
    with pytest.raises(MigrationReconciliationCollectionError):
        collector.collect(
            manifest=wrong_manifest,
            requirement=_requirements()[ReconciliationScope.SCHEMA_GENERATION],
        )


def test_observer_failure_is_redacted_and_not_cached() -> None:
    observer = _Observer(error=RuntimeError("secret schema diagnostic"))
    collector = TenantSchemaObservationCollectorSet(
        observer=observer,
        connection=object(),
        context=_context(),
    ).collectors(
        generation_key="schema.generation",
        digest_key="schema.digest",
    )[1]

    with pytest.raises(MigrationReconciliationCollectionError) as caught:
        collector.collect(
            manifest=_manifest(),
            requirement=_requirements()[ReconciliationScope.SCHEMA_GENERATION],
        )

    assert str(caught.value) == "MIGRATION_RECONCILIATION_COLLECTION_FAILED"
    assert "secret" not in str(caught.value)
    assert len(observer.calls) == 1
