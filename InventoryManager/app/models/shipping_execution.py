"""Immutable tenant-side shipping and print execution snapshots."""

from datetime import datetime
from uuid import uuid4

from app import db


def _new_uuid():
    return str(uuid4())


class OutboundShipment(db.Model):
    __tablename__ = "outbound_shipments"
    __table_args__ = (
        db.CheckConstraint(
            "provider = 'sf'",
            name="ck_outbound_shipments_provider_sf",
        ),
        db.CheckConstraint(
            "status IN ('prepared', 'provider_submitting', 'submitted', "
            "'cancel_requested', 'cancel_unknown', 'cancelled', "
            "'needs_review', 'failed')",
            name="ck_outbound_shipments_status_valid",
        ),
        db.CheckConstraint(
            "binding_revision >= 1",
            name="ck_outbound_shipments_binding_revision_positive",
        ),
        db.Index(
            "ix_outbound_shipments_rental_status",
            "rental_id",
            "status",
        ),
        db.Index(
            "ix_outbound_shipments_tracking_cursor",
            "submitted_at",
            "id",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=_new_uuid)
    provider = db.Column(db.String(16), nullable=False, default="sf")
    rental_id = db.Column(
        db.Integer,
        db.ForeignKey("rentals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    origin_warehouse_id = db.Column(
        db.Integer,
        db.ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    origin_warehouse_uuid = db.Column(db.String(36), nullable=False)
    integration_uuid = db.Column(db.String(36), nullable=False)
    provider_account_uuid = db.Column(db.String(36), nullable=False)
    integration_secret_revision_uuid = db.Column(db.String(36), nullable=False)
    provider_account_secret_revision_uuid = db.Column(
        db.String(36),
        nullable=False,
    )
    binding_revision = db.Column(db.BigInteger, nullable=False)
    account_masked_hint = db.Column(db.String(64), nullable=False)
    sender_snapshot = db.Column(db.JSON, nullable=False)
    receiver_snapshot = db.Column(db.JSON, nullable=False)
    cargo_snapshot = db.Column(db.JSON, nullable=False)
    tracking_check_phone_last4 = db.Column(db.String(4), nullable=False)
    express_type_id = db.Column(db.Integer, nullable=False)
    scheduled_dispatch_at = db.Column(db.DateTime, nullable=False)
    provider_order_id = db.Column(db.String(128), nullable=False, unique=True)
    request_hash = db.Column(db.String(64), nullable=False)
    waybill_no = db.Column(db.String(64), nullable=True, unique=True)
    status = db.Column(db.String(32), nullable=False, default="prepared")
    safe_error_code = db.Column(db.String(64), nullable=True)
    prepared_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    submitted_at = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    rental = db.relationship("Rental")
    origin_warehouse = db.relationship("Warehouse")


class ProviderOperationAttempt(db.Model):
    __tablename__ = "provider_operation_attempts"
    __table_args__ = (
        db.UniqueConstraint(
            "shipment_id",
            "operation",
            "attempt_no",
            name="uq_provider_attempts_shipment_operation_no",
        ),
        db.UniqueConstraint(
            "idempotency_key",
            name="uq_provider_attempts_idempotency_key",
        ),
        db.UniqueConstraint(
            "background_job_uuid",
            name="uq_provider_attempts_background_job_uuid",
        ),
        db.CheckConstraint(
            "attempt_no >= 1",
            name="ck_provider_attempts_number_positive",
        ),
        db.CheckConstraint(
            "binding_revision >= 1",
            name="ck_provider_attempts_binding_revision_positive",
        ),
        db.CheckConstraint(
            "status IN ('prepared', 'provider_submitting', 'succeeded', "
            "'definitive_failure', 'unknown', 'needs_review')",
            name="ck_provider_attempts_status_valid",
        ),
        db.CheckConstraint(
            "tenant_access_version IS NULL OR tenant_access_version >= 1",
            name="ck_provider_attempts_tenant_access_version_positive",
        ),
        db.CheckConstraint(
            "((tenant_access_version IS NULL "
            "AND requested_by_user_uuid IS NULL "
            "AND request_id IS NULL "
            "AND correlation_id IS NULL "
            "AND job_enqueued_at IS NULL) OR "
            "(background_job_uuid IS NOT NULL "
            "AND tenant_access_version IS NOT NULL "
            "AND requested_by_user_uuid IS NOT NULL "
            "AND request_id IS NOT NULL))",
            name="ck_provider_attempts_job_intent_provenance",
        ),
        db.Index(
            "ix_provider_attempts_job_intent_scan",
            "operation",
            "status",
            "job_enqueued_at",
            "created_at",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=_new_uuid)
    shipment_id = db.Column(
        db.String(36),
        db.ForeignKey("outbound_shipments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    background_job_uuid = db.Column(db.String(36), nullable=True)
    tenant_access_version = db.Column(db.BigInteger, nullable=True)
    requested_by_user_uuid = db.Column(db.String(36), nullable=True)
    request_id = db.Column(db.String(64), nullable=True)
    correlation_id = db.Column(db.String(64), nullable=True)
    job_enqueued_at = db.Column(db.DateTime, nullable=True)
    operation = db.Column(db.String(32), nullable=False)
    idempotency_key = db.Column(db.String(128), nullable=False)
    attempt_no = db.Column(db.Integer, nullable=False)
    integration_secret_revision_uuid = db.Column(db.String(36), nullable=False)
    provider_account_secret_revision_uuid = db.Column(
        db.String(36),
        nullable=False,
    )
    binding_revision = db.Column(db.BigInteger, nullable=False)
    status = db.Column(db.String(32), nullable=False, default="prepared")
    safe_provider_code = db.Column(db.String(64), nullable=True)
    response_hash = db.Column(db.String(64), nullable=True)
    latency_ms = db.Column(db.Integer, nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    shipment = db.relationship("OutboundShipment")


class WaybillPrintJob(db.Model):
    __tablename__ = "waybill_print_jobs"
    __table_args__ = (
        db.UniqueConstraint(
            "idempotency_key",
            name="uq_waybill_print_jobs_idempotency_key",
        ),
        db.CheckConstraint(
            "binding_revision >= 1",
            name="ck_waybill_print_jobs_binding_revision_positive",
        ),
        db.CheckConstraint(
            "status IN ('prepared', 'provider_submitting', 'printed', "
            "'unknown', 'needs_review', 'failed', 'cancelled')",
            name="ck_waybill_print_jobs_status_valid",
        ),
        db.Index(
            "ix_waybill_print_jobs_shipment_status",
            "shipment_id",
            "status",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=_new_uuid)
    shipment_id = db.Column(
        db.String(36),
        db.ForeignKey("outbound_shipments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    rental_id = db.Column(
        db.Integer,
        db.ForeignKey("rentals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    waybill_no_snapshot = db.Column(db.String(64), nullable=False)
    first_label_warehouse_uuid = db.Column(db.String(36), nullable=False)
    integration_uuid = db.Column(db.String(36), nullable=False)
    provider_account_uuid = db.Column(db.String(36), nullable=False)
    integration_secret_revision_uuid = db.Column(db.String(36), nullable=False)
    provider_account_secret_revision_uuid = db.Column(
        db.String(36),
        nullable=False,
    )
    binding_revision = db.Column(db.BigInteger, nullable=False)
    return_warehouse_id = db.Column(
        db.Integer,
        db.ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    return_warehouse_uuid = db.Column(db.String(36), nullable=False)
    return_contact_snapshot = db.Column(db.JSON, nullable=False)
    printer_sn_snapshot = db.Column(db.String(128), nullable=False)
    operator_user_uuid = db.Column(db.String(36), nullable=False)
    idempotency_key = db.Column(db.String(128), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="prepared")
    provider_task_id = db.Column(db.String(128), nullable=True)
    safe_error_code = db.Column(db.String(64), nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    shipment = db.relationship("OutboundShipment")
    rental = db.relationship("Rental")
    return_warehouse = db.relationship("Warehouse")
