import os
from datetime import date, datetime, time, timedelta

import pytest

from app import create_app, db
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental
from app.services.relay.relay_case_service import RelayCaseService
from app.services.shipping.sf_tracking_service import SFTrackingService
from tests.support.test_database import (
    assert_current_user_has_test_only_grants,
    build_mysql_test_config,
)


@pytest.fixture
def app():
    if not os.environ.get("TEST_DATABASE_URL"):
        return create_app("testing")
    app = create_app(build_mysql_test_config())
    with app.app_context():
        with db.engine.connect() as connection:
            assert_current_user_has_test_only_grants(
                connection, db.engine.url.database
            )
    return app


@pytest.fixture
def db_session(app):
    with app.app_context():
        db.create_all()
        yield db.session
        db.session.rollback()
        db.drop_all()


def seed_shipped_case(db_session, phone="13800138000"):
    model = DeviceModel(
        name="relay-tracking",
        display_name="接力物流测试",
        is_active=True,
    )
    db_session.add(model)
    db_session.flush()
    device = Device(
        name="RTK-01",
        model=model.name,
        model_id=model.id,
        is_accessory=False,
        lifecycle_status="active",
    )
    db_session.add(device)
    db_session.flush()
    first = Rental(
        device_id=device.id,
        start_date=date(2026, 8, 2),
        end_date=date(2026, 8, 5),
        ship_out_time=datetime(2026, 8, 1, 19),
        ship_in_time=datetime(2026, 8, 9, 12),
        customer_name="前单",
        customer_phone=phone,
        destination="杭州",
        status="not_shipped",
    )
    second = Rental(
        device_id=device.id,
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 14),
        ship_out_time=datetime(2026, 8, 7, 19),
        ship_in_time=datetime(2026, 8, 16, 12),
        customer_name="后单",
        status="not_shipped",
    )
    db_session.add_all([first, second])
    db_session.commit()
    relay_case = RelayCaseService.update_case(
        first.id,
        second.id,
        "shipped",
        sf_tracking_number="SF1234567890",
    )
    return relay_case


def test_refresh_uses_predecessor_phone_and_does_not_complete(
    app, db_session, monkeypatch
):
    relay_case = seed_shipped_case(db_session)
    captured = {}

    def query(_cls, number, phone_last4):
        captured.update(number=number, phone_last4=phone_last4)
        return {
            "tracking_number": number,
            "status": "delivered",
            "status_text": "已签收",
            "routes": [],
            "last_update": "2026-08-05 10:32:00",
            "delivered_time": "2026-08-05 10:32:00",
        }

    monkeypatch.setattr(
        SFTrackingService, "query", classmethod(query)
    )

    result = RelayCaseService.refresh_tracking(
        relay_case.id, now=datetime(2026, 8, 5, 10, 33)
    )

    assert captured == {
        "number": "SF1234567890",
        "phone_last4": "8000",
    }
    assert relay_case.status == "shipped"
    assert relay_case.sf_tracking_status == "delivered"
    assert relay_case.sf_tracking_summary == "已签收 · 2026-08-05 10:32:00"
    assert result["status"] == "delivered"


def test_refresh_without_phone_keeps_shipped_and_caches_reason(
    app, db_session, monkeypatch
):
    relay_case = seed_shipped_case(db_session, phone=None)
    called = []

    def query(_cls, *_args):
        called.append(True)

    monkeypatch.setattr(SFTrackingService, "query", classmethod(query))

    result = RelayCaseService.refresh_tracking(relay_case.id)

    assert called == []
    assert relay_case.status == "shipped"
    assert relay_case.sf_tracking_status == "query_failed"
    assert "缺少前单客户手机号" in relay_case.sf_tracking_summary
    assert result["status"] == "query_failed"


def test_refresh_api_failure_keeps_shipped_and_caches_retry_reason(
    app, db_session, monkeypatch
):
    relay_case = seed_shipped_case(db_session)

    def fail(_cls, _number, _phone):
        raise RuntimeError("顺丰暂时不可用")

    monkeypatch.setattr(SFTrackingService, "query", classmethod(fail))

    result = RelayCaseService.refresh_tracking(relay_case.id)

    assert relay_case.status == "shipped"
    assert relay_case.sf_tracking_status == "query_failed"
    assert relay_case.sf_tracking_summary == "顺丰暂时不可用"
    assert result["status"] == "query_failed"


def test_refresh_rejects_unknown_or_unshipped_case(app, db_session):
    with pytest.raises(ValueError, match="接力记录不存在"):
        RelayCaseService.refresh_tracking(999)

    relay_case = seed_shipped_case(db_session)
    relay_case.status = "agreed"
    db_session.commit()

    with pytest.raises(ValueError, match="尚未寄出"):
        RelayCaseService.refresh_tracking(relay_case.id)
