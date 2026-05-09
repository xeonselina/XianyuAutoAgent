"""add_device_lifecycle_management

Revision ID: 001_lifecycle_mgmt
Revises: fdaa742857fe
Create Date: 2026-05-09 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001_lifecycle_mgmt'
down_revision = 'fdaa742857fe'
branch_labels = None
depends_on = None


def upgrade():
    """Add lifecycle management columns to devices table"""
    
    # Create the lifecycle_status enum type
    lifecycle_status_enum = sa.Enum(
        'active', 'sold', 'decommissioned', 'damaged', 'retired',
        name='device_lifecycle_status'
    )
    
    # Add columns to devices table
    with op.batch_alter_table('devices', schema=None) as batch_op:
        # Add lifecycle_status with default 'active'
        batch_op.add_column(
            sa.Column(
                'lifecycle_status',
                lifecycle_status_enum,
                nullable=False,
                default='active',
                server_default='active',
                comment='设备生命周期状态'
            )
        )
        
        # Add lifecycle_reason for optional explanation
        batch_op.add_column(
            sa.Column(
                'lifecycle_reason',
                sa.String(255),
                nullable=True,
                comment='生命周期变更原因'
            )
        )
        
        # Add lifecycle_date to track when status changed
        batch_op.add_column(
            sa.Column(
                'lifecycle_date',
                sa.DateTime,
                nullable=True,
                comment='生命周期状态变更日期'
            )
        )
        
        # Add index on lifecycle_status for faster queries
        batch_op.create_index(
            'idx_devices_lifecycle_status',
            ['lifecycle_status']
        )


def downgrade():
    """Remove lifecycle management columns from devices table"""
    
    with op.batch_alter_table('devices', schema=None) as batch_op:
        # Drop index first
        batch_op.drop_index('idx_devices_lifecycle_status')
        
        # Drop columns
        batch_op.drop_column('lifecycle_date')
        batch_op.drop_column('lifecycle_reason')
        batch_op.drop_column('lifecycle_status')
    
    # Drop enum type
    op.execute('DROP TYPE IF EXISTS device_lifecycle_status')
