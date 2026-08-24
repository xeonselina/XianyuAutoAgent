"""Independent platform-administrator identity and factor records."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from .base import ControlBase


def _new_uuid() -> str:
    return str(uuid4())


SHA256_DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")
AES_GCM_NONCE_TYPE = sa.LargeBinary(12).with_variant(mysql.BINARY(12), "mysql")
RECOVERY_FACTOR_TIMESTAMP_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)
PLATFORM_SESSION_TIMESTAMP_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)


class PlatformAdmin(ControlBase):
    __tablename__ = "platform_admins"
    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('setup_pending', 'recovery_pending', 'active', 'disabled')",
            name="status_valid",
        ),
        sa.CheckConstraint(
            "length(username_canonical) BETWEEN 3 AND 64",
            name="username_length_valid",
        ),
        sa.CheckConstraint(
            "username_canonical = lower(username_canonical)",
            name="username_lowercase",
        ),
        sa.CheckConstraint("auth_version >= 1", name="auth_version_positive"),
        sa.CheckConstraint("setup_version >= 1", name="setup_version_positive"),
        sa.CheckConstraint("totp_generation >= 1", name="totp_generation_positive"),
        sa.CheckConstraint(
            "recovery_code_generation >= 1",
            name="recovery_code_generation_positive",
        ),
        sa.CheckConstraint(
            "password_hash_version IS NULL OR password_hash_version >= 1",
            name="password_hash_version_positive",
        ),
        sa.CheckConstraint(
            "((password_hash_encoded IS NULL "
            "AND password_hash_algorithm IS NULL "
            "AND password_hash_version IS NULL) OR "
            "(password_hash_encoded IS NOT NULL "
            "AND password_hash_algorithm IS NOT NULL "
            "AND password_hash_version IS NOT NULL))",
            name="password_hash_fields_consistent",
        ),
        sa.CheckConstraint(
            "(status <> 'active' OR password_hash_encoded IS NOT NULL)",
            name="active_requires_password",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint("updated_at >= created_at", name="updated_after_creation"),
        sa.CheckConstraint(
            "((status = 'disabled' AND disabled_at IS NOT NULL) OR "
            "(status <> 'disabled' AND disabled_at IS NULL))",
            name="disabled_at_matches_status",
        ),
        sa.CheckConstraint(
            "disabled_at IS NULL OR disabled_at >= created_at",
            name="disabled_after_creation",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    username_canonical: Mapped[str] = mapped_column(
        sa.String(64), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(
        sa.String(24), nullable=False, server_default=sa.text("'setup_pending'")
    )
    password_hash_encoded: Mapped[str | None] = mapped_column(
        sa.String(512), nullable=True
    )
    password_hash_algorithm: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True
    )
    password_hash_version: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True
    )
    auth_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    setup_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    totp_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    recovery_code_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    row_version: Mapped[int] = mapped_column(
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
    disabled_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class PlatformAdminTotpCredential(ControlBase):
    __tablename__ = "platform_admin_totp_credentials"
    __table_args__ = (
        sa.UniqueConstraint(
            "platform_admin_id",
            "generation",
            name="uq_platform_admin_totp_admin_generation",
        ),
        sa.UniqueConstraint(
            "current_confirmed_admin_id",
            name="uq_platform_admin_totp_current_confirmed",
        ),
        sa.CheckConstraint("generation >= 1", name="generation_positive"),
        sa.CheckConstraint("secret_revision >= 1", name="secret_revision_positive"),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'replaced', 'revoked')",
            name="status_valid",
        ),
        sa.CheckConstraint(
            "length(seed_nonce) = 12", name="seed_nonce_length"
        ),
        sa.CheckConstraint(
            "length(seed_ciphertext) >= 16", name="seed_ciphertext_has_tag"
        ),
        sa.CheckConstraint("root_key_version >= 1", name="root_key_version_positive"),
        sa.CheckConstraint("crypto_version >= 1", name="crypto_version_positive"),
        sa.CheckConstraint("aad_version >= 1", name="aad_version_positive"),
        sa.CheckConstraint("totp_algorithm = 'SHA1'", name="totp_algorithm_valid"),
        sa.CheckConstraint("totp_digits IN (6, 8)", name="totp_digits_valid"),
        sa.CheckConstraint("totp_period_seconds >= 15", name="totp_period_positive"),
        sa.CheckConstraint(
            "last_accepted_time_step IS NULL OR last_accepted_time_step >= 0",
            name="last_step_nonnegative",
        ),
        sa.CheckConstraint(
            "((status = 'pending' AND confirmed_at IS NULL AND retired_at IS NULL) "
            "OR (status = 'confirmed' AND confirmed_at IS NOT NULL "
            "AND retired_at IS NULL) "
            "OR (status IN ('replaced', 'revoked') AND retired_at IS NOT NULL))",
            name="lifecycle_valid",
        ),
        sa.CheckConstraint(
            "confirmed_at IS NULL OR confirmed_at >= created_at",
            name="confirmed_after_creation",
        ),
        sa.CheckConstraint(
            "retired_at IS NULL OR retired_at >= created_at",
            name="retired_after_creation",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.Index(
            "ix_platform_admin_totp_admin_status_generation",
            "platform_admin_id",
            "status",
            "generation",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    platform_admin_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "platform_admins.id",
            name="fk_pa_totp_admin",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    secret_revision: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, server_default=sa.text("'pending'")
    )
    seed_nonce: Mapped[bytes] = mapped_column(AES_GCM_NONCE_TYPE, nullable=False)
    seed_ciphertext: Mapped[bytes] = mapped_column(sa.LargeBinary, nullable=False)
    root_key_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    crypto_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    aad_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    totp_algorithm: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, server_default=sa.text("'SHA1'")
    )
    totp_digits: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("6")
    )
    totp_period_seconds: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("30")
    )
    last_accepted_time_step: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    current_confirmed_admin_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.Computed(
            "CASE WHEN status = 'confirmed' THEN platform_admin_id ELSE NULL END",
            persisted=True,
        ),
        nullable=True,
    )


class PlatformAdminRecoveryCode(ControlBase):
    __tablename__ = "platform_admin_recovery_codes"
    __table_args__ = (
        sa.UniqueConstraint(
            "platform_admin_id",
            "generation",
            "ordinal",
            name="uq_platform_admin_recovery_admin_generation_ordinal",
        ),
        sa.CheckConstraint("generation >= 1", name="generation_positive"),
        sa.CheckConstraint("ordinal >= 1", name="ordinal_positive"),
        sa.CheckConstraint(
            "length(token_digest_sha256) = 32",
            name="token_digest_sha256_length",
        ),
        sa.CheckConstraint(
            "state IN ('active', 'consumed', 'revoked')", name="state_valid"
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="expiry_after_creation",
        ),
        sa.CheckConstraint(
            "((state = 'active' AND consumed_at IS NULL AND revoked_at IS NULL) "
            "OR (state = 'consumed' AND consumed_at IS NOT NULL "
            "AND revoked_at IS NULL) "
            "OR (state = 'revoked' AND consumed_at IS NULL "
            "AND revoked_at IS NOT NULL))",
            name="lifecycle_valid",
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR (consumed_at >= created_at AND "
            "(expires_at IS NULL OR consumed_at < expires_at))",
            name="consumed_within_lifetime",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="revoked_after_creation",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.Index(
            "ix_platform_admin_recovery_admin_generation_state",
            "platform_admin_id",
            "generation",
            "state",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    platform_admin_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "platform_admins.id",
            name="fk_pa_recovery_admin",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    ordinal: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    token_digest_sha256: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False, unique=True
    )
    state: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, server_default=sa.text("'active'")
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        RECOVERY_FACTOR_TIMESTAMP_TYPE, nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class PlatformAdminSetupChallenge(ControlBase):
    __tablename__ = "platform_admin_setup_challenges"
    __table_args__ = (
        sa.UniqueConstraint(
            "platform_admin_id",
            "setup_version",
            name="uq_platform_admin_setup_admin_version",
        ),
        sa.CheckConstraint("setup_version >= 1", name="setup_version_positive"),
        sa.CheckConstraint(
            "length(token_digest_sha256) = 32",
            name="token_digest_sha256_length",
        ),
        sa.CheckConstraint(
            "state IN ('active', 'consumed', 'revoked')", name="state_valid"
        ),
        sa.CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        sa.CheckConstraint(
            "((state = 'active' AND consumed_at IS NULL AND revoked_at IS NULL) "
            "OR (state = 'consumed' AND consumed_at IS NOT NULL "
            "AND revoked_at IS NULL) "
            "OR (state = 'revoked' AND consumed_at IS NULL "
            "AND revoked_at IS NOT NULL))",
            name="lifecycle_valid",
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR (consumed_at >= created_at "
            "AND consumed_at < expires_at)",
            name="consumed_within_lifetime",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="revoked_after_creation",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.Index(
            "ix_platform_admin_setup_active_expiry",
            "platform_admin_id",
            "state",
            "expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    platform_admin_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "platform_admins.id",
            name="fk_pa_setup_admin",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    setup_version: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    token_digest_sha256: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False, unique=True
    )
    state: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, server_default=sa.text("'active'")
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class PlatformAdminSession(ControlBase):
    __tablename__ = "platform_admin_sessions"
    __table_args__ = (
        sa.CheckConstraint(
            "length(token_digest_sha256) = 32",
            name="token_digest_sha256_length",
        ),
        sa.CheckConstraint(
            "length(csrf_digest_sha256) = 32",
            name="csrf_digest_sha256_length",
        ),
        sa.CheckConstraint(
            "auth_version_at_issue >= 1", name="auth_version_at_issue_positive"
        ),
        sa.CheckConstraint(
            "setup_version_at_issue >= 1", name="setup_version_at_issue_positive"
        ),
        sa.CheckConstraint("policy_version >= 1", name="policy_version_positive"),
        sa.CheckConstraint("csrf_generation >= 1", name="csrf_generation_positive"),
        sa.CheckConstraint(
            "idle_timeout_seconds >= 1", name="idle_timeout_seconds_positive"
        ),
        sa.CheckConstraint(
            "mfa_method IN ('totp', 'recovery_code')", name="mfa_method_valid"
        ),
        sa.CheckConstraint(
            "((mfa_method = 'totp' AND totp_credential_id IS NOT NULL "
            "AND recovery_code_id IS NULL AND totp_time_step IS NOT NULL) OR "
            "(mfa_method = 'recovery_code' AND totp_credential_id IS NULL "
            "AND recovery_code_id IS NOT NULL AND totp_time_step IS NULL))",
            name="mfa_provenance_matches_method",
        ),
        sa.CheckConstraint(
            "totp_time_step IS NULL OR totp_time_step >= 0",
            name="totp_time_step_nonnegative",
        ),
        sa.CheckConstraint(
            "idle_expires_at <= absolute_expires_at",
            name="idle_before_absolute_expiry",
        ),
        sa.CheckConstraint(
            "mfa_verified_at <= created_at", name="mfa_before_creation"
        ),
        sa.CheckConstraint(
            "last_seen_at >= created_at", name="last_seen_after_creation"
        ),
        sa.CheckConstraint(
            "idle_expires_at > last_seen_at", name="idle_after_last_seen"
        ),
        sa.CheckConstraint(
            "absolute_expires_at > created_at",
            name="absolute_expiry_after_creation",
        ),
        sa.CheckConstraint(
            "((revoked_at IS NULL AND revoked_reason_code IS NULL "
            "AND revoked_by_session_id IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_reason_code IS NOT NULL))",
            name="revocation_fields_consistent",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="revoked_after_creation",
        ),
        sa.Index(
            "ix_platform_admin_sessions_admin_active_expiry",
            "platform_admin_id",
            "revoked_at",
            "absolute_expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    platform_admin_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("platform_admins.id", ondelete="RESTRICT"),
        nullable=False,
    )
    token_digest_sha256: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False, unique=True
    )
    csrf_digest_sha256: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False, unique=True
    )
    auth_version_at_issue: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    setup_version_at_issue: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    mfa_method: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    mfa_verified_at: Mapped[datetime] = mapped_column(
        PLATFORM_SESSION_TIMESTAMP_TYPE, nullable=False
    )
    totp_credential_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "platform_admin_totp_credentials.id",
            name="fk_pa_session_totp",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    totp_time_step: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    recovery_code_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "platform_admin_recovery_codes.id",
            name="fk_pa_session_recovery",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    policy_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    csrf_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    idle_timeout_seconds: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        PLATFORM_SESSION_TIMESTAMP_TYPE, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        PLATFORM_SESSION_TIMESTAMP_TYPE, nullable=False
    )
    idle_expires_at: Mapped[datetime] = mapped_column(
        PLATFORM_SESSION_TIMESTAMP_TYPE, nullable=False
    )
    absolute_expires_at: Mapped[datetime] = mapped_column(
        PLATFORM_SESSION_TIMESTAMP_TYPE, nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        PLATFORM_SESSION_TIMESTAMP_TYPE, nullable=True
    )
    revoked_reason_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    revoked_by_session_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "platform_admin_sessions.id",
            name="fk_platform_admin_sessions_revoked_by_session",
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


class PlatformAdminRateLimitCounter(ControlBase):
    __tablename__ = "platform_admin_rate_limit_counters"
    __table_args__ = (
        sa.UniqueConstraint(
            "scope",
            "subject_digest_sha256",
            "window_kind",
            "window_started_at",
            name="uq_platform_admin_rate_limit_window",
        ),
        sa.CheckConstraint(
            "scope IN ('password', 'mfa', 'setup', 'code_reveal')",
            name="scope_valid",
        ),
        sa.CheckConstraint(
            "window_kind IN ('rolling_hour', 'calendar_day', 'device_burst')",
            name="window_kind_valid",
        ),
        sa.CheckConstraint(
            "length(subject_digest_sha256) = 32",
            name="subject_digest_length",
        ),
        sa.CheckConstraint("attempt_count >= 1", name="attempt_count_positive"),
        sa.CheckConstraint("policy_version >= 1", name="policy_version_positive"),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint("expires_at > window_started_at", name="expiry_after_start"),
        sa.CheckConstraint(
            "blocked_until IS NULL OR blocked_until <= expires_at",
            name="block_within_window",
        ),
        sa.CheckConstraint("updated_at >= created_at", name="updated_after_creation"),
        sa.Index(
            "ix_platform_admin_rate_limit_expiry", "scope", "expires_at"
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    scope: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    subject_digest_sha256: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    window_kind: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    policy_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    blocked_until: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    row_version: Mapped[int] = mapped_column(
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
