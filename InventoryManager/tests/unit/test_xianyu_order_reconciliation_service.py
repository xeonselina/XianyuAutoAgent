"""闲鱼漏录订单对账服务测试。"""

from datetime import date

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
    assert result["sync"]["last_error"] == "timeout"
