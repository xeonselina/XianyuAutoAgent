"""Create durable D26 tenant deletion workflow and tombstone records."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "202608220015"
down_revision = "202608220014"
branch_labels = None
depends_on = None


DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")


def upgrade() -> None:
    op.create_table(
        "tenant_deletion_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("database_uuid", sa.String(length=36), nullable=False),
        sa.Column(
            "active_tenant_id",
            sa.String(length=36),
            sa.Computed(
                "CASE WHEN status IN ('pending_review', 'cooling_off', "
                "'committing', 'awaiting_offsite_ack', 'releasing_claims', "
                "'dropping', 'failed') THEN tenant_id ELSE NULL END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("requested_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("request_challenge_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("request_revision", sa.BigInteger(), nullable=False),
        sa.Column("execution_generation", sa.BigInteger(), nullable=False),
        sa.Column("executor_fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("current_action_id", sa.String(length=36), nullable=False),
        sa.Column(
            "committed_tenant_access_version", sa.BigInteger(), nullable=False
        ),
        sa.Column("desired_dml_login_state", sa.String(length=16), nullable=False),
        sa.Column("published_dml_generation", sa.BigInteger(), nullable=False),
        sa.Column("latest_dml_generation", sa.BigInteger(), nullable=False),
        sa.Column("candidate_dml_generation", sa.BigInteger(), nullable=True),
        sa.Column("recovery_dispositions_required", sa.Boolean(), nullable=False),
        sa.Column(
            "reviewed_by_platform_admin_id", sa.String(length=36), nullable=True
        ),
        sa.Column("cancelled_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("cancel_challenge_id", sa.String(length=36), nullable=True),
        sa.Column(
            "pre_freeze_tenant_status", sa.String(length=32), nullable=True
        ),
        sa.Column(
            "pre_freeze_suspension_phase", sa.String(length=24), nullable=True
        ),
        sa.Column("failure_resume_status", sa.String(length=24), nullable=True),
        sa.Column("failure_code", sa.String(length=96), nullable=True),
        sa.Column("executor_lease_owner", sa.String(length=128), nullable=True),
        sa.Column("executor_lease_token_digest", DIGEST_TYPE, nullable=True),
        sa.Column(
            "executor_lease_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "executor_lease_recovery_run_id", sa.String(length=36), nullable=True
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execute_not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('pending_review', 'rejected', 'cooling_off', "
            "'cancelled', 'committing', 'awaiting_offsite_ack', "
            "'releasing_claims', 'dropping', 'completed', 'failed')",
            name=op.f("ck_tenant_deletion_requests_status_valid"),
        ),
        sa.CheckConstraint(
            "request_revision >= 1",
            name=op.f("ck_tenant_deletion_requests_revision_positive"),
        ),
        sa.CheckConstraint(
            "execution_generation >= 1",
            name=op.f("ck_tenant_deletion_requests_generation_positive"),
        ),
        sa.CheckConstraint(
            "executor_fencing_token >= 1",
            name=op.f("ck_tenant_deletion_requests_fencing_token_positive"),
        ),
        sa.CheckConstraint(
            "committed_tenant_access_version >= 1",
            name=op.f("ck_tenant_deletion_requests_access_version_positive"),
        ),
        sa.CheckConstraint(
            "published_dml_generation >= 1",
            name=op.f(
                "ck_tenant_deletion_requests_published_dml_generation_positive"
            ),
        ),
        sa.CheckConstraint(
            "latest_dml_generation >= published_dml_generation",
            name=op.f("ck_tenant_deletion_requests_dml_generation_order_valid"),
        ),
        sa.CheckConstraint(
            "candidate_dml_generation IS NULL OR "
            "candidate_dml_generation > latest_dml_generation",
            name=op.f(
                "ck_tenant_deletion_requests_candidate_dml_generation_valid"
            ),
        ),
        sa.CheckConstraint(
            "desired_dml_login_state IN ('active', 'locked')",
            name=op.f("ck_tenant_deletion_requests_desired_dml_state_valid"),
        ),
        sa.CheckConstraint(
            "pre_freeze_tenant_status IS NULL OR pre_freeze_tenant_status IN "
            "('active', 'expired', 'suspending', 'suspended', 'resuming')",
            name=op.f(
                "ck_tenant_deletion_requests_pre_freeze_tenant_status_valid"
            ),
        ),
        sa.CheckConstraint(
            "pre_freeze_suspension_phase IS NULL OR "
            "pre_freeze_suspension_phase IN "
            "('freezing', 'active', 'failed', 'resolving')",
            name=op.f(
                "ck_tenant_deletion_requests_pre_freeze_suspension_phase_valid"
            ),
        ),
        sa.CheckConstraint(
            "failure_resume_status IS NULL OR failure_resume_status IN "
            "('committing', 'awaiting_offsite_ack', 'releasing_claims', "
            "'dropping')",
            name=op.f(
                "ck_tenant_deletion_requests_failure_resume_status_valid"
            ),
        ),
        sa.CheckConstraint(
            "((status = 'failed' AND failure_resume_status IS NOT NULL "
            "AND failure_code IS NOT NULL) OR "
            "(status <> 'failed' AND failure_resume_status IS NULL "
            "AND failure_code IS NULL))",
            name=op.f("ck_tenant_deletion_requests_failure_state_complete"),
        ),
        sa.CheckConstraint(
            "execute_not_before IS NULL OR reviewed_at IS NOT NULL",
            name=op.f("ck_tenant_deletion_requests_cooling_time_has_review"),
        ),
        sa.CheckConstraint(
            "((executor_lease_owner IS NULL "
            "AND executor_lease_token_digest IS NULL "
            "AND executor_lease_expires_at IS NULL "
            "AND executor_lease_recovery_run_id IS NULL) OR "
            "(executor_lease_owner IS NOT NULL "
            "AND executor_lease_token_digest IS NOT NULL "
            "AND executor_lease_expires_at IS NOT NULL "
            "AND executor_lease_recovery_run_id IS NOT NULL))",
            name=op.f("ck_tenant_deletion_requests_executor_lease_complete"),
        ),
        sa.CheckConstraint(
            "executor_lease_token_digest IS NULL OR "
            "length(executor_lease_token_digest) = 32",
            name=op.f(
                "ck_tenant_deletion_requests_executor_lease_digest_length"
            ),
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name=op.f("ck_tenant_deletion_requests_row_version_positive"),
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_tenant_deletion_requests")
        ),
        sa.UniqueConstraint(
            "active_tenant_id",
            name="uq_tenant_deletion_requests_active_tenant",
        ),
        sa.UniqueConstraint(
            "request_challenge_id",
            name="uq_tenant_deletion_requests_request_challenge",
        ),
        sa.UniqueConstraint(
            "cancel_challenge_id",
            name="uq_tenant_deletion_requests_cancel_challenge",
        ),
    )
    op.create_index(
        "ix_tenant_deletion_requests_tenant_status",
        "tenant_deletion_requests",
        ["tenant_id", "status", "request_revision"],
        unique=False,
    )
    op.create_index(
        "ix_tenant_deletion_requests_executor_lease",
        "tenant_deletion_requests",
        ["status", "executor_lease_expires_at"],
        unique=False,
    )

    op.create_table(
        "tenant_deletion_actions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("deletion_request_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("execution_generation", sa.BigInteger(), nullable=False),
        sa.Column("executor_fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=191), nullable=False),
        sa.Column("request_digest", DIGEST_TYPE, nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("failure_code", sa.String(length=96), nullable=True),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('request', 'review_approve', 'review_reject', "
            "'cancel', 'commit')",
            name=op.f("ck_tenant_deletion_actions_kind_valid"),
        ),
        sa.CheckConstraint(
            "outcome IN ('running', 'succeeded', 'failed')",
            name=op.f("ck_tenant_deletion_actions_outcome_valid"),
        ),
        sa.CheckConstraint(
            "execution_generation >= 1",
            name=op.f("ck_tenant_deletion_actions_generation_positive"),
        ),
        sa.CheckConstraint(
            "executor_fencing_token >= 1",
            name=op.f("ck_tenant_deletion_actions_fencing_token_positive"),
        ),
        sa.CheckConstraint(
            "length(request_digest) = 32",
            name=op.f("ck_tenant_deletion_actions_request_digest_length"),
        ),
        sa.CheckConstraint(
            "((outcome = 'failed' AND failure_code IS NOT NULL) OR "
            "(outcome <> 'failed' AND failure_code IS NULL))",
            name=op.f("ck_tenant_deletion_actions_failure_outcome_complete"),
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name=op.f("ck_tenant_deletion_actions_row_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["deletion_request_id"],
            ["tenant_deletion_requests.id"],
            name="fk_tenant_deletion_actions_request",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_deletion_actions")),
        sa.UniqueConstraint(
            "deletion_request_id",
            "idempotency_key",
            name="uq_tenant_deletion_actions_request_idempotency",
        ),
    )
    op.create_index(
        "ix_tenant_deletion_actions_request_kind",
        "tenant_deletion_actions",
        ["deletion_request_id", "kind", "execution_generation"],
        unique=False,
    )

    op.create_table(
        "tenant_deletion_effects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("deletion_request_id", sa.String(length=36), nullable=False),
        sa.Column("action_id", sa.String(length=36), nullable=False),
        sa.Column("effect_kind", sa.String(length=64), nullable=False),
        sa.Column("execution_generation", sa.BigInteger(), nullable=False),
        sa.Column("executor_fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("tenant_access_version", sa.BigInteger(), nullable=False),
        sa.Column("dml_generation", sa.BigInteger(), nullable=True),
        sa.Column("tombstone_sequence", sa.BigInteger(), nullable=True),
        sa.Column(
            "state",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("result_digest", DIGEST_TYPE, nullable=True),
        sa.Column("safe_outcome_code", sa.String(length=64), nullable=True),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('pending', 'succeeded', 'failed', 'superseded')",
            name=op.f("ck_tenant_deletion_effects_state_valid"),
        ),
        sa.CheckConstraint(
            "execution_generation >= 1",
            name=op.f("ck_tenant_deletion_effects_generation_positive"),
        ),
        sa.CheckConstraint(
            "executor_fencing_token >= 1",
            name=op.f("ck_tenant_deletion_effects_fencing_token_positive"),
        ),
        sa.CheckConstraint(
            "tenant_access_version >= 1",
            name=op.f("ck_tenant_deletion_effects_access_version_positive"),
        ),
        sa.CheckConstraint(
            "dml_generation IS NULL OR dml_generation >= 1",
            name=op.f("ck_tenant_deletion_effects_dml_generation_positive"),
        ),
        sa.CheckConstraint(
            "tombstone_sequence IS NULL OR tombstone_sequence >= 1",
            name=op.f(
                "ck_tenant_deletion_effects_tombstone_sequence_positive"
            ),
        ),
        sa.CheckConstraint(
            "result_digest IS NULL OR length(result_digest) = 32",
            name=op.f("ck_tenant_deletion_effects_result_digest_length"),
        ),
        sa.CheckConstraint(
            "((state = 'pending' AND completed_at IS NULL "
            "AND result_digest IS NULL AND safe_outcome_code IS NULL) OR "
            "(state <> 'pending' AND completed_at IS NOT NULL "
            "AND result_digest IS NOT NULL AND safe_outcome_code IS NOT NULL))",
            name=op.f("ck_tenant_deletion_effects_terminal_result_complete"),
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name=op.f("ck_tenant_deletion_effects_row_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["action_id"],
            ["tenant_deletion_actions.id"],
            name="fk_tenant_deletion_effects_action",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["deletion_request_id"],
            ["tenant_deletion_requests.id"],
            name="fk_tenant_deletion_effects_request",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_deletion_effects")),
        sa.UniqueConstraint(
            "deletion_request_id",
            "action_id",
            "execution_generation",
            "effect_kind",
            "tombstone_sequence",
            name="uq_tenant_deletion_effects_generation_kind",
        ),
    )
    op.create_index(
        "ix_tenant_deletion_effects_pending",
        "tenant_deletion_effects",
        ["state", "effect_kind", "created_at"],
        unique=False,
    )

    op.create_table(
        "tenant_deletion_evidence_receipts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("deletion_request_id", sa.String(length=36), nullable=False),
        sa.Column("action_id", sa.String(length=36), nullable=False),
        sa.Column("receipt_kind", sa.String(length=32), nullable=False),
        sa.Column("verifier_kind", sa.String(length=32), nullable=False),
        sa.Column(
            "evidence_schema_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("evidence_digest", DIGEST_TYPE, nullable=False),
        sa.Column("execution_generation", sa.BigInteger(), nullable=False),
        sa.Column("executor_fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("tenant_access_version", sa.BigInteger(), nullable=False),
        sa.Column("tombstone_sequence", sa.BigInteger(), nullable=True),
        sa.Column("tombstone_head_hash", DIGEST_TYPE, nullable=True),
        sa.Column("recovery_run_id", sa.String(length=36), nullable=True),
        sa.Column("recovery_hold_id", sa.String(length=36), nullable=True),
        sa.Column("recovery_hold_revision", sa.BigInteger(), nullable=True),
        sa.Column("recovery_disposition_digest", DIGEST_TYPE, nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "receipt_kind IN ('lockdown', 'cancellation', 'isolation', "
            "'executor_fence', 'offsite_ack', 'claim_release', "
            "'destructive_cleanup')",
            name=op.f("ck_tenant_deletion_evidence_receipts_kind_valid"),
        ),
        sa.CheckConstraint(
            "verifier_kind IN ('control_current_read', "
            "'nas_authenticated_ack', 'provider_claim_current_read', "
            "'destructive_current_read')",
            name=op.f(
                "ck_tenant_deletion_evidence_receipts_verifier_kind_valid"
            ),
        ),
        sa.CheckConstraint(
            "evidence_schema_version = 1",
            name=op.f(
                "ck_tenant_deletion_evidence_receipts_schema_version_supported"
            ),
        ),
        sa.CheckConstraint(
            "execution_generation >= 1",
            name=op.f(
                "ck_tenant_deletion_evidence_receipts_generation_positive"
            ),
        ),
        sa.CheckConstraint(
            "executor_fencing_token >= 1",
            name=op.f(
                "ck_tenant_deletion_evidence_receipts_fencing_token_positive"
            ),
        ),
        sa.CheckConstraint(
            "tenant_access_version >= 1",
            name=op.f(
                "ck_tenant_deletion_evidence_receipts_access_version_positive"
            ),
        ),
        sa.CheckConstraint(
            "length(evidence_digest) = 32",
            name=op.f(
                "ck_tenant_deletion_evidence_receipts_evidence_digest_length"
            ),
        ),
        sa.CheckConstraint(
            "tombstone_sequence IS NULL OR tombstone_sequence >= 1",
            name=op.f(
                "ck_tenant_deletion_evidence_receipts_tombstone_sequence_positive"
            ),
        ),
        sa.CheckConstraint(
            "tombstone_head_hash IS NULL OR length(tombstone_head_hash) = 32",
            name=op.f(
                "ck_tenant_deletion_evidence_receipts_tombstone_head_hash_length"
            ),
        ),
        sa.CheckConstraint(
            "recovery_disposition_digest IS NULL OR "
            "length(recovery_disposition_digest) = 32",
            name=op.f(
                "ck_tenant_deletion_evidence_receipts_recovery_disposition_digest_length"
            ),
        ),
        sa.CheckConstraint(
            "((recovery_run_id IS NULL AND recovery_hold_id IS NULL "
            "AND recovery_hold_revision IS NULL "
            "AND recovery_disposition_digest IS NULL) OR "
            "(recovery_run_id IS NOT NULL AND recovery_hold_id IS NOT NULL "
            "AND recovery_hold_revision IS NOT NULL "
            "AND recovery_hold_revision >= 1 "
            "AND recovery_disposition_digest IS NOT NULL))",
            name=op.f(
                "ck_tenant_deletion_evidence_receipts_recovery_disposition_anchor_complete"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["action_id"],
            ["tenant_deletion_actions.id"],
            name="fk_tenant_deletion_receipts_action",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["deletion_request_id"],
            ["tenant_deletion_requests.id"],
            name="fk_tenant_deletion_receipts_request",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_tenant_deletion_evidence_receipts")
        ),
        sa.UniqueConstraint(
            "deletion_request_id",
            "action_id",
            "execution_generation",
            "receipt_kind",
            name="uq_tenant_deletion_receipts_generation_kind",
        ),
    )
    op.create_index(
        "ix_tenant_deletion_receipts_request_kind",
        "tenant_deletion_evidence_receipts",
        ["deletion_request_id", "receipt_kind", "verified_at"],
        unique=False,
    )

    op.create_table(
        "tenant_deletion_tombstones",
        sa.Column("deletion_request_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("database_uuid", sa.String(length=36), nullable=False),
        sa.Column("ledger_sequence", sa.BigInteger(), nullable=False),
        sa.Column("previous_hash", DIGEST_TYPE, nullable=True),
        sa.Column("record_hash", DIGEST_TYPE, nullable=False),
        sa.Column("head_hash", DIGEST_TYPE, nullable=False),
        sa.Column("checkpoint_root_key_version", sa.BigInteger(), nullable=False),
        sa.Column("checkpoint_mac", DIGEST_TYPE, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("offsite_artifact_checksum", DIGEST_TYPE, nullable=True),
        sa.Column(
            "offsite_acknowledged_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "offsite_authenticated",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "offsite_durably_persisted",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "offsite_checksum_verified",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "offsite_chain_verified",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ledger_sequence >= 1",
            name=op.f("ck_tenant_deletion_tombstones_sequence_positive"),
        ),
        sa.CheckConstraint(
            "previous_hash IS NULL OR length(previous_hash) = 32",
            name=op.f("ck_tenant_deletion_tombstones_previous_hash_length"),
        ),
        sa.CheckConstraint(
            "length(record_hash) = 32",
            name=op.f("ck_tenant_deletion_tombstones_record_hash_length"),
        ),
        sa.CheckConstraint(
            "length(head_hash) = 32",
            name=op.f("ck_tenant_deletion_tombstones_head_hash_length"),
        ),
        sa.CheckConstraint(
            "checkpoint_root_key_version >= 1",
            name=op.f(
                "ck_tenant_deletion_tombstones_checkpoint_key_version_positive"
            ),
        ),
        sa.CheckConstraint(
            "length(checkpoint_mac) = 32",
            name=op.f("ck_tenant_deletion_tombstones_checkpoint_mac_length"),
        ),
        sa.CheckConstraint(
            "offsite_artifact_checksum IS NULL OR "
            "length(offsite_artifact_checksum) = 32",
            name=op.f("ck_tenant_deletion_tombstones_offsite_checksum_length"),
        ),
        sa.CheckConstraint(
            "((offsite_acknowledged_at IS NULL "
            "AND offsite_artifact_checksum IS NULL "
            "AND offsite_authenticated = 0 "
            "AND offsite_durably_persisted = 0 "
            "AND offsite_checksum_verified = 0 "
            "AND offsite_chain_verified = 0) OR "
            "(offsite_acknowledged_at IS NOT NULL "
            "AND offsite_artifact_checksum IS NOT NULL "
            "AND offsite_authenticated = 1 "
            "AND offsite_durably_persisted = 1 "
            "AND offsite_checksum_verified = 1 "
            "AND offsite_chain_verified = 1))",
            name=op.f("ck_tenant_deletion_tombstones_offsite_ack_complete"),
        ),
        sa.PrimaryKeyConstraint(
            "deletion_request_id",
            name=op.f("pk_tenant_deletion_tombstones"),
        ),
        sa.UniqueConstraint(
            "database_uuid", name="uq_tenant_deletion_tombstones_database"
        ),
        sa.UniqueConstraint(
            "ledger_sequence", name="uq_tenant_deletion_tombstones_sequence"
        ),
        sa.UniqueConstraint(
            "tenant_id", name="uq_tenant_deletion_tombstones_tenant"
        ),
    )


def downgrade() -> None:
    op.drop_table("tenant_deletion_tombstones")
    op.drop_table("tenant_deletion_evidence_receipts")
    op.drop_table("tenant_deletion_effects")
    op.drop_table("tenant_deletion_actions")
    op.drop_table("tenant_deletion_requests")
