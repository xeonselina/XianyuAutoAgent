"""Create fenced registration workflows and immutable outcome anchors.

Revision ID: 202608220010
Revises: 202608220009
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "202608220010"
down_revision = "202608220009"
branch_labels = None
depends_on = None


HASH = sa.LargeBinary(length=32).with_variant(mysql.BINARY(32), "mysql")
REGISTRATION_LEASE_EXPIRY_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)


def upgrade() -> None:
    op.create_table(
        "tenant_registration_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("redemption_code_id", sa.String(length=36), nullable=False),
        sa.Column("requested_tenant_name", sa.String(length=255), nullable=True),
        sa.Column("provisional_tenant_uuid", sa.String(length=36), nullable=True),
        sa.Column("provisional_database_uuid", sa.String(length=36), nullable=True),
        sa.Column("registration_commit_uuid", sa.String(length=36), nullable=True),
        sa.Column("superseded_by_replacement_uuid", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", HASH, nullable=False),
        sa.Column("provisioning_execution_generation", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_token", sa.String(length=128), nullable=True),
        sa.Column(
            "lease_expires_at",
            REGISTRATION_LEASE_EXPIRY_TYPE,
            nullable=True,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_safe_error_code", sa.String(length=64), nullable=True),
        sa.Column("recovery_run_uuid", sa.String(length=36), nullable=False),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('otp_verified', 'reserved', 'provisioning', 'ready', "
            "'committing', 'active', 'failed', 'identity_conflict', "
            "'security_blocked', 'superseded_by_replacement', "
            "'integrity_blocked', 'recovery_review')",
            name="ck_tenant_registration_attempts_status_valid",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_tenant_registration_attempts_attempt_count_nonnegative"),
        sa.CheckConstraint("length(request_digest) = 32", name="ck_tenant_registration_attempts_request_digest_length"),
        sa.CheckConstraint("provisioning_execution_generation >= 1", name="ck_tenant_registration_attempts_provisioning_generation_positive"),
        sa.CheckConstraint("requested_tenant_name IS NULL OR length(trim(requested_tenant_name)) BETWEEN 1 AND 255", name="ck_tenant_registration_attempts_requested_tenant_name_bounded"),
        sa.CheckConstraint("row_version >= 1", name="ck_tenant_registration_attempts_row_version_positive"),
        sa.CheckConstraint(
            "((status IN ('provisioning', 'ready', 'committing') "
            "AND lease_owner IS NOT NULL AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(status NOT IN ('provisioning', 'ready', 'committing') "
            "AND lease_owner IS NULL AND lease_token IS NULL "
            "AND lease_expires_at IS NULL))",
            name="ck_tenant_registration_attempts_lease_matches_status",
        ),
        sa.CheckConstraint(
            "((status = 'active' AND registration_commit_uuid IS NOT NULL) OR "
            "(status <> 'active' AND registration_commit_uuid IS NULL))",
            name="ck_tenant_registration_attempts_commit_matches_active_status",
        ),
        sa.CheckConstraint(
            "((status = 'superseded_by_replacement' "
            "AND superseded_by_replacement_uuid IS NOT NULL AND superseded_at IS NOT NULL) OR "
            "(status <> 'superseded_by_replacement' "
            "AND superseded_by_replacement_uuid IS NULL AND superseded_at IS NULL))",
            name="ck_tenant_registration_attempts_replacement_status_match",
        ),
        sa.ForeignKeyConstraint(["redemption_code_id"], ["redemption_codes.id"], name="fk_reg_attempt_code", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_tenant_registration_attempts_user_id_users", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_registration_attempts"),
        sa.UniqueConstraint("idempotency_key", name="uq_registration_attempts_idempotency"),
        sa.UniqueConstraint("redemption_code_id", name="uq_registration_attempts_code"),
        sa.UniqueConstraint("registration_commit_uuid", name="uq_registration_attempts_commit"),
        sa.UniqueConstraint("superseded_by_replacement_uuid", name="uq_registration_attempts_replacement"),
    )
    op.create_index("ix_registration_attempts_status_lease", "tenant_registration_attempts", ["status", "lease_expires_at"], unique=False)
    op.create_index("ix_registration_attempts_user_status", "tenant_registration_attempts", ["user_id", "status", "created_at"], unique=False)

    op.create_table(
        "redemption_code_replacements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_code_uuid", sa.String(length=36), nullable=False),
        sa.Column("replacement_code_uuid", sa.String(length=36), nullable=False),
        sa.Column("source_attempt_uuid", sa.String(length=36), nullable=True),
        sa.Column("source_user_uuid", sa.String(length=36), nullable=True),
        sa.Column("source_provisional_tenant_uuid", sa.String(length=36), nullable=True),
        sa.Column("source_provisional_database_uuid", sa.String(length=36), nullable=True),
        sa.Column("chain_root_code_uuid", sa.String(length=36), nullable=False),
        sa.Column("chain_generation", sa.BigInteger(), nullable=False),
        sa.Column("plan_revision_uuid", sa.String(length=36), nullable=False),
        sa.Column("entitlements_schema_version", sa.Integer(), nullable=False),
        sa.Column("entitlements_digest", HASH, nullable=False),
        sa.Column("service_duration_seconds", sa.BigInteger(), nullable=False),
        sa.Column("replacement_redeem_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fenced_provisioning_generation", sa.BigInteger(), nullable=True),
        sa.Column("platform_admin_uuid", sa.String(length=36), nullable=False),
        sa.Column("platform_session_uuid", sa.String(length=36), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", HASH, nullable=False),
        sa.Column("expected_source_code_row_version", sa.BigInteger(), nullable=False),
        sa.Column("expected_source_attempt_row_version", sa.BigInteger(), nullable=True),
        sa.Column("current_recovery_run_uuid", sa.String(length=36), nullable=False),
        sa.Column("cleanup_outbox_event_uuid", sa.String(length=36), nullable=True),
        sa.Column("platform_audit_uuid", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("chain_generation >= 1", name="ck_redemption_code_replacements_chain_generation_positive"),
        sa.CheckConstraint("entitlements_schema_version >= 1", name="ck_redemption_code_replacements_ent_schema_positive"),
        sa.CheckConstraint("expected_source_attempt_row_version IS NULL OR expected_source_attempt_row_version >= 1", name="ck_redemption_code_replacements_source_attempt_revision_positive"),
        sa.CheckConstraint("expected_source_code_row_version >= 1", name="ck_redemption_code_replacements_source_code_revision_positive"),
        sa.CheckConstraint("fenced_provisioning_generation IS NULL OR fenced_provisioning_generation >= 1", name="ck_redemption_code_replacements_fenced_generation_positive"),
        sa.CheckConstraint("length(entitlements_digest) = 32", name="ck_redemption_code_replacements_entitlements_digest_length"),
        sa.CheckConstraint("length(request_digest) = 32", name="ck_redemption_code_replacements_request_digest_length"),
        sa.CheckConstraint("length(trim(reason_code)) >= 1", name="ck_redemption_code_replacements_reason_code_nonempty"),
        sa.CheckConstraint("service_duration_seconds >= 1", name="ck_redemption_code_replacements_service_duration_positive"),
        sa.CheckConstraint("source_code_uuid <> replacement_code_uuid", name="ck_redemption_code_replacements_source_differs_from_replacement"),
        sa.ForeignKeyConstraint(["cleanup_outbox_event_uuid"], ["control_outbox_events.id"], name="fk_code_replacement_cleanup", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["plan_revision_uuid"], ["plans.id"], name="fk_redemption_code_replacements_plan_revision_uuid_plans", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["platform_admin_uuid"], ["platform_admins.id"], name="fk_code_replacement_admin", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["platform_session_uuid"], ["platform_admin_sessions.id"], name="fk_code_replacement_session", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replacement_code_uuid"], ["redemption_codes.id"], name="fk_code_replacement_successor", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_attempt_uuid"], ["tenant_registration_attempts.id"], name="fk_code_replacement_attempt", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_code_uuid"], ["redemption_codes.id"], name="fk_code_replacement_source", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_redemption_code_replacements"),
        sa.UniqueConstraint("cleanup_outbox_event_uuid", name="uq_code_replacements_cleanup_outbox"),
        sa.UniqueConstraint("idempotency_key", name="uq_code_replacements_idempotency"),
        sa.UniqueConstraint("platform_audit_uuid", name="uq_code_replacements_platform_audit"),
        sa.UniqueConstraint("replacement_code_uuid", name="uq_code_replacements_replacement_code"),
        sa.UniqueConstraint("source_attempt_uuid", name="uq_code_replacements_source_attempt"),
        sa.UniqueConstraint("source_code_uuid", name="uq_code_replacements_source_code"),
    )

    op.create_table(
        "registration_integrity_incidents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("attempt_uuid", sa.String(length=36), nullable=False),
        sa.Column("open_attempt_uuid", sa.String(length=36), sa.Computed("CASE WHEN state IN ('open', 'recovery_cleanup_pending') THEN attempt_uuid ELSE NULL END", persisted=True), nullable=True),
        sa.Column("code_uuid", sa.String(length=36), nullable=False),
        sa.Column("user_uuid", sa.String(length=36), nullable=False),
        sa.Column("provisional_tenant_uuid", sa.String(length=36), nullable=True),
        sa.Column("provisional_database_uuid", sa.String(length=36), nullable=True),
        sa.Column("detected_attempt_status", sa.String(length=40), nullable=False),
        sa.Column("detected_replacement_uuid", sa.String(length=36), nullable=True),
        sa.Column("provisioning_generation", sa.BigInteger(), nullable=False),
        sa.Column("presence_bitmap", sa.BigInteger(), nullable=False),
        sa.Column("presence_digest", HASH, nullable=False),
        sa.Column("current_recovery_run_uuid", sa.String(length=36), nullable=False),
        sa.Column("marker_generation", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("resolution_source", sa.String(length=32), nullable=True),
        sa.Column("evidence_policy_version", sa.Integer(), nullable=False),
        sa.Column("safe_evidence_reference", sa.String(length=255), nullable=False),
        sa.Column("decision_digest", HASH, nullable=True),
        sa.Column("platform_audit_uuid", sa.String(length=36), nullable=True),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("state IN ('open', 'resolved_committed', 'resolved_absent', 'recovery_cleanup_pending', 'recovery_cleaned')", name="ck_registration_integrity_incidents_state_valid"),
        sa.CheckConstraint("decision_digest IS NULL OR length(decision_digest) = 32", name="ck_registration_integrity_incidents_decision_digest_length"),
        sa.CheckConstraint("evidence_policy_version >= 1", name="ck_registration_integrity_incidents_evidence_policy_positive"),
        sa.CheckConstraint("length(presence_digest) = 32", name="ck_registration_integrity_incidents_presence_digest_length"),
        sa.CheckConstraint("marker_generation >= 1", name="ck_registration_integrity_incidents_marker_generation_positive"),
        sa.CheckConstraint("provisioning_generation >= 1", name="ck_registration_integrity_incidents_provision_positive"),
        sa.CheckConstraint("row_version >= 1", name="ck_registration_integrity_incidents_row_version_positive"),
        sa.CheckConstraint(
            "((state IN ('open', 'recovery_cleanup_pending') AND resolved_at IS NULL) OR "
            "(state NOT IN ('open', 'recovery_cleanup_pending') AND resolved_at IS NOT NULL))",
            name="ck_registration_integrity_incidents_resolved_at_matches_state",
        ),
        sa.ForeignKeyConstraint(["attempt_uuid"], ["tenant_registration_attempts.id"], name="fk_reg_incident_attempt", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_registration_integrity_incidents"),
        sa.UniqueConstraint("open_attempt_uuid", name="uq_registration_incidents_open_attempt"),
    )

    op.create_table(
        "tenant_registration_commits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("attempt_uuid", sa.String(length=36), nullable=False),
        sa.Column("code_uuid", sa.String(length=36), nullable=False),
        sa.Column("tenant_uuid", sa.String(length=36), nullable=False),
        sa.Column("database_uuid", sa.String(length=36), nullable=False),
        sa.Column("user_uuid", sa.String(length=36), nullable=False),
        sa.Column("membership_uuid", sa.String(length=36), nullable=False),
        sa.Column("subscription_uuid", sa.String(length=36), nullable=False),
        sa.Column("subscription_event_uuid", sa.String(length=36), nullable=False),
        sa.Column("recovery_run_uuid", sa.String(length=36), nullable=False),
        sa.Column("provisioning_execution_generation_at_commit", sa.BigInteger(), nullable=False),
        sa.Column("plan_revision_uuid", sa.String(length=36), nullable=False),
        sa.Column("entitlements_schema_version", sa.Integer(), nullable=False),
        sa.Column("entitlements_digest", HASH, nullable=False),
        sa.Column("service_duration_seconds", sa.BigInteger(), nullable=False),
        sa.Column("published_tenant_name_digest", HASH, nullable=False),
        sa.Column("published_slug_digest", HASH, nullable=False),
        sa.Column("schema_generation", sa.BigInteger(), nullable=False),
        sa.Column("database_identity_digest", HASH, nullable=False),
        sa.Column("released_hold_uuid", sa.String(length=36), nullable=False),
        sa.Column("released_hold_revision_at_commit", sa.BigInteger(), nullable=False),
        sa.Column("initial_route_version", sa.BigInteger(), nullable=False),
        sa.Column("initial_credential_generation", sa.BigInteger(), nullable=False),
        sa.Column("commit_policy_version", sa.Integer(), nullable=False),
        sa.Column("entity_link_digest", HASH, nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("commit_policy_version >= 1", name="ck_tenant_registration_commits_commit_policy_version_positive"),
        sa.CheckConstraint("entitlements_schema_version >= 1", name="ck_tenant_registration_commits_ent_schema_positive"),
        sa.CheckConstraint("initial_credential_generation >= 1", name="ck_tenant_registration_commits_initial_credential_positive"),
        sa.CheckConstraint("initial_route_version >= 1", name="ck_tenant_registration_commits_initial_route_version_positive"),
        sa.CheckConstraint("length(database_identity_digest) = 32", name="ck_tenant_registration_commits_database_identity_digest_length"),
        sa.CheckConstraint("length(entitlements_digest) = 32", name="ck_tenant_registration_commits_entitlements_digest_length"),
        sa.CheckConstraint("length(entity_link_digest) = 32", name="ck_tenant_registration_commits_entity_link_digest_length"),
        sa.CheckConstraint("length(published_slug_digest) = 32", name="ck_tenant_registration_commits_slug_digest_length"),
        sa.CheckConstraint("length(published_tenant_name_digest) = 32", name="ck_tenant_registration_commits_tenant_name_digest_length"),
        sa.CheckConstraint("provisioning_execution_generation_at_commit >= 1", name="ck_tenant_registration_commits_provisioning_generation_positive"),
        sa.CheckConstraint("released_hold_revision_at_commit >= 1", name="ck_tenant_registration_commits_released_hold_revision_positive"),
        sa.CheckConstraint("schema_generation >= 1", name="ck_tenant_registration_commits_schema_generation_positive"),
        sa.CheckConstraint("service_duration_seconds >= 1", name="ck_tenant_registration_commits_service_duration_positive"),
        sa.ForeignKeyConstraint(["attempt_uuid"], ["tenant_registration_attempts.id"], name="fk_reg_commit_attempt", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["code_uuid"], ["redemption_codes.id"], name="fk_tenant_registration_commits_code_uuid_redemption_codes", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["database_uuid"], ["tenant_databases.database_uuid"], name="fk_tenant_registration_commits_database_uuid_tenant_databases", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["membership_uuid"], ["tenant_memberships.id"], name="fk_reg_commit_membership", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["plan_revision_uuid", "entitlements_schema_version", "entitlements_digest"],
            ["plans.id", "plans.entitlements_schema_version", "plans.entitlements_digest"],
            name="fk_registration_commits_plan_digest",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["subscription_event_uuid"], ["subscription_events.id"], name="fk_reg_commit_subscription_event", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subscription_uuid"], ["subscriptions.id"], name="fk_tenant_registration_commits_subscription_uuid_subscriptions", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_uuid"], ["tenants.id"], name="fk_tenant_registration_commits_tenant_uuid_tenants", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_uuid"], ["users.id"], name="fk_tenant_registration_commits_user_uuid_users", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_registration_commits"),
        sa.UniqueConstraint("attempt_uuid", name="uq_registration_commits_attempt"),
        sa.UniqueConstraint("code_uuid", name="uq_registration_commits_code"),
        sa.UniqueConstraint("database_uuid", name="uq_registration_commits_database"),
        sa.UniqueConstraint("membership_uuid", name="uq_registration_commits_membership"),
        sa.UniqueConstraint("subscription_event_uuid", name="uq_registration_commits_event"),
        sa.UniqueConstraint("subscription_uuid", name="uq_registration_commits_subscription"),
        sa.UniqueConstraint("tenant_uuid", name="uq_registration_commits_tenant"),
    )


def downgrade() -> None:
    op.drop_table("tenant_registration_commits")
    op.drop_table("registration_integrity_incidents")
    op.drop_table("redemption_code_replacements")
    op.drop_table("tenant_registration_attempts")
