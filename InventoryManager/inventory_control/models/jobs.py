"""Durable control-plane job and system-outbox records."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from inventory_control.sql_defaults import MicrosecondCurrentTimestamp

from .base import ControlBase


BACKGROUND_JOB_STATUSES = (
    "pending",
    "leased",
    "provider_submitting",
    "suspension_blocked",
    "needs_review",
    "recovery_review",
    "succeeded",
    "failed",
    "dead_letter",
    "cancelled",
)

CONTROL_OUTBOX_STATES = (
    "pending",
    "leased",
    "succeeded",
    "cancelled",
    "recovery_quarantined",
)

JOB_PROTOCOL_TIMESTAMP_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)


def _new_uuid() -> str:
    return str(uuid4())


class BackgroundJob(ControlBase):
    __tablename__ = "background_jobs"
    __table_args__ = (
        sa.UniqueConstraint(
            "tenant_id",
            "job_type",
            "resource_key",
            "idempotency_key",
            name="uq_background_jobs_effective_idempotency",
        ),
        sa.CheckConstraint(
            "status IN ("
            + ", ".join(f"'{status}'" for status in BACKGROUND_JOB_STATUSES)
            + ")",
            name="status_valid",
        ),
        sa.CheckConstraint("priority >= 0", name="priority_nonnegative"),
        sa.CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        sa.CheckConstraint("max_attempts >= 1", name="max_attempts_positive"),
        sa.CheckConstraint(
            "execution_generation >= 0", name="execution_generation_nonnegative"
        ),
        sa.CheckConstraint(
            "((status IN ('leased', 'provider_submitting') "
            "AND lease_owner IS NOT NULL AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(status NOT IN ('leased', 'provider_submitting') "
            "AND lease_owner IS NULL AND lease_token IS NULL "
            "AND lease_expires_at IS NULL))",
            name="lease_matches_status",
        ),
        sa.Index(
            "ix_background_jobs_claim",
            "status",
            "available_at",
            "priority",
            "created_at",
        ),
        sa.Index("ix_background_jobs_lease_expiry", "status", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    tenant_access_version: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    job_type: Mapped[str] = mapped_column(sa.String(96), nullable=False)
    resource_key: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    requested_by_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    requested_by_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    request_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    priority: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    status: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, server_default=sa.text("'pending'")
    )
    attempts: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("3")
    )
    execution_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("0")
    )
    available_at: Mapped[datetime] = mapped_column(
        JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=False
    )
    not_after: Mapped[datetime | None] = mapped_column(
        JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
    lease_owner: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
    blocked_reason_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    blocked_at: Mapped[datetime | None] = mapped_column(
        JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
    review_reason_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        JOB_PROTOCOL_TIMESTAMP_TYPE,
        nullable=False,
        server_default=MicrosecondCurrentTimestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        JOB_PROTOCOL_TIMESTAMP_TYPE,
        nullable=False,
        server_default=MicrosecondCurrentTimestamp(),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )


class ControlOutboxEvent(ControlBase):
    __tablename__ = "control_outbox_events"
    __table_args__ = (
        sa.UniqueConstraint(
            "source_type",
            "source_uuid",
            "source_generation",
            "event_type",
            "idempotency_key",
            name="uq_control_outbox_events_effective_idempotency",
        ),
        sa.CheckConstraint(
            "state IN ("
            + ", ".join(f"'{state}'" for state in CONTROL_OUTBOX_STATES)
            + ")",
            name="state_valid",
        ),
        sa.CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        sa.CheckConstraint("max_attempts >= 1", name="max_attempts_positive"),
        sa.CheckConstraint("source_generation >= 1", name="source_generation_positive"),
        sa.CheckConstraint(
            "execution_generation >= 0", name="execution_generation_nonnegative"
        ),
        sa.CheckConstraint(
            "((state = 'leased' AND lease_owner IS NOT NULL "
            "AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'leased' AND lease_owner IS NULL "
            "AND lease_token IS NULL AND lease_expires_at IS NULL))",
            name="lease_matches_state",
        ),
        sa.Index(
            "ix_control_outbox_events_claim",
            "state",
            "available_at",
            "created_at",
        ),
        sa.Index(
            "ix_control_outbox_events_lease_expiry", "state", "lease_expires_at"
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=True,
    )
    tenant_access_version: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    source_type: Mapped[str] = mapped_column(sa.String(96), nullable=False)
    source_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    source_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String(96), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    state: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, server_default=sa.text("'pending'")
    )
    attempts: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("10")
    )
    execution_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("0")
    )
    available_at: Mapped[datetime] = mapped_column(
        JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=False
    )
    not_after: Mapped[datetime | None] = mapped_column(
        JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
    lease_owner: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    result_digest_version: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True
    )
    result_digest: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    result_mac: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        JOB_PROTOCOL_TIMESTAMP_TYPE,
        nullable=False,
        server_default=MicrosecondCurrentTimestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        JOB_PROTOCOL_TIMESTAMP_TYPE,
        nullable=False,
        server_default=MicrosecondCurrentTimestamp(),
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
