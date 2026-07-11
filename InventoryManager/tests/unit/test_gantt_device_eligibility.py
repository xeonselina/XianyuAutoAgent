from datetime import date, timedelta

import pytest

from app import create_app, db
from app.models.device import Device
from app.models.device_model import DeviceModel
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
    with pytest.raises(RuntimeError, match="数据库名必须包含 test"):
        assert_test_database_url(
            "mysql+pymysql://inventory_test:secret@192.168.50.132/inventory_db"
        )


def test_accepts_test_database_on_192_instance(monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    url = assert_test_database_url(
        "mysql+pymysql://inventory_test:secret@192.168.50.132/inventory_reorder_test"
    )
    assert url.database == "inventory_reorder_test"


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
                status="online",
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


def test_find_slot_excludes_offline_active_device(app, db_session):
    with app.app_context():
        model = DeviceModel(
            name="eligibility-offline",
            display_name="资格测试-离线",
            is_active=True,
        )
        db_session.add(model)
        db_session.flush()
        db_session.add(
            Device(
                name="离线设备",
                model=model.name,
                model_id=model.id,
                is_accessory=False,
                status="offline",
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

        assert result is None
