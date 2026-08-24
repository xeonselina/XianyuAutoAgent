from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.shipping import (
    SfHistoricalTrackingDispatcher,
    SfSdkTrackingAdapter,
    TrackingProviderError,
)
from inventory_control.integrations import (
    SfHistoricalTrackingRequest,
    SfProviderExecutionContext,
    SfTrackingQueryItem,
)


SHIPMENT_UUID = "80000000-0000-4000-8000-000000000001"


def _request():
    return SfHistoricalTrackingRequest(
        context=SfProviderExecutionContext(
            tenant_uuid="10000000-0000-4000-8000-000000000001",
            warehouse_uuid="20000000-0000-4000-8000-000000000001",
            provider_account_uuid="30000000-0000-4000-8000-000000000001",
            integration_uuid="40000000-0000-4000-8000-000000000001",
            integration_secret_revision_uuid=(
                "50000000-0000-4000-8000-000000000001"
            ),
            provider_account_secret_revision_uuid=(
                "60000000-0000-4000-8000-000000000001"
            ),
            global_claim_uuid="70000000-0000-4000-8000-000000000001",
            claim_generation=2,
            binding_revision=7,
            masked_account_hint="****0001",
            historical=True,
        ),
        phone_last4="9000",
        items=(
            SfTrackingQueryItem(
                shipment_uuid=SHIPMENT_UUID,
                waybill_no="SF-TRACK-1",
            ),
        ),
        integration_credentials={
            "partner_id": "exact-partner",
            "checkword": "exact-checkword",
        },
        account_secret="exact-monthly-account",
    )


class _FakeClient:
    def __init__(self):
        self.calls = []

    def batch_search_routes(self, waybills, phone_last4):
        self.calls.append((waybills, phone_last4))
        return {"apiResultCode": "A1000", "apiResultData": "typed-fake"}

    def parse_route_response(self, _response):
        return {
            "SF-TRACK-1": {
                "status": "in_transit",
                "routes": [
                    {
                        "accept_time": "2026-08-23 06:00:00",
                        "remark": "运输中",
                        "first_status_code": "2",
                    },
                ],
            },
        }


def test_sdk_adapter_uses_exact_request_credentials_and_typed_projection():
    constructed = []
    client = _FakeClient()

    def client_factory(**kwargs):
        constructed.append(kwargs)
        return client

    adapter = SfSdkTrackingAdapter(
        test_mode=False,
        provider_timezone=ZoneInfo("Asia/Shanghai"),
        client_factory=client_factory,
    )

    results = SfHistoricalTrackingDispatcher.dispatch(
        request=_request(),
        adapter=adapter,
    )

    assert constructed == [
        {
            "partner_id": "exact-partner",
            "checkword": "exact-checkword",
            "test_mode": False,
        }
    ]
    assert client.calls == [(["SF-TRACK-1"], "9000")]
    assert results[0].status_code == "in_transit"
    assert results[0].events[0].occurred_at == datetime.fromisoformat(
        "2026-08-23T06:00:00+08:00"
    )
    assert "exact-partner" not in repr(adapter)


def test_sdk_adapter_classifies_non_success_envelope_as_unavailable():
    class FailedClient(_FakeClient):
        def batch_search_routes(self, waybills, phone_last4):
            self.calls.append((waybills, phone_last4))
            return {
                "apiResultCode": "A9999",
                "apiErrorMsg": "provider detail must not escape",
            }

    adapter = SfSdkTrackingAdapter(
        test_mode=True,
        provider_timezone=ZoneInfo("Asia/Shanghai"),
        client_factory=lambda **_kwargs: FailedClient(),
    )

    with pytest.raises(TrackingProviderError) as caught:
        SfHistoricalTrackingDispatcher.dispatch(
            request=_request(),
            adapter=adapter,
        )
    assert "provider detail" not in str(caught.value)
