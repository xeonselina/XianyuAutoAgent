"""add shipping execution ledgers

Revision ID: 20260822_shipping_ledgers
Revises: 20260822_inspection_warehouse
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_shipping_ledgers"
down_revision = "20260822_inspection_warehouse"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "outbound_shipments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("rental_id", sa.Integer(), nullable=False),
        sa.Column("origin_warehouse_id", sa.Integer(), nullable=False),
        sa.Column("origin_warehouse_uuid", sa.String(length=36), nullable=False),
        sa.Column("integration_uuid", sa.String(length=36), nullable=False),
        sa.Column("provider_account_uuid", sa.String(length=36), nullable=False),
        sa.Column(
            "integration_secret_revision_uuid",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "provider_account_secret_revision_uuid",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column("binding_revision", sa.BigInteger(), nullable=False),
        sa.Column("account_masked_hint", sa.String(length=64), nullable=False),
        sa.Column("sender_snapshot", sa.JSON(), nullable=False),
        sa.Column("receiver_snapshot", sa.JSON(), nullable=False),
        sa.Column("tracking_check_phone_last4", sa.String(length=4), nullable=False),
        sa.Column("express_type_id", sa.Integer(), nullable=False),
        sa.Column("provider_order_id", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("waybill_no", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("safe_error_code", sa.String(length=64), nullable=True),
        sa.Column("prepared_at", sa.DateTime(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "provider = 'sf'",
            name="ck_outbound_shipments_provider_sf",
        ),
        sa.CheckConstraint(
            "status IN ('prepared', 'provider_submitting', 'submitted', "
            "'cancel_requested', 'cancel_unknown', 'cancelled', "
            "'needs_review', 'failed')",
            name="ck_outbound_shipments_status_valid",
        ),
        sa.CheckConstraint(
            "binding_revision >= 1",
            name="ck_outbound_shipments_binding_revision_positive",
        ),
        sa.ForeignKeyConstraint(
            ["origin_warehouse_id"],
            ["warehouses.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rental_id"],
            ["rentals.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_order_id",
            name="uq_outbound_shipments_provider_order_id",
        ),
        sa.UniqueConstraint(
            "waybill_no",
            name="uq_outbound_shipments_waybill_no",
        ),
    )
    op.create_index(
        "ix_outbound_shipments_rental_status",
        "outbound_shipments",
        ["rental_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_outbound_shipments_tracking_cursor",
        "outbound_shipments",
        ["submitted_at", "id"],
        unique=False,
    )

    op.create_table(
        "provider_operation_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("shipment_id", sa.String(length=36), nullable=False),
        sa.Column("background_job_uuid", sa.String(length=36), nullable=True),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column(
            "integration_secret_revision_uuid",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "provider_account_secret_revision_uuid",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column("binding_revision", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("safe_provider_code", sa.String(length=64), nullable=True),
        sa.Column("response_hash", sa.String(length=64), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "attempt_no >= 1",
            name="ck_provider_attempts_number_positive",
        ),
        sa.CheckConstraint(
            "binding_revision >= 1",
            name="ck_provider_attempts_binding_revision_positive",
        ),
        sa.CheckConstraint(
            "status IN ('prepared', 'provider_submitting', 'succeeded', "
            "'definitive_failure', 'unknown', 'needs_review')",
            name="ck_provider_attempts_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["outbound_shipments.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_provider_attempts_idempotency_key",
        ),
        sa.UniqueConstraint(
            "shipment_id",
            "operation",
            "attempt_no",
            name="uq_provider_attempts_shipment_operation_no",
        ),
    )

    op.create_table(
        "waybill_print_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("shipment_id", sa.String(length=36), nullable=False),
        sa.Column("rental_id", sa.Integer(), nullable=False),
        sa.Column("waybill_no_snapshot", sa.String(length=64), nullable=False),
        sa.Column(
            "first_label_warehouse_uuid",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column("integration_uuid", sa.String(length=36), nullable=False),
        sa.Column("provider_account_uuid", sa.String(length=36), nullable=False),
        sa.Column(
            "integration_secret_revision_uuid",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "provider_account_secret_revision_uuid",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column("binding_revision", sa.BigInteger(), nullable=False),
        sa.Column("return_warehouse_id", sa.Integer(), nullable=False),
        sa.Column("return_warehouse_uuid", sa.String(length=36), nullable=False),
        sa.Column("return_contact_snapshot", sa.JSON(), nullable=False),
        sa.Column("printer_sn_snapshot", sa.String(length=128), nullable=False),
        sa.Column("operator_user_uuid", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_task_id", sa.String(length=128), nullable=True),
        sa.Column("safe_error_code", sa.String(length=64), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "binding_revision >= 1",
            name="ck_waybill_print_jobs_binding_revision_positive",
        ),
        sa.CheckConstraint(
            "status IN ('prepared', 'provider_submitting', 'printed', "
            "'unknown', 'needs_review', 'failed', 'cancelled')",
            name="ck_waybill_print_jobs_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["rental_id"],
            ["rentals.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["return_warehouse_id"],
            ["warehouses.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["shipment_id"],
            ["outbound_shipments.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_waybill_print_jobs_idempotency_key",
        ),
    )
    op.create_index(
        "ix_waybill_print_jobs_shipment_status",
        "waybill_print_jobs",
        ["shipment_id", "status"],
        unique=False,
    )


def downgrade():
    # MySQL may select these composite indexes to enforce the leading-column
    # foreign keys.  Dropping the tables removes their indexes atomically;
    # dropping an index first fails with error 1553 while the FK still exists.
    op.drop_table("waybill_print_jobs")
    op.drop_table("provider_operation_attempts")
    op.drop_table("outbound_shipments")
