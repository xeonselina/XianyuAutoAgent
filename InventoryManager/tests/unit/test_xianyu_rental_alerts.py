"""仅使用 SQLite 内存数据库与模拟闲鱼响应。"""

from unittest.mock import Mock

import pytest

from app import db
from app.models.xianyu_rental_alert import XianyuRentalAlert
from app.models.xianyu_shop import XianyuShop
from app.services.xianyu_order_reconciliation_service import XianyuOrderReconciliationService
from tests.unit.test_xianyu_order_reconciliation_service import (
    app, db_session, device, make_alert, make_order, make_rental,
)


def client_for(**orders):
    return Mock(list_orders=Mock(return_value=[]), get_order_detail=Mock(side_effect=orders.get))


def order(status=24, refund_status=0, **values):
    return {**make_order("XY", 8000, refund_status), "order_status": status, **values}


def test_database_is_isolated_memory_sqlite(db_session):
    assert str(db.engine.url) == "sqlite:///:memory:"


def test_two_devices_on_normal_order_do_not_alert_or_repeat_lookup(db_session, device):
    db_session.add_all([make_rental(device.id, "XY"), make_rental(device.id, " XY ")])
    db_session.commit()
    client = client_for(XY=order(12))
    result = XianyuOrderReconciliationService(service=client).reconcile()
    assert result["rental_alerts"] == []
    assert result["sync"]["last_error"] is None
    client.get_order_detail.assert_called_once_with("XY")


def test_list_status_is_reused_without_detail_request(db_session, device):
    db_session.add_all([make_rental(device.id, "XY"), make_rental(device.id, "XY")])
    db_session.commit()
    client = client_for()
    client.list_orders.return_value = [order(12)]
    assert XianyuOrderReconciliationService(service=client).reconcile()["rental_alerts"] == []
    client.get_order_detail.assert_not_called()


@pytest.mark.parametrize("status", [23, 24, "23", "24"])
def test_closed_order_groups_devices_and_ignores_amount_threshold(db_session, device, status):
    rentals = [make_rental(device.id, "XY"), make_rental(device.id, " XY ")]
    db_session.add_all(rentals)
    db_session.commit()
    client = client_for(XY=order(status, pay_amount=1))
    result = XianyuOrderReconciliationService(service=client).reconcile()
    assert result["count"] == 0
    assert len(result["rental_alerts"]) == 1
    alert = result["rental_alerts"][0]
    assert alert["kind"] == "closed"
    assert {row["id"] for row in alert["rentals"]} == {row.id for row in rentals}
    assert alert["rentals"][0]["device_name"] == "测试相机"
    assert alert["last_seen_at"].endswith("Z")
    client.get_order_detail.assert_called_once_with("XY")


@pytest.mark.parametrize("status", ["not_shipped", "scheduled_for_shipping", "shipped", "returned", "completed", "cancelled"])
def test_only_outstanding_rentals_are_checked(db_session, device, status):
    rental = make_rental(device.id, "XY")
    rental.status = status
    db_session.add(rental)
    db_session.commit()
    client = client_for(XY=order())
    result = XianyuOrderReconciliationService(service=client).reconcile()
    active = status in {"not_shipped", "scheduled_for_shipping", "shipped"}
    assert bool(result["rental_alerts"]) == active
    assert client.get_order_detail.call_count == int(active)


@pytest.mark.parametrize("refund", [0, 4, 6])
def test_no_refund_cancelled_refund_and_rejected_refund_do_not_alert(db_session, device, refund):
    db_session.add(make_rental(device.id, "XY"))
    db_session.commit()
    result = XianyuOrderReconciliationService(service=client_for(XY=order(12, refund))).reconcile()
    assert result["rental_alerts"] == []


@pytest.mark.parametrize("refund", [1, 2, 3, 5, 8])
def test_refunds_on_live_order_only_ask_to_review(db_session, device, refund):
    db_session.add_all([make_rental(device.id, "XY"), make_rental(device.id, "XY")])
    db_session.commit()
    result = XianyuOrderReconciliationService(service=client_for(XY=order(12, refund))).reconcile()
    assert len(result["rental_alerts"]) == 1
    assert result["rental_alerts"][0]["kind"] == "refund_review"
    assert len(result["rental_alerts"][0]["rentals"]) == 2


def test_partial_refund_is_not_whole_order_cancellation(db_session, device):
    db_session.add(make_rental(device.id, "XY"))
    db_session.commit()
    result = XianyuOrderReconciliationService(service=client_for(
        XY=order(21, 5, refund_amount=2000),
    )).reconcile()
    assert result["rental_alerts"][0]["kind"] == "refund_review"
    assert result["rental_alerts"][0]["status_text"] == "部分退款，请核对"


def test_deleting_one_rental_keeps_other_until_all_handled_without_sync(db_session, device, app):
    first, second = make_rental(device.id, "XY"), make_rental(device.id, "XY")
    db_session.add_all([first, second])
    db_session.commit()
    service = XianyuOrderReconciliationService(service=client_for(XY=order()))
    assert len(service.reconcile()["rental_alerts"][0]["rentals"]) == 2
    db_session.delete(first)
    db_session.commit()
    # GET 只读取缓存与最新档期，删除后无需再调用闲鱼。
    result = app.test_client().get("/api/xianyu-order-alerts").get_json()["data"]
    assert [row["id"] for row in result["rental_alerts"][0]["rentals"]] == [second.id]
    second.status = "cancelled"
    db_session.commit()
    assert service.get_snapshot()["rental_alerts"] == []


def test_shop_identity_and_missing_order_ignore_are_independent(db_session, device):
    first = XianyuShop.query.first()
    second = XianyuShop(name="二店", app_key="", is_active=True)
    db_session.add(second)
    db_session.flush()
    db_session.add_all([
        make_rental(device.id, "XY", first.id), make_rental(device.id, "XY", second.id),
        make_alert(order_no="XY", state="ignored", pay_amount=8000),
    ])
    db_session.commit()
    service = XianyuOrderReconciliationService(service_factory=lambda shop: client_for(
        XY=order(24 if shop.id == first.id else 12),
    ))
    result = service.reconcile()
    assert [(row["xianyu_shop_id"], row["order_no"]) for row in result["rental_alerts"]] == [(first.id, "XY")]
    assert service.get_snapshot(second.id)["rental_alerts"] == []
    first.is_active = False
    db_session.commit()
    assert service.get_snapshot()["rental_alerts"] == []


@pytest.mark.parametrize("invalid", [None, {}, {"order_no": "OTHER"}, order(order_status=None), order(order_status=99), order(refund_status=None)])
def test_failed_detail_keeps_previous_alert_and_success_time(db_session, device, invalid):
    db_session.add(make_rental(device.id, "XY"))
    db_session.commit()
    client = client_for(XY=order())
    service = XianyuOrderReconciliationService(service=client)
    before = service.reconcile()
    client.get_order_detail.side_effect = lambda _: invalid
    after = service.reconcile()
    assert after["rental_alerts"] == before["rental_alerts"]
    assert after["sync"]["last_success_at"] == before["sync"]["last_success_at"]
    assert "1 笔档期订单状态查询失败" in after["sync"]["last_error"]


def test_one_failure_does_not_hide_other_new_closed_orders(db_session, device):
    db_session.add_all([make_rental(device.id, "BAD"), make_rental(device.id, "XY")])
    db_session.commit()
    result = XianyuOrderReconciliationService(service=client_for(XY=order())).reconcile()
    assert [row["order_no"] for row in result["rental_alerts"]] == ["XY"]
    assert result["sync"]["last_error"]


def test_recovered_normal_status_clears_alert_and_error(db_session, device):
    db_session.add(make_rental(device.id, "XY"))
    db_session.commit()
    client = client_for(XY=order())
    service = XianyuOrderReconciliationService(service=client)
    assert service.reconcile()["rental_alerts"]
    client.get_order_detail.side_effect = lambda _: order(12)
    assert service.reconcile()["rental_alerts"] == []
    assert XianyuRentalAlert.query.count() == 0


def test_intentionally_kept_closed_order_can_be_ignored_across_reconciliation(
    db_session, device,
):
    db_session.add(make_rental(device.id, "XY"))
    db_session.commit()
    client = client_for(XY=order())
    service = XianyuOrderReconciliationService(service=client)

    assert service.reconcile()["rental_alerts"]
    ignored = service.ignore_rental_alert(
        XianyuShop.query.first().id,
        "XY",
        "买家已线下确认，故意保留档期",
    )
    assert ignored["rental_alerts"] == []

    again = service.reconcile()
    assert again["rental_alerts"] == []
    cached = XianyuRentalAlert.query.one()
    assert cached.ignored_reason == "买家已线下确认，故意保留档期"
    assert cached.ignored_at is not None


def test_ignoring_missing_or_already_ignored_rental_alert_fails(db_session, device):
    service = XianyuOrderReconciliationService(service=client_for())
    with pytest.raises(LookupError, match="待处理档期提醒不存在"):
        service.ignore_rental_alert(1, "UNKNOWN", "无需提醒")


def test_changing_order_identity_hides_stale_cache_immediately(db_session, device):
    rental = make_rental(device.id, "XY")
    db_session.add(rental)
    db_session.commit()
    service = XianyuOrderReconciliationService(service=client_for(XY=order()))
    assert service.reconcile()["rental_alerts"]
    rental.xianyu_order_no = "NEW"
    db_session.commit()
    assert service.get_snapshot()["rental_alerts"] == []
