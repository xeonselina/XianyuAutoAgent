"""Preserve exact subscription protocol timestamps on MySQL.

Revision ID: 202608230037
Revises: 202608230036
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op
from sqlalchemy.dialects import mysql


revision = "202608230037"
down_revision = "202608230036"
branch_labels = None
depends_on = None


_TABLE_COLUMNS = {
    "subscriptions": (("expires_at", False),),
    "subscription_events": (
        ("calculation_base_at", False),
        ("database_effective_at", False),
        ("before_expires_at", True),
        ("after_expires_at", False),
        ("factor_accepted_at", True),
    ),
}


def upgrade() -> None:
    _alter_precision(mysql.DATETIME(fsp=6))


def downgrade() -> None:
    _alter_precision(mysql.DATETIME())


def _alter_precision(selected_type) -> None:
    if op.get_context().dialect.name != "mysql":
        return
    for table_name, columns in _TABLE_COLUMNS.items():
        for column_name, nullable in columns:
            op.alter_column(
                table_name,
                column_name,
                existing_type=mysql.DATETIME(),
                type_=selected_type,
                existing_nullable=nullable,
            )
