"""Flask adapter for the two fixed SaaS Core health endpoints."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager

from flask import Blueprint, Response, request

from inventory_control.database import ControlDatabase

from .health import (
    HealthEndpointResult,
    HealthEndpointService,
    HostRecoveryMarker,
)


AdmissionGate = Callable[[], bool | AbstractContextManager[bool]]
MarkerReader = Callable[[], HostRecoveryMarker]


class BoundedHealthAdmissionGate:
    """Non-blocking concurrency and fixed-window request budget.

    One instance must be composed per endpoint.  The lease holds its semaphore
    until the endpoint finishes its control-database read, so external and
    monitor probes cannot consume an unbounded number of control connections.
    """

    def __init__(
        self,
        *,
        max_concurrent: int,
        max_requests: int,
        interval_seconds: float,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        if (
            isinstance(max_concurrent, bool)
            or not isinstance(max_concurrent, int)
            or max_concurrent < 1
            or isinstance(max_requests, bool)
            or not isinstance(max_requests, int)
            or max_requests < 1
            or isinstance(interval_seconds, bool)
            or not isinstance(interval_seconds, (int, float))
            or interval_seconds <= 0
            or (
                monotonic_clock is not None
                and not callable(monotonic_clock)
            )
        ):
            raise ValueError("health admission policy is invalid")
        self._semaphore = threading.BoundedSemaphore(max_concurrent)
        self._max_requests = max_requests
        self._interval_seconds = float(interval_seconds)
        self._clock = monotonic_clock or time.monotonic
        self._request_times: deque[float] = deque()
        self._rate_lock = threading.Lock()

    def __call__(self) -> AbstractContextManager[bool]:
        return self.lease()

    @contextmanager
    def lease(self) -> Iterator[bool]:
        acquired = self._semaphore.acquire(blocking=False)
        if not acquired:
            yield False
            return
        try:
            if not self._consume_rate_slot():
                yield False
                return
            yield True
        finally:
            self._semaphore.release()

    def _consume_rate_slot(self) -> bool:
        now = self._clock()
        if not isinstance(now, (int, float)) or isinstance(now, bool):
            return False
        threshold = float(now) - self._interval_seconds
        with self._rate_lock:
            while self._request_times and self._request_times[0] <= threshold:
                self._request_times.popleft()
            if len(self._request_times) >= self._max_requests:
                return False
            self._request_times.append(float(now))
            return True


def create_health_blueprint(
    *,
    control_database: ControlDatabase,
    service: HealthEndpointService,
    marker_reader: MarkerReader,
    external_admission: AdmissionGate,
    monitor_admission: AdmissionGate,
) -> Blueprint:
    """Create non-tenantized endpoints with separate admission budgets.

    Admission gates are intentionally required rather than silently defaulted;
    the deployment adapter can back each one with its own bounded semaphore and
    rate limiter.  A rejected or broken gate fails before borrowing a control
    database connection.
    """

    if not isinstance(control_database, ControlDatabase):
        raise TypeError("control_database must be a ControlDatabase")
    if not isinstance(service, HealthEndpointService):
        raise TypeError("service must be a HealthEndpointService")
    for callback, label in (
        (marker_reader, "marker_reader"),
        (external_admission, "external_admission"),
        (monitor_admission, "monitor_admission"),
    ):
        if not callable(callback):
            raise TypeError(f"{label} must be callable")

    blueprint = Blueprint("saas_core_health", __name__)

    @blueprint.get("/health/external")
    def external_health() -> Response:
        if request.args:
            return health_response(_unavailable())
        with _admission(external_admission) as admitted:
            if not admitted:
                return health_response(_unavailable())
            try:
                marker = marker_reader()
                with control_database.transaction() as session:
                    result = service.external(session, marker=marker)
            except Exception:
                result = _unavailable()
        return health_response(result)

    @blueprint.get("/health/monitor")
    def monitor_health() -> Response:
        if request.args:
            return health_response(_unavailable())
        with _admission(monitor_admission) as admitted:
            if not admitted:
                return health_response(_unavailable())
            try:
                with control_database.transaction() as session:
                    result = service.monitor(session)
            except Exception:
                result = _unavailable()
        return health_response(result)

    return blueprint


def health_response(result: HealthEndpointResult) -> Response:
    if not isinstance(result, HealthEndpointResult):
        raise TypeError("result must be a HealthEndpointResult")
    response = Response(result.body, status=result.status_code)
    for key, value in result.headers.items():
        response.headers[key] = value
    return response


@contextmanager
def _admission(gate: AdmissionGate) -> Iterator[bool]:
    try:
        candidate = gate()
    except Exception:
        yield False
        return
    if isinstance(candidate, AbstractContextManager):
        try:
            admitted = candidate.__enter__()
        except Exception:
            yield False
            return
        try:
            yield admitted is True
        finally:
            try:
                candidate.__exit__(None, None, None)
            except Exception:
                pass
        return
    yield candidate is True


def _unavailable() -> HealthEndpointResult:
    return HealthEndpointResult(
        status_code=503,
        body=b'{"status":"unavailable"}\n',
    )
