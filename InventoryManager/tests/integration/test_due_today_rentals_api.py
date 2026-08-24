from datetime import date, timedelta

import pytest

from app import db
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental


@pytest.fixture
def client(app):
    return app.test_client()


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


def test_pending_returns_includes_due_today_and_overdue_main_rentals(
    app,
    client,
    db_session,
):
    today = date.today()
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

        overdue_days = [0, 1, 3, 4, 7, 8]
        pending_rentals = [
            _rental(
                main_device.id,
                end_date=today - timedelta(days=days + 1),
            )
            for days in overdue_days
        ]
        db_session.add_all(pending_rentals)
        db_session.flush()
        pending_ids = {
            days: rental.id for days, rental in zip(overdue_days, pending_rentals)
        }

        db_session.add_all(
            [
                _rental(
                    accessory.id,
                    end_date=today - timedelta(days=1),
                    parent_rental_id=pending_rentals[0].id,
                ),
                _rental(
                    main_device.id,
                    end_date=today - timedelta(days=10),
                    status="returned",
                ),
                _rental(main_device.id, end_date=today),
            ]
        )
        db_session.commit()

        response = client.get("/api/rentals/pending-returns")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["count"] == 6
    assert [
        (row["id"], row["due_date"], row["overdue_days"])
        for row in payload["data"]["rentals"]
    ] == [
        (pending_ids[8], (today - timedelta(days=8)).isoformat(), 8),
        (pending_ids[7], (today - timedelta(days=7)).isoformat(), 7),
        (pending_ids[4], (today - timedelta(days=4)).isoformat(), 4),
        (pending_ids[3], (today - timedelta(days=3)).isoformat(), 3),
        (pending_ids[1], (today - timedelta(days=1)).isoformat(), 1),
        (pending_ids[0], today.isoformat(), 0),
    ]
    assert all(
        row["device_model"] == "iPhone 15 Pro"
        and row["destination"] == "上海市浦东新区测试路 1 号"
        and row["customer_phone"] == "13800138000"
        and row["status"] == "shipped"
        for row in payload["data"]["rentals"]
    )


def test_due_today_endpoint_is_a_pending_returns_compatibility_alias(
    app,
    client,
    db_session,
):
    yesterday = date.today() - timedelta(days=1)
    with app.app_context():
        device = Device(
            name="手机-兼容接口",
            serial_number="PENDING-COMPAT",
            model="iphone-compat",
            is_accessory=False,
        )
        db_session.add(device)
        db_session.flush()
        db_session.add(_rental(device.id, end_date=yesterday))
        db_session.commit()

        canonical_response = client.get("/api/rentals/pending-returns")
        compatibility_response = client.get("/api/rentals/due-today")

    assert canonical_response.status_code == 200
    assert compatibility_response.status_code == 200
    assert compatibility_response.get_json()["data"] == (
        canonical_response.get_json()["data"]
    )


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
        db_session.add_all(
            [
                _rental(legacy_model_device.id, end_date=yesterday),
                _rental(name_fallback_device.id, end_date=yesterday),
            ]
        )
        db_session.commit()

        response = client.get("/api/rentals/pending-returns")

    rows = response.get_json()["data"]["rentals"]
    assert [row["device_model"] for row in rows] == [
        "x200u",
        "未命名型号手机",
    ]
