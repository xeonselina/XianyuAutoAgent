from datetime import date, datetime

import pytest

from app import create_app, db
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental
from app.services.rental_statistics_service import calculate_period_depreciation


@pytest.fixture
def app():
    application = create_app("testing")
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def add_rental(device_id, start_date, amount):
    db.session.add(
        Rental(
            device_id=device_id,
            start_date=start_date,
            end_date=start_date,
            customer_name=f"customer-{start_date}",
            order_amount=amount,
            status="completed",
        )
    )


def test_periodic_stats_prorate_device_until_lifecycle_date(app, client):
    with app.app_context():
        model = DeviceModel(
            name="stats-model",
            display_name="统计机型",
            is_accessory=False,
            device_value=7000,
        )
        db.session.add(model)
        db.session.flush()
        active = Device(
            name="active-device",
            serial_number="ACTIVE-1",
            model="stats-model",
            model_id=model.id,
            is_accessory=False,
            lifecycle_status="active",
        )
        sold = Device(
            name="sold-device",
            serial_number="SOLD-1",
            model="stats-model",
            model_id=model.id,
            is_accessory=False,
            lifecycle_status="sold",
            lifecycle_date=datetime(2026, 7, 15, 16, 30),
        )
        db.session.add_all([active, sold])
        db.session.flush()
        add_rental(active.id, date(2026, 7, 1), 100)
        add_rental(sold.id, date(2026, 7, 2), 200)
        add_rental(sold.id, date(2026, 7, 15), 300)
        add_rental(sold.id, date(2026, 7, 20), 400)
        db.session.commit()

        response = client.get(
            "/api/rental-stats/periodic",
            query_string={
                "period_type": "month",
                "model": str(model.id),
                "start_date": "2026-07-01",
                "end_date": "2026-07-31",
            },
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    row = payload["data"][0]
    assert row["device_count"] == 2
    assert row["available_device_weeks"] == pytest.approx(44 / 7, abs=0.0001)
    assert row["order_count"] == 2
    assert row["order_amount"] == 300
    assert row["rental_rate"] == pytest.approx(2 / (44 / 7), abs=0.0001)


def test_forecast_retains_exited_device_history_but_not_future_capacity(
    app, client
):
    with app.app_context():
        model = DeviceModel(
            name="x200u",
            display_name="X200 Ultra",
            is_accessory=False,
            device_value=7000,
        )
        db.session.add(model)
        db.session.flush()
        assert model.id == 1
        active = Device(
            name="active-x200u",
            serial_number="ACTIVE-X200U",
            model="x200u",
            model_id=model.id,
            is_accessory=False,
            lifecycle_status="active",
        )
        sold = Device(
            name="sold-x200u",
            serial_number="SOLD-X200U",
            model="x200u",
            model_id=model.id,
            is_accessory=False,
            lifecycle_status="sold",
            lifecycle_date=datetime(2026, 6, 1),
        )
        db.session.add_all([active, sold])
        db.session.flush()
        add_rental(active.id, date(2026, 5, 1), 100)
        add_rental(sold.id, date(2026, 5, 2), 200)
        db.session.commit()

        response = client.get("/api/rental-stats/x200u-forecast")

    assert response.status_code == 200
    payload = response.get_json()
    active_dep = calculate_period_depreciation(
        7000, date(2026, 5, 1), date(2026, 5, 1), date(2026, 6, 30)
    )
    sold_dep = calculate_period_depreciation(
        7000,
        date(2026, 5, 2),
        date(2026, 5, 2),
        date(2026, 6, 30),
        date(2026, 6, 1),
    )
    expected_history = 300 - 2 * 15 - active_dep - sold_dep

    assert payload["device_count"] == 1
    assert payload["total_cost"] == 14000
    assert payload["hist_net_profit"] == pytest.approx(expected_history, abs=0.01)
    for scenario in payload["scenarios"].values():
        assert all(month["device_count"] == 1 for month in scenario["months"])


def test_device_api_rejects_removed_online_offline_status(app, client):
    with app.app_context():
        device = Device(
            name="lifecycle-only",
            serial_number="LIFECYCLE-ONLY",
            model="test",
            is_accessory=False,
            lifecycle_status="active",
        )
        db.session.add(device)
        db.session.commit()
        device_id = device.id

    update_response = client.put(
        f"/api/devices/{device_id}",
        json={"status": "offline"},
    )
    filter_response = client.get("/api/devices?status=offline")

    assert update_response.status_code == 400
    assert "lifecycle_status" in update_response.get_json()["error"]
    assert filter_response.status_code == 400
    assert "lifecycle_status" in filter_response.get_json()["message"]
