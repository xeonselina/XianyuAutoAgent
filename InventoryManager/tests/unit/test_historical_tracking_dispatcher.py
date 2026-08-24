from datetime import datetime, timezone

import pytest

from app.services.shipping import (
    SfHistoricalTrackingDispatcher,
    SfTrackingRouteEvent,
    SfTrackingRouteResult,
    TrackingProviderError,
    TrackingProviderResponseError,
)
from inventory_control.integrations import (
    HistoricalTrackingCredentialError,
    SfHistoricalTrackingRequest,
    SfProviderExecutionContext,
    SfTrackingQueryItem,
)


TENANT_UUID = "10000000-0000-4000-8000-000000000001"
WAREHOUSE_UUID = "20000000-0000-4000-8000-000000000001"
INTEGRATION_UUID = "30000000-0000-4000-8000-000000000001"
ACCOUNT_UUID = "40000000-0000-4000-8000-000000000001"
INTEGRATION_REVISION_UUID = "50000000-0000-4000-8000-000000000001"
ACCOUNT_REVISION_UUID = "60000000-0000-4000-8000-000000000001"
CLAIM_UUID = "70000000-0000-4000-8000-000000000001"
SHIPMENT_1 = "80000000-0000-4000-8000-000000000001"
SHIPMENT_2 = "80000000-0000-4000-8000-000000000002"


def _request():
    return SfHistoricalTrackingRequest(
        context=SfProviderExecutionContext(
            tenant_uuid=TENANT_UUID,
            warehouse_uuid=WAREHOUSE_UUID,
            provider_account_uuid=ACCOUNT_UUID,
            integration_uuid=INTEGRATION_UUID,
            integration_secret_revision_uuid=INTEGRATION_REVISION_UUID,
            provider_account_secret_revision_uuid=ACCOUNT_REVISION_UUID,
            global_claim_uuid=CLAIM_UUID,
            claim_generation=3,
            binding_revision=7,
            masked_account_hint="****0001",
            historical=True,
        ),
        phone_last4="9000",
        items=(
            SfTrackingQueryItem(
                shipment_uuid=SHIPMENT_1,
                waybill_no="SF-TRACK-1",
            ),
            SfTrackingQueryItem(
                shipment_uuid=SHIPMENT_2,
                waybill_no="SF-TRACK-2",
            ),
        ),
        integration_credentials={
            "partner_id": "partner-secret",
            "checkword": "checkword-secret",
        },
        account_secret="monthly-account-secret",
    )


class _FakeAdapter:
    def __init__(self):
        self.seen = None

    def query_routes(self, request):
        credentials, account_secret = request.take_credentials()
        self.seen = (
            dict(credentials),
            account_secret,
            request.phone_last4,
            tuple(item.waybill_no for item in request.items),
        )
        return (
            SfTrackingRouteResult(
                shipment_uuid=SHIPMENT_1,
                waybill_no="SF-TRACK-1",
                status_code="delivered",
                events=(
                    SfTrackingRouteEvent(
                        occurred_at=datetime(
                            2026, 8, 23, 6, 5, tzinfo=timezone.utc
                        ),
                        status_code="delivered",
                        summary="快件已签收",
                    ),
                    SfTrackingRouteEvent(
                        occurred_at=datetime(
                            2026, 8, 23, 5, 0, tzinfo=timezone.utc
                        ),
                        status_code="in_transit",
                        summary="运输中",
                    ),
                ),
            ),
        )


def test_dispatch_consumes_credentials_once_and_projects_bounded_results():
    request = _request()
    adapter = _FakeAdapter()

    results = SfHistoricalTrackingDispatcher.dispatch(
        request=request,
        adapter=adapter,
    )

    assert adapter.seen == (
        {
            "partner_id": "partner-secret",
            "checkword": "checkword-secret",
        },
        "monthly-account-secret",
        "9000",
        ("SF-TRACK-1", "SF-TRACK-2"),
    )
    assert [result.shipment_uuid for result in results] == [
        SHIPMENT_1,
        SHIPMENT_2,
    ]
    assert results[0].found is True
    assert [event.status_code for event in results[0].events] == [
        "in_transit",
        "delivered",
    ]
    assert results[1].found is False
    assert results[1].status_code == "not_found"
    with pytest.raises(HistoricalTrackingCredentialError):
        request.take_credentials()


class _FailingAdapter:
    def query_routes(self, _request):
        raise RuntimeError("response containing provider details")


def test_dispatch_hides_adapter_exception_and_discards_credentials():
    request = _request()
    with pytest.raises(TrackingProviderError) as caught:
        SfHistoricalTrackingDispatcher.dispatch(
            request=request,
            adapter=_FailingAdapter(),
        )
    assert "provider details" not in str(caught.value)
    with pytest.raises(HistoricalTrackingCredentialError):
        request.take_credentials()


@pytest.mark.parametrize(
    "results",
    (
        "not-a-sequence-of-results",
        (
            SfTrackingRouteResult(
                shipment_uuid=SHIPMENT_1,
                waybill_no="SF-WRONG",
                status_code="delivered",
                events=(),
            ),
        ),
        (
            SfTrackingRouteResult(
                shipment_uuid=SHIPMENT_1,
                waybill_no="SF-TRACK-1",
                status_code="delivered",
                events=(),
            ),
            SfTrackingRouteResult(
                shipment_uuid=SHIPMENT_1,
                waybill_no="SF-TRACK-1",
                status_code="delivered",
                events=(),
            ),
        ),
    ),
)
def test_dispatch_rejects_untyped_mismatched_or_duplicate_provider_results(
    results,
):
    class Adapter:
        def query_routes(self, _request):
            return results

    with pytest.raises(TrackingProviderResponseError):
        SfHistoricalTrackingDispatcher.dispatch(
            request=_request(),
            adapter=Adapter(),
        )
