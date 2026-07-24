"""闲鱼漏录订单告警 API 集成测试。"""

import pytest


@pytest.fixture
def app():
    from app import create_app

    return create_app("testing")


@pytest.fixture
def client(app):
    return app.test_client()


def snapshot(order_no="XY-1"):
    alerts = [{"order_no": order_no}] if order_no else []
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
        "/api/xianyu-order-alerts/XY-1/ignore",
        json={"reason": "   "},
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "忽略原因不能为空"


def test_ignore_maps_missing_alert_to_not_found(client, monkeypatch):
    from app.handlers.xianyu_order_alert_handlers import (
        XianyuOrderAlertHandlers,
    )

    def missing(_order_no, _reason):
        raise LookupError("待处理订单不存在")

    monkeypatch.setattr(
        XianyuOrderAlertHandlers.service,
        "ignore",
        missing,
    )

    response = client.post(
        "/api/xianyu-order-alerts/UNKNOWN/ignore",
        json={"reason": "无需占用库存"},
    )

    assert response.status_code == 404
    assert response.get_json()["message"] == "待处理订单不存在"
