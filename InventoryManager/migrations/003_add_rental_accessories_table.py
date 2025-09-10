"""
Migration: Add rental_accessories table
"""

from alembic import op
import sqlalchemy as sa

def upgrade():
    # Create rental_accessories table
    op.create_table('rental_accessories',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True, comment='关联ID'),
        sa.Column('rental_id', sa.Integer, sa.ForeignKey('rentals.id'), nullable=False, comment='租赁ID'),
        sa.Column('device_id', sa.Integer, sa.ForeignKey('devices.id'), nullable=False, comment='附件设备ID'),
        sa.Column('created_at', sa.DateTime, default=sa.func.now(), comment='创建时间'),
        sa.Column('updated_at', sa.DateTime, default=sa.func.now(), onupdate=sa.func.now(), comment='更新时间'),
        sa.Index('idx_rental_accessories_rental_id', 'rental_id'),
        sa.Index('idx_rental_accessories_device_id', 'device_id')
    )

def downgrade():
    # Drop rental_accessories table
    op.drop_table('rental_accessories')