"""add rental relay management cases

Revision ID: 20260805_relay_cases
Revises: 20260729_device_lifecycle_only
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa


revision = "20260805_relay_cases"
down_revision = "20260729_device_lifecycle_only"
branch_labels = None
depends_on = None


def upgrade():
    relay_status = sa.Enum(
        "pending",
        "notified",
        "agreed",
        "shipped",
        "completed",
        name="relay_case_status",
    )
    op.create_table(
        "rental_relay_cases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("predecessor_rental_id", sa.Integer(), nullable=False),
        sa.Column("successor_rental_id", sa.Integer(), nullable=False),
        sa.Column("status", relay_status, nullable=False),
        sa.Column("sf_tracking_number", sa.String(length=50), nullable=True),
        sa.Column("sf_tracking_status", sa.String(length=50), nullable=True),
        sa.Column("sf_tracking_summary", sa.String(length=500), nullable=True),
        sa.Column("sf_last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.Column("agreed_at", sa.DateTime(), nullable=True),
        sa.Column("shipped_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "predecessor_rental_id <> successor_rental_id",
            name="ck_relay_case_distinct",
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_rental_id"], ["rentals.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["successor_rental_id"], ["rentals.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "predecessor_rental_id",
            "successor_rental_id",
            name="uq_relay_case_pair",
        ),
    )
    op.create_index(
        "ix_relay_case_status", "rental_relay_cases", ["status"]
    )
    op.create_index(
        "ix_rental_relay_cases_predecessor_rental_id",
        "rental_relay_cases",
        ["predecessor_rental_id"],
    )
    op.create_index(
        "ix_rental_relay_cases_successor_rental_id",
        "rental_relay_cases",
        ["successor_rental_id"],
    )

    op.execute(sa.text("""
        INSERT INTO rental_relay_cases (
            predecessor_rental_id,
            successor_rental_id,
            status,
            agreed_at,
            created_at,
            updated_at
        )
        SELECT
            predecessor_rental_id,
            successor_rental_id,
            'agreed',
            confirmed_at,
            created_at,
            updated_at
        FROM rental_relay_bindings
    """))


def downgrade():
    op.drop_index(
        "ix_rental_relay_cases_successor_rental_id",
        table_name="rental_relay_cases",
    )
    op.drop_index(
        "ix_rental_relay_cases_predecessor_rental_id",
        table_name="rental_relay_cases",
    )
    op.drop_index("ix_relay_case_status", table_name="rental_relay_cases")
    op.drop_table("rental_relay_cases")

