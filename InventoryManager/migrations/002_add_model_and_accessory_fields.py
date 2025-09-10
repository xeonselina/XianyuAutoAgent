"""
Migration: Add model and is_accessory fields to devices table
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column

def upgrade():
    # Add model column with default value
    op.add_column('devices', sa.Column('model', sa.String(50), nullable=False, server_default='x200u'))
    
    # Add is_accessory column with default value
    op.add_column('devices', sa.Column('is_accessory', sa.Boolean(), nullable=False, server_default='false'))
    
    # Update all existing devices to have model='x200u' and is_accessory=False
    devices_table = table('devices',
                         column('id', sa.Integer),
                         column('model', sa.String(50)),
                         column('is_accessory', sa.Boolean))
    
    # Update existing records explicitly
    op.execute(devices_table.update().values(model='x200u', is_accessory=False))

def downgrade():
    # Remove the added columns
    op.drop_column('devices', 'is_accessory')
    op.drop_column('devices', 'model')