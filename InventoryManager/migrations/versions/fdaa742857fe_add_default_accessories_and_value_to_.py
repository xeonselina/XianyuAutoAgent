"""add_default_accessories_and_value_to_device_models

Revision ID: fdaa742857fe
Revises: b7d7e1188aa0
Create Date: 2025-09-21 16:17:05.805798

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fdaa742857fe'
down_revision = 'b7d7e1188aa0'
branch_labels = None
depends_on = None


def upgrade():
    # 为 device_models 表添加默认附件和设备价值字段
    with op.batch_alter_table('device_models', schema=None) as batch_op:
        batch_op.add_column(sa.Column('default_accessories', sa.Text(), nullable=True, comment='默认附件列表，JSON格式'))
        batch_op.add_column(sa.Column('device_value', sa.Numeric(precision=10, scale=2), nullable=True, comment='设备价值'))


def downgrade():
    # 删除添加的字段
    with op.batch_alter_table('device_models', schema=None) as batch_op:
        batch_op.drop_column('device_value')
        batch_op.drop_column('default_accessories')
