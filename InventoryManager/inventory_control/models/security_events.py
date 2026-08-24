"""Minimal immutable tenant authentication security events."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .base import ControlBase


def _new_uuid() -> str:
    return str(uuid4())


class TenantAuthSecurityEvent(ControlBase):
    __tablename__ = "tenant_auth_security_events"
    __table_args__ = (
        sa.CheckConstraint(
            "event_type IN ("
            "'login_session_created', 'login_session_rotated', "
            "'logout_current', 'revoke_target', 'revoke_all', "
            "'session_expired', 'security_invalidated', "
            "'sensitive_challenge_requested', "
            "'sensitive_challenge_verified', "
            "'sensitive_challenge_rejected', "
            "'sensitive_action_committed', "
            "'sensitive_action_rejected')",
            name="event_type_valid",
        ),
        sa.CheckConstraint(
            "length(reason_code) BETWEEN 1 AND 64",
            name="reason_code_present",
        ),
        sa.CheckConstraint(
            "length(request_id) BETWEEN 1 AND 80",
            name="request_id_present",
        ),
        sa.Index(
            "ix_tenant_auth_security_events_user_created",
            "user_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=True,
    )
    user_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_session_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("tenant_user_sessions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    target_session_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("tenant_user_sessions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    target_resource_type: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    target_resource_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    expected_target_revision: Mapped[str | None] = mapped_column(
        sa.String(128), nullable=True
    )
    challenge_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("sms_challenges.id", ondelete="RESTRICT"),
        nullable=True,
    )
    intent_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "tenant_sensitive_action_intents.id",
            name="fk_auth_event_sensitive_intent",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    action_subtype: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    idempotency_reference: Mapped[str | None] = mapped_column(
        sa.String(128), nullable=True
    )
    safe_outcome: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    event_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    request_id: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )


__all__ = ["TenantAuthSecurityEvent"]
