"""remove obsolete device online/offline status

Revision ID: 20260729_device_lifecycle_only
Revises: 20260724_xianyu_alerts
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa


revision = "20260729_device_lifecycle_only"
down_revision = "20260724_xianyu_alerts"
branch_labels = None
depends_on = None


def upgrade():
    # The old offline flag is not a lifecycle event. Active rows remain active,
    # while existing sold/decommissioned/damaged/retired rows are untouched.
    op.execute(
        "UPDATE devices "
        "SET lifecycle_status = 'active' "
        "WHERE status = 'offline' AND lifecycle_status = 'active'"
    )
    op.drop_column("devices", "status")


def downgrade():
    op.add_column(
        "devices",
        sa.Column(
            "status",
            sa.Enum("online", "offline", name="device_status"),
            nullable=False,
            server_default="online",
        ),
    )
