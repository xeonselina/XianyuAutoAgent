from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask

from inventory_control.models.operations import PlatformOperationalSignal
from inventory_control.models.recovery import DisasterRecoveryRun
from inventory_control.operations import (
    BoundedHealthAdmissionGate,
    HealthEndpointService,
    HealthTransactionRequired,
    HostRecoveryMarker,
    HostRecoveryMarkerMode,
    OperationalEnvironment,
    create_health_blueprint,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
INSTALLATION = "1" * 64
MARKER = "2" * 64


@pytest.fixture
def database(mysql_control_database):
    return mysql_control_database


def _service(*, clock=lambda _session: NOW):
    return HealthEndpointService(
        environment=OperationalEnvironment.TEST,
        database_clock=clock,
    )


def _marker(mode=HostRecoveryMarkerMode.NORMAL):
    return HostRecoveryMarker(
        mode=mode,
        installation_fingerprint=INSTALLATION,
        marker_fingerprint=MARKER,
    )


def _run(*, status="completed", installation=INSTALLATION, marker=MARKER):
    return DisasterRecoveryRun(
        kind="host_restore",
        policy_version=1,
        status=status,
        expected_survivor_count=0,
        actual_survivor_count=0,
        host_installation_fingerprint=installation,
        deployment_marker_fingerprint=marker,
        row_version=1,
        started_at=NOW - timedelta(hours=1),
        reviewing_at=NOW - timedelta(minutes=30),
        completed_at=NOW if status == "completed" else None,
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW,
    )


def _signal(key, *, status="healthy", deadline=None):
    source, component, severity, observed_result = {
        "worker.heartbeat": ("worker", "worker", "p2", "heartbeat"),
        "evaluator.heartbeat": (
            "evaluator",
            "evaluator",
            "p2",
            "heartbeat",
        ),
        "notification.delivery": (
            "notification_adapter",
            "notification",
            "p2",
            "ok",
        ),
    }[key]
    unhealthy = status != "healthy"
    freshness_deadline = deadline or NOW + timedelta(seconds=50)
    observed_at = min(
        NOW - timedelta(seconds=10),
        freshness_deadline - timedelta(seconds=60),
    )
    return PlatformOperationalSignal(
        signal_key=key,
        environment="test",
        source=source,
        component=component,
        severity=severity,
        policy_version=1,
        failure_threshold=1,
        recovery_threshold=1,
        freshness_window_seconds=60,
        repeat_interval_seconds=60,
        observed_status="failure" if unhealthy else "ok",
        observed_result_class="delivery_failure" if unhealthy else observed_result,
        effective_status=status,
        result_class="delivery_failure" if unhealthy else observed_result,
        consecutive_failures=1 if unhealthy else 0,
        consecutive_recoveries=0 if unhealthy else 1,
        state_generation=1,
        alert_generation=1 if unhealthy else 0,
        lifecycle_sequence=1 if unhealthy else 0,
        active_alert_fingerprint="a" * 64 if unhealthy else None,
        alert_triggered_at=NOW if unhealthy else None,
        next_repeat_at=NOW + timedelta(minutes=1) if unhealthy else None,
        observed_at=observed_at,
        freshness_deadline_at=freshness_deadline,
        evaluated_at=NOW,
        row_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _assert_fixed(result, expected_status):
    assert result.status_code == expected_status
    assert result.available is (expected_status == 200)
    assert result.body in {b'{"status":"ok"}\n', b'{"status":"unavailable"}\n'}
    assert result.headers == {
        "Cache-Control": "no-store",
        "Content-Type": "application/json",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
    }
    body = result.body.decode()
    for forbidden in ("tenant", "database", "recovery", INSTALLATION, MARKER):
        assert forbidden not in body


def test_normal_external_health_is_one_read_and_does_not_require_run(database):
    with database.transaction() as session:
        result = _service().external(session, marker=_marker())
        assert not session.new and not session.dirty and not session.deleted
    _assert_fixed(result, 200)


@pytest.mark.parametrize(
    ("status", "installation", "marker"),
    [
        ("reviewing", INSTALLATION, MARKER),
        ("completed", "3" * 64, MARKER),
        ("completed", INSTALLATION, "4" * 64),
    ],
)
def test_host_restore_external_health_requires_exact_completed_current_run(
    database, status, installation, marker
):
    with database.transaction() as session:
        session.add(_run(status=status, installation=installation, marker=marker))
    with database.transaction() as session:
        result = _service().external(
            session,
            marker=_marker(HostRecoveryMarkerMode.HOST_RESTORE),
        )
    _assert_fixed(result, 503)


def test_completed_matching_host_restore_is_external_healthy(database):
    with database.transaction() as session:
        session.add(_run())
    with database.transaction() as session:
        result = _service().external(
            session,
            marker=_marker(HostRecoveryMarkerMode.HOST_RESTORE),
        )
    _assert_fixed(result, 200)


def test_missing_or_malformed_marker_is_fixed_unavailable(database):
    with database.transaction() as session:
        result = _service().external(session, marker=None)
    _assert_fixed(result, 503)
    with pytest.raises(ValueError, match="fingerprint"):
        HostRecoveryMarker(
            mode=HostRecoveryMarkerMode.NORMAL,
            installation_fingerprint="not-valid",
            marker_fingerprint=MARKER,
        )


def test_monitor_requires_both_fresh_heartbeats_and_clear_delivery_latch(database):
    with database.transaction() as session:
        session.add_all(
            [
                _signal("worker.heartbeat"),
                _signal("evaluator.heartbeat"),
                _signal("notification.delivery", deadline=NOW - timedelta(days=1)),
            ]
        )
    with database.transaction() as session:
        result = _service().monitor(session)
        assert not session.new and not session.dirty and not session.deleted
    _assert_fixed(result, 200)


@pytest.mark.parametrize(
    "failure",
    ["missing_worker", "stale_worker", "stale_evaluator", "delivery_latched"],
)
def test_monitor_fails_closed_for_missing_stale_or_latched_state(database, failure):
    rows = {
        "worker.heartbeat": _signal("worker.heartbeat"),
        "evaluator.heartbeat": _signal("evaluator.heartbeat"),
        "notification.delivery": _signal("notification.delivery"),
    }
    if failure == "missing_worker":
        rows.pop("worker.heartbeat")
    elif failure == "stale_worker":
        rows["worker.heartbeat"].freshness_deadline_at = NOW - timedelta(seconds=1)
    elif failure == "stale_evaluator":
        rows["evaluator.heartbeat"].freshness_deadline_at = NOW - timedelta(seconds=1)
    else:
        rows["notification.delivery"] = _signal(
            "notification.delivery", status="unhealthy"
        )
    with database.transaction() as session:
        session.add_all(rows.values())
    with database.transaction() as session:
        result = _service().monitor(session)
    _assert_fixed(result, 503)


def test_clock_or_query_failure_returns_fixed_503(database):
    def broken_clock(_session):
        raise RuntimeError("sensitive database detail")

    with database.transaction() as session:
        result = _service(clock=broken_clock).monitor(session)
    _assert_fixed(result, 503)
    assert b"sensitive" not in result.body


def test_both_health_reads_require_caller_owned_transaction(database):
    session = database.new_session()
    try:
        with pytest.raises(HealthTransactionRequired):
            _service().external(session, marker=_marker())
        with pytest.raises(HealthTransactionRequired):
            _service().monitor(session)
    finally:
        session.close()


def _http_app(
    database,
    *,
    service=None,
    marker_reader=lambda: _marker(),
    external_admission=lambda: True,
    monitor_admission=lambda: True,
):
    app = Flask(__name__)
    app.register_blueprint(
        create_health_blueprint(
            control_database=database,
            service=service or _service(),
            marker_reader=marker_reader,
            external_admission=external_admission,
            monitor_admission=monitor_admission,
        )
    )
    return app


def test_flask_adapter_exposes_only_fixed_no_store_response(database):
    app = _http_app(database)
    response = app.test_client().get(
        "/health/external",
        headers={
            "Cookie": "tenant=ignored",
            "Authorization": "Bearer ignored",
        },
    )
    assert response.status_code == 200
    assert response.get_data() == b'{"status":"ok"}\n'
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_query_parameters_or_failed_admission_never_borrow_database(database):
    engine_calls = {"connect": 0}

    from sqlalchemy import event

    @event.listens_for(database.engine, "checkout")
    def count_checkout(*_args):
        engine_calls["connect"] += 1

    app = _http_app(
        database,
        external_admission=lambda: False,
        monitor_admission=lambda: False,
    )
    client = app.test_client()
    assert client.get("/health/external").status_code == 503
    assert client.get("/health/monitor").status_code == 503
    assert client.get("/health/external?tenant=secret").status_code == 503
    assert engine_calls["connect"] == 0


def test_external_and_monitor_use_independent_admission_gates(database):
    with database.transaction() as session:
        session.add_all(
            [
                _signal("worker.heartbeat"),
                _signal("evaluator.heartbeat"),
                _signal("notification.delivery"),
            ]
        )
    app = _http_app(
        database,
        external_admission=lambda: False,
        monitor_admission=lambda: True,
    )
    client = app.test_client()
    assert client.get("/health/external").status_code == 503
    assert client.get("/health/monitor").status_code == 200


def test_bounded_admission_holds_nonblocking_concurrency_lease() -> None:
    gate = BoundedHealthAdmissionGate(
        max_concurrent=1,
        max_requests=10,
        interval_seconds=60,
    )

    with gate() as first:
        assert first is True
        with gate() as concurrent:
            assert concurrent is False
    with gate() as after_release:
        assert after_release is True


def test_bounded_admission_rate_window_is_fixed_and_fail_closed() -> None:
    current = {"value": 100.0}
    gate = BoundedHealthAdmissionGate(
        max_concurrent=1,
        max_requests=2,
        interval_seconds=60,
        monotonic_clock=lambda: current["value"],
    )

    with gate() as first:
        assert first is True
    with gate() as second:
        assert second is True
    with gate() as exhausted:
        assert exhausted is False
    current["value"] = 160.1
    with gate() as refreshed:
        assert refreshed is True


def test_marker_or_database_failure_is_never_serialized(database):
    def marker_failure():
        raise RuntimeError("host-internal-sensitive-detail")

    app = _http_app(database, marker_reader=marker_failure)
    response = app.test_client().get("/health/external")
    assert response.status_code == 503
    assert response.get_data() == b'{"status":"unavailable"}\n'
    assert b"sensitive" not in response.get_data()
