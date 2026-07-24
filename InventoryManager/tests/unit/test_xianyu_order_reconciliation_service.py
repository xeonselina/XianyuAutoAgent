"""闲鱼漏录订单对账服务测试。"""

from datetime import date, datetime
import threading
import time
from unittest.mock import Mock

import pytest


@pytest.fixture
def app():
    from app import create_app

    return create_app("testing")


@pytest.fixture
def db_session(app):
    from app import db

    with app.app_context():
        db.create_all()
        yield db.session
        db.session.rollback()
        db.drop_all()


@pytest.fixture
def device(db_session):
    from app.models.device import Device

    row = Device(name="测试相机", is_accessory=False)
    db_session.add(row)
    db_session.commit()
    return row


def make_order(order_no, pay_amount, refund_status=0):
    return {
        "order_no": order_no,
        "order_status": 12,
        "pay_amount": pay_amount,
        "refund_status": refund_status,
        "order_time": 1784880000,
        "buyer_nick": f"买家-{order_no}",
        "receiver_name": "收件人",
        "receiver_mobile": "13800138000",
        "prov_name": "广东省",
        "city_name": "深圳市",
        "area_name": "南山区",
        "town_name": "粤海街道",
        "address": "测试路1号",
        "goods": {
            "title": "相机租赁",
            "sku_text": "套餐A",
        },
    }


def make_rental(device_id, order_no):
    from app.models.rental import Rental

    return Rental(
        device_id=device_id,
        start_date=date(2026, 7, 25),
        end_date=date(2026, 7, 26),
        customer_name="已录入客户",
        xianyu_order_no=order_no,
        status="not_shipped",
    )


def test_alert_serializes_amount_and_order_fields(app, db_session):
    from app.models.xianyu_order_alert import XianyuOrderAlert

    with app.app_context():
        alert = XianyuOrderAlert(
            order_no=" XY-1 ",
            state="pending",
            pay_amount=5001,
            buyer_nick="买家",
            receiver_mobile="13800138000",
            goods_title="相机租赁",
        )
        db_session.add(alert)
        db_session.commit()

        payload = alert.to_dict()

        assert alert.order_no == "XY-1"
        assert payload["pay_amount"] == 5001
        assert payload["buyer_nick"] == "买家"


def test_alert_serializes_naive_database_datetimes_as_utc(
    app,
    db_session,
):
    from app.models.xianyu_order_alert import XianyuOrderAlert

    with app.app_context():
        alert = XianyuOrderAlert(
            order_no="UTC-1",
            state="pending",
            pay_amount=5001,
            order_time=datetime(2026, 7, 24, 2, 0, 0),
        )
        db_session.add(alert)
        db_session.commit()

        assert alert.to_dict()["order_time"] == "2026-07-24T02:00:00Z"


def test_reconcile_filters_amount_and_existing_rentals(
    db_session,
    device,
    monkeypatch,
    tmp_path,
):
    from app.services.xianyu_order_reconciliation_service import (
        XianyuOrderReconciliationService,
    )

    db_session.add(make_rental(device.id, " RECORDED "))
    db_session.commit()
    service = XianyuOrderReconciliationService(
        lock_path=str(tmp_path / "reconcile.lock")
    )
    monkeypatch.setattr(
        service.xianyu_service,
        "list_orders",
        lambda: [
            make_order("LOW", 5000),
            make_order("MISSING", 5001),
            make_order("RECORDED", 9000),
        ],
    )

    result = service.reconcile()

    assert [
        row["order_no"] for row in result["alerts"]
    ] == ["MISSING"]
    assert result["count"] == 1


def test_reconcile_does_not_filter_refund_status(
    db_session,
    monkeypatch,
    tmp_path,
):
    from app.services.xianyu_order_reconciliation_service import (
        XianyuOrderReconciliationService,
    )

    service = XianyuOrderReconciliationService(
        lock_path=str(tmp_path / "reconcile.lock")
    )
    monkeypatch.setattr(
        service.xianyu_service,
        "list_orders",
        lambda: [make_order("REFUNDING", 8000, refund_status=5)],
    )

    result = service.reconcile()

    assert [row["order_no"] for row in result["alerts"]] == [
        "REFUNDING"
    ]


def test_ignore_is_permanent_across_reconciliation(
    db_session,
    monkeypatch,
    tmp_path,
):
    from app.models.xianyu_order_alert import XianyuOrderAlert
    from app.services.xianyu_order_reconciliation_service import (
        XianyuOrderReconciliationService,
    )

    service = XianyuOrderReconciliationService(
        lock_path=str(tmp_path / "reconcile.lock")
    )
    monkeypatch.setattr(
        service.xianyu_service,
        "list_orders",
        lambda: [make_order("IGNORE-ME", 8000)],
    )

    assert service.reconcile()["count"] == 1
    assert service.ignore("IGNORE-ME", "非租赁商品")["count"] == 0
    assert service.reconcile()["count"] == 0

    ignored = XianyuOrderAlert.query.filter_by(
        order_no="IGNORE-ME"
    ).one()
    assert ignored.state == "ignored"
    assert ignored.ignored_reason == "非租赁商品"


def test_ignore_rejects_reason_longer_than_storage_limit(
    db_session,
    monkeypatch,
    tmp_path,
):
    from app.services.xianyu_order_reconciliation_service import (
        XianyuOrderReconciliationService,
    )

    service = XianyuOrderReconciliationService(
        lock_path=str(tmp_path / "reconcile.lock")
    )

    with pytest.raises(ValueError, match="500"):
        service.ignore("IGNORE-ME", "原" * 501)


def test_blocking_lock_serializes_ignore_with_reconciliation(tmp_path):
    from app.services.xianyu_order_reconciliation_service import (
        XianyuOrderReconciliationService,
    )

    lock_path = str(tmp_path / "reconcile.lock")
    reconciling_service = XianyuOrderReconciliationService(
        lock_path=lock_path
    )
    ignoring_service = XianyuOrderReconciliationService(
        lock_path=lock_path
    )
    reconcile_lock = reconciling_service._try_acquire_lock()
    acquired = threading.Event()
    release = threading.Event()

    def wait_for_lock():
        lock_handle = ignoring_service._acquire_lock()
        acquired.set()
        release.wait(timeout=2)
        ignoring_service._release_lock(lock_handle)

    worker = threading.Thread(target=wait_for_lock)
    worker.start()
    time.sleep(0.05)
    assert acquired.is_set() is False

    reconciling_service._release_lock(reconcile_lock)
    assert acquired.wait(timeout=1) is True
    release.set()
    worker.join(timeout=1)
    assert worker.is_alive() is False


def test_ignore_uses_reconciliation_lock(
    db_session,
    monkeypatch,
    tmp_path,
):
    from app.models.xianyu_order_alert import XianyuOrderAlert
    from app.services.xianyu_order_reconciliation_service import (
        XianyuOrderReconciliationService,
    )

    db_session.add(
        XianyuOrderAlert(
            order_no="LOCKED-IGNORE",
            state="pending",
            pay_amount=8000,
        )
    )
    db_session.commit()
    service = XianyuOrderReconciliationService(
        lock_path=str(tmp_path / "reconcile.lock")
    )
    acquire = Mock(wraps=service._acquire_lock)
    monkeypatch.setattr(service, "_acquire_lock", acquire)

    service.ignore("LOCKED-IGNORE", "非租赁商品")

    acquire.assert_called_once_with()


def test_failed_reconcile_keeps_existing_cache(
    db_session,
    monkeypatch,
    tmp_path,
):
    from app.models.xianyu_order_alert import XianyuOrderAlert
    from app.services.xianyu_order_reconciliation_service import (
        XianyuOrderReconciliationService,
    )
    from app.services.xianyu_order_service import (
        XianyuOrderServiceError,
    )

    db_session.add(
        XianyuOrderAlert(
            order_no="OLD",
            state="pending",
            pay_amount=6000,
        )
    )
    db_session.commit()
    service = XianyuOrderReconciliationService(
        lock_path=str(tmp_path / "reconcile.lock")
    )

    def fail():
        raise XianyuOrderServiceError("timeout")

    monkeypatch.setattr(service.xianyu_service, "list_orders", fail)

    result = service.reconcile()

    assert [row["order_no"] for row in result["alerts"]] == ["OLD"]
    assert result["sync"]["last_error"] == "闲鱼订单查询失败"


def test_unexpected_reconcile_error_does_not_persist_or_log_pii(
    db_session,
    monkeypatch,
    tmp_path,
    caplog,
):
    from app.models.xianyu_order_alert import XianyuOrderAlert
    from app.services.xianyu_order_reconciliation_service import (
        XianyuOrderReconciliationService,
    )

    db_session.add(
        XianyuOrderAlert(
            order_no="OLD",
            state="pending",
            pay_amount=6000,
        )
    )
    db_session.commit()
    service = XianyuOrderReconciliationService(
        lock_path=str(tmp_path / "reconcile.lock")
    )
    sensitive_value = "13800138000"

    def fail():
        raise RuntimeError(f"SQL bind receiver_mobile={sensitive_value}")

    monkeypatch.setattr(service.xianyu_service, "list_orders", fail)

    result = service.reconcile()

    assert result["sync"]["last_error"] == "漏录订单检查失败"
    assert sensitive_value not in caplog.text


def test_busy_reconciliation_does_not_start_second_external_query(
    db_session,
    monkeypatch,
    tmp_path,
):
    from app.services.xianyu_order_reconciliation_service import (
        XianyuOrderReconciliationService,
    )

    lock_path = str(tmp_path / "reconcile.lock")
    running_service = XianyuOrderReconciliationService(
        lock_path=lock_path
    )
    second_service = XianyuOrderReconciliationService(
        lock_path=lock_path
    )
    lock_handle = running_service._try_acquire_lock()
    external_query = Mock()
    monkeypatch.setattr(
        second_service.xianyu_service, "list_orders", external_query
    )

    try:
        result = second_service.reconcile()
    finally:
        running_service._release_lock(lock_handle)

    assert result["refreshing"] is True
    external_query.assert_not_called()


def test_cached_alert_disappears_immediately_after_rental_is_recorded(
    db_session,
    device,
):
    from app.models.xianyu_order_alert import XianyuOrderAlert
    from app.services.xianyu_order_reconciliation_service import (
        XianyuOrderReconciliationService,
    )

    db_session.add(
        XianyuOrderAlert(
            order_no="JUST-RECORDED",
            state="pending",
            pay_amount=8800,
        )
    )
    db_session.commit()
    service = XianyuOrderReconciliationService()
    assert service.get_snapshot()["count"] == 1

    db_session.add(make_rental(device.id, "JUST-RECORDED"))
    db_session.commit()

    assert service.get_snapshot()["count"] == 0
