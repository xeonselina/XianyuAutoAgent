"""Create tenant invitation reservations.

Revision ID: 202608220008
Revises: 202608220007
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from inventory_control.sql_defaults import MicrosecondCurrentTimestamp


revision = "202608220008"
down_revision = "202608220007"
branch_labels = None
depends_on = None


INVITATION_TIMESTAMP_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)


def upgrade() -> None:
    op.create_table(
        "tenant_invitations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column(
            "phone_region_iso2",
            sa.String(length=2),
            server_default=sa.text("'CN'"),
            nullable=False,
        ),
        sa.Column("phone_e164", sa.String(length=16), nullable=False),
        sa.Column("phone_normalization_version", sa.Integer(), nullable=False),
        sa.Column("role_key", sa.String(length=16), nullable=False),
        sa.Column(
            "token_hash",
            sa.LargeBinary(length=32).with_variant(mysql.BINARY(32), "mysql"),
            nullable=False,
        ),
        sa.Column(
            "token_generation",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "pending_user_id",
            sa.String(length=36),
            sa.Computed(
                "CASE WHEN status = 'pending' THEN user_id ELSE NULL END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("expires_at", INVITATION_TIMESTAMP_TYPE, nullable=False),
        sa.Column("accepted_at", INVITATION_TIMESTAMP_TYPE, nullable=True),
        sa.Column("superseded_at", INVITATION_TIMESTAMP_TYPE, nullable=True),
        sa.Column("terminal_reason_code", sa.String(length=64), nullable=True),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            INVITATION_TIMESTAMP_TYPE,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            INVITATION_TIMESTAMP_TYPE,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "phone_region_iso2 = 'CN'",
            name="ck_tenant_invitations_phone_region_cn",
        ),
        sa.CheckConstraint(
            "phone_e164 LIKE '+86%' AND length(phone_e164) = 14",
            name="ck_tenant_invitations_phone_e164_canonical_shape",
        ),
        sa.CheckConstraint(
            "phone_normalization_version >= 1",
            name="ck_tenant_invitations_phone_normalization_version_positive",
        ),
        sa.CheckConstraint(
            "role_key IN ('admin', 'operator')",
            name="ck_tenant_invitations_role_key_valid",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired', 'superseded')",
            name="ck_tenant_invitations_status_valid",
        ),
        sa.CheckConstraint(
            "token_generation >= 1",
            name="ck_tenant_invitations_token_generation_positive",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_tenant_invitations_row_version_positive",
        ),
        sa.CheckConstraint(
            "length(token_hash) = 32",
            name="ck_tenant_invitations_token_hash_length",
        ),
        sa.CheckConstraint(
            "((status = 'pending' AND user_id IS NOT NULL) OR "
            "(status <> 'pending' AND user_id IS NULL))",
            name="ck_tenant_invitations_user_matches_pending_status",
        ),
        sa.CheckConstraint(
            "((status = 'accepted' AND accepted_at IS NOT NULL) OR "
            "(status <> 'accepted' AND accepted_at IS NULL))",
            name="ck_tenant_invitations_accepted_at_matches_status",
        ),
        sa.CheckConstraint(
            "((status = 'superseded' AND superseded_at IS NOT NULL) OR "
            "(status <> 'superseded' AND superseded_at IS NULL))",
            name="ck_tenant_invitations_superseded_at_matches_status",
        ),
        sa.CheckConstraint(
            "((status IN ('revoked', 'expired', 'superseded') "
            "AND terminal_reason_code IS NOT NULL) OR "
            "(status IN ('pending', 'accepted') "
            "AND terminal_reason_code IS NULL))",
            name="ck_tenant_invitations_terminal_reason_matches_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_invitations_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_tenant_invitations_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_invitations"),
        sa.UniqueConstraint(
            "tenant_id",
            "pending_user_id",
            name="uq_tenant_invitations_pending_tenant_user",
        ),
        sa.UniqueConstraint(
            "token_hash",
            name="uq_tenant_invitations_token_hash",
        ),
    )
    op.create_index(
        "ix_tenant_invitations_user_status_expiry",
        "tenant_invitations",
        ["user_id", "status", "expires_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_tenant_invitations_tenant_status_expiry",
        "tenant_invitations",
        ["tenant_id", "status", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("tenant_invitations")
