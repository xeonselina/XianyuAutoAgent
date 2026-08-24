from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa

from app.services.migration.default_application_enforce import (
    DefaultApplicationEnforcementConflictError,
    DefaultApplicationEnforcementEvidence,
    DefaultApplicationEnforcementInputError,
    DefaultTenantApplicationEnforcementService,
)
from app.services.migration.default_phase_adapters import (
    DefaultMigrationApplicationEnforcementBundle,
    build_default_migration_application_enforce_executor,
)
from inventory_control import ControlBase, ControlDatabase
from inventory_control.default_migration import (
    DefaultTenantMigrationManifest,
    MigrationExecutionMode,
    MigrationExecutionPlan,
    MigrationJournal,
    MigrationJournalFileStore,
    MigrationPhase,
    MigrationPhaseEvidence,
    MigrationPhaseInvocation,
    journal_to_document,
)
from inventory_control.models import (
    DatabaseIdentityControlRecord,
    PlanRevision,
    Subscription,
    SubscriptionEvent,
    Tenant,
    TenantDatabase,
)
from inventory_control.subscriptions import parse_core_entitlements


TENANT_UUID = UUID("84000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("84000000-0000-4000-8000-000000000002")
PLAN_UUID = UUID("84000000-0000-4000-8000-000000000003")
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest() -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="application-enforce-v1",
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        source_schema_name="inventory_management_test",
        baseline_migration_id="baseline-v1",
        core_plan_revision_uuid=PLAN_UUID,
        control_schema_head="202608220026",
        tenant_schema_head="20260824_legacy_history",
        source_snapshot_digest=_digest("source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=_digest("name"),
        first_admin_phone_input_commitment=_digest("phone"),
    )


def _journal(manifest: DefaultTenantMigrationManifest) -> MigrationJournal:
    return MigrationJournal(
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
            )
        ),
    )


def _evidence(
    manifest: DefaultTenantMigrationManifest,
) -> DefaultApplicationEnforcementEvidence:
    return DefaultApplicationEnforcementEvidence(
        manifest_digest=manifest.digest,
        implementation_identity_digest=(
            manifest.implementation_identity_digest
        ),
        migration_bundle_digest=manifest.migration_bundle_digest,
        trusted_route_matrix_digest=_digest("trusted-route-matrix"),
        identity_namespace_matrix_digest=_digest("identity-namespace-matrix"),
        effective_gate_matrix_digest=_digest("effective-gate-matrix"),
        legacy_surface_negative_digest=_digest("legacy-negative-matrix"),
    )


@pytest.fixture
def control_database(mysql_control_database):
    manifest = _manifest()
    database = mysql_control_database
    snapshot = parse_core_entitlements(
        schema_version=1,
        entitlements={
            "features": {"xianyu_sync": True},
            "limits": {"member_seats": 10},
        },
    )
    with database.transaction() as session:
        session.add(
            Tenant(
                id=str(TENANT_UUID),
                name="默认租户",
                status="provisioning",
            )
        )
        session.add(
            TenantDatabase(
                tenant_id=str(TENANT_UUID),
                database_uuid=str(DATABASE_UUID),
                database_instance_key="isolated-test",
                database_name=manifest.source_schema_name,
                status="provisional",
                schema_version=manifest.tenant_schema_head,
                activated_by_registration_commit_uuid=(
                    "84000000-0000-4000-8000-000000000099"
                ),
                activation_route_version=1,
                activation_credential_generation=1,
                dml_username="tenant_dml_g1",
                dml_credential_generation=1,
                dml_root_key_version=1,
                dml_derivation_version=1,
                route_version=1,
                dml_desired_login_state="active",
                dml_observed_login_state="active",
                dml_login_state_version=1,
                platform_read_username="tenant_read_g1",
                platform_read_credential_generation=1,
                platform_read_root_key_version=1,
                platform_read_derivation_version=1,
                platform_read_route_version=1,
            )
        )
        session.add(
            DatabaseIdentityControlRecord(
                tenant_id=str(TENANT_UUID),
                database_uuid=str(DATABASE_UUID),
                expected_schema_generation=3,
                observed_schema_generation=3,
                expected_schema_revision=manifest.tenant_schema_head,
                expected_schema_sha256=_digest("schema"),
                observed_schema_revision=manifest.tenant_schema_head,
                observed_schema_sha256=_digest("schema"),
                identity_created_at=NOW,
                last_verified_at=NOW,
            )
        )
        session.add(
            PlanRevision(
                id=str(PLAN_UUID),
                code="core",
                revision=1,
                name="Core",
                entitlements_schema_version=1,
                entitlements_json={
                    "features": {"xianyu_sync": True},
                    "limits": {"member_seats": 10},
                },
                entitlements_digest=snapshot.digest_sha256,
                active=True,
            )
        )
    yield database


def test_publish_atomically_writes_d60_and_makes_exact_route_ready(
    control_database,
) -> None:
    manifest = _manifest()
    service = DefaultTenantApplicationEnforcementService()

    with control_database.transaction() as session:
        first = service.publish(
            session,
            manifest=manifest,
            journal=_journal(manifest),
            evidence=_evidence(manifest),
        )
    with control_database.transaction() as session:
        replay = service.publish(
            session,
            manifest=manifest,
            journal=_journal(manifest),
            evidence=_evidence(manifest),
        )

    assert first.created is True
    assert replay.created is False
    assert replay.digest == first.digest
    with control_database.new_session() as session:
        assert session.get(Tenant, str(TENANT_UUID)).status == "active"
        assert session.get(TenantDatabase, str(TENANT_UUID)).status == "ready"
        assert session.scalar(
            sa.select(sa.func.count()).select_from(Subscription)
        ) == 1
        event = session.scalar(sa.select(SubscriptionEvent))
        assert event.exact_duration_seconds == 3_153_600_000
        assert event.source_type == "migration_grant"


def test_schema_drift_rolls_back_grant_and_publication(control_database) -> None:
    manifest = _manifest()
    with control_database.transaction() as session:
        session.get(
            DatabaseIdentityControlRecord,
            str(TENANT_UUID),
        ).observed_schema_sha256 = _digest("drifted-schema")

    with control_database.transaction() as session:
        with pytest.raises(DefaultApplicationEnforcementConflictError):
            DefaultTenantApplicationEnforcementService().publish(
                session,
                manifest=manifest,
                journal=_journal(manifest),
                evidence=_evidence(manifest),
            )

    with control_database.new_session() as session:
        assert session.get(Tenant, str(TENANT_UUID)).status == "provisioning"
        assert session.get(TenantDatabase, str(TENANT_UUID)).status == (
            "provisional"
        )
        assert session.scalar(
            sa.select(sa.func.count()).select_from(Subscription)
        ) == 0


def test_evidence_from_another_bundle_is_rejected_before_write(
    control_database,
) -> None:
    manifest = _manifest()
    evidence = _evidence(manifest)
    object.__setattr__(evidence, "migration_bundle_digest", _digest("other"))

    with control_database.transaction() as session:
        with pytest.raises(DefaultApplicationEnforcementInputError):
            DefaultTenantApplicationEnforcementService().publish(
                session,
                manifest=manifest,
                journal=_journal(manifest),
                evidence=evidence,
            )

    with control_database.new_session() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(Subscription)
        ) == 0


class _Verifier:
    def __init__(self, evidence):
        self.evidence = evidence
        self.calls = []

    def verify(self, invocation):
        self.calls.append(invocation)
        return self.evidence


def test_phase_adapter_uses_current_journal_and_replays_stable_evidence(
    control_database,
    tmp_path,
) -> None:
    manifest = _manifest()
    journal = _journal(manifest)
    journal_path = tmp_path / "journal.json"
    journal_path.write_text(
        json.dumps(
            journal_to_document(journal),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n",
        encoding="ascii",
    )
    journal_path.chmod(0o600)
    verifier = _Verifier(_evidence(manifest))
    bundle = DefaultMigrationApplicationEnforcementBundle(
        control_session_factory=control_database.new_session,
        journal_store=MigrationJournalFileStore(journal_path),
        verifier=verifier,
    )
    executor = build_default_migration_application_enforce_executor(
        bundle=bundle
    )
    plan = MigrationExecutionPlan(
        phase=MigrationPhase.APPLICATION_ENFORCE,
        mode=MigrationExecutionMode.APPLY,
        manifest_digest=manifest.digest,
        prerequisites=(),
        completion_conditions=(),
        stop_conditions=(),
        rollback_action="stop before authoritative writes",
        mutations_allowed=True,
    )
    phase_key = "default-migration:" + hashlib.sha256(
        b"default-tenant-migration-phase-v1\x00"
        + manifest.digest
        + b"\x00application_enforce"
    ).hexdigest()
    invocation = MigrationPhaseInvocation(
        manifest=manifest,
        plan=plan,
        phase_execution_key=phase_key,
    )

    first = executor.execute(invocation)
    replay = executor.execute(invocation)

    assert first.result_state_digest == replay.result_state_digest
    assert first.executor_reference == "ordered-phase:application_enforce"
    assert len(verifier.calls) == 2
    assert "默认租户" not in repr(bundle)
