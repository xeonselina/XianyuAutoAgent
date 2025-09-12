"""fix_is_accessory_null_values

Revision ID: bd27d78e7f87
Revises: bff12792e76a
Create Date: 2025-09-10 19:00:03.812068

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bd27d78e7f87'
down_revision = 'bff12792e76a'
branch_labels = None
depends_on = None


def upgrade():
    # 将所有is_accessory为NULL的设备更新为False（表示非附件）
    op.execute("UPDATE devices SET is_accessory = FALSE WHERE is_accessory IS NULL")


def downgrade():
    # 回滚时将FALSE值改回NULL（如果需要的话）
    # 注意：这个回滚可能不完全准确，因为我们无法区分原来就是FALSE的和从NULL更新的
    # 但由于这是数据修复，通常不需要完全可逆的回滚
    pass
