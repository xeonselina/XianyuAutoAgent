"""可由普通发货和客户接力共同复用的顺丰轨迹查询。"""

import re

from flask import has_app_context
from sqlalchemy import or_

from app.models.rental import Rental


class TrackingNotFoundError(ValueError):
    """顺丰没有返回目标运单的轨迹。"""


class SFTrackingService:
    """校验查询参数并封装顺丰 SDK 的查询和解析步骤。"""

    @staticmethod
    def _validate_phone_last4(phone_last4):
        normalized = str(phone_last4 or "").strip()
        if not re.fullmatch(r"\d{4}", normalized):
            raise ValueError("顺丰查询手机后四位必须是 4 位数字")
        return normalized

    @classmethod
    def get_client(cls, rental=None, warehouse_id=None):
        from app.services.integration_resolver import IntegrationResolver

        resolver = IntegrationResolver()
        if rental is not None:
            return resolver.sf_for_rental(rental).client
        if warehouse_id is not None:
            return resolver.sf_for_warehouse(warehouse_id).client
        return resolver.sf_for_only_warehouse().client

    @staticmethod
    def _matched_rental(tracking_number):
        if not has_app_context():
            return None
        return Rental.query.filter(
            Rental.parent_rental_id.is_(None),
            or_(
                Rental.ship_out_tracking_no == tracking_number,
                Rental.ship_in_tracking_no == tracking_number,
            ),
        ).order_by(Rental.id).first()

    @classmethod
    def _query_client(cls, client, tracking_number, phone_last4):
        response = client.search_routes(tracking_number, phone_last4)
        parsed_routes = client.parse_route_response(response)
        route_info = parsed_routes.get(tracking_number)
        if route_info is None:
            raise TrackingNotFoundError("未找到该运单的物流信息")
        return route_info

    @classmethod
    def query(cls, tracking_number, phone_last4, rental=None, warehouse_id=None):
        tracking_number = str(tracking_number or "").strip()
        if not tracking_number:
            raise ValueError("顺丰运单号不能为空")
        phone_last4 = cls._validate_phone_last4(phone_last4)

        rental = rental or (
            cls._matched_rental(tracking_number)
            if warehouse_id is None else None
        )
        if rental is not None:
            client = cls.get_client(rental=rental)
        elif warehouse_id is not None:
            client = cls.get_client(warehouse_id=warehouse_id)
        else:
            # Temporary compatibility for non-request unit callers only.
            client = cls.get_client()
        return cls._query_client(client, tracking_number, phone_last4)

    @classmethod
    def query_scoped(cls, tracking_number, warehouse_id=None, phone_last4=None):
        """Resolve a manual query by matched Rental or explicit warehouse."""
        tracking_number = str(tracking_number or "").strip()
        if not tracking_number:
            raise ValueError("顺丰运单号不能为空")
        rental = cls._matched_rental(tracking_number)
        from app.services.integration_resolver import IntegrationResolver

        resolver = IntegrationResolver()
        if rental is not None:
            service = resolver.sf_for_rental(rental)
            digits = re.sub(r"\D", "", rental.customer_phone or "")
            if len(digits) < 4:
                digits = re.sub(r"\D", "", service.sender_phone or "")
            suffix = digits[-4:] if len(digits) >= 4 else phone_last4
        else:
            if isinstance(warehouse_id, bool):
                raise ValueError("无法匹配租赁时必须指定仓库")
            try:
                warehouse_id = int(warehouse_id)
            except (TypeError, ValueError):
                raise ValueError("无法匹配租赁时必须指定仓库") from None
            service = resolver.sf_for_warehouse(warehouse_id)
            suffix = phone_last4
        suffix = cls._validate_phone_last4(suffix)
        return cls._query_client(service.client, tracking_number, suffix)

    @classmethod
    def batch_query(cls, tracking_numbers, phone_last4):
        normalized_numbers = [
            str(number or "").strip() for number in tracking_numbers or []
        ]
        if not normalized_numbers or any(not number for number in normalized_numbers):
            raise ValueError("顺丰运单号列表不能为空")
        if len(normalized_numbers) > 100:
            raise ValueError("一次最多查询100个运单号")
        phone_last4 = cls._validate_phone_last4(phone_last4)

        client = cls.get_client()
        response = client.batch_search_routes(
            normalized_numbers, phone_last4
        )
        return client.parse_route_response(response)
