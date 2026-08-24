"""Make the invitation bearer digest length check effective on MySQL.

Revision ID: 202608230031
Revises: 202608230030
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op
from sqlalchemy.dialects import mysql


revision = "202608230031"
down_revision = "202608230030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _alter_token_hash(mysql.VARBINARY(32))


def downgrade() -> None:
    _alter_token_hash(mysql.BINARY(32))


def _alter_token_hash(selected_type) -> None:
    # MySQL-family BINARY pads short values to 32 bytes, which makes
    # LENGTH(token_hash) = 32 ineffective; VARBINARY preserves the submitted
    # length and lets the existing check reject malformed data.
    if op.get_context().dialect.name not in {"mysql", "mariadb"}:
        return
    op.alter_column(
        "tenant_invitations",
        "token_hash",
        existing_type=mysql.BINARY(32),
        type_=selected_type,
        existing_nullable=False,
    )
