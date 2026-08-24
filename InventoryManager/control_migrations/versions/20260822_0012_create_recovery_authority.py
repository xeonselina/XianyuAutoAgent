"""Create recovery epochs, tenant holds, and release actions."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "202608220012"
down_revision = "202608220011"
branch_labels = None
depends_on = None


DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")


def upgrade() -> None:
    op.create_table(
        "disaster_recovery_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("source_manifest_digest", DIGEST_TYPE, nullable=True),
        sa.Column("source_snapshot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "applied_tombstone_head_digest",
            DIGEST_TYPE,
            nullable=True,
        ),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "current_run_marker",
            sa.String(length=16),
            sa.Computed(
                "CASE WHEN status = 'superseded' THEN NULL ELSE 'current' END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "expected_survivor_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "actual_survivor_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("sealed_coverage_digest", DIGEST_TYPE, nullable=True),
        sa.Column("final_coverage_digest", DIGEST_TYPE, nullable=True),
        sa.Column("accepted_smoke_evidence_uuid", sa.String(length=36), nullable=True),
        sa.Column(
            "host_installation_fingerprint", sa.String(length=64), nullable=False
        ),
        sa.Column(
            "deployment_marker_fingerprint", sa.String(length=64), nullable=False
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewing_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('initial_baseline', 'host_restore')",
            name=op.f("ck_disaster_recovery_runs_kind_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('installing', 'reviewing', 'completed', "
            "'failed_closed', 'superseded')",
            name=op.f("ck_disaster_recovery_runs_status_valid"),
        ),
        sa.CheckConstraint(
            "policy_version >= 1",
            name=op.f("ck_disaster_recovery_runs_policy_version_positive"),
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name=op.f("ck_disaster_recovery_runs_row_version_positive"),
        ),
        sa.CheckConstraint(
            "expected_survivor_count >= 0",
            name=op.f(
                "ck_disaster_recovery_runs_expected_survivor_count_nonnegative"
            ),
        ),
        sa.CheckConstraint(
            "actual_survivor_count >= 0",
            name=op.f(
                "ck_disaster_recovery_runs_actual_survivor_count_nonnegative"
            ),
        ),
        sa.CheckConstraint(
            "source_manifest_digest IS NULL OR length(source_manifest_digest) = 32",
            name=op.f("ck_disaster_recovery_runs_source_manifest_digest_length"),
        ),
        sa.CheckConstraint(
            "sealed_coverage_digest IS NULL OR length(sealed_coverage_digest) = 32",
            name=op.f("ck_disaster_recovery_runs_sealed_coverage_digest_length"),
        ),
        sa.CheckConstraint(
            "final_coverage_digest IS NULL OR length(final_coverage_digest) = 32",
            name=op.f("ck_disaster_recovery_runs_final_coverage_digest_length"),
        ),
        sa.CheckConstraint(
            "applied_tombstone_head_digest IS NULL OR "
            "length(applied_tombstone_head_digest) = 32",
            name=op.f("ck_disaster_recovery_runs_tombstone_head_digest_length"),
        ),
        sa.CheckConstraint(
            "length(host_installation_fingerprint) = 64",
            name=op.f("ck_disaster_recovery_runs_host_fingerprint_length"),
        ),
        sa.CheckConstraint(
            "length(deployment_marker_fingerprint) = 64",
            name=op.f("ck_disaster_recovery_runs_marker_fingerprint_length"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('reviewing', 'completed') OR reviewing_at IS NOT NULL",
            name=op.f("ck_disaster_recovery_runs_reviewing_status_has_time"),
        ),
        sa.CheckConstraint(
            "status <> 'completed' OR completed_at IS NOT NULL",
            name=op.f("ck_disaster_recovery_runs_completed_status_has_time"),
        ),
        sa.CheckConstraint(
            "status <> 'superseded' OR superseded_at IS NOT NULL",
            name=op.f("ck_disaster_recovery_runs_superseded_status_has_time"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_disaster_recovery_runs")),
        sa.UniqueConstraint(
            "current_run_marker",
            name="uq_disaster_recovery_runs_current_marker",
        ),
    )

    op.create_table(
        "tenant_recovery_holds",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("recovery_run_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("database_uuid", sa.String(length=36), nullable=False),
        sa.Column(
            "created_from_registration_commit_uuid",
            sa.String(length=36),
            nullable=True,
        ),
        sa.Column("initial_hold_revision", sa.BigInteger(), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("terminal_reason_code", sa.String(length=64), nullable=True),
        sa.Column(
            "hold_revision",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("snapshot_underlying_status", sa.String(length=32), nullable=False),
        sa.Column("snapshot_access_version", sa.BigInteger(), nullable=False),
        sa.Column(
            "expected_dml_login_state_version", sa.BigInteger(), nullable=False
        ),
        sa.Column("dml_convergence_status", sa.String(length=24), nullable=False),
        sa.Column("review_reason_code", sa.String(length=64), nullable=True),
        sa.Column("review_evidence_type", sa.String(length=32), nullable=True),
        sa.Column(
            "review_evidence_reference", sa.String(length=160), nullable=True
        ),
        sa.Column(
            "reviewed_by_platform_admin_id", sa.String(length=36), nullable=True
        ),
        sa.Column(
            "reviewed_by_platform_session_id", sa.String(length=36), nullable=True
        ),
        sa.Column("released_by_action_uuid", sa.String(length=36), nullable=True),
        sa.Column("deletion_request_uuid", sa.String(length=36), nullable=True),
        sa.Column("tombstone_ledger_sequence", sa.BigInteger(), nullable=True),
        sa.Column("tombstone_record_hash", DIGEST_TYPE, nullable=True),
        sa.Column("held_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('held', 'reviewing', 'released', 'kept_closed', "
            "'tombstoned')",
            name=op.f("ck_tenant_recovery_holds_state_valid"),
        ),
        sa.CheckConstraint(
            "snapshot_underlying_status IN ('provisioning', 'active', 'expired', "
            "'suspending', 'suspended', 'resuming', 'deletion_cooling_off', "
            "'deletion_committing', 'deleted')",
            name=op.f("ck_tenant_recovery_holds_snapshot_underlying_status_valid"),
        ),
        sa.CheckConstraint(
            "dml_convergence_status IN "
            "('pending_lock', 'locked', 'active', 'failed_closed')",
            name=op.f("ck_tenant_recovery_holds_dml_convergence_status_valid"),
        ),
        sa.CheckConstraint(
            "hold_revision >= 1",
            name=op.f("ck_tenant_recovery_holds_hold_revision_positive"),
        ),
        sa.CheckConstraint(
            "snapshot_access_version >= 1",
            name=op.f("ck_tenant_recovery_holds_snapshot_access_version_positive"),
        ),
        sa.CheckConstraint(
            "expected_dml_login_state_version >= 1",
            name=op.f("ck_tenant_recovery_holds_dml_version_positive"),
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name=op.f("ck_tenant_recovery_holds_row_version_positive"),
        ),
        sa.CheckConstraint(
            "((created_from_registration_commit_uuid IS NULL "
            "AND initial_hold_revision IS NULL) OR "
            "(created_from_registration_commit_uuid IS NOT NULL "
            "AND initial_hold_revision IS NOT NULL "
            "AND initial_hold_revision >= 1))",
            name=op.f("ck_tenant_recovery_holds_registration_anchor_complete"),
        ),
        sa.CheckConstraint(
            "state <> 'released' OR released_at IS NOT NULL",
            name=op.f("ck_tenant_recovery_holds_released_state_has_time"),
        ),
        sa.CheckConstraint(
            "((state = 'tombstoned' "
            "AND terminal_reason_code = 'superseded_by_deletion' "
            "AND deletion_request_uuid IS NOT NULL "
            "AND tombstone_ledger_sequence IS NOT NULL "
            "AND tombstone_record_hash IS NOT NULL "
            "AND tombstoned_at IS NOT NULL) OR "
            "(state <> 'tombstoned' AND terminal_reason_code IS NULL "
            "AND tombstone_ledger_sequence IS NULL "
            "AND tombstone_record_hash IS NULL "
            "AND tombstoned_at IS NULL))",
            name=op.f(
                "ck_tenant_recovery_holds_tombstone_evidence_matches_state"
            ),
        ),
        sa.CheckConstraint(
            "tombstone_record_hash IS NULL OR length(tombstone_record_hash) = 32",
            name=op.f("ck_tenant_recovery_holds_tombstone_record_hash_length"),
        ),
        sa.ForeignKeyConstraint(
            ["recovery_run_id"],
            ["disaster_recovery_runs.id"],
            name="fk_recovery_holds_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_recovery_holds")),
        sa.UniqueConstraint(
            "recovery_run_id",
            "tenant_id",
            name="uq_tenant_recovery_holds_run_tenant",
        ),
        sa.UniqueConstraint(
            "released_by_action_uuid",
            name=op.f("uq_tenant_recovery_holds_released_by_action_uuid"),
        ),
    )
    op.create_index(
        "ix_tenant_recovery_holds_tenant_state",
        "tenant_recovery_holds",
        ["tenant_id", "state"],
        unique=False,
    )

    op.create_table(
        "disaster_recovery_release_actions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("recovery_run_id", sa.String(length=36), nullable=False),
        sa.Column("hold_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("expected_hold_revision", sa.BigInteger(), nullable=False),
        sa.Column("expected_tenant_row_version", sa.BigInteger(), nullable=False),
        sa.Column("expected_access_version", sa.BigInteger(), nullable=False),
        sa.Column(
            "expected_dml_login_state_version", sa.BigInteger(), nullable=False
        ),
        sa.Column(
            "expected_published_route_version", sa.BigInteger(), nullable=False
        ),
        sa.Column("candidate_generation", sa.BigInteger(), nullable=True),
        sa.Column("platform_admin_id", sa.String(length=36), nullable=False),
        sa.Column("platform_session_id", sa.String(length=36), nullable=False),
        sa.Column("recent_mfa_method", sa.String(length=16), nullable=False),
        sa.Column("recent_mfa_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("evidence_type", sa.String(length=32), nullable=False),
        sa.Column("evidence_reference", sa.String(length=160), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", DIGEST_TYPE, nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("safe_outcome_code", sa.String(length=64), nullable=True),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('release', 'keep_closed')",
            name=op.f("ck_disaster_recovery_release_actions_decision_valid"),
        ),
        sa.CheckConstraint(
            "state IN ('requested', 'running', 'succeeded', 'failed', "
            "'superseded')",
            name=op.f("ck_disaster_recovery_release_actions_state_valid"),
        ),
        sa.CheckConstraint(
            "recent_mfa_method IN ('totp', 'recovery_code')",
            name=op.f(
                "ck_disaster_recovery_release_actions_recent_mfa_method_valid"
            ),
        ),
        sa.CheckConstraint(
            "length(request_digest) = 32",
            name=op.f(
                "ck_disaster_recovery_release_actions_request_digest_length"
            ),
        ),
        sa.CheckConstraint(
            "expected_hold_revision >= 1",
            name=op.f(
                "ck_disaster_recovery_release_actions_hold_revision_positive"
            ),
        ),
        sa.CheckConstraint(
            "expected_tenant_row_version >= 1",
            name=op.f(
                "ck_disaster_recovery_release_actions_tenant_row_version_positive"
            ),
        ),
        sa.CheckConstraint(
            "expected_access_version >= 1",
            name=op.f(
                "ck_disaster_recovery_release_actions_access_version_positive"
            ),
        ),
        sa.CheckConstraint(
            "expected_dml_login_state_version >= 1",
            name=op.f(
                "ck_disaster_recovery_release_actions_dml_login_version_positive"
            ),
        ),
        sa.CheckConstraint(
            "expected_published_route_version >= 1",
            name=op.f(
                "ck_disaster_recovery_release_actions_route_version_positive"
            ),
        ),
        sa.CheckConstraint(
            "candidate_generation IS NULL OR candidate_generation >= 1",
            name=op.f(
                "ck_disaster_recovery_release_actions_candidate_positive"
            ),
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name=op.f("ck_disaster_recovery_release_actions_row_version_positive"),
        ),
        sa.CheckConstraint(
            "state NOT IN ('succeeded', 'failed', 'superseded') "
            "OR completed_at IS NOT NULL",
            name=op.f(
                "ck_disaster_recovery_release_actions_terminal_state_has_time"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["recovery_run_id"],
            ["disaster_recovery_runs.id"],
            name="fk_dr_release_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["hold_id"],
            ["tenant_recovery_holds.id"],
            name="fk_dr_release_hold",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["platform_admin_id"],
            ["platform_admins.id"],
            name="fk_dr_release_admin",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["platform_session_id"],
            ["platform_admin_sessions.id"],
            name="fk_dr_release_session",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_disaster_recovery_release_actions")
        ),
        sa.UniqueConstraint(
            "recovery_run_id",
            "tenant_id",
            "platform_admin_id",
            "idempotency_key",
            name="uq_dr_release_actions_actor_idempotency",
        ),
    )
    op.create_index(
        "ix_dr_release_actions_run_tenant_state",
        "disaster_recovery_release_actions",
        ["recovery_run_id", "tenant_id", "state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("disaster_recovery_release_actions")
    op.drop_table("tenant_recovery_holds")
    op.drop_table("disaster_recovery_runs")
