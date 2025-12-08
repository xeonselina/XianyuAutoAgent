"""add xianyu order fields to rentals

Revision ID: da9664d9f0c1
Revises: 295f5ec7c5fb
Create Date: 2025-12-06 23:57:56.809733

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'da9664d9f0c1'
down_revision = '295f5ec7c5fb'
branch_labels = None
depends_on = None


def upgrade():
    # 添加闲鱼订单相关字段到rentals表
    with op.batch_alter_table('rentals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('xianyu_order_no', sa.String(length=50), nullable=True, comment='闲鱼订单号'))
        batch_op.add_column(sa.Column('order_amount', sa.DECIMAL(precision=10, scale=2), nullable=True, comment='订单金额(元)'))
        batch_op.add_column(sa.Column('buyer_id', sa.String(length=100), nullable=True, comment='买家ID(闲鱼EID)'))


def downgrade():
    # 回滚: 删除添加的字段
    with op.batch_alter_table('rentals', schema=None) as batch_op:
        batch_op.drop_column('buyer_id')
        batch_op.drop_column('order_amount')
        batch_op.drop_column('xianyu_order_no')
