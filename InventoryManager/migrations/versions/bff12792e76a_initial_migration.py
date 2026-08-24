"""Initial migration

Revision ID: bff12792e76a
Revises:
Create Date: 2025-09-10 15:04:12.498249

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bff12792e76a'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    existing_tables = set(sa.inspect(connection).get_table_names())

    # The original deployment pre-created these three tables with init.sql.
    # New tenant databases are empty, so reproduce that historical baseline
    # here before applying the original incremental migration.
    if 'devices' not in existing_tables:
        op.create_table(
            'devices',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('name', sa.String(length=100), nullable=False),
            sa.Column('serial_number', sa.String(length=100), nullable=True),
            sa.Column(
                'status',
                sa.Enum(
                    'idle', 'pending_ship', 'renting', 'pending_return',
                    'returned', 'offline', name='device_status'
                ),
                nullable=True,
                server_default='idle',
            ),
            sa.Column('location', sa.String(length=100), nullable=True),
            sa.Column(
                'created_at',
                sa.DateTime(),
                nullable=True,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column(
                'updated_at',
                sa.DateTime(),
                nullable=True,
                server_default=sa.func.current_timestamp(),
            ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('serial_number'),
        )
        op.create_index('idx_devices_status', 'devices', ['status'])
        existing_tables.add('devices')

    if 'rentals' not in existing_tables:
        op.create_table(
            'rentals',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('device_id', sa.Integer(), nullable=False),
            sa.Column('start_date', sa.Date(), nullable=False),
            sa.Column('end_date', sa.Date(), nullable=False),
            sa.Column('ship_out_time', sa.DateTime(), nullable=True),
            sa.Column('ship_in_time', sa.DateTime(), nullable=True),
            sa.Column('customer_name', sa.String(length=100), nullable=False),
            sa.Column('customer_phone', sa.String(length=20), nullable=True),
            sa.Column('destination', sa.Text(), nullable=True),
            sa.Column(
                'ship_out_tracking_no',
                sa.String(length=50),
                nullable=True,
            ),
            sa.Column(
                'ship_in_tracking_no',
                sa.String(length=50),
                nullable=True,
            ),
            sa.Column(
                'status',
                sa.Enum(
                    'pending', 'active', 'completed', 'cancelled',
                    'overdue', name='rental_status'
                ),
                nullable=True,
                server_default='pending',
            ),
            sa.Column(
                'created_at',
                sa.DateTime(),
                nullable=True,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column(
                'updated_at',
                sa.DateTime(),
                nullable=True,
                server_default=sa.func.current_timestamp(),
            ),
            sa.ForeignKeyConstraint(
                ['device_id'], ['devices.id'], ondelete='CASCADE'
            ),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('idx_rentals_device_id', 'rentals', ['device_id'])
        op.create_index(
            'idx_rentals_dates',
            'rentals',
            ['start_date', 'end_date'],
        )
        op.create_index('idx_rentals_status', 'rentals', ['status'])
        op.create_index(
            'idx_rentals_tracking',
            'rentals',
            ['ship_out_tracking_no', 'ship_in_tracking_no'],
        )
        existing_tables.add('rentals')

    if 'audit_logs' not in existing_tables:
        op.create_table(
            'audit_logs',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('device_id', sa.Integer(), nullable=True),
            sa.Column('rental_id', sa.Integer(), nullable=True),
            sa.Column('action', sa.String(length=50), nullable=False),
            sa.Column('old_value', sa.Text(), nullable=True),
            sa.Column('new_value', sa.Text(), nullable=True),
            sa.Column('user_id', sa.String(length=100), nullable=True),
            sa.Column(
                'timestamp',
                sa.DateTime(),
                nullable=True,
                server_default=sa.func.current_timestamp(),
            ),
            sa.ForeignKeyConstraint(
                ['device_id'], ['devices.id'], ondelete='SET NULL'
            ),
            sa.ForeignKeyConstraint(
                ['rental_id'], ['rentals.id'], ondelete='SET NULL'
            ),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            'idx_audit_logs_device_id',
            'audit_logs',
            ['device_id'],
        )
        op.create_index(
            'idx_audit_logs_rental_id',
            'audit_logs',
            ['rental_id'],
        )
        op.create_index(
            'idx_audit_logs_timestamp',
            'audit_logs',
            ['timestamp'],
        )

    existing_tables = set(sa.inspect(connection).get_table_names())
    if 'rental_accessories' not in existing_tables:
        op.create_table(
            'rental_accessories',
            sa.Column(
                'id',
                sa.Integer(),
                autoincrement=True,
                nullable=False,
                comment='关联ID',
            ),
            sa.Column(
                'rental_id',
                sa.Integer(),
                nullable=False,
                comment='租赁ID',
            ),
            sa.Column(
                'device_id',
                sa.Integer(),
                nullable=False,
                comment='附件设备ID',
            ),
            sa.Column(
                'created_at',
                sa.DateTime(),
                nullable=True,
                comment='创建时间',
            ),
            sa.Column(
                'updated_at',
                sa.DateTime(),
                nullable=True,
                comment='更新时间',
            ),
            sa.ForeignKeyConstraint(['device_id'], ['devices.id']),
            sa.ForeignKeyConstraint(['rental_id'], ['rentals.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    device_columns = {
        column['name']
        for column in sa.inspect(connection).get_columns('devices')
    }
    with op.batch_alter_table('devices', schema=None) as batch_op:
        if 'model' not in device_columns:
            batch_op.add_column(
                sa.Column(
                    'model',
                    sa.String(length=50),
                    nullable=False,
                    comment='设备型号',
                    default='x200u',
                )
            )
        if 'is_accessory' not in device_columns:
            batch_op.add_column(
                sa.Column(
                    'is_accessory',
                    sa.Boolean(),
                    nullable=True,
                    comment='是否为附件',
                    default=False,
                )
            )


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.drop_column('is_accessory')
        batch_op.drop_column('model')

    op.drop_table('rental_accessories')
    # ### end Alembic commands ###
