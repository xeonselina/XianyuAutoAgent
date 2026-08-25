"""Reentrant business jobs run only by the independent worker."""

import logging
from datetime import datetime

from sqlalchemy import select

from app import db
from app.models.rental import Rental
from app.models.xianyu_shop import XianyuShop


logger = logging.getLogger(__name__)


def process_scheduled_shipments_for_current_tenant():
    """Ship due main Rentals, committing or rolling back one at a time."""
    due = list(db.session.scalars(
        select(Rental).where(
            Rental.parent_rental_id.is_(None),
            Rental.status == "scheduled_for_shipping",
            Rental.scheduled_ship_time <= datetime.utcnow(),
        ).order_by(Rental.id)
    ))
    for rental in due:
        try:
            if rental.xianyu_shop_id and rental.xianyu_order_no:
                from app.services.xianyu_order_service import get_xianyu_service

                result = get_xianyu_service(rental=rental).ship_order(rental)
                if not result.get("success"):
                    db.session.rollback()
                    logger.error("预约发货失败，租赁ID: %s", rental.id)
                    continue

            shipped_at = datetime.utcnow()
            rental.status = "shipped"
            rental.ship_out_time = shipped_at
            for child in rental.child_rentals:
                child.status = "shipped"
                child.ship_out_time = shipped_at
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            logger.error(
                "预约发货异常，租赁ID: %s，类型: %s",
                rental.id, type(exc).__name__,
            )


def reconcile_active_shops_for_current_tenant():
    """Reconcile each active shop independently in deterministic order."""
    from app.services.xianyu_order_reconciliation_service import (
        XianyuOrderReconciliationService,
    )

    shop_ids = list(db.session.scalars(
        select(XianyuShop.id).where(
            XianyuShop.is_active.is_(True)
        ).order_by(XianyuShop.id)
    ))
    for shop_id in shop_ids:
        try:
            XianyuOrderReconciliationService().reconcile_shop(shop_id)
        except Exception as exc:
            logger.error(
                "闲鱼店铺同步异常，店铺ID: %s，类型: %s",
                shop_id, type(exc).__name__,
            )
