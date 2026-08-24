"""Warehouse movement previews and repairs."""

import os
from datetime import date, datetime, time, timedelta
from threading import Barrier, Thread

import pytest

from app import create_app, db
from app.models.audit_log import AuditLog
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental
from app.models.warehouse import Warehouse
from app.services.warehouse_movement_service import (
    StaleMovementPreviewError,
    WarehouseMovementService,
)
from app.tenant_context import bind_tenant, reset_tenant
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

        class MovementConfig(TestingConfig):
            SQLALCHEMY_DATABASE_URI = parsed.render_as_string(
                hide_password=False
            )
            SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

        application = create_app(MovementConfig)
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
    warehouse = Warehouse(
        province=f"{name}省", city=f"{name}市", name=f"{name}仓"
    )
    db.session.add(warehouse)
    db.session.flush()
    return warehouse


def _model(name, *, accessory):
    model = DeviceModel(
        name=name,
        display_name=name,
        is_accessory=accessory,
        is_active=True,
    )
    db.session.add(model)
    db.session.flush()
    return model


def _device(name, warehouse, model=None, *, accessory=False, legacy=None):
    device = Device(
        name=name,
        serial_number=f"SN-{name}",
        model=legacy if legacy is not None else model.name,
        model_id=model.id if model is not None else None,
        is_accessory=accessory,
        lifecycle_status="active",
        warehouse_id=warehouse.id,
    )
    db.session.add(device)
    db.session.flush()
    return device


def _rental(
    main_device,
    warehouse,
    *accessories,
    start_in=10,
    duration=3,
    status="not_shipped",
    tracking=None,
):
    start = date.today() + timedelta(days=start_in)
    end = start + timedelta(days=duration)
    ship_out = datetime.combine(start - timedelta(days=2), time(19))
    ship_in = datetime.combine(end + timedelta(days=2), time(12))
    main = Rental(
        device_id=main_device.id,
        warehouse_id=warehouse.id,
        start_date=start,
        end_date=end,
        ship_out_time=ship_out,
        ship_in_time=ship_in,
        customer_name=f"客户-{main_device.name}-{start_in}",
        status=status,
        ship_out_tracking_no=tracking,
    )
    db.session.add(main)
    db.session.flush()
    children = []
    for accessory in accessories:
        child = Rental(
            device_id=accessory.id,
            warehouse_id=warehouse.id,
            parent_rental_id=main.id,
            start_date=start,
            end_date=end,
            ship_out_time=ship_out,
            ship_in_time=ship_in,
            customer_name=main.customer_name,
            status=status,
            ship_out_tracking_no=tracking,
        )
        db.session.add(child)
        children.append(child)
    db.session.flush()
    return main, children


def _group_snapshot(main_id):
    rows = Rental.query.filter(
        db.or_(Rental.id == main_id, Rental.parent_rental_id == main_id)
    ).order_by(Rental.id).all()
    return [
        (
            row.id,
            row.device_id,
            row.warehouse_id,
            row.parent_rental_id,
            row.start_date,
            row.end_date,
            row.ship_out_time,
            row.ship_in_time,
            row.status,
            row.customer_name,
            row.updated_at,
        )
        for row in rows
    ]


def _seed_main_move():
    source = _warehouse("深圳")
    target = _warehouse("杭州")
    main_model = _model("movement-camera", accessory=False)
    accessory_model = _model("movement-tripod", accessory=True)
    main_device = _device("main-source", source, main_model)
    old_accessory = _device(
        "tripod-source", source, accessory_model, accessory=True
    )
    replacement = _device(
        "tripod-target", target, accessory_model, accessory=True
    )
    main, children = _rental(
        main_device, source, old_accessory, start_in=12
    )
    db.session.commit()
    return {
        "source": source.id,
        "target": target.id,
        "main_device": main_device.id,
        "old_accessory": old_accessory.id,
        "replacement": replacement.id,
        "rental": main.id,
        "child": children[0].id,
    }


def test_main_device_move_follows_target_and_replaces_accessories(app):
    with app.app_context():
        case = _seed_main_move()
        preview = WarehouseMovementService.preview(
            case["main_device"], case["target"]
        )

        assert preview["blocked"] == []
        assert preview["shortages"] == []
        assert preview["manual"] == []
        assert preview["auto_fixable"] == [{
            "rental_id": case["rental"],
            "fulfillment_warehouse_id": case["target"],
            "replacements": [{
                "child_rental_id": case["child"],
                "old_device_id": case["old_accessory"],
                "new_device_id": case["replacement"],
            }],
        }]
        assert db.session.get(Device, case["main_device"]).warehouse_id == (
            case["source"]
        )

        result = WarehouseMovementService.execute(preview["token"])

        assert result["auto_fixable"] == preview["auto_fixable"]
        assert db.session.get(Device, case["main_device"]).warehouse_id == (
            case["target"]
        )
        assert db.session.get(Rental, case["rental"]).warehouse_id == (
            case["target"]
        )
        child = db.session.get(Rental, case["child"])
        assert (child.warehouse_id, child.device_id) == (
            case["target"], case["replacement"]
        )
        audit = AuditLog.query.filter_by(
            action="warehouse_device_moved"
        ).one()
        assert audit.details == {
            "old_warehouse_id": case["source"],
            "new_warehouse_id": case["target"],
            "replacements": [{
                "rental_id": case["rental"],
                "child_rental_id": case["child"],
                "old_device_id": case["old_accessory"],
                "new_device_id": case["replacement"],
            }],
        }


def test_legacy_model_matching_is_normalized(app):
    with app.app_context():
        source = _warehouse("深圳")
        target = _warehouse("杭州")
        main_model = _model("legacy-main", accessory=False)
        main_device = _device("legacy-main-1", source, main_model)
        old_accessory = _device(
            "legacy-old", source, accessory=True, legacy="  TriPod-X  "
        )
        replacement = _device(
            "legacy-new", target, accessory=True, legacy="tripod-x"
        )
        _main, children = _rental(main_device, source, old_accessory)
        db.session.commit()

        preview = WarehouseMovementService.preview(
            main_device.id, target.id
        )

        assert preview["auto_fixable"][0]["replacements"] == [{
            "child_rental_id": children[0].id,
            "old_device_id": old_accessory.id,
            "new_device_id": replacement.id,
        }]
        WarehouseMovementService.execute(preview["token"])
        assert db.session.get(Rental, children[0].id).device_id == (
            replacement.id
        )


def test_accessory_move_keeps_fulfillment_warehouse_and_replaces_child(app):
    with app.app_context():
        source = _warehouse("深圳")
        target = _warehouse("杭州")
        main_model = _model("accessory-main", accessory=False)
        accessory_model = _model("accessory-tripod", accessory=True)
        main_device = _device("accessory-main-1", source, main_model)
        moving = _device(
            "moving-tripod", source, accessory_model, accessory=True
        )
        spare = _device("spare-tripod", source, accessory_model, accessory=True)
        main, children = _rental(main_device, source, moving)
        db.session.commit()

        preview = WarehouseMovementService.preview(moving.id, target.id)
        WarehouseMovementService.execute(preview["token"])

        assert db.session.get(Device, moving.id).warehouse_id == target.id
        assert db.session.get(Rental, main.id).warehouse_id == source.id
        child = db.session.get(Rental, children[0].id)
        assert (child.warehouse_id, child.device_id) == (
            source.id, spare.id
        )


def test_nonoverlapping_rentals_reuse_one_replacement(app):
    with app.app_context():
        source = _warehouse("深圳")
        target = _warehouse("杭州")
        main_model = _model("reuse-main", accessory=False)
        accessory_model = _model("reuse-tripod", accessory=True)
        first_main = _device("reuse-main-1", source, main_model)
        second_main = _device("reuse-main-2", source, main_model)
        moving = _device("reuse-moving", source, accessory_model, accessory=True)
        spare = _device("reuse-spare", source, accessory_model, accessory=True)
        first, first_children = _rental(
            first_main, source, moving, start_in=10
        )
        second, second_children = _rental(
            second_main, source, moving, start_in=25
        )
        db.session.commit()

        preview = WarehouseMovementService.preview(moving.id, target.id)

        assert {row["rental_id"] for row in preview["auto_fixable"]} == {
            first.id, second.id
        }
        assert preview["shortages"] == []
        assert {
            row["replacements"][0]["new_device_id"]
            for row in preview["auto_fixable"]
        } == {spare.id}
        WarehouseMovementService.execute(preview["token"])
        assert {
            db.session.get(Rental, first_children[0].id).device_id,
            db.session.get(Rental, second_children[0].id).device_id,
        } == {spare.id}


def test_shortage_rental_is_unchanged_while_other_repairs_commit(app):
    with app.app_context():
        source = _warehouse("深圳")
        target = _warehouse("杭州")
        main_model = _model("short-main", accessory=False)
        accessory_model = _model("short-tripod", accessory=True)
        first_main = _device("short-main-1", source, main_model)
        second_main = _device("short-main-2", source, main_model)
        moving = _device("short-moving", source, accessory_model, accessory=True)
        spare = _device("short-spare", source, accessory_model, accessory=True)
        first, first_children = _rental(
            first_main, source, moving, start_in=10, duration=5
        )
        second, second_children = _rental(
            second_main, source, moving, start_in=12, duration=5
        )
        db.session.commit()
        before_shortage = _group_snapshot(second.id)

        preview = WarehouseMovementService.preview(moving.id, target.id)

        assert [row["rental_id"] for row in preview["auto_fixable"]] == [
            first.id
        ]
        assert preview["shortages"] == [{
            "rental_id": second.id,
            "code": "NO_AVAILABLE_REPLACEMENT",
            "missing": [{
                "child_rental_id": second_children[0].id,
                "model_id": accessory_model.id,
                "model": accessory_model.name,
            }],
        }]

        WarehouseMovementService.execute(preview["token"])

        assert db.session.get(Device, moving.id).warehouse_id == target.id
        assert db.session.get(Rental, first_children[0].id).device_id == spare.id
        assert _group_snapshot(second.id) == before_shortage


def test_existing_overlap_makes_candidate_unavailable(app):
    with app.app_context():
        source = _warehouse("深圳")
        target = _warehouse("杭州")
        main_model = _model("occupied-main", accessory=False)
        accessory_model = _model("occupied-tripod", accessory=True)
        moving_main = _device("occupied-main-1", source, main_model)
        existing_main = _device("occupied-main-2", source, main_model)
        moving = _device("occupied-moving", source, accessory_model, accessory=True)
        spare = _device("occupied-spare", source, accessory_model, accessory=True)
        moving_rental, moving_children = _rental(
            moving_main, source, moving, start_in=10, duration=4
        )
        _rental(existing_main, source, spare, start_in=11, duration=2)
        db.session.commit()

        preview = WarehouseMovementService.preview(moving.id, target.id)

        assert preview["auto_fixable"] == []
        assert preview["shortages"][0]["rental_id"] == moving_rental.id
        WarehouseMovementService.execute(preview["token"])
        assert db.session.get(Rental, moving_children[0].id).device_id == moving.id


@pytest.mark.parametrize(
    ("legacy_model", "expected_code"),
    [("", "MODEL_UNKNOWN"), ("tripod-without-spare", "NO_AVAILABLE_REPLACEMENT")],
)
def test_missing_model_or_replacement_is_explicit_shortage(
    app, legacy_model, expected_code
):
    with app.app_context():
        source = _warehouse("深圳")
        target = _warehouse("杭州")
        main_model = _model(f"missing-main-{expected_code}", accessory=False)
        main_device = _device(
            f"missing-main-device-{expected_code}", source, main_model
        )
        moving = _device(
            f"missing-moving-{expected_code}",
            source,
            accessory=True,
            legacy=legacy_model,
        )
        main, children = _rental(main_device, source, moving)
        db.session.commit()

        preview = WarehouseMovementService.preview(moving.id, target.id)

        assert preview["shortages"][0]["rental_id"] == main.id
        assert preview["shortages"][0]["code"] == expected_code
        assert preview["shortages"][0]["missing"][0][
            "child_rental_id"
        ] == children[0].id


def test_tracking_or_shipped_rentals_require_manual_repair(app):
    with app.app_context():
        source = _warehouse("深圳")
        target = _warehouse("杭州")
        main_model = _model("manual-main", accessory=False)
        moving = _device("manual-moving", source, main_model)
        tracking_rental, _ = _rental(
            moving, source, start_in=10, tracking="SF-LOCKED"
        )
        shipped_rental, _ = _rental(
            moving, source, start_in=30, status="shipped"
        )
        db.session.commit()
        tracking_before = _group_snapshot(tracking_rental.id)
        shipped_before = _group_snapshot(shipped_rental.id)

        preview = WarehouseMovementService.preview(moving.id, target.id)

        assert preview["auto_fixable"] == []
        assert preview["shortages"] == []
        assert preview["manual"] == [
            {"rental_id": tracking_rental.id, "reason": "TRACKING_EXISTS"},
            {"rental_id": shipped_rental.id, "reason": "ALREADY_SHIPPED"},
        ]
        WarehouseMovementService.execute(preview["token"])
        assert db.session.get(Device, moving.id).warehouse_id == target.id
        assert _group_snapshot(tracking_rental.id) == tracking_before
        assert _group_snapshot(shipped_rental.id) == shipped_before


@pytest.mark.parametrize(
    "changed_resource",
    ["rental", "rental_updated_at", "device", "warehouse", "assignment"],
)
def test_any_related_change_makes_preview_stale(app, changed_resource):
    with app.app_context():
        case = _seed_main_move()
        extra = _device(
            f"extra-{changed_resource}",
            db.session.get(Warehouse, case["source"]),
            db.session.get(Device, case["old_accessory"]).device_model,
            accessory=True,
        )
        db.session.commit()
        preview = WarehouseMovementService.preview(
            case["main_device"], case["target"]
        )

        if changed_resource == "rental":
            db.session.get(Rental, case["rental"]).customer_name = "已变化"
        elif changed_resource == "rental_updated_at":
            rental = db.session.get(Rental, case["rental"])
            rental.updated_at = rental.updated_at + timedelta(seconds=1)
        elif changed_resource == "device":
            db.session.get(Device, case["replacement"]).lifecycle_status = (
                "damaged"
            )
        elif changed_resource == "warehouse":
            db.session.get(Warehouse, case["target"]).name = "新名称"
        else:
            db.session.get(Rental, case["child"]).device_id = extra.id
        db.session.commit()

        with pytest.raises(StaleMovementPreviewError):
            WarehouseMovementService.execute(preview["token"])

        assert db.session.get(Device, case["main_device"]).warehouse_id == (
            case["source"]
        )
        assert AuditLog.query.count() == 0


def test_preview_token_is_bound_to_current_tenant(app):
    with app.app_context():
        case = _seed_main_move()
        first_context = bind_tenant(101, db.engine)
        try:
            preview = WarehouseMovementService.preview(
                case["main_device"], case["target"]
            )
        finally:
            reset_tenant(first_context)

        second_context = bind_tenant(202, db.engine)
        try:
            with pytest.raises(StaleMovementPreviewError):
                WarehouseMovementService.execute(preview["token"])
        finally:
            reset_tenant(second_context)
        assert db.session.get(Device, case["main_device"]).warehouse_id == (
            case["source"]
        )


def test_routes_require_matching_device_id(client, app):
    with app.app_context():
        case = _seed_main_move()

    preview_response = client.post(
        f"/api/devices/{case['main_device']}/movement-preview",
        json={"target_warehouse_id": case["target"]},
    )
    assert preview_response.status_code == 200
    preview = preview_response.get_json()["data"]

    mismatch = client.post(
        f"/api/devices/{case['old_accessory']}/move",
        json={"token": preview["token"]},
    )
    assert mismatch.status_code == 409

    moved = client.post(
        f"/api/devices/{case['main_device']}/move",
        json={"token": preview["token"]},
    )
    assert moved.status_code == 200
    with app.app_context():
        assert db.session.get(Device, case["main_device"]).warehouse_id == (
            case["target"]
        )


def test_concurrent_execute_returns_one_stale_without_partial_write(app):
    with app.app_context():
        if db.engine.dialect.name != "mysql":
            pytest.skip("row-lock concurrency probe requires MariaDB")
        source = _warehouse("深圳")
        target = _warehouse("杭州")
        model = _model("concurrent-main", accessory=False)
        moving = _device("concurrent-moving", source, model)
        db.session.commit()
        source_id, target_id, moving_id = source.id, target.id, moving.id
        token = WarehouseMovementService.preview(
            moving_id, target_id
        )["token"]
        db.session.remove()

    barrier = Barrier(2)
    outcomes = []

    def execute():
        with app.app_context():
            barrier.wait()
            try:
                WarehouseMovementService.execute(token)
                outcomes.append("ok")
            except StaleMovementPreviewError:
                outcomes.append("stale")
            finally:
                db.session.remove()

    threads = [Thread(target=execute) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert sorted(outcomes) == ["ok", "stale"]
    with app.app_context():
        assert db.session.get(Device, moving_id).warehouse_id == target_id
        assert source_id != target_id
        assert AuditLog.query.filter_by(
            action="warehouse_device_moved"
        ).count() == 1


def test_audit_log_can_join_an_existing_transaction(app):
    with app.app_context():
        AuditLog.log_action(
            "transactional-test", details={"safe": True}, commit=False
        )
        db.session.flush()
        assert AuditLog.query.filter_by(action="transactional-test").count() == 1
        db.session.rollback()
        assert AuditLog.query.filter_by(action="transactional-test").count() == 0

        AuditLog.log_action("default-commit-test")
        assert AuditLog.query.filter_by(action="default-commit-test").count() == 1
