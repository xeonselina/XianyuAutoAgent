"""已录入档期的闲鱼订单退款/关闭状态缓存，与漏录忽略记录独立。"""

from datetime import datetime

from app import db


class XianyuRentalAlert(db.Model):
    __tablename__ = "xianyu_rental_alerts"
    __table_args__ = (
        db.UniqueConstraint("xianyu_shop_id", "order_no", name="uq_xianyu_rental_alert_shop_order"),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    xianyu_shop_id = db.Column(
        db.Integer, db.ForeignKey("xianyu_shops.id", ondelete="RESTRICT"), nullable=False,
    )
    order_no = db.Column(db.String(50), nullable=False)
    kind = db.Column(db.String(20), nullable=False)  # closed / refund_review
    status_text = db.Column(db.String(100), nullable=False)
    order_status = db.Column(db.Integer, nullable=False)
    refund_status = db.Column(db.Integer, nullable=False)
    first_detected_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
