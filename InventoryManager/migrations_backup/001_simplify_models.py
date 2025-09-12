"""
数据库迁移脚本 - 简化模型结构
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '001_simplify_models'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """升级数据库结构"""
    
    # 1. 删除users表
    op.drop_table('users')
    
    # 2. 修改devices表主键类型
    # 先删除外键约束
    op.drop_constraint('fk_rentals_device_id', 'rentals', type_='foreignkey')
    op.drop_constraint('fk_audit_logs_device_id', 'audit_logs', type_='foreignkey')
    
    # 修改主键类型从String到Integer
    op.alter_column('devices', 'id',
                    existing_type=sa.String(50),
                    type_=sa.Integer(),
                    existing_nullable=False,
                    autoincrement=True)
    
    # 重新创建外键约束
    op.create_foreign_key('fk_rentals_device_id', 'rentals', 'devices', ['device_id'], ['id'])
    op.create_foreign_key('fk_audit_logs_device_id', 'audit_logs', 'devices', ['device_id'], ['id'])
    
    # 3. 修改devices表 - 删除不需要的字段
    op.drop_column('devices', 'type')
    op.drop_column('devices', 'model')
    op.drop_column('devices', 'brand')
    op.drop_column('devices', 'condition')
    op.drop_column('devices', 'purchase_date')
    op.drop_column('devices', 'purchase_price')
    op.drop_column('devices', 'current_value')
    op.drop_column('devices', 'daily_rate')
    op.drop_column('devices', 'weekly_rate')
    op.drop_column('devices', 'monthly_rate')
    op.drop_column('devices', 'description')
    op.drop_column('devices', 'specifications')
    op.drop_column('devices', 'notes')
    
    # 4. 修改rentals表 - 删除不需要的字段
    op.drop_column('rentals', 'customer_email')
    op.drop_column('rentals', 'customer_company')
    op.drop_column('rentals', 'purpose')
    op.drop_column('rentals', 'daily_rate')
    op.drop_column('rentals', 'total_cost')
    op.drop_column('rentals', 'deposit')
    op.drop_column('rentals', 'created_by')
    op.drop_column('rentals', 'approved_by')
    op.drop_column('rentals', 'approved_at')
    op.drop_column('rentals', 'notes')
    op.drop_column('rentals', 'deposit')
    op.drop_column('rentals', 'return_notes')
    
    # 5. 修改audit_logs表 - 删除user_id字段
    op.drop_column('audit_logs', 'user_id')


def downgrade():
    """回滚数据库结构"""
    
    # 1. 重新创建users表
    op.create_table('users',
        sa.Column('id', sa.String(50), nullable=False),
        sa.Column('username', sa.String(80), nullable=False),
        sa.Column('email', sa.String(120), nullable=False),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('password_hash', sa.String(128), nullable=True),
        sa.Column('full_name', sa.String(100), nullable=True),
        sa.Column('department', sa.String(50), nullable=True),
        sa.Column('position', sa.String(50), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('is_admin', sa.Boolean(), nullable=True),
        sa.Column('last_login', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
        sa.UniqueConstraint('username')
    )
    
    # 2. 重新添加devices表的字段
    op.add_column('devices', sa.Column('type', sa.String(50), nullable=True))
    op.add_column('devices', sa.Column('model', sa.String(100), nullable=True))
    op.add_column('devices', sa.Column('brand', sa.String(50), nullable=True))
    op.add_column('devices', sa.Column('condition', sa.Enum('excellent', 'good', 'fair', 'poor', name='device_condition'), nullable=True))
    op.add_column('devices', sa.Column('purchase_date', sa.Date(), nullable=True))
    op.add_column('devices', sa.Column('purchase_price', sa.Decimal(10, 2), nullable=True))
    op.add_column('devices', sa.Column('current_value', sa.Decimal(10, 2), nullable=True))
    op.add_column('devices', sa.Column('daily_rate', sa.Decimal(8, 2), nullable=True))
    op.add_column('devices', sa.Column('weekly_rate', sa.Decimal(8, 2), nullable=True))
    op.add_column('devices', sa.Column('monthly_rate', sa.Decimal(8, 2), nullable=True))
    op.add_column('devices', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('devices', sa.Column('specifications', sa.JSON(), nullable=True))
    op.add_column('devices', sa.Column('notes', sa.Text(), nullable=True))
    
    # 3. 重新添加rentals表的字段
    op.add_column('rentals', sa.Column('customer_email', sa.String(100), nullable=True))
    op.add_column('rentals', sa.Column('customer_company', sa.String(100), nullable=True))
    op.add_column('rentals', sa.Column('purpose', sa.Text(), nullable=True))
    op.add_column('rentals', sa.Column('daily_rate', sa.Decimal(8, 2), nullable=True))
    op.add_column('rentals', sa.Column('total_cost', sa.Decimal(10, 2), nullable=True))
    op.add_column('rentals', sa.Column('deposit', sa.Decimal(8, 2), nullable=True))
    op.add_column('rentals', sa.Column('created_by', sa.String(50), nullable=True))
    op.add_column('rentals', sa.Column('approved_by', sa.String(50), nullable=True))
    op.add_column('rentals', sa.Column('approved_at', sa.DateTime(), nullable=True))
    op.add_column('rentals', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('rentals', sa.Column('return_notes', sa.Text(), nullable=True))
    
    # 4. 重新添加audit_logs表的user_id字段
    op.add_column('audit_logs', sa.Column('user_id', sa.String(50), nullable=True))
    op.create_foreign_key('fk_audit_logs_user_id', 'audit_logs', 'users', ['user_id'], ['id'])
    
    # 5. 恢复devices表主键类型
    op.alter_column('devices', 'id',
                    existing_type=sa.Integer(),
                    type_=sa.String(50),
                    existing_nullable=False,
                    autoincrement=False)
