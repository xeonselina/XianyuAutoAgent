"""Rental damage-note API integration tests."""

from datetime import date, timedelta

import pytest

from app import create_app, db
from app.models.device import Device
from app.models.rental import Rental
from app.models.warehouse import Warehouse


@pytest.fixture
def app():
    application = create_app("testing")
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    with app.app_context():
        db.create_all()
        db.session.add(Warehouse(
            province="待配置", city="待配置", name="默认仓库"
        ))
        db.session.commit()
        yield db.session
        db.session.rollback()
        db.drop_all()


@pytest.fixture
def rental(db_session):
    warehouse_id = db_session.query(Warehouse.id).scalar()
    device = Device(
        name="损坏备注测试机",
        is_accessory=False,
        warehouse_id=warehouse_id,
    )
    db_session.add(device)
    db_session.flush()

    record = Rental(
        device_id=device.id,
        warehouse_id=warehouse_id,
        start_date=date.today() - timedelta(days=3),
        end_date=date.today() - timedelta(days=1),
        customer_name="测试客户",
        status="returned",
    )
    db_session.add(record)
    db_session.commit()
    return record


def test_damage_note_is_serialized_and_trimmed_on_update(client, rental):
    initial = client.get(f"/api/rentals/{rental.id}")

    assert initial.status_code == 200
    assert initial.get_json()["data"]["damage_note"] is None

    response = client.put(
        f"/web/rentals/{rental.id}",
        json={"damage_note": "  屏幕右下角碎裂  "},
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["damage_note"] == "屏幕右下角碎裂"
    assert db.session.get(Rental, rental.id).damage_note == "屏幕右下角碎裂"


def test_blank_damage_note_clears_existing_value(client, rental):
    rental.damage_note = "镜头卡口松动"
    db.session.commit()

    response = client.put(
        f"/web/rentals/{rental.id}",
        json={"damage_note": "   "},
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["damage_note"] is None
    assert db.session.get(Rental, rental.id).damage_note is None


@pytest.mark.parametrize("invalid_note", [123, ["屏幕碎裂"], {"note": "屏幕碎裂"}])
def test_non_string_damage_note_is_rejected_without_changing_value(
    client,
    rental,
    invalid_note,
):
    rental.damage_note = "原备注"
    db.session.commit()

    response = client.put(
        f"/web/rentals/{rental.id}",
        json={"damage_note": invalid_note},
    )

    assert response.status_code == 400
    assert db.session.get(Rental, rental.id).damage_note == "原备注"


def test_overlong_damage_note_is_rejected_without_changing_value(client, rental):
    rental.damage_note = "原备注"
    db.session.commit()

    response = client.put(
        f"/web/rentals/{rental.id}",
        json={"damage_note": "坏" * 1001},
    )

    assert response.status_code == 400
    assert db.session.get(Rental, rental.id).damage_note == "原备注"


def test_damage_check_item_is_unchecked_and_keeps_report_snapshot(client, rental):
    rental.damage_note = "屏幕右下角碎裂"
    db.session.commit()

    lookup = client.get(f"/api/inspections/rental/latest/{rental.device_id}")

    assert lookup.status_code == 200
    checklist = lookup.get_json()["data"]["checklist"]
    assert checklist[-1] == {
        "name": "处理用户反馈：屏幕右下角碎裂",
        "order": len(checklist),
        "default_checked": False,
    }

    create_response = client.post(
        "/api/inspections",
        json={
            "rental_id": rental.id,
            "device_id": rental.device_id,
            "check_items": [
                {
                    "name": item["name"],
                    "order": item["order"],
                    "is_checked": item.get("default_checked", True),
                }
                for item in checklist
            ],
        },
    )

    assert create_response.status_code == 201
    inspection = create_response.get_json()["data"]
    assert inspection["status"] == "abnormal"
    assert inspection["check_items"][-1]["item_name"] == "处理用户反馈：屏幕右下角碎裂"
    assert inspection["check_items"][-1]["is_checked"] is False

    clear_response = client.put(
        f"/web/rentals/{rental.id}",
        json={"damage_note": None},
    )
    assert clear_response.status_code == 200

    saved_response = client.get(f"/api/inspections/{inspection['id']}")
    saved_item = saved_response.get_json()["data"]["check_items"][-1]
    assert saved_item["item_name"] == "处理用户反馈：屏幕右下角碎裂"
    assert saved_item["is_checked"] is False
