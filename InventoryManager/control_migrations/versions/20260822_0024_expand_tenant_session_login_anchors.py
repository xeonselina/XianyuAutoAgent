"""Add OTP issuance and browser-session rotation anchors."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202608220024"
down_revision = "202608220023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_user_sessions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "created_from_challenge_id",
                sa.String(length=36),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "rotated_from_session_id",
                sa.String(length=36),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "replaced_by_session_id",
                sa.String(length=36),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_tenant_sessions_created_from_challenge",
            "sms_challenges",
            ["created_from_challenge_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_tenant_sessions_rotated_from_session",
            "tenant_user_sessions",
            ["rotated_from_session_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_tenant_sessions_replaced_by_session",
            "tenant_user_sessions",
            ["replaced_by_session_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_unique_constraint(
            "uq_tenant_sessions_created_from_challenge",
            ["created_from_challenge_id"],
        )
        batch_op.create_unique_constraint(
            "uq_tenant_sessions_rotated_from_session",
            ["rotated_from_session_id"],
        )
        batch_op.create_unique_constraint(
            "uq_tenant_sessions_replaced_by_session",
            ["replaced_by_session_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_user_sessions") as batch_op:
        batch_op.drop_constraint(
            "fk_tenant_sessions_replaced_by_session",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_tenant_sessions_rotated_from_session",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_tenant_sessions_created_from_challenge",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "uq_tenant_sessions_replaced_by_session",
            type_="unique",
        )
        batch_op.drop_constraint(
            "uq_tenant_sessions_rotated_from_session",
            type_="unique",
        )
        batch_op.drop_constraint(
            "uq_tenant_sessions_created_from_challenge",
            type_="unique",
        )
        batch_op.drop_column("replaced_by_session_id")
        batch_op.drop_column("rotated_from_session_id")
        batch_op.drop_column("created_from_challenge_id")
