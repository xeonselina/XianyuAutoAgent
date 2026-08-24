"""Warehouse-scoped inventory, gantt, device, and rental flows."""

import os
from datetime import date, datetime, time, timedelta

import pytest

from app import create_app, db
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental
from app.models.warehouse import Warehouse
from app.models.xianyu_order_alert import XianyuOrderAlert
from app.models.xianyu_shop import XianyuShop
from config import TestingConfig
from tests.support.test_database import (
    assert_current_user_has_test_only_grants,
    assert_test_database_url,
)


@pytest.fixture(scope="module")
def app():
    raw_url = os.environ.get("TEST_TENANT_DATABASE_URL_A")
    if raw_url:
        parsed = assert_test_database_url(raw_url)

        class WarehouseFlowConfig(TestingConfig):
            SQLALCHEMY_DATABASE_URI = parsed.render_as_string(
                hide_password=False
            )
            SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

        application = create_app(WarehouseFlowConfig)
        with application.app_context():
            with db.engine.connect() as connection:
                assert_current_user_has_test_only_grants(
                    connection,
                    parsed.database,
                    "control_saas_test",
                    "tenant_b_saas_test",
                )
        return application
    return create_app("testing")


@pytest.fixture(autouse=True)
def clean_schema(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def warehouse_case(app):
    with app.app_context():
        warehouse_a = Warehouse(
            province="广东省", city="深圳市", name="深圳仓库"
        )
        warehouse_b = Warehouse(
            province="浙江省", city="杭州市", name="杭州仓库"
        )
        model = DeviceModel(
            name="warehouse-camera",
            display_name="仓库测试相机",
            is_accessory=False,
            is_active=True,
        )
        accessory_model = DeviceModel(
            name="warehouse-tripod",
            display_name="仓库测试三脚架",
            is_accessory=True,
            is_active=True,
        )
        db.session.add_all(
            [warehouse_a, warehouse_b, model, accessory_model]
        )
        db.session.flush()
        main_a = Device(
            name="深圳主机",
            serial_number="WH-MAIN-A",
            model=model.name,
            model_id=model.id,
            is_accessory=False,
            warehouse_id=warehouse_a.id,
        )
        main_b = Device(
            name="杭州主机",
            serial_number="WH-MAIN-B",
            model=model.name,
            model_id=model.id,
            is_accessory=False,
            warehouse_id=warehouse_b.id,
        )
        accessory_a = Device(
            name="深圳三脚架",
            serial_number="WH-ACC-A",
            model=accessory_model.name,
            model_id=accessory_model.id,
            is_accessory=True,
            warehouse_id=warehouse_a.id,
        )
        accessory_b = Device(
            name="杭州三脚架",
            serial_number="WH-ACC-B",
            model=accessory_model.name,
            model_id=accessory_model.id,
            is_accessory=True,
            warehouse_id=warehouse_b.id,
        )
        db.session.add_all([main_a, main_b, accessory_a, accessory_b])
        db.session.commit()
        return {
            "warehouse_a": warehouse_a.id,
            "warehouse_b": warehouse_b.id,
            "model": model.id,
            "main_a": main_a.id,
            "main_b": main_b.id,
            "accessory_a": accessory_a.id,
            "accessory_b": accessory_b.id,
        }


def _rental_payload(case, **overrides):
    start = date.today() + timedelta(days=10)
    payload = {
        "warehouse_id": case["warehouse_a"],
        "device_id": case["main_a"],
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=3)).isoformat(),
        "ship_out_time": datetime.combine(
            start - timedelta(days=2), time(19)
        ).isoformat(),
        "ship_in_time": datetime.combine(
            start + timedelta(days=5), time(12)
        ).isoformat(),
        "customer_name": "仓库测试客户",
        "accessories": [],
    }
    payload.update(overrides)
    return payload


def _create_existing_rental(case, warehouse_key="warehouse_a"):
    warehouse_id = case[warehouse_key]
    device_id = case[
        "main_a" if warehouse_key == "warehouse_a" else "main_b"
    ]
    start = date.today() + timedelta(days=10)
    rental = Rental(
        device_id=device_id,
        warehouse_id=warehouse_id,
        start_date=start,
        end_date=start + timedelta(days=3),
        ship_out_time=datetime.combine(start - timedelta(days=2), time(19)),
        ship_in_time=datetime.combine(start + timedelta(days=5), time(12)),
        customer_name=f"{warehouse_key}-客户",
        status="not_shipped",
    )
    db.session.add(rental)
    db.session.commit()
    return rental


def _ids(response, key):
    payload = response.get_json()
    data = payload.get("data", payload)
    rows = data if key == "data" and isinstance(data, list) else data[key]
    return {row["id"] for row in rows}


def test_device_inventory_and_rental_reads_accept_warehouse_or_all(
    client, app, warehouse_case
):
    with app.app_context():
        rental_a = _create_existing_rental(warehouse_case, "warehouse_a")
        rental_b = _create_existing_rental(warehouse_case, "warehouse_b")
        rental_a_id, rental_b_id = rental_a.id, rental_b.id

    devices_a = client.get(
        f"/api/devices?warehouse_id={warehouse_case['warehouse_a']}"
    )
    devices_all = client.get("/api/devices?warehouse_id=all")
    assert _ids(devices_a, "devices") == {
        warehouse_case["main_a"], warehouse_case["accessory_a"]
    }
    assert _ids(devices_all, "devices") == {
        warehouse_case["main_a"], warehouse_case["main_b"],
        warehouse_case["accessory_a"], warehouse_case["accessory_b"],
    }

    start = date.today() + timedelta(days=30)
    inventory_a = client.get(
        "/api/inventory/available",
        query_string={
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=2)).isoformat(),
            "warehouse_id": warehouse_case["warehouse_a"],
        },
    )
    inventory_all = client.get(
        "/api/inventory/available",
        query_string={
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=2)).isoformat(),
            "warehouse_id": "all",
        },
    )
    assert _ids(inventory_a, "data") == {warehouse_case["main_a"]}
    assert _ids(inventory_all, "data") == {
        warehouse_case["main_a"], warehouse_case["main_b"]
    }

    rentals_a = client.get(
        f"/api/rentals?warehouse_id={warehouse_case['warehouse_a']}"
    )
    rentals_all = client.get("/api/rentals?warehouse_id=all")
    assert _ids(rentals_a, "rentals") == {rental_a_id}
    assert _ids(rentals_all, "rentals") == {rental_a_id, rental_b_id}


def test_gantt_data_statistics_and_slot_are_warehouse_scoped(
    client, app, warehouse_case
):
    with app.app_context():
        rental_a = _create_existing_rental(warehouse_case, "warehouse_a")
        _create_existing_rental(warehouse_case, "warehouse_b")
        start_date = rental_a.start_date.isoformat()
        end_date = rental_a.end_date.isoformat()
        rental_a_id = rental_a.id

    gantt = client.get(
        "/api/gantt/data",
        query_string={
            "start_date": start_date,
            "end_date": end_date,
            "warehouse_id": warehouse_case["warehouse_a"],
        },
    ).get_json()["data"]
    gantt_all = client.get(
        "/api/gantt/data",
        query_string={
            "start_date": start_date,
            "end_date": end_date,
            "warehouse_id": "all",
        },
    ).get_json()["data"]
    assert {row["id"] for row in gantt["devices"]} == {
        warehouse_case["main_a"]
    }
    assert {row["id"] for row in gantt["rentals"]} == {rental_a_id}
    assert {row["id"] for row in gantt_all["devices"]} == {
        warehouse_case["main_a"], warehouse_case["main_b"]
    }

    far_date = date.today() + timedelta(days=30)
    stats = client.get(
        "/api/gantt/daily-stats",
        query_string={
            "date": far_date.isoformat(),
            "warehouse_id": warehouse_case["warehouse_a"],
        },
    )
    assert stats.get_json()["data"]["available_count"] == 1

    slot = client.post(
        "/api/rentals/find-slot",
        json={
            "start_date": far_date.isoformat(),
            "end_date": (far_date + timedelta(days=2)).isoformat(),
            "logistics_days": 1,
            "model": warehouse_case["model"],
            "is_accessory": False,
            "warehouse_id": warehouse_case["warehouse_a"],
        },
    )
    slot_all = client.post(
        "/api/rentals/find-slot",
        json={
            "start_date": far_date.isoformat(),
            "end_date": (far_date + timedelta(days=2)).isoformat(),
            "logistics_days": 1,
            "model": warehouse_case["model"],
            "is_accessory": False,
            "warehouse_id": "all",
        },
    )
    assert _ids(slot, "available_devices") == {warehouse_case["main_a"]}
    assert _ids(slot_all, "available_devices") == {
        warehouse_case["main_a"], warehouse_case["main_b"]
    }


def test_rental_statistics_and_shipping_list_are_warehouse_scoped(
    client, app, warehouse_case
):
    with app.app_context():
        rental_a = _create_existing_rental(warehouse_case, "warehouse_a")
        rental_b = _create_existing_rental(warehouse_case, "warehouse_b")
        rental_a_id, rental_b_id = rental_a.id, rental_b.id
        start_date = rental_a.start_date
        ship_date = rental_a.ship_out_time.date()

    query = {
        "period_type": "week",
        "start_date": start_date.isoformat(),
        "end_date": (start_date + timedelta(days=6)).isoformat(),
        "warehouse_id": warehouse_case["warehouse_a"],
    }
    scoped_stats = client.get(
        "/api/rental-stats/periodic", query_string=query
    ).get_json()
    query["warehouse_id"] = "all"
    all_stats = client.get(
        "/api/rental-stats/periodic", query_string=query
    ).get_json()
    assert scoped_stats["data"][0]["device_count"] == 1
    assert scoped_stats["data"][0]["order_count"] == 1
    assert all_stats["data"][0]["device_count"] == 2
    assert all_stats["data"][0]["order_count"] == 2

    scoped_shipping = client.get(
        "/api/rentals/by-ship-date",
        query_string={
            "start_date": ship_date.isoformat(),
            "end_date": ship_date.isoformat(),
            "warehouse_id": warehouse_case["warehouse_a"],
        },
    )
    all_shipping = client.get(
        "/api/rentals/by-ship-date",
        query_string={
            "start_date": ship_date.isoformat(),
            "end_date": ship_date.isoformat(),
            "warehouse_id": "all",
        },
    )
    assert _ids(scoped_shipping, "rentals") == {rental_a_id}
    assert _ids(all_shipping, "rentals") == {rental_a_id, rental_b_id}


@pytest.mark.parametrize("warehouse_id", [None, "all", "not-an-id"])
def test_multi_warehouse_device_write_requires_concrete_warehouse(
    client, warehouse_case, warehouse_id
):
    payload = {
        "name": "新设备",
        "serial_number": f"NEW-{warehouse_id}",
    }
    if warehouse_id is not None:
        payload["warehouse_id"] = warehouse_id
    response = client.post("/api/devices", json=payload)
    assert response.status_code == 400


@pytest.mark.parametrize("warehouse_id", [None, "all", "not-an-id"])
def test_multi_warehouse_rental_write_requires_concrete_warehouse(
    client, app, warehouse_case, warehouse_id
):
    payload = _rental_payload(warehouse_case)
    if warehouse_id is None:
        payload.pop("warehouse_id")
    else:
        payload["warehouse_id"] = warehouse_id
    response = client.post("/api/rentals", json=payload)
    assert response.status_code == 400
    with app.app_context():
        assert Rental.query.count() == 0


def test_single_warehouse_device_write_auto_selects_and_update_cannot_move(
    client, app, warehouse_case
):
    with app.app_context():
        Device.query.filter_by(
            warehouse_id=warehouse_case["warehouse_b"]
        ).delete()
        second_warehouse = db.session.get(
            Warehouse, warehouse_case["warehouse_b"]
        )
        db.session.delete(second_warehouse)
        db.session.commit()

    created = client.post(
        "/api/devices",
        json={"name": "自动选仓设备", "serial_number": "AUTO-WH"},
    )
    assert created.status_code == 201
    assert created.get_json()["data"]["warehouse_id"] == warehouse_case[
        "warehouse_a"
    ]

    response = client.put(
        f"/api/devices/{created.get_json()['data']['id']}",
        json={"warehouse_id": warehouse_case["warehouse_a"]},
    )
    assert response.status_code == 400


def test_rental_create_persists_one_warehouse_for_main_and_children(
    client, warehouse_case
):
    response = client.post(
        "/api/rentals",
        json=_rental_payload(
            warehouse_case, accessories=[warehouse_case["accessory_a"]]
        ),
    )
    assert response.status_code == 201
    result = response.get_json()["data"]
    assert result["main_rental"]["warehouse_id"] == warehouse_case[
        "warehouse_a"
    ]
    assert {r["warehouse_id"] for r in result["accessory_rentals"]} == {
        warehouse_case["warehouse_a"]
    }
    assert {r["xianyu_shop_id"] for r in result["accessory_rentals"]} == {
        None
    }


def test_rental_rejects_cross_warehouse_inventory_atomically(
    client, app, warehouse_case
):
    response = client.post(
        "/api/rentals",
        json=_rental_payload(
            warehouse_case, accessories=[warehouse_case["accessory_b"]]
        ),
    )
    assert response.status_code == 409
    assert response.get_json()["code"] == "WAREHOUSE_MISMATCH"
    with app.app_context():
        assert Rental.query.count() == 0


def test_rental_create_rejects_busy_device_and_accessory(
    client, app, warehouse_case
):
    with app.app_context():
        _create_existing_rental(warehouse_case, "warehouse_a")
    busy_main = client.post(
        "/api/rentals", json=_rental_payload(warehouse_case)
    )
    assert busy_main.status_code == 409
    assert busy_main.get_json()["code"] == "DEVICE_UNAVAILABLE"

    with app.app_context():
        Rental.query.delete()
        existing = _create_existing_rental(warehouse_case, "warehouse_a")
        existing.device_id = warehouse_case["accessory_a"]
        db.session.commit()
    busy_accessory = client.post(
        "/api/rentals",
        json=_rental_payload(
            warehouse_case, accessories=[warehouse_case["accessory_a"]]
        ),
    )
    assert busy_accessory.status_code == 409
    assert busy_accessory.get_json()["code"] == "DEVICE_UNAVAILABLE"


def test_rental_update_validates_whole_selection_before_writing(
    client, app, warehouse_case
):
    with app.app_context():
        rental = _create_existing_rental(warehouse_case, "warehouse_a")
        rental_id = rental.id
        original_customer = rental.customer_name

    rejected = client.put(
        f"/api/rentals/{rental_id}",
        json={
            "warehouse_id": warehouse_case["warehouse_a"],
            "customer_name": "不应写入",
            "accessories": [warehouse_case["accessory_b"]],
        },
    )
    assert rejected.status_code == 409
    assert rejected.get_json()["code"] == "WAREHOUSE_MISMATCH"
    with app.app_context():
        persisted = db.session.get(Rental, rental_id)
        assert persisted.customer_name == original_customer
        assert list(persisted.child_rentals) == []

    accepted = client.put(
        f"/api/rentals/{rental_id}",
        json={
            "warehouse_id": warehouse_case["warehouse_b"],
            "device_id": warehouse_case["main_b"],
            "accessories": [warehouse_case["accessory_b"]],
        },
    )
    assert accepted.status_code == 200
    with app.app_context():
        persisted = db.session.get(Rental, rental_id)
        assert persisted.warehouse_id == warehouse_case["warehouse_b"]
        assert persisted.device_id == warehouse_case["main_b"]
        assert {child.warehouse_id for child in persisted.child_rentals} == {
            warehouse_case["warehouse_b"]
        }


def test_one_active_shop_auto_binds_and_offline_order_clears_shop(
    client, app, warehouse_case
):
    with app.app_context():
        shop = XianyuShop(
            name="唯一店铺", app_key="one", is_active=True
        )
        db.session.add(shop)
        db.session.commit()
        shop_id = shop.id

    created = client.post(
        "/api/rentals",
        json=_rental_payload(warehouse_case, xianyu_order_no="XY-ONE"),
    )
    assert created.status_code == 201
    assert created.get_json()["data"]["main_rental"][
        "xianyu_shop_id"
    ] == shop_id

    offline = client.post(
        "/api/rentals",
        json=_rental_payload(
            warehouse_case,
            device_id=warehouse_case["main_b"],
            warehouse_id=warehouse_case["warehouse_b"],
            xianyu_shop_id=shop_id,
            xianyu_order_no="",
        ),
    )
    assert offline.status_code == 201
    assert offline.get_json()["data"]["main_rental"]["xianyu_shop_id"] is None


def test_multiple_active_shops_require_valid_explicit_shop(
    client, app, warehouse_case
):
    with app.app_context():
        active_a = XianyuShop(name="店铺A", app_key="a", is_active=True)
        active_b = XianyuShop(name="店铺B", app_key="b", is_active=True)
        inactive = XianyuShop(name="停用店", app_key="off", is_active=False)
        db.session.add_all([active_a, active_b, inactive])
        db.session.commit()
        active_id = active_a.id
        inactive_id = inactive.id

    missing = client.post(
        "/api/rentals",
        json=_rental_payload(warehouse_case, xianyu_order_no="XY-MULTI"),
    )
    assert missing.status_code == 400

    invalid = client.post(
        "/api/rentals",
        json=_rental_payload(
            warehouse_case,
            xianyu_order_no="XY-MULTI",
            xianyu_shop_id=inactive_id,
        ),
    )
    assert invalid.status_code == 400

    accepted = client.post(
        "/api/rentals",
        json=_rental_payload(
            warehouse_case,
            xianyu_order_no="XY-MULTI",
            xianyu_shop_id=active_id,
        ),
    )
    assert accepted.status_code == 201


def test_order_alert_shop_is_inherited_even_with_multiple_active_shops(
    client, app, warehouse_case
):
    with app.app_context():
        alert_shop = XianyuShop(
            name="告警店铺", app_key="alert", is_active=True
        )
        other_shop = XianyuShop(
            name="其他店铺", app_key="other", is_active=True
        )
        db.session.add_all([alert_shop, other_shop])
        db.session.flush()
        db.session.add(
            XianyuOrderAlert(
                order_no="XY-ALERT",
                xianyu_shop_id=alert_shop.id,
                pay_amount=100,
            )
        )
        db.session.commit()
        alert_shop_id = alert_shop.id

    response = client.post(
        "/api/rentals",
        json=_rental_payload(warehouse_case, xianyu_order_no="XY-ALERT"),
    )
    assert response.status_code == 201
    assert response.get_json()["data"]["main_rental"][
        "xianyu_shop_id"
    ] == alert_shop_id


def test_order_alert_keeps_its_shop_after_shop_is_disabled(
    client, app, warehouse_case
):
    with app.app_context():
        shop = XianyuShop(
            name="已停用告警店铺", app_key="disabled", is_active=False
        )
        db.session.add(shop)
        db.session.flush()
        db.session.add(XianyuOrderAlert(
            order_no="XY-DISABLED-ALERT",
            xianyu_shop_id=shop.id,
            pay_amount=100,
        ))
        db.session.commit()
        shop_id = shop.id

    response = client.post(
        "/api/rentals",
        json=_rental_payload(
            warehouse_case, xianyu_order_no="XY-DISABLED-ALERT"
        ),
    )
    assert response.status_code == 201
    assert response.get_json()["data"]["main_rental"][
        "xianyu_shop_id"
    ] == shop_id


def test_order_number_uniqueness_is_scoped_to_shop(
    client, app, warehouse_case
):
    with app.app_context():
        shop_a = XianyuShop(name="店铺A", app_key="a", is_active=True)
        shop_b = XianyuShop(name="店铺B", app_key="b", is_active=True)
        db.session.add_all([shop_a, shop_b])
        db.session.commit()
        shop_a_id, shop_b_id = shop_a.id, shop_b.id

    first = client.post(
        "/api/rentals",
        json=_rental_payload(
            warehouse_case,
            xianyu_order_no="XY-SAME",
            xianyu_shop_id=shop_a_id,
        ),
    )
    second = client.post(
        "/api/rentals",
        json=_rental_payload(
            warehouse_case,
            device_id=warehouse_case["main_b"],
            warehouse_id=warehouse_case["warehouse_b"],
            xianyu_order_no="XY-SAME",
            xianyu_shop_id=shop_b_id,
        ),
    )
    later = date.today() + timedelta(days=40)
    duplicate = client.post(
        "/api/rentals",
        json=_rental_payload(
            warehouse_case,
            device_id=warehouse_case["main_b"],
            warehouse_id=warehouse_case["warehouse_b"],
            xianyu_order_no="XY-SAME",
            xianyu_shop_id=shop_a_id,
            start_date=later.isoformat(),
            end_date=(later + timedelta(days=2)).isoformat(),
            ship_out_time=datetime.combine(
                later - timedelta(days=2), time(19)
            ).isoformat(),
            ship_in_time=datetime.combine(
                later + timedelta(days=4), time(12)
            ).isoformat(),
        ),
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert duplicate.status_code == 400


@pytest.mark.parametrize("endpoint", [
    "/api/devices?warehouse_id=bad",
    "/api/rentals?warehouse_id=0",
    "/api/gantt/data?warehouse_id=999999",
])
def test_invalid_read_warehouse_is_a_stable_bad_request(
    client, warehouse_case, endpoint
):
    response = client.get(endpoint)
    assert response.status_code == 400


def test_invalid_slot_warehouse_is_a_stable_bad_request(
    client, warehouse_case
):
    response = client.post(
        "/api/rentals/find-slot",
        json={
            "start_date": (date.today() + timedelta(days=20)).isoformat(),
            "end_date": (date.today() + timedelta(days=22)).isoformat(),
            "logistics_days": 1,
            "model": warehouse_case["model"],
            "is_accessory": False,
            "warehouse_id": "bad",
        },
    )
    assert response.status_code == 400
