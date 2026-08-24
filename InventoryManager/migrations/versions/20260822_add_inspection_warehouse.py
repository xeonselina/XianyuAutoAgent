"""add inspection warehouse and tenant actor

Revision ID: 20260822_inspection_warehouse
Revises: 20260822_rental_logistics
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_inspection_warehouse"
down_revision = "20260822_rental_logistics"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("inspection_record", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "inspector_user_uuid",
                sa.String(length=36),
                nullable=True,
                comment="SaaS 租户用户 UUID",
            )
        )
        batch_op.add_column(
            sa.Column(
                "warehouse_id",
                sa.Integer(),
                nullable=True,
                comment="首次验货确认的实际入库仓库",
            )
        )
        batch_op.create_foreign_key(
            "fk_inspection_record_warehouse_id_warehouses",
            "warehouses",
            ["warehouse_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "ix_inspection_record_warehouse_id",
            ["warehouse_id"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("inspection_record", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_inspection_record_warehouse_id_warehouses",
            type_="foreignkey",
        )
        batch_op.drop_index("ix_inspection_record_warehouse_id")
        batch_op.drop_column("warehouse_id")
        batch_op.drop_column("inspector_user_uuid")
