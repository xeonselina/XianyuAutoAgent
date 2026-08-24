from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from types import SimpleNamespace
from uuid import UUID

from flask import Flask
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app import db
from app.routes.xianyu_order_alert_api import bp
from app.services.xianyu_sync import (
    XIANYU_SYNC_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyXianyuSyncHttpRuntime,
)
from inventory_control import ControlBase, ControlDatabase, Tenant
from inventory_control.crypto import RootKey
from inventory_control.integrations import (
    ProviderValidationOutcome,
    TenantIntegrationService,
)
from inventory_control.jobs import (
    ScheduleGateVerdict,
    XianyuSyncJobCoordinator,
)
from inventory_control.models.jobs import BackgroundJob
from config import Config, DockerConfig, ProductionConfig, TestingConfig


TENANT_ID = UUID("81000000-0000-4000-8000-000000000001")
USER_ID = UUID("81000000-0000-4000-8000-000000000002")
INTEGRATION_ID = UUID("81000000-0000-4000-8000-000000000003")
ACTION_ID = UUID("81000000-0000-4000-8000-000000000004")
ATTEMPT_ID = UUID("81000000-0000-4000-8000-000000000005")
NOW = datetime(2026, 8, 23, 2, 0, tzinfo=timezone.utc)


class _Gate:
    def __init__(self, runtime):
        self.runtime = runtime

    def evaluate(self, _session, *, tenant, now):
        assert self.runtime.inside is False
        assert tenant.id == str(TENANT_ID)
        assert now == NOW
        return ScheduleGateVerdict(True)


class _TenantRuntime:
    def __init__(self, engine):
        self.engine = engine
        self.inside = False
        self.calls = []

    @contextmanager
    def tenant_session(self, **kwargs):
        self.calls.append(kwargs)
        session = Session(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.inside = True
        try:
            yield SimpleNamespace(
                auth_context=SimpleNamespace(
                    tenant_id=str(TENANT_ID),
                    user_id=str(USER_ID),
                ),
                request_id="xianyu-test-request",
                database_now=NOW,
                tenant_session=session,
            )
        finally:
            self.inside = False
            session.close()


def _control_database(database):
    with database.transaction() as session:
        session.add(Tenant(id=str(TENANT_ID), status="active", access_version=2))
    with database.transaction() as session:
        TenantIntegrationService(session).create_integration(
            integration_uuid=INTEGRATION_ID,
            tenant_uuid=TENANT_ID,
            provider="xianyu",
            name="primary",
        )
    with database.transaction() as session:
        pending = TenantIntegrationService(session).create_pending_revision(
            integration_uuid=INTEGRATION_ID,
            credentials={"app_key": "key", "app_secret": "secret"},
            root_key=RootKey(version=1, material=b"k" * 32),
            created_by_user_uuid=USER_ID,
            action_uuid=ACTION_ID,
            idempotency_key="xianyu-http-revision-1",
            expected_integration_row_version=1,
            expected_current_secret_revision_uuid=None,
        )
    with database.transaction() as session:
        TenantIntegrationService(session).begin_provider_validation(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=ATTEMPT_ID,
            expected_revision_row_version=1,
        )
    with database.transaction() as session:
        TenantIntegrationService(session).record_provider_validation_result(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=ATTEMPT_ID,
            outcome=ProviderValidationOutcome.SUCCESS,
            provider_result_digest=hashlib.sha256(b"valid").digest(),
            safe_code="VALID",
            completed_at=NOW,
        )
    return database


def _runtime_harness(database):
    tenant_engine = database.engine
    tenant_runtime = _TenantRuntime(tenant_engine)
    control = _control_database(database)
    runtime = SqlAlchemyXianyuSyncHttpRuntime(
        tenant_business_runtime=tenant_runtime,
        job_coordinator=XianyuSyncJobCoordinator(
            database=control,
            gate=_Gate(tenant_runtime),
        ),
    )
    return runtime, tenant_runtime, tenant_engine, control


def test_refresh_closes_tenant_connection_before_control_job_enqueue(
    mysql_routed_database,
):
    runtime, tenant_runtime, tenant_engine, control = _runtime_harness(
        mysql_routed_database
    )
    app = Flask(__name__)
    try:
        with app.test_request_context(
            "/api/xianyu-order-alerts/refresh", method="POST"
        ):
            result = runtime.refresh_alerts(flask_request=SimpleNamespace())

        assert tenant_runtime.inside is False
        assert result["snapshot_revision"] == 0
        assert result["job_status"] == "pending"
        assert result["reused"] is False
        with control.new_session() as session:
            jobs = list(session.scalars(sa.select(BackgroundJob)))
        assert len(jobs) == 1
        assert jobs[0].payload["connections"][0]["integration_uuid"] == str(
            INTEGRATION_ID
        )
    finally:
        tenant_engine.dispose()
        control.dispose()


def test_route_returns_202_and_never_uses_legacy_provider_path(
    mysql_routed_database,
):
    runtime, _tenant_runtime, tenant_engine, control = _runtime_harness(
        mysql_routed_database
    )
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        ENABLE_LEGACY_SINGLE_TENANT_XIANYU_ALERT_API=False,
    )
    app.register_blueprint(bp)
    app.extensions[XIANYU_SYNC_HTTP_RUNTIME_EXTENSION] = runtime
    try:
        response = app.test_client().post("/api/xianyu-order-alerts/refresh")
        payload = response.get_json()

        assert response.status_code == 202
        assert payload["data"]["job_status"] == "pending"
        assert response.headers["Cache-Control"] == "private, no-store"
    finally:
        tenant_engine.dispose()
        control.dispose()


def test_route_without_runtime_fails_closed_even_if_legacy_env_exists(monkeypatch):
    monkeypatch.setenv("XIANYU_APP_KEY", "legacy-key-must-not-authorize")
    monkeypatch.setenv("XIANYU_APP_SECRET", "legacy-secret-must-not-authorize")
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        ENABLE_LEGACY_SINGLE_TENANT_XIANYU_ALERT_API=False,
    )
    app.register_blueprint(bp)

    response = app.test_client().post("/api/xianyu-order-alerts/refresh")

    assert response.status_code == 503
    assert response.get_json()["data"]["code"] == "XIANYU_SYNC_UNAVAILABLE"
    assert "legacy" not in response.get_data(as_text=True)


def test_only_testing_config_enables_legacy_xianyu_compatibility():
    assert Config.ENABLE_LEGACY_SINGLE_TENANT_XIANYU_ALERT_API is False
    assert ProductionConfig.ENABLE_LEGACY_SINGLE_TENANT_XIANYU_ALERT_API is False
    assert DockerConfig.ENABLE_LEGACY_SINGLE_TENANT_XIANYU_ALERT_API is False
    assert TestingConfig.ENABLE_LEGACY_SINGLE_TENANT_XIANYU_ALERT_API is True
