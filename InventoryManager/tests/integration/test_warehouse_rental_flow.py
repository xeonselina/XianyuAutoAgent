"""Warehouse-scoped inventory, gantt, device, and rental flows."""

import os
from datetime import date, datetime, time, timedelta
from threading import Barrier, Thread

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


def test_concurrent_rental_updates_serialize_the_fresh_whole_group(
    client, app, warehouse_case, monkeypatch
):
    """Disjoint Device locks must not let one Rental group become mixed."""
    with app.app_context():
        if db.engine.dialect.name != "mysql":
            pytest.skip("row-lock concurrency probe requires MariaDB")
        warehouse_c = Warehouse(
            province="四川省", city="成都市", name="成都仓库"
        )
        model = db.session.get(DeviceModel, warehouse_case["model"])
        db.session.add(warehouse_c)
        db.session.flush()
        main_c = Device(
            name="成都原主机",
            serial_number="WH-MAIN-C",
            model=model.name,
            model_id=model.id,
            is_accessory=False,
            warehouse_id=warehouse_c.id,
        )
        db.session.add(main_c)
        db.session.flush()
        start = date.today() + timedelta(days=10)
        rental = Rental(
            device_id=main_c.id,
            warehouse_id=warehouse_c.id,
            start_date=start,
            end_date=start + timedelta(days=3),
            ship_out_time=datetime.combine(
                start - timedelta(days=2), time(19)
            ),
            ship_in_time=datetime.combine(
                start + timedelta(days=5), time(12)
            ),
            customer_name="并发更新前客户",
            status="not_shipped",
        )
        db.session.add(rental)
        db.session.commit()
        rental_id = rental.id

    from app.services.rental.rental_service import RentalService

    selections_ready = Barrier(2)
    original_update = RentalService.update_rental_with_accessories

    def synchronized_validate(
        warehouse_id,
        device_id,
        accessory_ids,
        _occupancy_start,
        _occupancy_end,
        exclude_rental_ids=(),
        preserve_existing=False,
    ):
        del exclude_rental_ids, preserve_existing
        selected_ids = sorted({int(device_id), *map(int, accessory_ids)})
        selected = (
            Device.query.filter(Device.id.in_(selected_ids))
            .order_by(Device.id)
            .populate_existing()
            .with_for_update()
            .all()
        )
        selected_by_id = {row.id: row for row in selected}
        assert all(
            row.warehouse_id == warehouse_id for row in selected
        )
        selections_ready.wait(timeout=5)
        return (
            selected_by_id[int(device_id)],
            [selected_by_id[int(row_id)] for row_id in accessory_ids],
        )

    monkeypatch.setattr(
        RentalService, "_validate_selection", synchronized_validate
    )

    def update_without_implicit_autoflush(*args, **kwargs):
        # The invariant must come from explicit group locks, not an incidental
        # relationship-query autoflush of the main row.
        db.session.autoflush = False
        return original_update(*args, **kwargs)

    monkeypatch.setattr(
        RentalService,
        "update_rental_with_accessories",
        update_without_implicit_autoflush,
    )
    results = []

    def submit(payload):
        response = app.test_client().put(
            f"/api/rentals/{rental_id}", json=payload
        )
        results.append(response.status_code)

    payload_a = _rental_payload(
        warehouse_case,
        accessories=[warehouse_case["accessory_a"]],
        customer_name="并发更新甲",
    )
    payload_b = _rental_payload(
        warehouse_case,
        warehouse_id=warehouse_case["warehouse_b"],
        device_id=warehouse_case["main_b"],
        accessories=[warehouse_case["accessory_b"]],
        customer_name="并发更新乙",
    )
    threads = [
        Thread(target=submit, args=(payload,))
        for payload in (payload_a, payload_b)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert sorted(results) == [200, 200]
    with app.app_context():
        group = Rental.query.filter(
            (Rental.id == rental_id)
            | (Rental.parent_rental_id == rental_id)
        ).order_by(Rental.id).all()
        assert len(group) == 2
        serialized_identity = {
            (row.warehouse_id, row.device_id) for row in group
        }
        assert serialized_identity in (
            {
                (
                    warehouse_case["warehouse_a"],
                    warehouse_case["main_a"],
                ),
                (
                    warehouse_case["warehouse_a"],
                    warehouse_case["accessory_a"],
                ),
            },
            {
                (
                    warehouse_case["warehouse_b"],
                    warehouse_case["main_b"],
                ),
                (
                    warehouse_case["warehouse_b"],
                    warehouse_case["accessory_b"],
                ),
            },
        )


@pytest.mark.parametrize(
    ("status", "ship_out_tracking_no"),
    [
        ("shipped", None),
        ("returned", None),
        ("completed", None),
        ("not_shipped", "SF-OUTBOUND-EVIDENCE"),
    ],
)
def test_fulfilled_rental_rejects_identity_reassignment_atomically(
    client, app, warehouse_case, status, ship_out_tracking_no
):
    created = client.post(
        "/api/rentals",
        json=_rental_payload(
            warehouse_case,
            accessories=[warehouse_case["accessory_a"]],
        ),
    )
    assert created.status_code == 201
    rental_id = created.get_json()["data"]["main_rental"]["id"]
    with app.app_context():
        rental = db.session.get(Rental, rental_id)
        rental.status = status
        rental.ship_out_tracking_no = ship_out_tracking_no
        for child in rental.child_rentals:
            child.status = status
            child.ship_out_tracking_no = ship_out_tracking_no
        db.session.commit()
        original_customer = rental.customer_name

    response = client.put(
        f"/api/rentals/{rental_id}",
        json={
            "warehouse_id": warehouse_case["warehouse_b"],
            "device_id": warehouse_case["main_b"],
            "accessories": [warehouse_case["accessory_b"]],
            "customer_name": "不得部分写入",
        },
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "已履约租赁不能更换仓库或设备"
    with app.app_context():
        persisted = db.session.get(Rental, rental_id)
        children = list(persisted.child_rentals)
        assert persisted.warehouse_id == warehouse_case["warehouse_a"]
        assert persisted.device_id == warehouse_case["main_a"]
        assert persisted.customer_name == original_customer
        assert len(children) == 1
        assert children[0].warehouse_id == warehouse_case["warehouse_a"]
        assert children[0].device_id == warehouse_case["accessory_a"]


@pytest.mark.parametrize(
    ("status", "ship_out_tracking_no"),
    [
        ("shipped", None),
        ("returned", None),
        ("completed", None),
        ("not_shipped", "SF-OUTBOUND-EVIDENCE"),
    ],
)
def test_fulfilled_rental_allows_same_identity_metadata_edit(
    client, app, warehouse_case, status, ship_out_tracking_no
):
    created = client.post(
        "/api/rentals",
        json=_rental_payload(
            warehouse_case,
            accessories=[warehouse_case["accessory_a"]],
        ),
    )
    rental_id = created.get_json()["data"]["main_rental"]["id"]
    with app.app_context():
        rental = db.session.get(Rental, rental_id)
        rental.status = status
        rental.ship_out_tracking_no = ship_out_tracking_no
        for child in rental.child_rentals:
            child.status = status
            child.ship_out_tracking_no = ship_out_tracking_no
        if status == "completed":
            for device_id in (
                warehouse_case["main_a"],
                warehouse_case["accessory_a"],
            ):
                device = db.session.get(Device, device_id)
                device.warehouse_id = warehouse_case["warehouse_b"]
                device.lifecycle_status = "retired"
        db.session.commit()

    response = client.put(
        f"/api/rentals/{rental_id}",
        json={
            "warehouse_id": warehouse_case["warehouse_a"],
            "device_id": warehouse_case["main_a"],
            "accessories": [warehouse_case["accessory_a"]],
            "customer_name": "允许修改备注字段",
        },
    )

    assert response.status_code == 200
    with app.app_context():
        persisted = db.session.get(Rental, rental_id)
        assert persisted.customer_name == "允许修改备注字段"
        assert persisted.warehouse_id == warehouse_case["warehouse_a"]
        assert persisted.device_id == warehouse_case["main_a"]
        assert {
            (child.warehouse_id, child.device_id)
            for child in persisted.child_rentals
        } == {
            (
                warehouse_case["warehouse_a"],
                warehouse_case["accessory_a"],
            )
        }


def test_scheduled_unshipped_rental_identity_remains_editable(
    client, app, warehouse_case
):
    created = client.post(
        "/api/rentals",
        json=_rental_payload(
            warehouse_case,
            accessories=[warehouse_case["accessory_a"]],
        ),
    )
    rental_id = created.get_json()["data"]["main_rental"]["id"]
    with app.app_context():
        rental = db.session.get(Rental, rental_id)
        rental.status = "scheduled_for_shipping"
        for child in rental.child_rentals:
            child.status = "scheduled_for_shipping"
        db.session.commit()

    response = client.put(
        f"/api/rentals/{rental_id}",
        json={
            "warehouse_id": warehouse_case["warehouse_b"],
            "device_id": warehouse_case["main_b"],
            "accessories": [warehouse_case["accessory_b"]],
        },
    )

    assert response.status_code == 200
    with app.app_context():
        group = Rental.query.filter(
            (Rental.id == rental_id)
            | (Rental.parent_rental_id == rental_id)
        ).all()
        assert {row.warehouse_id for row in group} == {
            warehouse_case["warehouse_b"]
        }
        assert {row.device_id for row in group} == {
            warehouse_case["main_b"], warehouse_case["accessory_b"]
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


def test_rental_create_uses_effective_logistics_occupancy(
    client, app, warehouse_case
):
    with app.app_context():
        existing = _create_existing_rental(warehouse_case, "warehouse_a")
        later_start = existing.end_date + timedelta(days=3)
        overlapping_ship_out = existing.ship_in_time - timedelta(hours=1)

    response = client.post(
        "/api/rentals",
        json=_rental_payload(
            warehouse_case,
            start_date=later_start.isoformat(),
            end_date=(later_start + timedelta(days=2)).isoformat(),
            ship_out_time=overlapping_ship_out.isoformat(),
            ship_in_time=datetime.combine(
                later_start + timedelta(days=4), time(12)
            ).isoformat(),
        ),
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "DEVICE_UNAVAILABLE"


def test_rental_create_rejects_invalid_effective_occupancy_interval(
    client, app, warehouse_case
):
    start = date.today() + timedelta(days=10)
    response = client.post(
        "/api/rentals",
        json=_rental_payload(
            warehouse_case,
            ship_out_time=datetime.combine(start, time(12)).isoformat(),
            ship_in_time=datetime.combine(start, time(11)).isoformat(),
        ),
    )

    assert response.status_code == 400
    with app.app_context():
        assert Rental.query.count() == 0


def test_rental_update_merges_logistics_before_conflict_check(
    client, app, warehouse_case
):
    with app.app_context():
        existing = _create_existing_rental(warehouse_case, "warehouse_a")
        later_start = existing.end_date + timedelta(days=10)
        later = Rental(
            device_id=warehouse_case["main_a"],
            warehouse_id=warehouse_case["warehouse_a"],
            start_date=later_start,
            end_date=later_start + timedelta(days=2),
            ship_out_time=datetime.combine(
                later_start - timedelta(days=2), time(19)
            ),
            ship_in_time=datetime.combine(
                later_start + timedelta(days=4), time(12)
            ),
            customer_name="稍后客户",
            status="not_shipped",
        )
        db.session.add(later)
        db.session.commit()
        later_id = later.id
        original_ship_out = later.ship_out_time
        overlapping_ship_out = existing.ship_in_time - timedelta(hours=1)

    response = client.put(
        f"/api/rentals/{later_id}",
        json={
            "warehouse_id": warehouse_case["warehouse_a"],
            "ship_out_time": overlapping_ship_out.isoformat(),
        },
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "DEVICE_UNAVAILABLE"
    with app.app_context():
        assert db.session.get(Rental, later_id).ship_out_time == (
            original_ship_out
        )


def _concurrent_create(app, payloads):
    barrier = Barrier(len(payloads))
    results = []

    def submit(payload):
        client = app.test_client()
        barrier.wait()
        response = client.post("/api/rentals", json=payload)
        body = response.get_json()
        results.append((response.status_code, body.get("code")))

    threads = [Thread(target=submit, args=(payload,)) for payload in payloads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    return sorted(results)


def test_concurrent_rental_create_serializes_main_device(
    app, warehouse_case
):
    with app.app_context():
        if db.engine.dialect.name != "mysql":
            pytest.skip("row-lock concurrency probe requires MariaDB")
    payload = _rental_payload(warehouse_case)

    results = _concurrent_create(
        app,
        [
            {**payload, "customer_name": "并发客户甲"},
            {**payload, "customer_name": "并发客户乙"},
        ],
    )

    assert results == [(201, None), (409, "DEVICE_UNAVAILABLE")]


def test_concurrent_rental_create_serializes_shared_accessory(
    app, warehouse_case
):
    with app.app_context():
        if db.engine.dialect.name != "mysql":
            pytest.skip("row-lock concurrency probe requires MariaDB")
        model = db.session.get(DeviceModel, warehouse_case["model"])
        other_main = Device(
            name="深圳备用主机",
            serial_number="WH-MAIN-A2",
            model=model.name,
            model_id=model.id,
            is_accessory=False,
            warehouse_id=warehouse_case["warehouse_a"],
        )
        db.session.add(other_main)
        db.session.commit()
        other_main_id = other_main.id
    payload = _rental_payload(
        warehouse_case, accessories=[warehouse_case["accessory_a"]]
    )

    results = _concurrent_create(
        app,
        [
            {**payload, "customer_name": "附件并发甲"},
            {
                **payload,
                "device_id": other_main_id,
                "customer_name": "附件并发乙",
            },
        ],
    )

    assert results == [(201, None), (409, "DEVICE_UNAVAILABLE")]


def test_lifecycle_reads_cover_concrete_all_omitted_and_invalid_warehouse(
    client, warehouse_case
):
    scoped_summary = client.get(
        "/api/devices/lifecycle/summary",
        query_string={"warehouse_id": warehouse_case["warehouse_a"]},
    )
    all_summary = client.get(
        "/api/devices/lifecycle/summary",
        query_string={"warehouse_id": "all"},
    )
    omitted_summary = client.get("/api/devices/lifecycle/summary")
    scoped_list = client.get(
        "/api/devices/lifecycle/list",
        query_string={"warehouse_id": warehouse_case["warehouse_a"]},
    )

    assert scoped_summary.get_json()["data"][
        "lifecycle_status_summary"
    ]["total"] == 2
    assert all_summary.get_json()["data"][
        "lifecycle_status_summary"
    ]["total"] == 4
    assert omitted_summary.get_json()["data"][
        "lifecycle_status_summary"
    ]["total"] == 4
    assert {row["id"] for row in scoped_list.get_json()["data"]} == {
        warehouse_case["main_a"], warehouse_case["accessory_a"]
    }
    for warehouse_id in ("bad", 999999):
        assert client.get(
            "/api/devices/lifecycle/list",
            query_string={"warehouse_id": warehouse_id},
        ).status_code == 400


def test_external_reads_keep_api_key_and_support_warehouse_scope(
    client, app, warehouse_case
):
    with app.app_context():
        app.config["API_KEY"] = "scope-test-key"
        rental_a = _create_existing_rental(warehouse_case, "warehouse_a")
        _create_existing_rental(warehouse_case, "warehouse_b")
        rental_a_id = rental_a.id
    headers = {"X-API-Key": "scope-test-key"}

    scoped_devices = client.get(
        "/external-api/devices",
        query_string={"warehouse_id": warehouse_case["warehouse_a"]},
        headers=headers,
    )
    all_devices = client.get(
        "/external-api/devices",
        query_string={"warehouse_id": "all"},
        headers=headers,
    )
    omitted_devices = client.get("/external-api/devices", headers=headers)
    scoped_stats = client.get(
        "/external-api/statistics",
        query_string={"warehouse_id": warehouse_case["warehouse_a"]},
        headers=headers,
    )

    assert {row["id"] for row in scoped_devices.get_json()["data"]} == {
        warehouse_case["main_a"], warehouse_case["accessory_a"]
    }
    assert len(all_devices.get_json()["data"]) == 4
    assert len(omitted_devices.get_json()["data"]) == 4
    assert scoped_stats.get_json()["data"]["devices"]["total"] == 2
    assert scoped_stats.get_json()["data"]["rentals"]["total"] == 1
    assert rental_a_id is not None
    assert client.get(
        "/external-api/devices",
        query_string={"warehouse_id": "bad"},
        headers=headers,
    ).status_code == 400
    assert client.get(
        "/external-api/statistics",
        query_string={"warehouse_id": 999999},
        headers=headers,
    ).status_code == 400
    assert client.get(
        "/external-api/devices",
        query_string={"warehouse_id": warehouse_case["warehouse_a"]},
    ).status_code == 401


def test_external_inventory_available_is_warehouse_scoped(
    client, app, warehouse_case
):
    with app.app_context():
        app.config["API_KEY"] = "scope-test-key"
    future = datetime.now() + timedelta(days=30)
    response = client.get(
        "/external-api/inventory/available",
        query_string={
            "warehouse_id": warehouse_case["warehouse_a"],
            "ship_out_time": future.isoformat(),
            "ship_in_time": (future + timedelta(days=2)).isoformat(),
        },
        headers={"X-API-Key": "scope-test-key"},
    )

    assert response.status_code == 200
    assert {row["device_id"] for row in response.get_json()["data"]} == {
        warehouse_case["main_a"]
    }


def test_periodic_history_stays_with_rental_warehouse_after_device_move(
    client, app, warehouse_case
):
    with app.app_context():
        rental = _create_existing_rental(warehouse_case, "warehouse_a")
        rental.order_amount = 321
        start_date = rental.start_date
        db.session.get(Device, warehouse_case["main_a"]).warehouse_id = (
            warehouse_case["warehouse_b"]
        )
        db.session.commit()

    response = client.get(
        "/api/rental-stats/periodic",
        query_string={
            "period_type": "week",
            "start_date": start_date.isoformat(),
            "end_date": (start_date + timedelta(days=6)).isoformat(),
            "warehouse_id": warehouse_case["warehouse_a"],
        },
    )

    row = response.get_json()["data"][0]
    assert row["device_count"] == 0
    assert row["order_count"] == 1
    assert row["order_amount"] == 321


def test_x200_history_stays_with_rental_warehouse_after_device_move(
    client, app, warehouse_case
):
    with app.app_context():
        model = db.session.get(DeviceModel, warehouse_case["model"])
        model.device_value = 1000
        historical = Rental(
            device_id=warehouse_case["main_a"],
            warehouse_id=warehouse_case["warehouse_a"],
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 3),
            customer_name="历史仓客户",
            order_amount=100,
            status="completed",
        )
        db.session.add(historical)
        db.session.flush()
        db.session.get(Device, warehouse_case["main_a"]).warehouse_id = (
            warehouse_case["warehouse_b"]
        )
        db.session.commit()

    response = client.get(
        "/api/rental-stats/x200u-forecast",
        query_string={"warehouse_id": warehouse_case["warehouse_a"]},
    )

    assert response.status_code == 200
    assert response.get_json()["device_count"] == 0
    assert response.get_json()["hist_net_profit"] == 85
