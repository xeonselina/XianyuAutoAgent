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
    build_mysql_test_config,
    clear_guarded_mysql_test_rows,
    guarded_mysql_test_metadata,
)


@pytest.fixture(scope="module")
def app():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.fail("TEST_DATABASE_URL is required for database tests")
    application = create_app(build_mysql_test_config())
    with application.app_context():
        with guarded_mysql_test_metadata(db.engine, db.metadata):
            yield application
        db.session.remove()


@pytest.fixture
def db_session(app):
    with app.app_context():
        clear_guarded_mysql_test_rows(db.engine, db.metadata)
        try:
            yield db.session
        finally:
            db.session.rollback()
            db.session.remove()


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
        logistics_days=1,
        planned_ship_out_date=date(2026, 7, 31),
        planned_return_date=date(2026, 8, 7),
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
        logistics_days=4,
        planned_ship_out_date=date(2026, 8, 5),
        planned_return_date=date(2026, 8, 19),
        ship_out_time=datetime(2026, 8, 7, 19),
        ship_in_time=datetime(2026, 8, 16, 12),
        customer_name="后单",
        status="not_shipped",
    )
    db_session.add_all([first, second])
    db_session.commit()
    outcome = RelayCaseService.update_case(
        first.id,
        second.id,
        "shipped",
        sf_tracking_number="SF1234567890",
    )
    return outcome.relay_case


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
            "routes": [{
                "accept_time": "2026-08-05 10:32:00",
                "accept_address": "杭州市",
                "remark": "快件已由客户本人签收",
                "op_code": "80",
                "first_status_code": "4",
                "first_status_name": "已签收",
                "secondary_status_code": "",
                "secondary_status_name": "",
            }],
            "latest_route": {
                "accept_time": "2026-08-05 10:32:00",
                "accept_address": "杭州市",
                "remark": "快件已由客户本人签收",
            },
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
    assert relay_case.sf_tracking_summary == (
        "已签收 · 快件已由客户本人签收 · 杭州市 · "
        "2026-08-05 10:32:00"
    )
    assert result["status"] == "delivered"
    assert result["status_text"] == "已签收"
    assert result["routes"][0]["remark"] == "快件已由客户本人签收"


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
