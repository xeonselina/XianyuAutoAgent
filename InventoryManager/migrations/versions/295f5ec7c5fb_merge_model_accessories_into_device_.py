"""merge model_accessories into device_models

Revision ID: 295f5ec7c5fb
Revises: a514ad030209
Create Date: 2025-10-12 08:34:42.327822

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '295f5ec7c5fb'
down_revision = 'a514ad030209'
branch_labels = None
depends_on = None


def upgrade():
    """
    合并 model_accessories 表到 device_models 表

    1. 在 device_models 表添加新字段
    2. 将 model_accessories 数据迁移到 device_models
    3. 删除 model_accessories 表
    """
    connection = op.get_bind()

    # 1. 在 device_models 表中添加新字段
    with op.batch_alter_table('device_models', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_accessory', sa.Boolean(), default=False, nullable=False, server_default='0', comment='是否为附件'))
        batch_op.add_column(sa.Column('parent_model_id', sa.Integer(), sa.ForeignKey('device_models.id'), nullable=True, comment='主设备型号ID（如果是附件）'))

    # 2. 将 model_accessories 的数据迁移到 device_models
    # 查询所有 model_accessories 记录
    accessories = connection.execute(text("""
        SELECT
            id, model_id, accessory_name, accessory_description,
            accessory_value, is_active, created_at, updated_at
        FROM model_accessories
    """)).fetchall()

    # 为每个附件创建一个新的 device_model 记录
    for acc in accessories:
        connection.execute(text("""
            INSERT INTO device_models
            (name, display_name, description, is_active, is_accessory,
             parent_model_id, device_value, created_at, updated_at)
            VALUES
            (:name, :display_name, :description, :is_active, TRUE,
             :parent_model_id, :value, :created_at, :updated_at)
        """), {
            'name': f"{acc[2]}_{acc[0]}",  # accessory_name + id 确保唯一性
            'display_name': acc[2],  # accessory_name
            'description': acc[3],  # accessory_description
            'is_active': acc[5],  # is_active
            'parent_model_id': acc[1],  # model_id
            'value': acc[4],  # accessory_value
            'created_at': acc[6],  # created_at
            'updated_at': acc[7]  # updated_at
        })

    # 3. 删除 model_accessories 表
    op.drop_table('model_accessories')


def downgrade():
    """
    回滚：将 device_models 表中的附件数据恢复到 model_accessories 表
    """
    connection = op.get_bind()

    # 1. 重新创建 model_accessories 表
    op.create_table('model_accessories',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, comment='关系ID'),
        sa.Column('model_id', sa.Integer(), sa.ForeignKey('device_models.id'), nullable=False, comment='主设备型号ID'),
        sa.Column('accessory_name', sa.String(100), nullable=False, comment='附件名称'),
        sa.Column('accessory_description', sa.Text(), nullable=True, comment='附件描述'),
        sa.Column('accessory_value', mysql.DECIMAL(precision=10, scale=2), nullable=True, comment='附件价值'),
        sa.Column('is_required', sa.Boolean(), default=False, comment='是否必需附件'),
        sa.Column('is_active', sa.Boolean(), default=True, comment='是否启用'),
        sa.Column('created_at', sa.DateTime(), default=sa.func.utcnow(), comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), default=sa.func.utcnow(), onupdate=sa.func.utcnow(), comment='更新时间')
    )

    # 2. 将 is_accessory=True 的 device_model 记录迁移回 model_accessories
    accessory_models = connection.execute(text("""
        SELECT
            id, display_name, description, device_value,
            parent_model_id, is_active, created_at, updated_at
        FROM device_models
        WHERE is_accessory = TRUE
    """)).fetchall()

    for acc in accessory_models:
        connection.execute(text("""
            INSERT INTO model_accessories
            (model_id, accessory_name, accessory_description, accessory_value,
             is_required, is_active, created_at, updated_at)
            VALUES
            (:model_id, :name, :description, :value, FALSE,
             :is_active, :created_at, :updated_at)
        """), {
            'model_id': acc[4],  # parent_model_id
            'name': acc[1],  # display_name
            'description': acc[2],  # description
            'value': acc[3],  # device_value
            'is_active': acc[5],  # is_active
            'created_at': acc[6],  # created_at
            'updated_at': acc[7]  # updated_at
        })

    # 3. 删除 is_accessory=True 的 device_model 记录
    connection.execute(text("DELETE FROM device_models WHERE is_accessory = TRUE"))

    # 4. 删除新添加的字段
    with op.batch_alter_table('device_models', schema=None) as batch_op:
        batch_op.drop_constraint('device_models_ibfk_1', type_='foreignkey')
        batch_op.drop_column('parent_model_id')
        batch_op.drop_column('is_accessory')
