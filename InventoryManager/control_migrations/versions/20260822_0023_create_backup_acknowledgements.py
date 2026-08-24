"""Create independent NAS backup and cloud-sync acknowledgement facts."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from inventory_control.sql_defaults import MicrosecondCurrentTimestamp


revision = "202608220023"
down_revision = "202608220022"
branch_labels = None
depends_on = None


SHA256_DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")
ACK_TIMESTAMP_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)


def upgrade() -> None:
    op.create_table(
        "backup_artifact_acknowledgements",
        sa.Column("artifact_id", sa.String(length=36), nullable=False),
        sa.Column("ack_kind", sa.String(length=24), nullable=False),
        sa.Column("manifest_sha256", SHA256_DIGEST_TYPE, nullable=False),
        sa.Column("artifact_sha256", SHA256_DIGEST_TYPE, nullable=False),
        sa.Column("source_generation", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", SHA256_DIGEST_TYPE, nullable=False),
        sa.Column("safe_result", sa.String(length=16), nullable=False),
        sa.Column("reported_at", ACK_TIMESTAMP_TYPE, nullable=False),
        sa.Column(
            "received_at",
            ACK_TIMESTAMP_TYPE,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ack_kind IN ('backup-status-ack', 'sync-status-ack')",
            name=op.f("ck_backup_artifact_acknowledgements_ack_kind_valid"),
        ),
        sa.CheckConstraint(
            "((ack_kind = 'backup-status-ack' AND safe_result = 'verified') OR "
            "(ack_kind = 'sync-status-ack' AND safe_result = 'synced'))",
            name=op.f("ck_backup_artifact_acknowledgements_safe_result_valid"),
        ),
        sa.CheckConstraint(
            "length(manifest_sha256) = 32 "
            "AND length(artifact_sha256) = 32 "
            "AND length(request_digest) = 32",
            name=op.f("ck_backup_artifact_acknowledgements_digest_lengths"),
        ),
        sa.CheckConstraint(
            "source_generation >= 1",
            name=op.f(
                "ck_backup_artifact_acknowledgements_source_generation_positive"
            ),
        ),
        sa.CheckConstraint(
            "length(idempotency_key) >= 1 "
            "AND length(idempotency_key) <= 128",
            name=op.f(
                "ck_backup_artifact_acknowledgements_idempotency_key_length"
            ),
        ),
        sa.CheckConstraint(
            "row_version = 1",
            name=op.f("ck_backup_artifact_acknowledgements_row_version_fixed"),
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["completed_backup_artifacts.artifact_id"],
            name="fk_backup_artifact_acks_completed",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "artifact_id",
            "ack_kind",
            name=op.f("pk_backup_artifact_acknowledgements"),
        ),
        sa.UniqueConstraint(
            "ack_kind",
            "idempotency_key",
            name="uq_backup_artifact_acks_kind_idempotency",
        ),
    )
    op.create_index(
        "ix_backup_artifact_acks_kind_received",
        "backup_artifact_acknowledgements",
        ["ack_kind", "received_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("backup_artifact_acknowledgements")
