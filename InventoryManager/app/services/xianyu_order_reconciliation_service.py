"""闲鱼待发货订单与库存预定的对账服务。"""

import hashlib
import logging
from datetime import datetime

from flask import current_app
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import db
from app.models.rental import Rental
from app.models.xianyu_order_alert import XianyuOrderAlert
from app.models.xianyu_shop import XianyuShop
from app.services.integration_resolver import IntegrationResolver
from app.services.xianyu_order_service import XianyuOrderServiceError


logger = logging.getLogger(__name__)


class XianyuShopConfigIncompleteError(RuntimeError):
    """The tenant has no shop to scope reconciliation state to."""


class XianyuOrderReconciliationService:
    """维护可信的漏录订单缓存。"""

    MIN_PAY_AMOUNT = 5000
    def __init__(self, service_factory=None, service=None, lock_path=None):
        self.service_factory = service_factory
        self.service = service

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

    @staticmethod
    def _lock_name(database, shop_id):
        identity = hashlib.sha256(str(database).encode()).hexdigest()[:16]
        return f"xianyu-reconcile:{identity}:shop:{shop_id}"

    def _locked_session(self, shop_id):
        connection = db.session.get_bind().connect()
        session = Session(bind=connection)
        if connection.dialect.name not in {"mysql", "mariadb"}:
            if current_app.testing:
                return connection, session, None
            session.close()
            connection.close()
            raise RuntimeError("Xianyu reconciliation requires MariaDB")
        database = connection.execute(text("SELECT DATABASE()")) .scalar_one()
        name = self._lock_name(database, shop_id)
        if connection.execute(
            text("SELECT GET_LOCK(:name, 0)"), {"name": name}
        ).scalar_one() != 1:
            session.close()
            connection.close()
            return None
        return connection, session, name

    @staticmethod
    def _release_lock(resources):
        if resources is None:
            return
        connection, session, name = resources
        session.close()
        if name:
            connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})
        connection.close()

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
    def _existing_rental_order_numbers(shop_id, session=None):
        session = session or db.session
        rows = session.execute(select(Rental.xianyu_order_no).where(
            Rental.xianyu_shop_id == shop_id,
            Rental.xianyu_order_no.isnot(None),
        )).all()
        return {
            str(value).strip()
            for (value,) in rows
            if value and str(value).strip()
        }

    def _replace_pending(self, pending_orders, now, shop_id, session):
        current_pending = {
            alert.order_no: alert
            for alert in session.scalars(select(XianyuOrderAlert).where(
                XianyuOrderAlert.xianyu_shop_id == shop_id,
                XianyuOrderAlert.state == "pending",
            ))
        }

        for order_no, alert in current_pending.items():
            if order_no not in pending_orders:
                session.delete(alert)

        for order_no, order in pending_orders.items():
            alert = current_pending.get(order_no)
            if alert is None:
                alert = XianyuOrderAlert(
                    xianyu_shop_id=shop_id,
                    order_no=order_no,
                    state="pending",
                    pay_amount=int(order.get("pay_amount") or 0),
                    first_detected_at=now,
                )
                session.add(alert)

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

    def get_snapshot(self, shop_id=None, session=None):
        session = session or db.session
        shops = list(session.scalars(select(XianyuShop).order_by(XianyuShop.id)))
        if not shops:
            raise XianyuShopConfigIncompleteError("请先配置闲鱼店铺")
        selected = [shop for shop in shops if shop_id is None or shop.id == shop_id]
        if not selected:
            raise XianyuShopConfigIncompleteError("闲鱼店铺不存在")
        ids = [shop.id for shop in selected]
        existing = {
            (shop.id, order_no)
            for shop in selected
            for order_no in self._existing_rental_order_numbers(shop.id, session)
        }
        rows = list(session.scalars(select(XianyuOrderAlert).where(
            XianyuOrderAlert.xianyu_shop_id.in_(ids),
            XianyuOrderAlert.state == "pending",
        ).order_by(XianyuOrderAlert.order_time.desc(), XianyuOrderAlert.id.desc())))
        alerts = [
            {**alert.to_dict(), "xianyu_shop_name": alert.xianyu_shop.name}
            for alert in rows
            if (alert.xianyu_shop_id, alert.order_no) not in existing
        ]
        active = [shop for shop in shops if shop.is_active]
        sync_shop = selected[0] if shop_id is not None else None
        aggregate_success = min((shop.last_success_at for shop in active), default=None) \
            if active and all(shop.last_success_at for shop in active) else None
        sync = {
            "last_attempt_at": None,
            "last_success_at": sync_shop.to_dict()["last_success_at"] if sync_shop else next(
                (shop.to_dict()["last_success_at"] for shop in active
                 if shop.last_success_at == aggregate_success), None),
            "last_error": sync_shop.last_error if sync_shop else next(
                (shop.last_error for shop in active if shop.last_error), None
            ),
        }
        return {
            "alerts": alerts,
            "count": len(alerts),
            "sync": sync,
            "refreshing": False,
            "shops": [{"id": shop.id, "name": shop.name} for shop in active],
        }

    def reconcile_shop(self, shop_id):
        """完整拉取后原子替换一个店铺的可信告警缓存。"""
        resources = self._locked_session(shop_id)
        if resources is None:
            snapshot = self.get_snapshot(shop_id)
            snapshot["refreshing"] = True
            return snapshot
        _connection, session, _name = resources
        try:
            shop = session.get(XianyuShop, shop_id)
            if shop is None or not shop.is_active:
                raise XianyuShopConfigIncompleteError("闲鱼店铺不存在或已停用")
            now = datetime.utcnow()
            client = self.service_factory(shop) if self.service_factory else (
                self.service or IntegrationResolver(session=session).xianyu_for_shop(shop)
            )
            eligible = self._eligible_orders(client.list_orders())
            existing = self._existing_rental_order_numbers(shop.id, session)
            ignored = {
                order_no
                for (order_no,) in session.execute(select(
                    XianyuOrderAlert.order_no
                ).where(
                    XianyuOrderAlert.xianyu_shop_id == shop.id,
                    XianyuOrderAlert.state == "ignored",
                ))
            }
            excluded = existing | ignored
            pending = {
                order_no: order
                for order_no, order in eligible.items()
                if order_no not in excluded
            }

            self._replace_pending(pending, now, shop.id, session)
            shop.last_success_at = now
            shop.last_error = None
            session.commit()
        except XianyuOrderServiceError:
            session.rollback()
            logger.error("闲鱼漏录订单对账失败，类型: XianyuOrderServiceError")
            shop = session.get(XianyuShop, shop_id)
            shop.last_error = "闲鱼订单查询失败"
            session.commit()
        except Exception as exc:
            session.rollback()
            if isinstance(exc, XianyuShopConfigIncompleteError):
                raise
            logger.error(
                "闲鱼漏录订单对账失败，异常类型: %s",
                type(exc).__name__,
            )
            shop = session.get(XianyuShop, shop_id)
            shop.last_error = "漏录订单检查失败"
            session.commit()
        finally:
            self._release_lock(resources)
            db.session.expire_all()
        return self.get_snapshot(shop_id)

    def reconcile(self):
        for shop_id in db.session.scalars(select(XianyuShop.id).where(
            XianyuShop.is_active.is_(True)).order_by(XianyuShop.id)):
            self.reconcile_shop(shop_id)
        return self.get_snapshot()

    def ignore(self, shop_id, order_no, reason):
        """永久忽略一个当前待处理告警。"""
        normalized_order_no = self._normalize_order_no(order_no)
        normalized_reason = str(reason or "").strip()
        if not normalized_reason:
            raise ValueError("忽略原因不能为空")
        if len(normalized_reason) > 500:
            raise ValueError("忽略原因不能超过500个字符")

        resources = self._locked_session(shop_id)
        if resources is None:
            raise RuntimeError("店铺正在同步，请稍后重试")
        _connection, session, _name = resources
        try:
            if session.get(XianyuShop, shop_id) is None:
                raise XianyuShopConfigIncompleteError("闲鱼店铺不存在")
            alert = session.scalar(select(XianyuOrderAlert).where(
                XianyuOrderAlert.xianyu_shop_id == shop_id,
                XianyuOrderAlert.order_no == normalized_order_no,
                XianyuOrderAlert.state == "pending",
            ))
            if alert is None:
                raise LookupError("待处理订单不存在")

            alert.state = "ignored"
            alert.ignored_reason = normalized_reason
            alert.ignored_at = datetime.utcnow()
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            self._release_lock(resources)
            db.session.expire_all()

        return self.get_snapshot()
