"""add rental logistics and relay accessory facts

Revision ID: 20260822_rental_logistics
Revises: 20260822_accessories
Create Date: 2026-08-22
"""

from alembic import context, op
import sqlalchemy as sa


revision = "20260822_rental_logistics"
down_revision = "20260822_accessories"
branch_labels = None
depends_on = None


_DOWNGRADE_DEVICE_FK_INDEX = "ix_rentals_device_id_downgrade"


def upgrade():
    with op.batch_alter_table("rentals", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "customer_note",
                sa.Text(),
                nullable=True,
                comment="客户可见备注",
            )
        )
        batch_op.add_column(
            sa.Column("customer_province", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("customer_city", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("customer_district", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "customer_address_detail",
                sa.String(length=255),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "preferred_warehouse_id",
                sa.Integer(),
                nullable=True,
                comment="预约时用于排序的偏好仓库，不覆盖设备实际仓库",
            )
        )
        batch_op.add_column(
            sa.Column("logistics_days", sa.SmallInteger(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("planned_ship_out_date", sa.Date(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("planned_return_date", sa.Date(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("actual_shipped_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("actual_returned_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "logistics_estimate_origin_warehouse_id",
                sa.Integer(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "logistics_estimate_provider",
                sa.String(length=32),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "logistics_estimate_provider_version",
                sa.String(length=64),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "logistics_estimate_rule_version",
                sa.String(length=64),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "logistics_estimate_days",
                sa.SmallInteger(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "logistics_estimate_evaluated_at",
                sa.DateTime(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "logistics_estimate_address_digest",
                sa.String(length=64),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "logistics_estimate_address_summary",
                sa.String(length=255),
                nullable=True,
            )
        )
        batch_op.create_check_constraint(
            "ck_rentals_logistics_days_valid",
            "logistics_days IS NULL OR "
            "(logistics_days >= 0 AND logistics_days <= 7)",
        )
        batch_op.create_check_constraint(
            "ck_rentals_estimate_days_valid",
            "logistics_estimate_days IS NULL OR "
            "(logistics_estimate_days >= 0 AND logistics_estimate_days <= 7)",
        )
        batch_op.create_check_constraint(
            "ck_rentals_planned_window_consistent",
            "(planned_ship_out_date IS NULL AND planned_return_date IS NULL) OR "
            "(planned_ship_out_date IS NOT NULL AND "
            "planned_return_date IS NOT NULL AND "
            "planned_ship_out_date < planned_return_date)",
        )
        batch_op.create_foreign_key(
            "fk_rentals_preferred_warehouse_id_warehouses",
            "warehouses",
            ["preferred_warehouse_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_rentals_estimate_origin_warehouse_id_warehouses",
            "warehouses",
            ["logistics_estimate_origin_warehouse_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "ix_rentals_device_status_usage_period",
            ["device_id", "status", "start_date", "end_date"],
            unique=False,
        )
        batch_op.create_index(
            "ix_rentals_device_status_planned_window",
            [
                "device_id",
                "status",
                "planned_ship_out_date",
                "planned_return_date",
            ],
            unique=False,
        )

    # A previous downgrade may have installed this MySQL-only support index
    # before removing the two composite indexes.  The new usage-period index
    # now supports the legacy device FK, so head metadata must not retain it.
    if (
        not context.is_offline_mode()
        and op.get_bind().dialect.name == "mysql"
        and _DOWNGRADE_DEVICE_FK_INDEX in _index_names("rentals")
    ):
        op.drop_index(_DOWNGRADE_DEVICE_FK_INDEX, table_name="rentals")

    with op.batch_alter_table("rental_relay_cases", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("accessory_note", sa.String(length=500), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "accessory_note_updated_by",
                sa.String(length=36),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "accessory_note_updated_at",
                sa.DateTime(),
                nullable=True,
            )
        )


def downgrade():
    with op.batch_alter_table("rental_relay_cases", schema=None) as batch_op:
        batch_op.drop_column("accessory_note_updated_at")
        batch_op.drop_column("accessory_note_updated_by")
        batch_op.drop_column("accessory_note")

    if (
        op.get_bind().dialect.name == "mysql"
        and (
            context.is_offline_mode()
            or not _has_surviving_device_index()
        )
    ):
        op.create_index(
            _DOWNGRADE_DEVICE_FK_INDEX,
            "rentals",
            ["device_id"],
            unique=False,
        )

    with op.batch_alter_table("rentals", schema=None) as batch_op:
        batch_op.drop_index("ix_rentals_device_status_planned_window")
        batch_op.drop_index("ix_rentals_device_status_usage_period")
        batch_op.drop_constraint(
            "fk_rentals_estimate_origin_warehouse_id_warehouses",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_rentals_preferred_warehouse_id_warehouses",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "ck_rentals_planned_window_consistent",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_rentals_estimate_days_valid",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_rentals_logistics_days_valid",
            type_="check",
        )
        batch_op.drop_column("logistics_estimate_address_summary")
        batch_op.drop_column("logistics_estimate_address_digest")
        batch_op.drop_column("logistics_estimate_evaluated_at")
        batch_op.drop_column("logistics_estimate_days")
        batch_op.drop_column("logistics_estimate_rule_version")
        batch_op.drop_column("logistics_estimate_provider_version")
        batch_op.drop_column("logistics_estimate_provider")
        batch_op.drop_column("logistics_estimate_origin_warehouse_id")
        batch_op.drop_column("actual_returned_at")
        batch_op.drop_column("actual_shipped_at")
        batch_op.drop_column("planned_return_date")
        batch_op.drop_column("planned_ship_out_date")
        batch_op.drop_column("logistics_days")
        batch_op.drop_column("preferred_warehouse_id")
        batch_op.drop_column("customer_address_detail")
        batch_op.drop_column("customer_district")
        batch_op.drop_column("customer_city")
        batch_op.drop_column("customer_province")
        batch_op.drop_column("customer_note")


def _index_names(table_name):
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
        if isinstance(index.get("name"), str)
    }


def _has_surviving_device_index():
    removed = {
        "ix_rentals_device_status_planned_window",
        "ix_rentals_device_status_usage_period",
    }
    return any(
        index.get("name") not in removed
        and tuple(index.get("column_names") or ())[:1] == ("device_id",)
        for index in sa.inspect(op.get_bind()).get_indexes("rentals")
    )
