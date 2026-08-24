"""align the legacy audit log table with the current business model

Revision ID: 20260825_audit_schema
Revises: 20260807_damage_notes
Create Date: 2026-08-25
"""

from alembic import op
import sqlalchemy as sa


revision = "20260825_audit_schema"
down_revision = "20260807_damage_notes"
branch_labels = None
depends_on = None


_CURRENT_COLUMNS = {
    "resource_type": sa.Column("resource_type", sa.String(length=50)),
    "resource_id": sa.Column("resource_id", sa.String(length=50)),
    "description": sa.Column("description", sa.Text()),
    "details": sa.Column("details", sa.JSON()),
    "ip_address": sa.Column("ip_address", sa.String(length=45)),
    "user_agent": sa.Column("user_agent", sa.String(length=500)),
    "created_at": sa.Column("created_at", sa.DateTime()),
}
_LEGACY_COLUMNS = {"old_value", "new_value", "user_id", "timestamp"}


def _column_names(connection):
    return {
        column["name"]
        for column in sa.inspect(connection).get_columns("audit_logs")
    }


def upgrade():
    connection = op.get_bind()
    columns = _column_names(connection)
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        for name, column in _CURRENT_COLUMNS.items():
            if name not in columns:
                batch_op.add_column(column)

    columns = _column_names(connection)
    if "timestamp" in columns:
        connection.execute(
            sa.text(
                "UPDATE audit_logs "
                "SET created_at = COALESCE(created_at, `timestamp`)"
            )
        )
    if {"old_value", "new_value", "user_id"} <= columns:
        connection.execute(
            sa.text(
                "UPDATE audit_logs SET details = COALESCE(details, "
                "JSON_OBJECT('old_value', old_value, "
                "'new_value', new_value, 'legacy_user_id', user_id))"
            )
        )
    connection.execute(
        sa.text(
            "UPDATE audit_logs SET "
            "resource_type = COALESCE(resource_type, "
            "CASE WHEN rental_id IS NOT NULL THEN 'rental' "
            "WHEN device_id IS NOT NULL THEN 'device' END), "
            "resource_id = COALESCE(resource_id, "
            "CAST(COALESCE(rental_id, device_id) AS CHAR))"
        )
    )

    columns = _column_names(connection)
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        for name in sorted(_LEGACY_COLUMNS & columns):
            batch_op.drop_column(name)


def downgrade():
    connection = op.get_bind()
    columns = _column_names(connection)
    legacy_definitions = {
        "old_value": sa.Column("old_value", sa.Text()),
        "new_value": sa.Column("new_value", sa.Text()),
        "user_id": sa.Column("user_id", sa.String(length=100)),
        "timestamp": sa.Column("timestamp", sa.DateTime()),
    }
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        for name, column in legacy_definitions.items():
            if name not in columns:
                batch_op.add_column(column)

    connection.execute(
        sa.text(
            "UPDATE audit_logs SET `timestamp` = created_at "
            "WHERE `timestamp` IS NULL"
        )
    )
    columns = _column_names(connection)
    with op.batch_alter_table("audit_logs", schema=None) as batch_op:
        for name in sorted(set(_CURRENT_COLUMNS) & columns):
            batch_op.drop_column(name)
