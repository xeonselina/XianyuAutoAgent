"""闲鱼漏录订单告警 API 集成测试。"""

from types import SimpleNamespace

import pytest


@pytest.fixture
def app():
    from app import create_app
    from flask import g

    application = create_app("testing")
    application.before_request(
        lambda: setattr(g, "member", SimpleNamespace(role="admin"))
    )
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def empty_business_client(app):
    from app import db

    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def snapshot(order_no="XY-1"):
    alerts = [{"order_no": order_no, "xianyu_shop_id": 7}] if order_no else []
    return {
        "alerts": alerts,
        "count": len(alerts),
        "sync": {
            "last_attempt_at": None,
            "last_success_at": None,
            "last_error": None,
        },
        "refreshing": False,
    }


def test_get_alerts_returns_cached_snapshot(client, monkeypatch):
    from app.handlers.xianyu_order_alert_handlers import (
        XianyuOrderAlertHandlers,
    )

    monkeypatch.setattr(
        XianyuOrderAlertHandlers.service,
        "get_snapshot",
        lambda: snapshot(),
    )

    response = client.get("/api/xianyu-order-alerts")

    assert response.status_code == 200
    assert response.get_json()["data"]["count"] == 1


def test_refresh_alerts_runs_reconciliation(client, monkeypatch):
    from app.handlers.xianyu_order_alert_handlers import (
        XianyuOrderAlertHandlers,
    )

    monkeypatch.setattr(
        XianyuOrderAlertHandlers.service,
        "reconcile",
        lambda: snapshot("XY-REFRESH"),
    )

    response = client.post("/api/xianyu-order-alerts/refresh")

    assert response.status_code == 200
    assert response.get_json()["data"]["alerts"][0]["order_no"] == (
        "XY-REFRESH"
    )


def test_ignore_requires_non_empty_reason(client):
    response = client.post(
        "/api/xianyu-order-alerts/7/XY-1/ignore",
        json={"reason": "   "},
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "忽略原因不能为空"


def test_ignore_rejects_reason_longer_than_500_characters(client):
    response = client.post(
        "/api/xianyu-order-alerts/7/XY-1/ignore",
        json={"reason": "原" * 501},
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "忽略原因不能超过500个字符"


def test_ignore_maps_missing_alert_to_not_found(client, monkeypatch):
    from app.handlers.xianyu_order_alert_handlers import (
        XianyuOrderAlertHandlers,
    )

    def missing(_shop_id, _order_no, _reason):
        raise LookupError("待处理订单不存在")

    monkeypatch.setattr(
        XianyuOrderAlertHandlers.service,
        "ignore",
        missing,
    )

    response = client.post(
        "/api/xianyu-order-alerts/7/UNKNOWN/ignore",
        json={"reason": "无需占用库存"},
    )

    assert response.status_code == 404
    assert response.get_json()["message"] == "待处理订单不存在"


def test_ignore_passes_compound_shop_order_identity(client, monkeypatch):
    from app.handlers.xianyu_order_alert_handlers import XianyuOrderAlertHandlers

    called = {}
    monkeypatch.setattr(XianyuOrderAlertHandlers.service, "ignore",
        lambda shop_id, order_no, reason: called.update(
            shop_id=shop_id, order_no=order_no, reason=reason) or snapshot(None))

    response = client.post("/api/xianyu-order-alerts/9/SAME/ignore", json={"reason": "不处理"})

    assert response.status_code == 200
    assert called == {"shop_id": 9, "order_no": "SAME", "reason": "不处理"}


@pytest.mark.parametrize("exists", [False, True])
def test_order_detail_rejects_missing_or_inactive_shop(empty_business_client, app, monkeypatch, exists):
    from app import db
    from app.models.xianyu_shop import XianyuShop
    shop_id = 999
    if exists:
        with app.app_context():
            shop = XianyuShop(name="停用店", app_key="key", is_active=False)
            db.session.add(shop); db.session.commit()
            shop_id = shop.id
    monkeypatch.setattr("app.services.xianyu_order_service.get_xianyu_service",
                        lambda **_: pytest.fail("不应调用外部闲鱼服务"))
    response = empty_business_client.post("/api/rentals/fetch-xianyu-order", json={"order_no": "XY-1", "xianyu_shop_id": shop_id})
    assert (response.status_code, response.get_json()["code"]) == (409, "CONFIG_INCOMPLETE")


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/xianyu-order-alerts", None),
        ("post", "/api/xianyu-order-alerts/refresh", None),
        (
            "post",
            "/api/xianyu-order-alerts/7/XY-1/ignore",
            {"reason": "无需处理"},
        ),
    ],
)
def test_missing_shop_returns_config_incomplete_without_500(
    empty_business_client,
    method,
    path,
    body,
):
    response = getattr(empty_business_client, method)(path, json=body)

    assert response.status_code == 409
    assert response.get_json() == {
        "success": False,
        "message": "闲鱼店铺不存在" if "/ignore" in path else "请先配置闲鱼店铺",
        "code": "CONFIG_INCOMPLETE",
    }
