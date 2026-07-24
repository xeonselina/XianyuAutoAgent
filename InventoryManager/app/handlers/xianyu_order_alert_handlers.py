"""闲鱼漏录订单告警 API 处理器。"""

from flask import current_app, request

from app.services.xianyu_order_reconciliation_service import (
    XianyuOrderReconciliationService,
)
from app.utils.response import (
    bad_request,
    not_found,
    server_error,
    success,
)


class XianyuOrderAlertHandlers:
    """将对账服务结果转换为统一 API 响应。"""

    service = XianyuOrderReconciliationService()

    @classmethod
    def get_alerts(cls):
        try:
            return success(data=cls.service.get_snapshot())
        except Exception as exc:
            current_app.logger.error("读取闲鱼漏单告警失败: %s", exc)
            return server_error("读取漏录订单告警失败")

    @classmethod
    def refresh_alerts(cls):
        try:
            return success(data=cls.service.reconcile())
        except Exception as exc:
            current_app.logger.error("刷新闲鱼漏单告警失败: %s", exc)
            return server_error("刷新漏录订单告警失败")

    @classmethod
    def ignore_alert(cls, order_no):
        data = request.get_json(silent=True) or {}
        reason = str(data.get("reason") or "").strip()
        if not reason:
            return bad_request("忽略原因不能为空")

        try:
            snapshot = cls.service.ignore(order_no, reason)
            return success(data=snapshot, message="订单已永久忽略")
        except ValueError as exc:
            return bad_request(str(exc))
        except LookupError as exc:
            return not_found(str(exc))
        except Exception as exc:
            current_app.logger.error("永久忽略闲鱼订单失败: %s", exc)
            return server_error("忽略订单失败")
