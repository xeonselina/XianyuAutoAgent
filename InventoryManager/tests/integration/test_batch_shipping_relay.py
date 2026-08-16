from datetime import date, datetime, timedelta

import pytest

from app import create_app, db
from app.models.device import Device
from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding


@pytest.fixture
def app():
    return create_app("testing")


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    with app.app_context():
        db.create_all()
        yield db.session
        db.session.rollback()
        db.drop_all()


def seed_relay_pair(db_session):
    ship_date = date(2026, 8, 20)
    device = Device(
        name="批量发货接力测试设备",
        model="x300u",
        is_accessory=False,
    )
    db_session.add(device)
    db_session.flush()

    predecessor = Rental(
        device_id=device.id,
        start_date=ship_date - timedelta(days=6),
        end_date=ship_date - timedelta(days=2),
        ship_out_time=datetime(2026, 8, 13, 19),
        customer_name="接力前单",
        customer_phone="13800138000",
        destination="杭州市",
        status="not_shipped",
    )
    successor = Rental(
        device_id=device.id,
        start_date=ship_date + timedelta(days=1),
        end_date=ship_date + timedelta(days=4),
        ship_out_time=datetime(2026, 8, 20, 19),
        customer_name="接力后单",
        customer_phone="13900139000",
        destination="上海市",
        status="not_shipped",
    )
    db_session.add_all([predecessor, successor])
    db_session.flush()
    db_session.add(RentalRelayBinding(
        predecessor_rental_id=predecessor.id,
        successor_rental_id=successor.id,
    ))
    db_session.commit()
    return predecessor, successor


def test_ship_date_list_marks_relay_successor(client, db_session):
    predecessor, successor = seed_relay_pair(db_session)

    response = client.get(
        "/api/rentals/by-ship-date",
        query_string={
            "start_date": "2026-08-20",
            "end_date": "2026-08-20",
        },
    )

    assert response.status_code == 200
    rentals = response.get_json()["data"]["rentals"]
    assert len(rentals) == 1
    assert rentals[0]["id"] == successor.id
    assert rentals[0]["is_relay_shipping"] is True
    assert rentals[0]["relay_predecessor_rental_id"] == predecessor.id


def test_schedule_api_refuses_relay_successor(
    client, db_session, monkeypatch
):
    _, successor = seed_relay_pair(db_session)
    shipping_calls = []

    class FakeSFService:
        def place_shipping_order(self, *_args, **_kwargs):
            shipping_calls.append(True)
            return {"success": True, "waybill_no": "SF-SHOULD-NOT-EXIST"}

    monkeypatch.setattr(
        "app.services.shipping.sf_express_service.get_sf_express_service",
        lambda: FakeSFService(),
    )
    monkeypatch.setattr(
        "app.services.xianyu_order_service.get_xianyu_service",
        lambda: object(),
    )

    response = client.post(
        "/api/shipping-batch/schedule",
        json={
            "rental_ids": [successor.id],
            "scheduled_time": "2026-08-20T18:00:00",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["scheduled_count"] == 0
    assert len(payload["failed_rentals"]) == 1
    assert "接力订单" in payload["failed_rentals"][0]["reason"]
    assert shipping_calls == []
    db_session.refresh(successor)
    assert successor.status == "not_shipped"
    assert successor.ship_out_tracking_no is None
