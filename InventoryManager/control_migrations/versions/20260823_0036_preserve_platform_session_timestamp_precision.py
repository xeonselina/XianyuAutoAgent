"""Preserve exact platform-session timestamps on MySQL.

Revision ID: 202608230036
Revises: 202608230035
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op
from sqlalchemy.dialects import mysql


revision = "202608230036"
down_revision = "202608230035"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("mfa_verified_at", False),
    ("created_at", False),
    ("last_seen_at", False),
    ("idle_expires_at", False),
    ("absolute_expires_at", False),
    ("revoked_at", True),
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
            "platform_admin_sessions",
            column_name,
            existing_type=mysql.DATETIME(),
            type_=selected_type,
            existing_nullable=nullable,
        )
