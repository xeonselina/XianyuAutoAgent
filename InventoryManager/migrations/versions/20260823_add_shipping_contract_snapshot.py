"""add scheduled dispatch and cargo shipment snapshots

Revision ID: 20260823_shipping_contract
Revises: 20260823_shipping_intent
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260823_shipping_contract"
down_revision = "20260823_shipping_intent"
branch_labels = None
depends_on = None


_LEGACY_CARGO = '{"items":[{"count":1,"name":"租赁设备"}]}'


def upgrade():
    with op.batch_alter_table("outbound_shipments") as batch_op:
        batch_op.add_column(
            sa.Column("cargo_snapshot", sa.JSON(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("scheduled_dispatch_at", sa.DateTime(), nullable=True)
        )

    op.execute(
        sa.text(
            "UPDATE outbound_shipments "
            "SET cargo_snapshot = :cargo, "
            "scheduled_dispatch_at = COALESCE("
            "(SELECT rentals.scheduled_ship_time FROM rentals "
            "WHERE rentals.id = outbound_shipments.rental_id), "
            "prepared_at, created_at) "
            "WHERE cargo_snapshot IS NULL OR scheduled_dispatch_at IS NULL"
        ).bindparams(cargo=_LEGACY_CARGO)
    )

    with op.batch_alter_table("outbound_shipments") as batch_op:
        batch_op.alter_column(
            "cargo_snapshot",
            existing_type=sa.JSON(),
            nullable=False,
        )
        batch_op.alter_column(
            "scheduled_dispatch_at",
            existing_type=sa.DateTime(),
            nullable=False,
        )


def downgrade():
    with op.batch_alter_table("outbound_shipments") as batch_op:
        batch_op.drop_column("scheduled_dispatch_at")
        batch_op.drop_column("cargo_snapshot")
