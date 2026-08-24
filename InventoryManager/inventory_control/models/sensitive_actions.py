"""Persistent one-shot authorization records for tenant-sensitive actions."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from .base import ControlBase


def _new_uuid() -> str:
    return str(uuid4())


MAC_SHA256_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")
SENSITIVE_ACTION_TIMESTAMP_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)


class TenantSensitiveActionIntent(ControlBase):
    """A purpose-bound D48 action that never stores its request payload."""

    __tablename__ = "tenant_sensitive_action_intents"
    __table_args__ = (
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_sensitive_action_intents_tenant_idempotency",
        ),
        sa.CheckConstraint(
            "purpose IN ("
            "'integration_credential_change', 'sf_account_bind', "
            "'sf_account_unbind', 'sf_account_rebind', 'admin_invitation', "
            "'grant_admin', 'revoke_admin', 'tenant_delete', "
            "'tenant_delete_cancel', 'phone_change_old', 'phone_change_new')",
            name="purpose_valid",
        ),
        sa.CheckConstraint(
            "status IN ('pending_verification', 'authorized', 'executing', "
            "'succeeded', 'failed', 'expired', 'cancelled')",
            name="status_valid",
        ),
        sa.CheckConstraint(
            "length(action_subtype) BETWEEN 1 AND 64",
            name="action_subtype_present",
        ),
        sa.CheckConstraint(
            "length(target_type) BETWEEN 1 AND 64",
            name="target_type_present",
        ),
        sa.CheckConstraint(
            "length(expected_target_revision) BETWEEN 1 AND 128",
            name="expected_target_revision_present",
        ),
        sa.CheckConstraint(
            "canonicalization_version >= 1",
            name="canonicalization_version_positive",
        ),
        sa.CheckConstraint(
            "context_mac_version >= 1", name="context_mac_version_positive"
        ),
        sa.CheckConstraint(
            "root_key_version >= 1", name="root_key_version_positive"
        ),
        sa.CheckConstraint(
            "length(request_context_mac_sha256) = 32",
            name="request_context_mac_sha256_length",
        ),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 128",
            name="idempotency_key_present",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        sa.CheckConstraint(
            "((status IN ('authorized', 'executing', 'succeeded', 'failed') "
            "AND authorized_at IS NOT NULL) OR "
            "(status IN ('pending_verification', 'expired', 'cancelled'))) ",
            name="authorization_timestamp_matches_status",
        ),
        sa.CheckConstraint(
            "((status = 'executing' AND executing_at IS NOT NULL) OR "
            "status <> 'executing')",
            name="executing_timestamp_matches_status",
        ),
        sa.CheckConstraint(
            "((status IN ('succeeded', 'failed', 'expired', 'cancelled') "
            "AND completed_at IS NOT NULL) OR "
            "(status NOT IN ('succeeded', 'failed', 'expired', 'cancelled') "
            "AND completed_at IS NULL))",
            name="completion_timestamp_matches_status",
        ),
        sa.Index(
            "ix_sensitive_action_intents_tenant_status_expiry",
            "tenant_id",
            "status",
            "expires_at",
        ),
        sa.Index(
            "ix_sensitive_action_intents_actor_created",
            "actor_user_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_user_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_session_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("tenant_user_sessions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    action_subtype: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    target_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    expected_target_revision: Mapped[str] = mapped_column(
        sa.String(128), nullable=False
    )
    canonicalization_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False
    )
    context_mac_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    root_key_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    request_context_mac_sha256: Mapped[bytes] = mapped_column(
        MAC_SHA256_TYPE, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(24),
        nullable=False,
        server_default=sa.text("'pending_verification'"),
    )
    safe_result_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    request_id: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(
        sa.String(128), nullable=True
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        SENSITIVE_ACTION_TIMESTAMP_TYPE, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        SENSITIVE_ACTION_TIMESTAMP_TYPE, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        SENSITIVE_ACTION_TIMESTAMP_TYPE, nullable=False
    )
    authorized_at: Mapped[datetime | None] = mapped_column(
        SENSITIVE_ACTION_TIMESTAMP_TYPE, nullable=True
    )
    executing_at: Mapped[datetime | None] = mapped_column(
        SENSITIVE_ACTION_TIMESTAMP_TYPE, nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        SENSITIVE_ACTION_TIMESTAMP_TYPE, nullable=True
    )


class TenantSensitiveActionIntentChallenge(ControlBase):
    """Maps each intent to its exact primary or phone-change challenges."""

    __tablename__ = "tenant_sensitive_action_intent_challenges"
    __table_args__ = (
        sa.UniqueConstraint(
            "challenge_id", name="uq_sensitive_intent_challenges_challenge"
        ),
        sa.CheckConstraint(
            "challenge_role IN ('primary', 'old_phone', 'new_phone')",
            name="challenge_role_valid",
        ),
    )

    intent_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "tenant_sensitive_action_intents.id", ondelete="RESTRICT"
        ),
        primary_key=True,
    )
    challenge_role: Mapped[str] = mapped_column(
        sa.String(16), primary_key=True
    )
    challenge_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("sms_challenges.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )


__all__ = [
    "TenantSensitiveActionIntent",
    "TenantSensitiveActionIntentChallenge",
]
