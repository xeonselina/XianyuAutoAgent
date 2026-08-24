from datetime import datetime, timedelta, timezone

import pytest

from app.services.xianyu_sync import (
    XianyuAlertFact,
    XianyuProviderError,
    XianyuProviderRateLimited,
    XianyuProviderSettings,
    XianyuProviderSyncResponse,
    XianyuSyncProviderDispatcher,
)
from inventory_control.integrations import (
    XianyuSyncCredentialError,
    XianyuSyncExecutionContext,
    XianyuSyncProviderRequest,
)


TENANT = "81000000-0000-4000-8000-000000000001"
INTEGRATION = "81000000-0000-4000-8000-000000000002"
REVISION = "81000000-0000-4000-8000-000000000003"
NOW = datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc)
SETTINGS = XianyuProviderSettings(
    endpoint="https://open.goofish.pro",
    connect_timeout_seconds=3,
    read_timeout_seconds=15,
    rate_limit_retry_seconds=45,
    page_size=100,
    max_pages=20,
)


def _request():
    return XianyuSyncProviderRequest(
        context=XianyuSyncExecutionContext(
            tenant_uuid=TENANT,
            integration_uuid=INTEGRATION,
            secret_revision_uuid=REVISION,
            integration_row_version=4,
            revision_row_version=3,
        ),
        provider_cursor="cursor-before",
        credentials={"app_key": "app-value", "app_secret": "secret-value"},
    )


def test_dispatch_projects_typed_success_and_consumes_credentials():
    class Adapter:
        seen = None

        def fetch_alerts(self, *, request, settings):
            self.seen = (
                dict(request.take_credentials()),
                request.provider_cursor,
                settings.read_timeout_seconds,
            )
            return XianyuProviderSyncResponse(
                alerts=(XianyuAlertFact(order_no="ORDER-1", pay_amount=6000),),
                next_cursor="cursor-after",
            )

    request = _request()
    adapter = Adapter()
    result = XianyuSyncProviderDispatcher.dispatch(
        request=request,
        adapter=adapter,
        settings=SETTINGS,
    )

    assert adapter.seen == (
        {"app_key": "app-value", "app_secret": "secret-value"},
        "cursor-before",
        15,
    )
    assert result.status == "succeeded"
    assert result.provider_cursor == "cursor-after"
    assert [alert.order_no for alert in result.alerts] == ["ORDER-1"]
    with pytest.raises(XianyuSyncCredentialError):
        request.take_credentials()


def test_dispatch_projects_rate_limit_without_exposing_exception_details():
    retry_at = NOW + timedelta(seconds=45)

    class Adapter:
        def fetch_alerts(self, **_kwargs):
            raise XianyuProviderRateLimited(retry_after_at=retry_at)

    result = XianyuSyncProviderDispatcher.dispatch(
        request=_request(),
        adapter=Adapter(),
        settings=SETTINGS,
    )

    assert result.status == "rate_limited"
    assert result.safe_error_code == "PROVIDER_RATE_LIMITED"
    assert result.retry_after_at == retry_at


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    (
        (XianyuProviderError("PROVIDER_REJECTED"), "PROVIDER_REJECTED"),
        (RuntimeError("secret-value leaked upstream"), "PROVIDER_UNAVAILABLE"),
    ),
)
def test_dispatch_maps_failures_to_safe_codes(failure, expected_code):
    class Adapter:
        def fetch_alerts(self, **_kwargs):
            raise failure

    request = _request()
    result = XianyuSyncProviderDispatcher.dispatch(
        request=request,
        adapter=Adapter(),
        settings=SETTINGS,
    )

    assert result.status == "failed"
    assert result.safe_error_code == expected_code
    assert "secret-value" not in repr(result)
    with pytest.raises(XianyuSyncCredentialError):
        request.take_credentials()


def test_dispatch_rejects_untyped_provider_response():
    class Adapter:
        def fetch_alerts(self, **_kwargs):
            return {"alerts": []}

    result = XianyuSyncProviderDispatcher.dispatch(
        request=_request(),
        adapter=Adapter(),
        settings=SETTINGS,
    )

    assert result.status == "failed"
    assert result.safe_error_code == "PROVIDER_RESPONSE_INVALID"


@pytest.mark.parametrize(
    "changes",
    (
        {"endpoint": "http://insecure.example"},
        {"endpoint": "https://user:password@provider.example"},
        {"endpoint": "https://provider.example?token=secret"},
        {"connect_timeout_seconds": 0},
        {"read_timeout_seconds": 61},
        {"rate_limit_retry_seconds": 0},
        {"page_size": 101},
        {"max_pages": 0},
    ),
)
def test_provider_settings_are_explicit_and_bounded(changes):
    values = {
        "endpoint": SETTINGS.endpoint,
        "connect_timeout_seconds": SETTINGS.connect_timeout_seconds,
        "read_timeout_seconds": SETTINGS.read_timeout_seconds,
        "rate_limit_retry_seconds": SETTINGS.rate_limit_retry_seconds,
        "page_size": SETTINGS.page_size,
        "max_pages": SETTINGS.max_pages,
    }
    values.update(changes)

    with pytest.raises(ValueError):
        XianyuProviderSettings(**values)
