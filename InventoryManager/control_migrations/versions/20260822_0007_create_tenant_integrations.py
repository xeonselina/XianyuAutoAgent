"""Create tenant integrations and immutable credential revisions.

Revision ID: 202608220007
Revises: 202608220006
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "202608220007"
down_revision = "202608220006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    digest_type = sa.LargeBinary(length=32).with_variant(
        mysql.BINARY(32), "mysql"
    )
    nonce_type = sa.LargeBinary(length=12).with_variant(
        mysql.BINARY(12), "mysql"
    )

    op.create_table(
        "tenant_integrations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("current_secret_revision_id", sa.String(length=36), nullable=True),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'unconfigured'"),
            nullable=False,
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
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
            "provider IN ('sf', 'xianyu', 'kuaimai')",
            name=op.f("ck_tenant_integrations_provider_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('unconfigured', 'pending', 'active', 'inactive', "
            "'verification_failed')",
            name=op.f("ck_tenant_integrations_status_valid"),
        ),
        sa.CheckConstraint(
            "length(trim(name)) >= 1",
            name=op.f("ck_tenant_integrations_name_nonempty"),
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name=op.f("ck_tenant_integrations_row_version_positive"),
        ),
        sa.CheckConstraint(
            "current_secret_revision_id IS NULL OR status IN ('active', 'inactive')",
            name=op.f("ck_tenant_integrations_current_pointer_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_integrations_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_integrations"),
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
    )
    op.create_index(
        "ix_tenant_integrations_tenant_provider_status",
        "tenant_integrations",
        ["tenant_id", "provider", "status"],
        unique=False,
    )

    op.create_table(
        "tenant_integration_secret_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_integration_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("revision_no", sa.BigInteger(), nullable=False),
        sa.Column("crypto_context_uuid", sa.String(length=36), nullable=False),
        sa.Column("credential_schema_version", sa.Integer(), nullable=False),
        sa.Column("credential_bundle_version", sa.Integer(), nullable=False),
        sa.Column("canonical_semantics_digest", digest_type, nullable=False),
        sa.Column("credentials_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("credentials_nonce", nonce_type, nullable=False),
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
        sa.Column(
            "last_envelope_rotation_event_id", sa.String(length=36), nullable=True
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending_validation'"),
            nullable=False,
        ),
        sa.Column(
            "current_integration_id",
            sa.String(length=36),
            sa.Computed(
                "CASE WHEN status = 'current' THEN tenant_integration_id ELSE NULL END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("created_from_action_uuid", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_uuid", sa.String(length=36), nullable=False),
        sa.Column("request_idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", digest_type, nullable=False),
        sa.Column("expected_integration_row_version", sa.BigInteger(), nullable=False),
        sa.Column(
            "expected_current_secret_revision_id", sa.String(length=36), nullable=True
        ),
        sa.Column(
            "verification_status",
            sa.String(length=32),
            server_default=sa.text("'not_attempted'"),
            nullable=False,
        ),
        sa.Column("verification_attempt_uuid", sa.String(length=36), nullable=True),
        sa.Column("verification_result_digest", digest_type, nullable=True),
        sa.Column("verification_safe_code", sa.String(length=64), nullable=True),
        sa.Column(
            "verification_completed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider IN ('sf', 'xianyu', 'kuaimai')",
            name=op.f("ck_tenant_integration_secret_revisions_provider_valid"),
        ),
        sa.CheckConstraint(
            "revision_no >= 1",
            name=op.f(
                "ck_tenant_integration_secret_revisions_revision_no_positive"
            ),
        ),
        sa.CheckConstraint(
            "credential_schema_version >= 1",
            name=op.f(
                "ck_tenant_integration_secret_revisions_schema_ver_pos"
            ),
        ),
        sa.CheckConstraint(
            "credential_bundle_version >= 1",
            name=op.f(
                "ck_tenant_integration_secret_revisions_bundle_ver_pos"
            ),
        ),
        sa.CheckConstraint(
            "length(canonical_semantics_digest) = 32",
            name=op.f(
                "ck_tenant_integration_secret_revisions_semantics_hash_len"
            ),
        ),
        sa.CheckConstraint(
            "length(credentials_nonce) = 12",
            name=op.f(
                "ck_tenant_integration_secret_revisions_credentials_nonce_length"
            ),
        ),
        sa.CheckConstraint(
            "length(credentials_ciphertext) >= 16",
            name=op.f(
                "ck_tenant_integration_secret_revisions_cipher_has_tag"
            ),
        ),
        sa.CheckConstraint(
            "root_key_version >= 1",
            name=op.f(
                "ck_tenant_integration_secret_revisions_root_key_version_positive"
            ),
        ),
        sa.CheckConstraint(
            "crypto_version >= 1",
            name=op.f(
                "ck_tenant_integration_secret_revisions_crypto_version_positive"
            ),
        ),
        sa.CheckConstraint(
            "aad_version >= 1",
            name=op.f(
                "ck_tenant_integration_secret_revisions_aad_version_positive"
            ),
        ),
        sa.CheckConstraint(
            "envelope_generation >= 1",
            name=op.f(
                "ck_tenant_integration_secret_revisions_envelope_gen_pos"
            ),
        ),
        sa.CheckConstraint(
            "envelope_row_version >= 1",
            name=op.f(
                "ck_tenant_integration_secret_revisions_envelope_row_ver_pos"
            ),
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name=op.f(
                "ck_tenant_integration_secret_revisions_row_version_positive"
            ),
        ),
        sa.CheckConstraint(
            "envelope_row_version = envelope_generation",
            name=op.f(
                "ck_tenant_integration_secret_revisions_envelope_versions_equal"
            ),
        ),
        sa.CheckConstraint(
            "row_version >= envelope_row_version",
            name=op.f(
                "ck_tenant_integration_secret_revisions_row_covers_envelope"
            ),
        ),
        sa.CheckConstraint(
            "((envelope_generation = 1 "
            "AND last_envelope_rotation_event_id IS NULL) OR "
            "(envelope_generation >= 2 "
            "AND last_envelope_rotation_event_id IS NOT NULL))",
            name=op.f(
                "ck_tenant_integration_secret_revisions_envelope_event_ptr_valid"
            ),
        ),
        sa.CheckConstraint(
            "status IN ('pending_validation', 'current', 'superseded', 'revoked')",
            name=op.f("ck_tenant_integration_secret_revisions_status_valid"),
        ),
        sa.CheckConstraint(
            "verification_status IN ('not_attempted', 'submitting', "
            "'succeeded', 'failed', 'unknown')",
            name=op.f(
                "ck_tenant_integration_secret_revisions_"
                "verification_status_valid"
            ),
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
            name=op.f(
                "ck_tenant_integration_secret_revisions_verify_facts_valid"
            ),
        ),
        sa.CheckConstraint(
            "verification_safe_code IS NULL OR "
            "length(trim(verification_safe_code)) >= 1",
            name=op.f(
                "ck_tenant_integration_secret_revisions_verify_code_nonempty"
            ),
        ),
        sa.CheckConstraint(
            "((status = 'pending_validation' AND activated_at IS NULL "
            "AND superseded_at IS NULL AND revoked_at IS NULL) OR "
            "(status = 'current' AND activated_at IS NOT NULL "
            "AND superseded_at IS NULL AND revoked_at IS NULL) OR "
            "(status = 'superseded' AND activated_at IS NOT NULL "
            "AND superseded_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL))",
            name=op.f(
                "ck_tenant_integration_secret_revisions_lifecycle_times_valid"
            ),
        ),
        sa.CheckConstraint(
            "((verification_status IN ('not_attempted', 'submitting', 'unknown') "
            "AND status = 'pending_validation') OR "
            "(verification_status = 'failed' AND status = 'revoked') OR "
            "(verification_status = 'succeeded' "
            "AND status IN ('current', 'superseded')))",
            name=op.f(
                "ck_tenant_integration_secret_revisions_verify_lifecycle_valid"
            ),
        ),
        sa.CheckConstraint(
            "length(request_digest) = 32",
            name=op.f(
                "ck_tenant_integration_secret_revisions_request_digest_length"
            ),
        ),
        sa.CheckConstraint(
            "length(trim(request_idempotency_key)) >= 1 "
            "AND length(request_idempotency_key) <= 128",
            name=op.f(
                "ck_tenant_integration_secret_revisions_request_key_bounded"
            ),
        ),
        sa.CheckConstraint(
            "expected_integration_row_version >= 1",
            name=op.f(
                "ck_tenant_integration_secret_revisions_expected_int_ver_pos"
            ),
        ),
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
        sa.PrimaryKeyConstraint("id", name="pk_tenant_integration_secret_revisions"),
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
    )
    op.create_index(
        "ix_integration_secret_revisions_integration_status",
        "tenant_integration_secret_revisions",
        ["tenant_integration_id", "status", "revision_no"],
        unique=False,
    )

    op.create_table(
        "tenant_integration_secret_envelope_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "tenant_integration_secret_revision_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column("envelope_generation", sa.BigInteger(), nullable=False),
        sa.Column("from_root_key_version", sa.BigInteger(), nullable=False),
        sa.Column("to_root_key_version", sa.BigInteger(), nullable=False),
        sa.Column("from_crypto_version", sa.Integer(), nullable=False),
        sa.Column("to_crypto_version", sa.Integer(), nullable=False),
        sa.Column("from_aad_version", sa.Integer(), nullable=False),
        sa.Column("to_aad_version", sa.Integer(), nullable=False),
        sa.Column("before_ciphertext_digest", digest_type, nullable=False),
        sa.Column("after_ciphertext_digest", digest_type, nullable=False),
        sa.Column("rotation_run_uuid", sa.String(length=36), nullable=False),
        sa.Column("rotation_action_uuid", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", digest_type, nullable=False),
        sa.Column(
            "safe_outcome",
            sa.String(length=16),
            server_default=sa.text("'succeeded'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "envelope_generation >= 2",
            name=op.f(
                "ck_tenant_integration_secret_envelope_events_gen_rotated"
            ),
        ),
        sa.CheckConstraint(
            "from_root_key_version >= 1 AND to_root_key_version >= 1",
            name=op.f(
                "ck_tenant_integration_secret_envelope_events_root_vers_pos"
            ),
        ),
        sa.CheckConstraint(
            "from_crypto_version >= 1 AND to_crypto_version >= 1",
            name=op.f(
                "ck_tenant_integration_secret_envelope_events_crypto_vers_pos"
            ),
        ),
        sa.CheckConstraint(
            "from_aad_version >= 1 AND to_aad_version >= 1",
            name=op.f(
                "ck_tenant_integration_secret_envelope_events_aad_vers_pos"
            ),
        ),
        sa.CheckConstraint(
            "length(before_ciphertext_digest) = 32",
            name=op.f(
                "ck_tenant_integration_secret_envelope_events_before_hash_len"
            ),
        ),
        sa.CheckConstraint(
            "length(after_ciphertext_digest) = 32",
            name=op.f(
                "ck_tenant_integration_secret_envelope_events_after_hash_len"
            ),
        ),
        sa.CheckConstraint(
            "length(request_digest) = 32",
            name=op.f(
                "ck_tenant_integration_secret_envelope_events_request_hash_len"
            ),
        ),
        sa.CheckConstraint(
            "safe_outcome = 'succeeded'",
            name=op.f(
                "ck_tenant_integration_secret_envelope_events_"
                "outcome_succeeded"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_integration_secret_revision_id"],
            ["tenant_integration_secret_revisions.id"],
            name="fk_tis_envelope_revision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id", name="pk_tenant_integration_secret_envelope_events"
        ),
        sa.UniqueConstraint(
            "tenant_integration_secret_revision_id",
            "envelope_generation",
            name="uq_integration_secret_envelope_events_generation",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_integration_secret_envelope_events_idempotency",
        ),
    )

    op.create_table(
        "tenant_provider_defaults",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("integration_id", sa.String(length=36), nullable=False),
        sa.Column("updated_by", sa.String(length=36), nullable=False),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
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
            "provider IN ('sf', 'xianyu', 'kuaimai')",
            name=op.f("ck_tenant_provider_defaults_provider_valid"),
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name=op.f("ck_tenant_provider_defaults_row_version_positive"),
        ),
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
        sa.PrimaryKeyConstraint(
            "tenant_id", "provider", name="pk_tenant_provider_defaults"
        ),
    )


def downgrade() -> None:
    op.drop_table("tenant_provider_defaults")
    op.drop_table("tenant_integration_secret_envelope_events")
    op.drop_table("tenant_integration_secret_revisions")
    op.drop_table("tenant_integrations")
