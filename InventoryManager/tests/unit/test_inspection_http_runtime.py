from __future__ import annotations

from flask import Flask

from app.routes.inspection import inspection_bp
from app.services.inspection.http_runtime import (
    INSPECTION_SAAS_HTTP_RUNTIME_EXTENSION,
)
from config import Config, DockerConfig, ProductionConfig, TestingConfig


class _Runtime:
    def __init__(self, result):
        self.result = result
        self.calls: list[tuple[str, object]] = []

    def latest_by_device_id(self, *, flask_request, device_id):
        self.calls.append((flask_request.path, device_id))
        return self.result

    def latest_by_device_name(self, *, flask_request, device_name):
        self.calls.append((flask_request.path, device_name))
        return self.result

    def create_inspection(self, *, flask_request, payload):
        self.calls.append((flask_request.path, payload))
        return self.result

    def get_inspection(self, *, flask_request, inspection_id):
        self.calls.append((flask_request.path, inspection_id))
        return self.result

    def update_inspection(self, *, flask_request, inspection_id, payload):
        self.calls.append((flask_request.path, (inspection_id, payload)))
        return self.result

    def list_inspections(self, *, flask_request, filters):
        self.calls.append((flask_request.path, filters))
        return self.result


def _app(*, testing=False, legacy=False, runtime=None):
    app = Flask(__name__)
    app.config.update(
        TESTING=testing,
        ENABLE_LEGACY_SINGLE_TENANT_INSPECTION_API=legacy,
    )
    if runtime is not None:
        app.extensions[INSPECTION_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
    app.register_blueprint(inspection_bp)
    return app


def test_production_inspection_routes_fail_closed_without_runtime(monkeypatch):
    monkeypatch.setattr(
        "app.routes.inspection.InspectionService.get_inspection_records",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy inspection service must not run")
        ),
    )
    client = _app(testing=False, legacy=True).test_client()

    response = client.get("/api/inspections")

    assert response.status_code == 503
    assert response.get_json() == {
        "success": False,
        "message": "租户验货服务尚未就绪",
    }
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Pragma"] == "no-cache"


def test_only_testing_config_enables_legacy_inspection_compatibility():
    assert Config.ENABLE_LEGACY_SINGLE_TENANT_INSPECTION_API is False
    assert ProductionConfig.ENABLE_LEGACY_SINGLE_TENANT_INSPECTION_API is False
    assert DockerConfig.ENABLE_LEGACY_SINGLE_TENANT_INSPECTION_API is False
    assert TestingConfig.ENABLE_LEGACY_SINGLE_TENANT_INSPECTION_API is True


def test_all_migrated_inspection_routes_use_protocol_runtime():
    result = {"id": 7, "status": "normal"}
    runtime = _Runtime(result)
    client = _app(runtime=runtime).test_client()

    responses = [
        client.get("/api/inspections/rental/latest/3"),
        client.get("/api/inspections/rental/latest/by-name/device-3"),
        client.post("/api/inspections", json={"rental_id": 4}),
        client.get("/api/inspections/7"),
        client.put("/api/inspections/7", json={"check_items": []}),
        client.get("/api/inspections?status=normal&page=2"),
    ]

    assert [response.status_code for response in responses] == [
        200,
        200,
        201,
        200,
        200,
        200,
    ]
    assert all(
        response.headers["Cache-Control"] == "private, no-store"
        for response in responses
    )
    assert runtime.calls == [
        ("/api/inspections/rental/latest/3", 3),
        ("/api/inspections/rental/latest/by-name/device-3", "device-3"),
        ("/api/inspections", {"rental_id": 4}),
        ("/api/inspections/7", 7),
        ("/api/inspections/7", (7, {"check_items": []})),
        ("/api/inspections", {"status": "normal", "page": "2"}),
    ]


def test_missing_runtime_result_is_not_found_without_global_query():
    client = _app(runtime=_Runtime(None)).test_client()

    latest = client.get("/api/inspections/rental/latest/3")
    detail = client.get("/api/inspections/7")

    assert latest.status_code == 404
    assert detail.status_code == 404

