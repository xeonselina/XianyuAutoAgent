"""Tenant Xianyu shop model."""

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


class XianyuShop(db.Model):
    __tablename__ = "xianyu_shops"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    app_key = db.Column(db.String(255), nullable=False)
    app_secret_ciphertext = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    last_success_at = db.Column(db.DateTime)
    last_error = db.Column(db.String(1000))
    created_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "app_key": self.app_key,
            "app_secret_configured": bool(self.app_secret_ciphertext),
            "is_active": self.is_active,
            "last_success_at": _iso(self.last_success_at),
            "last_error": self.last_error,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }
