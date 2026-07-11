from datetime import date, datetime, time, timedelta

import pytest

from app import create_app, db
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding
from app.services.gantt.reorder_service import GanttReorderService


@pytest.fixture
def app():
    return create_app("testing")


@pytest.fixture
def db_session(app):
    with app.app_context():
        db.create_all()
        yield db.session
        db.session.rollback()
        db.drop_all()


def make_rental(device_id, customer, ship_out_day, ship_in_day, parent_id=None):
    return Rental(
        device_id=device_id,
        start_date=ship_out_day + timedelta(days=1),
        end_date=ship_in_day - timedelta(days=1),
        ship_out_time=datetime.combine(ship_out_day, time(19)),
        ship_in_time=datetime.combine(ship_in_day, time(12)),
        customer_name=customer,
        customer_phone="13800138000",
        destination="测试地址",
        status="not_shipped",
        parent_rental_id=parent_id,
    )


def seed_device(db_session):
    model = DeviceModel(name="relay", display_name="接力测试", is_active=True)
    db_session.add(model)
    db_session.flush()
    device = Device(
        name="R-01",
        model=model.name,
        model_id=model.id,
        is_accessory=False,
        status="online",
        lifecycle_status="active",
    )
    db_session.add(device)
    db_session.flush()
    return model, device


def test_analyze_requires_confirmation_for_multi_day_overlap(app, db_session):
    with app.app_context():
        _, device = seed_device(db_session)
        first = make_rental(
            device.id, "客户1", date.today() + timedelta(days=2),
            date.today() + timedelta(days=8)
        )
        second = make_rental(
            device.id, "客户2", date.today() + timedelta(days=7),
            date.today() + timedelta(days=13)
        )
        db_session.add_all([first, second])
        db_session.commit()

        result = GanttReorderService.analyze(today=date.today())

        overlap = result["overlaps"][0]
        assert overlap["status"] == "needs_confirmation"
        assert overlap["overlap_days"] == 1
        assert overlap["predecessor"]["customer_name"] == "客户1"
        assert overlap["successor"]["customer_phone"] == "13800138000"
        assert overlap["successor"]["destination"] == "测试地址"


def test_analyze_marks_persisted_binding_as_bound(app, db_session):
    with app.app_context():
        _, device = seed_device(db_session)
        first = make_rental(
            device.id, "客户1", date.today() + timedelta(days=2),
            date.today() + timedelta(days=8)
        )
        second = make_rental(
            device.id, "客户2", date.today() + timedelta(days=7),
            date.today() + timedelta(days=13)
        )
        db_session.add_all([first, second])
        db_session.flush()
        db_session.add(RentalRelayBinding(
            predecessor_rental_id=first.id,
            successor_rental_id=second.id,
        ))
        db_session.commit()

        overlap = GanttReorderService.analyze()["overlaps"][0]

        assert overlap["status"] == "bound"
        assert overlap["binding_id"] is not None


def test_binding_rejects_child_rental(app, db_session):
    with app.app_context():
        _, device = seed_device(db_session)
        parent = make_rental(
            device.id, "父", date.today() + timedelta(days=2),
            date.today() + timedelta(days=6)
        )
        db_session.add(parent)
        db_session.flush()
        child = make_rental(
            device.id, "子", date.today() + timedelta(days=5),
            date.today() + timedelta(days=9), parent.id
        )

        with pytest.raises(ValueError, match="只允许主 rental"):
            RentalRelayBinding.validate_pair(parent, child)
