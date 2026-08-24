"""Read-only migration snapshots with deliberately no execution authority."""

from datetime import datetime
from uuid import uuid4

from app import db


LEGACY_UNATTRIBUTED_KIND = "legacy_unattributed"


def _new_uuid() -> str:
    return str(uuid4())


class LegacyUnattributedShipmentSnapshot(db.Model):
    """Legacy lifecycle/tracking facts that can never resolve a provider."""

    __tablename__ = "legacy_unattributed_shipments"
    __table_args__ = (
        db.CheckConstraint(
            "snapshot_kind = 'legacy_unattributed'",
            name="ck_legacy_unattributed_shipments_kind",
        ),
        db.CheckConstraint(
            "lifecycle_status IN ('not_shipped', 'scheduled_for_shipping', "
            "'shipped', 'returned', 'completed', 'cancelled')",
            name="ck_legacy_unattributed_shipments_status",
        ),
        db.UniqueConstraint(
            "source_rental_id",
            name="uq_legacy_unattributed_shipments_source_rental",
        ),
        db.Index(
            "ix_legacy_unattributed_shipments_created",
            "created_at",
            "id",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=_new_uuid)
    snapshot_kind = db.Column(
        db.String(32),
        nullable=False,
        default=LEGACY_UNATTRIBUTED_KIND,
    )
    source_rental_id = db.Column(db.Integer, nullable=False)
    rental_id = db.Column(
        db.Integer,
        db.ForeignKey("rentals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    lifecycle_status = db.Column(db.String(32), nullable=False)
    ship_out_tracking_no = db.Column(db.String(64), nullable=True)
    ship_in_tracking_no = db.Column(db.String(64), nullable=True)
    shipped_at = db.Column(db.DateTime, nullable=True)
    returned_at = db.Column(db.DateTime, nullable=True)
    source_digest = db.Column(db.String(64), nullable=False)
    migration_manifest_digest = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    rental = db.relationship("Rental")


class LegacyUnattributedPrintSnapshot(db.Model):
    """Occurrence-only print history with no printer or provider task."""

    __tablename__ = "legacy_unattributed_prints"
    __table_args__ = (
        db.CheckConstraint(
            "snapshot_kind = 'legacy_unattributed'",
            name="ck_legacy_unattributed_prints_kind",
        ),
        db.UniqueConstraint(
            "source_audit_id",
            name="uq_legacy_unattributed_prints_source_audit",
        ),
        db.Index(
            "ix_legacy_unattributed_prints_occurred",
            "occurred_at",
            "id",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=_new_uuid)
    snapshot_kind = db.Column(
        db.String(32),
        nullable=False,
        default=LEGACY_UNATTRIBUTED_KIND,
    )
    source_audit_id = db.Column(db.Integer, nullable=False)
    rental_id = db.Column(
        db.Integer,
        db.ForeignKey("rentals.id", ondelete="SET NULL"),
        nullable=True,
    )
    shipment_snapshot_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "legacy_unattributed_shipments.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    occurred_at = db.Column(db.DateTime, nullable=True)
    source_digest = db.Column(db.String(64), nullable=False)
    migration_manifest_digest = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    rental = db.relationship("Rental")
    shipment_snapshot = db.relationship("LegacyUnattributedShipmentSnapshot")


__all__ = [
    "LEGACY_UNATTRIBUTED_KIND",
    "LegacyUnattributedPrintSnapshot",
    "LegacyUnattributedShipmentSnapshot",
]
