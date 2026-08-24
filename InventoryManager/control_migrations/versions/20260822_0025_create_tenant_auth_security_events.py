"""Create immutable tenant authentication security events."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202608220025"
down_revision = "202608220024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_auth_security_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("actor_session_id", sa.String(length=36), nullable=True),
        sa.Column("target_session_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_type IN ("
            "'login_session_created', 'login_session_rotated', "
            "'logout_current', 'revoke_target', 'revoke_all', "
            "'session_expired', 'security_invalidated')",
            name=op.f(
                "ck_tenant_auth_security_events_event_type_valid"
            ),
        ),
        sa.CheckConstraint(
            "length(reason_code) BETWEEN 1 AND 64",
            name=op.f(
                "ck_tenant_auth_security_events_reason_code_present"
            ),
        ),
        sa.CheckConstraint(
            "length(request_id) BETWEEN 1 AND 80",
            name=op.f(
                "ck_tenant_auth_security_events_request_id_present"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_auth_security_events_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_tenant_auth_security_events_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_session_id"],
            ["tenant_user_sessions.id"],
            name=op.f(
                "fk_tenant_auth_security_events_actor_session_id_"
                "tenant_user_sessions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_session_id"],
            ["tenant_user_sessions.id"],
            name=op.f(
                "fk_tenant_auth_security_events_target_session_id_"
                "tenant_user_sessions"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_tenant_auth_security_events")
        ),
    )
    op.create_index(
        "ix_tenant_auth_security_events_user_created",
        "tenant_auth_security_events",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("tenant_auth_security_events")
