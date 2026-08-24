"""Express-type API and carrier-order contract tests."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app import db
from app.models.device import Device
from app.models.rental import Rental
from app.services.shipping.sf_express_service import SFExpressService


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def rental(db_session):
    device = Device(name="快递类型测试设备", is_accessory=False)
    db_session.add(device)
    db_session.flush()

    record = Rental(
        device_id=device.id,
        start_date=date.today() + timedelta(days=2),
        end_date=date.today() + timedelta(days=5),
        customer_name="测试客户",
        customer_phone="13800138000",
        destination="浙江省杭州市测试路 1 号",
        status="not_shipped",
        express_type_id=2,
    )
    db_session.add(record)
    db_session.commit()
    return record


@pytest.mark.parametrize("express_type_id", [1, 2, 263])
def test_update_express_type_accepts_documented_products(
    client, db_session, rental, express_type_id
):
    response = client.patch(
        "/api/shipping-batch/express-type",
        json={"rental_id": rental.id, "express_type_id": express_type_id},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "message": "快递类型已更新",
    }
    db_session.refresh(rental)
    assert rental.express_type_id == express_type_id


@pytest.mark.parametrize("express_type_id", [6, 99, "2", True])
def test_update_express_type_rejects_undocumented_products(
    client, db_session, rental, express_type_id
):
    response = client.patch(
        "/api/shipping-batch/express-type",
        json={"rental_id": rental.id, "express_type_id": express_type_id},
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "快递类型无效"
    db_session.refresh(rental)
    assert rental.express_type_id == 2


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"rental_id": 1},
        {"express_type_id": 2},
        {"rental_id": 1, "express_type_id": None},
    ],
)
def test_update_express_type_rejects_missing_parameters(client, payload):
    response = client.patch(
        "/api/shipping-batch/express-type",
        json=payload,
    )

    assert response.status_code == 400
    assert "缺少必要参数" in response.get_json()["message"]


def test_update_express_type_returns_not_found(client, rental):
    response = client.patch(
        "/api/shipping-batch/express-type",
        json={"rental_id": rental.id + 9999, "express_type_id": 1},
    )

    assert response.status_code == 404
    assert response.get_json()["message"] == "租赁记录不存在"


@pytest.mark.parametrize(
    ("status", "tracking_no"),
    [
        ("not_shipped", "SF-LOCKED"),
        ("scheduled_for_shipping", None),
        ("shipped", None),
    ],
)
def test_update_express_type_is_locked_after_waybill_creation(
    client, db_session, rental, status, tracking_no
):
    rental.status = status
    rental.ship_out_tracking_no = tracking_no
    db_session.commit()

    response = client.patch(
        "/api/shipping-batch/express-type",
        json={"rental_id": rental.id, "express_type_id": 263},
    )

    assert response.status_code == 409
    assert response.get_json()["message"] == "运单已创建，快递类型不可修改"
    db_session.refresh(rental)
    assert rental.express_type_id == 2


def test_successful_scheduling_locks_express_type(
    client, db_session, rental, monkeypatch
):
    accessory = Device(name="预约发货附件", is_accessory=True)
    db_session.add(accessory)
    db_session.flush()
    child = Rental(
        device_id=accessory.id,
        start_date=rental.start_date,
        end_date=rental.end_date,
        customer_name=rental.customer_name,
        status="not_shipped",
        parent_rental_id=rental.id,
    )
    db_session.add(child)
    db_session.commit()

    class FakeSFService:
        def place_shipping_order(self, *_args, **_kwargs):
            return {"success": True, "waybill_no": "SF-CREATED"}

    monkeypatch.setattr(
        "app.services.shipping.sf_express_service.get_sf_express_service",
        lambda: FakeSFService(),
    )
    monkeypatch.setattr(
        "app.services.xianyu_order_service.get_xianyu_service",
        lambda: object(),
    )

    schedule_response = client.post(
        "/api/shipping-batch/schedule",
        json={
            "rental_ids": [rental.id],
            "scheduled_time": "2026-08-22T18:00:00",
        },
    )
    update_response = client.patch(
        "/api/shipping-batch/express-type",
        json={"rental_id": rental.id, "express_type_id": 263},
    )

    assert schedule_response.status_code == 200
    assert schedule_response.get_json()["data"]["scheduled_count"] == 1
    assert update_response.status_code == 409
    db_session.refresh(rental)
    db_session.refresh(child)
    assert rental.ship_out_tracking_no == "SF-CREATED"
    assert rental.status == "scheduled_for_shipping"
    assert rental.scheduled_ship_time == datetime(2026, 8, 22, 18)
    assert child.status == "scheduled_for_shipping"
    assert rental.express_type_id == 2


def _service_without_external_client():
    service = object.__new__(SFExpressService)
    service.monthly_card = "test-card"
    service.sender_name = "测试寄件人"
    service.sender_phone = "13800138000"
    service.sender_address = "广东省深圳市测试路 1 号"
    return service


def _rental_stub(express_type_id):
    return SimpleNamespace(
        id=7,
        customer_name="测试收件人",
        customer_phone="13900139000",
        destination="浙江省杭州市测试路 2 号",
        express_type_id=express_type_id,
        device=SimpleNamespace(
            device_model=SimpleNamespace(name="测试设备"),
        ),
    )


@pytest.mark.parametrize(
    ("express_type_id", "expected_id", "has_special_delivery"),
    [(None, 2, False), (1, 1, False), (263, 263, True)],
)
def test_sf_payload_uses_selected_or_application_default_product(
    express_type_id, expected_id, has_special_delivery
):
    service = _service_without_external_client()
    captured = {}

    def fake_create_order(order_data):
        captured.update(order_data)
        return {"success": True, "waybill_no": "SF-TEST"}

    service.create_order = fake_create_order

    result = service.place_shipping_order(
        _rental_stub(express_type_id),
        datetime(2026, 8, 22, 18, 0),
    )

    assert result["success"] is True
    assert captured["expressTypeId"] == expected_id
    assert ("specialDeliveryTypeCode" in captured) is has_special_delivery
    if has_special_delivery:
        assert captured["specialDeliveryTypeCode"] == 263


def test_sf_payload_rejects_legacy_product_six_without_provider_call():
    service = _service_without_external_client()
    provider_calls = []
    service.create_order = lambda order_data: provider_calls.append(order_data)

    result = service.place_shipping_order(
        _rental_stub(6),
        datetime(2026, 8, 22, 18, 0),
    )

    assert result == {
        "success": False,
        "message": "快递类型无效，请重新选择后再下单",
    }
    assert provider_calls == []
