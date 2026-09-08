"""Allow intentional refunded/closed rental alerts to be ignored."""

from alembic import op
import sqlalchemy as sa


revision = "20260908_xianyu_alert_ignore"
down_revision = "20260907_xianyu_rental_alerts"
branch_labels = None
depends_on = None


def upgrade():
    existing = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("xianyu_rental_alerts")
    }
    if "ignored_at" not in existing:
        op.add_column(
            "xianyu_rental_alerts",
            sa.Column("ignored_at", sa.DateTime(), nullable=True),
        )
    if "ignored_reason" not in existing:
        op.add_column(
            "xianyu_rental_alerts",
            sa.Column("ignored_reason", sa.String(500), nullable=True),
        )


def downgrade():
    existing = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("xianyu_rental_alerts")
    }
    if "ignored_reason" in existing:
        op.drop_column("xianyu_rental_alerts", "ignored_reason")
    if "ignored_at" in existing:
        op.drop_column("xianyu_rental_alerts", "ignored_at")
