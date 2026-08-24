"""Preserve exact SMS challenge protocol timestamps on MySQL.

Revision ID: 202608230033
Revises: 202608230032
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op
from sqlalchemy.dialects import mysql


revision = "202608230033"
down_revision = "202608230032"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("created_at", False),
    ("expires_at", False),
    ("delivery_recorded_at", True),
    ("consumed_at", True),
    ("locked_at", True),
    ("invalidated_at", True),
)


def upgrade() -> None:
    _alter_precision(mysql.DATETIME(fsp=6))


def downgrade() -> None:
    _alter_precision(mysql.DATETIME())


def _alter_precision(selected_type) -> None:
    if op.get_context().dialect.name != "mysql":
        return
    for column_name, nullable in _COLUMNS:
        op.alter_column(
            "sms_challenges",
            column_name,
            existing_type=mysql.DATETIME(),
            type_=selected_type,
            existing_nullable=nullable,
        )
