"""Create full-backup lease, attempt, and completed artifact persistence."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from inventory_control.sql_defaults import MicrosecondCurrentTimestamp


revision = "202608220017"
down_revision = "202608220016"
branch_labels = None
depends_on = None


SHA256_DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")
CANONICAL_MANIFEST_TYPE = sa.LargeBinary().with_variant(
    mysql.MEDIUMBLOB(), "mysql"
)
BACKUP_TIMESTAMP_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)


def upgrade() -> None:
    op.create_table(
        "platform_backup_leases",
        sa.Column("lease_key", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column(
            "observed_at",
            BACKUP_TIMESTAMP_TYPE,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.Column("holder_id", sa.String(length=128), nullable=True),
        sa.Column("acquisition_id", sa.String(length=36), nullable=True),
        sa.Column("acquired_at", BACKUP_TIMESTAMP_TYPE, nullable=True),
        sa.Column("expires_at", BACKUP_TIMESTAMP_TYPE, nullable=True),
        sa.Column("last_acquisition_id", sa.String(length=36), nullable=True),
        sa.CheckConstraint(
            "lease_key = 'fleet_full_backup'",
            name=op.f("ck_platform_backup_leases_scope_fixed"),
        ),
        sa.CheckConstraint(
            "status IN ('available', 'held')",
            name=op.f("ck_platform_backup_leases_status_valid"),
        ),
        sa.CheckConstraint(
            "generation >= 0 AND fencing_token >= 0",
            name=op.f("ck_platform_backup_leases_fence_nonnegative"),
        ),
        sa.CheckConstraint(
            "((status = 'available' "
            "AND holder_id IS NULL AND acquisition_id IS NULL "
            "AND acquired_at IS NULL AND expires_at IS NULL) OR "
            "(status = 'held' AND generation >= 1 AND fencing_token >= 1 "
            "AND holder_id IS NOT NULL AND acquisition_id IS NOT NULL "
            "AND acquired_at IS NOT NULL AND expires_at IS NOT NULL "
            "AND last_acquisition_id = acquisition_id))",
            name=op.f("ck_platform_backup_leases_state_complete"),
        ),
        sa.CheckConstraint(
            "acquired_at IS NULL OR expires_at > acquired_at",
            name=op.f("ck_platform_backup_leases_window_valid"),
        ),
        sa.CheckConstraint(
            "status <> 'held' OR "
            "(observed_at >= acquired_at AND observed_at < expires_at)",
            name=op.f("ck_platform_backup_leases_observation_in_window"),
        ),
        sa.PrimaryKeyConstraint(
            "lease_key", name=op.f("pk_platform_backup_leases")
        ),
    )
    lease_table = sa.table(
        "platform_backup_leases",
        sa.column("lease_key", sa.String(length=32)),
        sa.column("status", sa.String(length=16)),
        sa.column("generation", sa.BigInteger()),
        sa.column("fencing_token", sa.BigInteger()),
    )
    op.bulk_insert(
        lease_table,
        [
            {
                "lease_key": "fleet_full_backup",
                "status": "available",
                "generation": 0,
                "fencing_token": 0,
            }
        ],
    )

    op.create_table(
        "backup_attempts",
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("acquisition_id", sa.String(length=36), nullable=False),
        sa.Column("lease_generation", sa.BigInteger(), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("partial_name", sa.String(length=80), nullable=False),
        sa.Column("started_at", BACKUP_TIMESTAMP_TYPE, nullable=False),
        sa.CheckConstraint(
            "lease_generation >= 1 AND fencing_token >= 1",
            name=op.f("ck_backup_attempts_fence_positive"),
        ),
        sa.CheckConstraint(
            "partial_name LIKE 'backup-%.sql.gz.partial'",
            name=op.f("ck_backup_attempts_partial_name_valid"),
        ),
        sa.PrimaryKeyConstraint(
            "attempt_id", name=op.f("pk_backup_attempts")
        ),
        sa.UniqueConstraint(
            "partial_name", name="uq_backup_attempts_partial_name"
        ),
    )

    op.create_table(
        "completed_backup_artifacts",
        sa.Column("artifact_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("published_name", sa.String(length=72), nullable=False),
        sa.Column(
            "canonical_manifest_bytes",
            CANONICAL_MANIFEST_TYPE,
            nullable=False,
        ),
        sa.Column("artifact_sha256", SHA256_DIGEST_TYPE, nullable=False),
        sa.Column("manifest_sha256", SHA256_DIGEST_TYPE, nullable=False),
        sa.Column("record_sha256", SHA256_DIGEST_TYPE, nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("snapshot_at", BACKUP_TIMESTAMP_TYPE, nullable=False),
        sa.Column("completed_at", BACKUP_TIMESTAMP_TYPE, nullable=False),
        sa.Column("installation_id", sa.String(length=36), nullable=False),
        sa.Column("recovery_run_id", sa.String(length=36), nullable=False),
        sa.Column("marker_generation", sa.BigInteger(), nullable=False),
        sa.Column("marker_sha256", SHA256_DIGEST_TYPE, nullable=False),
        sa.CheckConstraint(
            "length(artifact_sha256) = 32 "
            "AND length(manifest_sha256) = 32 "
            "AND length(record_sha256) = 32 "
            "AND length(marker_sha256) = 32",
            name=op.f("ck_completed_backup_artifacts_digest_lengths"),
        ),
        sa.CheckConstraint(
            "length(canonical_manifest_bytes) >= 1 "
            "AND length(canonical_manifest_bytes) <= 1048576",
            name=op.f("ck_completed_backup_artifacts_manifest_size_valid"),
        ),
        sa.CheckConstraint(
            "size_bytes >= 1",
            name=op.f("ck_completed_backup_artifacts_size_positive"),
        ),
        sa.CheckConstraint(
            "completed_at >= snapshot_at",
            name=op.f("ck_completed_backup_artifacts_time_order_valid"),
        ),
        sa.CheckConstraint(
            "marker_generation >= 1",
            name=op.f(
                "ck_completed_backup_artifacts_marker_generation_positive"
            ),
        ),
        sa.CheckConstraint(
            "published_name LIKE 'backup-%.sql.gz'",
            name=op.f("ck_completed_backup_artifacts_published_name_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["backup_attempts.attempt_id"],
            name="fk_completed_backup_artifacts_attempt",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "artifact_id", name=op.f("pk_completed_backup_artifacts")
        ),
        sa.UniqueConstraint(
            "attempt_id", name="uq_completed_backup_artifacts_attempt"
        ),
        sa.UniqueConstraint(
            "published_name", name="uq_completed_backup_artifacts_name"
        ),
    )


def downgrade() -> None:
    op.drop_table("completed_backup_artifacts")
    op.drop_table("backup_attempts")
    op.drop_table("platform_backup_leases")
