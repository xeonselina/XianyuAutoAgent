"""Tenant-database logical accessory inventory facts.

Logical unit identifiers are implementation details.  Deliberately do not add
``to_dict`` methods here: tenant-facing serializers expose accessory types and
aggregated quantities, never unit or link identifiers.
"""

from datetime import datetime
from uuid import uuid4

from app import db


def _new_uuid():
    return str(uuid4())


class AccessoryType(db.Model):
    __tablename__ = "accessory_types"
    __table_args__ = (
        db.CheckConstraint(
            "tracking_mode IN ('device_bound', 'logical_unit')",
            name="ck_accessory_types_tracking_mode_valid",
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    display_name = db.Column(db.String(100), nullable=False)
    tracking_mode = db.Column(db.String(32), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    display_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class DeviceAccessoryConfig(db.Model):
    __tablename__ = "device_accessory_configs"

    device_id = db.Column(
        db.Integer,
        db.ForeignKey("devices.id", ondelete="CASCADE"),
        primary_key=True,
    )
    accessory_type_id = db.Column(
        db.Integer,
        db.ForeignKey("accessory_types.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    device = db.relationship("Device")
    accessory_type = db.relationship("AccessoryType")


class AccessoryUnit(db.Model):
    __tablename__ = "accessory_units"
    __table_args__ = (
        db.UniqueConstraint(
            "id",
            "accessory_type_id",
            name="uq_accessory_units_id_type",
        ),
        db.UniqueConstraint(
            "legacy_source_type",
            "legacy_source_id",
            name="uq_accessory_units_legacy_source",
        ),
        db.CheckConstraint(
            "condition_status IN "
            "('active', 'maintenance', 'lost', 'retired')",
            name="ck_accessory_units_condition_valid",
        ),
        db.CheckConstraint(
            "row_version >= 1",
            name="ck_accessory_units_row_version_positive",
        ),
        db.Index(
            "ix_accessory_units_availability",
            "accessory_type_id",
            "warehouse_id",
            "condition_status",
            "current_holder_rental_id",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=_new_uuid)
    accessory_type_id = db.Column(
        db.Integer,
        db.ForeignKey("accessory_types.id", ondelete="RESTRICT"),
        nullable=False,
    )
    warehouse_id = db.Column(
        db.Integer,
        db.ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    current_holder_rental_id = db.Column(
        db.Integer,
        db.ForeignKey("rentals.id", ondelete="RESTRICT"),
        nullable=True,
    )
    condition_status = db.Column(db.String(32), nullable=False, default="active")
    legacy_source_type = db.Column(db.String(64), nullable=True)
    legacy_source_id = db.Column(db.String(128), nullable=True)
    row_version = db.Column(db.BigInteger, nullable=False, default=1)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    accessory_type = db.relationship("AccessoryType")
    warehouse = db.relationship("Warehouse")
    current_holder_rental = db.relationship("Rental")


class RentalAccessoryRequest(db.Model):
    __tablename__ = "rental_accessory_requests"
    __table_args__ = (
        db.Index(
            "ix_rental_accessory_requests_type_rental",
            "accessory_type_id",
            "rental_id",
        ),
    )

    rental_id = db.Column(
        db.Integer,
        db.ForeignKey("rentals.id", ondelete="CASCADE"),
        primary_key=True,
    )
    accessory_type_id = db.Column(
        db.Integer,
        db.ForeignKey("accessory_types.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    name_snapshot = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    rental = db.relationship("Rental")
    accessory_type = db.relationship("AccessoryType")


class RentalAccessoryUnitLink(db.Model):
    __tablename__ = "rental_accessory_unit_links"
    __table_args__ = (
        db.UniqueConstraint(
            "rental_id",
            "accessory_type_id",
            name="uq_rental_accessory_links_rental_type",
        ),
        db.UniqueConstraint(
            "rental_id",
            "accessory_unit_id",
            name="uq_rental_accessory_links_rental_unit",
        ),
        db.ForeignKeyConstraint(
            ["accessory_unit_id", "accessory_type_id"],
            ["accessory_units.id", "accessory_units.accessory_type_id"],
            name="fk_rental_accessory_links_unit_type",
            ondelete="RESTRICT",
        ),
        db.CheckConstraint(
            "reservation_start_at < reservation_end_at",
            name="ck_rental_accessory_links_window_valid",
        ),
        db.Index(
            "ix_rental_accessory_links_unit_window",
            "accessory_unit_id",
            "reservation_start_at",
            "reservation_end_at",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=_new_uuid)
    rental_id = db.Column(
        db.Integer,
        db.ForeignKey("rentals.id", ondelete="CASCADE"),
        nullable=False,
    )
    accessory_type_id = db.Column(
        db.Integer,
        db.ForeignKey("accessory_types.id", ondelete="RESTRICT"),
        nullable=False,
    )
    accessory_unit_id = db.Column(db.String(36), nullable=False)
    reservation_start_at = db.Column(db.DateTime, nullable=False)
    reservation_end_at = db.Column(db.DateTime, nullable=False)
    source_relay_case_id = db.Column(
        db.Integer,
        db.ForeignKey("rental_relay_cases.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    rental = db.relationship("Rental")
    accessory_type = db.relationship(
        "AccessoryType",
        foreign_keys=[accessory_type_id],
        viewonly=True,
    )
    accessory_unit = db.relationship("AccessoryUnit")
    source_relay_case = db.relationship("RentalRelayCase")


class AccessoryUnitEvent(db.Model):
    __tablename__ = "accessory_unit_events"
    __table_args__ = (
        db.UniqueConstraint(
            "idempotency_key",
            name="uq_accessory_unit_events_idempotency",
        ),
        db.CheckConstraint(
            "event_type IN ('created', 'linked', 'unlinked', 'dispatched', "
            "'relay_handoff', 'inspected', 'warehouse_moved', "
            "'maintenance', 'lost', 'restored', 'retired')",
            name="ck_accessory_unit_events_type_valid",
        ),
        db.Index("ix_accessory_unit_events_unit_occurred", "unit_id", "occurred_at"),
    )

    id = db.Column(db.String(36), primary_key=True, default=_new_uuid)
    unit_id = db.Column(
        db.String(36),
        db.ForeignKey("accessory_units.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type = db.Column(db.String(32), nullable=False)
    main_device_id = db.Column(
        db.Integer,
        db.ForeignKey("devices.id", ondelete="SET NULL"),
        nullable=True,
    )
    rental_id = db.Column(
        db.Integer,
        db.ForeignKey("rentals.id", ondelete="SET NULL"),
        nullable=True,
    )
    relay_case_id = db.Column(
        db.Integer,
        db.ForeignKey("rental_relay_cases.id", ondelete="SET NULL"),
        nullable=True,
    )
    from_warehouse_id = db.Column(
        db.Integer,
        db.ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=True,
    )
    to_warehouse_id = db.Column(
        db.Integer,
        db.ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=True,
    )
    from_holder_rental_id = db.Column(
        db.Integer,
        db.ForeignKey("rentals.id", ondelete="SET NULL"),
        nullable=True,
    )
    to_holder_rental_id = db.Column(
        db.Integer,
        db.ForeignKey("rentals.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_type = db.Column(db.String(32), nullable=False)
    actor_id = db.Column(db.String(64), nullable=True)
    reason = db.Column(db.String(64), nullable=True)
    note = db.Column(db.String(500), nullable=True)
    idempotency_key = db.Column(db.String(128), nullable=False)
    occurred_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    unit = db.relationship("AccessoryUnit")
    main_device = db.relationship("Device")
    rental = db.relationship("Rental", foreign_keys=[rental_id])
    relay_case = db.relationship("RentalRelayCase")
    from_warehouse = db.relationship("Warehouse", foreign_keys=[from_warehouse_id])
    to_warehouse = db.relationship("Warehouse", foreign_keys=[to_warehouse_id])
    from_holder_rental = db.relationship(
        "Rental",
        foreign_keys=[from_holder_rental_id],
    )
    to_holder_rental = db.relationship(
        "Rental",
        foreign_keys=[to_holder_rental_id],
    )
