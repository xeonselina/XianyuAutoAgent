"""Public Gantt reorder routes never fall back to the legacy signer."""

from __future__ import annotations

from app import create_app
from app.services.gantt.gantt_service import GanttService
from app.services.gantt.http_runtime import (
    GANTT_SAAS_HTTP_RUNTIME_EXTENSION,
)
from app.services.gantt.reorder_service import GanttReorderService
from config import Config, DockerConfig, ProductionConfig, TestingConfig


class _Runtime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def analyze(self, *, flask_request):
        self.calls.append(("analyze", flask_request.path))
        return {"overlaps": []}

    def view(self, *, flask_request, query):
        self.calls.append(("view", dict(query)))
        return {
            "date_range": {"start": "2026-08-22", "end": "2026-09-06"},
            "devices": [],
            "rentals": [],
        }

    def preview(self, *, flask_request, decisions):
        self.calls.append(("preview", decisions))
        return {"token": "saas-proof", "changes": []}

    def execute(self, *, flask_request, token):
        self.calls.append(("execute", token))
        return {"changes": [], "relay_changes": []}


def test_reorder_routes_fail_closed_without_explicit_saas_runtime(monkeypatch):
    app = create_app("testing")
    client = app.test_client()

    monkeypatch.setattr(
        GanttReorderService,
        "execute",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy execute must be unreachable")
        ),
    )

    analyze = client.post("/api/gantt/reorder/analyze")
    preview = client.post(
        "/api/gantt/reorder/preview", json={"decisions": []}
    )
    execute = client.post(
        "/api/gantt/reorder/execute", json={"token": "legacy-token"}
    )

    assert (analyze.status_code, preview.status_code, execute.status_code) == (
        503,
        503,
        503,
    )
    assert all(
        response.headers.get("Cache-Control") == "private, no-store"
        for response in (analyze, preview, execute)
    )


def test_reorder_routes_delegate_only_to_protocol_complete_runtime():
    app = create_app("testing")
    runtime = _Runtime()
    app.extensions[GANTT_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
    client = app.test_client()

    analyze = client.post("/api/gantt/reorder/analyze")
    preview = client.post(
        "/api/gantt/reorder/preview",
        json={"decisions": [{"action": "keep"}]},
    )
    execute = client.post(
        "/api/gantt/reorder/execute", json={"token": "saas-proof"}
    )

    assert analyze.status_code == 200
    assert preview.get_json()["data"]["token"] == "saas-proof"
    assert execute.status_code == 200
    assert all(
        response.headers.get("Cache-Control") == "private, no-store"
        for response in (analyze, preview, execute)
    )
    assert runtime.calls == [
        ("analyze", "/api/gantt/reorder/analyze"),
        ("preview", [{"action": "keep"}]),
        ("execute", "saas-proof"),
    ]


def test_normalized_view_delegates_to_explicit_runtime_and_is_not_cached():
    app = create_app("testing")
    runtime = _Runtime()
    app.extensions[GANTT_SAAS_HTTP_RUNTIME_EXTENSION] = runtime

    response = app.test_client().get(
        "/api/gantt/view?start_date=2026-08-22&end_date=2026-08-31"
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.get_json()["data"]["devices"] == []
    assert runtime.calls == [
        (
            "view",
            {"start_date": "2026-08-22", "end_date": "2026-08-31"},
        )
    ]


def test_shape_mismatched_runtime_is_not_accepted():
    app = create_app("testing")
    app.extensions[GANTT_SAAS_HTTP_RUNTIME_EXTENSION] = object()

    response = app.test_client().post("/api/gantt/reorder/analyze")

    assert response.status_code == 503


def test_legacy_single_tenant_gantt_reads_are_test_only_by_default():
    assert Config.ENABLE_LEGACY_SINGLE_TENANT_GANTT_READS is False
    assert ProductionConfig.ENABLE_LEGACY_SINGLE_TENANT_GANTT_READS is False
    assert DockerConfig.ENABLE_LEGACY_SINGLE_TENANT_GANTT_READS is False
    assert TestingConfig.ENABLE_LEGACY_SINGLE_TENANT_GANTT_READS is True


def test_legacy_single_tenant_reads_fail_closed_before_global_query(
    monkeypatch,
):
    app = create_app("testing")
    app.config["ENABLE_LEGACY_SINGLE_TENANT_GANTT_READS"] = False
    client = app.test_client()

    def global_tenant_query_must_not_run(*_args, **_kwargs):
        raise AssertionError("global single-tenant query must be unreachable")

    monkeypatch.setattr(
        GanttService,
        "get_gantt_data",
        global_tenant_query_must_not_run,
    )
    monkeypatch.setattr(
        GanttService,
        "get_daily_statistics",
        global_tenant_query_must_not_run,
    )
    monkeypatch.setattr(
        GanttService,
        "find_available_slot",
        global_tenant_query_must_not_run,
    )

    responses = (
        client.get("/api/gantt/view"),
        client.get("/api/gantt/data"),
        client.get("/api/gantt/daily-stats"),
        client.post("/api/rentals/find-slot", json={}),
    )

    assert [response.status_code for response in responses] == [
        503,
        503,
        503,
        503,
    ]
    assert responses[0].get_json()["message"] == "租户档期服务尚未就绪"
    assert all(
        response.get_json()["message"] == "租户档期读服务尚未就绪"
        for response in responses[1:]
    )


def test_legacy_single_tenant_read_gate_requires_exact_boolean_true():
    app = create_app("testing")
    app.config["ENABLE_LEGACY_SINGLE_TENANT_GANTT_READS"] = "true"

    response = app.test_client().get("/api/gantt/data")

    assert response.status_code == 503
