"""add rental damage notes

Revision ID: 20260807_damage_notes
Revises: 20260805_relay_cases
Create Date: 2026-08-07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260807_damage_notes"
down_revision = "20260805_relay_cases"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("rentals", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "damage_note",
                sa.Text(),
                nullable=True,
                comment="客户反馈的当前设备损坏备注",
            )
        )

    with op.batch_alter_table("inspection_check_item", schema=None) as batch_op:
        batch_op.alter_column(
            "item_name",
            existing_type=sa.String(length=100),
            type_=sa.String(length=1020),
            existing_nullable=False,
            existing_comment="检查项名称",
        )


def downgrade():
    with op.batch_alter_table("inspection_check_item", schema=None) as batch_op:
        batch_op.alter_column(
            "item_name",
            existing_type=sa.String(length=1020),
            type_=sa.String(length=100),
            existing_nullable=False,
            existing_comment="检查项名称",
        )

    with op.batch_alter_table("rentals", schema=None) as batch_op:
        batch_op.drop_column("damage_note")
