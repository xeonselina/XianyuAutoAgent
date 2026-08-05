"""接力管理 API 的参数验证与响应映射。"""

from datetime import date, timedelta

from flask import current_app, request

from app import db
from app.services.relay.relay_case_service import (
    ALL_STATUSES,
    OPEN_STATUSES,
    RelayBindingConflictError,
    RelayCaseService,
)
from app.utils.response import bad_request, error, server_error, success


class RelayCaseHandlers:
    """把 HTTP 参数转换成接力领域服务调用。"""

    @staticmethod
    def _statuses():
        raw_values = request.args.getlist("statuses")
        if not raw_values:
            return list(OPEN_STATUSES)
        statuses = []
        for raw_value in raw_values:
            statuses.extend(
                value.strip()
                for value in raw_value.split(",")
                if value.strip()
            )
        if not statuses:
            raise ValueError("状态筛选不能为空")
        invalid = set(statuses) - set(ALL_STATUSES)
        if invalid:
            raise ValueError(
                "无效的接力状态: " + ", ".join(sorted(invalid))
            )
        return list(dict.fromkeys(statuses))

    @staticmethod
    def _date_arg(name, default):
        raw_value = request.args.get(name)
        if not raw_value:
            return default
        try:
            return date.fromisoformat(raw_value)
        except ValueError as exc:
            raise ValueError(f"{name} 必须是 YYYY-MM-DD 日期") from exc

    @staticmethod
    def _positive_int(name, default, maximum=None):
        raw_value = request.args.get(name)
        try:
            value = int(raw_value) if raw_value is not None else default
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} 必须是正整数") from exc
        if value < 1:
            raise ValueError(f"{name} 必须是正整数")
        if maximum is not None and value > maximum:
            raise ValueError(f"{name} 不能大于 {maximum}")
        return value

    @staticmethod
    def _case_payload(relay_case, tracking=None):
        return {
            "case_id": relay_case.id,
            "predecessor_rental_id": relay_case.predecessor_rental_id,
            "successor_rental_id": relay_case.successor_rental_id,
            "status": relay_case.status,
            "sf_tracking_number": relay_case.sf_tracking_number,
            "tracking": tracking or RelayCaseService._tracking(relay_case),
            "notified_at": (
                relay_case.notified_at.isoformat()
                if relay_case.notified_at else None
            ),
            "agreed_at": (
                relay_case.agreed_at.isoformat()
                if relay_case.agreed_at else None
            ),
            "shipped_at": (
                relay_case.shipped_at.isoformat()
                if relay_case.shipped_at else None
            ),
            "completed_at": (
                relay_case.completed_at.isoformat()
                if relay_case.completed_at else None
            ),
        }

    @classmethod
    def handle_list(cls):
        today = date.today()
        try:
            statuses = cls._statuses()
            ship_date_from = cls._date_arg(
                "ship_date_from", today - timedelta(days=3)
            )
            ship_date_to = cls._date_arg(
                "ship_date_to", today + timedelta(days=5)
            )
            page = cls._positive_int("page", 1)
            per_page = cls._positive_int("per_page", 50, maximum=100)
            data = RelayCaseService.list_cases(
                statuses=statuses,
                ship_date_from=ship_date_from,
                ship_date_to=ship_date_to,
                page=page,
                per_page=per_page,
                today=today,
            )
            return success(data=data)
        except ValueError as exc:
            return bad_request(str(exc))
        except Exception:
            current_app.logger.exception("加载接力管理列表失败")
            return server_error("加载接力管理列表失败")

    @classmethod
    def handle_update(cls, predecessor_id, successor_id):
        data = request.get_json(silent=True) or {}
        status = data.get("status")
        if not status:
            return bad_request("缺少接力状态")
        try:
            relay_case = RelayCaseService.update_case(
                predecessor_id,
                successor_id,
                status,
                sf_tracking_number=data.get("sf_tracking_number"),
            )
            tracking = None
            if status == "shipped":
                tracking = RelayCaseService.refresh_tracking(relay_case.id)
            return success(
                data=cls._case_payload(relay_case, tracking),
                message="接力状态已更新",
            )
        except RelayBindingConflictError as exc:
            return error(str(exc), status_code=409)
        except ValueError as exc:
            return bad_request(str(exc))
        except Exception:
            db.session.rollback()
            current_app.logger.exception("更新接力状态失败")
            return server_error("更新接力状态失败，所有修改已回滚")

    @staticmethod
    def handle_refresh_tracking(case_id):
        try:
            return success(
                data=RelayCaseService.refresh_tracking(case_id),
                message="物流状态已刷新",
            )
        except ValueError as exc:
            return bad_request(str(exc))
        except Exception:
            current_app.logger.exception("刷新接力物流失败")
            return server_error("刷新接力物流失败")

    @staticmethod
    def handle_refresh_tracking_batch():
        data = request.get_json(silent=True) or {}
        case_ids = data.get("case_ids")
        if not isinstance(case_ids, list) or not case_ids:
            return bad_request("case_ids 必须是非空列表")
        if len(case_ids) > 100:
            return bad_request("一次最多刷新 100 条接力物流")
        try:
            normalized_ids = [int(case_id) for case_id in case_ids]
        except (TypeError, ValueError):
            return bad_request("case_ids 必须只包含整数")

        items = []
        success_count = 0
        for case_id in normalized_ids:
            try:
                tracking = RelayCaseService.refresh_tracking(case_id)
                items.append({
                    "case_id": case_id,
                    "success": True,
                    "tracking": tracking,
                })
                success_count += 1
            except Exception as exc:
                items.append({
                    "case_id": case_id,
                    "success": False,
                    "message": str(exc) or "物流刷新失败",
                })
        return success(data={
            "items": items,
            "total": len(items),
            "success_count": success_count,
        })
