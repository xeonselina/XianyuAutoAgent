"""Expand operational protocol timestamps to MySQL microsecond precision.

Revision ID: 202608230030
Revises: 202608220029
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "202608230030"
down_revision = "202608220029"
branch_labels = None
depends_on = None


_SIGNAL_COLUMNS = (
    ("alert_triggered_at", True),
    ("next_repeat_at", True),
    ("observed_at", False),
    ("freshness_deadline_at", False),
    ("evaluated_at", False),
    ("created_at", False),
    ("updated_at", False),
)
_EVENT_COLUMNS = (
    ("suppressed_until", True),
    ("occurred_at", False),
)


def upgrade() -> None:
    _alter_timestamp_precision(mysql.DATETIME(fsp=6))


def downgrade() -> None:
    _alter_timestamp_precision(mysql.DATETIME())


def _alter_timestamp_precision(selected_type: sa.types.TypeEngine) -> None:
    # SQLite already retains the values used by local migration contract
    # tests and its ALTER COLUMN grammar cannot express MySQL FSP.  The
    # forward fix is intentionally physical-dialect specific; ORM metadata
    # continues to resolve to ordinary DateTime on non-MySQL dialects.
    if op.get_context().dialect.name != "mysql":
        return
    for table_name, columns in (
        ("platform_operational_signals", _SIGNAL_COLUMNS),
        ("platform_alert_lifecycle_events", _EVENT_COLUMNS),
    ):
        for column_name, nullable in columns:
            op.alter_column(
                table_name,
                column_name,
                existing_type=mysql.DATETIME(),
                type_=selected_type,
                existing_nullable=nullable,
            )
