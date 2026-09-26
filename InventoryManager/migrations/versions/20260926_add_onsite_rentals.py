"""Add onsite fulfillment to rentals."""
from alembic import op
import sqlalchemy as sa

revision = '20260926_add_onsite_rentals'
down_revision = '20260914_merge_booking_alerts'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('rentals', sa.Column('fulfillment_mode', sa.String(16), nullable=False, server_default='courier'))
    op.add_column('rentals', sa.Column('onsite_note', sa.Text(), nullable=True))
    op.add_column('rentals', sa.Column('onsite_returned_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('rentals', 'onsite_returned_at')
    op.drop_column('rentals', 'onsite_note')
    op.drop_column('rentals', 'fulfillment_mode')
