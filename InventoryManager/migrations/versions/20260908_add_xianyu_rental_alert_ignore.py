"""Allow intentional refunded/closed rental alerts to be ignored."""

from alembic import op
import sqlalchemy as sa


revision = "20260908_xianyu_rental_alert_ignore"
down_revision = "20260907_xianyu_rental_alerts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "xianyu_rental_alerts",
        sa.Column("ignored_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "xianyu_rental_alerts",
        sa.Column("ignored_reason", sa.String(500), nullable=True),
    )


def downgrade():
    op.drop_column("xianyu_rental_alerts", "ignored_reason")
    op.drop_column("xianyu_rental_alerts", "ignored_at")
