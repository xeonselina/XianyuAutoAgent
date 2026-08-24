from flask import Flask
import pytest

from app.handlers.shipping_batch_handlers import ShippingBatchHandlers
from app.routes.shipping_batch_api import bp
from app.services.shipping.batch_http_runtime import (
    SF_BATCH_SHIPPING_HTTP_RUNTIME_EXTENSION,
    SfBatchShippingRequestInvalid,
    _parse_batch_request,
    install_sf_batch_shipping_http_runtime,
)
from config import Config, DockerConfig, ProductionConfig, TestingConfig


@pytest.mark.parametrize(
    ("path", "method"),
    (
        ("/api/shipping-batch/schedule", "post"),
        ("/api/shipping-batch/status", "get"),
        ("/api/shipping-batch/express-type", "patch"),
        ("/api/shipping-batch/printers", "get"),
        ("/api/shipping-batch/print-waybills", "post"),
        ("/api/shipping-batch/ship-to-xianyu/1", "post"),
    ),
)
def test_legacy_shipping_surface_is_blocked_before_handler_outside_tests(
    monkeypatch,
    path,
    method,
) -> None:
    def unexpected_handler(*_args, **_kwargs):
        raise AssertionError("legacy shipping handler must remain unreachable")

    for name in (
        "handle_schedule_shipment",
        "handle_get_status",
        "handle_update_express_type",
        "handle_get_printers",
        "handle_print_waybills",
        "handle_ship_to_xianyu",
    ):
        monkeypatch.setattr(ShippingBatchHandlers, name, unexpected_handler)

    app = Flask(__name__)
    app.config.update(
        TESTING=False,
        ENABLE_LEGACY_SINGLE_TENANT_SHIPPING_BATCH_API=True,
    )
    app.register_blueprint(bp)

    response = getattr(app.test_client(), method)(path, json={})

    assert response.status_code == 503
    expected = {
        "success": False,
        "message": "租户发货服务尚未就绪",
    }
    if path.endswith("/schedule"):
        expected["data"] = {
            "code": "SF_BATCH_SHIPPING_RUNTIME_UNAVAILABLE"
        }
    assert response.get_json() == expected
    assert response.headers["Cache-Control"] == "private, no-store"


def test_only_testing_config_enables_legacy_shipping_compatibility() -> None:
    assert Config.ENABLE_LEGACY_SINGLE_TENANT_SHIPPING_BATCH_API is False
    assert ProductionConfig.ENABLE_LEGACY_SINGLE_TENANT_SHIPPING_BATCH_API is False
    assert DockerConfig.ENABLE_LEGACY_SINGLE_TENANT_SHIPPING_BATCH_API is False
    assert TestingConfig.ENABLE_LEGACY_SINGLE_TENANT_SHIPPING_BATCH_API is True


def test_schedule_route_delegates_only_to_explicit_tenant_runtime() -> None:
    calls = []

    class Runtime:
        def schedule_shipments(self, **kwargs):
            calls.append(kwargs)
            return {
                "request_uuid": "11111111-1111-4111-8111-111111111111",
                "accepted_count": 1,
                "items": [],
            }

    app = Flask(__name__)
    app.config["TESTING"] = False
    app.register_blueprint(bp)
    runtime = Runtime()
    install_sf_batch_shipping_http_runtime(app, runtime)

    payload = {
        "request_uuid": "11111111-1111-4111-8111-111111111111",
        "rental_ids": [1],
        "scheduled_time": "2026-08-24T09:00:00+08:00",
    }
    response = app.test_client().post(
        "/api/shipping-batch/schedule",
        json=payload,
    )

    assert response.status_code == 202
    assert response.get_json()["message"] == "发货任务已受理"
    assert calls[0]["payload"] == payload
    assert app.extensions[SF_BATCH_SHIPPING_HTTP_RUNTIME_EXTENSION] is runtime


def test_batch_parser_deduplicates_and_normalizes_time() -> None:
    parsed = _parse_batch_request({
        "request_uuid": "11111111-1111-4111-8111-111111111111",
        "rental_ids": [3, 1, 3],
        "scheduled_time": "2026-08-24T09:00:00+08:00",
    })

    assert parsed.rental_ids == (3, 1)
    assert parsed.scheduled_dispatch_at.isoformat() == "2026-08-24T01:00:00"


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {
            "request_uuid": "11111111-1111-4111-8111-111111111111",
            "rental_ids": [],
            "scheduled_time": "2026-08-24T09:00:00+08:00",
        },
        {
            "request_uuid": "11111111-1111-4111-8111-111111111111",
            "rental_ids": [True],
            "scheduled_time": "2026-08-24T09:00:00+08:00",
        },
        {
            "request_uuid": "11111111-1111-4111-8111-111111111111",
            "rental_ids": [1],
            "scheduled_time": "2026-08-24T09:00:00",
        },
    ),
)
def test_batch_parser_rejects_ambiguous_identity_or_time(payload) -> None:
    with pytest.raises(SfBatchShippingRequestInvalid):
        _parse_batch_request(payload)
