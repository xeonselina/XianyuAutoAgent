"""客户间直接转寄的运营管理记录。"""

from datetime import datetime

from app import db


class RentalRelayCase(db.Model):
    """保存接力组合的当前运营阶段和顺丰查询摘要。"""

    __tablename__ = "rental_relay_cases"
    __table_args__ = (
        db.UniqueConstraint(
            "predecessor_rental_id",
            "successor_rental_id",
            name="uq_relay_case_pair",
        ),
        db.CheckConstraint(
            "predecessor_rental_id <> successor_rental_id",
            name="ck_relay_case_distinct",
        ),
        db.Index("ix_relay_case_status", "status"),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    predecessor_rental_id = db.Column(
        db.Integer,
        db.ForeignKey("rentals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    successor_rental_id = db.Column(
        db.Integer,
        db.ForeignKey("rentals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = db.Column(
        db.Enum(
            "pending",
            "notified",
            "agreed",
            "shipped",
            "completed",
            name="relay_case_status",
        ),
        nullable=False,
        default="pending",
    )

    sf_tracking_number = db.Column(db.String(50))
    sf_tracking_status = db.Column(db.String(50))
    sf_tracking_summary = db.Column(db.String(500))
    sf_last_checked_at = db.Column(db.DateTime)

    notified_at = db.Column(db.DateTime)
    agreed_at = db.Column(db.DateTime)
    shipped_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
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

    def __repr__(self):
        return (
            f"<RentalRelayCase {self.predecessor_rental_id}:"
            f"{self.successor_rental_id} {self.status}>"
        )
