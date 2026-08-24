"""Atomic warehouse receipt behavior for return inspections."""

import os
from datetime import date, timedelta
from threading import Barrier, Thread

import pytest
from sqlalchemy import event

from app import create_app, db
from app.models.audit_log import AuditLog
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.inspection_check_item import InspectionCheckItem
from app.models.inspection_record import InspectionRecord
from app.models.rental import Rental
from app.models.warehouse import Warehouse
from app.services.warehouse_movement_service import WarehouseMovementService
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

        class InspectionWarehouseConfig(TestingConfig):
            SQLALCHEMY_DATABASE_URI = parsed.render_as_string(
                hide_password=False
            )
            SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

        application = create_app(InspectionWarehouseConfig)
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


def _warehouse(name):
    row = Warehouse(
        province=f"{name}省", city=f"{name}市", name=f"{name}仓"
    )
    db.session.add(row)
    db.session.flush()
    return row


def _model(name, *, accessory):
    row = DeviceModel(
        name=name,
        display_name=name,
        is_accessory=accessory,
        is_active=True,
    )
    db.session.add(row)
    db.session.flush()
    return row


def _device(name, warehouse, model, *, accessory=False):
    row = Device(
        name=name,
        serial_number=f"INSPECTION-{name}",
        model=model.name,
        model_id=model.id,
        is_accessory=accessory,
        lifecycle_status="active",
        warehouse_id=warehouse.id,
    )
    db.session.add(row)
    db.session.flush()
    return row


def _rental(device, warehouse, *, parent=None, future=False, flags=False):
    offset = timedelta(days=10) if future else -timedelta(days=4)
    start = date.today() + offset
    row = Rental(
        device_id=device.id,
        warehouse_id=warehouse.id,
        parent_rental_id=parent.id if parent else None,
        start_date=start,
        end_date=start + timedelta(days=2),
        customer_name=f"客户-{device.name}",
        status="not_shipped" if future else "completed",
        includes_handle=flags,
        includes_lens_mount=flags,
    )
    db.session.add(row)
    db.session.flush()
    return row


def _payload(case, **overrides):
    payload = {
        "rental_id": case["rental"],
        "device_id": case["main"],
        "check_items": [
            {"name": "机身与附件", "is_checked": True, "order": 1}
        ],
    }
    payload.update(overrides)
    return payload


def _seed_case(*, with_future=False):
    source = _warehouse("深圳")
    target = _warehouse("杭州")
    main_model = _model("inspection-camera", accessory=False)
    accessory_model = _model("inspection-tripod", accessory=True)
    main = _device("main", source, main_model)
    received = _device(
        "received-tripod", source, accessory_model, accessory=True
    )
    not_received = _device(
        "not-received-tripod", source, accessory_model, accessory=True
    )
    unrelated = _device(
        "unrelated-tripod", source, accessory_model, accessory=True
    )
    target_spare = _device(
        "target-spare", target, accessory_model, accessory=True
    )
    rental = _rental(main, source, flags=True)
    received_child = _rental(received, source, parent=rental)
    not_received_child = _rental(not_received, source, parent=rental)

    other_main = _device("other-main", source, main_model)
    other_rental = _rental(other_main, source)
    other_child = _rental(unrelated, source, parent=other_rental)

    future = None
    future_child = None
    if with_future:
        future = _rental(main, source, future=True)
        future_child = _rental(received, source, parent=future, future=True)
    db.session.commit()
    return {
        "source": source.id,
        "target": target.id,
        "main": main.id,
        "received": received.id,
        "not_received": not_received.id,
        "unrelated": unrelated.id,
        "target_spare": target_spare.id,
        "rental": rental.id,
        "received_child": received_child.id,
        "not_received_child": not_received_child.id,
        "other_rental": other_rental.id,
        "other_child": other_child.id,
        "future": future.id if future else None,
        "future_child": future_child.id if future_child else None,
    }


def _configure_child_only_candidate(case, *, overlaps_future):
    db.session.get(Device, case["main"]).warehouse_id = case["target"]
    db.session.get(Device, case["unrelated"]).lifecycle_status = "retired"
    if overlaps_future:
        start = date.today() + timedelta(days=9)
        end = date.today() + timedelta(days=11)
    else:
        start = date.today() - timedelta(days=2)
        end = date.today()
    for rental_id in (
        case["rental"],
        case["received_child"],
        case["not_received_child"],
    ):
        rental = db.session.get(Rental, rental_id)
        rental.start_date = start
        rental.end_date = end
        rental.status = "returned"
    db.session.commit()


def _assert_no_inspection_writes():
    assert InspectionRecord.query.count() == 0
    assert InspectionCheckItem.query.count() == 0
    assert AuditLog.query.count() == 0


def test_missing_receiving_warehouse_uses_main_rental_warehouse(
    client, app
):
    with app.app_context():
        case = _seed_case()
        db.session.get(Device, case["main"]).warehouse_id = case["target"]
        db.session.commit()

    response = client.post("/api/inspections", json=_payload(case))

    assert response.status_code == 201
    body = response.get_json()["data"]
    impact = body["warehouse_impacts"]
    assert impact["primary_device_id"] == case["main"]
    assert impact["moved_device_ids"] == [case["main"]]
    assert impact["target_warehouse_id"] == (
        case["source"]
    )
    assert impact["token"]
    with app.app_context():
        assert db.session.get(Device, case["main"]).warehouse_id == (
            case["source"]
        )
        assert db.session.get(Device, case["received"]).warehouse_id == (
            case["source"]
        )
        assert db.session.get(Rental, case["rental"]).warehouse_id == (
            case["source"]
        )


def test_selected_warehouse_moves_main_and_only_received_actual_children(
    client, app
):
    with app.app_context():
        case = _seed_case(with_future=True)

    response = client.post(
        "/api/inspections",
        json=_payload(
            case,
            receiving_warehouse_id=case["target"],
            received_device_ids=[case["received"]],
        ),
    )

    assert response.status_code == 201
    body = response.get_json()["data"]
    assert body["rental"]["includes_handle"] is True
    assert body["rental"]["includes_lens_mount"] is True
    impact = body["warehouse_impacts"]
    assert impact["primary_device_id"] == case["main"]
    assert impact["moved_device_ids"] == sorted(
        [case["main"], case["received"]]
    )
    assert impact["token"]
    assert impact["blocked"] == []
    assert impact["shortages"] == []
    assert impact["manual"] == []
    assert impact["auto_fixable"] == [{
        "rental_id": case["future"],
        "fulfillment_warehouse_id": case["target"],
        "replacements": [],
    }]

    with app.app_context():
        assert db.session.get(Device, case["main"]).warehouse_id == (
            case["target"]
        )
        assert db.session.get(Device, case["received"]).warehouse_id == (
            case["target"]
        )
        assert db.session.get(Device, case["not_received"]).warehouse_id == (
            case["source"]
        )
        assert Device.query.count() == 6
        for rental_id in [
            case["rental"],
            case["received_child"],
            case["not_received_child"],
            case["future"],
            case["future_child"],
        ]:
            assert db.session.get(Rental, rental_id).warehouse_id == (
                case["source"]
            )
        assert db.session.get(
            Rental, case["future_child"]
        ).device_id == case["received"]
        audit = AuditLog.query.one()
        assert audit.action == "inspection_warehouse_received"
        assert audit.details["moves"] == [
            {
                "device_id": case["main"],
                "old_warehouse_id": case["source"],
                "new_warehouse_id": case["target"],
            },
            {
                "device_id": case["received"],
                "old_warehouse_id": case["source"],
                "new_warehouse_id": case["target"],
            },
        ]

    repaired = client.post(
        f"/api/devices/{case['main']}/move",
        json={"token": impact["token"]},
    )
    assert repaired.status_code == 200
    with app.app_context():
        assert db.session.get(Device, case["main"]).warehouse_id == (
            case["target"]
        )
        assert db.session.get(Device, case["received"]).warehouse_id == (
            case["target"]
        )
        assert db.session.get(Rental, case["future"]).warehouse_id == (
            case["target"]
        )
        future_child = db.session.get(Rental, case["future_child"])
        assert (future_child.device_id, future_child.warehouse_id) == (
            case["received"], case["target"]
        )
        assert AuditLog.query.filter_by(
            action="warehouse_receipt_rentals_repaired"
        ).count() == 1

    replay = client.post(
        f"/api/devices/{case['main']}/move",
        json={"token": impact["token"]},
    )
    assert replay.status_code == 409


def test_child_only_receipt_repairs_moved_children_in_fulfillment_warehouse(
    client, app
):
    with app.app_context():
        case = _seed_case(with_future=True)
        db.session.get(Device, case["main"]).warehouse_id = case["target"]
        db.session.commit()

    inspection = client.post(
        "/api/inspections",
        json=_payload(
            case,
            receiving_warehouse_id=case["target"],
            received_device_ids=[case["received"]],
        ),
    )

    assert inspection.status_code == 201
    impact = inspection.get_json()["data"]["warehouse_impacts"]
    assert impact["moved_device_ids"] == [case["received"]]
    assert impact["auto_fixable"] == [{
        "rental_id": case["future"],
        "fulfillment_warehouse_id": case["source"],
        "replacements": [{
            "child_rental_id": case["future_child"],
            "old_device_id": case["received"],
            "new_device_id": case["not_received"],
        }],
    }]

    repaired = client.post(
        f"/api/devices/{case['main']}/move",
        json={"token": impact["token"]},
    )
    assert repaired.status_code == 200
    with app.app_context():
        assert db.session.get(Rental, case["future"]).warehouse_id == (
            case["source"]
        )
        child = db.session.get(Rental, case["future_child"])
        assert (child.device_id, child.warehouse_id) == (
            case["not_received"], case["source"]
        )
        assert db.session.get(Device, case["main"]).warehouse_id == (
            case["target"]
        )
        assert db.session.get(Device, case["received"]).warehouse_id == (
            case["target"]
        )


@pytest.mark.parametrize("received_key", ["unrelated", "missing", "other"])
def test_received_ids_outside_the_main_rental_are_rejected_without_writes(
    client, app, received_key
):
    with app.app_context():
        case = _seed_case()
        received_id = {
            "unrelated": case["target_spare"],
            "missing": 987654321,
            "other": case["unrelated"],
        }[received_key]
        before = {
            device.id: device.warehouse_id
            for device in Device.query.order_by(Device.id).all()
        }

    response = client.post(
        "/api/inspections",
        json=_payload(
            case,
            receiving_warehouse_id=case["target"],
            received_device_ids=[received_id],
        ),
    )

    assert response.status_code == 400
    with app.app_context():
        _assert_no_inspection_writes()
        assert {
            device.id: device.warehouse_id
            for device in Device.query.order_by(Device.id).all()
        } == before


@pytest.mark.parametrize(
    "received_ids",
    [True, "1", [True], [0], [-1], ["1"], [{}]],
)
def test_malformed_received_ids_are_stable_400_and_write_nothing(
    client, app, received_ids
):
    with app.app_context():
        case = _seed_case()

    response = client.post(
        "/api/inspections",
        json=_payload(case, received_device_ids=received_ids),
    )

    assert response.status_code == 400
    with app.app_context():
        _assert_no_inspection_writes()


@pytest.mark.parametrize(
    "payload_change",
    [
        {"rental_id": -1},
        {"device_id": -1},
        {"receiving_warehouse_id": 987654321},
        {"receiving_warehouse_id": True},
    ],
)
def test_invalid_rental_device_or_warehouse_is_400_without_writes(
    client, app, payload_change
):
    with app.app_context():
        case = _seed_case()

    response = client.post(
        "/api/inspections", json=_payload(case, **payload_change)
    )

    assert response.status_code == 400
    with app.app_context():
        _assert_no_inspection_writes()


def test_device_must_be_the_main_device_of_a_main_rental(client, app):
    with app.app_context():
        case = _seed_case()

    wrong_device = client.post(
        "/api/inspections",
        json=_payload(case, device_id=case["received"]),
    )
    child_rental = client.post(
        "/api/inspections",
        json=_payload(case, rental_id=case["received_child"]),
    )

    assert wrong_device.status_code == 400
    assert child_rental.status_code == 400
    with app.app_context():
        _assert_no_inspection_writes()


@pytest.mark.parametrize(
    "check_items",
    [
        None,
        "invalid",
        [None],
        [{}],
        [{"name": "", "is_checked": True, "order": 1}],
        [{"name": "x", "is_checked": "yes", "order": 1}],
        [{"name": "x", "is_checked": True, "order": True}],
        [],
        [{"name": "x", "is_checked": True, "order": -1}],
        [{"name": "x", "is_checked": True, "order": 2147483648}],
        [{"name": "x"}],
        [{"name": "x", "is_checked": True}],
        [{"name": "x", "order": 1}],
        [{"name": "x" * 1021, "is_checked": True, "order": 1}],
    ],
)
def test_malformed_check_items_roll_back_everything(client, app, check_items):
    with app.app_context():
        case = _seed_case()

    response = client.post(
        "/api/inspections",
        json=_payload(
            case,
            receiving_warehouse_id=case["target"],
            received_device_ids=[case["received"]],
            check_items=check_items,
        ),
    )

    assert response.status_code == 400
    assert "INSERT INTO" not in str(response.get_json())
    assert "parameters" not in str(response.get_json())
    with app.app_context():
        _assert_no_inspection_writes()
        assert db.session.get(Device, case["main"]).warehouse_id == (
            case["source"]
        )
        assert db.session.get(Device, case["received"]).warehouse_id == (
            case["source"]
        )


def test_database_failure_rolls_back_inspection_items_devices_and_audit(
    client, app
):
    with app.app_context():
        case = _seed_case()

    def fail_audit_insert(_mapper, _connection, _target):
        raise RuntimeError("database detail must not leak")

    event.listen(AuditLog, "before_insert", fail_audit_insert)
    try:
        response = client.post(
            "/api/inspections",
            json=_payload(
                case,
                receiving_warehouse_id=case["target"],
                received_device_ids=[case["received"]],
            ),
        )
    finally:
        event.remove(AuditLog, "before_insert", fail_audit_insert)

    assert response.status_code == 500
    assert "database detail" not in str(response.get_json())
    with app.app_context():
        _assert_no_inspection_writes()
        assert db.session.get(Device, case["main"]).warehouse_id == (
            case["source"]
        )
        assert db.session.get(Device, case["received"]).warehouse_id == (
            case["source"]
        )


def test_preview_failure_happens_before_any_write(client, app, monkeypatch):
    with app.app_context():
        case = _seed_case()

    def fail_preview(
        _device_id, _moved_ids, _warehouse_id, _excluded_main_rental_id
    ):
        raise RuntimeError("preview unavailable")

    monkeypatch.setattr(
        WarehouseMovementService,
        "preview_receipt_repair",
        fail_preview,
    )
    response = client.post(
        "/api/inspections",
        json=_payload(case, receiving_warehouse_id=case["target"]),
    )

    assert response.status_code == 500
    assert "preview unavailable" not in str(response.get_json())
    with app.app_context():
        _assert_no_inspection_writes()
        assert db.session.get(Device, case["main"]).warehouse_id == (
            case["source"]
        )


def test_concurrent_receipts_serialize_warehouse_changes(app):
    with app.app_context():
        if db.engine.dialect.name != "mysql":
            pytest.skip("warehouse concurrency probe requires MariaDB")
        case = _seed_case()
        db.session.remove()

    barrier = Barrier(2)
    outcomes = []

    def submit():
        with app.test_client() as thread_client:
            barrier.wait()
            response = thread_client.post(
                "/api/inspections",
                json=_payload(
                    case,
                    receiving_warehouse_id=case["target"],
                ),
            )
            outcomes.append(
                (response.status_code, response.get_json().get("data"))
            )

    threads = [Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert sorted(status for status, _data in outcomes) == [201, 201]
    has_impact = sorted(
        data["warehouse_impacts"] is not None
        for _status, data in outcomes
    )
    assert has_impact == [False, True]
    with app.app_context():
        assert db.session.get(Device, case["main"]).warehouse_id == (
            case["target"]
        )
        assert InspectionRecord.query.count() == 2
        assert InspectionCheckItem.query.count() == 2
        assert AuditLog.query.filter_by(
            action="inspection_warehouse_received"
        ).count() == 2


def test_aggregate_receipt_shortage_leaves_future_group_unchanged(
    client, app
):
    with app.app_context():
        case = _seed_case(with_future=True)
        received_model_id = db.session.get(
            Device, case["received"]
        ).model_id
        db.session.delete(db.session.get(Device, case["target_spare"]))
        db.session.commit()

    response = client.post(
        "/api/inspections",
        json=_payload(case, receiving_warehouse_id=case["target"]),
    )

    assert response.status_code == 201
    impact = response.get_json()["data"]["warehouse_impacts"]
    assert impact["auto_fixable"] == []
    assert impact["manual"] == []
    assert impact["shortages"] == [{
        "rental_id": case["future"],
        "code": "NO_AVAILABLE_REPLACEMENT",
        "missing": [{
            "child_rental_id": case["future_child"],
            "model_id": received_model_id,
            "model": "inspection-tripod",
        }],
    }]
    assert impact["token"]

    executed = client.post(
        f"/api/devices/{case['main']}/move",
        json={"token": impact["token"]},
    )
    assert executed.status_code == 200
    with app.app_context():
        assert db.session.get(Rental, case["future"]).warehouse_id == (
            case["source"]
        )
        child = db.session.get(Rental, case["future_child"])
        assert (child.device_id, child.warehouse_id) == (
            case["received"], case["source"]
        )

    replay = client.post(
        f"/api/devices/{case['main']}/move",
        json={"token": impact["token"]},
    )
    assert replay.status_code == 409


def test_receipt_repair_excludes_inspected_group_and_survives_completion(
    client, app
):
    with app.app_context():
        case = _seed_case(with_future=True)
        current = db.session.get(Rental, case["rental"])
        current.start_date = date.today() - timedelta(days=1)
        current.end_date = date.today()
        current.status = "not_shipped"
        db.session.commit()

    inspection = client.post(
        "/api/inspections",
        json=_payload(
            case,
            receiving_warehouse_id=case["target"],
            received_device_ids=[case["received"]],
        ),
    )

    assert inspection.status_code == 201
    impact = inspection.get_json()["data"]["warehouse_impacts"]
    assert impact["auto_fixable"] == [{
        "rental_id": case["future"],
        "fulfillment_warehouse_id": case["target"],
        "replacements": [],
    }]
    assert impact["blocked"] == []
    assert impact["shortages"] == []
    assert impact["manual"] == []

    with app.app_context():
        payload = WarehouseMovementService._load_token(impact["token"])
        assert payload["excluded_main_rental_id"] == case["rental"]
        excluded_ids = {
            case["rental"],
            case["received_child"],
            case["not_received_child"],
        }
        assert excluded_ids.isdisjoint(payload["related_rental_ids"])
        assert excluded_ids.isdisjoint(
            row["id"] for row in payload["snapshot"]["rentals"]
        )

        current_rows = [
            db.session.get(Rental, rental_id)
            for rental_id in sorted(excluded_ids)
        ]
        before = {
            row.id: (row.device_id, row.warehouse_id)
            for row in current_rows
        }
        current = db.session.get(Rental, case["rental"])
        current.status = "completed"
        db.session.commit()

    repaired = client.post(
        f"/api/devices/{case['main']}/move",
        json={"token": impact["token"]},
    )

    assert repaired.status_code == 200
    with app.app_context():
        assert {
            rental_id: (
                db.session.get(Rental, rental_id).device_id,
                db.session.get(Rental, rental_id).warehouse_id,
            )
            for rental_id in sorted(before)
        } == before
        assert db.session.get(Rental, case["future"]).warehouse_id == (
            case["target"]
        )
        future_child = db.session.get(Rental, case["future_child"])
        assert (future_child.device_id, future_child.warehouse_id) == (
            case["received"], case["target"]
        )


def test_returned_inspected_group_is_not_reported_as_manual(client, app):
    with app.app_context():
        case = _seed_case(with_future=True)
        current = db.session.get(Rental, case["rental"])
        current.start_date = date.today() - timedelta(days=2)
        current.end_date = date.today()
        current.status = "returned"
        db.session.commit()

    inspection = client.post(
        "/api/inspections",
        json=_payload(case, receiving_warehouse_id=case["target"]),
    )

    assert inspection.status_code == 201
    impact = inspection.get_json()["data"]["warehouse_impacts"]
    assert impact["manual"] == []
    assert {
        row["rental_id"] for key in (
            "auto_fixable", "blocked", "shortages", "manual"
        ) for row in impact[key]
    } == {case["future"]}


def test_child_only_receipt_keeps_excluded_overlapping_candidate_occupied(
    client, app
):
    with app.app_context():
        case = _seed_case(with_future=True)
        _configure_child_only_candidate(case, overlaps_future=True)
        model = db.session.get(Device, case["not_received"]).model
        model_id = db.session.get(Device, case["not_received"]).model_id

    inspection = client.post(
        "/api/inspections",
        json=_payload(
            case,
            receiving_warehouse_id=case["target"],
            received_device_ids=[case["received"]],
        ),
    )

    assert inspection.status_code == 201
    impact = inspection.get_json()["data"]["warehouse_impacts"]
    assert impact["moved_device_ids"] == [case["received"]]
    assert impact["auto_fixable"] == []
    assert impact["manual"] == []
    assert impact["shortages"] == [{
        "rental_id": case["future"],
        "code": "NO_AVAILABLE_REPLACEMENT",
        "missing": [{
            "child_rental_id": case["future_child"],
            "model_id": model_id,
            "model": model,
        }],
    }]
    excluded_ids = {
        case["rental"],
        case["received_child"],
        case["not_received_child"],
    }
    with app.app_context():
        payload = WarehouseMovementService._load_token(impact["token"])
        assert excluded_ids.isdisjoint(payload["related_rental_ids"])
        assert excluded_ids.isdisjoint(
            row["id"] for row in payload["snapshot"]["rentals"]
        )

    executed = client.post(
        f"/api/devices/{case['main']}/move",
        json={"token": impact["token"]},
    )

    assert executed.status_code == 200
    executed_impact = executed.get_json()["data"]
    assert executed_impact["shortages"] == impact["shortages"]
    assert executed_impact["auto_fixable"] == impact["auto_fixable"]
    with app.app_context():
        assert db.session.get(
            Rental, case["not_received_child"]
        ).device_id == case["not_received"]
        assert db.session.get(
            Rental, case["future_child"]
        ).device_id == case["received"]


def test_receipt_repair_keeps_completed_excluded_group_as_occupancy(
    client, app
):
    with app.app_context():
        case = _seed_case(with_future=True)
        _configure_child_only_candidate(case, overlaps_future=True)
        candidate = db.session.get(Device, case["not_received"])
        model = candidate.model
        model_id = candidate.model_id
        main_model = db.session.get(
            DeviceModel,
            db.session.get(Device, case["main"]).model_id,
        )
        source = db.session.get(Warehouse, case["source"])
        later_main_device = _device(
            "later-main", source, main_model
        )
        later_main = _rental(later_main_device, source, future=True)
        later_child = _rental(
            db.session.get(Device, case["received"]),
            source,
            parent=later_main,
            future=True,
        )
        later_main.start_date = date.today() + timedelta(days=20)
        later_main.end_date = date.today() + timedelta(days=22)
        later_child.start_date = later_main.start_date
        later_child.end_date = later_main.end_date
        later_main_id = later_main.id
        later_child_id = later_child.id
        db.session.commit()

    inspection = client.post(
        "/api/inspections",
        json=_payload(
            case,
            receiving_warehouse_id=case["target"],
            received_device_ids=[case["received"]],
        ),
    )

    assert inspection.status_code == 201
    impact = inspection.get_json()["data"]["warehouse_impacts"]
    assert impact["moved_device_ids"] == [case["received"]]
    assert impact["auto_fixable"] == [{
        "rental_id": later_main_id,
        "fulfillment_warehouse_id": case["source"],
        "replacements": [{
            "child_rental_id": later_child_id,
            "old_device_id": case["received"],
            "new_device_id": case["not_received"],
        }],
    }]
    assert impact["manual"] == []
    assert impact["shortages"] == [{
        "rental_id": case["future"],
        "code": "NO_AVAILABLE_REPLACEMENT",
        "missing": [{
            "child_rental_id": case["future_child"],
            "model_id": model_id,
            "model": model,
        }],
    }]
    excluded_ids = {
        case["rental"],
        case["received_child"],
        case["not_received_child"],
    }
    with app.app_context():
        payload = WarehouseMovementService._load_token(impact["token"])
        assert excluded_ids.isdisjoint(payload["related_rental_ids"])
        assert excluded_ids.isdisjoint(
            row["id"] for row in payload["snapshot"]["rentals"]
        )
        for rental_id in excluded_ids:
            db.session.get(Rental, rental_id).status = "completed"
        db.session.commit()

    executed = client.post(
        f"/api/devices/{case['main']}/move",
        json={"token": impact["token"]},
    )

    assert executed.status_code == 200
    executed_impact = executed.get_json()["data"]
    assert executed_impact["shortages"] == impact["shortages"]
    assert executed_impact["auto_fixable"] == impact["auto_fixable"]
    with app.app_context():
        assert db.session.get(
            Rental, case["not_received_child"]
        ).device_id == case["not_received"]
        assert db.session.get(
            Rental, case["future_child"]
        ).device_id == case["received"]
        later = db.session.get(Rental, later_main_id)
        assert later.warehouse_id == case["source"]
        assert db.session.get(
            Rental, later_child_id
        ).device_id == case["not_received"]


def test_child_only_receipt_can_reuse_non_overlapping_excluded_candidate(
    client, app
):
    with app.app_context():
        case = _seed_case(with_future=True)
        _configure_child_only_candidate(case, overlaps_future=False)

    inspection = client.post(
        "/api/inspections",
        json=_payload(
            case,
            receiving_warehouse_id=case["target"],
            received_device_ids=[case["received"]],
        ),
    )

    assert inspection.status_code == 201
    impact = inspection.get_json()["data"]["warehouse_impacts"]
    assert impact["shortages"] == []
    assert impact["auto_fixable"] == [{
        "rental_id": case["future"],
        "fulfillment_warehouse_id": case["source"],
        "replacements": [{
            "child_rental_id": case["future_child"],
            "old_device_id": case["received"],
            "new_device_id": case["not_received"],
        }],
    }]

    executed = client.post(
        f"/api/devices/{case['main']}/move",
        json={"token": impact["token"]},
    )

    assert executed.status_code == 200
    with app.app_context():
        assert db.session.get(
            Rental, case["not_received_child"]
        ).device_id == case["not_received"]
        assert db.session.get(
            Rental, case["future_child"]
        ).device_id == case["not_received"]


@pytest.mark.parametrize(
    ("manual_kind", "expected_reason"),
    [("tracking", "TRACKING_EXISTS"), ("shipped", "ALREADY_SHIPPED")],
)
def test_aggregate_receipt_marks_locked_future_groups_manual(
    client, app, manual_kind, expected_reason
):
    with app.app_context():
        case = _seed_case(with_future=True)
        future = db.session.get(Rental, case["future"])
        if manual_kind == "tracking":
            future.ship_out_tracking_no = "SF-RECEIPT-LOCKED"
        else:
            future.status = "shipped"
        db.session.commit()

    response = client.post(
        "/api/inspections",
        json=_payload(case, receiving_warehouse_id=case["target"]),
    )

    assert response.status_code == 201
    impact = response.get_json()["data"]["warehouse_impacts"]
    assert impact["auto_fixable"] == []
    assert impact["shortages"] == []
    assert impact["manual"] == [{
        "rental_id": case["future"],
        "reason": expected_reason,
    }]


def test_concurrent_aggregate_repair_executes_once_and_other_is_stale(
    client, app
):
    with app.app_context():
        if db.engine.dialect.name != "mysql":
            pytest.skip("receipt repair concurrency requires MariaDB")
        case = _seed_case(with_future=True)

    inspection = client.post(
        "/api/inspections",
        json=_payload(
            case,
            receiving_warehouse_id=case["target"],
            received_device_ids=[case["received"]],
        ),
    )
    token = inspection.get_json()["data"]["warehouse_impacts"]["token"]
    barrier = Barrier(2)
    outcomes = []

    def execute():
        with app.test_client() as thread_client:
            barrier.wait()
            response = thread_client.post(
                f"/api/devices/{case['main']}/move",
                json={"token": token},
            )
            outcomes.append(response.status_code)

    threads = [Thread(target=execute) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert sorted(outcomes) == [200, 409]
    with app.app_context():
        assert db.session.get(Rental, case["future"]).warehouse_id == (
            case["target"]
        )
        assert AuditLog.query.filter_by(
            action="warehouse_receipt_rentals_repaired"
        ).count() == 1
