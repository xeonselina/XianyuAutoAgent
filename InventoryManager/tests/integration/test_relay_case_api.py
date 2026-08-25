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
from app.models.warehouse import Warehouse
from app.models.xianyu_shop import XianyuShop
from app.services import xianyu_order_service
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


def seed_pair(db_session, suffix, planned_ship_date=None):
    shop = XianyuShop(name=f"接力店 {suffix}", app_key="test", is_active=True)
    db_session.add(shop)
    db_session.flush()
    planned_ship_date = planned_ship_date or date.today()
    model = DeviceModel(
        name=f"relay-api-{suffix}",
        display_name=f"接力 API {suffix}",
        is_active=True,
    )
    db_session.add(model)
    db_session.flush()
    device = Device(
        name=f"RA-{suffix}",
        model=model.name,
        model_id=model.id,
        is_accessory=False,
        lifecycle_status="active",
        warehouse_id=db_session.query(Warehouse.id).scalar(),
    )
    db_session.add(device)
    db_session.flush()

    first_ship_out = planned_ship_date - timedelta(days=5)
    first_ship_in = planned_ship_date + timedelta(days=3)
    second_ship_out = first_ship_in - timedelta(days=2)
    first = Rental(
        device_id=device.id,
        warehouse_id=device.warehouse_id,
        start_date=planned_ship_date - timedelta(days=4),
        end_date=planned_ship_date - timedelta(days=1),
        ship_out_time=datetime.combine(first_ship_out, time(19)),
        ship_in_time=datetime.combine(first_ship_in, time(12)),
        customer_name=f"前单 {suffix}",
        customer_phone="13800138000",
        destination="杭州市西湖区",
        buyer_id=f"鹿鹿 {suffix}",
        status="not_shipped",
    )
    second = Rental(
        device_id=device.id,
        warehouse_id=device.warehouse_id,
        start_date=planned_ship_date + timedelta(days=4),
        end_date=planned_ship_date + timedelta(days=8),
        ship_out_time=datetime.combine(second_ship_out, time(19)),
        ship_in_time=datetime.combine(planned_ship_date + timedelta(days=10), time(12)),
        customer_name=f"后单 {suffix}",
        customer_phone="13900139000",
        destination="上海市浦东新区",
        buyer_id=f"星星 {suffix}",
        status="not_shipped",
        xianyu_shop_id=shop.id,
    )
    db_session.add_all([first, second])
    db_session.commit()
    return first, second


def sf_route(tracking_number="SF1234567890", status="in_transit"):
    return {
        "tracking_number": tracking_number,
        "status": status,
        "status_text": "运送中" if status != "delivered" else "已签收",
        "routes": [],
        "last_update": "2026-08-05 10:00:00",
        "delivered_time": None,
    }


def test_list_defaults_to_open_statuses_and_t_minus_3_to_plus_5(
    client, db_session
):
    inside = seed_pair(db_session, "inside", date.today())
    seed_pair(db_session, "outside", date.today() + timedelta(days=6))
    completed = seed_pair(db_session, "completed", date.today())
    db_session.add(RentalRelayCase(
        predecessor_rental_id=completed[0].id,
        successor_rental_id=completed[1].id,
        status="completed",
        sf_tracking_number="SFCOMPLETED",
    ))
    db_session.commit()

    response = client.get("/api/relay-cases")

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["total"] == 1
    assert payload["items"][0]["predecessor"]["id"] == inside[0].id
    assert payload["filters"] == {
        "statuses": ["pending", "notified", "agreed", "shipped"],
        "ship_date_from": (date.today() - timedelta(days=3)).isoformat(),
        "ship_date_to": (date.today() + timedelta(days=5)).isoformat(),
    }
    assert payload["per_page"] == 50


def test_list_accepts_completed_status_date_range_and_pagination(
    client, db_session
):
    pair = seed_pair(db_session, "completed-filter", date.today())
    relay_case = RentalRelayCase(
        predecessor_rental_id=pair[0].id,
        successor_rental_id=pair[1].id,
        status="completed",
        sf_tracking_number="SFDONE",
    )
    db_session.add(relay_case)
    db_session.commit()

    response = client.get(
        "/api/relay-cases",
        query_string={
            "statuses": "completed",
            "ship_date_from": date.today().isoformat(),
            "ship_date_to": date.today().isoformat(),
            "page": 1,
            "per_page": 1,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["total"] == 1
    assert payload["items"][0]["case_id"] == relay_case.id
    assert payload["items"][0]["status"] == "completed"


def test_update_creates_notified_case(client, db_session):
    first, second = seed_pair(db_session, "notify")

    response = client.put(
        f"/api/relay-cases/{first.id}/{second.id}",
        json={"status": "notified"},
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["status"] == "notified"
    assert RentalRelayCase.query.filter_by(
        predecessor_rental_id=first.id,
        successor_rental_id=second.id,
    ).one().notified_at is not None


def prepare_manual_pair(db_session, suffix="manual"):
    first, second = seed_pair(db_session, suffix)
    first.status = "returned"
    second.status = "not_shipped"
    second.ship_out_time = first.ship_in_time + timedelta(days=1)
    second.start_date = second.ship_out_time.date() + timedelta(days=1)
    second.end_date = second.start_date + timedelta(days=4)
    db_session.commit()
    return first, second


def test_manual_options_resolve_returned_current_and_next_rental(
    client, db_session
):
    first, second = prepare_manual_pair(db_session, "manual-options")

    response = client.get("/api/relay-cases/manual-options")

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["total"] == 1
    option = payload["items"][0]
    assert option["device"]["id"] == first.device_id
    assert option["predecessor"]["id"] == first.id
    assert option["predecessor"]["status"] == "returned"
    assert option["successor"]["id"] == second.id
    assert option["successor"]["status"] == "not_shipped"
    assert option["can_create"] is True
    assert option["blocked_reason"] is None


def test_manual_create_binds_pair_as_agreed_and_keeps_it_visible(
    client, db_session
):
    first, second = prepare_manual_pair(db_session, "manual-create")

    response = client.post(
        "/api/relay-cases/manual",
        json={"device_id": first.device_id},
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["predecessor_rental_id"] == first.id
    assert payload["successor_rental_id"] == second.id
    assert payload["status"] == "agreed"
    assert RentalRelayBinding.query.filter_by(
        predecessor_rental_id=first.id,
        successor_rental_id=second.id,
    ).one_or_none() is not None
    relay_case = RentalRelayCase.query.filter_by(
        predecessor_rental_id=first.id,
        successor_rental_id=second.id,
    ).one()
    assert AuditLog.query.filter_by(
        action="relay_case_manually_created",
        resource_id=str(relay_case.id),
    ).one_or_none() is not None

    list_response = client.get(
        "/api/relay-cases",
        query_string={
            "statuses": "agreed",
            "ship_date_from": (date.today() - timedelta(days=2)).isoformat(),
            "ship_date_to": (date.today() + timedelta(days=2)).isoformat(),
        },
    )
    list_payload = list_response.get_json()["data"]
    assert list_payload["total"] == 1
    assert list_payload["items"][0]["source"] == "manual"
    assert list_payload["items"][0]["schedule_changed"] is False

def test_manual_create_rejects_pair_that_is_already_bound(client, db_session):
    first, second = prepare_manual_pair(db_session, "manual-duplicate")
    db_session.add(RentalRelayBinding(
        predecessor_rental_id=first.id,
        successor_rental_id=second.id,
    ))
    db_session.commit()

    response = client.post(
        "/api/relay-cases/manual",
        json={"device_id": first.device_id},
    )

    assert response.status_code == 409
    assert "已标记为接力" in response.get_json()["message"]


def test_manual_options_require_an_ongoing_current_rental(client, db_session):
    first, _ = prepare_manual_pair(db_session, "manual-completed")
    first.status = "completed"
    db_session.commit()

    response = client.get("/api/relay-cases/manual-options")

    assert response.status_code == 200
    assert response.get_json()["data"] == {"items": [], "total": 0}


def test_shipped_requires_tracking_number(client, db_session):
    first, second = seed_pair(db_session, "missing-tracking")

    response = client.put(
        f"/api/relay-cases/{first.id}/{second.id}",
        json={"status": "shipped"},
    )

    assert response.status_code == 400
    assert "顺丰运单号" in response.get_json()["message"]
    assert RentalRelayCase.query.count() == 0


def test_shipped_saves_then_refreshes_tracking(
    client, db_session, monkeypatch
):
    first, second = seed_pair(db_session, "ship")
    second.xianyu_order_no = "5126917575981011333"
    db_session.commit()
    shipped_rentals = []

    class FakeXianyuService:
        def ship_order(self, rental):
            shipped_rentals.append(rental.id)
            return {"success": True, "message": "ok", "data": {}}

    monkeypatch.setattr(
        xianyu_order_service,
        "get_xianyu_service",
        lambda **_: FakeXianyuService(),
    )
    monkeypatch.setattr(
        SFTrackingService,
        "query",
        classmethod(lambda cls, number, phone, **_: sf_route(number)),
    )

    response = client.put(
        f"/api/relay-cases/{first.id}/{second.id}",
        json={
            "status": "shipped",
            "sf_tracking_number": "SF1234567890",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["status"] == "shipped"
    assert payload["tracking"]["status"] == "in_transit"
    assert payload["xianyu_sync"] == {
        "attempted": True,
        "success": True,
        "message": "ok",
    }
    db_session.refresh(second)
    assert second.status == "shipped"
    assert second.ship_out_tracking_no == "SF1234567890"
    assert shipped_rentals == [second.id]
    assert RentalRelayBinding.query.count() == 1


@pytest.mark.parametrize(
    ("xianyu_result", "expected_message"),
    [
        (
            {"success": False, "message": "没有闲鱼订单号", "skipped": True},
            "闲鱼发货失败",
        ),
        (
            {"success": False, "message": "闲鱼接口繁忙", "code": 500},
            "闲鱼发货失败",
        ),
        (RuntimeError("闲鱼网络超时"), "闲鱼发货失败"),
    ],
)
def test_shipped_xianyu_failure_keeps_local_state_and_refreshes_tracking(
    client,
    db_session,
    monkeypatch,
    xianyu_result,
    expected_message,
):
    first, second = seed_pair(db_session, "ship-xianyu-failure")
    second.xianyu_order_no = "3315624386722187397"
    db_session.commit()

    class FakeXianyuService:
        def ship_order(self, rental):
            if isinstance(xianyu_result, Exception):
                raise xianyu_result
            return xianyu_result

    monkeypatch.setattr(
        xianyu_order_service,
        "get_xianyu_service",
        lambda **_: FakeXianyuService(),
    )
    monkeypatch.setattr(
        SFTrackingService,
        "query",
        classmethod(lambda cls, number, phone, **_: sf_route(number)),
    )

    response = client.put(
        f"/api/relay-cases/{first.id}/{second.id}",
        json={
            "status": "shipped",
            "sf_tracking_number": "SF2234567890",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["xianyu_sync"] == {
        "attempted": True,
        "success": False,
        "message": expected_message,
    }
    assert payload["tracking"]["status"] == "in_transit"
    db_session.refresh(second)
    assert second.status == "shipped"
    assert second.ship_out_tracking_no == "SF2234567890"


def test_binding_conflict_returns_409(client, db_session):
    first, second = seed_pair(db_session, "conflict")
    third = Rental(
        device_id=first.device_id,
        warehouse_id=first.warehouse_id,
        start_date=date.today() + timedelta(days=20),
        end_date=date.today() + timedelta(days=23),
        ship_out_time=datetime.combine(
            date.today() + timedelta(days=18), time(19)
        ),
        ship_in_time=datetime.combine(
            date.today() + timedelta(days=25), time(12)
        ),
        customer_name="冲突订单",
        status="not_shipped",
    )
    db_session.add(third)
    db_session.flush()
    db_session.add(RentalRelayBinding(
        predecessor_rental_id=first.id,
        successor_rental_id=third.id,
    ))
    db_session.commit()

    response = client.put(
        f"/api/relay-cases/{first.id}/{second.id}",
        json={"status": "agreed"},
    )

    assert response.status_code == 409
    assert "其他接力绑定" in response.get_json()["message"]


@pytest.mark.parametrize(
    "query_string",
    [
        {"statuses": "unknown"},
        {"ship_date_from": "2026-99-99"},
        {"ship_date_from": "2026-08-10", "ship_date_to": "2026-08-01"},
        {"page": 0},
        {"per_page": 101},
    ],
)
def test_list_rejects_invalid_filters(client, db_session, query_string):
    response = client.get("/api/relay-cases", query_string=query_string)

    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_single_and_batch_tracking_refresh_support_partial_failures(
    client, db_session, monkeypatch
):
    first, second = seed_pair(db_session, "tracking")
    shipped = RelayCaseService.update_case(
        first.id,
        second.id,
        "shipped",
        sf_tracking_number="SF1234567890",
    ).relay_case
    agreed_pair = seed_pair(db_session, "agreed")
    agreed = RelayCaseService.update_case(
        agreed_pair[0].id, agreed_pair[1].id, "agreed"
    ).relay_case
    monkeypatch.setattr(
        SFTrackingService,
        "query",
        classmethod(lambda cls, number, phone, **_: sf_route(number)),
    )

    single = client.post(
        f"/api/relay-cases/{shipped.id}/tracking/refresh"
    )
    batch = client.post(
        "/api/relay-cases/tracking/refresh-batch",
        json={"case_ids": [shipped.id, agreed.id]},
    )

    assert single.status_code == 200
    assert single.get_json()["data"]["status"] == "in_transit"
    assert batch.status_code == 200
    payload = batch.get_json()["data"]
    assert payload["total"] == 2
    assert payload["success_count"] == 1
    assert payload["items"][1]["success"] is False
    assert "尚未寄出" in payload["items"][1]["message"]
