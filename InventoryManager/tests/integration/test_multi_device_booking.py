"""Atomic two-camera booking smoke tests (isolated SQLite)."""
import uuid
from datetime import date, timedelta

import pytest

from app import create_app, db
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental, RentalBooking, RentalBookingRequest
from app.models.warehouse import Warehouse


@pytest.fixture
def case():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        wh = Warehouse(name='双机测试仓', province='广东省', city='深圳市')
        model = DeviceModel(name='x300u', display_name='X300 Ultra', is_active=True)
        db.session.add_all([wh, model])
        db.session.flush()
        devices = [Device(name=f'双机{i}', model='x300u', model_id=model.id, warehouse_id=wh.id) for i in range(3)]
        db.session.add_all(devices)
        db.session.commit()
        payload = {
            'device_id': devices[0].id, 'warehouse_id': wh.id,
            'customer_name': '双机客户', 'start_date': (date.today() + timedelta(days=10)).isoformat(),
            'end_date': (date.today() + timedelta(days=13)).isoformat(),
            'order_amount': '101.01', 'lens_combo': 'bare',
            'booking_request_id': str(uuid.uuid4()),
            'additional_devices': [{'device_id': devices[1].id, 'lens_combo': 'lens_400mm', 'accessories': []}],
        }
        yield app.test_client(), payload, devices
        db.session.remove()
        db.drop_all()


def test_two_configurations_atomic_and_retry(case):
    client, payload, _ = case
    response = client.post('/api/rentals', json=payload)
    assert response.status_code == 201, response.json
    rows = response.json['data']['main_rentals']
    assert [r['lens_combo'] for r in rows] == ['bare', 'lens_400mm']
    assert round(sum(r['order_amount'] for r in rows), 2) == 101.01
    assert rows[0]['booking']['recorded_quantity'] == 2
    assert all(r['parent_rental_id'] is None for r in rows)
    retry = client.post('/api/rentals', json=payload)
    assert retry.status_code == 201, retry.json
    assert [r['id'] for r in retry.json['data']['main_rentals']] == [r['id'] for r in rows]
    assert Rental.query.count() == 2
    assert RentalBookingRequest.query.count() == 1


def test_second_conflict_leaves_no_first_rental(case):
    client, payload, _ = case
    single = dict(payload, device_id=payload['additional_devices'][0]['device_id'], additional_devices=[], booking_request_id=str(uuid.uuid4()))
    assert client.post('/api/rentals', json=single).status_code == 201
    response = client.post('/api/rentals', json=payload)
    assert response.status_code == 400, response.json
    assert Rental.query.count() == 1
    assert RentalBooking.query.count() == 0
