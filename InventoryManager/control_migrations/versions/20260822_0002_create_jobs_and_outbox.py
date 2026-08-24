"""Create durable background jobs and the system control outbox.

Revision ID: 202608220002
Revises: 202608220001
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from inventory_control.sql_defaults import MicrosecondCurrentTimestamp


revision = "202608220002"
down_revision = "202608220001"
branch_labels = None
depends_on = None


JOB_PROTOCOL_TIMESTAMP_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)


def upgrade() -> None:
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_access_version", sa.BigInteger(), nullable=False),
        sa.Column("job_type", sa.String(length=96), nullable=False),
        sa.Column("resource_key", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("requested_by_type", sa.String(length=32), nullable=False),
        sa.Column("requested_by_id", sa.String(length=36), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "priority", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "attempts", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            server_default=sa.text("3"),
            nullable=False,
        ),
        sa.Column(
            "execution_generation",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("available_at", JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=False),
        sa.Column("not_after", JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_token", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True),
        sa.Column("last_heartbeat_at", JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True),
        sa.Column("blocked_reason_code", sa.String(length=64), nullable=True),
        sa.Column("blocked_at", JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True),
        sa.Column("review_reason_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            JOB_PROTOCOL_TIMESTAMP_TYPE,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            JOB_PROTOCOL_TIMESTAMP_TYPE,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.Column("started_at", JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True),
        sa.Column("completed_at", JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'leased', 'provider_submitting', "
            "'suspension_blocked', 'needs_review', 'recovery_review', "
            "'succeeded', 'failed', 'dead_letter', 'cancelled')",
            name="ck_background_jobs_status_valid",
        ),
        sa.CheckConstraint(
            "priority >= 0", name="ck_background_jobs_priority_nonnegative"
        ),
        sa.CheckConstraint(
            "attempts >= 0", name="ck_background_jobs_attempts_nonnegative"
        ),
        sa.CheckConstraint(
            "max_attempts >= 1", name="ck_background_jobs_max_attempts_positive"
        ),
        sa.CheckConstraint(
            "execution_generation >= 0",
            name="ck_background_jobs_execution_generation_nonnegative",
        ),
        sa.CheckConstraint(
            "((status IN ('leased', 'provider_submitting') "
            "AND lease_owner IS NOT NULL AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(status NOT IN ('leased', 'provider_submitting') "
            "AND lease_owner IS NULL AND lease_token IS NULL "
            "AND lease_expires_at IS NULL))",
            name="ck_background_jobs_lease_matches_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_background_jobs_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_background_jobs"),
        sa.UniqueConstraint(
            "tenant_id",
            "job_type",
            "resource_key",
            "idempotency_key",
            name="uq_background_jobs_effective_idempotency",
        ),
    )
    op.create_index(
        "ix_background_jobs_claim",
        "background_jobs",
        ["status", "available_at", "priority", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_background_jobs_lease_expiry",
        "background_jobs",
        ["status", "lease_expires_at"],
        unique=False,
    )

    op.create_table(
        "control_outbox_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=True),
        sa.Column("tenant_access_version", sa.BigInteger(), nullable=True),
        sa.Column("source_type", sa.String(length=96), nullable=False),
        sa.Column("source_uuid", sa.String(length=36), nullable=False),
        sa.Column("source_generation", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=96), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "state",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "attempts", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            server_default=sa.text("10"),
            nullable=False,
        ),
        sa.Column(
            "execution_generation",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("available_at", JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=False),
        sa.Column("not_after", JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_token", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True),
        sa.Column("last_heartbeat_at", JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("result_digest_version", sa.Integer(), nullable=True),
        sa.Column("result_digest", sa.String(length=128), nullable=True),
        sa.Column("result_mac", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            JOB_PROTOCOL_TIMESTAMP_TYPE,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            JOB_PROTOCOL_TIMESTAMP_TYPE,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.Column("last_attempt_at", JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True),
        sa.Column("completed_at", JOB_PROTOCOL_TIMESTAMP_TYPE, nullable=True),
        sa.CheckConstraint(
            "state IN ('pending', 'leased', 'succeeded', 'cancelled', "
            "'recovery_quarantined')",
            name="ck_control_outbox_events_state_valid",
        ),
        sa.CheckConstraint(
            "attempts >= 0", name="ck_control_outbox_events_attempts_nonnegative"
        ),
        sa.CheckConstraint(
            "max_attempts >= 1",
            name="ck_control_outbox_events_max_attempts_positive",
        ),
        sa.CheckConstraint(
            "source_generation >= 1",
            name="ck_control_outbox_events_source_generation_positive",
        ),
        sa.CheckConstraint(
            "execution_generation >= 0",
            name="ck_control_outbox_events_execution_generation_nonnegative",
        ),
        sa.CheckConstraint(
            "((state = 'leased' AND lease_owner IS NOT NULL "
            "AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'leased' AND lease_owner IS NULL "
            "AND lease_token IS NULL AND lease_expires_at IS NULL))",
            name="ck_control_outbox_events_lease_matches_state",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_control_outbox_events_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_control_outbox_events"),
        sa.UniqueConstraint(
            "source_type",
            "source_uuid",
            "source_generation",
            "event_type",
            "idempotency_key",
            name="uq_control_outbox_events_effective_idempotency",
        ),
    )
    op.create_index(
        "ix_control_outbox_events_claim",
        "control_outbox_events",
        ["state", "available_at", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_control_outbox_events_lease_expiry",
        "control_outbox_events",
        ["state", "lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("control_outbox_events")
    op.drop_table("background_jobs")
