"""Preserve exact recovery-factor consumption time on MySQL.

Revision ID: 202608230032
Revises: 202608230031
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op
from sqlalchemy.dialects import mysql


revision = "202608230032"
down_revision = "202608230031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _alter_consumed_at(mysql.DATETIME(fsp=6))


def downgrade() -> None:
    _alter_consumed_at(mysql.DATETIME())


def _alter_consumed_at(selected_type) -> None:
    if op.get_context().dialect.name != "mysql":
        return
    op.alter_column(
        "platform_admin_recovery_codes",
        "consumed_at",
        existing_type=mysql.DATETIME(),
        type_=selected_type,
        existing_nullable=True,
    )
