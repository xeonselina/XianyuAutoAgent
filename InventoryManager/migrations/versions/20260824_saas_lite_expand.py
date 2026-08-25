"""add the lightweight warehouse and shop schema

Revision ID: 20260824_saas_lite_expand
Revises: 20260825_audit_schema
Create Date: 2026-08-25
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_saas_lite_expand"
down_revision = "20260825_audit_schema"
branch_labels = None
depends_on = None


def _tables(connection):
    return set(sa.inspect(connection).get_table_names())


def _columns(connection, table_name):
    return {
        column["name"]
        for column in sa.inspect(connection).get_columns(table_name)
    }


def _foreign_key_exists(connection, table_name, columns):
    expected = tuple(columns)
    return any(
        tuple(foreign_key["constrained_columns"]) == expected
        for foreign_key in sa.inspect(connection).get_foreign_keys(
            table_name
        )
    )


def _add_foreign_key_column(
    connection,
    table_name,
    column_name,
    referred_table,
    constraint_name,
):
    if column_name not in _columns(connection, table_name):
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(column_name, sa.Integer(), nullable=True)
            )
    if not _foreign_key_exists(connection, table_name, [column_name]):
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.create_foreign_key(
                constraint_name,
                referred_table,
                [column_name],
                ["id"],
                ondelete="RESTRICT",
            )


def _drop_alert_order_uniques(connection):
    inspector = sa.inspect(connection)
    names = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(
            "xianyu_order_alerts"
        )
        if constraint["column_names"] == ["order_no"]
    }
    names.update(
        index["name"]
        for index in inspector.get_indexes("xianyu_order_alerts")
        if index["unique"] and index["column_names"] == ["order_no"]
    )
    for name in sorted(names):
        op.drop_index(name, table_name="xianyu_order_alerts")


def _ensure_alert_order_lookup_index(connection):
    indexes = sa.inspect(connection).get_indexes("xianyu_order_alerts")
    if not any(
        index["column_names"] == ["order_no"] and not index["unique"]
        for index in indexes
    ):
        op.create_index(
            "ix_xianyu_order_alerts_order_no",
            "xianyu_order_alerts",
            ["order_no"],
            unique=False,
        )


def upgrade():
    connection = op.get_bind()
    tables = _tables(connection)

    if "warehouses" not in tables:
        op.create_table(
            "warehouses",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("province", sa.String(length=64), nullable=False),
            sa.Column("city", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    if "xianyu_shops" not in tables:
        op.create_table(
            "xianyu_shops",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("app_key", sa.String(length=255), nullable=False),
            sa.Column("app_secret_ciphertext", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("last_success_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.String(length=1000), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    tables = _tables(connection)
    if "xianyu_order_alerts" not in tables:
        op.create_table(
            "xianyu_order_alerts",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("order_no", sa.String(length=50), nullable=False),
            sa.Column("xianyu_shop_id", sa.Integer(), nullable=True),
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
            sa.ForeignKeyConstraint(
                ["xianyu_shop_id"], ["xianyu_shops.id"],
                name="fk_xianyu_order_alerts_xianyu_shop_id",
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_xianyu_order_alerts_order_no",
            "xianyu_order_alerts", ["order_no"], unique=False,
        )
        op.create_index(
            "ix_xianyu_order_alerts_state",
            "xianyu_order_alerts", ["state"], unique=False,
        )
    if "warehouse_sf_configs" not in tables:
        op.create_table(
            "warehouse_sf_configs",
            sa.Column("warehouse_id", sa.Integer(), nullable=False),
            sa.Column("partner_id", sa.String(length=100), nullable=True),
            sa.Column("checkword_ciphertext", sa.Text(), nullable=True),
            sa.Column("monthly_card_ciphertext", sa.Text(), nullable=True),
            sa.Column("test_mode", sa.Boolean(), nullable=False),
            sa.Column("sender_name", sa.String(length=100), nullable=True),
            sa.Column("sender_phone", sa.String(length=30), nullable=True),
            sa.Column("sender_address", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["warehouse_id"],
                ["warehouses.id"],
                name="fk_warehouse_sf_configs_warehouse_id",
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("warehouse_id"),
        )
    if "warehouse_kuaimai_configs" not in tables:
        op.create_table(
            "warehouse_kuaimai_configs",
            sa.Column("warehouse_id", sa.Integer(), nullable=False),
            sa.Column("app_id", sa.String(length=100), nullable=True),
            sa.Column("app_secret_ciphertext", sa.Text(), nullable=True),
            sa.Column("printer_sn", sa.String(length=100), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["warehouse_id"],
                ["warehouses.id"],
                name="fk_warehouse_kuaimai_configs_warehouse_id",
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("warehouse_id"),
        )

    _add_foreign_key_column(
        connection,
        "devices",
        "warehouse_id",
        "warehouses",
        "fk_devices_warehouse_id",
    )
    _add_foreign_key_column(
        connection,
        "rentals",
        "warehouse_id",
        "warehouses",
        "fk_rentals_warehouse_id",
    )
    _add_foreign_key_column(
        connection,
        "rentals",
        "xianyu_shop_id",
        "xianyu_shops",
        "fk_rentals_xianyu_shop_id",
    )
    _add_foreign_key_column(
        connection,
        "xianyu_order_alerts",
        "xianyu_shop_id",
        "xianyu_shops",
        "fk_xianyu_order_alerts_xianyu_shop_id",
    )
    _drop_alert_order_uniques(connection)
    _ensure_alert_order_lookup_index(connection)


def _drop_foreign_key_column(connection, table_name, column_name):
    if column_name not in _columns(connection, table_name):
        return
    foreign_keys = [
        foreign_key
        for foreign_key in sa.inspect(connection).get_foreign_keys(table_name)
        if foreign_key["constrained_columns"] == [column_name]
    ]
    with op.batch_alter_table(table_name, schema=None) as batch_op:
        for foreign_key in foreign_keys:
            batch_op.drop_constraint(
                foreign_key["name"],
                type_="foreignkey",
            )
        batch_op.drop_column(column_name)


def downgrade():
    connection = op.get_bind()
    _drop_foreign_key_column(
        connection, "xianyu_order_alerts", "xianyu_shop_id"
    )
    _drop_foreign_key_column(connection, "rentals", "xianyu_shop_id")
    _drop_foreign_key_column(connection, "rentals", "warehouse_id")
    _drop_foreign_key_column(connection, "devices", "warehouse_id")

    indexes = sa.inspect(connection).get_indexes("xianyu_order_alerts")
    for index in indexes:
        if index["column_names"] == ["order_no"]:
            op.drop_index(index["name"], table_name="xianyu_order_alerts")
    op.create_index(
        "ix_xianyu_order_alerts_order_no",
        "xianyu_order_alerts",
        ["order_no"],
        unique=True,
    )

    for table_name in (
        "warehouse_kuaimai_configs",
        "warehouse_sf_configs",
        "xianyu_shops",
        "warehouses",
    ):
        if table_name in _tables(connection):
            op.drop_table(table_name)
