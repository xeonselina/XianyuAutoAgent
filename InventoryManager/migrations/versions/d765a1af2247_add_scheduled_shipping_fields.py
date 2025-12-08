"""add_scheduled_shipping_fields

Revision ID: d765a1af2247
Revises: da9664d9f0c1
Create Date: 2025-12-07 21:27:38.079396

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd765a1af2247'
down_revision = 'da9664d9f0c1'
branch_labels = None
depends_on = None


def upgrade():
    # Add scheduled_ship_time field
    op.add_column('rentals', sa.Column('scheduled_ship_time', sa.DateTime(), nullable=True, comment='预约发货时间'))
    # Add sf_waybill_no field
    op.add_column('rentals', sa.Column('sf_waybill_no', sa.String(50), nullable=True, comment='顺丰运单号'))


def downgrade():
    # Remove sf_waybill_no field
    op.drop_column('rentals', 'sf_waybill_no')
    # Remove scheduled_ship_time field
    op.drop_column('rentals', 'scheduled_ship_time')
