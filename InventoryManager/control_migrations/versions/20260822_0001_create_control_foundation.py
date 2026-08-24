"""Create the minimal inventory control foundation.

Revision ID: 202608220001
Revises:
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa


revision = "202608220001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "control_installations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("marker_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_control_installations_row_version_positive",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_control_installations"),
        sa.UniqueConstraint(
            "marker_fingerprint",
            name="uq_control_installations_marker_fingerprint",
        ),
    )
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("slug", sa.String(length=255), nullable=True),
        sa.Column(
            "public_identity_published_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'provisioning'"),
            nullable=False,
        ),
        sa.Column("access_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default=sa.text("'Asia/Shanghai'"),
            nullable=False,
        ),
        sa.Column(
            "locale",
            sa.String(length=16),
            server_default=sa.text("'zh-CN'"),
            nullable=False,
        ),
        sa.Column("settings_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "access_version >= 1",
            name="ck_tenants_access_version_positive",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_tenants_row_version_positive",
        ),
        sa.CheckConstraint(
            "status IN ('provisioning', 'active', 'expired', 'suspending', "
            "'suspended', 'resuming', 'deletion_cooling_off', "
            "'deletion_committing', 'deleted')",
            name="ck_tenants_status_valid",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    op.create_table(
        "tenant_databases",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("database_uuid", sa.String(length=36), nullable=False),
        sa.Column("database_instance_key", sa.String(length=128), nullable=False),
        sa.Column("database_name", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'provisional'"),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(length=128), nullable=True),
        sa.Column("route_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "route_version >= 1",
            name="ck_tenant_databases_route_version_positive",
        ),
        sa.CheckConstraint(
            "status IN ('provisional', 'ready', 'failed', 'retired')",
            name="ck_tenant_databases_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_databases_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_tenant_databases"),
        sa.UniqueConstraint(
            "database_instance_key",
            "database_name",
            name="uq_tenant_databases_instance_name",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "database_uuid",
            name="uq_tenant_databases_tenant_database",
        ),
        sa.UniqueConstraint(
            "database_uuid",
            name="uq_tenant_databases_database_uuid",
        ),
    )
    op.create_table(
        "database_identity_control_records",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("database_uuid", sa.String(length=36), nullable=False),
        sa.Column("expected_schema_generation", sa.BigInteger(), nullable=False),
        sa.Column("observed_schema_generation", sa.BigInteger(), nullable=True),
        sa.Column(
            "identity_created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "expected_schema_generation >= 1",
            name=(
                "ck_database_identity_control_records_"
                "expected_schema_generation_positive"
            ),
        ),
        sa.CheckConstraint(
            "observed_schema_generation IS NULL OR observed_schema_generation >= 1",
            name=(
                "ck_database_identity_control_records_"
                "observed_schema_generation_positive"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "database_uuid"],
            [
                "tenant_databases.tenant_id",
                "tenant_databases.database_uuid",
            ],
            name="fk_database_identity_control_records_route_identity",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", name="pk_database_identity_control_records"
        ),
        sa.UniqueConstraint(
            "database_uuid",
            name="uq_database_identity_control_records_database_uuid",
        ),
    )


def downgrade() -> None:
    op.drop_table("database_identity_control_records")
    op.drop_table("tenant_databases")
    op.drop_table("tenants")
    op.drop_table("control_installations")
