"""add multi-warehouse foundation

Revision ID: 20260822_warehouses
Revises: 20260822_db_identity
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_warehouses"
down_revision = "20260822_db_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "warehouses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("warehouse_uuid", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("setup_state", sa.String(length=16), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("default_slot", sa.SmallInteger(), nullable=True),
        sa.Column("contact_name", sa.String(length=120), nullable=True),
        sa.Column("contact_phone", sa.String(length=32), nullable=True),
        sa.Column("province", sa.String(length=64), nullable=True),
        sa.Column("city", sa.String(length=64), nullable=True),
        sa.Column("district", sa.String(length=64), nullable=True),
        sa.Column("address_detail", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_warehouses_status_valid",
        ),
        sa.CheckConstraint(
            "setup_state IN ('pending', 'ready')",
            name="ck_warehouses_setup_state_valid",
        ),
        sa.CheckConstraint(
            "(is_default = 1 AND default_slot = 1) OR "
            "(is_default = 0 AND default_slot IS NULL)",
            name="ck_warehouses_default_slot_consistent",
        ),
        sa.CheckConstraint(
            "setup_state = 'pending' OR "
            "(name IS NOT NULL AND contact_name IS NOT NULL AND "
            "contact_phone IS NOT NULL AND province IS NOT NULL AND "
            "city IS NOT NULL AND district IS NOT NULL AND "
            "address_detail IS NOT NULL)",
            name="ck_warehouses_ready_fields_present",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("default_slot", name="uq_warehouses_default_slot"),
        sa.UniqueConstraint("warehouse_uuid", name="uq_warehouses_warehouse_uuid"),
    )

    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "warehouse_id",
                sa.Integer(),
                nullable=True,
                comment="当前实际仓库ID",
            )
        )
        batch_op.create_foreign_key(
            "fk_devices_warehouse_id_warehouses",
            "warehouses",
            ["warehouse_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "ix_devices_warehouse_id",
            ["warehouse_id"],
            unique=False,
        )

    op.create_table(
        "warehouse_printers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("printer_sn", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'verification_failed')",
            name="ck_warehouse_printers_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("printer_sn", name="uq_warehouse_printers_printer_sn"),
        sa.UniqueConstraint("warehouse_id", name="uq_warehouse_printers_warehouse_id"),
    )

    op.create_table(
        "user_warehouse_preferences",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("scene", sa.String(length=32), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "scene IN ('booking', 'shipping', 'inspection')",
            name="ck_user_warehouse_preferences_scene_valid",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "scene"),
    )

    op.create_table(
        "warehouse_provider_bindings",
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_account_uuid", sa.String(length=36), nullable=True),
        sa.Column("binding_revision", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("bound_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "binding_revision >= 1",
            name="ck_warehouse_provider_bindings_revision_positive",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'verification_failed')",
            name="ck_warehouse_provider_bindings_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("warehouse_id", "provider"),
        sa.UniqueConstraint(
            "provider",
            "provider_account_uuid",
            name="uq_warehouse_provider_bindings_provider_account",
        ),
    )

    op.create_table(
        "device_warehouse_movements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("from_warehouse_id", sa.Integer(), nullable=True),
        sa.Column("to_warehouse_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("actor_user_id", sa.String(length=36), nullable=False),
        sa.Column("related_resource_type", sa.String(length=64), nullable=True),
        sa.Column("related_resource_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "source IN ('inspection', 'manual_change')",
            name="ck_device_warehouse_movements_source_valid",
        ),
        sa.CheckConstraint(
            "from_warehouse_id IS NULL OR from_warehouse_id <> to_warehouse_id",
            name="ck_device_warehouse_movements_changes_warehouse",
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["from_warehouse_id"],
            ["warehouses.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_warehouse_id"],
            ["warehouses.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("device_warehouse_movements")
    op.drop_table("warehouse_provider_bindings")
    op.drop_table("user_warehouse_preferences")
    op.drop_table("warehouse_printers")
    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_devices_warehouse_id_warehouses",
            type_="foreignkey",
        )
        batch_op.drop_index("ix_devices_warehouse_id")
        batch_op.drop_column("warehouse_id")
    op.drop_table("warehouses")
