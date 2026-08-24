"""闲鱼漏录订单告警与同步状态模型。"""

from datetime import datetime, timezone

from sqlalchemy.orm import validates

from app import db


class XianyuOrderAlert(db.Model):
    """保存当前漏录订单与永久忽略记录。"""

    __tablename__ = "xianyu_order_alerts"
    __table_args__ = (
        db.CheckConstraint(
            "state IN ('pending', 'ignored')",
            name="ck_xianyu_order_alert_state",
        ),
        db.UniqueConstraint(
            "xianyu_shop_id",
            "order_no",
            name="uq_xianyu_alert_shop_order",
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    order_no = db.Column(db.String(50), nullable=False, index=True)
    xianyu_shop_id = db.Column(
        db.Integer,
        db.ForeignKey("xianyu_shops.id", ondelete="RESTRICT"),
        nullable=False,
    )
    state = db.Column(
        db.String(20), nullable=False, default="pending", index=True
    )
    pay_amount = db.Column(db.BigInteger, nullable=False)
    buyer_nick = db.Column(db.String(100))
    receiver_name = db.Column(db.String(100))
    receiver_mobile = db.Column(db.String(20))
    address = db.Column(db.String(500))
    goods_title = db.Column(db.String(500))
    goods_sku_text = db.Column(db.String(500))
    order_time = db.Column(db.DateTime)
    first_detected_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow
    )
    last_seen_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow
    )
    ignored_reason = db.Column(db.String(500))
    ignored_at = db.Column(db.DateTime)
    created_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    xianyu_shop = db.relationship("XianyuShop")

    @validates("order_no")
    def normalize_order_no(self, _key, value):
        """订单号统一去除首尾空格，空值不允许入库。"""
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("订单号不能为空")
        return normalized

    @staticmethod
    def _iso(value):
        if not value:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")

    def to_dict(self):
        """返回告警条所需的非内部字段。"""
        return {
            "order_no": self.order_no,
            "xianyu_shop_id": self.xianyu_shop_id,
            "pay_amount": self.pay_amount,
            "buyer_nick": self.buyer_nick,
            "receiver_name": self.receiver_name,
            "receiver_mobile": self.receiver_mobile,
            "address": self.address,
            "goods_title": self.goods_title,
            "goods_sku_text": self.goods_sku_text,
            "order_time": self._iso(self.order_time),
            "first_detected_at": self._iso(self.first_detected_at),
            "last_seen_at": self._iso(self.last_seen_at),
        }
