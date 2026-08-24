"""Preserve exact invitation lifecycle timestamps on MySQL.

Revision ID: 202608230035
Revises: 202608230034
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op
from sqlalchemy.dialects import mysql


revision = "202608230035"
down_revision = "202608230034"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("expires_at", False),
    ("accepted_at", True),
    ("superseded_at", True),
    ("created_at", False),
    ("updated_at", False),
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
            "tenant_invitations",
            column_name,
            existing_type=mysql.DATETIME(),
            type_=selected_type,
            existing_nullable=nullable,
        )
