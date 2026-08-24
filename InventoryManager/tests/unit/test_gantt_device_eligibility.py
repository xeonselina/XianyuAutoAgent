from datetime import date, timedelta

import pytest

from app import create_app, db
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental
from app.services.gantt.gantt_service import GanttService
from tests.support.test_database import assert_test_database_url


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


def test_rejects_production_database_name(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("ALLOW_REAL_TEST_DATABASE", "true")
    with pytest.raises(RuntimeError, match="inventory_management_test"):
        assert_test_database_url(
            "mysql+pymysql://inventory_test:secret@192.168.50.132/inventory_db"
        )


def test_accepts_test_database_on_192_instance(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("ALLOW_REAL_TEST_DATABASE", "true")
    url = assert_test_database_url(
        "mysql+pymysql://inventory_test:secret@192.168.50.132/"
        "inventory_management_test"
    )
    assert url.database == "inventory_management_test"


@pytest.mark.parametrize(
    "lifecycle_status",
    ["sold", "damaged", "decommissioned", "retired"],
)
def test_find_slot_excludes_online_non_active_device(
    app, db_session, lifecycle_status
):
    with app.app_context():
        model = DeviceModel(
            name=f"eligibility-{lifecycle_status}",
            display_name=f"资格测试-{lifecycle_status}",
            is_active=True,
        )
        db_session.add(model)
        db_session.flush()
        db_session.add(
            Device(
                name=f"设备-{lifecycle_status}",
                model=model.name,
                model_id=model.id,
                is_accessory=False,
                lifecycle_status=lifecycle_status,
            )
        )
        db_session.commit()

        result = GanttService.find_available_slot(
            date.today() + timedelta(days=5),
            date.today() + timedelta(days=8),
            1,
            model.id,
            False,
        )

        assert result is None


def test_find_slot_includes_active_device(app, db_session):
    with app.app_context():
        model = DeviceModel(
            name="eligibility-active",
            display_name="资格测试-活动",
            is_active=True,
        )
        db_session.add(model)
        db_session.flush()
        db_session.add(
            Device(
                name="活动设备",
                model=model.name,
                model_id=model.id,
                is_accessory=False,
                lifecycle_status="active",
            )
        )
        db_session.commit()

        result = GanttService.find_available_slot(
            date.today() + timedelta(days=5),
            date.today() + timedelta(days=8),
            1,
            model.id,
            False,
        )

        assert result is not None
        assert result["total_available"] == 1


def test_find_slot_uses_usage_period_as_hard_conflict_and_logistics_as_warning(
    app, db_session
):
    with app.app_context():
        model = DeviceModel(
            name="shared-overlap-policy",
            display_name="统一档期规则",
            is_active=True,
        )
        db_session.add(model)
        db_session.flush()
        device = Device(
            name="统一规则设备",
            model=model.name,
            model_id=model.id,
            is_accessory=False,
            lifecycle_status="active",
        )
        db_session.add(device)
        db_session.flush()
        predecessor = Rental(
            device_id=device.id,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 2),
            logistics_days=1,
            planned_ship_out_date=date(2026, 8, 30),
            planned_return_date=date(2026, 9, 4),
            customer_name="前单",
            status="not_shipped",
        )
        db_session.add(predecessor)
        db_session.commit()

        soft_overlap = GanttService.find_available_slot(
            date(2026, 9, 3),
            date(2026, 9, 3),
            0,
            model.id,
            False,
        )

        assert soft_overlap is not None
        assert soft_overlap["total_available"] == 1
        assert soft_overlap["warnings"] == [{
            "code": "LOGISTICS_OVERLAP_RELAY_WARNING",
            "device_id": device.id,
            "predecessor_rental_id": predecessor.id,
            "successor_rental_id": None,
            "overlap_days": 2,
            "blocking": False,
            "relay_candidate": True,
        }]

        hard_overlap = GanttService.find_available_slot(
            date(2026, 9, 2),
            date(2026, 9, 3),
            0,
            model.id,
            False,
        )

        assert hard_overlap is None
