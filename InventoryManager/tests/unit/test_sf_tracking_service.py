import pytest

from app.services.shipping.sf_tracking_service import (
    SFTrackingService,
    TrackingNotFoundError,
)


class FakeSFClient:
    def __init__(self, parsed):
        self.parsed = parsed
        self.search_calls = []
        self.batch_calls = []
        self.parse_calls = []

    def search_routes(self, tracking_number, phone_last4):
        self.search_calls.append((tracking_number, phone_last4))
        return {"raw": "single"}

    def batch_search_routes(self, tracking_numbers, phone_last4):
        self.batch_calls.append((tracking_numbers, phone_last4))
        return {"raw": "batch"}

    def parse_route_response(self, response):
        self.parse_calls.append(response)
        return self.parsed


def test_query_passes_supplied_phone_last4_to_one_client(monkeypatch):
    route = {
        "tracking_number": "SF1",
        "status": "in_transit",
        "status_text": "运送中",
        "routes": [],
        "last_update": "2026-08-05 10:00:00",
        "delivered_time": None,
    }
    client = FakeSFClient(parsed={"SF1": route})
    monkeypatch.setattr(
        SFTrackingService,
        "get_client",
        classmethod(lambda cls: client),
    )

    result = SFTrackingService.query("SF1", "8000")

    assert result == route
    assert client.search_calls == [("SF1", "8000")]
    assert client.parse_calls == [{"raw": "single"}]


def test_query_rejects_missing_route(monkeypatch):
    client = FakeSFClient(parsed={})
    monkeypatch.setattr(
        SFTrackingService,
        "get_client",
        classmethod(lambda cls: client),
    )

    with pytest.raises(TrackingNotFoundError, match="未找到"):
        SFTrackingService.query("SF404", "8000")


@pytest.mark.parametrize(
    ("tracking_number", "phone_last4", "message"),
    [
        ("", "8000", "运单号"),
        ("SF1", "", "手机后四位"),
        ("SF1", "13800", "手机后四位"),
        ("SF1", "ABCD", "手机后四位"),
    ],
)
def test_query_validates_tracking_number_and_phone(
    tracking_number, phone_last4, message
):
    with pytest.raises(ValueError, match=message):
        SFTrackingService.query(tracking_number, phone_last4)


def test_batch_query_preserves_existing_shared_phone_behavior(monkeypatch):
    parsed = {
        "SF1": {"tracking_number": "SF1", "status": "picked_up"},
        "SF2": {"tracking_number": "SF2", "status": "in_transit"},
    }
    client = FakeSFClient(parsed=parsed)
    monkeypatch.setattr(
        SFTrackingService,
        "get_client",
        classmethod(lambda cls: client),
    )

    result = SFTrackingService.batch_query(["SF1", "SF2"], "4947")

    assert result == parsed
    assert client.batch_calls == [(["SF1", "SF2"], "4947")]

