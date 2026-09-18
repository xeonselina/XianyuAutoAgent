"""Add atomic same-model multi-device bookings (tenant database)."""
from alembic import op
import sqlalchemy as sa

revision = '20260914_multi_device_booking'
down_revision = '20260824_saas_lite_contract'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('rental_bookings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('xianyu_shop_id', sa.Integer(), sa.ForeignKey('xianyu_shops.id', ondelete='RESTRICT')),
        sa.Column('order_no', sa.String(50)),
        sa.Column('expected_quantity', sa.Integer(), nullable=False),
        sa.Column('total_amount', sa.Numeric(10, 2)),
        sa.Column('quantity_change_reason', sa.Text()),
        sa.Column('xianyu_waybill_no', sa.String(50)),
        sa.UniqueConstraint('xianyu_shop_id', 'order_no', name='uq_booking_shop_order'))
    op.create_table('rental_booking_requests',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('rental_ids', sa.JSON(), nullable=False))
    with op.batch_alter_table('rentals') as batch:
        batch.add_column(sa.Column('booking_id', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_rental_booking', 'rental_bookings', ['booking_id'], ['id'], ondelete='RESTRICT')
        batch.create_index('ix_rentals_booking_id', ['booking_id'])


def downgrade():
    with op.batch_alter_table('rentals') as batch:
        batch.drop_index('ix_rentals_booking_id')
        batch.drop_constraint('fk_rental_booking', type_='foreignkey')
        batch.drop_column('booking_id')
    op.drop_table('rental_booking_requests')
    op.drop_table('rental_bookings')
