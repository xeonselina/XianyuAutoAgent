"""Make schema-operation digest length checks effective on MySQL.

Revision ID: 202608230038
Revises: 202608230037
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op
from sqlalchemy.dialects import mysql


revision = "202608230038"
down_revision = "202608230037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _alter_digest(mysql.VARBINARY(32))


def downgrade() -> None:
    _alter_digest(mysql.BINARY(32))


def _alter_digest(selected_type) -> None:
    if op.get_context().dialect.name != "mysql":
        return
    op.alter_column(
        "platform_schema_operation_leases",
        "last_request_digest",
        existing_type=mysql.BINARY(32),
        type_=selected_type,
        existing_nullable=True,
    )
