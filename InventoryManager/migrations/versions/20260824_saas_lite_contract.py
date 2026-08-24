"""backfill and enforce the lightweight warehouse and shop schema

Revision ID: 20260824_saas_lite_contract
Revises: 20260824_saas_lite_expand
Create Date: 2026-08-25
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_saas_lite_contract"
down_revision = "20260824_saas_lite_expand"
branch_labels = None
depends_on = None


def _tables(connection):
    return set(sa.inspect(connection).get_table_names())


def _column(connection, table_name, column_name):
    return next(
        column
        for column in sa.inspect(connection).get_columns(table_name)
        if column["name"] == column_name
    )


def _has_unique(connection, table_name, columns):
    expected = tuple(columns)
    return any(
        tuple(constraint["column_names"]) == expected
        for constraint in sa.inspect(connection).get_unique_constraints(
            table_name
        )
    )


def _ensure_default_warehouse(connection):
    warehouse_id = connection.scalar(
        sa.text(
            "SELECT id FROM warehouses "
            "WHERE province = '待配置' AND city = '待配置' "
            "AND name = '默认仓库' ORDER BY id LIMIT 1"
        )
    )
    if warehouse_id is not None:
        return warehouse_id
    result = connection.execute(
        sa.text(
            "INSERT INTO warehouses "
            "(province, city, name, created_at, updated_at) VALUES "
            "('待配置', '待配置', '默认仓库', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )
    return result.lastrowid


def _ensure_default_shop(connection):
    shop_id = connection.scalar(
        sa.text(
            "SELECT id FROM xianyu_shops "
            "WHERE name = '默认闲鱼店铺' AND app_key = '' "
            "ORDER BY id LIMIT 1"
        )
    )
    if shop_id is not None:
        return shop_id
    result = connection.execute(
        sa.text(
            "INSERT INTO xianyu_shops "
            "(name, app_key, is_active, created_at, updated_at) VALUES "
            "('默认闲鱼店铺', '', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )
    return result.lastrowid


def _make_not_null(connection, table_name, column_name):
    column = _column(connection, table_name, column_name)
    if column["nullable"]:
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.alter_column(
                column_name,
                existing_type=column["type"],
                nullable=False,
            )


def upgrade():
    connection = op.get_bind()
    warehouse_id = _ensure_default_warehouse(connection)
    shop_id = _ensure_default_shop(connection)

    connection.execute(
        sa.text(
            "UPDATE devices SET warehouse_id = :warehouse_id "
            "WHERE warehouse_id IS NULL"
        ),
        {"warehouse_id": warehouse_id},
    )
    connection.execute(
        sa.text(
            "UPDATE rentals SET warehouse_id = :warehouse_id "
            "WHERE warehouse_id IS NULL"
        ),
        {"warehouse_id": warehouse_id},
    )
    connection.execute(
        sa.text(
            "UPDATE xianyu_order_alerts SET xianyu_shop_id = :shop_id "
            "WHERE xianyu_shop_id IS NULL"
        ),
        {"shop_id": shop_id},
    )
    connection.execute(
        sa.text(
            "UPDATE rentals SET xianyu_shop_id = :shop_id "
            "WHERE xianyu_shop_id IS NULL "
            "AND parent_rental_id IS NULL "
            "AND NULLIF(TRIM(xianyu_order_no), '') IS NOT NULL"
        ),
        {"shop_id": shop_id},
    )

    if "xianyu_order_sync_state" in _tables(connection):
        sync_state = connection.execute(
            sa.text(
                "SELECT last_success_at, last_error "
                "FROM xianyu_order_sync_state ORDER BY id LIMIT 1"
            )
        ).mappings().first()
        if sync_state is not None:
            connection.execute(
                sa.text(
                    "UPDATE xianyu_shops SET last_success_at = :success, "
                    "last_error = :error, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = :shop_id"
                ),
                {
                    "success": sync_state["last_success_at"],
                    "error": sync_state["last_error"],
                    "shop_id": shop_id,
                },
            )
        op.drop_table("xianyu_order_sync_state")

    _make_not_null(connection, "devices", "warehouse_id")
    _make_not_null(connection, "rentals", "warehouse_id")
    _make_not_null(connection, "xianyu_order_alerts", "xianyu_shop_id")

    if not _has_unique(
        connection,
        "xianyu_order_alerts",
        ["xianyu_shop_id", "order_no"],
    ):
        op.create_unique_constraint(
            "uq_xianyu_alert_shop_order",
            "xianyu_order_alerts",
            ["xianyu_shop_id", "order_no"],
        )
    if not _has_unique(
        connection,
        "rentals",
        ["xianyu_shop_id", "xianyu_order_no"],
    ):
        op.create_unique_constraint(
            "uq_rental_shop_order",
            "rentals",
            ["xianyu_shop_id", "xianyu_order_no"],
        )


def _drop_unique(connection, table_name, columns):
    expected = tuple(columns)
    first_column = columns[0]
    indexes = sa.inspect(connection).get_indexes(table_name)
    if not any(
        index["column_names"] == [first_column]
        for index in indexes
    ):
        op.create_index(
            f"ix_{table_name}_{first_column}",
            table_name,
            [first_column],
            unique=False,
        )
    names = {
        constraint["name"]
        for constraint in sa.inspect(connection).get_unique_constraints(
            table_name
        )
        if tuple(constraint["column_names"]) == expected
    }
    for name in sorted(names):
        op.drop_constraint(name, table_name, type_="unique")


def _make_nullable(connection, table_name, column_name):
    column = _column(connection, table_name, column_name)
    if not column["nullable"]:
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.alter_column(
                column_name,
                existing_type=column["type"],
                nullable=True,
            )


def downgrade():
    connection = op.get_bind()
    _drop_unique(
        connection,
        "rentals",
        ["xianyu_shop_id", "xianyu_order_no"],
    )
    _drop_unique(
        connection,
        "xianyu_order_alerts",
        ["xianyu_shop_id", "order_no"],
    )
    _make_nullable(connection, "devices", "warehouse_id")
    _make_nullable(connection, "rentals", "warehouse_id")
    _make_nullable(connection, "xianyu_order_alerts", "xianyu_shop_id")

    if "xianyu_order_sync_state" not in _tables(connection):
        op.create_table(
            "xianyu_order_sync_state",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("last_success_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.String(length=1000), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    if connection.scalar(
        sa.text("SELECT id FROM xianyu_order_sync_state WHERE id = 1")
    ) is None:
        connection.execute(
            sa.text(
                "INSERT INTO xianyu_order_sync_state "
                "(id, last_attempt_at, last_success_at, last_error) "
                "SELECT 1, NULL, last_success_at, last_error "
                "FROM xianyu_shops ORDER BY id LIMIT 1"
            )
        )
