"""Create the non-secret platform root-key version registry."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "202608220016"
down_revision = "202608220015"
branch_labels = None
depends_on = None


SHA256_DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")


def upgrade() -> None:
    op.create_table(
        "platform_root_key_versions",
        sa.Column(
            "version",
            sa.BigInteger(),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("fingerprint_sha256", SHA256_DIGEST_TYPE, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "active_slot",
            sa.SmallInteger(),
            sa.Computed(
                "CASE WHEN status = 'active' THEN 1 ELSE NULL END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "activated_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f("ck_platform_root_key_versions_version_positive"),
        ),
        sa.CheckConstraint(
            "length(fingerprint_sha256) = 32",
            name=op.f("ck_platform_root_key_versions_fingerprint_length"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'legacy', 'retired')",
            name=op.f("ck_platform_root_key_versions_status_valid"),
        ),
        sa.CheckConstraint(
            "((status = 'retired' AND retired_at IS NOT NULL) OR "
            "(status IN ('active', 'legacy') AND retired_at IS NULL))",
            name=op.f(
                "ck_platform_root_key_versions_retired_at_matches_status"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "version", name=op.f("pk_platform_root_key_versions")
        ),
        sa.UniqueConstraint(
            "fingerprint_sha256",
            name="uq_root_key_versions_fingerprint",
        ),
        sa.UniqueConstraint(
            "active_slot",
            name="uq_root_key_versions_active_slot",
        ),
    )


def downgrade() -> None:
    op.drop_table("platform_root_key_versions")
