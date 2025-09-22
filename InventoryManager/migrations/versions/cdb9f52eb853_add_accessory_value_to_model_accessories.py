"""add_accessory_value_to_model_accessories

Revision ID: cdb9f52eb853
Revises: fdaa742857fe
Create Date: 2025-09-21 16:20:33.342536

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cdb9f52eb853'
down_revision = 'fdaa742857fe'
branch_labels = None
depends_on = None


def upgrade():
    # 为 model_accessories 表添加附件价值字段
    with op.batch_alter_table('model_accessories', schema=None) as batch_op:
        batch_op.add_column(sa.Column('accessory_value', sa.Numeric(precision=10, scale=2), nullable=True, comment='附件价值'))


def downgrade():
    # 删除附件价值字段
    with op.batch_alter_table('model_accessories', schema=None) as batch_op:
        batch_op.drop_column('accessory_value')
