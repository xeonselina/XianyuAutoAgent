"""Immutable, credential-free audit records for the platform boundary."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .base import ControlBase


def _new_uuid() -> str:
    return str(uuid4())


class PlatformAuditLog(ControlBase):
    __tablename__ = "platform_audit_logs"
    __table_args__ = (
        sa.CheckConstraint(
            "actor_type IN ('platform_admin', 'os_operator', "
            "'cli_break_glass', 'system')",
            name="actor_type_valid",
        ),
        sa.CheckConstraint(
            "access_mode IN ('authentication', 'control', 'tenant_read')",
            name="access_mode_valid",
        ),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'rejected', 'failed', 'rate_limited')",
            name="outcome_valid",
        ),
        sa.CheckConstraint(
            "authentication_factor IS NULL OR authentication_factor IN "
            "('totp', 'recovery_code')",
            name="authentication_factor_valid",
        ),
        sa.CheckConstraint(
            "length(action) BETWEEN 1 AND 64", name="action_present"
        ),
        sa.CheckConstraint(
            "length(safe_reason_code) BETWEEN 1 AND 64",
            name="safe_reason_code_present",
        ),
        sa.CheckConstraint(
            "length(request_id) BETWEEN 1 AND 128",
            name="request_id_present",
        ),
        sa.CheckConstraint(
            "result_count IS NULL OR result_count >= 0",
            name="result_count_nonnegative",
        ),
        sa.CheckConstraint(
            "((actor_type = 'platform_admin' "
            "AND actor_platform_admin_id IS NOT NULL) OR "
            "(actor_type <> 'platform_admin' "
            "AND actor_platform_admin_id IS NULL "
            "AND actor_platform_session_id IS NULL))",
            name="actor_identity_consistent",
        ),
        sa.Index(
            "ix_platform_audit_logs_created", "created_at", "id"
        ),
        sa.Index(
            "ix_platform_audit_logs_target_admin_created",
            "target_platform_admin_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    actor_type: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    actor_platform_admin_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "platform_admins.id",
            name="fk_platform_audit_actor_admin",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    actor_platform_session_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "platform_admin_sessions.id",
            name="fk_platform_audit_actor_session",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    os_operator_reference: Mapped[str | None] = mapped_column(
        sa.String(128), nullable=True
    )
    target_tenant_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    target_resource_type: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    target_resource_id: Mapped[str | None] = mapped_column(
        sa.String(128), nullable=True
    )
    target_platform_admin_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "platform_admins.id",
            name="fk_platform_audit_target_admin",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    route_or_command_template: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )
    action: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    access_mode: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    pii_revealed: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    outcome: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    safe_reason_code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    authentication_factor: Mapped[str | None] = mapped_column(
        sa.String(24), nullable=True
    )
    result_count: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    request_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(
        sa.String(128), nullable=True
    )
    ip_summary: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    user_agent_summary: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )


__all__ = ["PlatformAuditLog"]
