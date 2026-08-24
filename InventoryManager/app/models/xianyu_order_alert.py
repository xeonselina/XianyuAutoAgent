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
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # Nullable only for rows created by the pre-SaaS implementation.  Every
    # durable SaaS synchronization result is written with both immutable
    # control-plane references populated.
    integration_uuid = db.Column(db.String(36), index=True)
    secret_revision_uuid = db.Column(db.String(36))
    order_no = db.Column(
        db.String(50), nullable=False, unique=True, index=True
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


class XianyuOrderSyncState(db.Model):
    """闲鱼漏单对账最近一次运行状态（固定使用 id=1）。"""

    __tablename__ = "xianyu_order_sync_state"

    id = db.Column(db.Integer, primary_key=True)
    __table_args__ = (
        db.UniqueConstraint(
            "last_applied_job_uuid",
            name="uq_xianyu_sync_last_applied_job_uuid",
        ),
        db.CheckConstraint(
            "snapshot_revision >= 0",
            name="ck_xianyu_sync_snapshot_revision_nonnegative",
        ),
        db.CheckConstraint(
            "sync_status IN ('never', 'syncing', 'succeeded', "
            "'partial_failure', 'failed', 'rate_limited')",
            name="ck_xianyu_sync_status_valid",
        ),
    )

    last_attempt_at = db.Column(db.DateTime)
    last_success_at = db.Column(db.DateTime)
    last_error = db.Column(db.String(1000))
    snapshot_revision = db.Column(
        db.BigInteger, nullable=False, default=0, server_default="0"
    )
    sync_status = db.Column(
        db.String(32), nullable=False, default="never", server_default="never"
    )
    current_job_uuid = db.Column(db.String(36))
    last_applied_job_uuid = db.Column(db.String(36))
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    @classmethod
    def get_or_create(cls):
        state = db.session.get(cls, 1)
        if state is None:
            state = cls(id=1)
            db.session.add(state)
            db.session.flush()
        return state

    def to_dict(self):
        return {
            "last_attempt_at": XianyuOrderAlert._iso(self.last_attempt_at),
            "last_success_at": XianyuOrderAlert._iso(self.last_success_at),
            "last_error": self.last_error,
            "snapshot_revision": int(self.snapshot_revision or 0),
            "sync_status": self.sync_status,
            "current_job_uuid": self.current_job_uuid,
        }


class XianyuConnectionSyncState(db.Model):
    """Latest independently persisted result for one tenant Xianyu connection."""

    __tablename__ = "xianyu_connection_sync_states"
    __table_args__ = (
        db.CheckConstraint(
            "snapshot_revision >= 0",
            name="ck_xianyu_connection_snapshot_revision_nonnegative",
        ),
        db.CheckConstraint(
            "row_version >= 1",
            name="ck_xianyu_connection_row_version_positive",
        ),
        db.CheckConstraint(
            "sync_status IN ('never', 'syncing', 'succeeded', "
            "'failed', 'rate_limited')",
            name="ck_xianyu_connection_sync_status_valid",
        ),
        db.Index(
            "ix_xianyu_connection_sync_status",
            "sync_status",
            "last_attempt_at",
        ),
    )

    integration_uuid = db.Column(db.String(36), primary_key=True)
    secret_revision_uuid = db.Column(db.String(36), nullable=False)
    snapshot_revision = db.Column(
        db.BigInteger, nullable=False, default=0, server_default="0"
    )
    sync_status = db.Column(
        db.String(32), nullable=False, default="never", server_default="never"
    )
    last_job_uuid = db.Column(db.String(36))
    last_attempt_at = db.Column(db.DateTime)
    last_success_at = db.Column(db.DateTime)
    safe_error_code = db.Column(db.String(64))
    retry_after_at = db.Column(db.DateTime)
    provider_cursor = db.Column(db.String(512))
    row_version = db.Column(
        db.BigInteger, nullable=False, default=1, server_default="1"
    )
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
            "integration_uuid": self.integration_uuid,
            "secret_revision_uuid": self.secret_revision_uuid,
            "snapshot_revision": int(self.snapshot_revision or 0),
            "sync_status": self.sync_status,
            "last_attempt_at": XianyuOrderAlert._iso(self.last_attempt_at),
            "last_success_at": XianyuOrderAlert._iso(self.last_success_at),
            "safe_error_code": self.safe_error_code,
            "retry_after_at": XianyuOrderAlert._iso(self.retry_after_at),
        }
