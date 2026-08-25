"""Warehouse-scoped shipping, printing, and tracking regression coverage."""

import os
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app import create_app, db
from app.crypto import SecretBox
from app.routes import sf_tracking_api
from app.models.device import Device
from app.models.rental import Rental
from app.models.warehouse import (
    Warehouse,
    WarehouseKuaimaiConfig,
    WarehouseSFConfig,
)
from app.services.printing.kuaimai_service import KuaimaiPrintService
from app.services.settings_service import (
    KUAIMAI_SECRET_PURPOSE,
    SF_CHECKWORD_PURPOSE,
    SF_MONTHLY_CARD_PURPOSE,
)
from app.services.shipping.sf_express_service import SFExpressService
from app.services.shipping.waybill_print_service import (
    build_sf_client_order_id,
    normalize_sender_address,
)
from app.tenant_context import bind_tenant, reset_tenant
from app.utils.sf.sf_sdk_wrapper import SFExpressSDK
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

        class ShippingConfig(TestingConfig):
            SQLALCHEMY_DATABASE_URI = parsed.render_as_string(
                hide_password=False
            )
            SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

        application = create_app(ShippingConfig)
        with application.app_context():
            with db.engine.connect() as connection:
                assert_current_user_has_test_only_grants(
                    connection, parsed.database,
                    "control_saas_test", "tenant_b_saas_test",
                )
        return application
    return create_app("testing")


@pytest.fixture(autouse=True)
def shipping_case(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        box = SecretBox.from_base64(app.config["SAAS_MASTER_KEY"])
        app.extensions["control_store"] = SimpleNamespace(secret_box=box)
        warehouses = [
            Warehouse(province="广东省", city="深圳市", name="A仓"),
            Warehouse(province="浙江省", city="杭州市", name="B仓"),
        ]
        db.session.add_all(warehouses)
        db.session.flush()
        for index, warehouse in enumerate(warehouses, 1):
            db.session.add(WarehouseSFConfig(
                warehouse_id=warehouse.id,
                partner_id=f"partner-{index}",
                checkword_ciphertext=box.encrypt(
                    f"check-{index}", SF_CHECKWORD_PURPOSE
                ),
                monthly_card_ciphertext=box.encrypt(
                    f"monthly-{index}", SF_MONTHLY_CARD_PURPOSE
                ),
                sender_name=f"sender-{index}",
                sender_phone=f"1380013800{index}",
                sender_address=f"address-{index}",
            ))
            db.session.add(WarehouseKuaimaiConfig(
                warehouse_id=warehouse.id,
                app_id=f"app-{index}",
                app_secret_ciphertext=box.encrypt(
                    f"secret-{index}", KUAIMAI_SECRET_PURPOSE
                ),
                printer_sn=f"printer-{index}",
            ))
        devices = [
            Device(name=f"device-{index}", model="x200u",
                   warehouse_id=warehouse.id)
            for index, warehouse in enumerate(warehouses, 1)
        ]
        db.session.add_all(devices)
        db.session.flush()
        today = date.today() + timedelta(days=5)
        rentals = [
            Rental(
                device_id=device.id, warehouse_id=warehouse.id,
                start_date=today, end_date=today + timedelta(days=2),
                customer_name=f"customer-{index}",
                customer_phone=f"1390013900{index}",
                destination=f"destination-{index}", status="not_shipped",
            )
            for index, (warehouse, device) in enumerate(
                zip(warehouses, devices), 1
            )
        ]
        db.session.add_all(rentals)
        db.session.commit()
        yield {
            "warehouses": [row.id for row in warehouses],
            "devices": [row.id for row in devices],
            "rentals": [row.id for row in rentals],
        }
        db.session.remove()
        db.drop_all()


def _tenant_request(app, method, path, **kwargs):
    with app.app_context():
        token = bind_tenant(42, db.engine)
        try:
            return getattr(app.test_client(), method)(path, **kwargs)
        finally:
            reset_tenant(token)


def test_schedule_uses_each_warehouse_and_stable_order_id(
    app, shipping_case, monkeypatch
):
    calls = []

    def create_order(service, order_data):
        calls.append((service.config, order_data))
        return {"success": True, "waybill_no": f"SF-{service.partner_id}"}

    monkeypatch.setattr(SFExpressService, "create_order", create_order)
    response = _tenant_request(
        app, "post", "/api/shipping-batch/schedule",
        json={
            "rental_ids": shipping_case["rentals"],
            "scheduled_time": "2026-08-30T18:00:00",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["scheduled_count"] == 2
    assert [call[0].partner_id for call in calls] == ["partner-1", "partner-2"]
    assert [call[0].monthly_card for call in calls] == ["monthly-1", "monthly-2"]
    assert [call[0].sender_name for call in calls] == ["sender-1", "sender-2"]
    assert [call[1]["orderId"] for call in calls] == [
        build_sf_client_order_id(42, rental_id)
        for rental_id in shipping_case["rentals"]
    ]
    senders = [call[1]["contactInfoList"][0] for call in calls]
    assert [(r["province"], r["city"], r["address"]) for r in senders] == [
        ("广东省", "深圳市", "address-1"), ("浙江省", "杭州市", "address-2")]
    assert (normalize_sender_address("广东省", "深圳市", "广东省深圳市科技园"), normalize_sender_address("上海市", "上海市", "上海市浦东新区")) == ("广东省深圳市科技园", "上海市浦东新区")
    assert build_sf_client_order_id(42, 7) == "t42-r7"


def test_schedule_isolates_external_failure_per_rental(
    app, shipping_case, monkeypatch, caplog
):
    caplog.set_level("INFO")
    def create_order(service, _order_data):
        if service.partner_id == "partner-1":
            return {"success": False, "message": "private upstream body"}
        return {"success": True, "waybill_no": "SF-B"}

    monkeypatch.setattr(SFExpressService, "create_order", create_order)
    response = _tenant_request(
        app, "post", "/api/shipping-batch/schedule",
        json={"rental_ids": shipping_case["rentals"],
              "scheduled_time": "2026-08-30T18:00:00"},
    )
    payload = response.get_json()["data"]
    assert payload["scheduled_count"] == 1
    assert payload["results"][0]["code"] == "EXTERNAL_SERVICE_ERROR"
    assert "private upstream body" not in str(payload)
    assert payload["results"][1]["waybill_no"] == "SF-B"
    monkeypatch.setattr("app.utils.sf.sf_sdk_wrapper.requests.post", lambda *_a, **_k: SimpleNamespace(status_code=500, text="private upstream body", raise_for_status=lambda: (_ for _ in ()).throw(RuntimeError("HTTP 500"))))
    printed = _tenant_request(app, "post", "/api/shipping-batch/print-waybills",
        json={"rental_ids": [shipping_case["rentals"][1]],
              "include_shipping_slips": False}).get_json()
    assert printed["data"]["results"][0]["code"] == "EXTERNAL_SERVICE_ERROR"
    assert "private upstream body" not in str(printed)
    monkeypatch.setattr(SFExpressSDK, "search_routes", lambda *_: {
        "apiResultCode": "A9999", "apiErrorMsg": "private upstream body"})
    legacy = _tenant_request(app, "post", "/api/tracking/query",
        json={"tracking_number": "SF-B"})
    assert (legacy.status_code, legacy.get_json()["code"]) == (
        502, "EXTERNAL_SERVICE_ERROR")
    assert _tenant_request(app, "post", "/api/tracking/update-now").status_code == 410
    assert _tenant_request(app, "get", "/api/tracking/scheduler-status").status_code == 410
    assert "private upstream body" not in str(legacy.get_json())
    assert "private upstream body" not in caplog.text


@pytest.mark.parametrize("mismatch", ["main", "child"])
def test_mismatch_and_duplicate_never_call_sf(
    app, shipping_case, monkeypatch, mismatch
):
    with app.app_context():
        rental = db.session.get(Rental, shipping_case["rentals"][0])
        print_ids = [rental.id]
        if mismatch == "main":
            rental.device.warehouse_id = shipping_case["warehouses"][1]
        else:
            child_device = Device(
                name="wrong accessory", model="tripod", is_accessory=True,
                warehouse_id=shipping_case["warehouses"][1],
            )
            db.session.add(child_device)
            db.session.flush()
            child = Rental(
                device_id=child_device.id,
                warehouse_id=rental.warehouse_id,
                parent_rental_id=rental.id,
                start_date=rental.start_date, end_date=rental.end_date,
                customer_name=rental.customer_name,
                ship_out_tracking_no="SF-CHILD", status="not_shipped",
            )
            db.session.add(child)
            db.session.flush()
            print_ids.append(child.id)
        rental.ship_out_tracking_no = "SF-MAIN"
        db.session.commit()
    calls = []
    monkeypatch.setattr(
        SFExpressService, "create_order",
        lambda *_args: calls.append(True),
    )
    response = _tenant_request(
        app, "post", "/api/shipping-batch/schedule",
        json={"rental_ids": [shipping_case["rentals"][0]],
              "scheduled_time": "2026-08-30T18:00:00"},
    )
    result = response.get_json()["data"]["results"][0]
    assert result["code"] == "WAREHOUSE_MISMATCH"
    assert calls == []
    monkeypatch.setattr(SFExpressService, "get_waybill_pdf",
                        lambda *_: calls.append(True))
    printed = _tenant_request(app, "post", "/api/shipping-batch/print-waybills",
        json={"rental_ids": print_ids, "include_shipping_slips": False})
    assert all(row["code"] == "WAREHOUSE_MISMATCH"
               for row in printed.get_json()["data"]["results"])
    assert calls == []


def test_existing_waybill_and_missing_config_are_isolated(
    app, shipping_case, monkeypatch
):
    with app.app_context():
        first = db.session.get(Rental, shipping_case["rentals"][0])
        first.ship_out_tracking_no = "SF-EXISTING"
        first.status = "not_shipped"
        db.session.get(
            WarehouseSFConfig, shipping_case["warehouses"][1]
        ).sender_name = None
        db.session.commit()
    calls = []
    monkeypatch.setattr(
        SFExpressService, "create_order",
        lambda *_args: calls.append(True),
    )
    response = _tenant_request(
        app, "post", "/api/shipping-batch/schedule",
        json={"rental_ids": shipping_case["rentals"],
              "scheduled_time": "2026-08-30T18:00:00"},
    )
    results = response.get_json()["data"]["results"]
    assert "已有运单" in results[0]["message"]
    assert results[1]["code"] == "CONFIG_INCOMPLETE"
    assert calls == []


def test_print_and_tracking_resolve_the_rental_warehouse(
    app, shipping_case, monkeypatch
):
    with app.app_context():
        for rental_id in shipping_case["rentals"]:
            rental = db.session.get(Rental, rental_id)
            rental.ship_out_tracking_no = f"SF-{rental_id}"
            rental.ship_out_time = datetime.utcnow()
        db.session.commit()
    printed = []
    monkeypatch.setattr(
        SFExpressService, "get_waybill_pdf",
        lambda service, _rental: {"success": True, "pdf_data": b"pdf"},
    )
    monkeypatch.setattr(
        "app.services.shipping.pdf_conversion_service."
        "PDFConversionService.convert_pdf_to_base64_images",
        lambda *_args: ["image"],
    )
    monkeypatch.setattr(
        KuaimaiPrintService, "print_image",
        lambda service, **_kwargs: (
            printed.append(service.default_printer_sn)
            or {"success": True, "job_id": service.default_printer_sn}
        ),
    )
    response = _tenant_request(
        app, "post", "/api/shipping-batch/print-waybills",
        json={"rental_ids": shipping_case["rentals"],
              "include_shipping_slips": False},
    )
    assert response.status_code == 200
    assert printed == ["printer-1", "printer-2"]
    monkeypatch.setattr("app.services.shipping.waybill_print_service.WaybillPrintService._print_single_shipping_slip", lambda *_: {"success": False, "error": "配置不完整", "code": "CONFIG_INCOMPLETE"})
    slips = _tenant_request(app, "post", "/api/shipping-batch/print-waybills", json={"rental_ids": shipping_case["rentals"], "include_shipping_slips": True}).get_json()["data"]["results"]
    assert [row.get("code") for row in slips] == ["CONFIG_INCOMPLETE"] * 2

    queries = []
    monkeypatch.setattr(
        SFExpressSDK, "search_routes",
        lambda client, number, last4: (
            queries.append((client.partner_id, number, last4))
            or {"number": number}
        ),
    )
    monkeypatch.setattr(
        SFExpressSDK, "parse_route_response",
        lambda _client, raw: {
            raw["number"]: {"tracking_number": raw["number"]}
        },
    )
    matched = _tenant_request(
        app, "post", "/api/sf-tracking/query",
        json={"tracking_no": f"SF-{shipping_case['rentals'][1]}"},
    )
    missing_scope = _tenant_request(
        app, "post", "/api/sf-tracking/query",
        json={"tracking_no": "SF-UNKNOWN", "phone_last4": "9000"},
    )
    unmatched = _tenant_request(
        app, "post", "/api/sf-tracking/query",
        json={"tracking_no": "SF-UNKNOWN",
              "warehouse_id": shipping_case["warehouses"][0],
              "phone_last4": "9000"},
    )
    assert matched.status_code == 200
    assert missing_scope.status_code == 400
    assert unmatched.status_code == 200
    assert queries == [
        ("partner-2", f"SF-{shipping_case['rentals'][1]}", "9002"),
        ("partner-1", "SF-UNKNOWN", "9000"),
    ]
    listed = _tenant_request(app, "get", "/api/sf-tracking/list",
        query_string={"warehouse_id": shipping_case["warehouses"][1]})
    assert [row["rental_id"] for row in listed.get_json()["data"]] == [shipping_case["rentals"][1]]
    failures = {"SF-C": sf_tracking_api.ConfigurationIncomplete("warehouse", 1, ("sender",)), "SF-W": sf_tracking_api.WarehouseMismatchError("ambiguous"), "SF-E": RuntimeError("private upstream body")}
    monkeypatch.setattr(sf_tracking_api.SFTrackingService, "query_scoped", classmethod(lambda _cls, number, **_kwargs: (_ for _ in ()).throw(failures[number])))
    batch = _tenant_request(app, "post", "/api/sf-tracking/batch-query", json={"tracking_numbers": list(failures), "warehouse_id": shipping_case["warehouses"][0], "phone_last4": "9000"}).get_json()
    assert [(row["code"], row["message"]) for row in batch["error_details"]] == [("CONFIG_INCOMPLETE", "仓库顺丰配置不完整"), ("WAREHOUSE_MISMATCH", "运单号无法确定唯一仓库"), ("EXTERNAL_SERVICE_ERROR", "顺丰服务调用失败")]
    assert "private upstream body" not in str(batch)


def test_sf_test_api_is_absent_in_production(app):
    original = {key: app.config[key] for key in ("TESTING", "DEBUG", "IS_PRODUCTION")}
    try:
        app.config.update(TESTING=False, DEBUG=False, IS_PRODUCTION=False)
        assert app.test_client().get("/api/sf-test/status").status_code == 404
        app.config.update(TESTING=True)
        assert app.test_client().get("/api/sf-test/status").status_code != 404
        app.config.update(IS_PRODUCTION=True)
        response = app.test_client().get("/api/sf-test/status")
    finally:
        app.config.update(original)
    assert response.status_code == 404


def test_tracking_duplicate_fails_closed(app, shipping_case, monkeypatch):
    with app.app_context():
        for rental_id in shipping_case["rentals"]:
            row = db.session.get(Rental, rental_id)
            row.ship_out_tracking_no = "SF-DUPLICATE"
            row.ship_out_time = datetime.utcnow()
        db.session.commit()
    calls = []
    monkeypatch.setattr(SFExpressSDK, "search_routes",
                        lambda *_: calls.append(True))
    duplicate = _tenant_request(app, "post", "/api/sf-tracking/query",
                                json={"tracking_no": "SF-DUPLICATE"})
    assert (duplicate.status_code, duplicate.get_json()["code"], calls) == (409, "WAREHOUSE_MISMATCH", [])


def test_schedule_rolls_back_only_failed_rental_commit(app, shipping_case, monkeypatch):
    monkeypatch.setattr(SFExpressService, "create_order", lambda service, _: {"success": True, "waybill_no": f"SF-{service.partner_id}"})
    with app.app_context():
        real_commit = db.session.commit
        commits = []

        def fail_first_commit():
            commits.append(True)
            if len(commits) == 1:
                raise RuntimeError("database write failed")
            return real_commit()

        monkeypatch.setattr(db.session, "commit", fail_first_commit)
        response = _tenant_request(app, "post", "/api/shipping-batch/schedule",
            json={"rental_ids": shipping_case["rentals"],
                  "scheduled_time": "2026-08-30T18:00:00"})
        tracking = [db.session.get(Rental, rental_id).ship_out_tracking_no
                    for rental_id in shipping_case["rentals"]]
        assert tracking == [None, "SF-partner-2"]
    results = response.get_json()["data"]["results"]
    assert results[0]["code"] == "EXTERNAL_SERVICE_ERROR"
    assert results[1]["success"] is True
