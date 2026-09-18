"""store lens combination choices on device models

Revision ID: 20260830_model_lens_combos
Revises: 20260824_saas_lite_contract
Create Date: 2026-08-30
"""

from alembic import op
import sqlalchemy as sa


revision = "20260830_model_lens_combos"
down_revision = "20260824_saas_lite_contract"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "device_models",
        sa.Column("allowed_lens_combos", sa.Text(), nullable=True),
    )
    op.add_column(
        "device_models",
        sa.Column("default_lens_combo", sa.String(length=30), nullable=True),
    )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE device_models "
            "SET allowed_lens_combos = :allowed, "
            "default_lens_combo = :default_combo "
            "WHERE is_accessory = 0"
        ),
        {
            "allowed": '["lens_200mm", "bare"]',
            "default_combo": "lens_200mm",
        },
    )
    connection.execute(
        sa.text(
            "UPDATE device_models "
            "SET allowed_lens_combos = :allowed, "
            "default_lens_combo = :default_combo "
            "WHERE is_accessory = 0 AND "
            "LOWER(REPLACE(REPLACE(name, ' ', ''), '+', '')) LIKE '%x300u%'"
        ),
        {
            "allowed": (
                '["lens_400mm", "lens_200mm", "bare", "lens_dual"]'
            ),
            "default_combo": "lens_400mm",
        },
    )


def downgrade():
    op.drop_column("device_models", "default_lens_combo")
    op.drop_column("device_models", "allowed_lens_combos")
