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
    gantt = client.get('/api/gantt/data', query_string={
        'start_date': payload['start_date'], 'end_date': payload['end_date'],
        'warehouse_id': payload['warehouse_id'],
    })
    assert gantt.status_code == 200
    assert all(r['booking']['recorded_quantity'] == 2 for r in gantt.json['data']['rentals'])
    assert len(gantt.json['data']['rentals']) == 2
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
    assert response.status_code == 409, response.json
    assert Rental.query.count() == 1
    assert RentalBooking.query.count() == 0


@pytest.mark.parametrize('case_name', ['same_device', 'different_model', 'invalid_combo', 'repeat_accessory'])
def test_invalid_second_selection_rolls_back(case, case_name):
    client, payload, devices = case
    if case_name == 'same_device':
        payload['additional_devices'][0]['device_id'] = payload['device_id']
    elif case_name == 'different_model':
        devices[1].model_id = None
        devices[1].model = 'x200u'
        payload['additional_devices'][0]['lens_combo'] = 'bare'
        db.session.commit()
    elif case_name == 'invalid_combo':
        payload['additional_devices'][0]['lens_combo'] = 'invalid'
    else:
        devices[2].is_accessory = True
        devices[2].name = '三脚架'
        db.session.commit()
        payload['accessories'] = [devices[2].id]
        payload['additional_devices'][0]['accessories'] = [devices[2].id]
    response = client.post('/api/rentals', json=payload)
    assert response.status_code == 400, response.json
    assert Rental.query.count() == RentalBooking.query.count() == RentalBookingRequest.query.count() == 0


def test_append_existing_order_preserves_shared_fields_and_splits_amount(case):
    client, payload, devices = case
    first = dict(payload, additional_devices=[])
    response = client.post('/api/rentals', json=first)
    rid = response.json['data']['main_rental']['id']
    append = dict(payload, additional_devices=[], device_id=devices[1].id,
                  booking_request_id=str(uuid.uuid4()), append_to_rental_id=rid,
                  customer_name='must not overwrite', order_amount='999', lens_combo='lens_200mm')
    response = client.post('/api/rentals', json=append)
    assert response.status_code == 201, response.json
    rows = Rental.query.order_by(Rental.id).all()
    assert len(rows) == 2
    assert rows[1].customer_name == rows[0].customer_name == '双机客户'
    assert float(sum(r.order_amount for r in rows)) == 101.01
    assert rows[1].booking_id == rows[0].booking_id
    assert client.post('/api/rentals', json=append).status_code == 201
    third = dict(append, booking_request_id=str(uuid.uuid4()), device_id=devices[2].id)
    assert client.post('/api/rentals', json=third).status_code == 400
    assert Rental.query.count() == 2


def test_cancel_restore_reminder_and_explicit_reduction(case):
    from app.models.xianyu_shop import XianyuShop
    from app.services.xianyu_order_reconciliation_service import XianyuOrderReconciliationService
    client, payload, _ = case
    shop = XianyuShop(name='双机测试店', app_key='', app_secret_ciphertext='', is_active=True)
    db.session.add(shop)
    db.session.commit()
    payload.update(xianyu_shop_id=shop.id, xianyu_order_no='TWO-ORDER')
    created = client.post('/api/rentals', json=payload)
    assert created.status_code == 201, created.json
    rows = created.json['data']['main_rentals']
    assert XianyuOrderReconciliationService().get_snapshot()['count'] == 0
    assert client.put(f"/api/rentals/{rows[1]['id']}/status", json={'status': 'cancelled'}).status_code == 200
    alerts = XianyuOrderReconciliationService().get_snapshot()['alerts']
    assert len(alerts) == 1
    assert alerts[0]['recorded_quantity'] == 1
    reduced = client.post(f"/api/rentals/{rows[0]['id']}/reduce-booking", json={
        'warehouse_id': payload['warehouse_id'], 'reason': '客户确认只租一台', 'total_amount': '70.00',
    })
    assert reduced.status_code == 200, reduced.json
    assert XianyuOrderReconciliationService().get_snapshot()['count'] == 0
    assert float(db.session.get(Rental, rows[0]['id']).order_amount) == 70


def test_replenish_cancelled_device_does_not_double_amount(case):
    client, payload, devices = case
    response = client.post('/api/rentals', json=payload)
    rows = response.json['data']['main_rentals']
    client.put(f"/api/rentals/{rows[1]['id']}/status", json={'status': 'cancelled'})
    append = dict(payload, device_id=devices[2].id, additional_devices=[],
                  booking_request_id=str(uuid.uuid4()), append_to_rental_id=rows[0]['id'])
    response = client.post('/api/rentals', json=append)
    assert response.status_code == 201, response.json
    active = Rental.query.filter(Rental.status != 'cancelled').all()
    assert len(active) == 2
    assert float(sum(r.order_amount for r in active)) == 101.01


def test_changed_payload_cannot_reuse_receipt(case):
    client, payload, _ = case
    assert client.post('/api/rentals', json=payload).status_code == 201
    payload['order_amount'] = '120'
    assert client.post('/api/rentals', json=payload).status_code == 400
    assert Rental.query.count() == 2


def test_same_waybill_notification_is_sent_once(case, monkeypatch):
    from app.services.xianyu_order_service import XianyuOrderService
    client, payload, _ = case
    assert client.post('/api/rentals', json=payload).status_code == 201
    rows = Rental.query.order_by(Rental.id).all()
    for row in rows:
        row.xianyu_order_no = 'SHIP-TWO'
        row.ship_out_tracking_no = 'SF-TWO'
    db.session.commit()
    service = XianyuOrderService.__new__(XianyuOrderService)
    calls = []
    monkeypatch.setattr(service, '_request_with_body_sign', lambda *args: calls.append(args) or {'code': 0})
    assert service.ship_order(rows[0])['success']
    db.session.commit()
    assert service.ship_order(rows[1])['success']
    assert len(calls) == 1
    rows[1].ship_out_tracking_no = 'SF-OTHER'
    assert not service.ship_order(rows[1])['success']
    assert len(calls) == 1


def test_multi_booking_migration_preserves_old_rows_and_downgrades():
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    engine = sa.create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE xianyu_shops (id INTEGER PRIMARY KEY)')
        connection.exec_driver_sql('CREATE TABLE rentals (id INTEGER PRIMARY KEY, customer_name VARCHAR(100))')
        connection.exec_driver_sql("INSERT INTO rentals VALUES (1, 'existing')")
        path = Path(__file__).resolve().parents[2] / 'migrations/versions/20260914_multi_device_booking.py'
        spec = importlib.util.spec_from_file_location('booking_migration', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            assert 'booking_id' in {c['name'] for c in sa.inspect(connection).get_columns('rentals')}
            assert connection.exec_driver_sql('SELECT customer_name, booking_id FROM rentals').one() == ('existing', None)
            module.downgrade()
            assert 'rental_bookings' not in sa.inspect(connection).get_table_names()
            assert connection.exec_driver_sql('SELECT customer_name FROM rentals').scalar_one() == 'existing'


def test_declaring_existing_order_keeps_reminder_before_second_save(case):
    from app.models.xianyu_shop import XianyuShop
    from app.services.xianyu_order_reconciliation_service import XianyuOrderReconciliationService
    client, payload, _ = case
    shop = XianyuShop(name='声明测试店', app_key='', app_secret_ciphertext='', is_active=True)
    db.session.add(shop)
    db.session.commit()
    payload.update(xianyu_shop_id=shop.id, xianyu_order_no='DECLARE-TWO', additional_devices=[])
    response = client.post('/api/rentals', json=payload)
    rid = response.json['data']['main_rental']['id']
    response = client.post(f'/api/rentals/{rid}/declare-booking', json={'warehouse_id': payload['warehouse_id']})
    assert response.status_code == 200, response.json
    assert response.json['data']['recorded_quantity'] == 1
    assert XianyuOrderReconciliationService().get_snapshot()['count'] == 1
    assert float(db.session.get(Rental, rid).order_amount) == 101.01


def test_all_cancelled_order_can_be_rebooked(case):
    from app.models.xianyu_shop import XianyuShop
    client, payload, _ = case
    shop = XianyuShop(name='重录测试店', app_key='', app_secret_ciphertext='', is_active=True)
    db.session.add(shop)
    db.session.commit()
    payload.update(xianyu_shop_id=shop.id, xianyu_order_no='REBOOK-TWO')
    created = client.post('/api/rentals', json=payload)
    for row in created.json['data']['main_rentals']:
        client.put(f"/api/rentals/{row['id']}/status", json={'status': 'cancelled'})
    payload['booking_request_id'] = str(uuid.uuid4())
    response = client.post('/api/rentals', json=payload)
    assert response.status_code == 201, response.json
    assert response.json['data']['main_rental']['booking']['recorded_quantity'] == 2
    assert RentalBooking.query.count() == 1


@pytest.mark.parametrize('amount', ['0', '0.01'])
def test_zero_or_one_cent_amount_is_not_lost(case, amount):
    client, payload, _ = case
    payload['order_amount'] = amount
    response = client.post('/api/rentals', json=payload)
    assert response.status_code == 201, response.json
    assert sum(row['order_amount'] for row in response.json['data']['main_rentals']) == float(amount)


def test_two_custom_packages_keep_independent_snapshots(case):
    client, payload, devices = case
    model = devices[0].device_model
    model.set_rental_packages_list([
        {'id': 'body-only', 'name': '裸机套餐', 'is_active': True, 'items': []},
        {'id': 'long-lens', 'name': '400mm 套餐', 'is_active': True, 'items': [{'name': '400mm 镜头', 'qty': 1}]},
    ])
    model.default_rental_package_id = 'body-only'
    db.session.commit()
    payload.pop('lens_combo')
    payload['rental_package_id'] = 'body-only'
    payload['additional_devices'][0].pop('lens_combo')
    payload['additional_devices'][0]['rental_package_id'] = 'long-lens'
    response = client.post('/api/rentals', json=payload)
    assert response.status_code == 201, response.json
    rows = response.json['data']['main_rentals']
    assert [r['rental_package_name'] for r in rows] == ['裸机套餐', '400mm 套餐']
    assert rows[0]['rental_package_items'] == []
    assert rows[1]['rental_package_items'] == [{'name': '400mm 镜头', 'qty': 1}]
    assert [r['rental_package_name'] for r in rows[0]['booking']['rentals']] == ['裸机套餐', '400mm 套餐']


def test_edit_booking_machine_start_and_shipping_dates(case):
    from datetime import datetime
    client, payload, _ = case
    rows = client.post('/api/rentals', json=payload).json['data']['main_rentals']
    first, second = [db.session.get(Rental, r['id']) for r in rows]
    other_start = second.start_date
    new_start = first.start_date - timedelta(days=1)
    new_ship = datetime.combine(new_start - timedelta(days=2), datetime.min.time())
    response = client.put(f'/web/rentals/{first.id}', json={
        'warehouse_id': first.warehouse_id, 'start_date': new_start.isoformat(),
        'ship_out_time': new_ship.isoformat(),
    })
    assert response.status_code == 200, response.json
    db.session.refresh(first)
    db.session.refresh(second)
    assert first.start_date == new_start and first.ship_out_time == new_ship
    assert second.start_date == other_start
    invalid = client.put(f'/web/rentals/{first.id}', json={
        'warehouse_id': first.warehouse_id, 'start_date': (first.end_date + timedelta(days=1)).isoformat(),
    })
    assert invalid.status_code == 400
    db.session.refresh(first)
    assert first.start_date == new_start
