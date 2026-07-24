"""add xianyu missing order alerts

Revision ID: 20260724_xianyu_alerts
Revises: 20260711_relay_bindings
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa


revision = "20260724_xianyu_alerts"
down_revision = "20260711_relay_bindings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "xianyu_order_alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_no", sa.String(length=50), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("pay_amount", sa.BigInteger(), nullable=False),
        sa.Column("buyer_nick", sa.String(length=100), nullable=True),
        sa.Column("receiver_name", sa.String(length=100), nullable=True),
        sa.Column("receiver_mobile", sa.String(length=20), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("goods_title", sa.String(length=500), nullable=True),
        sa.Column("goods_sku_text", sa.String(length=500), nullable=True),
        sa.Column("order_time", sa.DateTime(), nullable=True),
        sa.Column("first_detected_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("ignored_reason", sa.String(length=500), nullable=True),
        sa.Column("ignored_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'ignored')",
            name="ck_xianyu_order_alert_state",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_no"),
    )
    op.create_index(
        "ix_xianyu_order_alerts_order_no",
        "xianyu_order_alerts",
        ["order_no"],
        unique=True,
    )
    op.create_index(
        "ix_xianyu_order_alerts_state",
        "xianyu_order_alerts",
        ["state"],
        unique=False,
    )

    op.create_table(
        "xianyu_order_sync_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("xianyu_order_sync_state")
    op.drop_index(
        "ix_xianyu_order_alerts_state",
        table_name="xianyu_order_alerts",
    )
    op.drop_index(
        "ix_xianyu_order_alerts_order_no",
        table_name="xianyu_order_alerts",
    )
    op.drop_table("xianyu_order_alerts")
