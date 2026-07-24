"""闲鱼漏录订单告警 API。"""

from flask import Blueprint

from app.handlers.xianyu_order_alert_handlers import (
    XianyuOrderAlertHandlers,
)
from app.utils.response import handle_response


bp = Blueprint("xianyu_order_alert_api", __name__)


@bp.get("/api/xianyu-order-alerts")
@handle_response
def get_alerts():
    return XianyuOrderAlertHandlers.get_alerts()


@bp.post("/api/xianyu-order-alerts/refresh")
@handle_response
def refresh_alerts():
    return XianyuOrderAlertHandlers.refresh_alerts()


@bp.post("/api/xianyu-order-alerts/<order_no>/ignore")
@handle_response
def ignore_alert(order_no):
    return XianyuOrderAlertHandlers.ignore_alert(order_no)
