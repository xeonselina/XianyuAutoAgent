"""Warehouse and per-warehouse logistics configuration models."""

from datetime import datetime, timezone

from app import db


def _iso(value):
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _strings_present(*values):
    return all(
        isinstance(value, str) and bool(value.strip())
        for value in values
    )


def resolve_write_warehouse_id(requested_id):
    """Resolve a concrete warehouse for a write without storing preference."""
    if requested_id not in (None, ""):
        if isinstance(requested_id, bool) or not isinstance(
            requested_id, int
        ):
            raise ValueError("仓库不存在")
        warehouse = db.session.get(Warehouse, requested_id)
        if warehouse is None:
            raise ValueError("仓库不存在")
        return warehouse.id

    warehouse_ids = [
        warehouse_id
        for (warehouse_id,) in db.session.query(Warehouse.id)
        .order_by(Warehouse.id)
        .limit(2)
        .all()
    ]
    if len(warehouse_ids) != 1:
        raise ValueError("请指定仓库")
    return warehouse_ids[0]


def resolve_read_warehouse_id(requested_id):
    """Resolve an optional read filter; ``all`` means no warehouse filter."""
    if requested_id is None:
        return None
    if requested_id == "all":
        return "all"
    if isinstance(requested_id, bool):
        raise ValueError("仓库不存在")
    try:
        warehouse_id = int(requested_id)
    except (TypeError, ValueError):
        raise ValueError("仓库不存在") from None
    if warehouse_id <= 0 or db.session.get(Warehouse, warehouse_id) is None:
        raise ValueError("仓库不存在")
    return warehouse_id


class Warehouse(db.Model):
    __tablename__ = "warehouses"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    province = db.Column(db.String(64), nullable=False)
    city = db.Column(db.String(64), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    sf_config = db.relationship(
        "WarehouseSFConfig",
        back_populates="warehouse",
        uselist=False,
    )
    kuaimai_config = db.relationship(
        "WarehouseKuaimaiConfig",
        back_populates="warehouse",
        uselist=False,
    )

    @property
    def sf_configured(self):
        config = self.sf_config
        return config is not None and _strings_present(
            self.province, self.city, config.partner_id,
            config.checkword_ciphertext, config.monthly_card_ciphertext,
            config.sender_name, config.sender_phone, config.sender_address,
        )

    @property
    def kuaimai_configured(self):
        config = self.kuaimai_config
        return config is not None and _strings_present(
            config.app_id, config.app_secret_ciphertext, config.printer_sn,
        )

    def to_dict(self):
        data = {
            "id": self.id,
            "province": self.province,
            "city": self.city,
            "name": self.name,
            "sf_configured": self.sf_configured,
            "kuaimai_configured": self.kuaimai_configured,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }
        if self.sf_config is not None:
            data["return_contact"] = {
                "name": self.sf_config.sender_name,
                "phone": self.sf_config.sender_phone,
                "detail": self.sf_config.sender_address,
            }
        return data

    def to_settings_dict(self):
        data = self.to_dict()
        data["sf_config"] = (
            self.sf_config.to_dict() if self.sf_config is not None else None
        )
        data["kuaimai_config"] = (
            self.kuaimai_config.to_dict()
            if self.kuaimai_config is not None
            else None
        )
        return data


class WarehouseSFConfig(db.Model):
    __tablename__ = "warehouse_sf_configs"

    warehouse_id = db.Column(
        db.Integer,
        db.ForeignKey("warehouses.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    partner_id = db.Column(db.String(100))
    checkword_ciphertext = db.Column(db.Text)
    monthly_card_ciphertext = db.Column(db.Text)
    test_mode = db.Column(db.Boolean, nullable=False, default=False)
    sender_name = db.Column(db.String(100))
    sender_phone = db.Column(db.String(30))
    sender_address = db.Column(db.String(500))
    created_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    warehouse = db.relationship("Warehouse", back_populates="sf_config")

    def to_dict(self):
        return {
            "warehouse_id": self.warehouse_id,
            "partner_id": self.partner_id,
            "checkword_configured": bool(self.checkword_ciphertext),
            "monthly_card_configured": bool(
                self.monthly_card_ciphertext
            ),
            "test_mode": self.test_mode,
            "sender_name": self.sender_name,
            "sender_phone": self.sender_phone,
            "sender_address": self.sender_address,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


class WarehouseKuaimaiConfig(db.Model):
    __tablename__ = "warehouse_kuaimai_configs"

    warehouse_id = db.Column(
        db.Integer,
        db.ForeignKey("warehouses.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    app_id = db.Column(db.String(100))
    app_secret_ciphertext = db.Column(db.Text)
    printer_sn = db.Column(db.String(100))
    created_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    warehouse = db.relationship(
        "Warehouse", back_populates="kuaimai_config"
    )

    def to_dict(self):
        return {
            "warehouse_id": self.warehouse_id,
            "app_id": self.app_id,
            "app_secret_configured": bool(self.app_secret_ciphertext),
            "printer_sn": self.printer_sn,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }
