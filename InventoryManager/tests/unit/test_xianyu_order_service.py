"""闲管家订单客户端测试。"""

import json
import logging

import pytest
import requests

from app.services.xianyu_order_service import XianyuOrderService


def make_service():
    service = XianyuOrderService()
    service.app_key = "test-app"
    service.app_secret = "test-secret"
    return service


def test_list_orders_fetches_every_page(monkeypatch):
    service = make_service()
    responses = [
        {
            "code": 0,
            "data": {
                "list": [{"order_no": "1"}],
                "count": 2,
                "page_no": 1,
                "page_size": 1,
            },
        },
        {
            "code": 0,
            "data": {
                "list": [{"order_no": "2"}],
                "count": 2,
                "page_no": 2,
                "page_size": 1,
            },
        },
    ]
    requests = []

    def fake_request(path, body):
        requests.append((path, body))
        return responses.pop(0)

    monkeypatch.setattr(service, "_request_with_body_sign", fake_request)

    assert [
        row["order_no"] for row in service.list_orders(page_size=1)
    ] == ["1", "2"]
    assert requests == [
        (
            "/api/open/order/list",
            {"order_status": 12, "page_no": 1, "page_size": 1},
        ),
        (
            "/api/open/order/list",
            {"order_status": 12, "page_no": 2, "page_size": 1},
        ),
    ]


def test_list_orders_rejects_partial_results(monkeypatch):
    from app.services.xianyu_order_service import XianyuOrderServiceError

    service = make_service()
    responses = [
        {
            "code": 0,
            "data": {
                "list": [{"order_no": "1"}],
                "count": 2,
            },
        },
        None,
    ]
    monkeypatch.setattr(
        service,
        "_request_with_body_sign",
        lambda *_args, **_kwargs: responses.pop(0),
    )

    with pytest.raises(
        XianyuOrderServiceError,
        match="订单列表无响应",
    ):
        service.list_orders(page_size=1)


@pytest.mark.parametrize("count", [None, -1])
def test_list_orders_rejects_missing_or_negative_total(
    monkeypatch,
    count,
):
    from app.services.xianyu_order_service import XianyuOrderServiceError

    service = make_service()
    data = {"list": [{"order_no": "1"}]}
    if count is not None:
        data["count"] = count
    monkeypatch.setattr(
        service,
        "_request_with_body_sign",
        lambda *_args, **_kwargs: {"code": 0, "data": data},
    )

    with pytest.raises(XianyuOrderServiceError):
        service.list_orders(page_size=1)


def test_list_orders_rejects_total_that_changes_between_pages(
    monkeypatch,
):
    from app.services.xianyu_order_service import XianyuOrderServiceError

    service = make_service()
    responses = [
        {
            "code": 0,
            "data": {"list": [{"order_no": "1"}], "count": 3},
        },
        {
            "code": 0,
            "data": {"list": [{"order_no": "2"}], "count": 2},
        },
    ]
    monkeypatch.setattr(
        service,
        "_request_with_body_sign",
        lambda *_args, **_kwargs: responses.pop(0),
    )

    with pytest.raises(
        XianyuOrderServiceError,
        match="总数不一致",
    ):
        service.list_orders(page_size=1)


def test_signing_logs_do_not_expose_app_secret(caplog):
    service = make_service()
    service.app_secret = "never-log-this-secret"

    with caplog.at_level(logging.DEBUG):
        service._gen_param_sign({"order_no": "XY-1"})

    assert service.app_secret not in caplog.text


def test_invalid_json_logs_do_not_expose_response_body(
    monkeypatch,
    caplog,
):
    service = make_service()

    class InvalidJsonResponse:
        status_code = 200
        text = "买家手机号 13800138000"

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            raise json.JSONDecodeError("invalid", "x", 0)

    monkeypatch.setattr(
        "app.services.xianyu_order_service.requests.post",
        lambda *_args, **_kwargs: InvalidJsonResponse(),
    )

    with caplog.at_level(logging.ERROR):
        assert (
            service._request_with_body_sign(
                "/api/open/order/list",
                {"order_status": 12},
            )
            is None
        )

    assert "13800138000" not in caplog.text


def test_request_failure_logs_do_not_expose_signed_url(
    monkeypatch,
    caplog,
):
    service = make_service()
    signed_url = (
        "https://open.goofish.pro/api/open/order/list"
        "?appid=test-app&timestamp=1&sign=never-log-this-sign"
    )
    prepared_request = requests.Request(
        "POST",
        signed_url,
    ).prepare()
    failure = requests.HTTPError(
        f"500 Server Error for url: {signed_url}",
        request=prepared_request,
    )
    monkeypatch.setattr(
        "app.services.xianyu_order_service.requests.post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )

    with caplog.at_level(logging.ERROR):
        assert (
            service._request_with_body_sign(
                "/api/open/order/list",
                {"order_status": 12},
            )
            is None
        )

    assert "never-log-this-sign" not in caplog.text
    assert "appid=test-app" not in caplog.text
