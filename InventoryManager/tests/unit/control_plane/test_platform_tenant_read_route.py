from __future__ import annotations

from flask import Flask

from app.routes.platform_identity_api import bp
from app.services.platform_tenant_read import (
    PLATFORM_TENANT_READ_HTTP_RUNTIME_EXTENSION,
)


class _TenantReadRuntime:
    def __init__(self) -> None:
        self.calls = []

    def list_rentals(
        self,
        *,
        flask_request,
        tenant_id,
        query_arguments,
    ):
        self.calls.append(
            {
                "method": flask_request.method,
                "tenant_id": tenant_id,
                "query": query_arguments.to_dict(flat=False),
            }
        )
        return {
            "items": [],
            "page": 2,
            "page_size": 25,
            "has_more": False,
            "status_filter": "shipped",
        }

    def get_rental_customer_pii(
        self,
        *,
        flask_request,
        tenant_id,
        rental_id,
        query_arguments,
    ):
        self.calls.append(
            {
                "method": flask_request.method,
                "tenant_id": tenant_id,
                "rental_id": rental_id,
                "query": query_arguments.to_dict(flat=False),
            }
        )
        return {
            "rental_id": int(rental_id),
            "customer": {
                "name": "张三",
                "phone": "13800138000",
                "address": {
                    "province": "广东省",
                    "city": "深圳市",
                    "district": "南山区",
                    "detail": "科技园 1 号",
                },
            },
        }

    def list_devices(
        self,
        *,
        flask_request,
        tenant_id,
        query_arguments,
    ):
        return self._list_simple(
            flask_request,
            tenant_id,
            query_arguments,
            resource="devices",
        )

    def list_warehouses(
        self,
        *,
        flask_request,
        tenant_id,
        query_arguments,
    ):
        return self._list_simple(
            flask_request,
            tenant_id,
            query_arguments,
            resource="warehouses",
        )

    def _list_simple(
        self,
        flask_request,
        tenant_id,
        query_arguments,
        *,
        resource,
    ):
        self.calls.append(
            {
                "method": flask_request.method,
                "tenant_id": tenant_id,
                "resource": resource,
                "query": query_arguments.to_dict(flat=False),
            }
        )
        return {"items": [], "page": 1, "page_size": 25, "has_more": False}


def _app(runtime=None) -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    if runtime is not None:
        app.extensions[PLATFORM_TENANT_READ_HTTP_RUNTIME_EXTENSION] = runtime
    app.register_blueprint(bp)
    return app


def test_route_delegates_one_tenant_query_and_protects_response_cache() -> None:
    runtime = _TenantReadRuntime()
    response = _app(runtime).test_client().get(
        "/platform/api/tenants/tenant-a/read/rentals"
        "?page=2&page_size=25&status=shipped"
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "items": [],
        "page": 2,
        "page_size": 25,
        "has_more": False,
        "status_filter": "shipped",
    }
    assert runtime.calls == [
        {
            "method": "GET",
            "tenant_id": "tenant-a",
            "query": {
                "page": ["2"],
                "page_size": ["25"],
                "status": ["shipped"],
            },
        }
    ]
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Pragma"] == "no-cache"


def test_route_without_runtime_fails_closed() -> None:
    response = _app().test_client().get(
        "/platform/api/tenants/tenant-a/read/rentals"
    )

    assert response.status_code == 503
    assert response.get_json()["success"] is False
    assert response.headers["Cache-Control"] == "private, no-store"


def test_pii_route_delegates_exact_resource_and_reason() -> None:
    runtime = _TenantReadRuntime()
    response = _app(runtime).test_client().get(
        "/platform/api/tenants/tenant-a/read/rentals/42/customer-pii"
        "?reason=support_case"
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["rental_id"] == 42
    assert runtime.calls == [
        {
            "method": "GET",
            "tenant_id": "tenant-a",
            "rental_id": "42",
            "query": {"reason": ["support_case"]},
        }
    ]
    assert response.headers["Cache-Control"] == "private, no-store"


def test_device_and_warehouse_routes_share_the_same_runtime_contract() -> None:
    runtime = _TenantReadRuntime()
    client = _app(runtime).test_client()
    devices = client.get(
        "/platform/api/tenants/tenant-a/read/devices"
        "?page_size=25&lifecycle_status=active"
    )
    warehouses = client.get(
        "/platform/api/tenants/tenant-a/read/warehouses"
        "?page_size=25&status=active&setup_state=ready"
    )

    assert devices.status_code == 200
    assert warehouses.status_code == 200
    assert runtime.calls == [
        {
            "method": "GET",
            "tenant_id": "tenant-a",
            "resource": "devices",
            "query": {
                "page_size": ["25"],
                "lifecycle_status": ["active"],
            },
        },
        {
            "method": "GET",
            "tenant_id": "tenant-a",
            "resource": "warehouses",
            "query": {
                "page_size": ["25"],
                "status": ["active"],
                "setup_state": ["ready"],
            },
        },
    ]
