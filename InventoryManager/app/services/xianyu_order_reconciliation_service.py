"""闲鱼待发货订单与库存预定的对账服务。"""

import fcntl
import logging
from datetime import datetime

from app import db
from app.models.rental import Rental
from app.models.xianyu_order_alert import (
    XianyuOrderAlert,
    XianyuOrderSyncState,
)
from app.services.xianyu_order_service import (
    XianyuOrderServiceError,
    xianyu_service,
)


logger = logging.getLogger(__name__)


class XianyuOrderReconciliationService:
    """维护可信的漏录订单缓存。"""

    MIN_PAY_AMOUNT = 5000
    DEFAULT_LOCK_PATH = "/tmp/inventory_xianyu_order_reconcile.lock"

    def __init__(self, service=None, lock_path=None):
        self.xianyu_service = service or xianyu_service
        self.lock_path = lock_path or self.DEFAULT_LOCK_PATH

    @staticmethod
    def _normalize_order_no(value):
        return str(value or "").strip()

    def _eligible_orders(self, orders):
        eligible = {}
        for order in orders:
            order_no = self._normalize_order_no(order.get("order_no"))
            if not order_no:
                continue
            try:
                pay_amount = int(order.get("pay_amount") or 0)
            except (TypeError, ValueError):
                continue
            if pay_amount > self.MIN_PAY_AMOUNT:
                eligible[order_no] = order
        return eligible

    def _try_acquire_lock(self):
        lock_handle = open(self.lock_path, "a+")
        try:
            fcntl.flock(
                lock_handle.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
            return lock_handle
        except BlockingIOError:
            lock_handle.close()
            return None

    def _acquire_lock(self):
        """阻塞获取对账锁，用于必须串行完成的本地状态变更。"""
        lock_handle = open(self.lock_path, "a+")
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        return lock_handle

    @staticmethod
    def _release_lock(lock_handle):
        if lock_handle is None:
            return
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        finally:
            lock_handle.close()

    def is_refreshing(self):
        lock_handle = self._try_acquire_lock()
        if lock_handle is None:
            return True
        self._release_lock(lock_handle)
        return False

    @staticmethod
    def _unix_datetime(value):
        if not value:
            return None
        try:
            return datetime.utcfromtimestamp(int(value))
        except (TypeError, ValueError, OSError, OverflowError):
            return None

    @staticmethod
    def _address(order):
        return "".join(
            str(order.get(field) or "").strip()
            for field in (
                "prov_name",
                "city_name",
                "area_name",
                "town_name",
                "address",
            )
        )

    @staticmethod
    def _existing_rental_order_numbers():
        rows = (
            db.session.query(Rental.xianyu_order_no)
            .filter(Rental.xianyu_order_no.isnot(None))
            .all()
        )
        return {
            str(value).strip()
            for (value,) in rows
            if value and str(value).strip()
        }

    def _replace_pending(self, pending_orders, now):
        current_pending = {
            alert.order_no: alert
            for alert in XianyuOrderAlert.query.filter_by(
                state="pending"
            ).all()
        }

        for order_no, alert in current_pending.items():
            if order_no not in pending_orders:
                db.session.delete(alert)

        for order_no, order in pending_orders.items():
            alert = current_pending.get(order_no)
            if alert is None:
                alert = XianyuOrderAlert(
                    order_no=order_no,
                    state="pending",
                    pay_amount=int(order.get("pay_amount") or 0),
                    first_detected_at=now,
                )
                db.session.add(alert)

            goods = order.get("goods")
            if not isinstance(goods, dict):
                goods = {}

            alert.pay_amount = int(order.get("pay_amount") or 0)
            alert.buyer_nick = order.get("buyer_nick")
            alert.receiver_name = order.get("receiver_name")
            alert.receiver_mobile = order.get("receiver_mobile")
            alert.address = self._address(order)
            alert.goods_title = goods.get("title")
            alert.goods_sku_text = goods.get("sku_text")
            alert.order_time = self._unix_datetime(
                order.get("order_time")
            )
            alert.last_seen_at = now

    def get_snapshot(self):
        existing = self._existing_rental_order_numbers()
        rows = (
            XianyuOrderAlert.query.filter_by(state="pending")
            .order_by(
                XianyuOrderAlert.order_time.desc(),
                XianyuOrderAlert.id.desc(),
            )
            .all()
        )
        alerts = [
            alert.to_dict()
            for alert in rows
            if alert.order_no not in existing
        ]
        state = db.session.get(XianyuOrderSyncState, 1)
        sync = (
            state.to_dict()
            if state
            else {
                "last_attempt_at": None,
                "last_success_at": None,
                "last_error": None,
            }
        )
        return {
            "alerts": alerts,
            "count": len(alerts),
            "sync": sync,
            "refreshing": self.is_refreshing(),
        }

    def reconcile(self):
        """执行一次完整对账；失败时只更新失败状态。"""
        lock_handle = self._try_acquire_lock()
        if lock_handle is None:
            snapshot = self.get_snapshot()
            snapshot["refreshing"] = True
            return snapshot

        try:
            now = datetime.utcnow()
            eligible = self._eligible_orders(
                self.xianyu_service.list_orders()
            )
            existing = self._existing_rental_order_numbers()
            ignored = {
                order_no
                for (order_no,) in db.session.query(
                    XianyuOrderAlert.order_no
                )
                .filter(XianyuOrderAlert.state == "ignored")
                .all()
            }
            excluded = existing | ignored
            pending = {
                order_no: order
                for order_no, order in eligible.items()
                if order_no not in excluded
            }

            self._replace_pending(pending, now)
            state = XianyuOrderSyncState.get_or_create()
            state.last_attempt_at = now
            state.last_success_at = now
            state.last_error = None
            db.session.commit()
        except XianyuOrderServiceError:
            db.session.rollback()
            logger.error("闲鱼漏录订单对账失败，类型: XianyuOrderServiceError")
            state = XianyuOrderSyncState.get_or_create()
            state.last_attempt_at = datetime.utcnow()
            state.last_error = "闲鱼订单查询失败"
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.error(
                "闲鱼漏录订单对账失败，异常类型: %s",
                type(exc).__name__,
            )
            state = XianyuOrderSyncState.get_or_create()
            state.last_attempt_at = datetime.utcnow()
            state.last_error = "漏录订单检查失败"
            db.session.commit()
        finally:
            self._release_lock(lock_handle)

        return self.get_snapshot()

    def ignore(self, order_no, reason):
        """永久忽略一个当前待处理告警。"""
        normalized_order_no = self._normalize_order_no(order_no)
        normalized_reason = str(reason or "").strip()
        if not normalized_reason:
            raise ValueError("忽略原因不能为空")
        if len(normalized_reason) > 500:
            raise ValueError("忽略原因不能超过500个字符")

        lock_handle = self._acquire_lock()
        try:
            alert = XianyuOrderAlert.query.filter_by(
                order_no=normalized_order_no,
                state="pending",
            ).one_or_none()
            if alert is None:
                raise LookupError("待处理订单不存在")

            alert.state = "ignored"
            alert.ignored_reason = normalized_reason
            alert.ignored_at = datetime.utcnow()
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        finally:
            self._release_lock(lock_handle)

        return self.get_snapshot()
