"""Minimal tenant-user, membership, and server-session control models."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import ControlBase


def _new_uuid() -> str:
    return str(uuid4())


SHA256_DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")


class User(ControlBase):
    __tablename__ = "users"
    __table_args__ = (
        sa.CheckConstraint("phone_region_iso2 = 'CN'", name="phone_region_cn"),
        sa.CheckConstraint(
            "phone_e164 LIKE '+86%' AND length(phone_e164) = 14",
            name="phone_e164_canonical_shape",
        ),
        sa.CheckConstraint(
            "phone_normalization_version >= 1",
            name="phone_normalization_version_positive",
        ),
        sa.CheckConstraint("auth_version >= 1", name="auth_version_positive"),
        sa.CheckConstraint(
            "status IN ('unverified', 'active', 'disabled')",
            name="status_valid",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    phone_region_iso2: Mapped[str] = mapped_column(
        sa.String(2), nullable=False, server_default=sa.text("'CN'")
    )
    phone_e164: Mapped[str] = mapped_column(sa.String(16), nullable=False, unique=True)
    phone_normalization_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False
    )
    phone_metadata_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    phone_verified_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, server_default=sa.text("'unverified'")
    )
    auth_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )

    memberships: Mapped[list[TenantMembership]] = relationship(
        back_populates="user"
    )
    sessions: Mapped[list[TenantUserSession]] = relationship(back_populates="user")


class TenantMembership(ControlBase):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        sa.UniqueConstraint(
            "tenant_id", "user_id", name="uq_tenant_memberships_tenant_user"
        ),
        sa.UniqueConstraint(
            "claimed_user_id", name="uq_tenant_memberships_claimed_user"
        ),
        sa.CheckConstraint(
            "role_key IN ('admin', 'operator')", name="role_key_valid"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled', 'released')", name="status_valid"
        ),
        sa.CheckConstraint(
            "source_type IN ('migration', 'invitation', 'registration')",
            name="source_type_valid",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint(
            "((status = 'released' AND released_at IS NOT NULL) OR "
            "(status <> 'released' AND released_at IS NULL))",
            name="released_at_matches_status",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    role_key: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, server_default=sa.text("'active'")
    )
    source_type: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    source_uuid: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    registration_commit_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    released_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    claimed_user_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.Computed(
            "CASE WHEN status = 'released' THEN NULL ELSE user_id END",
            persisted=True,
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )

    user: Mapped[User] = relationship(back_populates="memberships")


class TenantUserSession(ControlBase):
    __tablename__ = "tenant_user_sessions"
    __table_args__ = (
        sa.UniqueConstraint(
            "created_from_challenge_id",
            name="uq_tenant_sessions_created_from_challenge",
        ),
        sa.UniqueConstraint(
            "rotated_from_session_id",
            name="uq_tenant_sessions_rotated_from_session",
        ),
        sa.UniqueConstraint(
            "replaced_by_session_id",
            name="uq_tenant_sessions_replaced_by_session",
        ),
        sa.CheckConstraint(
            "length(token_digest_sha256) = 32", name="token_digest_sha256_length"
        ),
        sa.CheckConstraint(
            "length(csrf_digest_sha256) = 32", name="csrf_digest_sha256_length"
        ),
        sa.CheckConstraint(
            "auth_version_at_issue >= 1", name="auth_version_at_issue_positive"
        ),
        sa.CheckConstraint(
            "tenant_access_version_at_issue >= 1",
            name="tenant_access_version_at_issue_positive",
        ),
        sa.CheckConstraint("policy_version >= 1", name="policy_version_positive"),
        sa.CheckConstraint("csrf_generation >= 1", name="csrf_generation_positive"),
        sa.CheckConstraint(
            "idle_timeout_seconds >= 1", name="idle_timeout_seconds_positive"
        ),
        sa.CheckConstraint(
            "idle_expires_at <= absolute_expires_at",
            name="idle_before_absolute_expiry",
        ),
        sa.CheckConstraint(
            "((revoked_at IS NULL AND revoked_reason_code IS NULL "
            "AND revoked_by_session_id IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_reason_code IS NOT NULL))",
            name="revocation_fields_consistent",
        ),
        sa.Index(
            "ix_tenant_user_sessions_user_active_expiry",
            "user_id",
            "revoked_at",
            "absolute_expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_from_challenge_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "sms_challenges.id",
            name="fk_tenant_sessions_created_from_challenge",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
    )
    rotated_from_session_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "tenant_user_sessions.id",
            name="fk_tenant_sessions_rotated_from_session",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    replaced_by_session_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "tenant_user_sessions.id",
            name="fk_tenant_sessions_replaced_by_session",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    token_digest_sha256: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False, unique=True
    )
    csrf_digest_sha256: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False, unique=True
    )
    auth_version_at_issue: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    tenant_access_version_at_issue: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    policy_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    csrf_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    idle_timeout_seconds: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    idle_expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    absolute_expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    revoked_reason_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    revoked_by_session_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "tenant_user_sessions.id",
            name="fk_tenant_sessions_revoked_by_session",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    device_name: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    user_agent_summary: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )
    first_ip_summary: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    last_ip_summary: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")
