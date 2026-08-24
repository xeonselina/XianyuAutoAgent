"""add logical accessory inventory facts

Revision ID: 20260822_accessories
Revises: 20260822_warehouses
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_accessories"
down_revision = "20260822_warehouses"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "accessory_types",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("tracking_mode", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "tracking_mode IN ('device_bound', 'logical_unit')",
            name="ck_accessory_types_tracking_mode_valid",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_accessory_types_name"),
    )

    op.create_table(
        "device_accessory_configs",
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("accessory_type_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["accessory_type_id"],
            ["accessory_types.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("device_id", "accessory_type_id"),
    )

    op.create_table(
        "accessory_units",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("accessory_type_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("current_holder_rental_id", sa.Integer(), nullable=True),
        sa.Column("condition_status", sa.String(length=32), nullable=False),
        sa.Column("legacy_source_type", sa.String(length=64), nullable=True),
        sa.Column("legacy_source_id", sa.String(length=128), nullable=True),
        sa.Column("row_version", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "condition_status IN "
            "('active', 'maintenance', 'lost', 'retired')",
            name="ck_accessory_units_condition_valid",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_accessory_units_row_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["accessory_type_id"],
            ["accessory_types.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["current_holder_rental_id"],
            ["rentals.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "accessory_type_id",
            name="uq_accessory_units_id_type",
        ),
        sa.UniqueConstraint(
            "legacy_source_type",
            "legacy_source_id",
            name="uq_accessory_units_legacy_source",
        ),
    )
    op.create_index(
        "ix_accessory_units_availability",
        "accessory_units",
        [
            "accessory_type_id",
            "warehouse_id",
            "condition_status",
            "current_holder_rental_id",
        ],
        unique=False,
    )

    op.create_table(
        "rental_accessory_requests",
        sa.Column("rental_id", sa.Integer(), nullable=False),
        sa.Column("accessory_type_id", sa.Integer(), nullable=False),
        sa.Column("name_snapshot", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["accessory_type_id"],
            ["accessory_types.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rental_id"],
            ["rentals.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("rental_id", "accessory_type_id"),
    )
    op.create_index(
        "ix_rental_accessory_requests_type_rental",
        "rental_accessory_requests",
        ["accessory_type_id", "rental_id"],
        unique=False,
    )

    op.create_table(
        "rental_accessory_unit_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("rental_id", sa.Integer(), nullable=False),
        sa.Column("accessory_type_id", sa.Integer(), nullable=False),
        sa.Column("accessory_unit_id", sa.String(length=36), nullable=False),
        sa.Column("reservation_start_at", sa.DateTime(), nullable=False),
        sa.Column("reservation_end_at", sa.DateTime(), nullable=False),
        sa.Column("source_relay_case_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "reservation_start_at < reservation_end_at",
            name="ck_rental_accessory_links_window_valid",
        ),
        sa.ForeignKeyConstraint(
            ["accessory_type_id"],
            ["accessory_types.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["accessory_unit_id", "accessory_type_id"],
            ["accessory_units.id", "accessory_units.accessory_type_id"],
            name="fk_rental_accessory_links_unit_type",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rental_id"],
            ["rentals.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_relay_case_id"],
            ["rental_relay_cases.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rental_id",
            "accessory_type_id",
            name="uq_rental_accessory_links_rental_type",
        ),
        sa.UniqueConstraint(
            "rental_id",
            "accessory_unit_id",
            name="uq_rental_accessory_links_rental_unit",
        ),
    )
    op.create_index(
        "ix_rental_accessory_links_unit_window",
        "rental_accessory_unit_links",
        ["accessory_unit_id", "reservation_start_at", "reservation_end_at"],
        unique=False,
    )

    op.create_table(
        "accessory_unit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("unit_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("main_device_id", sa.Integer(), nullable=True),
        sa.Column("rental_id", sa.Integer(), nullable=True),
        sa.Column("relay_case_id", sa.Integer(), nullable=True),
        sa.Column("from_warehouse_id", sa.Integer(), nullable=True),
        sa.Column("to_warehouse_id", sa.Integer(), nullable=True),
        sa.Column("from_holder_rental_id", sa.Integer(), nullable=True),
        sa.Column("to_holder_rental_id", sa.Integer(), nullable=True),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('created', 'linked', 'unlinked', 'dispatched', "
            "'relay_handoff', 'inspected', 'warehouse_moved', "
            "'maintenance', 'lost', 'restored', 'retired')",
            name="ck_accessory_unit_events_type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["from_holder_rental_id"],
            ["rentals.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["from_warehouse_id"],
            ["warehouses.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["main_device_id"],
            ["devices.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["relay_case_id"],
            ["rental_relay_cases.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rental_id"],
            ["rentals.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["to_holder_rental_id"],
            ["rentals.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["to_warehouse_id"],
            ["warehouses.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["accessory_units.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_accessory_unit_events_idempotency",
        ),
    )
    op.create_index(
        "ix_accessory_unit_events_unit_occurred",
        "accessory_unit_events",
        ["unit_id", "occurred_at"],
        unique=False,
    )


def downgrade():
    # MySQL can use these leading-column indexes for the table's foreign keys.
    # Dropping each table removes its indexes without violating error 1553.
    op.drop_table("accessory_unit_events")
    op.drop_table("rental_accessory_unit_links")
    op.drop_table("rental_accessory_requests")
    op.drop_table("accessory_units")
    op.drop_table("device_accessory_configs")
    op.drop_table("accessory_types")
