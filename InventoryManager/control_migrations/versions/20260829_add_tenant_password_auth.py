"""Add password authentication state to tenant members."""

from alembic import op
import sqlalchemy as sa


revision = "20260829_tenant_password_auth"
down_revision = "20260824_control_baseline"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tenant_members",
        sa.Column("password_hash", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "tenant_members",
        sa.Column(
            "failed_password_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "tenant_members",
        sa.Column("password_locked_until", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "tenant_members",
        sa.Column("password_changed_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_column("tenant_members", "password_changed_at")
    op.drop_column("tenant_members", "password_locked_until")
    op.drop_column("tenant_members", "failed_password_attempts")
    op.drop_column("tenant_members", "password_hash")
