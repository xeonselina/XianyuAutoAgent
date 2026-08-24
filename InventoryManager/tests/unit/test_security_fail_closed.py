"""Regression tests for Phase 0 credential and diagnostic-route containment."""

import logging

import pytest

from app import create_app
from app.services.gantt.reorder_service import GanttReorderService
from app.services.printing.kuaimai_service import KuaimaiPrintService
from app.services.shipping.sf_express_service import SFExpressService
from app.services.shipping.sf_tracking_service import SFTrackingService
from app.utils.scheduler_tasks import RentalTrackingScheduler
from app.utils.sf.sf_sdk_wrapper import SFExpressSDK
from config import TestingConfig


class ProductionLikeConfig(TestingConfig):
    TESTING = False
    DEBUG = False
    SECRET_KEY = None


class DebugLikeConfig(TestingConfig):
    TESTING = False
    DEBUG = True
    SECRET_KEY = None


class MissingRequiredConfig(TestingConfig):
    TESTING = False
    SECRET_KEY = None
    SQLALCHEMY_DATABASE_URI = None


@pytest.mark.parametrize(
    "configuration",
    (ProductionLikeConfig, DebugLikeConfig, TestingConfig),
)
def test_provider_test_routes_are_never_registered(
    configuration,
):
    app = create_app(configuration)

    routes = {rule.rule for rule in app.url_map.iter_rules()}

    assert not any(route.startswith("/api/sf-test") for route in routes)


def test_web_application_factory_never_starts_legacy_scheduler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.utils.scheduler.init_scheduler",
        lambda _app: calls.append("started"),
    )

    create_app(ProductionLikeConfig)

    assert calls == []


def test_application_fails_closed_when_required_runtime_config_is_missing():
    with pytest.raises(RuntimeError, match="SQLALCHEMY_DATABASE_URI"):
        create_app(MissingRequiredConfig)


def test_production_startup_does_not_require_generic_secret_key():
    app = create_app(ProductionLikeConfig)

    assert app.config.get("SECRET_KEY") is None


def test_platform_routes_expose_no_tenant_identity_recovery_mutation():
    app = create_app(ProductionLikeConfig)
    tenant_mutations = {
        (rule.rule, method)
        for rule in app.url_map.iter_rules()
        if rule.rule.startswith("/platform/api/tenants/")
        for method in rule.methods
        if method not in {"GET", "HEAD", "OPTIONS"}
    }

    assert tenant_mutations == {
        (
            "/platform/api/tenants/<tenant_id>/subscription-adjustments",
            "POST",
        ),
        (
            "/platform/api/tenants/<tenant_id>/subscription-adjustments/preview",
            "POST",
        ),
    }


def test_legacy_gantt_signer_is_literal_test_only():
    app = create_app(ProductionLikeConfig)
    app.config["LEGACY_GANTT_TEST_SIGNING_KEY"] = b"x" * 32

    with app.app_context(), pytest.raises(
        RuntimeError,
        match="legacy Gantt signer is unavailable",
    ):
        GanttReorderService._serializer()


def test_kuaimai_initialization_and_request_logs_do_not_contain_credentials(
    monkeypatch, caplog
):
    app_id = "phase0-kuaimai-app-id"
    app_secret = "phase0-kuaimai-app-secret"
    printer_sn = "phase0-kuaimai-printer"
    response_marker = "phase0-kuaimai-response-secret"
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": True,
                "code": 0,
                "private_payload": response_marker,
                "data": {"job": "job-1"},
            }

    monkeypatch.setattr(
        "app.services.printing.kuaimai_service.requests.post",
        lambda *_args, **_kwargs: FakeResponse(),
    )
    caplog.set_level(logging.DEBUG)

    service = KuaimaiPrintService(
        app_id=app_id,
        app_secret=app_secret,
        default_printer_sn=printer_sn,
    )
    result = service._make_request("getPrintJobStatus", {"jobId": "job-1"})

    assert result == {"job": "job-1"}
    for sensitive_value in (app_id, app_secret, printer_sn, response_marker):
        assert sensitive_value not in caplog.text


def test_legacy_provider_adapters_do_not_discover_process_credentials(
    monkeypatch,
):
    for name in (
        "KUAIMAI_APP_ID",
        "KUAIMAI_APP_SECRET",
        "KUAIMAI_PRINTER_SN",
        "SF_PARTNER_ID",
        "SF_CHECKWORD",
        "SF_MONTHLY_CARD",
        "SF_CHECKPHONENO",
    ):
        monkeypatch.setenv(name, "must-not-be-read")

    kuaimai = KuaimaiPrintService()
    sf = SFExpressService()
    scheduler = RentalTrackingScheduler()

    assert kuaimai.configured is False
    assert (kuaimai.app_id, kuaimai.app_secret, kuaimai.default_printer_sn) == (
        "",
        "",
        "",
    )
    assert (sf.partner_id, sf.checkword, sf.monthly_card) == (None, None, None)
    assert scheduler.sf_client is None
    assert scheduler.check_phone_no is None
    with pytest.raises(RuntimeError, match="explicitly injected"):
        SFTrackingService.get_client()


def test_sf_sdk_logs_only_request_and_response_metadata(monkeypatch, caplog):
    partner_id = "phase0-sf-partner"
    checkword = "phase0-sf-checkword"
    customer_marker = "phase0-customer-private-data"
    response_marker = "phase0-sf-response-private-data"

    class FakeResponse:
        status_code = 200
        text = response_marker

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "apiResultCode": "A1000",
                "apiResultData": response_marker,
            }

    monkeypatch.setattr(
        "app.utils.sf.sf_sdk_wrapper.requests.post",
        lambda *_args, **_kwargs: FakeResponse(),
    )
    caplog.set_level(logging.INFO)
    sdk = SFExpressSDK(partner_id, checkword, use_oauth=False)

    result = sdk._call_sf_express_service(
        "PHASE0_TEST_SERVICE",
        {"contact": customer_marker},
    )

    assert result["apiResultCode"] == "A1000"
    for sensitive_value in (
        partner_id,
        checkword,
        customer_marker,
        response_marker,
    ):
        assert sensitive_value not in caplog.text
