"""update device status enum to online/offline only

Revision ID: 635938af2cdd
Revises: cdb9f52eb853
Create Date: 2025-09-27 23:00:03.897419

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '635938af2cdd'
down_revision = 'cdb9f52eb853'
branch_labels = None
depends_on = None


def upgrade():
    # MySQL/MariaDB 枚举更新策略
    # 步骤1: 先将列改为字符串类型
    op.execute("ALTER TABLE devices MODIFY COLUMN status VARCHAR(50)")

    # 步骤2: 更新数据 - 将旧状态映射到新状态
    op.execute("UPDATE devices SET status = 'online' WHERE status IN ('idle', 'pending_ship', 'renting', 'pending_return', 'returned')")
    op.execute("UPDATE devices SET status = 'offline' WHERE status = 'offline'")

    # 步骤3: 将列改为新的枚举类型
    op.execute("ALTER TABLE devices MODIFY COLUMN status ENUM('online', 'offline') DEFAULT 'online'")


def downgrade():
    # MySQL/MariaDB 枚举回滚策略
    # 步骤1: 先将列改为字符串类型
    op.execute("ALTER TABLE devices MODIFY COLUMN status VARCHAR(50)")

    # 步骤2: 将现有状态映射回旧状态
    op.execute("UPDATE devices SET status = 'idle' WHERE status = 'online'")
    # offline 保持不变

    # 步骤3: 将列改为旧的枚举类型
    op.execute("ALTER TABLE devices MODIFY COLUMN status ENUM('idle', 'pending_ship', 'renting', 'pending_return', 'returned', 'offline') DEFAULT 'idle'")
