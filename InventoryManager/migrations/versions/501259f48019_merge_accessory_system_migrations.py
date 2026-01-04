"""merge accessory system migrations

Revision ID: 501259f48019
Revises: 20260104154655, 462f697d4fcb
Create Date: 2026-01-04 19:53:13.856891

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '501259f48019'
down_revision = ('20260104154655', '462f697d4fcb')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
