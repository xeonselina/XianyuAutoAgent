"""add device models and accessories tables

Revision ID: b7d7e1188aa0
Revises: consolidated_schema
Create Date: 2025-09-19 23:00:56.278713

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7d7e1188aa0'
down_revision = 'consolidated_schema'
branch_labels = None
depends_on = None


def upgrade():
    # 创建设备型号表
    op.create_table('device_models',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, comment='型号ID'),
        sa.Column('name', sa.String(50), nullable=False, unique=True, comment='型号名称'),
        sa.Column('display_name', sa.String(100), nullable=False, comment='显示名称'),
        sa.Column('description', sa.Text(), nullable=True, comment='型号描述'),
        sa.Column('is_active', sa.Boolean(), default=True, comment='是否启用'),
        sa.Column('created_at', sa.DateTime(), default=sa.func.utcnow(), comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), default=sa.func.utcnow(), onupdate=sa.func.utcnow(), comment='更新时间')
    )

    # 创建型号附件关系表
    op.create_table('model_accessories',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, comment='关系ID'),
        sa.Column('model_id', sa.Integer(), sa.ForeignKey('device_models.id'), nullable=False, comment='主设备型号ID'),
        sa.Column('accessory_name', sa.String(100), nullable=False, comment='附件名称'),
        sa.Column('accessory_description', sa.Text(), nullable=True, comment='附件描述'),
        sa.Column('is_required', sa.Boolean(), default=False, comment='是否必需附件'),
        sa.Column('is_active', sa.Boolean(), default=True, comment='是否启用'),
        sa.Column('created_at', sa.DateTime(), default=sa.func.utcnow(), comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), default=sa.func.utcnow(), onupdate=sa.func.utcnow(), comment='更新时间')
    )

    # 在devices表中添加model_id外键字段
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('model_id', sa.Integer(), sa.ForeignKey('device_models.id'), nullable=True, comment='设备型号ID'))

    # 插入默认的设备型号数据
    from sqlalchemy import text
    connection = op.get_bind()

    # 插入x200u型号
    connection.execute(text("""
        INSERT INTO device_models (name, display_name, description, is_active, created_at, updated_at)
        VALUES ('x200u', 'X200U', '默认设备型号', TRUE, UTC_TIMESTAMP(), UTC_TIMESTAMP())
    """))

    # 获取x200u的ID
    result = connection.execute(text("SELECT id FROM device_models WHERE name = 'x200u'"))
    x200u_id = result.fetchone()[0]

    # 插入x200u手柄附件
    connection.execute(text("""
        INSERT INTO model_accessories (model_id, accessory_name, accessory_description, is_required, is_active, created_at, updated_at)
        VALUES (:model_id, 'x200u手柄', 'X200U专用手柄', FALSE, TRUE, UTC_TIMESTAMP(), UTC_TIMESTAMP())
    """), {'model_id': x200u_id})

    # 更新现有设备的model_id
    connection.execute(text("""
        UPDATE devices
        SET model_id = :model_id
        WHERE model = 'x200u' OR (model IS NULL AND is_accessory = FALSE)
    """), {'model_id': x200u_id})


def downgrade():
    # 删除devices表中的model_id字段
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.drop_constraint('devices_model_id_fkey', type_='foreignkey')
        batch_op.drop_column('model_id')

    # 删除表
    op.drop_table('model_accessories')
    op.drop_table('device_models')
