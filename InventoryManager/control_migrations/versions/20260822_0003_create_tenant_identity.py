"""Create tenant users, memberships, and server-side sessions.

Revision ID: 202608220003
Revises: 202608220002
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "202608220003"
down_revision = "202608220002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "phone_region_iso2",
            sa.String(length=2),
            server_default=sa.text("'CN'"),
            nullable=False,
        ),
        sa.Column("phone_e164", sa.String(length=16), nullable=False),
        sa.Column("phone_normalization_version", sa.Integer(), nullable=False),
        sa.Column("phone_metadata_version", sa.String(length=64), nullable=False),
        sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'unverified'"),
            nullable=False,
        ),
        sa.Column(
            "auth_version",
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
            "phone_region_iso2 = 'CN'", name="ck_users_phone_region_cn"
        ),
        sa.CheckConstraint(
            "phone_e164 LIKE '+86%' AND length(phone_e164) = 14",
            name="ck_users_phone_e164_canonical_shape",
        ),
        sa.CheckConstraint(
            "phone_normalization_version >= 1",
            name="ck_users_phone_normalization_version_positive",
        ),
        sa.CheckConstraint(
            "auth_version >= 1", name="ck_users_auth_version_positive"
        ),
        sa.CheckConstraint(
            "status IN ('unverified', 'active', 'disabled')",
            name="ck_users_status_valid",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("phone_e164", name="uq_users_phone_e164"),
    )

    op.create_table(
        "tenant_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role_key", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_uuid", sa.String(length=36), nullable=True),
        sa.Column("registration_commit_uuid", sa.String(length=36), nullable=True),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "claimed_user_id",
            sa.String(length=36),
            sa.Computed(
                "CASE WHEN status = 'released' THEN NULL ELSE user_id END",
                persisted=True,
            ),
            nullable=True,
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
            "role_key IN ('admin', 'operator')",
            name="ck_tenant_memberships_role_key_valid",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled', 'released')",
            name="ck_tenant_memberships_status_valid",
        ),
        sa.CheckConstraint(
            "source_type IN ('migration', 'invitation', 'registration')",
            name="ck_tenant_memberships_source_type_valid",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_tenant_memberships_row_version_positive",
        ),
        sa.CheckConstraint(
            "((status = 'released' AND released_at IS NOT NULL) OR "
            "(status <> 'released' AND released_at IS NULL))",
            name="ck_tenant_memberships_released_at_matches_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_memberships_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_tenant_memberships_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_memberships"),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            name="uq_tenant_memberships_tenant_user",
        ),
        sa.UniqueConstraint(
            "claimed_user_id", name="uq_tenant_memberships_claimed_user"
        ),
    )

    op.create_table(
        "tenant_user_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "token_digest_sha256",
            sa.LargeBinary(length=32).with_variant(mysql.BINARY(32), "mysql"),
            nullable=False,
        ),
        sa.Column(
            "csrf_digest_sha256",
            sa.LargeBinary(length=32).with_variant(mysql.BINARY(32), "mysql"),
            nullable=False,
        ),
        sa.Column("auth_version_at_issue", sa.BigInteger(), nullable=False),
        sa.Column("tenant_access_version_at_issue", sa.BigInteger(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column(
            "csrf_generation",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("idle_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason_code", sa.String(length=64), nullable=True),
        sa.Column("revoked_by_session_id", sa.String(length=36), nullable=True),
        sa.Column("device_name", sa.String(length=100), nullable=True),
        sa.Column("user_agent_summary", sa.String(length=255), nullable=True),
        sa.Column("first_ip_summary", sa.String(length=64), nullable=True),
        sa.Column("last_ip_summary", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "length(token_digest_sha256) = 32",
            name="ck_tenant_user_sessions_token_digest_sha256_length",
        ),
        sa.CheckConstraint(
            "length(csrf_digest_sha256) = 32",
            name="ck_tenant_user_sessions_csrf_digest_sha256_length",
        ),
        sa.CheckConstraint(
            "auth_version_at_issue >= 1",
            name="ck_tenant_user_sessions_auth_version_at_issue_positive",
        ),
        sa.CheckConstraint(
            "tenant_access_version_at_issue >= 1",
            name="ck_tenant_user_sessions_tenant_access_version_at_issue_positive",
        ),
        sa.CheckConstraint(
            "policy_version >= 1",
            name="ck_tenant_user_sessions_policy_version_positive",
        ),
        sa.CheckConstraint(
            "csrf_generation >= 1",
            name="ck_tenant_user_sessions_csrf_generation_positive",
        ),
        sa.CheckConstraint(
            "idle_timeout_seconds >= 1",
            name="ck_tenant_user_sessions_idle_timeout_seconds_positive",
        ),
        sa.CheckConstraint(
            "idle_expires_at <= absolute_expires_at",
            name="ck_tenant_user_sessions_idle_before_absolute_expiry",
        ),
        sa.CheckConstraint(
            "((revoked_at IS NULL AND revoked_reason_code IS NULL "
            "AND revoked_by_session_id IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_reason_code IS NOT NULL))",
            name="ck_tenant_user_sessions_revocation_fields_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_session_id"],
            ["tenant_user_sessions.id"],
            name="fk_tenant_sessions_revoked_by_session",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_tenant_user_sessions_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_user_sessions"),
        sa.UniqueConstraint(
            "csrf_digest_sha256",
            name="uq_tenant_user_sessions_csrf_digest_sha256",
        ),
        sa.UniqueConstraint(
            "token_digest_sha256",
            name="uq_tenant_user_sessions_token_digest_sha256",
        ),
    )
    op.create_index(
        "ix_tenant_user_sessions_user_active_expiry",
        "tenant_user_sessions",
        ["user_id", "revoked_at", "absolute_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("tenant_user_sessions")
    op.drop_table("tenant_memberships")
    op.drop_table("users")
