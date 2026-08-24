"""Tenant-database warehouse foundation models."""

from datetime import datetime
from uuid import uuid4

from app import db


def _new_uuid():
    return str(uuid4())


class Warehouse(db.Model):
    __tablename__ = "warehouses"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_warehouses_status_valid",
        ),
        db.CheckConstraint(
            "setup_state IN ('pending', 'ready')",
            name="ck_warehouses_setup_state_valid",
        ),
        db.CheckConstraint(
            "(is_default = 1 AND default_slot = 1) OR "
            "(is_default = 0 AND default_slot IS NULL)",
            name="ck_warehouses_default_slot_consistent",
        ),
        db.CheckConstraint(
            "setup_state = 'pending' OR "
            "(name IS NOT NULL AND contact_name IS NOT NULL AND "
            "contact_phone IS NOT NULL AND province IS NOT NULL AND "
            "city IS NOT NULL AND district IS NOT NULL AND "
            "address_detail IS NOT NULL)",
            name="ck_warehouses_ready_fields_present",
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    warehouse_uuid = db.Column(
        db.String(36),
        nullable=False,
        unique=True,
        default=_new_uuid,
    )
    name = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(16), nullable=False, default="active")
    setup_state = db.Column(db.String(16), nullable=False, default="pending")
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    default_slot = db.Column(db.SmallInteger, nullable=True, unique=True)
    contact_name = db.Column(db.String(120), nullable=True)
    contact_phone = db.Column(db.String(32), nullable=True)
    province = db.Column(db.String(64), nullable=True)
    city = db.Column(db.String(64), nullable=True)
    district = db.Column(db.String(64), nullable=True)
    address_detail = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    devices = db.relationship("Device", back_populates="warehouse", lazy="dynamic")

    @classmethod
    def pending_default(cls, *, contact_phone=None):
        return cls(
            is_default=True,
            default_slot=1,
            setup_state="pending",
            status="active",
            contact_phone=contact_phone,
        )

    def mark_ready(
        self,
        *,
        name,
        contact_name,
        contact_phone,
        province,
        city,
        district,
        address_detail,
    ):
        required = {
            "name": name,
            "contact_name": contact_name,
            "contact_phone": contact_phone,
            "province": province,
            "city": city,
            "district": district,
            "address_detail": address_detail,
        }
        if any(not isinstance(value, str) or not value.strip() for value in required.values()):
            raise ValueError("ready warehouse fields must be non-empty")
        for field_name, value in required.items():
            setattr(self, field_name, value.strip())
        self.setup_state = "ready"


class WarehousePrinter(db.Model):
    __tablename__ = "warehouse_printers"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('active', 'inactive', 'verification_failed')",
            name="ck_warehouse_printers_status_valid",
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    warehouse_id = db.Column(
        db.Integer,
        db.ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    printer_sn = db.Column(db.String(128), nullable=False, unique=True)
    display_name = db.Column(db.String(120), nullable=False)
    provider = db.Column(db.String(32), nullable=False, default="kuaimai")
    status = db.Column(db.String(32), nullable=False, default="active")
    last_verified_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    warehouse = db.relationship("Warehouse")


class UserWarehousePreference(db.Model):
    __tablename__ = "user_warehouse_preferences"
    __table_args__ = (
        db.CheckConstraint(
            "scene IN ('booking', 'shipping', 'inspection')",
            name="ck_user_warehouse_preferences_scene_valid",
        ),
    )

    user_id = db.Column(db.String(36), primary_key=True)
    scene = db.Column(db.String(32), primary_key=True)
    warehouse_id = db.Column(
        db.Integer,
        db.ForeignKey("warehouses.id", ondelete="CASCADE"),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    warehouse = db.relationship("Warehouse")


class WarehouseProviderBinding(db.Model):
    __tablename__ = "warehouse_provider_bindings"
    __table_args__ = (
        db.UniqueConstraint(
            "provider",
            "provider_account_uuid",
            name="uq_warehouse_provider_bindings_provider_account",
        ),
        db.CheckConstraint(
            "binding_revision >= 1",
            name="ck_warehouse_provider_bindings_revision_positive",
        ),
        db.CheckConstraint(
            "status IN ('active', 'inactive', 'verification_failed')",
            name="ck_warehouse_provider_bindings_status_valid",
        ),
    )

    warehouse_id = db.Column(
        db.Integer,
        db.ForeignKey("warehouses.id", ondelete="CASCADE"),
        primary_key=True,
    )
    provider = db.Column(db.String(32), primary_key=True)
    provider_account_uuid = db.Column(db.String(36), nullable=True)
    binding_revision = db.Column(db.BigInteger, nullable=False, default=1)
    status = db.Column(db.String(32), nullable=False, default="inactive")
    verified_at = db.Column(db.DateTime, nullable=True)
    bound_by = db.Column(db.String(36), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    warehouse = db.relationship("Warehouse")


class DeviceWarehouseMovement(db.Model):
    __tablename__ = "device_warehouse_movements"
    __table_args__ = (
        db.CheckConstraint(
            "source IN ('inspection', 'manual_change')",
            name="ck_device_warehouse_movements_source_valid",
        ),
        db.CheckConstraint(
            "from_warehouse_id IS NULL OR from_warehouse_id <> to_warehouse_id",
            name="ck_device_warehouse_movements_changes_warehouse",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=_new_uuid)
    device_id = db.Column(
        db.Integer,
        db.ForeignKey("devices.id", ondelete="RESTRICT"),
        nullable=False,
    )
    from_warehouse_id = db.Column(
        db.Integer,
        db.ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=True,
    )
    to_warehouse_id = db.Column(
        db.Integer,
        db.ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source = db.Column(db.String(32), nullable=False)
    note = db.Column(db.String(500), nullable=True)
    actor_user_id = db.Column(db.String(36), nullable=False)
    related_resource_type = db.Column(db.String(64), nullable=True)
    related_resource_id = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    device = db.relationship("Device")
    from_warehouse = db.relationship("Warehouse", foreign_keys=[from_warehouse_id])
    to_warehouse = db.relationship("Warehouse", foreign_keys=[to_warehouse_id])
