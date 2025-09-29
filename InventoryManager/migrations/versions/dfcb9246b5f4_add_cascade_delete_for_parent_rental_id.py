"""add_cascade_delete_for_parent_rental_id

Revision ID: dfcb9246b5f4
Revises: b4f997b59975
Create Date: 2025-09-29 13:33:11.682119

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dfcb9246b5f4'
down_revision = 'b4f997b59975'
branch_labels = None
depends_on = None


def upgrade():
    # 更新外键约束以添加CASCADE删除
    with op.batch_alter_table('rentals', schema=None) as batch_op:
        # 删除旧的外键约束（实际名称是 rentals_ibfk_2）
        batch_op.drop_constraint('rentals_ibfk_2', type_='foreignkey')
        # 创建新的外键约束，添加CASCADE删除
        batch_op.create_foreign_key(
            'fk_rentals_parent_rental_id',
            'rentals',
            ['parent_rental_id'],
            ['id'],
            ondelete='CASCADE'
        )


def downgrade():
    # 回滚：删除CASCADE约束，恢复原始外键约束
    with op.batch_alter_table('rentals', schema=None) as batch_op:
        # 删除CASCADE外键约束
        batch_op.drop_constraint('fk_rentals_parent_rental_id', type_='foreignkey')
        # 恢复原始外键约束（无CASCADE）
        batch_op.create_foreign_key(
            'fk_rentals_parent_rental_id',
            'rentals',
            ['parent_rental_id'],
            ['id']
        )
