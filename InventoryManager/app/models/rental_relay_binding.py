"""主 rental 之间的永久接力关系。"""

from datetime import datetime

from app import db


class RentalRelayBinding(db.Model):
    __tablename__ = "rental_relay_bindings"
    __table_args__ = (
        db.UniqueConstraint(
            "predecessor_rental_id", name="uq_relay_predecessor"
        ),
        db.UniqueConstraint(
            "successor_rental_id", name="uq_relay_successor"
        ),
        db.CheckConstraint(
            "predecessor_rental_id <> successor_rental_id",
            name="ck_relay_distinct",
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    predecessor_rental_id = db.Column(
        db.Integer,
        db.ForeignKey("rentals.id", ondelete="CASCADE"),
        nullable=False,
    )
    successor_rental_id = db.Column(
        db.Integer,
        db.ForeignKey("rentals.id", ondelete="CASCADE"),
        nullable=False,
    )
    confirmed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    predecessor = db.relationship(
        "Rental", foreign_keys=[predecessor_rental_id]
    )
    successor = db.relationship(
        "Rental", foreign_keys=[successor_rental_id]
    )

    @staticmethod
    def validate_pair(predecessor, successor):
        if (
            predecessor.parent_rental_id is not None
            or successor.parent_rental_id is not None
        ):
            raise ValueError("接力绑定只允许主 rental")
        if predecessor.id == successor.id:
            raise ValueError("接力前后 rental 不能相同")
        if predecessor.device_id != successor.device_id:
            raise ValueError("接力 rental 必须位于同一设备")
        if not predecessor.device or not successor.device:
            raise ValueError("接力 rental 缺少设备")
        if predecessor.device.model_id != successor.device.model_id:
            raise ValueError("接力 rental 必须属于同一型号")
        if not predecessor.ship_out_time or not successor.ship_out_time:
            raise ValueError("接力 rental 缺少寄出时间")
        if predecessor.ship_out_time >= successor.ship_out_time:
            raise ValueError("接力顺序不正确")

    def to_dict(self):
        return {
            "id": self.id,
            "predecessor_rental_id": self.predecessor_rental_id,
            "successor_rental_id": self.successor_rental_id,
            "confirmed_at": self.confirmed_at.isoformat(),
        }
