"""remove_sf_waybill_no_column

Revision ID: cb739080dde2
Revises: d765a1af2247
Create Date: 2025-12-08 19:57:41.920629

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cb739080dde2'
down_revision = 'd765a1af2247'
branch_labels = None
depends_on = None


def upgrade():
    # 删除 sf_waybill_no 列
    with op.batch_alter_table('rentals', schema=None) as batch_op:
        batch_op.drop_column('sf_waybill_no')


def downgrade():
    # 恢复 sf_waybill_no 列
    with op.batch_alter_table('rentals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sf_waybill_no', sa.String(length=50), nullable=True, comment='顺丰运单号'))
