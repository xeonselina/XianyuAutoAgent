"""Tenant-owned provider accounts and immutable account-secret envelopes."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .base import ControlBase
from .integrations import AES_GCM_NONCE_TYPE, SHA256_DIGEST_TYPE


def _new_uuid() -> str:
    return str(uuid4())


class TenantProviderAccount(ControlBase):
    """Stable SF business-account identity without account-secret ciphertext."""

    __tablename__ = "tenant_provider_accounts"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["integration_id", "tenant_id", "provider"],
            [
                "tenant_integrations.id",
                "tenant_integrations.tenant_id",
                "tenant_integrations.provider",
            ],
            name="fk_provider_accounts_integration_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["current_global_claim_id"],
            ["provider_account_claims.id"],
            name="fk_provider_accounts_current_claim",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "id",
            "tenant_id",
            "provider",
            "integration_id",
            name="uq_provider_accounts_identity_scope",
        ),
        sa.CheckConstraint("provider = 'sf'", name="provider_sf"),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'inactive', 'verification_failed')",
            name="status_valid",
        ),
        sa.CheckConstraint("length(trim(label)) >= 1", name="label_nonempty"),
        sa.CheckConstraint(
            "length(trim(masked_hint)) >= 1", name="masked_hint_nonempty"
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint(
            "((current_global_claim_id IS NULL "
            "AND current_claim_generation IS NULL) OR "
            "(current_global_claim_id IS NOT NULL "
            "AND current_claim_generation IS NOT NULL "
            "AND current_claim_generation >= 1))",
            name="claim_pointer_complete",
        ),
        sa.CheckConstraint(
            "current_secret_revision_id IS NULL OR status IN ('active', 'inactive')",
            name="secret_pointer_status_valid",
        ),
        sa.CheckConstraint(
            "status <> 'active' OR "
            "(current_secret_revision_id IS NOT NULL "
            "AND current_global_claim_id IS NOT NULL "
            "AND current_claim_generation IS NOT NULL "
            "AND last_verified_at IS NOT NULL)",
            name="active_context_complete",
        ),
        sa.CheckConstraint(
            "status <> 'pending' OR "
            "(current_secret_revision_id IS NULL "
            "AND current_global_claim_id IS NULL)",
            name="pending_has_no_current",
        ),
        sa.Index(
            "ix_provider_accounts_tenant_provider_status",
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
    integration_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    current_secret_revision_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    current_global_claim_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    current_claim_generation: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    label: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    masked_hint: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, server_default=sa.text("'pending'")
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


class TenantProviderAccountSecretRevision(ControlBase):
    """One immutable monthly-account value with a rotatable envelope."""

    __tablename__ = "tenant_provider_account_secret_revisions"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            [
                "tenant_provider_account_id",
                "tenant_id",
                "provider",
                "integration_id",
            ],
            [
                "tenant_provider_accounts.id",
                "tenant_provider_accounts.tenant_id",
                "tenant_provider_accounts.provider",
                "tenant_provider_accounts.integration_id",
            ],
            name="fk_account_secret_revisions_account_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_claim_id"],
            ["provider_account_claims.id"],
            name="fk_account_secret_revisions_claim",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_provider_account_id",
            "revision_no",
            name="uq_account_secret_revisions_number",
        ),
        sa.UniqueConstraint(
            "crypto_context_uuid",
            name="uq_account_secret_revisions_crypto_context",
        ),
        sa.UniqueConstraint(
            "request_idempotency_key",
            name="uq_account_secret_revisions_idempotency",
        ),
        sa.UniqueConstraint(
            "current_provider_account_id",
            name="uq_account_secret_revisions_current_account",
        ),
        sa.CheckConstraint("provider = 'sf'", name="provider_sf"),
        sa.CheckConstraint("revision_no >= 1", name="revision_no_positive"),
        sa.CheckConstraint(
            "account_secret_schema_version >= 1", name="schema_version_positive"
        ),
        sa.CheckConstraint(
            "account_secret_bundle_version >= 1", name="bundle_version_positive"
        ),
        sa.CheckConstraint(
            "length(canonical_semantics_digest) = 32", name="semantics_hash_len"
        ),
        sa.CheckConstraint(
            "length(account_fingerprint) = 32", name="fingerprint_length"
        ),
        sa.CheckConstraint(
            "fingerprint_version = 1", name="fingerprint_version_supported"
        ),
        sa.CheckConstraint(
            "fingerprint_root_key_version >= 1", name="fingerprint_key_positive"
        ),
        sa.CheckConstraint(
            "expected_claim_generation >= 1", name="expected_claim_gen_positive"
        ),
        sa.CheckConstraint(
            "expected_claim_row_version >= 1", name="expected_claim_row_positive"
        ),
        sa.CheckConstraint(
            "target_binding_revision >= 1", name="target_binding_revision_positive"
        ),
        sa.CheckConstraint(
            "expected_warehouse_binding_revision IS NULL OR "
            "expected_warehouse_binding_revision >= 1",
            name="expected_warehouse_binding_revision_positive",
        ),
        sa.CheckConstraint(
            "activated_claim_generation IS NULL OR "
            "activated_claim_generation >= expected_claim_generation",
            name="activated_claim_gen_current",
        ),
        sa.CheckConstraint(
            "length(account_secret_nonce) = 12", name="account_nonce_length"
        ),
        sa.CheckConstraint(
            "length(account_secret_ciphertext) >= 16", name="account_cipher_has_tag"
        ),
        sa.CheckConstraint("root_key_version >= 1", name="root_key_version_positive"),
        sa.CheckConstraint("crypto_version >= 1", name="crypto_version_positive"),
        sa.CheckConstraint("aad_version >= 1", name="aad_version_positive"),
        sa.CheckConstraint("envelope_generation >= 1", name="envelope_gen_positive"),
        sa.CheckConstraint(
            "envelope_row_version = envelope_generation",
            name="envelope_versions_equal",
        ),
        sa.CheckConstraint(
            "row_version >= envelope_row_version", name="row_covers_envelope"
        ),
        sa.CheckConstraint(
            "((envelope_generation = 1 "
            "AND last_envelope_rotation_event_id IS NULL) OR "
            "(envelope_generation >= 2 "
            "AND last_envelope_rotation_event_id IS NOT NULL))",
            name="envelope_event_pointer_valid",
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
            name="verification_facts_valid",
        ),
        sa.CheckConstraint(
            "((status = 'pending_validation' "
            "AND activated_at IS NULL AND superseded_at IS NULL "
            "AND revoked_at IS NULL AND activated_claim_generation IS NULL) OR "
            "(status = 'current' "
            "AND activated_at IS NOT NULL AND superseded_at IS NULL "
            "AND revoked_at IS NULL AND activated_claim_generation IS NOT NULL) OR "
            "(status = 'superseded' "
            "AND activated_at IS NOT NULL AND superseded_at IS NOT NULL "
            "AND revoked_at IS NULL AND activated_claim_generation IS NOT NULL) OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL))",
            name="lifecycle_facts_valid",
        ),
        sa.CheckConstraint(
            "((verification_status IN ('not_attempted', 'submitting', 'unknown') "
            "AND status = 'pending_validation') OR "
            "(verification_status = 'failed' AND status = 'revoked') OR "
            "(verification_status = 'succeeded' "
            "AND status IN ('current', 'superseded')))",
            name="verification_lifecycle_valid",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 32", name="request_digest_length"
        ),
        sa.CheckConstraint(
            "length(trim(request_idempotency_key)) >= 1 "
            "AND length(request_idempotency_key) <= 128",
            name="request_key_bounded",
        ),
        sa.CheckConstraint(
            "expected_account_row_version >= 1", name="expected_account_ver_positive"
        ),
        sa.CheckConstraint(
            "expected_integration_row_version >= 1",
            name="expected_integration_ver_positive",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint(
            "length(trim(masked_hint)) >= 1", name="masked_hint_nonempty"
        ),
        sa.Index(
            "ix_account_secret_revisions_account_status",
            "tenant_provider_account_id",
            "status",
            "revision_no",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    tenant_provider_account_id: Mapped[str] = mapped_column(
        sa.String(36), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    provider: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    integration_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    revision_no: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    crypto_context_uuid: Mapped[str] = mapped_column(
        sa.String(36), nullable=False, default=_new_uuid
    )
    account_secret_schema_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False
    )
    account_secret_bundle_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False
    )
    canonical_semantics_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    account_secret_ciphertext: Mapped[bytes] = mapped_column(
        sa.LargeBinary, nullable=False
    )
    account_secret_nonce: Mapped[bytes] = mapped_column(
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
    provider_account_claim_id: Mapped[str] = mapped_column(
        sa.String(36), nullable=False
    )
    account_fingerprint: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    fingerprint_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    fingerprint_root_key_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    expected_claim_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    expected_claim_row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    target_binding_revision: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    expected_warehouse_provider_account_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    expected_warehouse_binding_revision: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    activated_claim_generation: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    masked_hint: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default=sa.text("'pending_validation'"),
    )
    current_provider_account_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.Computed(
            "CASE WHEN status = 'current' "
            "THEN tenant_provider_account_id ELSE NULL END",
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
    expected_account_absent: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False
    )
    expected_account_row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    expected_integration_row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    validation_integration_secret_revision_id: Mapped[str] = mapped_column(
        sa.String(36), nullable=False
    )
    expected_current_secret_revision_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    expected_current_global_claim_id: Mapped[str | None] = mapped_column(
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


class TenantProviderAccountSecretEnvelopeEvent(ControlBase):
    """Append-only evidence for account-secret envelope maintenance."""

    __tablename__ = "tenant_provider_account_secret_envelope_events"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["tenant_provider_account_secret_revision_id"],
            ["tenant_provider_account_secret_revisions.id"],
            name="fk_account_secret_envelope_events_revision",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_provider_account_secret_revision_id",
            "envelope_generation",
            name="uq_account_secret_envelope_events_generation",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_account_secret_envelope_events_idempotency",
        ),
        sa.CheckConstraint("envelope_generation >= 2", name="generation_rotated"),
        sa.CheckConstraint(
            "from_root_key_version >= 1 AND to_root_key_version >= 1",
            name="root_versions_positive",
        ),
        sa.CheckConstraint(
            "from_crypto_version >= 1 AND to_crypto_version >= 1",
            name="crypto_versions_positive",
        ),
        sa.CheckConstraint(
            "from_aad_version >= 1 AND to_aad_version >= 1",
            name="aad_versions_positive",
        ),
        sa.CheckConstraint(
            "length(before_ciphertext_digest) = 32", name="before_hash_len"
        ),
        sa.CheckConstraint(
            "length(after_ciphertext_digest) = 32", name="after_hash_len"
        ),
        sa.CheckConstraint(
            "length(request_digest) = 32", name="request_hash_len"
        ),
        sa.CheckConstraint("safe_outcome = 'succeeded'", name="outcome_succeeded"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    tenant_provider_account_secret_revision_id: Mapped[str] = mapped_column(
        sa.String(36), nullable=False
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
