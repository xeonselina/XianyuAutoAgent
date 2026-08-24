"""add structurally read-only legacy-unattributed history

Revision ID: 20260824_legacy_history
Revises: 20260823_shipping_contract
Create Date: 2026-08-24
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_legacy_history"
down_revision = "20260823_shipping_contract"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "legacy_unattributed_shipments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_kind", sa.String(length=32), nullable=False),
        sa.Column("source_rental_id", sa.Integer(), nullable=False),
        sa.Column("rental_id", sa.Integer(), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=32), nullable=False),
        sa.Column("ship_out_tracking_no", sa.String(length=64), nullable=True),
        sa.Column("ship_in_tracking_no", sa.String(length=64), nullable=True),
        sa.Column("shipped_at", sa.DateTime(), nullable=True),
        sa.Column("returned_at", sa.DateTime(), nullable=True),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "migration_manifest_digest",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "snapshot_kind = 'legacy_unattributed'",
            name="ck_legacy_unattributed_shipments_kind",
        ),
        sa.CheckConstraint(
            "lifecycle_status IN ('not_shipped', 'scheduled_for_shipping', "
            "'shipped', 'returned', 'completed', 'cancelled')",
            name="ck_legacy_unattributed_shipments_status",
        ),
        sa.ForeignKeyConstraint(
            ["rental_id"],
            ["rentals.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_rental_id",
            name="uq_legacy_unattributed_shipments_source_rental",
        ),
    )
    op.create_index(
        "ix_legacy_unattributed_shipments_created",
        "legacy_unattributed_shipments",
        ["created_at", "id"],
        unique=False,
    )

    op.create_table(
        "legacy_unattributed_prints",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_kind", sa.String(length=32), nullable=False),
        sa.Column("source_audit_id", sa.Integer(), nullable=False),
        sa.Column("rental_id", sa.Integer(), nullable=True),
        sa.Column("shipment_snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=True),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "migration_manifest_digest",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "snapshot_kind = 'legacy_unattributed'",
            name="ck_legacy_unattributed_prints_kind",
        ),
        sa.ForeignKeyConstraint(
            ["rental_id"],
            ["rentals.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_snapshot_id"],
            ["legacy_unattributed_shipments.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_audit_id",
            name="uq_legacy_unattributed_prints_source_audit",
        ),
    )
    op.create_index(
        "ix_legacy_unattributed_prints_occurred",
        "legacy_unattributed_prints",
        ["occurred_at", "id"],
        unique=False,
    )


def downgrade():
    op.drop_table("legacy_unattributed_prints")
    op.drop_table("legacy_unattributed_shipments")
