from datetime import date, timedelta

import pytest

from app import db
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental


@pytest.fixture
def app():
    from app import create_app

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


def _rental(device_id, *, end_date, status="shipped", parent_rental_id=None):
    return Rental(
        device_id=device_id,
        start_date=end_date - timedelta(days=3),
        end_date=end_date,
        customer_name="提醒测试客户",
        customer_phone="13800138000",
        destination="上海市浦东新区测试路 1 号",
        status=status,
        parent_rental_id=parent_rental_id,
    )


def test_due_today_returns_only_shipped_main_rentals_ended_yesterday(
    app,
    client,
    db_session,
):
    today = date.today()
    yesterday = today - timedelta(days=1)
    with app.app_context():
        model = DeviceModel(
            name="iphone-15-pro",
            display_name="iPhone 15 Pro",
            is_accessory=False,
        )
        db_session.add(model)
        db_session.flush()
        main_device = Device(
            name="手机-01",
            serial_number="DUE-MAIN-01",
            model="iphone-15-pro",
            model_id=model.id,
            is_accessory=False,
        )
        accessory = Device(
            name="手机支架-01",
            serial_number="DUE-CHILD-01",
            model="phone-holder",
            is_accessory=True,
        )
        db_session.add_all([main_device, accessory])
        db_session.flush()

        due = _rental(main_device.id, end_date=yesterday)
        db_session.add(due)
        db_session.flush()
        due_id = due.id
        db_session.add_all([
            _rental(
                accessory.id,
                end_date=yesterday,
                parent_rental_id=due.id,
            ),
            _rental(
                main_device.id,
                end_date=yesterday,
                status="returned",
            ),
            _rental(main_device.id, end_date=today),
        ])
        db_session.commit()

        response = client.get("/api/rentals/due-today")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["count"] == 1
    assert payload["data"]["rentals"] == [{
        "id": due_id,
        "device_model": "iPhone 15 Pro",
        "start_date": (yesterday - timedelta(days=3)).isoformat(),
        "end_date": yesterday.isoformat(),
        "destination": "上海市浦东新区测试路 1 号",
        "customer_phone": "13800138000",
        "status": "shipped",
    }]


def test_due_today_uses_device_model_and_name_fallbacks(
    app,
    client,
    db_session,
):
    yesterday = date.today() - timedelta(days=1)
    with app.app_context():
        legacy_model_device = Device(
            name="手机-02",
            serial_number="DUE-FALLBACK-MODEL",
            model="x200u",
            is_accessory=False,
        )
        name_fallback_device = Device(
            name="未命名型号手机",
            serial_number="DUE-FALLBACK-NAME",
            model="",
            is_accessory=False,
        )
        db_session.add_all([legacy_model_device, name_fallback_device])
        db_session.flush()
        db_session.add_all([
            _rental(legacy_model_device.id, end_date=yesterday),
            _rental(name_fallback_device.id, end_date=yesterday),
        ])
        db_session.commit()

        response = client.get("/api/rentals/due-today")

    rows = response.get_json()["data"]["rentals"]
    assert [row["device_model"] for row in rows] == [
        "x200u",
        "未命名型号手机",
    ]
