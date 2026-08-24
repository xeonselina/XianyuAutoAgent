"""Fleet-wide schema-operation fencing lease persistence model."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from inventory_control.sql_defaults import MicrosecondCurrentTimestamp

from .base import ControlBase


SCHEMA_OPERATION_TIMESTAMP_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)
SCHEMA_OPERATION_DIGEST_TYPE = sa.LargeBinary(32).with_variant(
    mysql.VARBINARY(32),
    "mysql",
)


class PlatformSchemaOperationLease(ControlBase):
    """The pre-seeded singleton that serializes fleet schema operations."""

    __tablename__ = "platform_schema_operation_leases"
    __table_args__ = (
        sa.CheckConstraint(
            "lease_key = 'fleet_schema_operation'",
            name="scope_fixed",
        ),
        sa.CheckConstraint(
            "state IN ('available', 'held')",
            name="state_valid",
        ),
        sa.CheckConstraint(
            "purpose IS NULL OR purpose IN "
            "('provisioning', 'fleet_migration', 'backup', 'restore', "
            "'deletion', 'account_mutation')",
            name="purpose_valid",
        ),
        sa.CheckConstraint(
            "last_effect IS NULL OR last_effect IN "
            "('claimed', 'renewed', 'released')",
            name="last_effect_valid",
        ),
        sa.CheckConstraint(
            "generation >= 0 AND fencing_token >= 0 AND row_version >= 1",
            name="versions_valid",
        ),
        sa.CheckConstraint(
            "((last_effect IS NULL AND last_request_digest IS NULL) OR "
            "(last_effect IS NOT NULL AND last_request_digest IS NOT NULL "
            "AND length(last_request_digest) = 32))",
            name="request_replay_complete",
        ),
        sa.CheckConstraint(
            "((generation = 0 AND fencing_token = 0 "
            "AND last_claim_id IS NULL AND last_effect IS NULL) OR "
            "(generation >= 1 AND fencing_token >= 1 "
            "AND last_claim_id IS NOT NULL AND last_effect IS NOT NULL))",
            name="generation_lineage_complete",
        ),
        sa.CheckConstraint(
            "((state = 'available' AND owner_id IS NULL AND claim_id IS NULL "
            "AND purpose IS NULL AND acquired_at IS NULL AND expires_at IS NULL "
            "AND (generation = 0 OR last_effect = 'released')) OR "
            "(state = 'held' AND owner_id IS NOT NULL AND claim_id IS NOT NULL "
            "AND purpose IS NOT NULL AND acquired_at IS NOT NULL "
            "AND expires_at IS NOT NULL AND last_claim_id = claim_id "
            "AND last_effect IN ('claimed', 'renewed'))) ",
            name="state_complete",
        ),
        sa.CheckConstraint(
            "acquired_at IS NULL OR expires_at > acquired_at",
            name="window_valid",
        ),
        sa.CheckConstraint(
            "state <> 'held' OR "
            "(observed_at >= acquired_at AND observed_at < expires_at)",
            name="observation_in_window",
        ),
    )

    lease_key: Mapped[str] = mapped_column(sa.String(32), primary_key=True)
    state: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    generation: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        server_default=sa.text("0"),
    )
    fencing_token: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        server_default=sa.text("0"),
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        server_default=sa.text("1"),
    )
    observed_at: Mapped[datetime] = mapped_column(
        SCHEMA_OPERATION_TIMESTAMP_TYPE,
        nullable=False,
        server_default=MicrosecondCurrentTimestamp(),
    )
    owner_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    claim_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    purpose: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    acquired_at: Mapped[datetime | None] = mapped_column(
        SCHEMA_OPERATION_TIMESTAMP_TYPE,
        nullable=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        SCHEMA_OPERATION_TIMESTAMP_TYPE,
        nullable=True,
    )
    last_claim_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        nullable=True,
    )
    last_effect: Mapped[str | None] = mapped_column(
        sa.String(16),
        nullable=True,
    )
    last_request_digest: Mapped[bytes | None] = mapped_column(
        SCHEMA_OPERATION_DIGEST_TYPE,
        nullable=True,
    )


__all__ = ["PlatformSchemaOperationLease"]
