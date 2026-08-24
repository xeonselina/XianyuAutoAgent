"""add tenant database identity anchor

Revision ID: 20260822_db_identity
Revises: 20260807_damage_notes
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_db_identity"
down_revision = "20260807_damage_notes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "database_identity",
        sa.Column(
            "singleton_key",
            sa.SmallInteger(),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("database_uuid", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("schema_generation", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "singleton_key = 1",
            name="ck_database_identity_singleton_key",
        ),
        sa.CheckConstraint(
            "schema_generation >= 1",
            name="ck_database_identity_schema_generation_positive",
        ),
        sa.PrimaryKeyConstraint("singleton_key"),
        sa.UniqueConstraint(
            "database_uuid",
            name="uq_database_identity_database_uuid",
        ),
    )


def downgrade():
    op.drop_table("database_identity")
