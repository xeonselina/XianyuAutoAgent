"""fix rental status enum values

Revision ID: ecf5c063a38d
Revises: 635938af2cdd
Create Date: 2025-09-28 09:47:18.644093

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ecf5c063a38d'
down_revision = '635938af2cdd'
branch_labels = None
depends_on = None


def upgrade():
    # 修复租赁状态数据
    # 先将列改为字符串类型以便处理无效状态
    op.execute("ALTER TABLE rentals MODIFY COLUMN status VARCHAR(50)")

    # 将无效的状态映射到有效状态
    # pending -> not_shipped (未发货)
    # active -> shipped (已发货)
    # overdue -> shipped (已发货但逾期)
    op.execute("UPDATE rentals SET status = 'not_shipped' WHERE status = 'pending'")
    op.execute("UPDATE rentals SET status = 'shipped' WHERE status = 'active'")
    op.execute("UPDATE rentals SET status = 'shipped' WHERE status = 'overdue'")

    # 将列改回正确的枚举类型
    op.execute("ALTER TABLE rentals MODIFY COLUMN status ENUM('not_shipped', 'shipped', 'returned', 'completed', 'cancelled') DEFAULT 'not_shipped'")


def downgrade():
    # 回滚：恢复旧的状态值
    op.execute("ALTER TABLE rentals MODIFY COLUMN status VARCHAR(50)")

    # 将状态映射回旧值（尽量保持原有逻辑）
    # 注意：这种回滚可能不是完全可逆的，因为我们丢失了原始的具体状态信息
    op.execute("UPDATE rentals SET status = 'pending' WHERE status = 'not_shipped'")
    op.execute("UPDATE rentals SET status = 'active' WHERE status = 'shipped'")

    # 恢复旧的枚举类型（如果知道的话）
    op.execute("ALTER TABLE rentals MODIFY COLUMN status ENUM('pending', 'active', 'overdue', 'returned', 'completed', 'cancelled') DEFAULT 'pending'")
