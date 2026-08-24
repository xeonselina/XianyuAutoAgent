from uuid import uuid4

from app import create_app
from app.services.tenant_integrations import (
    TENANT_INTEGRATION_HTTP_RUNTIME_EXTENSION,
    TenantIntegrationInputRejected,
    TenantIntegrationSmsRateLimited,
)


class _Runtime:
    def __init__(self):
        self.calls = []
        self.error = None

    def _result(self, operation, **kwargs):
        self.calls.append((operation, kwargs))
        if self.error is not None:
            raise self.error
        return {"operation": operation}

    def list_integrations(self, **kwargs):
        return self._result("list", **kwargs)

    def create_integration(self, **kwargs):
        return self._result("create", **kwargs)

    def request_credential_challenge(self, **kwargs):
        return self._result("challenge", **kwargs)

    def confirm_credential_change(self, **kwargs):
        return self._result("confirm", **kwargs)


def test_routes_fail_closed_without_integration_runtime():
    app = create_app("testing")
    response = app.test_client().get("/api/integrations")

    assert response.status_code == 503
    assert response.get_json() == {
        "success": False,
        "message": "租户集成服务尚未就绪",
    }
    assert response.headers["Cache-Control"] == "private, no-store"


def test_metadata_and_write_only_credential_routes_delegate_exact_payload():
    app = create_app("testing")
    runtime = _Runtime()
    app.extensions[TENANT_INTEGRATION_HTTP_RUNTIME_EXTENSION] = runtime
    client = app.test_client()
    integration_id = str(uuid4())
    secret_marker = "must-stay-write-only"

    assert client.get("/api/integrations").status_code == 200
    created = client.post(
        "/api/integrations",
        json={"provider": "sf", "name": "主连接"},
    )
    challenged = client.post(
        f"/api/integrations/{integration_id}/credential-challenges",
        json={"credentials": {"checkword": secret_marker}},
    )
    confirmed = client.post(
        f"/api/integrations/{integration_id}/credential-confirm",
        json={"credentials": {"checkword": secret_marker}, "code": "123456"},
    )

    assert created.status_code == 201
    assert challenged.status_code == 202
    assert confirmed.status_code == 200
    assert [call[0] for call in runtime.calls] == [
        "list",
        "create",
        "challenge",
        "confirm",
    ]
    assert runtime.calls[2][1]["integration_id"] == integration_id
    assert runtime.calls[3][1]["integration_id"] == integration_id
    assert secret_marker not in challenged.get_data(as_text=True)
    assert secret_marker not in confirmed.get_data(as_text=True)
    assert all(
        response.headers["Cache-Control"] == "private, no-store"
        for response in (created, challenged, confirmed)
    )


def test_route_translates_input_rejection_without_echoing_secret():
    app = create_app("testing")
    runtime = _Runtime()
    runtime.error = TenantIntegrationInputRejected()
    app.extensions[TENANT_INTEGRATION_HTTP_RUNTIME_EXTENSION] = runtime
    marker = "credential-marker-must-not-echo"

    response = app.test_client().post(
        "/api/integrations",
        json={"credentials": {"app_secret": marker}},
    )

    assert response.status_code == 400
    assert response.get_json()["data"]["code"] == (
        "TENANT_INTEGRATION_INPUT_INVALID"
    )
    assert marker not in response.get_data(as_text=True)


def test_sms_throttle_returns_bounded_retry_after():
    app = create_app("testing")
    runtime = _Runtime()
    runtime.error = TenantIntegrationSmsRateLimited(
        retry_after_seconds=999_999
    )
    app.extensions[TENANT_INTEGRATION_HTTP_RUNTIME_EXTENSION] = runtime

    response = app.test_client().post(
        f"/api/integrations/{uuid4()}/credential-challenges",
        json={},
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "86400"
    assert response.get_json()["data"]["code"] == (
        "TENANT_INTEGRATION_SMS_RATE_LIMITED"
    )
