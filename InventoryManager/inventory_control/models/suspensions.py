"""Durable, non-secret D52 tenant-suspension facts.

These records contain only control-plane authorization, fencing, and safe
outcome facts.  Physical database-account work is represented by the existing
control outbox and is deliberately not claimed by either table.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from inventory_control.sql_defaults import MicrosecondCurrentTimestamp

from .base import ControlBase


MICROSECOND_DATETIME = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)
SHA256_DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")


def _new_uuid() -> str:
    return str(uuid4())


class TenantSuspension(ControlBase):
    """One D52 aggregate; only ``resolved`` releases its active-tenant key."""

    __tablename__ = "tenant_suspensions"
    __table_args__ = (
        sa.UniqueConstraint(
            "active_tenant_id",
            name="uq_tenant_suspensions_active_tenant",
        ),
        sa.CheckConstraint(
            "state IN ('freezing', 'active', 'resolving', 'resolved', 'failed')",
            name="state_valid",
        ),
        sa.CheckConstraint(
            "barrier_generation >= 1 AND committed_tenant_row_version >= 1 "
            "AND committed_access_version >= 1 AND row_version >= 1",
            name="versions_positive",
        ),
        sa.CheckConstraint(
            "((state = 'freezing' AND frozen_at IS NULL "
            "AND resolving_at IS NULL AND resolved_at IS NULL "
            "AND safe_failure_code IS NULL) OR "
            "(state = 'active' AND frozen_at IS NOT NULL "
            "AND resolving_at IS NULL AND resolved_at IS NULL "
            "AND safe_failure_code IS NULL) OR "
            "(state = 'resolving' AND frozen_at IS NOT NULL "
            "AND resolving_at IS NOT NULL AND resolved_at IS NULL "
            "AND safe_failure_code IS NULL) OR "
            "(state = 'resolved' AND frozen_at IS NOT NULL "
            "AND resolving_at IS NOT NULL AND resolved_at IS NOT NULL "
            "AND safe_failure_code IS NULL) OR "
            "(state = 'failed' AND resolved_at IS NULL "
            "AND safe_failure_code IS NOT NULL))",
            name="state_facts_complete",
        ),
        sa.Index(
            "ix_tenant_suspensions_tenant_state",
            "tenant_id",
            "state",
            "barrier_generation",
        ),
    )

    id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "tenants.id",
            name="fk_tenant_suspensions_tenant",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    active_tenant_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.Computed(
            "CASE WHEN state = 'resolved' THEN NULL ELSE tenant_id END",
            persisted=True,
        ),
        nullable=True,
    )
    initial_reason_code: Mapped[str] = mapped_column(
        sa.String(64), nullable=False
    )
    initial_safe_note: Mapped[str | None] = mapped_column(
        sa.String(500), nullable=True
    )
    barrier_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    committed_tenant_row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    committed_access_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(
        MICROSECOND_DATETIME, nullable=False
    )
    frozen_at: Mapped[datetime | None] = mapped_column(
        MICROSECOND_DATETIME, nullable=True
    )
    resolving_at: Mapped[datetime | None] = mapped_column(
        MICROSECOND_DATETIME, nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        MICROSECOND_DATETIME, nullable=True
    )
    safe_failure_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        MICROSECOND_DATETIME,
        nullable=False,
        server_default=MicrosecondCurrentTimestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        MICROSECOND_DATETIME,
        nullable=False,
        server_default=MicrosecondCurrentTimestamp(),
    )


class TenantSuspensionAction(ControlBase):
    """Immutable authorization identity plus mutable reducer outcome."""

    __tablename__ = "tenant_suspension_actions"
    __table_args__ = (
        sa.UniqueConstraint(
            "suspension_id",
            "generation",
            name="uq_suspension_actions_suspension_generation",
        ),
        sa.UniqueConstraint(
            "suspension_id",
            "idempotency_key",
            name="uq_suspension_actions_suspension_idempotency",
        ),
        sa.CheckConstraint(
            "direction IN ('freeze', 'resolve', 'enforce_locked')",
            name="direction_valid",
        ),
        sa.CheckConstraint(
            "actor_type IN ('platform_admin', 'system')",
            name="actor_type_valid",
        ),
        sa.CheckConstraint(
            "authorization_source IN "
            "('user_step_up', 'deletion_request', 'dr_recovery')",
            name="authorization_source_valid",
        ),
        sa.CheckConstraint(
            "state IN ('requested', 'running', 'succeeded', "
            "'superseded', 'failed')",
            name="state_valid",
        ),
        sa.CheckConstraint(
            "recent_step_up_method IS NULL OR "
            "recent_step_up_method IN ('totp', 'recovery_code')",
            name="step_up_method_valid",
        ),
        sa.CheckConstraint(
            "generation >= 1 AND expected_suspension_row_version >= 0 "
            "AND expected_tenant_row_version >= 1 "
            "AND expected_access_version >= 1 AND row_version >= 1",
            name="versions_valid",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 32",
            name="request_digest_length",
        ),
        sa.CheckConstraint(
            "((direction IN ('freeze', 'resolve') "
            "AND actor_type = 'platform_admin' "
            "AND platform_admin_id IS NOT NULL "
            "AND platform_session_id IS NOT NULL "
            "AND recent_step_up_method IS NOT NULL "
            "AND recent_step_up_at IS NOT NULL "
            "AND authorization_source = 'user_step_up' "
            "AND authorization_source_uuid IS NULL) OR "
            "(direction = 'enforce_locked' AND actor_type = 'system' "
            "AND platform_admin_id IS NULL AND platform_session_id IS NULL "
            "AND recent_step_up_method IS NULL AND recent_step_up_at IS NULL "
            "AND authorization_source IN ('deletion_request', 'dr_recovery') "
            "AND authorization_source_uuid IS NOT NULL))",
            name="authority_provenance_complete",
        ),
        sa.CheckConstraint(
            "((state IN ('succeeded', 'superseded', 'failed') "
            "AND completed_at IS NOT NULL AND safe_outcome_code IS NOT NULL) "
            "OR (state IN ('requested', 'running') "
            "AND completed_at IS NULL AND safe_outcome_code IS NULL))",
            name="terminal_outcome_complete",
        ),
        sa.CheckConstraint(
            "((state = 'failed' AND safe_failure_code IS NOT NULL) OR "
            "(state <> 'failed' AND safe_failure_code IS NULL))",
            name="failure_state_complete",
        ),
        sa.ForeignKeyConstraint(
            ["suspension_id"],
            ["tenant_suspensions.id"],
            name="fk_suspension_actions_suspension",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["platform_admin_id"],
            ["platform_admins.id"],
            name="fk_suspension_actions_admin",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["platform_session_id"],
            ["platform_admin_sessions.id"],
            name="fk_suspension_actions_session",
            ondelete="RESTRICT",
        ),
        sa.Index(
            "ix_suspension_actions_suspension_state",
            "suspension_id",
            "state",
            "generation",
        ),
    )

    id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    suspension_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    direction: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    actor_type: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    platform_admin_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    platform_session_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    recent_step_up_method: Mapped[str | None] = mapped_column(
        sa.String(24), nullable=True
    )
    recent_step_up_at: Mapped[datetime | None] = mapped_column(
        MICROSECOND_DATETIME, nullable=True
    )
    authorization_source: Mapped[str] = mapped_column(
        sa.String(32), nullable=False
    )
    authorization_source_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    safe_correlation: Mapped[str | None] = mapped_column(
        sa.String(160), nullable=True
    )
    reason_code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    safe_note: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(
        sa.String(160), nullable=False
    )
    request_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    expected_suspension_row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    expected_tenant_row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    expected_access_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    state: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    safe_outcome_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    safe_failure_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    requested_at: Mapped[datetime] = mapped_column(
        MICROSECOND_DATETIME, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        MICROSECOND_DATETIME, nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        MICROSECOND_DATETIME, nullable=True
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        MICROSECOND_DATETIME,
        nullable=False,
        server_default=MicrosecondCurrentTimestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        MICROSECOND_DATETIME,
        nullable=False,
        server_default=MicrosecondCurrentTimestamp(),
    )


__all__ = ["TenantSuspension", "TenantSuspensionAction"]
