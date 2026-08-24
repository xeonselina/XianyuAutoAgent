"""Tenant-owned provider connections and immutable secret envelopes."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from .base import ControlBase


def _new_uuid() -> str:
    return str(uuid4())


SHA256_DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")
AES_GCM_NONCE_TYPE = sa.LargeBinary(12).with_variant(mysql.BINARY(12), "mysql")


class TenantIntegration(ControlBase):
    """Stable, non-secret identity for one tenant/provider connection."""

    __tablename__ = "tenant_integrations"
    __table_args__ = (
        sa.UniqueConstraint(
            "tenant_id",
            "provider",
            "name",
            name="uq_tenant_integrations_tenant_provider_name",
        ),
        sa.UniqueConstraint(
            "id",
            "tenant_id",
            "provider",
            name="uq_tenant_integrations_identity_scope",
        ),
        sa.CheckConstraint(
            "provider IN ('sf', 'xianyu', 'kuaimai')",
            name="provider_valid",
        ),
        sa.CheckConstraint(
            "status IN ('unconfigured', 'pending', 'active', 'inactive', "
            "'verification_failed')",
            name="status_valid",
        ),
        sa.CheckConstraint("length(trim(name)) >= 1", name="name_nonempty"),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint(
            "current_secret_revision_id IS NULL OR status IN ('active', 'inactive')",
            name="current_pointer_status_valid",
        ),
        sa.Index(
            "ix_tenant_integrations_tenant_provider_status",
            "tenant_id",
            "provider",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    current_secret_revision_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    config_json: Mapped[dict[str, Any]] = mapped_column(
        sa.JSON, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default=sa.text("'unconfigured'"),
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
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


class TenantIntegrationSecretRevision(ControlBase):
    """One immutable credential bundle with a separately rotatable envelope."""

    __tablename__ = "tenant_integration_secret_revisions"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["tenant_integration_id", "tenant_id", "provider"],
            [
                "tenant_integrations.id",
                "tenant_integrations.tenant_id",
                "tenant_integrations.provider",
            ],
            name="fk_integration_secret_revisions_integration_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_integration_id",
            "revision_no",
            name="uq_integration_secret_revisions_number",
        ),
        sa.UniqueConstraint(
            "crypto_context_uuid",
            name="uq_integration_secret_revisions_crypto_context",
        ),
        sa.UniqueConstraint(
            "request_idempotency_key",
            name="uq_integration_secret_revisions_idempotency",
        ),
        sa.UniqueConstraint(
            "current_integration_id",
            name="uq_integration_secret_revisions_current_integration",
        ),
        sa.CheckConstraint(
            "provider IN ('sf', 'xianyu', 'kuaimai')",
            name="provider_valid",
        ),
        sa.CheckConstraint("revision_no >= 1", name="revision_no_positive"),
        sa.CheckConstraint(
            "credential_schema_version >= 1",
            name="schema_ver_pos",
        ),
        sa.CheckConstraint(
            "credential_bundle_version >= 1",
            name="bundle_ver_pos",
        ),
        sa.CheckConstraint(
            "length(canonical_semantics_digest) = 32",
            name="semantics_hash_len",
        ),
        sa.CheckConstraint(
            "length(credentials_nonce) = 12",
            name="credentials_nonce_length",
        ),
        sa.CheckConstraint(
            "length(credentials_ciphertext) >= 16",
            name="cipher_has_tag",
        ),
        sa.CheckConstraint("root_key_version >= 1", name="root_key_version_positive"),
        sa.CheckConstraint("crypto_version >= 1", name="crypto_version_positive"),
        sa.CheckConstraint("aad_version >= 1", name="aad_version_positive"),
        sa.CheckConstraint(
            "envelope_generation >= 1",
            name="envelope_gen_pos",
        ),
        sa.CheckConstraint(
            "envelope_row_version >= 1",
            name="envelope_row_ver_pos",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint(
            "envelope_row_version = envelope_generation",
            name="envelope_versions_equal",
        ),
        sa.CheckConstraint(
            "row_version >= envelope_row_version",
            name="row_covers_envelope",
        ),
        sa.CheckConstraint(
            "((envelope_generation = 1 "
            "AND last_envelope_rotation_event_id IS NULL) OR "
            "(envelope_generation >= 2 "
            "AND last_envelope_rotation_event_id IS NOT NULL))",
            name="envelope_event_ptr_valid",
        ),
        sa.CheckConstraint(
            "status IN ('pending_validation', 'current', 'superseded', 'revoked')",
            name="status_valid",
        ),
        sa.CheckConstraint(
            "verification_status IN ('not_attempted', 'submitting', "
            "'succeeded', 'failed', 'unknown')",
            name="verification_status_valid",
        ),
        sa.CheckConstraint(
            "((verification_status = 'not_attempted' "
            "AND verification_attempt_uuid IS NULL "
            "AND verification_result_digest IS NULL "
            "AND verification_safe_code IS NULL "
            "AND verification_completed_at IS NULL) OR "
            "(verification_status = 'submitting' "
            "AND verification_attempt_uuid IS NOT NULL "
            "AND verification_result_digest IS NULL "
            "AND verification_safe_code IS NULL "
            "AND verification_completed_at IS NULL) OR "
            "(verification_status IN ('succeeded', 'failed', 'unknown') "
            "AND verification_attempt_uuid IS NOT NULL "
            "AND verification_result_digest IS NOT NULL "
            "AND verification_safe_code IS NOT NULL "
            "AND verification_completed_at IS NOT NULL))",
            name="verify_facts_valid",
        ),
        sa.CheckConstraint(
            "verification_safe_code IS NULL OR "
            "length(trim(verification_safe_code)) >= 1",
            name="verify_code_nonempty",
        ),
        sa.CheckConstraint(
            "((status = 'pending_validation' AND activated_at IS NULL "
            "AND superseded_at IS NULL AND revoked_at IS NULL) OR "
            "(status = 'current' AND activated_at IS NOT NULL "
            "AND superseded_at IS NULL AND revoked_at IS NULL) OR "
            "(status = 'superseded' AND activated_at IS NOT NULL "
            "AND superseded_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL))",
            name="lifecycle_times_valid",
        ),
        sa.CheckConstraint(
            "((verification_status IN ('not_attempted', 'submitting', 'unknown') "
            "AND status = 'pending_validation') OR "
            "(verification_status = 'failed' AND status = 'revoked') OR "
            "(verification_status = 'succeeded' "
            "AND status IN ('current', 'superseded')))",
            name="verify_lifecycle_valid",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 32",
            name="request_digest_length",
        ),
        sa.CheckConstraint(
            "length(trim(request_idempotency_key)) >= 1 "
            "AND length(request_idempotency_key) <= 128",
            name="request_key_bounded",
        ),
        sa.CheckConstraint(
            "expected_integration_row_version >= 1",
            name="expected_int_ver_pos",
        ),
        sa.Index(
            "ix_integration_secret_revisions_integration_status",
            "tenant_integration_id",
            "status",
            "revision_no",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    tenant_integration_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    tenant_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    provider: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    revision_no: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    crypto_context_uuid: Mapped[str] = mapped_column(
        sa.String(36), nullable=False, default=_new_uuid
    )
    credential_schema_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    credential_bundle_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    canonical_semantics_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    credentials_ciphertext: Mapped[bytes] = mapped_column(
        sa.LargeBinary, nullable=False
    )
    credentials_nonce: Mapped[bytes] = mapped_column(
        AES_GCM_NONCE_TYPE, nullable=False
    )
    root_key_version: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    crypto_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    aad_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    envelope_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    envelope_row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    last_envelope_rotation_event_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default=sa.text("'pending_validation'"),
    )
    current_integration_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.Computed(
            "CASE WHEN status = 'current' THEN tenant_integration_id ELSE NULL END",
            persisted=True,
        ),
        nullable=True,
    )
    created_from_action_uuid: Mapped[str] = mapped_column(
        sa.String(36), nullable=False
    )
    created_by_user_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    request_idempotency_key: Mapped[str] = mapped_column(
        sa.String(128), nullable=False
    )
    request_digest: Mapped[bytes] = mapped_column(SHA256_DIGEST_TYPE, nullable=False)
    expected_integration_row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    expected_current_secret_revision_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    verification_status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default=sa.text("'not_attempted'"),
    )
    verification_attempt_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    verification_result_digest: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    verification_safe_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    verification_completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


class TenantIntegrationSecretEnvelopeEvent(ControlBase):
    """Append-only proof that one business revision kept its semantics."""

    __tablename__ = "tenant_integration_secret_envelope_events"
    __table_args__ = (
        sa.UniqueConstraint(
            "tenant_integration_secret_revision_id",
            "envelope_generation",
            name="uq_integration_secret_envelope_events_generation",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_integration_secret_envelope_events_idempotency",
        ),
        sa.CheckConstraint(
            "envelope_generation >= 2",
            name="gen_rotated",
        ),
        sa.CheckConstraint(
            "from_root_key_version >= 1 AND to_root_key_version >= 1",
            name="root_vers_pos",
        ),
        sa.CheckConstraint(
            "from_crypto_version >= 1 AND to_crypto_version >= 1",
            name="crypto_vers_pos",
        ),
        sa.CheckConstraint(
            "from_aad_version >= 1 AND to_aad_version >= 1",
            name="aad_vers_pos",
        ),
        sa.CheckConstraint(
            "length(before_ciphertext_digest) = 32",
            name="before_hash_len",
        ),
        sa.CheckConstraint(
            "length(after_ciphertext_digest) = 32",
            name="after_hash_len",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 32",
            name="request_hash_len",
        ),
        sa.CheckConstraint("safe_outcome = 'succeeded'", name="outcome_succeeded"),
        sa.ForeignKeyConstraint(
            ["tenant_integration_secret_revision_id"],
            ["tenant_integration_secret_revisions.id"],
            name="fk_tis_envelope_revision",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    tenant_integration_secret_revision_id: Mapped[str] = mapped_column(
        sa.String(36),
        nullable=False,
    )
    envelope_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    from_root_key_version: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    to_root_key_version: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    from_crypto_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    to_crypto_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    from_aad_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    to_aad_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    before_ciphertext_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    after_ciphertext_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    rotation_run_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    rotation_action_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    request_digest: Mapped[bytes] = mapped_column(SHA256_DIGEST_TYPE, nullable=False)
    safe_outcome: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, server_default=sa.text("'succeeded'")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


class TenantProviderDefault(ControlBase):
    """Default connection selector only for newly created provider accounts."""

    __tablename__ = "tenant_provider_defaults"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["integration_id", "tenant_id", "provider"],
            [
                "tenant_integrations.id",
                "tenant_integrations.tenant_id",
                "tenant_integrations.provider",
            ],
            name="fk_tenant_provider_defaults_integration_scope",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "provider IN ('sf', 'xianyu', 'kuaimai')",
            name="provider_valid",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
    )

    tenant_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(sa.String(16), primary_key=True)
    integration_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    updated_by: Mapped[str] = mapped_column(sa.String(36), nullable=False)
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
