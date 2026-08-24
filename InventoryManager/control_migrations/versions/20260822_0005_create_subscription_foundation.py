"""Create plan, member-seat guard, subscription, and event foundations.

Revision ID: 202608220005
Revises: 202608220004
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "202608220005"
down_revision = "202608220004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    digest_type = sa.LargeBinary(length=32).with_variant(
        mysql.BINARY(32), "mysql"
    )

    op.create_table(
        "plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("entitlements_schema_version", sa.Integer(), nullable=False),
        sa.Column("entitlements_json", sa.JSON(), nullable=False),
        sa.Column("entitlements_digest", digest_type, nullable=False),
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.true(),
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
            "length(trim(code)) >= 1", name="ck_plans_code_nonempty"
        ),
        sa.CheckConstraint(
            "length(trim(name)) >= 1", name="ck_plans_name_nonempty"
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_plans_revision_positive"
        ),
        sa.CheckConstraint(
            "entitlements_schema_version >= 1",
            name="ck_plans_entitlements_schema_version_positive",
        ),
        sa.CheckConstraint(
            "length(entitlements_digest) = 32",
            name="ck_plans_entitlements_digest_length",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plans"),
        sa.UniqueConstraint(
            "code", "revision", name="uq_plans_code_revision"
        ),
        sa.UniqueConstraint(
            "id",
            "entitlements_schema_version",
            "entitlements_digest",
            name="uq_plans_snapshot_identity",
        ),
    )

    op.create_table(
        "tenant_quota_guards",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column(
            "quota_key",
            sa.String(length=32),
            server_default=sa.text("'member_seats'"),
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
        sa.CheckConstraint(
            "quota_key = 'member_seats'",
            name="ck_tenant_quota_guards_quota_key_member_seats",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_tenant_quota_guards_row_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_tenant_quota_guards_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "quota_key", name="pk_tenant_quota_guards"
        ),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("plan_revision_uuid", sa.String(length=36), nullable=False),
        sa.Column("entitlements_schema_version", sa.Integer(), nullable=False),
        sa.Column("entitlements_json", sa.JSON(), nullable=False),
        sa.Column("entitlements_digest", digest_type, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "provider",
            sa.String(length=16),
            server_default=sa.text("'manual'"),
            nullable=False,
        ),
        sa.Column("provider_ref", sa.String(length=128), nullable=True),
        sa.Column(
            "created_from_registration_commit_uuid",
            sa.String(length=36),
            nullable=True,
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
            "entitlements_schema_version >= 1",
            name="ck_subscriptions_entitlements_schema_version_positive",
        ),
        sa.CheckConstraint(
            "length(entitlements_digest) = 32",
            name="ck_subscriptions_entitlements_digest_length",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'expired')",
            name="ck_subscriptions_status_valid",
        ),
        sa.CheckConstraint(
            "provider IN ('manual', 'stripe', 'wechat', 'alipay')",
            name="ck_subscriptions_provider_valid",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_subscriptions_row_version_positive",
        ),
        sa.CheckConstraint(
            "provider_ref IS NULL OR length(provider_ref) <= 128",
            name="ck_subscriptions_provider_ref_bounded",
        ),
        sa.CheckConstraint(
            "created_from_registration_commit_uuid IS NULL OR "
            "length(created_from_registration_commit_uuid) = 36",
            name="ck_subscriptions_registration_commit_uuid_shape",
        ),
        sa.ForeignKeyConstraint(
            [
                "plan_revision_uuid",
                "entitlements_schema_version",
                "entitlements_digest",
            ],
            [
                "plans.id",
                "plans.entitlements_schema_version",
                "plans.entitlements_digest",
            ],
            name="fk_subscriptions_plan_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_subscriptions_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_subscriptions"),
        sa.UniqueConstraint(
            "created_from_registration_commit_uuid",
            name="uq_subscriptions_registration_commit",
        ),
        sa.UniqueConstraint(
            "id", "tenant_id", name="uq_subscriptions_id_tenant"
        ),
        sa.UniqueConstraint("tenant_id", name="uq_subscriptions_tenant_id"),
    )
    op.create_index(
        "ix_subscriptions_status_expiry",
        "subscriptions",
        ["status", "expires_at"],
        unique=False,
    )

    op.create_table(
        "subscription_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("subscription_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_uuid", sa.String(length=36), nullable=False),
        sa.Column("consumed_code_uuid", sa.String(length=36), nullable=True),
        sa.Column(
            "before_plan_revision_uuid", sa.String(length=36), nullable=True
        ),
        sa.Column(
            "after_plan_revision_uuid", sa.String(length=36), nullable=False
        ),
        sa.Column("before_entitlements_digest", digest_type, nullable=True),
        sa.Column("after_entitlements_digest", digest_type, nullable=False),
        sa.Column("exact_duration_seconds", sa.BigInteger(), nullable=True),
        sa.Column("signed_delta_days", sa.Integer(), nullable=True),
        sa.Column(
            "calculation_base_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "database_effective_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("before_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("after_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("before_status", sa.String(length=16), nullable=True),
        sa.Column("after_status", sa.String(length=16), nullable=False),
        sa.Column(
            "expected_subscription_row_version", sa.BigInteger(), nullable=True
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", digest_type, nullable=False),
        sa.Column("canonicalization_version", sa.Integer(), nullable=False),
        sa.Column("platform_actor_id", sa.String(length=36), nullable=True),
        sa.Column("platform_session_id", sa.String(length=36), nullable=True),
        sa.Column("factor_method", sa.String(length=32), nullable=True),
        sa.Column(
            "factor_accepted_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("offline_reference", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('activated', 'renewed', 'days_adjusted', "
            "'expired_now', 'migration_granted')",
            name="ck_subscription_events_event_type_valid",
        ),
        sa.CheckConstraint(
            "source_type IN ('registration', 'redemption', "
            "'platform_adjustment', 'migration_grant')",
            name="ck_subscription_events_source_type_valid",
        ),
        sa.CheckConstraint(
            "((source_type = 'registration' AND event_type = 'activated') OR "
            "(source_type = 'redemption' AND event_type = 'renewed') OR "
            "(source_type = 'platform_adjustment' AND event_type IN "
            "('days_adjusted', 'expired_now')) OR "
            "(source_type = 'migration_grant' "
            "AND event_type = 'migration_granted'))",
            name="ck_subscription_events_source_event_match",
        ),
        sa.CheckConstraint(
            "length(source_uuid) = 36",
            name="ck_subscription_events_source_uuid_shape",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 32",
            name="ck_subscription_events_request_digest_length",
        ),
        sa.CheckConstraint(
            "length(trim(idempotency_key)) >= 1 "
            "AND length(idempotency_key) <= 128",
            name="ck_subscription_events_idempotency_key_bounded",
        ),
        sa.CheckConstraint(
            "canonicalization_version >= 1",
            name="ck_subscription_events_canonicalization_version_positive",
        ),
        sa.CheckConstraint(
            "before_entitlements_digest IS NULL OR "
            "length(before_entitlements_digest) = 32",
            name="ck_subscription_events_before_digest_length",
        ),
        sa.CheckConstraint(
            "length(after_entitlements_digest) = 32",
            name="ck_subscription_events_after_digest_length",
        ),
        sa.CheckConstraint(
            "before_status IS NULL OR before_status IN ('active', 'expired')",
            name="ck_subscription_events_before_status_valid",
        ),
        sa.CheckConstraint(
            "after_status IN ('active', 'expired')",
            name="ck_subscription_events_after_status_valid",
        ),
        sa.CheckConstraint(
            "((before_plan_revision_uuid IS NULL "
            "AND before_entitlements_digest IS NULL "
            "AND before_expires_at IS NULL AND before_status IS NULL) OR "
            "(before_plan_revision_uuid IS NOT NULL "
            "AND before_entitlements_digest IS NOT NULL "
            "AND before_expires_at IS NOT NULL AND before_status IS NOT NULL))",
            name="ck_subscription_events_before_snapshot_match",
        ),
        sa.CheckConstraint(
            "((source_type IN ('registration', 'migration_grant') "
            "AND before_plan_revision_uuid IS NULL) OR "
            "(source_type IN ('redemption', 'platform_adjustment') "
            "AND before_plan_revision_uuid IS NOT NULL))",
            name="ck_subscription_events_source_before_snapshot_match",
        ),
        sa.CheckConstraint(
            "((source_type IN ('registration', 'redemption', "
            "'migration_grant') AND exact_duration_seconds > 0 "
            "AND signed_delta_days IS NULL) OR "
            "(source_type = 'platform_adjustment' "
            "AND event_type = 'days_adjusted' "
            "AND exact_duration_seconds IS NULL "
            "AND signed_delta_days <> 0) OR "
            "(source_type = 'platform_adjustment' "
            "AND event_type = 'expired_now' "
            "AND exact_duration_seconds IS NULL "
            "AND signed_delta_days IS NULL))",
            name="ck_subscription_events_term_input_match",
        ),
        sa.CheckConstraint(
            "((source_type IN ('registration', 'redemption') "
            "AND consumed_code_uuid IS NOT NULL) OR "
            "(source_type IN ('platform_adjustment', 'migration_grant') "
            "AND consumed_code_uuid IS NULL))",
            name="ck_subscription_events_consumed_code_match",
        ),
        sa.CheckConstraint(
            "consumed_code_uuid IS NULL OR length(consumed_code_uuid) = 36",
            name="ck_subscription_events_consumed_code_uuid_shape",
        ),
        sa.CheckConstraint(
            "expected_subscription_row_version IS NULL OR "
            "expected_subscription_row_version >= 1",
            name="ck_subscription_events_expected_revision_positive",
        ),
        sa.CheckConstraint(
            "factor_method IS NULL OR factor_method IN ('totp', 'recovery_code')",
            name="ck_subscription_events_factor_method_valid",
        ),
        sa.CheckConstraint(
            "platform_actor_id IS NULL OR length(platform_actor_id) = 36",
            name="ck_subscription_events_platform_actor_uuid_shape",
        ),
        sa.CheckConstraint(
            "platform_session_id IS NULL OR length(platform_session_id) = 36",
            name="ck_subscription_events_platform_session_uuid_shape",
        ),
        sa.CheckConstraint(
            "((source_type = 'platform_adjustment' "
            "AND platform_actor_id IS NOT NULL "
            "AND platform_session_id IS NOT NULL "
            "AND factor_method IS NOT NULL "
            "AND factor_accepted_at IS NOT NULL) OR "
            "(source_type <> 'platform_adjustment' "
            "AND platform_actor_id IS NULL "
            "AND platform_session_id IS NULL "
            "AND factor_method IS NULL AND factor_accepted_at IS NULL))",
            name="ck_subscription_events_platform_evidence_match",
        ),
        sa.CheckConstraint(
            "source_type <> 'platform_adjustment' OR "
            "(before_plan_revision_uuid = after_plan_revision_uuid "
            "AND before_entitlements_digest = after_entitlements_digest)",
            name="ck_subscription_events_platform_snapshot_same",
        ),
        sa.CheckConstraint(
            "source_type <> 'migration_grant' OR "
            "exact_duration_seconds = 3153600000",
            name="ck_subscription_events_migration_duration_exact",
        ),
        sa.CheckConstraint(
            "length(trim(reason_code)) >= 1 AND length(reason_code) <= 64",
            name="ck_subscription_events_reason_code_bounded",
        ),
        sa.CheckConstraint(
            "note IS NULL OR length(note) <= 500",
            name="ck_subscription_events_note_bounded",
        ),
        sa.CheckConstraint(
            "offline_reference IS NULL OR length(offline_reference) <= 128",
            name="ck_subscription_events_offline_reference_bounded",
        ),
        sa.CheckConstraint(
            "offline_reference IS NULL OR source_type = 'platform_adjustment'",
            name="ck_subscription_events_offline_ref_source",
        ),
        sa.ForeignKeyConstraint(
            ["after_plan_revision_uuid"],
            ["plans.id"],
            name="fk_subscription_events_after_plan",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["before_plan_revision_uuid"],
            ["plans.id"],
            name="fk_subscription_events_before_plan",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id", "tenant_id"],
            ["subscriptions.id", "subscriptions.tenant_id"],
            name="fk_subscription_events_subscription_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_subscription_events"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_subscription_events_idempotency_key",
        ),
        sa.UniqueConstraint(
            "source_uuid", name="uq_subscription_events_source_uuid"
        ),
    )
    op.create_index(
        "ix_subscription_events_tenant_effective",
        "subscription_events",
        ["tenant_id", "database_effective_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("subscription_events")
    op.drop_table("subscriptions")
    op.drop_table("tenant_quota_guards")
    op.drop_table("plans")
