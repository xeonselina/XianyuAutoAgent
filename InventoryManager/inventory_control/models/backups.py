"""Control-plane persistence records for verified full backups."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from inventory_control.sql_defaults import MicrosecondCurrentTimestamp

from .base import ControlBase


SHA256_DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")
CANONICAL_MANIFEST_TYPE = sa.LargeBinary().with_variant(
    mysql.MEDIUMBLOB(), "mysql"
)
BACKUP_TIMESTAMP_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)


class PlatformBackupLease(ControlBase):
    """The sole fleet-wide full-backup lease row."""

    __tablename__ = "platform_backup_leases"
    __table_args__ = (
        sa.CheckConstraint(
            "lease_key = 'fleet_full_backup'", name="scope_fixed"
        ),
        sa.CheckConstraint(
            "status IN ('available', 'held')", name="status_valid"
        ),
        sa.CheckConstraint(
            "generation >= 0 AND fencing_token >= 0",
            name="fence_nonnegative",
        ),
        sa.CheckConstraint(
            "((status = 'available' "
            "AND holder_id IS NULL AND acquisition_id IS NULL "
            "AND acquired_at IS NULL AND expires_at IS NULL) OR "
            "(status = 'held' AND generation >= 1 AND fencing_token >= 1 "
            "AND holder_id IS NOT NULL AND acquisition_id IS NOT NULL "
            "AND acquired_at IS NOT NULL AND expires_at IS NOT NULL "
            "AND last_acquisition_id = acquisition_id))",
            name="state_complete",
        ),
        sa.CheckConstraint(
            "acquired_at IS NULL OR expires_at > acquired_at",
            name="window_valid",
        ),
        sa.CheckConstraint(
            "status <> 'held' OR "
            "(observed_at >= acquired_at AND observed_at < expires_at)",
            name="observation_in_window",
        ),
    )

    lease_key: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    fencing_token: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        BACKUP_TIMESTAMP_TYPE,
        nullable=False,
        server_default=MicrosecondCurrentTimestamp(),
    )
    holder_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    acquisition_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    acquired_at: Mapped[datetime | None] = mapped_column(
        BACKUP_TIMESTAMP_TYPE, nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        BACKUP_TIMESTAMP_TYPE, nullable=True
    )
    last_acquisition_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )


class BackupAttemptRecord(ControlBase):
    """Immutable attempt bound to the exact live lease fence it observed."""

    __tablename__ = "backup_attempts"
    __table_args__ = (
        sa.UniqueConstraint(
            "partial_name", name="uq_backup_attempts_partial_name"
        ),
        sa.CheckConstraint(
            "lease_generation >= 1 AND fencing_token >= 1",
            name="fence_positive",
        ),
        sa.CheckConstraint(
            "partial_name LIKE 'backup-%.sql.gz.partial'",
            name="partial_name_valid",
        ),
    )

    attempt_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    acquisition_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    lease_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    fencing_token: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    partial_name: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        BACKUP_TIMESTAMP_TYPE, nullable=False
    )


class CompletedBackupArtifactRecord(ControlBase):
    """Immutable verified artifact and its canonical non-secret manifest."""

    __tablename__ = "completed_backup_artifacts"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["backup_attempts.attempt_id"],
            name="fk_completed_backup_artifacts_attempt",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "attempt_id", name="uq_completed_backup_artifacts_attempt"
        ),
        sa.UniqueConstraint(
            "published_name", name="uq_completed_backup_artifacts_name"
        ),
        sa.CheckConstraint(
            "length(artifact_sha256) = 32 "
            "AND length(manifest_sha256) = 32 "
            "AND length(record_sha256) = 32 "
            "AND length(marker_sha256) = 32",
            name="digest_lengths",
        ),
        sa.CheckConstraint(
            "length(canonical_manifest_bytes) >= 1 "
            "AND length(canonical_manifest_bytes) <= 1048576",
            name="manifest_size_valid",
        ),
        sa.CheckConstraint("size_bytes >= 1", name="size_positive"),
        sa.CheckConstraint(
            "completed_at >= snapshot_at", name="time_order_valid"
        ),
        sa.CheckConstraint(
            "marker_generation >= 1", name="marker_generation_positive"
        ),
        sa.CheckConstraint(
            "published_name LIKE 'backup-%.sql.gz'",
            name="published_name_valid",
        ),
    )

    artifact_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    published_name: Mapped[str] = mapped_column(sa.String(72), nullable=False)
    canonical_manifest_bytes: Mapped[bytes] = mapped_column(
        CANONICAL_MANIFEST_TYPE, nullable=False
    )
    artifact_sha256: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    manifest_sha256: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    record_sha256: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(
        BACKUP_TIMESTAMP_TYPE, nullable=False
    )
    completed_at: Mapped[datetime] = mapped_column(
        BACKUP_TIMESTAMP_TYPE, nullable=False
    )
    installation_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    recovery_run_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    marker_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    marker_sha256: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )


class BackupArtifactAcknowledgementRecord(ControlBase):
    """Independent, privacy-minimized NAS backup or cloud-sync success ack."""

    __tablename__ = "backup_artifact_acknowledgements"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["completed_backup_artifacts.artifact_id"],
            name="fk_backup_artifact_acks_completed",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "ack_kind",
            "idempotency_key",
            name="uq_backup_artifact_acks_kind_idempotency",
        ),
        sa.CheckConstraint(
            "ack_kind IN ('backup-status-ack', 'sync-status-ack')",
            name="ack_kind_valid",
        ),
        sa.CheckConstraint(
            "((ack_kind = 'backup-status-ack' AND safe_result = 'verified') OR "
            "(ack_kind = 'sync-status-ack' AND safe_result = 'synced'))",
            name="safe_result_valid",
        ),
        sa.CheckConstraint(
            "length(manifest_sha256) = 32 "
            "AND length(artifact_sha256) = 32 "
            "AND length(request_digest) = 32",
            name="digest_lengths",
        ),
        sa.CheckConstraint(
            "source_generation >= 1", name="source_generation_positive"
        ),
        sa.CheckConstraint(
            "length(idempotency_key) >= 1 "
            "AND length(idempotency_key) <= 128",
            name="idempotency_key_length",
        ),
        sa.CheckConstraint("row_version = 1", name="row_version_fixed"),
        sa.Index(
            "ix_backup_artifact_acks_kind_received",
            "ack_kind",
            "received_at",
        ),
    )

    artifact_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    ack_kind: Mapped[str] = mapped_column(sa.String(24), primary_key=True)
    manifest_sha256: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    artifact_sha256: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    source_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    request_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    safe_result: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    reported_at: Mapped[datetime] = mapped_column(
        BACKUP_TIMESTAMP_TYPE, nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        BACKUP_TIMESTAMP_TYPE,
        nullable=False,
        server_default=MicrosecondCurrentTimestamp(),
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )


__all__ = [
    "BackupArtifactAcknowledgementRecord",
    "BackupAttemptRecord",
    "CompletedBackupArtifactRecord",
    "PlatformBackupLease",
]
