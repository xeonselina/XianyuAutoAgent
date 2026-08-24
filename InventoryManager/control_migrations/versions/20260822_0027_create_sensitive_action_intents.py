"""Create tenant-sensitive action intent persistence.

Revision ID: 202608220027
Revises: 202608220026
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "202608220027"
down_revision = "202608220026"
branch_labels = None
depends_on = None


MAC_SHA256_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")


def upgrade() -> None:
    op.create_table(
        "tenant_sensitive_action_intents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=False),
        sa.Column("actor_session_id", sa.String(length=36), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("action_subtype", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_uuid", sa.String(length=36), nullable=False),
        sa.Column("expected_target_revision", sa.String(length=128), nullable=False),
        sa.Column("canonicalization_version", sa.Integer(), nullable=False),
        sa.Column("context_mac_version", sa.Integer(), nullable=False),
        sa.Column("root_key_version", sa.Integer(), nullable=False),
        sa.Column(
            "request_context_mac_sha256",
            MAC_SHA256_TYPE,
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default=sa.text("'pending_verification'"),
            nullable=False,
        ),
        sa.Column("safe_result_code", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=80), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executing_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "purpose IN ("
            "'integration_credential_change', 'sf_account_bind', "
            "'sf_account_unbind', 'sf_account_rebind', 'admin_invitation', "
            "'grant_admin', 'revoke_admin', 'tenant_delete', "
            "'tenant_delete_cancel', 'phone_change_old', 'phone_change_new')",
            name=op.f("ck_tenant_sensitive_action_intents_purpose_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('pending_verification', 'authorized', 'executing', "
            "'succeeded', 'failed', 'expired', 'cancelled')",
            name=op.f("ck_tenant_sensitive_action_intents_status_valid"),
        ),
        sa.CheckConstraint(
            "length(action_subtype) BETWEEN 1 AND 64",
            name=op.f("ck_tenant_sensitive_action_intents_action_subtype_present"),
        ),
        sa.CheckConstraint(
            "length(target_type) BETWEEN 1 AND 64",
            name=op.f("ck_tenant_sensitive_action_intents_target_type_present"),
        ),
        sa.CheckConstraint(
            "length(expected_target_revision) BETWEEN 1 AND 128",
            name=op.f(
                "ck_tenant_sensitive_action_intents_"
                "expected_target_revision_present"
            ),
        ),
        sa.CheckConstraint(
            "canonicalization_version >= 1",
            name=op.f(
                "ck_tenant_sensitive_action_intents_"
                "canonicalization_version_positive"
            ),
        ),
        sa.CheckConstraint(
            "context_mac_version >= 1",
            name=op.f(
                "ck_tenant_sensitive_action_intents_"
                "context_mac_version_positive"
            ),
        ),
        sa.CheckConstraint(
            "root_key_version >= 1",
            name=op.f("ck_tenant_sensitive_action_intents_root_key_version_positive"),
        ),
        sa.CheckConstraint(
            "length(request_context_mac_sha256) = 32",
            name=op.f(
                "ck_tenant_sensitive_action_intents_"
                "request_context_mac_sha256_length"
            ),
        ),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 128",
            name=op.f("ck_tenant_sensitive_action_intents_idempotency_key_present"),
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name=op.f("ck_tenant_sensitive_action_intents_row_version_positive"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_tenant_sensitive_action_intents_expiry_after_creation"),
        ),
        sa.CheckConstraint(
            "((status IN ('authorized', 'executing', 'succeeded', 'failed') "
            "AND authorized_at IS NOT NULL) OR "
            "(status IN ('pending_verification', 'expired', 'cancelled'))) ",
            name=op.f(
                "ck_tenant_sensitive_action_intents_"
                "authorization_timestamp_matches_status"
            ),
        ),
        sa.CheckConstraint(
            "((status = 'executing' AND executing_at IS NOT NULL) OR "
            "status <> 'executing')",
            name=op.f(
                "ck_tenant_sensitive_action_intents_"
                "executing_timestamp_matches_status"
            ),
        ),
        sa.CheckConstraint(
            "((status IN ('succeeded', 'failed', 'expired', 'cancelled') "
            "AND completed_at IS NOT NULL) OR "
            "(status NOT IN ('succeeded', 'failed', 'expired', 'cancelled') "
            "AND completed_at IS NULL))",
            name=op.f(
                "ck_tenant_sensitive_action_intents_"
                "completion_timestamp_matches_status"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tenant_sensitive_action_intents_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_tenant_sensitive_action_intents_actor_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_session_id"],
            ["tenant_user_sessions.id"],
            name=op.f(
                "fk_tenant_sensitive_action_intents_actor_session_id_"
                "tenant_user_sessions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_sensitive_action_intents")),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_sensitive_action_intents_tenant_idempotency",
        ),
    )
    op.create_index(
        "ix_sensitive_action_intents_tenant_status_expiry",
        "tenant_sensitive_action_intents",
        ["tenant_id", "status", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_sensitive_action_intents_actor_created",
        "tenant_sensitive_action_intents",
        ["actor_user_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "tenant_sensitive_action_intent_challenges",
        sa.Column("intent_id", sa.String(length=36), nullable=False),
        sa.Column("challenge_role", sa.String(length=16), nullable=False),
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "challenge_role IN ('primary', 'old_phone', 'new_phone')",
            name=op.f(
                "ck_tenant_sensitive_action_intent_challenges_"
                "challenge_role_valid"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["intent_id"],
            ["tenant_sensitive_action_intents.id"],
            name=op.f(
                "fk_tenant_sensitive_action_intent_challenges_intent_id_"
                "tenant_sensitive_action_intents"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["challenge_id"],
            ["sms_challenges.id"],
            name=op.f(
                "fk_tenant_sensitive_action_intent_challenges_challenge_id_"
                "sms_challenges"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "intent_id",
            "challenge_role",
            name=op.f("pk_tenant_sensitive_action_intent_challenges"),
        ),
        sa.UniqueConstraint(
            "challenge_id", name="uq_sensitive_intent_challenges_challenge"
        ),
    )


def downgrade() -> None:
    op.drop_table("tenant_sensitive_action_intent_challenges")
    op.drop_table("tenant_sensitive_action_intents")
