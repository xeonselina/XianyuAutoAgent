"""add scheduled shipping index

Revision ID: 462f697d4fcb
Revises: 462f68514da8
Create Date: 2025-12-18 16:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '462f697d4fcb'
down_revision = '462f68514da8'
branch_labels = None
depends_on = None


def upgrade():
    # Create index for efficient querying of scheduled shipments
    # MySQL doesn't support partial indexes like PostgreSQL
    # So we create a regular composite index
    op.create_index(
        'idx_rental_scheduled_shipping',
        'rentals',
        ['status', 'scheduled_ship_time'],
        unique=False
    )


def downgrade():
    # Remove the index
    op.drop_index('idx_rental_scheduled_shipping', table_name='rentals')
