from __future__ import annotations

import hashlib
from uuid import UUID

import pytest
import sqlalchemy as sa

from app.services.migration import (
    DefaultControlInstallationMarkerObserver,
    DefaultExpandAlembicBinding,
    DefaultTenantDatabaseIdentityEstablisher,
    QualifiedDefaultControlExpandVerifier,
    QualifiedDefaultTenantExpandVerifier,
)
from app.services.migration.default_expand_enforce import (
    DefaultExpandEnforcementInputError,
)
from inventory_control.models import Installation
from inventory_control.default_migration import (
    DefaultMigrationStepInvocation,
    DefaultMySqlTenantGrantMatrixObservation,
    DefaultSchemaApplyReceipt,
    DefaultSchemaQualificationReceipt,
    DefaultSchemaQualificationTarget,
    DefaultTenantMigrationManifest,
    MigrationExecutionMode,
    MigrationExecutionPlan,
    MigrationPhase,
    MigrationPhaseInvocation,
)


CONTROL_HEAD = "202608230038"
MYSQL_TEST_TARGET = DefaultSchemaQualificationTarget(
    mysql_database_name="inventory_management_test",
    real_test_database_authorized=True,
)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _invocation() -> DefaultMigrationStepInvocation:
    manifest = DefaultTenantMigrationManifest(
        migration_idempotency_key="qualified-control-expand-v1",
        tenant_uuid=UUID("89000000-0000-4000-8000-000000000001"),
        database_uuid=UUID("89000000-0000-4000-8000-000000000002"),
        source_schema_name="inventory_management_test",
        baseline_migration_id="baseline-v1",
        core_plan_revision_uuid=UUID(
            "89000000-0000-4000-8000-000000000003"
        ),
        control_schema_head=CONTROL_HEAD,
        tenant_schema_head="20260823_shipping_contract",
        source_snapshot_digest=_digest("source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=_digest("name"),
        first_admin_phone_input_commitment=_digest("phone"),
    )
    plan = MigrationExecutionPlan(
        phase=MigrationPhase.EXPAND,
        mode=MigrationExecutionMode.APPLY,
        manifest_digest=manifest.digest,
        prerequisites=(),
        completion_conditions=(),
        stop_conditions=(),
        rollback_action="retain expand facts",
        mutations_allowed=True,
    )
    phase_key = "default-migration:" + hashlib.sha256(
        b"default-tenant-migration-phase-v1\x00"
        + manifest.digest
        + b"\x00expand"
    ).hexdigest()
    phase = MigrationPhaseInvocation(
        manifest=manifest,
        plan=plan,
        phase_execution_key=phase_key,
    )
    step_key = "default-step:" + hashlib.sha256(
        b"default-migration-step-v1\x00"
        + phase_key.encode("ascii")
        + b"\x00control_schema_expand"
    ).hexdigest()
    return DefaultMigrationStepInvocation(
        phase_invocation=phase,
        step_name="control_schema_expand",
        step_execution_key=step_key,
    )


class _Connection:
    def __init__(self, identity: str) -> None:
        self.identity = identity
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Runner:
    def __init__(
        self,
        *,
        schema_head: str,
        baseline_revision: str | None,
    ) -> None:
        self.schema_head = schema_head
        self.baseline_revision = baseline_revision

    def qualify(self, connection, *, target):
        return DefaultSchemaQualificationReceipt(
            schema_head=self.schema_head,
            baseline_revision=self.baseline_revision,
            dialect="mysql",
            migration_round_trip_digest=_digest("round-trip"),
            metadata_model_match_digest=_digest("qualified-metadata"),
            target_identity_digest=_digest(connection.identity),
        )

    def apply(self, connection, *, target):
        return DefaultSchemaApplyReceipt(
            schema_head=self.schema_head,
            dialect="mysql",
            migration_apply_digest=_digest("apply"),
            metadata_model_match_digest=_digest("applied-metadata"),
            target_identity_digest=_digest(connection.identity),
        )


class _Matrix:
    def verify(self):
        return DefaultMySqlTenantGrantMatrixObservation(
            dml_grants_digest=_digest("dml-grants"),
            platform_read_grants_digest=_digest("platform-grants"),
            cross_schema_negative_digest=_digest("cross-schema"),
        )


class _MisboundRunner:
    def __init__(self, *, wrong_head=False):
        self.wrong_head = wrong_head
        self.apply_calls = 0

    def qualify(self, connection, *, target):
        return DefaultSchemaQualificationReceipt(
            schema_head=(
                "another-head" if self.wrong_head else CONTROL_HEAD
            ),
            baseline_revision=None,
            dialect="mysql",
            migration_round_trip_digest=_digest("misbound-round-trip"),
            metadata_model_match_digest=_digest("misbound-metadata"),
            target_identity_digest=_digest("same-physical-target"),
        )

    def apply(self, connection, *, target):
        self.apply_calls += 1
        return DefaultSchemaApplyReceipt(
            schema_head=CONTROL_HEAD,
            dialect="mysql",
            migration_apply_digest=_digest("misbound-apply"),
            metadata_model_match_digest=_digest("misbound-apply-metadata"),
            target_identity_digest=_digest("same-physical-target"),
        )


def test_control_verifier_binds_qualified_and_forward_only_receipts():
    opened: list[_Connection] = []

    def qualification_connection():
        connection = _Connection("control-qualification")
        opened.append(connection)
        return connection

    def apply_connection():
        connection = _Connection("control-apply")
        opened.append(connection)
        return connection

    binding = DefaultExpandAlembicBinding(
        qualification_connection_factory=qualification_connection,
        qualification_target=MYSQL_TEST_TARGET,
        apply_connection_factory=apply_connection,
        apply_target=MYSQL_TEST_TARGET,
        runner=_Runner(
            schema_head=CONTROL_HEAD,
            baseline_revision=None,
        ),
    )
    observed_apply_targets: list[str] = []

    def marker(connection):
        observed_apply_targets.append(connection.identity)
        return _digest("installation-marker")

    verifier = QualifiedDefaultControlExpandVerifier(
        alembic=binding,
        control_account_grants_observer=lambda: _digest("control-grants"),
        installation_marker_observer=marker,
    )
    evidence = verifier.verify(_invocation())
    replay = verifier.verify(_invocation())
    assert evidence.digest == replay.digest
    assert evidence.schema_head == CONTROL_HEAD
    assert observed_apply_targets == ["control-apply", "control-apply"]
    assert len(opened) == 4
    assert all(connection.closed for connection in opened)


def test_observer_failure_produces_no_expand_evidence():
    binding = DefaultExpandAlembicBinding(
        qualification_connection_factory=lambda: _Connection(
            "control-qualification"
        ),
        qualification_target=MYSQL_TEST_TARGET,
        apply_connection_factory=lambda: _Connection("control-apply"),
        apply_target=MYSQL_TEST_TARGET,
        runner=_Runner(
            schema_head=CONTROL_HEAD,
            baseline_revision=None,
        ),
    )
    verifier = QualifiedDefaultControlExpandVerifier(
        alembic=binding,
        control_account_grants_observer=lambda: b"invalid",
        installation_marker_observer=lambda connection: _digest("marker"),
    )
    with pytest.raises(DefaultExpandEnforcementInputError):
        verifier.verify(_invocation())


def test_tenant_verifier_requires_one_bound_dual_account_matrix():
    verifier = QualifiedDefaultTenantExpandVerifier(
        alembic=DefaultExpandAlembicBinding(
            qualification_connection_factory=lambda: _Connection(
                "tenant-qualification"
            ),
            qualification_target=MYSQL_TEST_TARGET,
            apply_connection_factory=lambda: _Connection("tenant-apply"),
            apply_target=MYSQL_TEST_TARGET,
            runner=_Runner(
                schema_head="20260823_shipping_contract",
                baseline_revision="20260807_damage_notes",
            ),
        ),
        database_identity_establisher=lambda connection, manifest: _digest(
            "database-identity"
        ),
        grant_matrix_verifier=_Matrix(),
    )
    evidence = verifier.verify(_invocation())
    assert evidence.schema_head == "20260823_shipping_contract"
    assert evidence.tenant_dml_grants_digest == _digest("dml-grants")
    assert evidence.platform_read_grants_digest == _digest(
        "platform-grants"
    )
    assert evidence.cross_schema_negative_digest == _digest("cross-schema")


def test_wrong_head_stops_before_apply_and_same_physical_target_is_rejected():
    wrong_head = _MisboundRunner(wrong_head=True)
    wrong_binding = DefaultExpandAlembicBinding(
        qualification_connection_factory=lambda: _Connection("same-target"),
        qualification_target=MYSQL_TEST_TARGET,
        apply_connection_factory=lambda: _Connection("same-target"),
        apply_target=MYSQL_TEST_TARGET,
        runner=wrong_head,
    )
    same_target = _MisboundRunner()
    same_binding = DefaultExpandAlembicBinding(
        qualification_connection_factory=lambda: _Connection("same-target"),
        qualification_target=MYSQL_TEST_TARGET,
        apply_connection_factory=lambda: _Connection("same-target"),
        apply_target=MYSQL_TEST_TARGET,
        runner=same_target,
    )
    with pytest.raises(DefaultExpandEnforcementInputError):
        wrong_binding.run(expected_schema_head=CONTROL_HEAD)
    assert wrong_head.apply_calls == 0
    with pytest.raises(DefaultExpandEnforcementInputError):
        same_binding.run(expected_schema_head=CONTROL_HEAD)
    assert same_target.apply_calls == 1


def test_tenant_identity_establisher_writes_once_and_replays_stably(
    mysql_routed_database,
):
    engine = mysql_routed_database.engine
    invocation = _invocation()
    establisher = DefaultTenantDatabaseIdentityEstablisher(
        schema_generation=3
    )
    with engine.connect() as connection:
        first = establisher(connection, invocation.phase_invocation.manifest)
        replay = establisher(connection, invocation.phase_invocation.manifest)
        assert first == replay
        assert connection.execute(
            sa.text("SELECT COUNT(*) FROM database_identity")
        ).scalar_one() == 1
        connection.rollback()


def test_control_installation_observer_requires_one_matching_live_marker(
    mysql_routed_database,
):
    engine = mysql_routed_database.engine
    fingerprint = "a" * 64
    with engine.begin() as connection:
        connection.execute(
            sa.insert(Installation).values(
                id="89000000-0000-4000-8000-000000000010",
                marker_fingerprint=fingerprint,
                row_version=1,
            )
        )
    observer = DefaultControlInstallationMarkerObserver(
        expected_installation_fingerprint=fingerprint
    )
    with engine.connect() as connection:
        first = observer(connection)
        replay = observer(connection)
        assert first == replay
        assert not connection.in_transaction()
    with engine.begin() as connection:
        connection.execute(
            sa.insert(Installation).values(
                id="89000000-0000-4000-8000-000000000011",
                marker_fingerprint="b" * 64,
                row_version=1,
            )
        )
    with engine.connect() as connection:
        with pytest.raises(DefaultExpandEnforcementInputError):
            observer(connection)
