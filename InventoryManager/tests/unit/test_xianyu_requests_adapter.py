from datetime import datetime, timezone

import pytest

from app.services.xianyu_sync import (
    RequestsXianyuProviderAdapter,
    XianyuProviderError,
    XianyuProviderRateLimited,
    XianyuProviderSettings,
)
from inventory_control.integrations import (
    XianyuSyncCredentialError,
    XianyuSyncExecutionContext,
    XianyuSyncProviderRequest,
)


SETTINGS = XianyuProviderSettings(
    endpoint="https://open.goofish.pro",
    connect_timeout_seconds=3,
    read_timeout_seconds=15,
    rate_limit_retry_seconds=45,
    page_size=1,
    max_pages=3,
)
EPOCH = 1787443200


class Response:
    def __init__(self, payload=None, *, status_code=200, json_error=None):
        self.payload = payload
        self.status_code = status_code
        self.json_error = json_error

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _request():
    return XianyuSyncProviderRequest(
        context=XianyuSyncExecutionContext(
            tenant_uuid="b1000000-0000-4000-8000-000000000001",
            integration_uuid="b1000000-0000-4000-8000-000000000002",
            secret_revision_uuid="b1000000-0000-4000-8000-000000000003",
            integration_row_version=2,
            revision_row_version=3,
        ),
        provider_cursor=None,
        credentials={"app_key": "app-value", "app_secret": "secret-value"},
    )


def test_adapter_fetches_complete_pages_and_projects_only_eligible_orders():
    client = Client(
        (
            Response(
                {
                    "code": 0,
                    "data": {
                        "count": 2,
                        "list": [
                            {
                                "order_no": "ORDER-1",
                                "pay_amount": 5001,
                                "buyer_nick": "buyer",
                                "receiver_name": "receiver",
                                "receiver_mobile": "13800138000",
                                "prov_name": "广东省",
                                "city_name": "深圳市",
                                "area_name": "南山区",
                                "town_name": "粤海街道",
                                "address": "科技园",
                                "goods": {"title": "camera", "sku_text": "A"},
                                "order_time": 1787443200,
                            }
                        ],
                    },
                }
            ),
            Response(
                {
                    "code": 0,
                    "data": {
                        "count": 2,
                        "list": [
                            {
                                "order_no": "ORDER-2",
                                "pay_amount": 5000,
                            }
                        ],
                    },
                }
            ),
        )
    )

    result = RequestsXianyuProviderAdapter(
        http_client=client,
        epoch_seconds=lambda: EPOCH,
    ).fetch_alerts(request=_request(), settings=SETTINGS)

    assert len(client.calls) == 2
    assert [call[0] for call in client.calls] == [
        "https://open.goofish.pro/api/open/order/list",
        "https://open.goofish.pro/api/open/order/list",
    ]
    assert [call[1]["timeout"] for call in client.calls] == [(3, 15), (3, 15)]
    assert [call[1]["params"]["timestamp"] for call in client.calls] == [
        EPOCH,
        EPOCH,
    ]
    assert [len(call[1]["params"]["sign"]) for call in client.calls] == [32, 32]
    assert [alert.order_no for alert in result.alerts] == ["ORDER-1"]
    assert result.alerts[0].address == "广东省深圳市南山区粤海街道科技园"
    assert result.alerts[0].order_time == datetime.fromtimestamp(
        EPOCH, tz=timezone.utc
    )
    assert result.next_cursor is None


def test_adapter_uses_explicit_rate_limit_retry_time():
    request = _request()
    adapter = RequestsXianyuProviderAdapter(
        http_client=Client((Response(status_code=429),)),
        epoch_seconds=lambda: EPOCH,
    )

    with pytest.raises(XianyuProviderRateLimited) as caught:
        adapter.fetch_alerts(request=request, settings=SETTINGS)

    assert caught.value.retry_after_at == datetime.fromtimestamp(
        EPOCH + 45, tz=timezone.utc
    )
    with pytest.raises(XianyuSyncCredentialError):
        request.take_credentials()


@pytest.mark.parametrize(
    "response",
    (
        Response({"code": 0, "data": {"count": 2, "list": []}}),
        Response({"code": 0, "data": {"count": "not-an-int", "list": []}}),
        Response({"code": 1, "msg": "secret provider detail"}),
        Response(json_error=ValueError("secret invalid JSON body")),
        RuntimeError("secret transport detail"),
    ),
)
def test_adapter_maps_partial_rejected_and_transport_failures_without_details(
    response,
):
    adapter = RequestsXianyuProviderAdapter(
        http_client=Client((response,)),
        epoch_seconds=lambda: EPOCH,
    )

    with pytest.raises(XianyuProviderError) as caught:
        adapter.fetch_alerts(request=_request(), settings=SETTINGS)

    assert "secret" not in str(caught.value)


def test_adapter_rejects_duplicate_order_across_pages():
    client = Client(
        (
            Response(
                {
                    "code": 0,
                    "data": {
                        "count": 2,
                        "list": [{"order_no": "DUPLICATE", "pay_amount": 6000}],
                    },
                }
            ),
            Response(
                {
                    "code": 0,
                    "data": {
                        "count": 2,
                        "list": [{"order_no": "DUPLICATE", "pay_amount": 6000}],
                    },
                }
            ),
        )
    )

    with pytest.raises(XianyuProviderError) as caught:
        RequestsXianyuProviderAdapter(
            http_client=client,
            epoch_seconds=lambda: EPOCH,
        ).fetch_alerts(request=_request(), settings=SETTINGS)

    assert caught.value.safe_code == "PROVIDER_RESPONSE_INCONSISTENT"
