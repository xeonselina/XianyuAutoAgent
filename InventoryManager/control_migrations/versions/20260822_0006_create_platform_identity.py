"""Create the independent platform-administrator identity boundary.

Revision ID: 202608220006
Revises: 202608220005
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "202608220006"
down_revision = "202608220005"
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
        "platform_admins",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("username_canonical", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default=sa.text("'setup_pending'"),
            nullable=False,
        ),
        sa.Column("password_hash_encoded", sa.String(length=512), nullable=True),
        sa.Column("password_hash_algorithm", sa.String(length=32), nullable=True),
        sa.Column("password_hash_version", sa.Integer(), nullable=True),
        sa.Column(
            "auth_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "setup_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "totp_generation",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "recovery_code_generation",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
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
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('setup_pending', 'recovery_pending', 'active', 'disabled')",
            name="ck_platform_admins_status_valid",
        ),
        sa.CheckConstraint(
            "length(username_canonical) BETWEEN 3 AND 64",
            name="ck_platform_admins_username_length_valid",
        ),
        sa.CheckConstraint(
            "username_canonical = lower(username_canonical)",
            name="ck_platform_admins_username_lowercase",
        ),
        sa.CheckConstraint(
            "auth_version >= 1", name="ck_platform_admins_auth_version_positive"
        ),
        sa.CheckConstraint(
            "setup_version >= 1", name="ck_platform_admins_setup_version_positive"
        ),
        sa.CheckConstraint(
            "totp_generation >= 1",
            name="ck_platform_admins_totp_generation_positive",
        ),
        sa.CheckConstraint(
            "recovery_code_generation >= 1",
            name="ck_platform_admins_recovery_code_generation_positive",
        ),
        sa.CheckConstraint(
            "password_hash_version IS NULL OR password_hash_version >= 1",
            name="ck_platform_admins_password_hash_version_positive",
        ),
        sa.CheckConstraint(
            "((password_hash_encoded IS NULL "
            "AND password_hash_algorithm IS NULL "
            "AND password_hash_version IS NULL) OR "
            "(password_hash_encoded IS NOT NULL "
            "AND password_hash_algorithm IS NOT NULL "
            "AND password_hash_version IS NOT NULL))",
            name="ck_platform_admins_password_hash_fields_consistent",
        ),
        sa.CheckConstraint(
            "(status <> 'active' OR password_hash_encoded IS NOT NULL)",
            name="ck_platform_admins_active_requires_password",
        ),
        sa.CheckConstraint(
            "row_version >= 1", name="ck_platform_admins_row_version_positive"
        ),
        sa.CheckConstraint(
            "updated_at >= created_at",
            name="ck_platform_admins_updated_after_creation",
        ),
        sa.CheckConstraint(
            "((status = 'disabled' AND disabled_at IS NOT NULL) OR "
            "(status <> 'disabled' AND disabled_at IS NULL))",
            name="ck_platform_admins_disabled_at_matches_status",
        ),
        sa.CheckConstraint(
            "disabled_at IS NULL OR disabled_at >= created_at",
            name="ck_platform_admins_disabled_after_creation",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_platform_admins"),
        sa.UniqueConstraint(
            "username_canonical",
            name="uq_platform_admins_username_canonical",
        ),
    )

    op.create_table(
        "platform_admin_totp_credentials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("platform_admin_id", sa.String(length=36), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("secret_revision", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("seed_nonce", nonce_type, nullable=False),
        sa.Column("seed_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("root_key_version", sa.Integer(), nullable=False),
        sa.Column("crypto_version", sa.Integer(), nullable=False),
        sa.Column("aad_version", sa.Integer(), nullable=False),
        sa.Column(
            "totp_algorithm",
            sa.String(length=16),
            server_default=sa.text("'SHA1'"),
            nullable=False,
        ),
        sa.Column(
            "totp_digits",
            sa.Integer(),
            server_default=sa.text("6"),
            nullable=False,
        ),
        sa.Column(
            "totp_period_seconds",
            sa.Integer(),
            server_default=sa.text("30"),
            nullable=False,
        ),
        sa.Column("last_accepted_time_step", sa.BigInteger(), nullable=True),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "current_confirmed_admin_id",
            sa.String(length=36),
            sa.Computed(
                "CASE WHEN status = 'confirmed' THEN platform_admin_id ELSE NULL END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.CheckConstraint(
            "generation >= 1",
            name="ck_platform_admin_totp_credentials_generation_positive",
        ),
        sa.CheckConstraint(
            "secret_revision >= 1",
            name="ck_platform_admin_totp_credentials_secret_revision_positive",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'replaced', 'revoked')",
            name="ck_platform_admin_totp_credentials_status_valid",
        ),
        sa.CheckConstraint(
            "length(seed_nonce) = 12",
            name="ck_platform_admin_totp_credentials_seed_nonce_length",
        ),
        sa.CheckConstraint(
            "length(seed_ciphertext) >= 16",
            name="ck_platform_admin_totp_credentials_seed_ciphertext_has_tag",
        ),
        sa.CheckConstraint(
            "root_key_version >= 1",
            name="ck_platform_admin_totp_credentials_root_key_version_positive",
        ),
        sa.CheckConstraint(
            "crypto_version >= 1",
            name="ck_platform_admin_totp_credentials_crypto_version_positive",
        ),
        sa.CheckConstraint(
            "aad_version >= 1",
            name="ck_platform_admin_totp_credentials_aad_version_positive",
        ),
        sa.CheckConstraint(
            "totp_algorithm = 'SHA1'",
            name="ck_platform_admin_totp_credentials_totp_algorithm_valid",
        ),
        sa.CheckConstraint(
            "totp_digits IN (6, 8)",
            name="ck_platform_admin_totp_credentials_totp_digits_valid",
        ),
        sa.CheckConstraint(
            "totp_period_seconds >= 15",
            name="ck_platform_admin_totp_credentials_totp_period_positive",
        ),
        sa.CheckConstraint(
            "last_accepted_time_step IS NULL OR last_accepted_time_step >= 0",
            name="ck_platform_admin_totp_credentials_last_step_nonnegative",
        ),
        sa.CheckConstraint(
            "((status = 'pending' AND confirmed_at IS NULL "
            "AND retired_at IS NULL) OR "
            "(status = 'confirmed' AND confirmed_at IS NOT NULL "
            "AND retired_at IS NULL) OR "
            "(status IN ('replaced', 'revoked') AND retired_at IS NOT NULL))",
            name="ck_platform_admin_totp_credentials_lifecycle_valid",
        ),
        sa.CheckConstraint(
            "confirmed_at IS NULL OR confirmed_at >= created_at",
            name="ck_platform_admin_totp_credentials_confirmed_after_creation",
        ),
        sa.CheckConstraint(
            "retired_at IS NULL OR retired_at >= created_at",
            name="ck_platform_admin_totp_credentials_retired_after_creation",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_platform_admin_totp_credentials_row_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["platform_admin_id"],
            ["platform_admins.id"],
            name="fk_pa_totp_admin",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id", name="pk_platform_admin_totp_credentials"
        ),
        sa.UniqueConstraint(
            "platform_admin_id",
            "generation",
            name="uq_platform_admin_totp_admin_generation",
        ),
        sa.UniqueConstraint(
            "current_confirmed_admin_id",
            name="uq_platform_admin_totp_current_confirmed",
        ),
    )
    op.create_index(
        "ix_platform_admin_totp_admin_status_generation",
        "platform_admin_totp_credentials",
        ["platform_admin_id", "status", "generation"],
        unique=False,
    )

    op.create_table(
        "platform_admin_recovery_codes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("platform_admin_id", sa.String(length=36), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("token_digest_sha256", digest_type, nullable=False),
        sa.Column(
            "state",
            sa.String(length=16),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "generation >= 1",
            name="ck_platform_admin_recovery_codes_generation_positive",
        ),
        sa.CheckConstraint(
            "ordinal >= 1",
            name="ck_platform_admin_recovery_codes_ordinal_positive",
        ),
        sa.CheckConstraint(
            "length(token_digest_sha256) = 32",
            name=(
                "ck_platform_admin_recovery_codes_"
                "token_digest_sha256_length"
            ),
        ),
        sa.CheckConstraint(
            "state IN ('active', 'consumed', 'revoked')",
            name="ck_platform_admin_recovery_codes_state_valid",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="ck_platform_admin_recovery_codes_expiry_after_creation",
        ),
        sa.CheckConstraint(
            "((state = 'active' AND consumed_at IS NULL "
            "AND revoked_at IS NULL) OR "
            "(state = 'consumed' AND consumed_at IS NOT NULL "
            "AND revoked_at IS NULL) OR "
            "(state = 'revoked' AND consumed_at IS NULL "
            "AND revoked_at IS NOT NULL))",
            name="ck_platform_admin_recovery_codes_lifecycle_valid",
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR (consumed_at >= created_at AND "
            "(expires_at IS NULL OR consumed_at < expires_at))",
            name="ck_platform_admin_recovery_codes_consumed_within_lifetime",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_platform_admin_recovery_codes_revoked_after_creation",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_platform_admin_recovery_codes_row_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["platform_admin_id"],
            ["platform_admins.id"],
            name="fk_pa_recovery_admin",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id", name="pk_platform_admin_recovery_codes"
        ),
        sa.UniqueConstraint(
            "platform_admin_id",
            "generation",
            "ordinal",
            name="uq_platform_admin_recovery_admin_generation_ordinal",
        ),
        sa.UniqueConstraint(
            "token_digest_sha256",
            name="uq_platform_admin_recovery_codes_token_digest_sha256",
        ),
    )
    op.create_index(
        "ix_platform_admin_recovery_admin_generation_state",
        "platform_admin_recovery_codes",
        ["platform_admin_id", "generation", "state"],
        unique=False,
    )

    op.create_table(
        "platform_admin_setup_challenges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("platform_admin_id", sa.String(length=36), nullable=False),
        sa.Column("setup_version", sa.BigInteger(), nullable=False),
        sa.Column("token_digest_sha256", digest_type, nullable=False),
        sa.Column(
            "state",
            sa.String(length=16),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "setup_version >= 1",
            name="ck_platform_admin_setup_challenges_setup_version_positive",
        ),
        sa.CheckConstraint(
            "length(token_digest_sha256) = 32",
            name=(
                "ck_platform_admin_setup_challenges_"
                "token_digest_sha256_length"
            ),
        ),
        sa.CheckConstraint(
            "state IN ('active', 'consumed', 'revoked')",
            name="ck_platform_admin_setup_challenges_state_valid",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_platform_admin_setup_challenges_expiry_after_creation",
        ),
        sa.CheckConstraint(
            "((state = 'active' AND consumed_at IS NULL "
            "AND revoked_at IS NULL) OR "
            "(state = 'consumed' AND consumed_at IS NOT NULL "
            "AND revoked_at IS NULL) OR "
            "(state = 'revoked' AND consumed_at IS NULL "
            "AND revoked_at IS NOT NULL))",
            name="ck_platform_admin_setup_challenges_lifecycle_valid",
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR (consumed_at >= created_at "
            "AND consumed_at < expires_at)",
            name="ck_platform_admin_setup_challenges_consumed_within_lifetime",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_platform_admin_setup_challenges_revoked_after_creation",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_platform_admin_setup_challenges_row_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["platform_admin_id"],
            ["platform_admins.id"],
            name="fk_pa_setup_admin",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id", name="pk_platform_admin_setup_challenges"
        ),
        sa.UniqueConstraint(
            "platform_admin_id",
            "setup_version",
            name="uq_platform_admin_setup_admin_version",
        ),
        sa.UniqueConstraint(
            "token_digest_sha256",
            name="uq_platform_admin_setup_challenges_token_digest_sha256",
        ),
    )
    op.create_index(
        "ix_platform_admin_setup_active_expiry",
        "platform_admin_setup_challenges",
        ["platform_admin_id", "state", "expires_at"],
        unique=False,
    )

    op.create_table(
        "platform_admin_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("platform_admin_id", sa.String(length=36), nullable=False),
        sa.Column("token_digest_sha256", digest_type, nullable=False),
        sa.Column("csrf_digest_sha256", digest_type, nullable=False),
        sa.Column("auth_version_at_issue", sa.BigInteger(), nullable=False),
        sa.Column("setup_version_at_issue", sa.BigInteger(), nullable=False),
        sa.Column("mfa_method", sa.String(length=24), nullable=False),
        sa.Column("mfa_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("totp_credential_id", sa.String(length=36), nullable=True),
        sa.Column("totp_time_step", sa.BigInteger(), nullable=True),
        sa.Column("recovery_code_id", sa.String(length=36), nullable=True),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column(
            "csrf_generation",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("idle_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "absolute_expires_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason_code", sa.String(length=64), nullable=True),
        sa.Column("revoked_by_session_id", sa.String(length=36), nullable=True),
        sa.Column("device_name", sa.String(length=100), nullable=True),
        sa.Column("user_agent_summary", sa.String(length=255), nullable=True),
        sa.Column("first_ip_summary", sa.String(length=64), nullable=True),
        sa.Column("last_ip_summary", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "length(token_digest_sha256) = 32",
            name="ck_platform_admin_sessions_token_digest_sha256_length",
        ),
        sa.CheckConstraint(
            "length(csrf_digest_sha256) = 32",
            name="ck_platform_admin_sessions_csrf_digest_sha256_length",
        ),
        sa.CheckConstraint(
            "auth_version_at_issue >= 1",
            name="ck_platform_admin_sessions_auth_version_at_issue_positive",
        ),
        sa.CheckConstraint(
            "setup_version_at_issue >= 1",
            name="ck_platform_admin_sessions_setup_version_at_issue_positive",
        ),
        sa.CheckConstraint(
            "policy_version >= 1",
            name="ck_platform_admin_sessions_policy_version_positive",
        ),
        sa.CheckConstraint(
            "csrf_generation >= 1",
            name="ck_platform_admin_sessions_csrf_generation_positive",
        ),
        sa.CheckConstraint(
            "idle_timeout_seconds >= 1",
            name="ck_platform_admin_sessions_idle_timeout_seconds_positive",
        ),
        sa.CheckConstraint(
            "mfa_method IN ('totp', 'recovery_code')",
            name="ck_platform_admin_sessions_mfa_method_valid",
        ),
        sa.CheckConstraint(
            "((mfa_method = 'totp' AND totp_credential_id IS NOT NULL "
            "AND recovery_code_id IS NULL AND totp_time_step IS NOT NULL) OR "
            "(mfa_method = 'recovery_code' AND totp_credential_id IS NULL "
            "AND recovery_code_id IS NOT NULL AND totp_time_step IS NULL))",
            name="ck_platform_admin_sessions_mfa_provenance_matches_method",
        ),
        sa.CheckConstraint(
            "totp_time_step IS NULL OR totp_time_step >= 0",
            name="ck_platform_admin_sessions_totp_time_step_nonnegative",
        ),
        sa.CheckConstraint(
            "idle_expires_at <= absolute_expires_at",
            name="ck_platform_admin_sessions_idle_before_absolute_expiry",
        ),
        sa.CheckConstraint(
            "mfa_verified_at <= created_at",
            name="ck_platform_admin_sessions_mfa_before_creation",
        ),
        sa.CheckConstraint(
            "last_seen_at >= created_at",
            name="ck_platform_admin_sessions_last_seen_after_creation",
        ),
        sa.CheckConstraint(
            "idle_expires_at > last_seen_at",
            name="ck_platform_admin_sessions_idle_after_last_seen",
        ),
        sa.CheckConstraint(
            "absolute_expires_at > created_at",
            name="ck_platform_admin_sessions_absolute_expiry_after_creation",
        ),
        sa.CheckConstraint(
            "((revoked_at IS NULL AND revoked_reason_code IS NULL "
            "AND revoked_by_session_id IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_reason_code IS NOT NULL))",
            name="ck_platform_admin_sessions_revocation_fields_consistent",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_platform_admin_sessions_revoked_after_creation",
        ),
        sa.ForeignKeyConstraint(
            ["platform_admin_id"],
            ["platform_admins.id"],
            name="fk_platform_admin_sessions_platform_admin_id_platform_admins",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["totp_credential_id"],
            ["platform_admin_totp_credentials.id"],
            name="fk_pa_session_totp",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recovery_code_id"],
            ["platform_admin_recovery_codes.id"],
            name="fk_pa_session_recovery",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_session_id"],
            ["platform_admin_sessions.id"],
            name="fk_platform_admin_sessions_revoked_by_session",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_platform_admin_sessions"),
        sa.UniqueConstraint(
            "token_digest_sha256",
            name="uq_platform_admin_sessions_token_digest_sha256",
        ),
        sa.UniqueConstraint(
            "csrf_digest_sha256",
            name="uq_platform_admin_sessions_csrf_digest_sha256",
        ),
    )
    op.create_index(
        "ix_platform_admin_sessions_admin_active_expiry",
        "platform_admin_sessions",
        ["platform_admin_id", "revoked_at", "absolute_expires_at"],
        unique=False,
    )

    op.create_table(
        "platform_admin_rate_limit_counters",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("subject_digest_sha256", digest_type, nullable=False),
        sa.Column("window_kind", sa.String(length=24), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
            "scope IN ('password', 'mfa', 'setup', 'code_reveal')",
            name="ck_platform_admin_rate_limit_counters_scope_valid",
        ),
        sa.CheckConstraint(
            "window_kind IN ('rolling_hour', 'calendar_day', 'device_burst')",
            name="ck_platform_admin_rate_limit_counters_window_kind_valid",
        ),
        sa.CheckConstraint(
            "length(subject_digest_sha256) = 32",
            name="ck_platform_admin_rate_limit_counters_subject_digest_length",
        ),
        sa.CheckConstraint(
            "attempt_count >= 1",
            name="ck_platform_admin_rate_limit_counters_attempt_count_positive",
        ),
        sa.CheckConstraint(
            "policy_version >= 1",
            name="ck_platform_admin_rate_limit_counters_policy_version_positive",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_platform_admin_rate_limit_counters_row_version_positive",
        ),
        sa.CheckConstraint(
            "expires_at > window_started_at",
            name="ck_platform_admin_rate_limit_counters_expiry_after_start",
        ),
        sa.CheckConstraint(
            "blocked_until IS NULL OR blocked_until <= expires_at",
            name="ck_platform_admin_rate_limit_counters_block_within_window",
        ),
        sa.CheckConstraint(
            "updated_at >= created_at",
            name="ck_platform_admin_rate_limit_counters_updated_after_creation",
        ),
        sa.PrimaryKeyConstraint(
            "id", name="pk_platform_admin_rate_limit_counters"
        ),
        sa.UniqueConstraint(
            "scope",
            "subject_digest_sha256",
            "window_kind",
            "window_started_at",
            name="uq_platform_admin_rate_limit_window",
        ),
    )
    op.create_index(
        "ix_platform_admin_rate_limit_expiry",
        "platform_admin_rate_limit_counters",
        ["scope", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("platform_admin_rate_limit_counters")
    op.drop_table("platform_admin_sessions")
    op.drop_table("platform_admin_setup_challenges")
    op.drop_table("platform_admin_recovery_codes")
    op.drop_table("platform_admin_totp_credentials")
    op.drop_table("platform_admins")
