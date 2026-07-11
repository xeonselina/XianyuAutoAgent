"""add rental relay bindings

Revision ID: 20260711_relay_bindings
Revises: 20260622_lens_combo
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa


revision = "20260711_relay_bindings"
down_revision = "20260622_lens_combo"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rental_relay_bindings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("predecessor_rental_id", sa.Integer(), nullable=False),
        sa.Column("successor_rental_id", sa.Integer(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "predecessor_rental_id <> successor_rental_id",
            name="ck_relay_distinct",
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_rental_id"], ["rentals.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["successor_rental_id"], ["rentals.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "predecessor_rental_id", name="uq_relay_predecessor"
        ),
        sa.UniqueConstraint(
            "successor_rental_id", name="uq_relay_successor"
        ),
    )


def downgrade():
    op.drop_table("rental_relay_bindings")
