"""Create tenant provider accounts and immutable account-secret revisions.

Revision ID: 202608220029
Revises: 202608220028
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "202608220029"
down_revision = "202608220028"
branch_labels = None
depends_on = None


DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")
NONCE_TYPE = sa.LargeBinary(12).with_variant(mysql.BINARY(12), "mysql")


def upgrade() -> None:
    op.create_table(
        "tenant_provider_accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("integration_id", sa.String(length=36), nullable=False),
        sa.Column("current_secret_revision_id", sa.String(length=36), nullable=True),
        sa.Column("current_global_claim_id", sa.String(length=36), nullable=True),
        sa.Column("current_claim_generation", sa.BigInteger(), nullable=True),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("masked_hint", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider = 'sf'", name=op.f("ck_tenant_provider_accounts_provider_sf")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'inactive', 'verification_failed')",
            name=op.f("ck_tenant_provider_accounts_status_valid"),
        ),
        sa.CheckConstraint(
            "length(trim(label)) >= 1",
            name=op.f("ck_tenant_provider_accounts_label_nonempty"),
        ),
        sa.CheckConstraint(
            "length(trim(masked_hint)) >= 1",
            name=op.f("ck_tenant_provider_accounts_masked_hint_nonempty"),
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name=op.f("ck_tenant_provider_accounts_row_version_positive"),
        ),
        sa.CheckConstraint(
            "((current_global_claim_id IS NULL "
            "AND current_claim_generation IS NULL) OR "
            "(current_global_claim_id IS NOT NULL "
            "AND current_claim_generation IS NOT NULL "
            "AND current_claim_generation >= 1))",
            name=op.f("ck_tenant_provider_accounts_claim_pointer_complete"),
        ),
        sa.CheckConstraint(
            "current_secret_revision_id IS NULL OR status IN ('active', 'inactive')",
            name=op.f("ck_tenant_provider_accounts_secret_pointer_status_valid"),
        ),
        sa.CheckConstraint(
            "status <> 'active' OR "
            "(current_secret_revision_id IS NOT NULL "
            "AND current_global_claim_id IS NOT NULL "
            "AND current_claim_generation IS NOT NULL "
            "AND last_verified_at IS NOT NULL)",
            name=op.f("ck_tenant_provider_accounts_active_context_complete"),
        ),
        sa.CheckConstraint(
            "status <> 'pending' OR "
            "(current_secret_revision_id IS NULL "
            "AND current_global_claim_id IS NULL)",
            name=op.f("ck_tenant_provider_accounts_pending_has_no_current"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_provider_accounts_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_provider_accounts")),
        sa.UniqueConstraint(
            "id",
            "tenant_id",
            "provider",
            "integration_id",
            name="uq_provider_accounts_identity_scope",
        ),
    )
    op.create_index(
        "ix_provider_accounts_tenant_provider_status",
        "tenant_provider_accounts",
        ["tenant_id", "provider", "status"],
        unique=False,
    )

    op.create_table(
        "tenant_provider_account_secret_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_provider_account_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("integration_id", sa.String(length=36), nullable=False),
        sa.Column("revision_no", sa.BigInteger(), nullable=False),
        sa.Column("crypto_context_uuid", sa.String(length=36), nullable=False),
        sa.Column("account_secret_schema_version", sa.Integer(), nullable=False),
        sa.Column("account_secret_bundle_version", sa.Integer(), nullable=False),
        sa.Column("canonical_semantics_digest", DIGEST_TYPE, nullable=False),
        sa.Column("account_secret_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("account_secret_nonce", NONCE_TYPE, nullable=False),
        sa.Column("root_key_version", sa.BigInteger(), nullable=False),
        sa.Column("crypto_version", sa.Integer(), nullable=False),
        sa.Column("aad_version", sa.Integer(), nullable=False),
        sa.Column(
            "envelope_generation",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "envelope_row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("last_envelope_rotation_event_id", sa.String(36), nullable=True),
        sa.Column("provider_account_claim_id", sa.String(36), nullable=False),
        sa.Column("account_fingerprint", DIGEST_TYPE, nullable=False),
        sa.Column("fingerprint_version", sa.Integer(), nullable=False),
        sa.Column("fingerprint_root_key_version", sa.BigInteger(), nullable=False),
        sa.Column("expected_claim_generation", sa.BigInteger(), nullable=False),
        sa.Column("expected_claim_row_version", sa.BigInteger(), nullable=False),
        sa.Column("target_binding_revision", sa.BigInteger(), nullable=False),
        sa.Column(
            "expected_warehouse_provider_account_id",
            sa.String(length=36),
            nullable=True,
        ),
        sa.Column(
            "expected_warehouse_binding_revision",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column("activated_claim_generation", sa.BigInteger(), nullable=True),
        sa.Column("masked_hint", sa.String(32), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            server_default=sa.text("'pending_validation'"),
            nullable=False,
        ),
        sa.Column(
            "current_provider_account_id",
            sa.String(36),
            sa.Computed(
                "CASE WHEN status = 'current' "
                "THEN tenant_provider_account_id ELSE NULL END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("created_from_action_uuid", sa.String(36), nullable=False),
        sa.Column("created_by_user_uuid", sa.String(36), nullable=False),
        sa.Column("request_idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", DIGEST_TYPE, nullable=False),
        sa.Column("expected_account_absent", sa.Boolean(), nullable=False),
        sa.Column("expected_account_row_version", sa.BigInteger(), nullable=False),
        sa.Column("expected_integration_row_version", sa.BigInteger(), nullable=False),
        sa.Column(
            "validation_integration_secret_revision_id",
            sa.String(36),
            nullable=False,
        ),
        sa.Column("expected_current_secret_revision_id", sa.String(36), nullable=True),
        sa.Column("expected_current_global_claim_id", sa.String(36), nullable=True),
        sa.Column(
            "verification_status",
            sa.String(32),
            server_default=sa.text("'not_attempted'"),
            nullable=False,
        ),
        sa.Column("verification_attempt_uuid", sa.String(36), nullable=True),
        sa.Column("verification_result_digest", DIGEST_TYPE, nullable=True),
        sa.Column("verification_safe_code", sa.String(64), nullable=True),
        sa.Column("verification_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        *_revision_constraints(),
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
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_tenant_provider_account_secret_revisions")
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
    )
    op.create_index(
        "ix_account_secret_revisions_account_status",
        "tenant_provider_account_secret_revisions",
        ["tenant_provider_account_id", "status", "revision_no"],
        unique=False,
    )

    op.create_table(
        "tenant_provider_account_secret_envelope_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column(
            "tenant_provider_account_secret_revision_id",
            sa.String(36),
            nullable=False,
        ),
        sa.Column("envelope_generation", sa.BigInteger(), nullable=False),
        sa.Column("from_root_key_version", sa.BigInteger(), nullable=False),
        sa.Column("to_root_key_version", sa.BigInteger(), nullable=False),
        sa.Column("from_crypto_version", sa.Integer(), nullable=False),
        sa.Column("to_crypto_version", sa.Integer(), nullable=False),
        sa.Column("from_aad_version", sa.Integer(), nullable=False),
        sa.Column("to_aad_version", sa.Integer(), nullable=False),
        sa.Column("before_ciphertext_digest", DIGEST_TYPE, nullable=False),
        sa.Column("after_ciphertext_digest", DIGEST_TYPE, nullable=False),
        sa.Column("rotation_run_uuid", sa.String(36), nullable=False),
        sa.Column("rotation_action_uuid", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", DIGEST_TYPE, nullable=False),
        sa.Column(
            "safe_outcome",
            sa.String(16),
            server_default=sa.text("'succeeded'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        *_envelope_event_constraints(),
        sa.ForeignKeyConstraint(
            ["tenant_provider_account_secret_revision_id"],
            ["tenant_provider_account_secret_revisions.id"],
            name="fk_account_secret_envelope_events_revision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_tenant_provider_account_secret_envelope_events"),
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
    )


def downgrade() -> None:
    op.drop_table("tenant_provider_account_secret_envelope_events")
    op.drop_table("tenant_provider_account_secret_revisions")
    op.drop_table("tenant_provider_accounts")


def _revision_constraints() -> tuple[sa.CheckConstraint, ...]:
    checks = (
        ("provider = 'sf'", "provider_sf"),
        ("revision_no >= 1", "revision_no_positive"),
        ("account_secret_schema_version >= 1", "schema_version_positive"),
        ("account_secret_bundle_version >= 1", "bundle_version_positive"),
        ("length(canonical_semantics_digest) = 32", "semantics_hash_len"),
        ("length(account_fingerprint) = 32", "fingerprint_length"),
        ("fingerprint_version = 1", "fingerprint_version_supported"),
        ("fingerprint_root_key_version >= 1", "fingerprint_key_positive"),
        ("expected_claim_generation >= 1", "expected_claim_gen_positive"),
        ("expected_claim_row_version >= 1", "expected_claim_row_positive"),
        (
            "target_binding_revision >= 1",
            "target_binding_revision_positive",
        ),
        (
            "expected_warehouse_binding_revision IS NULL OR "
            "expected_warehouse_binding_revision >= 1",
            "expected_warehouse_binding_revision_positive",
        ),
        (
            "activated_claim_generation IS NULL OR "
            "activated_claim_generation >= expected_claim_generation",
            "activated_claim_gen_current",
        ),
        ("length(account_secret_nonce) = 12", "account_nonce_length"),
        ("length(account_secret_ciphertext) >= 16", "account_cipher_has_tag"),
        ("root_key_version >= 1", "root_key_version_positive"),
        ("crypto_version >= 1", "crypto_version_positive"),
        ("aad_version >= 1", "aad_version_positive"),
        ("envelope_generation >= 1", "envelope_gen_positive"),
        (
            "envelope_row_version = envelope_generation",
            "envelope_versions_equal",
        ),
        ("row_version >= envelope_row_version", "row_covers_envelope"),
        (
            "((envelope_generation = 1 "
            "AND last_envelope_rotation_event_id IS NULL) OR "
            "(envelope_generation >= 2 "
            "AND last_envelope_rotation_event_id IS NOT NULL))",
            "envelope_event_pointer_valid",
        ),
        (
            "status IN ('pending_validation', 'current', 'superseded', 'revoked')",
            "status_valid",
        ),
        (
            "verification_status IN ('not_attempted', 'submitting', "
            "'succeeded', 'failed', 'unknown')",
            "verification_status_valid",
        ),
        (
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
            "verification_facts_valid",
        ),
        (
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
            "lifecycle_facts_valid",
        ),
        (
            "((verification_status IN ('not_attempted', 'submitting', 'unknown') "
            "AND status = 'pending_validation') OR "
            "(verification_status = 'failed' AND status = 'revoked') OR "
            "(verification_status = 'succeeded' "
            "AND status IN ('current', 'superseded')))",
            "verification_lifecycle_valid",
        ),
        ("length(request_digest) = 32", "request_digest_length"),
        (
            "length(trim(request_idempotency_key)) >= 1 "
            "AND length(request_idempotency_key) <= 128",
            "request_key_bounded",
        ),
        ("expected_account_row_version >= 1", "expected_account_ver_positive"),
        (
            "expected_integration_row_version >= 1",
            "expected_integration_ver_positive",
        ),
        ("row_version >= 1", "row_version_positive"),
        ("length(trim(masked_hint)) >= 1", "masked_hint_nonempty"),
    )
    prefix = "ck_tenant_provider_account_secret_revisions_"
    return tuple(sa.CheckConstraint(sql, name=op.f(prefix + name)) for sql, name in checks)


def _envelope_event_constraints() -> tuple[sa.CheckConstraint, ...]:
    checks = (
        ("envelope_generation >= 2", "generation_rotated"),
        (
            "from_root_key_version >= 1 AND to_root_key_version >= 1",
            "root_versions_positive",
        ),
        (
            "from_crypto_version >= 1 AND to_crypto_version >= 1",
            "crypto_versions_positive",
        ),
        (
            "from_aad_version >= 1 AND to_aad_version >= 1",
            "aad_versions_positive",
        ),
        ("length(before_ciphertext_digest) = 32", "before_hash_len"),
        ("length(after_ciphertext_digest) = 32", "after_hash_len"),
        ("length(request_digest) = 32", "request_hash_len"),
        ("safe_outcome = 'succeeded'", "outcome_succeeded"),
    )
    prefix = "ck_tenant_provider_account_secret_envelope_events_"
    return tuple(sa.CheckConstraint(sql, name=op.f(prefix + name)) for sql, name in checks)
