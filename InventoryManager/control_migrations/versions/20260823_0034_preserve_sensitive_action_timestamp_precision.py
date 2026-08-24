"""Preserve exact sensitive-action protocol timestamps on MySQL.

Revision ID: 202608230034
Revises: 202608230033
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op
from sqlalchemy.dialects import mysql


revision = "202608230034"
down_revision = "202608230033"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("created_at", False),
    ("updated_at", False),
    ("expires_at", False),
    ("authorized_at", True),
    ("executing_at", True),
    ("completed_at", True),
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
            "tenant_sensitive_action_intents",
            column_name,
            existing_type=mysql.DATETIME(),
            type_=selected_type,
            existing_nullable=nullable,
        )
