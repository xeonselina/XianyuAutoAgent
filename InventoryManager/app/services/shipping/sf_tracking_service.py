"""可由普通发货和客户接力共同复用的顺丰轨迹查询。"""

import re


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
    def get_client(cls):
        raise RuntimeError(
            "legacy SF tracking requires an explicitly injected test client"
        )

    @classmethod
    def query(cls, tracking_number, phone_last4):
        tracking_number = str(tracking_number or "").strip()
        if not tracking_number:
            raise ValueError("顺丰运单号不能为空")
        phone_last4 = cls._validate_phone_last4(phone_last4)

        client = cls.get_client()
        response = client.search_routes(tracking_number, phone_last4)
        parsed_routes = client.parse_route_response(response)
        route_info = parsed_routes.get(tracking_number)
        if route_info is None:
            raise TrackingNotFoundError("未找到该运单的物流信息")
        return route_info

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
