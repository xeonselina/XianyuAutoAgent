"""add express_type_id to rentals

Revision ID: 95a4f16beffe
Revises: cb739080dde2
Create Date: 2025-12-09 21:06:25.622112

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '95a4f16beffe'
down_revision = 'cb739080dde2'
branch_labels = None
depends_on = None


def upgrade():
    # Add express_type_id column to rentals table
    op.add_column('rentals', sa.Column('express_type_id', sa.Integer(), nullable=True, comment='顺丰快递类型ID (1=特快,2=标快,263=半日达)'))

    # Set default value for existing rows
    op.execute("UPDATE rentals SET express_type_id = 2 WHERE express_type_id IS NULL")


def downgrade():
    # Remove express_type_id column
    op.drop_column('rentals', 'express_type_id')
