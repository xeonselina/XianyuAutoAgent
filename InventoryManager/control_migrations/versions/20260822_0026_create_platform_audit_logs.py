"""Create immutable platform audit records.

Revision ID: 202608220026
Revises: 202608220025
Create Date: 2026-08-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202608220026"
down_revision = "202608220025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_audit_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("actor_type", sa.String(length=24), nullable=False),
        sa.Column("actor_platform_admin_id", sa.String(length=36), nullable=True),
        sa.Column("actor_platform_session_id", sa.String(length=36), nullable=True),
        sa.Column("os_operator_reference", sa.String(length=128), nullable=True),
        sa.Column("target_tenant_id", sa.String(length=36), nullable=True),
        sa.Column("target_resource_type", sa.String(length=64), nullable=True),
        sa.Column("target_resource_id", sa.String(length=128), nullable=True),
        sa.Column("target_platform_admin_id", sa.String(length=36), nullable=True),
        sa.Column("route_or_command_template", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("access_mode", sa.String(length=24), nullable=False),
        sa.Column("pii_revealed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("safe_reason_code", sa.String(length=64), nullable=False),
        sa.Column("authentication_factor", sa.String(length=24), nullable=True),
        sa.Column("result_count", sa.BigInteger(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("ip_summary", sa.String(length=64), nullable=True),
        sa.Column("user_agent_summary", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "actor_type IN ('platform_admin', 'os_operator', "
            "'cli_break_glass', 'system')",
            name=op.f("ck_platform_audit_logs_actor_type_valid"),
        ),
        sa.CheckConstraint(
            "access_mode IN ('authentication', 'control', 'tenant_read')",
            name=op.f("ck_platform_audit_logs_access_mode_valid"),
        ),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'rejected', 'failed', 'rate_limited')",
            name=op.f("ck_platform_audit_logs_outcome_valid"),
        ),
        sa.CheckConstraint(
            "authentication_factor IS NULL OR authentication_factor IN "
            "('totp', 'recovery_code')",
            name=op.f(
                "ck_platform_audit_logs_authentication_factor_valid"
            ),
        ),
        sa.CheckConstraint(
            "length(action) BETWEEN 1 AND 64",
            name=op.f("ck_platform_audit_logs_action_present"),
        ),
        sa.CheckConstraint(
            "length(safe_reason_code) BETWEEN 1 AND 64",
            name=op.f("ck_platform_audit_logs_safe_reason_code_present"),
        ),
        sa.CheckConstraint(
            "length(request_id) BETWEEN 1 AND 128",
            name=op.f("ck_platform_audit_logs_request_id_present"),
        ),
        sa.CheckConstraint(
            "result_count IS NULL OR result_count >= 0",
            name=op.f("ck_platform_audit_logs_result_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "((actor_type = 'platform_admin' "
            "AND actor_platform_admin_id IS NOT NULL) OR "
            "(actor_type <> 'platform_admin' "
            "AND actor_platform_admin_id IS NULL "
            "AND actor_platform_session_id IS NULL))",
            name=op.f("ck_platform_audit_logs_actor_identity_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_platform_admin_id"],
            ["platform_admins.id"],
            name="fk_platform_audit_actor_admin",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_platform_session_id"],
            ["platform_admin_sessions.id"],
            name="fk_platform_audit_actor_session",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_platform_admin_id"],
            ["platform_admins.id"],
            name="fk_platform_audit_target_admin",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_audit_logs")),
    )
    op.create_index(
        "ix_platform_audit_logs_created",
        "platform_audit_logs",
        ["created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_platform_audit_logs_target_admin_created",
        "platform_audit_logs",
        ["target_platform_admin_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("platform_audit_logs")
