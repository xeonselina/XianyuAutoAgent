"""Create immutable encrypted redemption-code records.

Revision ID: 202608220009
Revises: 202608220008
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "202608220009"
down_revision = "202608220008"
branch_labels = None
depends_on = None


SHA256 = sa.LargeBinary(length=32).with_variant(mysql.BINARY(32), "mysql")
NONCE = sa.LargeBinary(length=12).with_variant(mysql.BINARY(12), "mysql")


def upgrade() -> None:
    op.create_table(
        "redemption_code_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("generation_request_uuid", sa.String(length=36), nullable=False),
        sa.Column("request_digest", SHA256, nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=True),
        sa.Column("internal_note", sa.String(length=500), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("plan_revision_uuid", sa.String(length=36), nullable=False),
        sa.Column("entitlements_schema_version", sa.Integer(), nullable=False),
        sa.Column("entitlements_json", sa.JSON(), nullable=False),
        sa.Column("entitlements_digest", SHA256, nullable=False),
        sa.Column("service_duration_seconds", sa.BigInteger(), nullable=False),
        sa.Column("default_redeem_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_platform_admin_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("plaintext_exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(trim(name)) >= 1",
            name="ck_redemption_code_batches_name_nonempty",
        ),
        sa.CheckConstraint(
            "channel IS NULL OR length(trim(channel)) >= 1",
            name="ck_redemption_code_batches_channel_nonempty",
        ),
        sa.CheckConstraint(
            "internal_note IS NULL OR length(trim(internal_note)) >= 1",
            name="ck_redemption_code_batches_internal_note_nonempty",
        ),
        sa.CheckConstraint(
            "quantity >= 1",
            name="ck_redemption_code_batches_quantity_positive",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 32",
            name="ck_redemption_code_batches_request_digest_length",
        ),
        sa.CheckConstraint(
            "entitlements_schema_version >= 1",
            name="ck_redemption_code_batches_entitlements_schema_version_positive",
        ),
        sa.CheckConstraint(
            "length(entitlements_digest) = 32",
            name="ck_redemption_code_batches_entitlements_digest_length",
        ),
        sa.CheckConstraint(
            "service_duration_seconds >= 1",
            name="ck_redemption_code_batches_service_duration_seconds_positive",
        ),
        sa.CheckConstraint(
            "plaintext_exported_at IS NULL OR plaintext_exported_at >= created_at",
            name="ck_redemption_code_batches_plaintext_export_after_creation",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_platform_admin_id"],
            ["platform_admins.id"],
            name="fk_redemption_batches_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plan_revision_uuid", "entitlements_schema_version", "entitlements_digest"],
            ["plans.id", "plans.entitlements_schema_version", "plans.entitlements_digest"],
            name="fk_redemption_batches_plan_snapshot",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_redemption_code_batches"),
        sa.UniqueConstraint(
            "generation_request_uuid",
            name="uq_redemption_batches_generation_request",
        ),
    )

    op.create_table(
        "redemption_codes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("crypto_context_uuid", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("code_prefix", sa.String(length=4), nullable=False),
        sa.Column("lookup_hash", SHA256, nullable=False),
        sa.Column("code_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("code_nonce", NONCE, nullable=False),
        sa.Column("secret_revision", sa.BigInteger(), nullable=False),
        sa.Column("root_key_version", sa.Integer(), nullable=False),
        sa.Column("crypto_version", sa.Integer(), nullable=False),
        sa.Column("aad_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default=sa.text("'active'"), nullable=False),
        sa.Column("plan_revision_uuid", sa.String(length=36), nullable=False),
        sa.Column("entitlements_schema_version", sa.Integer(), nullable=False),
        sa.Column("entitlements_json", sa.JSON(), nullable=False),
        sa.Column("entitlements_digest", SHA256, nullable=False),
        sa.Column("service_duration_seconds", sa.BigInteger(), nullable=False),
        sa.Column("redeem_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reserved_registration_attempt_uuid", sa.String(length=36), nullable=True),
        sa.Column("reserved_user_uuid", sa.String(length=36), nullable=True),
        sa.Column("redeemed_tenant_uuid", sa.String(length=36), nullable=True),
        sa.Column("redeemed_registration_attempt_uuid", sa.String(length=36), nullable=True),
        sa.Column("registration_commit_uuid", sa.String(length=36), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason_code", sa.String(length=64), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_under_recovery_run_uuid", sa.String(length=36), nullable=False),
        sa.Column("recovery_revoked_by_run_uuid", sa.String(length=36), nullable=True),
        sa.Column("recovery_revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(code_prefix) = 4", name="ck_redemption_codes_code_prefix_length"),
        sa.CheckConstraint("length(lookup_hash) = 32", name="ck_redemption_codes_lookup_hash_length"),
        sa.CheckConstraint("length(code_nonce) = 12", name="ck_redemption_codes_code_nonce_length"),
        sa.CheckConstraint("length(code_ciphertext) >= 42", name="ck_redemption_codes_ciphertext_contains_code_and_tag"),
        sa.CheckConstraint("secret_revision >= 1", name="ck_redemption_codes_secret_revision_positive"),
        sa.CheckConstraint("root_key_version >= 1", name="ck_redemption_codes_root_key_version_positive"),
        sa.CheckConstraint("crypto_version >= 1", name="ck_redemption_codes_crypto_version_positive"),
        sa.CheckConstraint("aad_version >= 1", name="ck_redemption_codes_aad_version_positive"),
        sa.CheckConstraint(
            "status IN ('active', 'reserved', 'redeemed', 'revoked', 'expired', 'recovery_revoked')",
            name="ck_redemption_codes_status_valid",
        ),
        sa.CheckConstraint("entitlements_schema_version >= 1", name="ck_redemption_codes_entitlements_schema_version_positive"),
        sa.CheckConstraint("length(entitlements_digest) = 32", name="ck_redemption_codes_entitlements_digest_length"),
        sa.CheckConstraint("service_duration_seconds >= 1", name="ck_redemption_codes_service_duration_seconds_positive"),
        sa.CheckConstraint("row_version >= 1", name="ck_redemption_codes_row_version_positive"),
        sa.CheckConstraint(
            "((reserved_registration_attempt_uuid IS NULL AND reserved_user_uuid IS NULL) OR "
            "(reserved_registration_attempt_uuid IS NOT NULL AND reserved_user_uuid IS NOT NULL))",
            name="ck_redemption_codes_reservation_binding_complete",
        ),
        sa.CheckConstraint(
            "(status <> 'reserved' OR (reserved_registration_attempt_uuid IS NOT NULL AND reserved_user_uuid IS NOT NULL))",
            name="ck_redemption_codes_reserved_status_has_binding",
        ),
        sa.CheckConstraint(
            "(status NOT IN ('active', 'expired') OR "
            "(reserved_registration_attempt_uuid IS NULL AND reserved_user_uuid IS NULL))",
            name="ck_redemption_codes_unowned_status_has_no_reservation",
        ),
        sa.CheckConstraint(
            "((redeemed_registration_attempt_uuid IS NULL AND registration_commit_uuid IS NULL) OR "
            "(redeemed_registration_attempt_uuid IS NOT NULL AND registration_commit_uuid IS NOT NULL))",
            name="ck_redemption_codes_registration_redemption_binding_complete",
        ),
        sa.CheckConstraint(
            "((status = 'redeemed' AND redeemed_tenant_uuid IS NOT NULL AND redeemed_at IS NOT NULL) OR "
            "(status <> 'redeemed' AND redeemed_tenant_uuid IS NULL AND redeemed_at IS NULL "
            "AND redeemed_registration_attempt_uuid IS NULL AND registration_commit_uuid IS NULL))",
            name="ck_redemption_codes_redemption_fields_match_status",
        ),
        sa.CheckConstraint(
            "((status = 'revoked' AND revoked_at IS NOT NULL AND revocation_reason_code IS NOT NULL) OR "
            "(status <> 'revoked' AND revoked_at IS NULL AND revocation_reason_code IS NULL))",
            name="ck_redemption_codes_revocation_fields_match_status",
        ),
        sa.CheckConstraint(
            "((status = 'expired' AND expired_at IS NOT NULL) OR (status <> 'expired' AND expired_at IS NULL))",
            name="ck_redemption_codes_expired_at_matches_status",
        ),
        sa.CheckConstraint(
            "((status = 'recovery_revoked' AND recovery_revoked_by_run_uuid IS NOT NULL "
            "AND recovery_revoked_at IS NOT NULL) OR (status <> 'recovery_revoked' "
            "AND recovery_revoked_by_run_uuid IS NULL AND recovery_revoked_at IS NULL))",
            name="ck_redemption_codes_recovery_revocation_matches_status",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["redemption_code_batches.id"],
            name="fk_redemption_codes_batch_id_redemption_code_batches",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plan_revision_uuid", "entitlements_schema_version", "entitlements_digest"],
            ["plans.id", "plans.entitlements_schema_version", "plans.entitlements_digest"],
            name="fk_redemption_codes_plan_snapshot",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_redemption_codes"),
        sa.UniqueConstraint("crypto_context_uuid", name="uq_redemption_codes_crypto_context"),
        sa.UniqueConstraint("lookup_hash", name="uq_redemption_codes_lookup_hash"),
    )
    op.create_index(
        "ix_redemption_codes_status_deadline",
        "redemption_codes",
        ["status", "redeem_before"],
        unique=False,
    )
    op.create_index(
        "ix_redemption_codes_batch",
        "redemption_codes",
        ["batch_id", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("redemption_codes")
    op.drop_table("redemption_code_batches")
