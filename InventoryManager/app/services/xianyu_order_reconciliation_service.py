"""闲鱼待发货订单与库存预定的对账服务。"""

import hashlib
import logging
from datetime import datetime

from flask import current_app
from sqlalchemy import select, text
from sqlalchemy.orm import Session, joinedload

from app import db
from app.models.rental import Rental
from app.models.xianyu_order_alert import XianyuOrderAlert
from app.models.xianyu_rental_alert import XianyuRentalAlert
from app.models.xianyu_shop import XianyuShop
from app.services.integration_resolver import IntegrationResolver
from app.services.xianyu_order_service import XianyuOrderServiceError


logger = logging.getLogger(__name__)


class XianyuShopConfigIncompleteError(RuntimeError):
    """The tenant has no shop to scope reconciliation state to."""


class XianyuOrderReconciliationService:
    """维护漏录订单与已录入档期的退款/关闭提醒。"""

    MIN_PAY_AMOUNT = 5000
    RECONCILE_ORDER_STATUSES = (12, 21)
    SYNC_STALE_AFTER_SECONDS = 10 * 60
    ACTIVE_RENTAL_STATUSES = ("not_shipped", "scheduled_for_shipping", "shipped")

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

    def _list_reconcilable_orders(self, client):
        """Fetch every actionable Xianyu status and de-duplicate transitions."""
        orders_by_number = {}
        for order_status in self.RECONCILE_ORDER_STATUSES:
            for order in client.list_orders(order_status=order_status):
                order_no = self._normalize_order_no(order.get("order_no"))
                if order_no:
                    orders_by_number[order_no] = order
        return list(orders_by_number.values())

    @staticmethod
    def _lock_name(database, shop_id):
        identity = hashlib.sha256(str(database).encode()).hexdigest()[:16]
        return f"xianyu-reconcile:{identity}:shop:{shop_id}"

    def _locked_session(self, shop_id):
        connection = db.session.get_bind().connect()
        if connection.dialect.name not in {"mysql", "mariadb"}:
            if current_app.testing:
                return connection, Session(bind=connection), None
            connection.close()
            raise RuntimeError("Xianyu reconciliation requires MariaDB")
        database = connection.execute(text("SELECT DATABASE()")) .scalar_one()
        name = self._lock_name(database, shop_id)
        if connection.execute(
            text("SELECT GET_LOCK(:name, 0)"), {"name": name}
        ).scalar_one() != 1:
            connection.close()
            return None
        # GET_LOCK starts an implicit transaction on MariaDB.  Close that
        # transaction before binding the ORM session; otherwise Session.commit
        # only completes its nested transaction and connection.close rolls the
        # business changes back.
        connection.commit()
        return connection, Session(bind=connection), name

    @staticmethod
    def _release_lock(resources):
        if resources is None:
            return
        connection, session, name = resources
        session.close()
        try:
            if name:
                connection.execute(
                    text("SELECT RELEASE_LOCK(:name)"), {"name": name}
                )
                connection.commit()
        finally:
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

    @classmethod
    def _active_rentals(cls, shop_ids, session):
        return list(session.scalars(select(Rental).where(
            Rental.xianyu_shop_id.in_(shop_ids),
            Rental.xianyu_order_no.isnot(None),
            Rental.status.in_(cls.ACTIVE_RENTAL_STATUSES),
        ).options(joinedload(Rental.device), joinedload(Rental.warehouse))
          .order_by(Rental.start_date, Rental.id)))

    @staticmethod
    def _rental_alert_status(order):
        """只根据平台状态判断；数量和本地档期数量不参与判定。

        枚举来源：闲管家 /api/open/order/list 的 order_status/refund_status。
        退款成功但交易仍有效时仅提示核对，不能推断整单取消。
        """
        try:
            order_status = int(str(order["order_status"]))
            refund_status = int(str(order["refund_status"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise XianyuOrderServiceError("闲鱼订单状态不完整") from exc
        if order_status not in {11, 12, 21, 22, 23, 24} or refund_status not in {0, 1, 2, 3, 4, 5, 6, 8}:
            raise XianyuOrderServiceError("闲鱼订单状态无法识别")
        if order_status in {23, 24}:
            kind, label = "closed", "已退款" if order_status == 23 else "交易关闭"
        elif refund_status in {1, 2, 3, 5, 8}:
            kind = "refund_review"
            label = {
                1: "退款申请中，请核对", 2: "待买家退货，请核对",
                3: "待确认退货收货，请核对", 5: "退款成功但订单未关闭，请核对",
                8: "待确认退货地址，请核对",
            }[refund_status]
            if refund_status == 5:
                try:
                    if 0 < int(order.get("refund_amount") or 0) < int(order.get("pay_amount") or 0):
                        label = "部分退款，请核对"
                except (TypeError, ValueError):
                    pass
        else:
            return None
        return {"kind": kind, "status_text": label, "order_status": order_status, "refund_status": refund_status}

    def _reconcile_rental_alerts(self, client, orders, now, shop_id, session):
        active = {
            self._normalize_order_no(rental.xianyu_order_no)
            for rental in self._active_rentals([shop_id], session)
            if self._normalize_order_no(rental.xianyu_order_no)
        }
        cached = {
            alert.order_no: alert for alert in session.scalars(select(XianyuRentalAlert).where(
                XianyuRentalAlert.xianyu_shop_id == shop_id,
            ))
        }
        for order_no in cached.keys() - active:
            session.delete(cached[order_no])

        failures = 0
        for order_no in sorted(active):
            try:
                # 待发货列表中消失不代表关闭，必须查询该订单的真实状态。
                order = orders.get(order_no)
                if order is None:
                    order = client.get_order_detail(order_no)
                if not isinstance(order, dict) or self._normalize_order_no(order.get("order_no")) != order_no:
                    raise XianyuOrderServiceError("闲鱼订单详情无效")
                status = self._rental_alert_status(order)
            except Exception as exc:
                # 单笔失败保留旧提醒，其他已核实订单仍正常更新。
                failures += 1
                logger.warning("闲鱼档期订单核对失败，异常类型: %s", type(exc).__name__)
                continue

            alert = cached.get(order_no)
            if status is None:
                if alert is not None:
                    session.delete(alert)
                continue
            if alert is None:
                alert = XianyuRentalAlert(
                    xianyu_shop_id=shop_id, order_no=order_no, first_detected_at=now,
                )
                session.add(alert)
            for key, value in status.items():
                setattr(alert, key, value)
            alert.last_seen_at = now
        return failures

    def _rental_alert_snapshot(self, shops, session):
        by_order = {}
        for rental in self._active_rentals([shop.id for shop in shops], session):
            key = (rental.xianyu_shop_id, self._normalize_order_no(rental.xianyu_order_no))
            by_order.setdefault(key, []).append({
                "id": rental.id,
                "customer_name": rental.customer_name,
                "device_name": rental.device.name,
                "warehouse_id": rental.warehouse_id,
                "warehouse_name": rental.warehouse.name,
                "start_date": rental.start_date.isoformat(),
                "end_date": rental.end_date.isoformat(),
                "status": rental.status,
                "parent_rental_id": rental.parent_rental_id,
            })
        names = {shop.id: shop.name for shop in shops}
        result = []
        for alert in session.scalars(select(XianyuRentalAlert).where(
            XianyuRentalAlert.xianyu_shop_id.in_(names),
            XianyuRentalAlert.ignored_at.is_(None),
        ).order_by(XianyuRentalAlert.first_detected_at.desc(), XianyuRentalAlert.id.desc())):
            rentals = by_order.get((alert.xianyu_shop_id, alert.order_no))
            if rentals:
                result.append({
                    "order_no": alert.order_no,
                    "xianyu_shop_id": alert.xianyu_shop_id,
                    "xianyu_shop_name": names[alert.xianyu_shop_id],
                    "kind": alert.kind,
                    "status_text": alert.status_text,
                    "last_seen_at": XianyuOrderAlert._iso(alert.last_seen_at),
                    "rentals": rentals,
                })
        return result

    def get_snapshot(self, shop_id=None, session=None):
        session = session or db.session
        shops = list(session.scalars(select(XianyuShop).order_by(XianyuShop.id)))
        if not shops:
            raise XianyuShopConfigIncompleteError("请先配置闲鱼店铺")
        selected = [shop for shop in shops if (shop.is_active if shop_id is None else shop.id == shop_id)]
        if shop_id is not None and not selected:
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
        sync_success = sync_shop.last_success_at if sync_shop else aggregate_success
        sync_is_stale = (
            sync_success is None
            or (datetime.utcnow() - sync_success).total_seconds()
            > self.SYNC_STALE_AFTER_SECONDS
        )
        sync = {
            "last_attempt_at": None,
            "last_success_at": sync_shop.to_dict()["last_success_at"] if sync_shop else next(
                (shop.to_dict()["last_success_at"] for shop in active
                 if shop.last_success_at == aggregate_success), None),
            "last_error": sync_shop.last_error if sync_shop else next(
                (shop.last_error for shop in active if shop.last_error), None
            ),
            "is_stale": sync_is_stale,
            "stale_after_seconds": self.SYNC_STALE_AFTER_SECONDS,
        }
        return {
            "alerts": alerts,
            "count": len(alerts),
            "rental_alerts": self._rental_alert_snapshot(selected, session),
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
            orders = self._list_reconcilable_orders(client)
            eligible = self._eligible_orders(orders)
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
            failures = self._reconcile_rental_alerts(client, {
                self._normalize_order_no(order.get("order_no")): order for order in orders
            }, now, shop.id, session)
            if failures:
                shop.last_error = f"{failures} 笔档期订单状态查询失败，已保留原提醒"
            else:
                shop.last_success_at = now
                shop.last_error = None
            session.commit()
            logger.info(
                "闲鱼漏录订单对账成功，店铺ID: %s，接口订单: %s，"
                "符合条件: %s，待补录: %s",
                shop.id,
                len(orders),
                len(eligible),
                len(pending),
            )
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

    def ignore_rental_alert(self, shop_id, order_no, reason):
        """永久忽略一笔故意保留的退款/关闭档期提醒。"""
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
            shop = session.get(XianyuShop, shop_id)
            if shop is None:
                raise XianyuShopConfigIncompleteError("闲鱼店铺不存在")
            alert = session.scalar(select(XianyuRentalAlert).where(
                XianyuRentalAlert.xianyu_shop_id == shop_id,
                XianyuRentalAlert.order_no == normalized_order_no,
                XianyuRentalAlert.ignored_at.is_(None),
            ))
            if alert is None:
                raise LookupError("待处理档期提醒不存在")

            alert.ignored_at = datetime.utcnow()
            alert.ignored_reason = normalized_reason
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            self._release_lock(resources)
            db.session.expire_all()

        return self.get_snapshot()
