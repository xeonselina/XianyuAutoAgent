"""add lens_combo to rentals and customer search indexes

Revision ID: 20260622_lens_combo
Revises: 0670a790bdd7, 001_lifecycle_mgmt
Create Date: 2026-06-22

新增 rentals.lens_combo 字段，并按机型回填默认值：
  - x300u  -> lens_400mm
  - x200u / x300pro -> lens_200mm

同时确保 rentals.customer_phone 与 rentals.customer_name 有索引，
便于 /api/customers/search 模糊匹配。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260622_lens_combo'
down_revision = ('0670a790bdd7', '001_lifecycle_mgmt')
branch_labels = None
depends_on = None


def _has_index(connection, table, index_name):
    rows = connection.execute(
        sa.text("SHOW INDEX FROM {} WHERE Key_name = :name".format(table)),
        {'name': index_name}
    ).fetchall()
    return len(rows) > 0


def upgrade():
    connection = op.get_bind()

    # 1. 添加 lens_combo 列（先 nullable，便于回填）
    with op.batch_alter_table('rentals', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'lens_combo',
            sa.Enum('lens_400mm', 'lens_200mm', 'bare', 'lens_dual', name='rental_lens_combo'),
            nullable=True,
            comment='镜头组合: lens_400mm=400MM镜头(增距镜) / lens_200mm=200MM镜头 / bare=裸机 / lens_dual=双镜头(仅x300u)'
        ))

    # 2. 按机型回填默认值
    # x300u -> lens_400mm
    connection.execute(sa.text("""
        UPDATE rentals r
        LEFT JOIN devices d ON r.device_id = d.id
        LEFT JOIN device_models dm ON d.model_id = dm.id
        SET r.lens_combo = 'lens_400mm'
        WHERE r.lens_combo IS NULL
          AND (dm.name = 'x300u' OR d.model = 'x300u')
    """))
    # x200u / x300pro -> lens_200mm
    connection.execute(sa.text("""
        UPDATE rentals r
        LEFT JOIN devices d ON r.device_id = d.id
        LEFT JOIN device_models dm ON d.model_id = dm.id
        SET r.lens_combo = 'lens_200mm'
        WHERE r.lens_combo IS NULL
          AND (dm.name IN ('x200u', 'x300pro') OR d.model IN ('x200u', 'x300pro'))
    """))
    # 其他未识别机型兜底
    connection.execute(sa.text(
        "UPDATE rentals SET lens_combo = 'lens_200mm' WHERE lens_combo IS NULL"
    ))

    # 3. 改为 NOT NULL 并设默认值
    with op.batch_alter_table('rentals', schema=None) as batch_op:
        batch_op.alter_column(
            'lens_combo',
            existing_type=sa.Enum('lens_400mm', 'lens_200mm', 'bare', 'lens_dual', name='rental_lens_combo'),
            nullable=False,
            server_default='lens_400mm',
            existing_comment='镜头组合: lens_400mm=400MM镜头(增距镜) / lens_200mm=200MM镜头 / bare=裸机 / lens_dual=双镜头(仅x300u)'
        )

    # 4. 补齐客户搜索相关索引
    if not _has_index(connection, 'rentals', 'idx_rentals_customer_phone'):
        op.create_index('idx_rentals_customer_phone', 'rentals', ['customer_phone'])
    if not _has_index(connection, 'rentals', 'idx_rentals_customer_name'):
        op.create_index('idx_rentals_customer_name', 'rentals', ['customer_name'])


def downgrade():
    connection = op.get_bind()

    if _has_index(connection, 'rentals', 'idx_rentals_customer_name'):
        op.drop_index('idx_rentals_customer_name', table_name='rentals')
    if _has_index(connection, 'rentals', 'idx_rentals_customer_phone'):
        op.drop_index('idx_rentals_customer_phone', table_name='rentals')

    with op.batch_alter_table('rentals', schema=None) as batch_op:
        batch_op.drop_column('lens_combo')

    # 删除枚举类型（MySQL Enum 是列内定义，无需额外处理）
