"""add durable shipping job intent provenance

Revision ID: 20260823_shipping_intent
Revises: 20260823_xianyu_sync_state
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260823_shipping_intent"
down_revision = "20260823_xianyu_sync_state"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("provider_operation_attempts") as batch_op:
        batch_op.add_column(
            sa.Column("tenant_access_version", sa.BigInteger(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "requested_by_user_uuid",
                sa.String(length=36),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("request_id", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("correlation_id", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("job_enqueued_at", sa.DateTime(), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_provider_attempts_background_job_uuid",
            ["background_job_uuid"],
        )
        batch_op.create_check_constraint(
            "ck_provider_attempts_tenant_access_version_positive",
            "tenant_access_version IS NULL OR tenant_access_version >= 1",
        )
        batch_op.create_check_constraint(
            "ck_provider_attempts_job_intent_provenance",
            "((tenant_access_version IS NULL "
            "AND requested_by_user_uuid IS NULL "
            "AND request_id IS NULL "
            "AND correlation_id IS NULL "
            "AND job_enqueued_at IS NULL) OR "
            "(background_job_uuid IS NOT NULL "
            "AND tenant_access_version IS NOT NULL "
            "AND requested_by_user_uuid IS NOT NULL "
            "AND request_id IS NOT NULL))",
        )
        batch_op.create_index(
            "ix_provider_attempts_job_intent_scan",
            ["operation", "status", "job_enqueued_at", "created_at"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("provider_operation_attempts") as batch_op:
        batch_op.drop_index("ix_provider_attempts_job_intent_scan")
        batch_op.drop_constraint(
            "ck_provider_attempts_job_intent_provenance",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_provider_attempts_tenant_access_version_positive",
            type_="check",
        )
        batch_op.drop_constraint(
            "uq_provider_attempts_background_job_uuid",
            type_="unique",
        )
        batch_op.drop_column("job_enqueued_at")
        batch_op.drop_column("correlation_id")
        batch_op.drop_column("request_id")
        batch_op.drop_column("requested_by_user_uuid")
        batch_op.drop_column("tenant_access_version")
