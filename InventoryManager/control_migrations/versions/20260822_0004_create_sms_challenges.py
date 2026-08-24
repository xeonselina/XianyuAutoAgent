"""Create purpose-bound SMS challenges and rate-limit lock subjects.

Revision ID: 202608220004
Revises: 202608220003
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "202608220004"
down_revision = "202608220003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sms_rate_limit_subjects",
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject_bucket", sa.String(length=128), nullable=False),
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
            "subject_type IN ('phone', 'source')",
            name="ck_sms_rate_limit_subjects_subject_type_valid",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_sms_rate_limit_subjects_row_version_positive",
        ),
        sa.PrimaryKeyConstraint(
            "subject_type",
            "subject_bucket",
            name="pk_sms_rate_limit_subjects",
        ),
    )

    digest_type = sa.LargeBinary(length=32).with_variant(mysql.BINARY(32), "mysql")
    op.create_table(
        "sms_challenges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("canonical_phone_e164", sa.String(length=16), nullable=False),
        sa.Column("phone_normalization_version", sa.Integer(), nullable=False),
        sa.Column("phone_metadata_version", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("actor_session_id", sa.String(length=36), nullable=True),
        sa.Column("action_payload_digest_sha256", digest_type, nullable=False),
        sa.Column("authoritative_revision", sa.String(length=128), nullable=False),
        sa.Column("code_hmac_sha256", digest_type, nullable=False),
        sa.Column("root_key_version", sa.Integer(), nullable=False),
        sa.Column("hmac_protocol_version", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("max_wrong_attempts", sa.Integer(), nullable=False),
        sa.Column("trusted_source_bucket", sa.String(length=128), nullable=False),
        sa.Column(
            "delivery_state",
            sa.String(length=16),
            server_default=sa.text("'committed'"),
            nullable=False,
        ),
        sa.Column(
            "verification_state",
            sa.String(length=24),
            server_default=sa.text("'pending_delivery'"),
            nullable=False,
        ),
        sa.Column(
            "wrong_attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivery_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_reason_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "purpose IN ("
            "'register', 'login', 'accept_invitation', "
            "'integration_credential_change', 'sf_account_bind', "
            "'sf_account_unbind', 'sf_account_rebind', 'admin_invitation', "
            "'grant_admin', 'revoke_admin', 'tenant_delete', "
            "'tenant_delete_cancel', 'phone_change_old', 'phone_change_new')",
            name="ck_sms_challenges_purpose_valid",
        ),
        sa.CheckConstraint(
            "canonical_phone_e164 LIKE '+86%' "
            "AND length(canonical_phone_e164) = 14",
            name="ck_sms_challenges_canonical_phone_shape",
        ),
        sa.CheckConstraint(
            "phone_normalization_version >= 1",
            name="ck_sms_challenges_phone_normalization_version_positive",
        ),
        sa.CheckConstraint(
            "length(action_payload_digest_sha256) = 32",
            name="ck_sms_challenges_action_payload_digest_sha256_length",
        ),
        sa.CheckConstraint(
            "length(code_hmac_sha256) = 32",
            name="ck_sms_challenges_code_hmac_sha256_length",
        ),
        sa.CheckConstraint(
            "root_key_version >= 1",
            name="ck_sms_challenges_root_key_version_positive",
        ),
        sa.CheckConstraint(
            "hmac_protocol_version >= 1",
            name="ck_sms_challenges_hmac_protocol_version_positive",
        ),
        sa.CheckConstraint(
            "policy_version >= 1",
            name="ck_sms_challenges_policy_version_positive",
        ),
        sa.CheckConstraint(
            "length(authoritative_revision) BETWEEN 1 AND 128",
            name="ck_sms_challenges_authoritative_revision_present",
        ),
        sa.CheckConstraint(
            "max_wrong_attempts >= 1 AND max_wrong_attempts <= 5",
            name="ck_sms_challenges_max_wrong_attempts_bounded",
        ),
        sa.CheckConstraint(
            "delivery_state IN ('committed', 'sent', 'send_unknown', 'failed')",
            name="ck_sms_challenges_delivery_state_valid",
        ),
        sa.CheckConstraint(
            "verification_state IN "
            "('pending_delivery', 'active', 'consumed', 'locked', 'invalidated')",
            name="ck_sms_challenges_verification_state_valid",
        ),
        sa.CheckConstraint(
            "wrong_attempt_count >= 0 AND wrong_attempt_count <= 5",
            name="ck_sms_challenges_wrong_attempt_count_bounded",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_sms_challenges_row_version_positive",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_sms_challenges_expiry_after_creation",
        ),
        sa.CheckConstraint(
            "((delivery_state = 'committed' AND delivery_recorded_at IS NULL) OR "
            "(delivery_state <> 'committed' AND delivery_recorded_at IS NOT NULL))",
            name="ck_sms_challenges_delivery_recorded_at_matches_state",
        ),
        sa.CheckConstraint(
            "((verification_state = 'pending_delivery' "
            "AND delivery_state = 'committed') OR "
            "verification_state <> 'pending_delivery')",
            name="ck_sms_challenges_pending_delivery_matches_delivery_state",
        ),
        sa.CheckConstraint(
            "(verification_state NOT IN ('active', 'consumed', 'locked') OR "
            "delivery_state IN ('sent', 'send_unknown'))",
            name="ck_sms_challenges_verifiable_state_matches_delivery",
        ),
        sa.CheckConstraint(
            "((verification_state = 'locked' "
            "AND wrong_attempt_count = max_wrong_attempts) OR "
            "verification_state <> 'locked')",
            name="ck_sms_challenges_locked_at_attempt_limit",
        ),
        sa.CheckConstraint(
            "((verification_state = 'consumed' AND consumed_at IS NOT NULL) OR "
            "(verification_state <> 'consumed' AND consumed_at IS NULL))",
            name="ck_sms_challenges_consumed_at_matches_state",
        ),
        sa.CheckConstraint(
            "((verification_state = 'locked' AND locked_at IS NOT NULL) OR "
            "(verification_state <> 'locked' AND locked_at IS NULL))",
            name="ck_sms_challenges_locked_at_matches_state",
        ),
        sa.CheckConstraint(
            "((verification_state = 'invalidated' "
            "AND invalidated_at IS NOT NULL "
            "AND invalidated_reason_code IS NOT NULL) OR "
            "(verification_state <> 'invalidated' "
            "AND invalidated_at IS NULL "
            "AND invalidated_reason_code IS NULL))",
            name="ck_sms_challenges_invalidation_fields_match_state",
        ),
        sa.ForeignKeyConstraint(
            ["actor_session_id"],
            ["tenant_user_sessions.id"],
            name="fk_sms_challenges_actor_session_id_tenant_user_sessions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_sms_challenges_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_sms_challenges_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sms_challenges"),
    )
    op.create_index(
        "ix_sms_challenges_phone_purpose_current",
        "sms_challenges",
        [
            "canonical_phone_e164",
            "purpose",
            "verification_state",
            "created_at",
        ],
        unique=False,
    )
    op.create_index(
        "ix_sms_challenges_phone_rate_window",
        "sms_challenges",
        ["canonical_phone_e164", "delivery_state", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_sms_challenges_source_rate_window",
        "sms_challenges",
        ["trusted_source_bucket", "delivery_state", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("sms_challenges")
    op.drop_table("sms_rate_limit_subjects")
