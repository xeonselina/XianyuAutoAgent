"""Rental damage-note API integration tests."""

from datetime import date, timedelta

import pytest

from app import create_app, db
from app.models.device import Device
from app.models.rental import Rental


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
        yield db.session
        db.session.rollback()
        db.drop_all()


@pytest.fixture
def rental(db_session):
    device = Device(name="损坏备注测试机", is_accessory=False)
    db_session.add(device)
    db_session.flush()

    record = Rental(
        device_id=device.id,
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

