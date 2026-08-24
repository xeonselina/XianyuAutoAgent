from __future__ import annotations

from flask import Flask

from app.routes.rental_api import bp as rental_api_blueprint
from app.services.rental.http_runtime import (
    RENTAL_SAAS_HTTP_RUNTIME_EXTENSION,
)
from config import Config, DockerConfig, ProductionConfig, TestingConfig


def _client(*, testing: bool, legacy_flag: object):
    app = Flask(__name__)
    app.config.update(
        TESTING=testing,
        ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API=legacy_flag,
    )
    app.register_blueprint(rental_api_blueprint)
    return app.test_client()


def test_all_rental_routes_fail_closed_before_legacy_handler_in_production(
    monkeypatch,
) -> None:
    def legacy_handler_must_not_run(*_args, **_kwargs):
        raise AssertionError("legacy rental handler must be unreachable")

    monkeypatch.setattr(
        "app.routes.rental_api.RentalHandlers.handle_get_rentals",
        legacy_handler_must_not_run,
    )
    client = _client(testing=False, legacy_flag=True)

    response = client.get("/api/rentals")

    assert response.status_code == 503
    assert response.get_json() == {
        "success": False,
        "message": "租户租赁服务尚未就绪",
    }
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Pragma"] == "no-cache"


def test_test_compatibility_requires_literal_true_flag(monkeypatch) -> None:
    calls: list[str] = []

    def legacy_handler():
        calls.append("called")
        return {"legacy": True}

    monkeypatch.setattr(
        "app.routes.rental_api.RentalHandlers.handle_get_rentals",
        legacy_handler,
    )

    blocked = _client(testing=True, legacy_flag="true").get("/api/rentals")
    allowed = _client(testing=True, legacy_flag=True).get("/api/rentals")

    assert blocked.status_code == 503
    assert allowed.status_code == 200
    assert allowed.get_json() == {"legacy": True}
    assert calls == ["called"]


def test_only_testing_config_enables_legacy_rental_compatibility() -> None:
    assert Config.ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API is False
    assert ProductionConfig.ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API is False
    assert DockerConfig.ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API is False
    assert TestingConfig.ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API is True


class _Runtime:
    def __init__(self, result):
        self.result = result
        self.calls: list[tuple[str, object]] = []

    def get_rental(self, *, flask_request, rental_id):
        self.calls.append((flask_request.path, rental_id))
        return self.result

    def get_edit_context(self, *, flask_request, rental_id):
        self.calls.append((flask_request.path, rental_id))
        return self.result

    def list_rentals(self, *, flask_request, filters):
        self.calls.append((flask_request.path, filters))
        return self.result

    def list_pending_returns(self, *, flask_request, pagination):
        self.calls.append((flask_request.path, pagination))
        return self.result

    def booking_bootstrap(self, *, flask_request):
        self.calls.append((flask_request.path, None))
        return self.result

    def booking_availability(self, *, flask_request, payload):
        self.calls.append((flask_request.path, payload))
        return self.result

    def create_rental(self, *, flask_request, payload):
        self.calls.append((flask_request.path, payload))
        return self.result

    def update_rental(self, *, flask_request, rental_id, payload):
        self.calls.append((flask_request.path, (rental_id, payload)))
        return self.result

    def update_rental_status(self, *, flask_request, rental_id, payload):
        self.calls.append((flask_request.path, (rental_id, payload)))
        return self.result

    def delete_rental(self, *, flask_request, rental_id):
        self.calls.append((flask_request.path, rental_id))
        return self.result


def test_migrated_detail_route_uses_only_protocol_complete_runtime(
    monkeypatch,
) -> None:
    def legacy_handler_must_not_run(*_args, **_kwargs):
        raise AssertionError("legacy rental handler must be unreachable")

    monkeypatch.setattr(
        "app.routes.rental_api.RentalHandlers.handle_get_rental",
        legacy_handler_must_not_run,
    )
    app = Flask(__name__)
    app.config.update(
        TESTING=False,
        ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API=False,
    )
    runtime = _Runtime({"id": 7, "customer_name": "tenant-row"})
    app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
    app.register_blueprint(rental_api_blueprint)

    response = app.test_client().get("/api/rentals/7")

    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "id": 7,
        "customer_name": "tenant-row",
    }
    assert runtime.calls == [("/api/rentals/7", "7")]
    assert response.headers["Cache-Control"] == "private, no-store"


def test_migrated_detail_route_rejects_missing_or_malformed_runtime() -> None:
    app = Flask(__name__)
    app.config.update(
        TESTING=False,
        ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API=False,
    )
    app.register_blueprint(rental_api_blueprint)
    client = app.test_client()

    missing = client.get("/api/rentals/1")
    app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] = object()
    malformed = client.get("/web/rentals/1")

    assert missing.status_code == 503
    assert malformed.status_code == 503
    assert missing.get_json()["message"] == "租户租赁服务尚未就绪"


def test_migrated_detail_route_hides_absent_local_id() -> None:
    app = Flask(__name__)
    app.config.update(
        TESTING=False,
        ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API=False,
    )
    app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] = _Runtime(None)
    app.register_blueprint(rental_api_blueprint)

    response = app.test_client().get("/api/rentals/999")

    assert response.status_code == 404
    assert response.get_json() == {
        "success": False,
        "message": "租赁记录不存在",
    }


def test_edit_context_uses_one_protocol_operation_and_hides_absent_id() -> None:
    result = {
        "rental": {"id": 7, "customer_name": "tenant-row"},
        "warehouses": [],
        "device_models": [],
        "accessory_types": [],
    }
    app = Flask(__name__)
    app.config.update(
        TESTING=False,
        ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API=False,
    )
    runtime = _Runtime(result)
    app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
    app.register_blueprint(rental_api_blueprint)
    client = app.test_client()

    response = client.get("/api/rentals/7/edit-context")
    assert response.status_code == 200
    assert response.get_json()["data"] == result
    assert runtime.calls == [("/api/rentals/7/edit-context", "7")]

    runtime.result = None
    missing = client.get("/api/rentals/999/edit-context")
    assert missing.status_code == 404


def test_migrated_list_route_passes_only_bounded_filter_input_to_runtime() -> None:
    result = {
        "rentals": [{"id": 8}],
        "total": 1,
        "pages": 1,
        "current_page": 2,
        "per_page": 10,
        "has_next": False,
        "has_prev": True,
    }
    app = Flask(__name__)
    app.config.update(
        TESTING=False,
        ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API=False,
    )
    runtime = _Runtime(result)
    app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
    app.register_blueprint(rental_api_blueprint)

    response = app.test_client().get(
        "/api/rentals?page=2&per_page=10&status=shipped"
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == result
    assert runtime.calls == [(
        "/api/rentals",
        {"page": "2", "per_page": "10", "status": "shipped"},
    )]


def test_migrated_pending_return_aliases_use_the_same_runtime_operation() -> None:
    result = {
        "rentals": [{"id": 9, "overdue_days": 0}],
        "count": 1,
        "total": 1,
        "pages": 1,
        "current_page": 1,
        "per_page": 20,
        "has_next": False,
        "has_prev": False,
        "as_of_date": "2026-08-23",
    }
    app = Flask(__name__)
    app.config.update(
        TESTING=False,
        ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API=False,
    )
    runtime = _Runtime(result)
    app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
    app.register_blueprint(rental_api_blueprint)
    client = app.test_client()

    canonical = client.get("/api/rentals/pending-returns?per_page=20")
    alias = client.get("/api/rentals/due-today?per_page=20")

    assert canonical.status_code == 200
    assert alias.status_code == 200
    assert canonical.get_json()["data"] == alias.get_json()["data"]
    assert runtime.calls == [
        ("/api/rentals/pending-returns", {"per_page": "20"}),
        ("/api/rentals/due-today", {"per_page": "20"}),
    ]


def test_booking_bootstrap_uses_explicit_runtime_and_no_store_response() -> None:
    result = {
        "warehouses": [{"id": 2, "name": "华东仓"}],
        "recent_warehouse_id": 2,
        "device_models": [{"id": 1, "name": "x200u"}],
        "accessory_types": [],
    }
    app = Flask(__name__)
    app.config.update(
        TESTING=False,
        ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API=False,
    )
    runtime = _Runtime(result)
    app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
    app.register_blueprint(rental_api_blueprint)

    response = app.test_client().get("/api/rental-booking/bootstrap")

    assert response.status_code == 200
    assert response.get_json()["data"] == result
    assert response.headers["Cache-Control"] == "private, no-store"
    assert runtime.calls == [("/api/rental-booking/bootstrap", None)]


def test_booking_availability_passes_json_only_to_explicit_runtime() -> None:
    result = {
        "candidates": [{"device": {"id": 7}, "available": True}],
        "estimate_by_warehouse": {},
    }
    app = Flask(__name__)
    app.config.update(
        TESTING=False,
        ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API=False,
    )
    runtime = _Runtime(result)
    app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
    app.register_blueprint(rental_api_blueprint)
    payload = {
        "start_date": "2026-09-01",
        "end_date": "2026-09-03",
        "model_id": 1,
    }

    response = app.test_client().post(
        "/api/rental-booking/availability",
        json=payload,
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == result
    assert response.headers["Cache-Control"] == "private, no-store"
    assert runtime.calls == [
        ("/api/rental-booking/availability", payload)
    ]


def test_create_rental_uses_explicit_runtime_and_returns_created() -> None:
    result = {
        "main_rental": {"id": 42},
        "accessory_rentals": [],
        "warnings": [],
        "refresh_scope": "current_window",
    }
    app = Flask(__name__)
    app.config.update(
        TESTING=False,
        ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API=False,
    )
    runtime = _Runtime(result)
    app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
    app.register_blueprint(rental_api_blueprint)
    payload = {"device_id": 7}

    response = app.test_client().post("/api/rentals", json=payload)

    assert response.status_code == 201
    assert response.get_json()["data"] == result
    assert response.headers["Cache-Control"] == "private, no-store"
    assert runtime.calls == [("/api/rentals", payload)]


def test_update_rental_aliases_pass_id_and_json_to_explicit_runtime() -> None:
    result = {
        "rental": {"id": 42},
        "warnings": [],
        "refresh_scope": "current_window",
    }
    app = Flask(__name__)
    app.config.update(
        TESTING=False,
        ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API=False,
    )
    runtime = _Runtime(result)
    app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
    app.register_blueprint(rental_api_blueprint)
    payload = {"device_id": 7}

    client = app.test_client()
    canonical = client.put("/api/rentals/42", json=payload)
    web_alias = client.put("/web/rentals/42", json=payload)

    assert canonical.status_code == 200
    assert web_alias.status_code == 200
    assert canonical.get_json()["data"] == result
    assert web_alias.get_json()["data"] == result
    assert runtime.calls == [
        ("/api/rentals/42", ("42", payload)),
        ("/web/rentals/42", ("42", payload)),
    ]


def test_status_route_passes_id_and_json_to_explicit_runtime() -> None:
    result = {
        "id": 42,
        "status": "returned",
        "refresh_scope": "current_window",
    }
    app = Flask(__name__)
    app.config.update(
        TESTING=False,
        ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API=False,
    )
    runtime = _Runtime(result)
    app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
    app.register_blueprint(rental_api_blueprint)

    response = app.test_client().put(
        "/api/rentals/42/status",
        json={"status": "returned"},
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == result
    assert runtime.calls == [
        ("/api/rentals/42/status", ("42", {"status": "returned"})),
    ]


def test_delete_aliases_use_explicit_runtime() -> None:
    result = {
        "id": 42,
        "deleted": True,
        "refresh_scope": "current_window",
    }
    app = Flask(__name__)
    app.config.update(
        TESTING=False,
        ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API=False,
    )
    runtime = _Runtime(result)
    app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
    app.register_blueprint(rental_api_blueprint)
    client = app.test_client()

    canonical = client.delete("/api/rentals/42")
    web_alias = client.delete("/web/rentals/42")

    assert canonical.status_code == 200
    assert web_alias.status_code == 200
    assert canonical.get_json()["data"] == result
    assert web_alias.get_json()["data"] == result
    assert runtime.calls == [
        ("/api/rentals/42", "42"),
        ("/web/rentals/42", "42"),
    ]
