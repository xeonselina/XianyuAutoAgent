"""add bundled accessory flags

Revision ID: 20260104154655
Revises: cb739080dde2
Create Date: 2026-01-04 15:46:55.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '20260104154655'
down_revision = 'cb739080dde2'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add boolean fields for bundled accessories (handle, lens_mount)
    and migrate historical data from child rentals.
    """
    # 1. Add new boolean columns with default False
    op.add_column('rentals', sa.Column('includes_handle', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('rentals', sa.Column('includes_lens_mount', sa.Boolean(), nullable=False, server_default='0'))
    
    # 2. Create indexes for performance
    op.create_index('idx_rentals_includes_handle', 'rentals', ['includes_handle'])
    op.create_index('idx_rentals_includes_lens_mount', 'rentals', ['includes_lens_mount'])
    
    # 3. Migrate historical data from child rentals to boolean flags
    connection = op.get_bind()
    
    # Get all main rentals (those without a parent)
    main_rentals = connection.execute(
        text("SELECT id FROM rentals WHERE parent_rental_id IS NULL")
    ).fetchall()
    
    print(f"Migrating {len(main_rentals)} main rental records...")
    
    for (rental_id,) in main_rentals:
        # Check if this rental has a handle accessory (child rental)
        handle_exists = connection.execute(
            text("""
                SELECT COUNT(*) FROM rentals r
                JOIN devices d ON r.device_id = d.id
                WHERE r.parent_rental_id = :rental_id
                AND d.name LIKE '%手柄%'
            """),
            {'rental_id': rental_id}
        ).scalar()
        
        if handle_exists > 0:
            connection.execute(
                text("UPDATE rentals SET includes_handle = 1 WHERE id = :rental_id"),
                {'rental_id': rental_id}
            )
        
        # Check if this rental has a lens mount accessory (child rental)
        lens_mount_exists = connection.execute(
            text("""
                SELECT COUNT(*) FROM rentals r
                JOIN devices d ON r.device_id = d.id
                WHERE r.parent_rental_id = :rental_id
                AND d.name LIKE '%镜头支架%'
            """),
            {'rental_id': rental_id}
        ).scalar()
        
        if lens_mount_exists > 0:
            connection.execute(
                text("UPDATE rentals SET includes_lens_mount = 1 WHERE id = :rental_id"),
                {'rental_id': rental_id}
            )
    
    connection.commit()
    print("Data migration completed successfully!")


def downgrade():
    """
    Remove boolean fields. Note: This does NOT restore child rental records.
    Manual restoration from backup may be required if rollback is needed.
    """
    op.drop_index('idx_rentals_includes_lens_mount', table_name='rentals')
    op.drop_index('idx_rentals_includes_handle', table_name='rentals')
    op.drop_column('rentals', 'includes_lens_mount')
    op.drop_column('rentals', 'includes_handle')
