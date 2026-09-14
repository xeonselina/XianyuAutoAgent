"""Cache refunded/closed Xianyu orders that still have active rentals."""

from alembic import op
import sqlalchemy as sa


revision = "20260907_xianyu_rental_alerts"
down_revision = "20260830_rental_packages"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "xianyu_rental_alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("xianyu_shop_id", sa.Integer(), nullable=False),
        sa.Column("order_no", sa.String(50), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status_text", sa.String(100), nullable=False),
        sa.Column("order_status", sa.Integer(), nullable=False),
        sa.Column("refund_status", sa.Integer(), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["xianyu_shop_id"], ["xianyu_shops.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("xianyu_shop_id", "order_no", name="uq_xianyu_rental_alert_shop_order"),
    )


def downgrade():
    op.drop_table("xianyu_rental_alerts")
