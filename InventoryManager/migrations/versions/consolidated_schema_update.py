"""Consolidated schema update - replace multiple migrations

Revision ID: consolidated_schema
Revises: bd27d78e7f87
Create Date: 2025-09-12 20:50:00.000000

This migration consolidates several previous migrations:
- Adds parent_rental_id to support rental grouping
- Removes rental_accessories table (replaced by parent-child rental structure)
- Updates device model fields

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'consolidated_schema'
down_revision = 'bd27d78e7f87'
branch_labels = None
depends_on = None


def upgrade():
    """Consolidated schema updates"""
    
    # 1. Add parent_rental_id column to rentals table
    print("Adding parent_rental_id column...")
    with op.batch_alter_table('rentals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('parent_rental_id', sa.Integer(), nullable=True, comment='父租赁记录ID（用于关联主设备和附件）'))
        batch_op.create_foreign_key('fk_rentals_parent_rental_id', 'rentals', ['parent_rental_id'], ['id'])
    
    # 2. Migrate data from rental_accessories table if it exists
    connection = op.get_bind()
    
    # Check if rental_accessories table exists
    inspector = sa.inspect(connection)
    tables = inspector.get_table_names()
    
    if 'rental_accessories' in tables:
        print("Migrating rental_accessories data...")
        
        # Get existing rental_accessories data
        result = connection.execute(text("""
            SELECT ra.rental_id, ra.device_id, r.start_date, r.end_date, r.customer_name, 
                   r.customer_phone, r.destination, r.status, r.ship_out_time, r.ship_in_time
            FROM rental_accessories ra
            JOIN rentals r ON ra.rental_id = r.id
        """))
        
        # Create child rental records for accessories
        for row in result:
            connection.execute(text("""
                INSERT INTO rentals (device_id, start_date, end_date, customer_name, 
                                   customer_phone, destination, status, ship_out_time, 
                                   ship_in_time, parent_rental_id, created_at, updated_at)
                VALUES (:device_id, :start_date, :end_date, :customer_name, 
                       :customer_phone, :destination, :status, :ship_out_time, 
                       :ship_in_time, :parent_rental_id, UTC_TIMESTAMP(), UTC_TIMESTAMP())
            """), {
                'device_id': row.device_id,
                'start_date': row.start_date,
                'end_date': row.end_date,
                'customer_name': row.customer_name,
                'customer_phone': row.customer_phone,
                'destination': row.destination,
                'status': row.status,
                'ship_out_time': row.ship_out_time,
                'ship_in_time': row.ship_in_time,
                'parent_rental_id': row.rental_id
            })
        
        # Drop the rental_accessories table
        print("Dropping rental_accessories table...")
        op.drop_table('rental_accessories')
    
    # 3. Update device model fields for main devices
    print("Updating device model fields...")
    connection.execute(text("""
        UPDATE devices 
        SET model = 'x200u' 
        WHERE (model = '' OR model IS NULL) 
        AND is_accessory = FALSE
    """))


def downgrade():
    """Rollback consolidated changes"""
    
    # 1. Recreate rental_accessories table
    op.create_table('rental_accessories',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, comment='关联ID'),
        sa.Column('rental_id', sa.Integer(), sa.ForeignKey('rentals.id'), nullable=False, comment='租赁ID'),
        sa.Column('device_id', sa.Integer(), sa.ForeignKey('devices.id'), nullable=False, comment='附件设备ID'),
        sa.Column('created_at', sa.DateTime(), default=sa.func.utcnow(), comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), default=sa.func.utcnow(), onupdate=sa.func.utcnow(), comment='更新时间')
    )
    
    # 2. Migrate child rentals back to rental_accessories
    connection = op.get_bind()
    child_rentals = connection.execute(sa.text("""
        SELECT id, device_id, parent_rental_id 
        FROM rentals 
        WHERE parent_rental_id IS NOT NULL
    """))
    
    for rental in child_rentals:
        connection.execute(sa.text("""
            INSERT INTO rental_accessories (rental_id, device_id, created_at, updated_at)
            VALUES (:rental_id, :device_id, UTC_TIMESTAMP(), UTC_TIMESTAMP())
        """), {
            'rental_id': rental.parent_rental_id,
            'device_id': rental.device_id
        })
    
    # Delete child rental records
    connection.execute(sa.text("DELETE FROM rentals WHERE parent_rental_id IS NOT NULL"))
    
    # 3. Remove parent_rental_id column
    with op.batch_alter_table('rentals', schema=None) as batch_op:
        batch_op.drop_constraint('fk_rentals_parent_rental_id', type_='foreignkey')
        batch_op.drop_column('parent_rental_id')
    
    # 4. Revert device model changes
    connection.execute(sa.text("""
        UPDATE devices 
        SET model = '' 
        WHERE model = 'x200u' 
        AND is_accessory = FALSE
    """))