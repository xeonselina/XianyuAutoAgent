"""add scheduled_for_shipping status

Revision ID: 462f68514da8
Revises: 95a4f16beffe
Create Date: 2025-12-18 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '462f68514da8'
down_revision = '95a4f16beffe'
branch_labels = None
depends_on = None


def upgrade():
    # Add 'scheduled_for_shipping' to rental_status enum
    # MySQL requires modifying the entire enum definition
    op.execute("""
        ALTER TABLE rentals
        MODIFY COLUMN status
        ENUM('not_shipped', 'scheduled_for_shipping', 'shipped', 'returned', 'completed', 'cancelled')
        DEFAULT 'not_shipped'
        COMMENT '租赁状态'
    """)


def downgrade():
    # Remove 'scheduled_for_shipping' from enum
    # First update any scheduled_for_shipping to not_shipped
    op.execute("UPDATE rentals SET status = 'not_shipped' WHERE status = 'scheduled_for_shipping'")

    # Then modify the enum back to original values
    op.execute("""
        ALTER TABLE rentals
        MODIFY COLUMN status
        ENUM('not_shipped', 'shipped', 'returned', 'completed', 'cancelled')
        DEFAULT 'not_shipped'
        COMMENT '租赁状态'
    """)
