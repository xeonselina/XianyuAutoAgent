from __future__ import annotations

import hashlib
from uuid import UUID

import pytest

from app.services.migration.default_expand_enforce import (
    DefaultControlExpandEvidence,
    DefaultExpandEnforcementInputError,
    DefaultTenantExpandEvidence,
)
from app.services.migration.default_phase_adapters import (
    DefaultControlSchemaExpandStep,
    DefaultMigrationExpandInfrastructureBundle,
    DefaultTenantSchemaExpandStep,
)
from inventory_control.default_migration import (
    DefaultMigrationStepInvocation,
    DefaultTenantMigrationManifest,
    MigrationExecutionMode,
    MigrationExecutionPlan,
    MigrationPhase,
    MigrationPhaseInvocation,
)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest():
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="verified-expand-v1",
        tenant_uuid=UUID("87000000-0000-4000-8000-000000000001"),
        database_uuid=UUID("87000000-0000-4000-8000-000000000002"),
        source_schema_name="inventory_management_test",
        baseline_migration_id="baseline-v1",
        core_plan_revision_uuid=UUID(
            "87000000-0000-4000-8000-000000000003"
        ),
        control_schema_head="202608220026",
        tenant_schema_head="20260823_shipping_contract",
        source_snapshot_digest=_digest("source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=_digest("name"),
        first_admin_phone_input_commitment=_digest("phone"),
    )


def _control(manifest, **extra):
    values = {
        "manifest_digest": manifest.digest,
        "implementation_identity_digest": (
            manifest.implementation_identity_digest
        ),
        "migration_bundle_digest": manifest.migration_bundle_digest,
        "schema_head": manifest.control_schema_head,
        "migration_round_trip_digest": _digest("control-migration"),
        "metadata_model_match_digest": _digest("control-metadata"),
        "control_account_grants_digest": _digest("control-grants"),
        "installation_marker_digest": _digest("installation-marker"),
    }
    values.update(extra)
    return DefaultControlExpandEvidence(**values)


def _tenant(manifest, **extra):
    values = {
        "manifest_digest": manifest.digest,
        "implementation_identity_digest": (
            manifest.implementation_identity_digest
        ),
        "migration_bundle_digest": manifest.migration_bundle_digest,
        "schema_head": manifest.tenant_schema_head,
        "migration_round_trip_digest": _digest("tenant-migration"),
        "metadata_model_match_digest": _digest("tenant-metadata"),
        "database_identity_observation_digest": _digest(
            "database-identity"
        ),
        "tenant_dml_grants_digest": _digest("tenant-dml-grants"),
        "platform_read_grants_digest": _digest("platform-read-grants"),
        "cross_schema_negative_digest": _digest("cross-schema-negative"),
    }
    values.update(extra)
    return DefaultTenantExpandEvidence(**values)


class _Verifier:
    def __init__(self, evidence):
        self.evidence = evidence
        self.calls = []

    def verify(self, invocation):
        self.calls.append(invocation)
        return self.evidence


def _phase_invocation(manifest):
    plan = MigrationExecutionPlan(
        phase=MigrationPhase.EXPAND,
        mode=MigrationExecutionMode.APPLY,
        manifest_digest=manifest.digest,
        prerequisites=(),
        completion_conditions=(),
        stop_conditions=(),
        rollback_action="retain expand evidence",
        mutations_allowed=True,
    )
    key = "default-migration:" + hashlib.sha256(
        b"default-tenant-migration-phase-v1\x00"
        + manifest.digest
        + b"\x00expand"
    ).hexdigest()
    return MigrationPhaseInvocation(
        manifest=manifest,
        plan=plan,
        phase_execution_key=key,
    )


def _step_invocation(phase, name):
    key = "default-step:" + hashlib.sha256(
        b"default-migration-step-v1\x00"
        + phase.phase_execution_key.encode("ascii")
        + b"\x00"
        + name.encode("ascii")
    ).hexdigest()
    return DefaultMigrationStepInvocation(
        phase_invocation=phase,
        step_name=name,
        step_execution_key=key,
    )


def test_expand_verifier_steps_bind_both_schema_heads_and_grant_matrices():
    manifest = _manifest()
    control = _Verifier(_control(manifest))
    tenant = _Verifier(_tenant(manifest))
    bundle = DefaultMigrationExpandInfrastructureBundle(
        control_verifier=control,
        tenant_verifier=tenant,
    )
    phase = _phase_invocation(manifest)
    control_step = DefaultControlSchemaExpandStep(bundle)
    tenant_step = DefaultTenantSchemaExpandStep(bundle)

    control_result = control_step.execute(
        _step_invocation(phase, control_step.name)
    )
    tenant_result = tenant_step.execute(
        _step_invocation(phase, tenant_step.name)
    )

    assert control_result.executor_reference == (
        "expand-infrastructure:control_schema_expand"
    )
    assert tenant_result.executor_reference == (
        "expand-infrastructure:tenant_schema_expand"
    )
    assert control_result.result_digest != tenant_result.result_digest
    assert len(control.calls) == len(tenant.calls) == 1


@pytest.mark.parametrize(
    "builder",
    [
        lambda manifest: _control(
            manifest,
            production_write_identity_used=True,
        ),
        lambda manifest: _tenant(manifest, provider_side_effect_count=1),
        lambda manifest: _tenant(manifest, print_side_effect_count=1),
    ],
)
def test_expand_evidence_rejects_production_authority_or_side_effects(builder):
    with pytest.raises(DefaultExpandEnforcementInputError):
        builder(_manifest())


def test_expand_evidence_cannot_be_reused_for_another_schema_head():
    manifest = _manifest()
    evidence = _tenant(manifest)
    object.__setattr__(evidence, "schema_head", "another-head")

    with pytest.raises(DefaultExpandEnforcementInputError):
        evidence.require_manifest(manifest)
