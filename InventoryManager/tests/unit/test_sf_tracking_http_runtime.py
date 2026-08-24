from app import create_app
import pytest

from app.services.shipping import (
    SfTrackingRequestInvalid,
    install_sf_tracking_http_runtime,
)
from app.services.shipping.tracking_http_runtime import (
    _parse_page,
    _parse_shipment_ids,
)


SHIPMENT_UUID = "80000000-0000-4000-8000-000000000001"


class _FakeRuntime:
    def __init__(self):
        self.calls = []

    def list_shipments(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {"items": [], "next_cursor": None}

    def query_shipment(self, **kwargs):
        self.calls.append(("query", kwargs))
        return {
            "shipment_id": SHIPMENT_UUID,
            "found": False,
            "events": [],
        }

    def query_shipments(self, **kwargs):
        self.calls.append(("batch", kwargs))
        return {"items": []}


def _app(runtime=None):
    app = create_app("testing")
    if runtime is not None:
        install_sf_tracking_http_runtime(app, runtime)
    return app


def test_routes_fail_closed_without_runtime_even_when_legacy_sf_env_exists(
    monkeypatch,
):
    monkeypatch.setenv("SF_PARTNER_ID", "legacy-must-not-run")
    monkeypatch.setenv("SF_CHECKWORD", "legacy-must-not-run")
    client = _app().test_client()

    for method, path, payload in (
        ("get", "/api/sf-tracking/list", None),
        ("post", "/api/sf-tracking/query", {"tracking_number": "SF1"}),
        (
            "post",
            "/api/sf-tracking/batch-query",
            {"tracking_numbers": ["SF1"]},
        ),
    ):
        response = getattr(client, method)(path, json=payload)
        assert response.status_code == 503
        assert response.get_json()["data"]["code"] == (
            "SF_TRACKING_RUNTIME_UNAVAILABLE"
        )
        assert response.headers["Cache-Control"] == "private, no-store"


def test_routes_delegate_only_shipment_contract_to_explicit_runtime():
    runtime = _FakeRuntime()
    client = _app(runtime).test_client()

    listed = client.get(
        "/api/sf-tracking/list?page_size=25&after_cursor=opaque"
    )
    queried = client.post(
        "/api/sf-tracking/query",
        json={"shipment_id": SHIPMENT_UUID},
    )
    batched = client.post(
        "/api/sf-tracking/batch-query",
        json={"shipment_ids": [SHIPMENT_UUID]},
    )

    assert listed.status_code == queried.status_code == batched.status_code == 200
    assert runtime.calls[0][1]["page_size"] == "25"
    assert runtime.calls[0][1]["after_cursor"] == "opaque"
    assert runtime.calls[1][1]["payload"] == {"shipment_id": SHIPMENT_UUID}
    assert runtime.calls[2][1]["payload"] == {
        "shipment_ids": [SHIPMENT_UUID]
    }


@pytest.mark.parametrize(
    "payload,single",
    (
        ({"tracking_number": "SF-LEGACY"}, True),
        ({"tracking_numbers": ["SF-LEGACY"]}, False),
        ({"shipment_id": SHIPMENT_UUID, "tenant_id": SHIPMENT_UUID}, True),
        ({"shipment_ids": []}, False),
        ({"shipment_ids": ["not-a-uuid"]}, False),
    ),
)
def test_runtime_parser_rejects_legacy_waybill_and_untrusted_scope_fields(
    payload,
    single,
):
    with pytest.raises(SfTrackingRequestInvalid):
        _parse_shipment_ids(payload, single=single)


@pytest.mark.parametrize(
    "page_size,cursor",
    (("0", None), ("101", None), ("not-an-int", None), ("25", "")),
)
def test_runtime_parser_bounds_page_and_cursor(page_size, cursor):
    with pytest.raises(SfTrackingRequestInvalid):
        _parse_page(page_size, cursor)
