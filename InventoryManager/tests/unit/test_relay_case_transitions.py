import os
from datetime import date, datetime, time, timedelta

import pytest

from app import create_app, db
from app.models.audit_log import AuditLog
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding
from app.models.rental_relay_case import RentalRelayCase
from app.services.relay.relay_case_service import (
    RelayBindingConflictError,
    RelayCaseService,
)
from app.services import xianyu_order_service
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


def seed_pair(db_session, overlap_days=2):
    model = DeviceModel(
        name="relay-transition",
        display_name="接力流转测试",
        is_active=True,
    )
    db_session.add(model)
    db_session.flush()
    device = Device(
        name="RT-01",
        model=model.name,
        model_id=model.id,
        is_accessory=False,
        lifecycle_status="active",
    )
    db_session.add(device)
    db_session.flush()
    first_ship_out = date(2026, 8, 1)
    first_ship_in = date(2026, 8, 9)
    second_ship_out = first_ship_in - timedelta(days=overlap_days)
    logistics_days = 1
    buffer = timedelta(days=logistics_days + 1)
    first_start = date(2026, 8, 2)
    first_end = date(2026, 8, 5)
    first_planned_return = first_end + buffer
    second_start = first_planned_return + buffer - timedelta(days=overlap_days)
    second_end = second_start + timedelta(days=4)
    first = Rental(
        device_id=device.id,
        start_date=first_start,
        end_date=first_end,
        logistics_days=logistics_days,
        planned_ship_out_date=first_start - buffer,
        planned_return_date=first_planned_return,
        ship_out_time=datetime.combine(first_ship_out, time(19)),
        ship_in_time=datetime.combine(first_ship_in, time(12)),
        customer_name="前单",
        customer_phone="13800138000",
        destination="杭州",
        status="not_shipped",
    )
    second = Rental(
        device_id=device.id,
        start_date=second_start,
        end_date=second_end,
        logistics_days=logistics_days,
        planned_ship_out_date=second_start - buffer,
        planned_return_date=second_end + buffer,
        ship_out_time=datetime.combine(second_ship_out, time(19)),
        ship_in_time=datetime.combine(second_ship_out + timedelta(days=9), time(12)),
        customer_name="后单",
        customer_phone="13900139000",
        destination="上海",
        status="not_shipped",
    )
    db_session.add_all([first, second])
    db_session.commit()
    return first, second


def set_planned_overlap(predecessor, successor, overlap_days):
    buffer = timedelta(days=successor.logistics_days + 1)
    successor.start_date = (
        predecessor.planned_return_date + buffer - timedelta(days=overlap_days)
    )
    successor.end_date = successor.start_date + timedelta(days=4)
    successor.planned_ship_out_date = successor.start_date - buffer
    successor.planned_return_date = successor.end_date + buffer


def test_agreed_creates_binding_audit_and_reached_milestones(app, db_session):
    first, second = seed_pair(db_session)
    now = datetime(2026, 8, 5, 9, 30)

    outcome = RelayCaseService.update_case(
        first.id, second.id, "agreed", now=now
    )
    relay_case = outcome.relay_case

    binding = RentalRelayBinding.query.filter_by(
        predecessor_rental_id=first.id,
        successor_rental_id=second.id,
    ).one()
    assert relay_case.status == "agreed"
    assert binding.id is not None
    assert relay_case.notified_at == now
    assert relay_case.agreed_at == now
    assert relay_case.shipped_at is None
    audit = AuditLog.query.filter_by(
        action="relay_case_status_changed"
    ).one()
    assert audit.details["old_status"] == "pending"
    assert audit.details["new_status"] == "agreed"


def test_rollback_before_agreed_removes_binding_and_later_milestones(
    app, db_session
):
    first, second = seed_pair(db_session)
    RelayCaseService.update_case(
        first.id,
        second.id,
        "shipped",
        sf_tracking_number="SF1234567890",
        now=datetime(2026, 8, 5, 9),
    )

    outcome = RelayCaseService.update_case(
        first.id,
        second.id,
        "notified",
        now=datetime(2026, 8, 6, 10),
    )
    relay_case = outcome.relay_case

    assert RentalRelayBinding.query.count() == 0
    assert relay_case.status == "notified"
    assert relay_case.notified_at == datetime(2026, 8, 5, 9)
    assert relay_case.agreed_at is None
    assert relay_case.shipped_at is None
    assert relay_case.completed_at is None
    assert relay_case.sf_tracking_number == "SF1234567890"


def test_shipped_requires_tracking_number(app, db_session):
    first, second = seed_pair(db_session)

    with pytest.raises(ValueError, match="顺丰运单号"):
        RelayCaseService.update_case(first.id, second.id, "shipped")

    assert RentalRelayCase.query.count() == 0
    assert RentalRelayBinding.query.count() == 0


def test_first_shipped_syncs_successor_and_reports_xianyu_success(
    app, db_session, monkeypatch
):
    first, second = seed_pair(db_session)
    second.xianyu_order_no = "5126917575981011333"
    original_ship_out_time = second.ship_out_time
    db_session.commit()
    shipped_rentals = []

    class FakeXianyuService:
        def ship_order(self, rental):
            shipped_rentals.append(rental.id)
            return {"success": True, "message": "ok", "data": {}}

    monkeypatch.setattr(
        xianyu_order_service,
        "get_xianyu_service",
        lambda: FakeXianyuService(),
    )

    outcome = RelayCaseService.update_case(
        first.id,
        second.id,
        "shipped",
        sf_tracking_number="SF1234567890",
        now=datetime(2026, 8, 9, 13, 56),
    )

    db_session.refresh(second)
    assert second.ship_out_tracking_no == "SF1234567890"
    assert second.status == "shipped"
    assert second.ship_out_time == original_ship_out_time
    assert shipped_rentals == [second.id]
    assert outcome.xianyu_sync == {
        "attempted": True,
        "success": True,
        "message": "ok",
    }


def test_first_shipped_fills_missing_successor_ship_out_time(
    app, db_session, monkeypatch
):
    first, second = seed_pair(db_session)
    RelayCaseService.update_case(first.id, second.id, "agreed")
    second.ship_out_time = None
    db_session.commit()
    monkeypatch.setattr(
        xianyu_order_service,
        "get_xianyu_service",
        lambda: type(
            "FakeXianyuService",
            (),
            {"ship_order": lambda self, rental: {
                "success": True,
                "message": "ok",
            }},
        )(),
    )
    shipped_at = datetime(2026, 8, 9, 14, 5)

    RelayCaseService.update_case(
        first.id,
        second.id,
        "shipped",
        sf_tracking_number="SF2234567890",
        now=shipped_at,
    )

    db_session.refresh(second)
    assert second.ship_out_time == shipped_at


def test_xianyu_failure_keeps_successor_shipped(
    app, db_session, monkeypatch
):
    first, second = seed_pair(db_session)
    second.xianyu_order_no = "3315624386722187397"
    db_session.commit()
    monkeypatch.setattr(
        xianyu_order_service,
        "get_xianyu_service",
        lambda: type(
            "FakeXianyuService",
            (),
            {"ship_order": lambda self, rental: {
                "success": False,
                "message": "闲鱼接口繁忙",
                "code": 500,
            }},
        )(),
    )

    outcome = RelayCaseService.update_case(
        first.id,
        second.id,
        "shipped",
        sf_tracking_number="SF3234567890",
    )

    db_session.refresh(second)
    assert outcome.relay_case.status == "shipped"
    assert second.status == "shipped"
    assert second.ship_out_tracking_no == "SF3234567890"
    assert outcome.xianyu_sync == {
        "attempted": True,
        "success": False,
        "message": "闲鱼接口繁忙",
    }


def test_xianyu_exception_keeps_successor_shipped(
    app, db_session, monkeypatch, caplog
):
    first, second = seed_pair(db_session)

    class FailingXianyuService:
        def ship_order(self, rental):
            raise RuntimeError("闲鱼网络超时")

    monkeypatch.setattr(
        xianyu_order_service,
        "get_xianyu_service",
        lambda: FailingXianyuService(),
    )

    outcome = RelayCaseService.update_case(
        first.id,
        second.id,
        "shipped",
        sf_tracking_number="SF4234567890",
    )

    db_session.refresh(second)
    assert second.status == "shipped"
    assert outcome.xianyu_sync == {
        "attempted": True,
        "success": False,
        "message": "闲鱼网络超时",
    }
    assert "接力后一单同步闲鱼失败" in caplog.text


def test_repeated_shipped_does_not_report_xianyu_twice(
    app, db_session, monkeypatch
):
    first, second = seed_pair(db_session)
    shipped_rentals = []

    class FakeXianyuService:
        def ship_order(self, rental):
            shipped_rentals.append(rental.id)
            return {"success": True, "message": "ok"}

    fake_service = FakeXianyuService()
    monkeypatch.setattr(
        xianyu_order_service,
        "get_xianyu_service",
        lambda: fake_service,
    )

    first_outcome = RelayCaseService.update_case(
        first.id,
        second.id,
        "shipped",
        sf_tracking_number="SF5234567890",
    )
    repeated_outcome = RelayCaseService.update_case(
        first.id,
        second.id,
        "shipped",
        sf_tracking_number="SF5234567890",
    )

    assert first_outcome.xianyu_sync["attempted"] is True
    assert repeated_outcome.xianyu_sync == {
        "attempted": False,
        "success": False,
        "message": "",
    }
    assert shipped_rentals == [second.id]


def test_direct_completed_does_not_update_successor_or_report_xianyu(
    app, db_session, monkeypatch
):
    first, second = seed_pair(db_session)
    shipped_rentals = []

    class FakeXianyuService:
        def ship_order(self, rental):
            shipped_rentals.append(rental.id)
            return {"success": True, "message": "ok"}

    monkeypatch.setattr(
        xianyu_order_service,
        "get_xianyu_service",
        lambda: FakeXianyuService(),
    )

    outcome = RelayCaseService.update_case(
        first.id,
        second.id,
        "completed",
        sf_tracking_number="SF6234567890",
    )

    db_session.refresh(second)
    assert second.status == "not_shipped"
    assert second.ship_out_tracking_no is None
    assert outcome.xianyu_sync["attempted"] is False
    assert shipped_rentals == []


def test_schedule_changed_case_cannot_newly_agree(app, db_session):
    first, second = seed_pair(db_session)
    relay_case = RentalRelayCase(
        predecessor_rental_id=first.id,
        successor_rental_id=second.id,
        status="notified",
    )
    db_session.add(relay_case)
    set_planned_overlap(first, second, 1)
    db_session.commit()

    with pytest.raises(ValueError, match="档期已变化"):
        RelayCaseService.update_case(first.id, second.id, "agreed")

    db_session.refresh(relay_case)
    assert relay_case.status == "notified"
    assert RentalRelayBinding.query.count() == 0


def test_existing_agreed_case_can_ship_after_schedule_changes(app, db_session):
    first, second = seed_pair(db_session)
    relay_case = RelayCaseService.update_case(
        first.id, second.id, "agreed"
    ).relay_case
    set_planned_overlap(first, second, 1)
    db_session.commit()

    updated = RelayCaseService.update_case(
        first.id,
        second.id,
        "shipped",
        sf_tracking_number="SF9876543210",
    ).relay_case

    assert updated.id == relay_case.id
    assert updated.status == "shipped"
    assert RentalRelayBinding.query.count() == 1


def test_conflicting_binding_rejects_agreed_and_keeps_case_unchanged(
    app, db_session
):
    first, second = seed_pair(db_session)
    third = Rental(
        device_id=first.device_id,
        start_date=date(2026, 8, 20),
        end_date=date(2026, 8, 23),
        logistics_days=1,
        planned_ship_out_date=date(2026, 8, 18),
        planned_return_date=date(2026, 8, 25),
        ship_out_time=datetime(2026, 8, 18, 19),
        ship_in_time=datetime(2026, 8, 25, 12),
        customer_name="冲突后单",
        status="not_shipped",
    )
    db_session.add(third)
    db_session.flush()
    db_session.add(RentalRelayBinding(
        predecessor_rental_id=first.id,
        successor_rental_id=third.id,
    ))
    db_session.commit()

    with pytest.raises(RelayBindingConflictError, match="已存在其他接力绑定"):
        RelayCaseService.update_case(first.id, second.id, "agreed")

    assert RentalRelayCase.query.count() == 0
    assert RentalRelayBinding.query.filter_by(
        predecessor_rental_id=first.id,
        successor_rental_id=third.id,
    ).count() == 1


def test_audit_failure_rolls_back_case_and_binding(app, db_session, monkeypatch):
    first, second = seed_pair(db_session)

    def fail_audit(_cls, *_args):
        raise RuntimeError("注入失败")

    monkeypatch.setattr(
        RelayCaseService, "_add_audit", classmethod(fail_audit)
    )

    with pytest.raises(RuntimeError, match="注入失败"):
        RelayCaseService.update_case(first.id, second.id, "agreed")

    assert RentalRelayCase.query.count() == 0
    assert RentalRelayBinding.query.count() == 0
    assert AuditLog.query.count() == 0


def test_shipped_audit_failure_rolls_back_successor_and_skips_xianyu(
    app, db_session, monkeypatch
):
    first, second = seed_pair(db_session)
    shipped_rentals = []

    class FakeXianyuService:
        def ship_order(self, rental):
            shipped_rentals.append(rental.id)
            return {"success": True, "message": "ok"}

    def fail_audit(_cls, *_args):
        raise RuntimeError("注入失败")

    monkeypatch.setattr(
        xianyu_order_service,
        "get_xianyu_service",
        lambda: FakeXianyuService(),
    )
    monkeypatch.setattr(
        RelayCaseService, "_add_audit", classmethod(fail_audit)
    )

    with pytest.raises(RuntimeError, match="注入失败"):
        RelayCaseService.update_case(
            first.id,
            second.id,
            "shipped",
            sf_tracking_number="SF7234567890",
        )

    db_session.refresh(second)
    assert second.status == "not_shipped"
    assert second.ship_out_tracking_no is None
    assert RentalRelayCase.query.count() == 0
    assert RentalRelayBinding.query.count() == 0
    assert shipped_rentals == []


def test_shipped_commit_failure_rolls_back_successor_and_skips_xianyu(
    app, db_session, monkeypatch
):
    first, second = seed_pair(db_session)
    shipped_rentals = []

    class FakeXianyuService:
        def ship_order(self, rental):
            shipped_rentals.append(rental.id)
            return {"success": True, "message": "ok"}

    monkeypatch.setattr(
        xianyu_order_service,
        "get_xianyu_service",
        lambda: FakeXianyuService(),
    )
    real_commit = db.session.commit
    monkeypatch.setattr(
        db.session,
        "commit",
        lambda: (_ for _ in ()).throw(RuntimeError("提交失败")),
    )

    with pytest.raises(RuntimeError, match="提交失败"):
        RelayCaseService.update_case(
            first.id,
            second.id,
            "shipped",
            sf_tracking_number="SF8234567890",
        )

    monkeypatch.setattr(db.session, "commit", real_commit)
    db.session.expire_all()
    persisted_successor = db.session.get(Rental, second.id)
    assert persisted_successor.status == "not_shipped"
    assert persisted_successor.ship_out_tracking_no is None
    assert RentalRelayCase.query.count() == 0
    assert RentalRelayBinding.query.count() == 0
    assert shipped_rentals == []


def test_invalid_status_does_not_create_case(app, db_session):
    first, second = seed_pair(db_session)

    with pytest.raises(ValueError, match="无效的接力状态"):
        RelayCaseService.update_case(first.id, second.id, "unknown")

    assert RentalRelayCase.query.count() == 0
