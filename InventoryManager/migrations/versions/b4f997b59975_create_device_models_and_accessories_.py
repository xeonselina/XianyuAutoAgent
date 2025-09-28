"""create device models and accessories tables

Revision ID: b4f997b59975
Revises: ecf5c063a38d
Create Date: 2025-09-28 13:23:30.372119

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b4f997b59975'
down_revision = 'ecf5c063a38d'
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy import text
    connection = op.get_bind()

    # 检查 device_models 表是否存在
    result = connection.execute(text("SHOW TABLES LIKE 'device_models'"))
    device_models_exists = result.fetchone() is not None

    if not device_models_exists:
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

    # 检查 model_accessories 表是否存在
    result = connection.execute(text("SHOW TABLES LIKE 'model_accessories'"))
    model_accessories_exists = result.fetchone() is not None

    if not model_accessories_exists:
        # 创建型号附件关系表
        op.create_table('model_accessories',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, comment='关系ID'),
            sa.Column('model_id', sa.Integer(), sa.ForeignKey('device_models.id'), nullable=False, comment='主设备型号ID'),
            sa.Column('accessory_name', sa.String(100), nullable=False, comment='附件名称'),
            sa.Column('accessory_description', sa.Text(), nullable=True, comment='附件描述'),
            sa.Column('is_required', sa.Boolean(), default=False, comment='是否必需附件'),
            sa.Column('is_active', sa.Boolean(), default=True, comment='是否启用'),
            sa.Column('created_at', sa.DateTime(), default=sa.func.utcnow(), comment='创建时间'),
            sa.Column('updated_at', sa.DateTime(), default=sa.func.utcnow(), onupdate=sa.func.utcnow(), comment='更新时间'),
            sa.Column('accessory_value', sa.Numeric(10, 2), nullable=True, comment='附件价值')
        )

    # 检查 devices 表是否有 model_id 字段
    result = connection.execute(text("SHOW COLUMNS FROM devices LIKE 'model_id'"))
    model_id_exists = result.fetchone() is not None

    if not model_id_exists:
        # 在devices表中添加model_id外键字段
        with op.batch_alter_table('devices', schema=None) as batch_op:
            batch_op.add_column(sa.Column('model_id', sa.Integer(), sa.ForeignKey('device_models.id'), nullable=True, comment='设备型号ID'))

    # 检查是否已有默认数据
    result = connection.execute(text("SELECT COUNT(*) FROM device_models WHERE name = 'x200u'"))
    x200u_exists = result.fetchone()[0] > 0

    if not x200u_exists:
        # 插入x200u型号
        connection.execute(text("""
            INSERT INTO device_models (name, display_name, description, is_active, created_at, updated_at)
            VALUES ('x200u', 'X200U', '默认设备型号', TRUE, UTC_TIMESTAMP(), UTC_TIMESTAMP())
        """))

    # 获取x200u的ID
    result = connection.execute(text("SELECT id FROM device_models WHERE name = 'x200u'"))
    x200u_row = result.fetchone()
    if x200u_row:
        x200u_id = x200u_row[0]

        # 检查是否已有手柄附件
        result = connection.execute(text("SELECT COUNT(*) FROM model_accessories WHERE model_id = :model_id AND accessory_name = 'x200u手柄'"), {'model_id': x200u_id})
        accessory_exists = result.fetchone()[0] > 0

        if not accessory_exists:
            # 插入x200u手柄附件
            connection.execute(text("""
                INSERT INTO model_accessories (model_id, accessory_name, accessory_description, is_required, is_active, created_at, updated_at, accessory_value)
                VALUES (:model_id, 'x200u手柄', 'X200U专用手柄', FALSE, TRUE, UTC_TIMESTAMP(), UTC_TIMESTAMP(), 50.00)
            """), {'model_id': x200u_id})

        # 更新现有设备的model_id（只更新还没有model_id的设备）
        connection.execute(text("""
            UPDATE devices
            SET model_id = :model_id
            WHERE (model = 'x200u' OR (model IS NULL AND is_accessory = FALSE)) AND model_id IS NULL
        """), {'model_id': x200u_id})


def downgrade():
    # 删除devices表中的model_id字段
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.drop_constraint('devices_model_id_fkey', type_='foreignkey')
        batch_op.drop_column('model_id')

    # 删除表
    op.drop_table('model_accessories')
    op.drop_table('device_models')
