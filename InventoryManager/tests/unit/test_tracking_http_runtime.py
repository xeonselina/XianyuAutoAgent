from flask import Flask
import pytest

from app.routes.tracking_api import bp
from config import Config, DockerConfig, ProductionConfig, TestingConfig


@pytest.mark.parametrize(
    ("path", "method"),
    (
        ("/api/tracking/query", "post"),
        ("/api/tracking/batch-query", "post"),
        ("/api/tracking/update-now", "post"),
        ("/api/tracking/scheduler-status", "get"),
        ("/api/device/update-status", "post"),
        ("/api/device/force-update-status", "post"),
        ("/api/device/status-summary", "get"),
    ),
)
def test_legacy_tracking_and_scheduler_surface_is_test_only(path, method):
    app = Flask(__name__)
    app.config.update(
        TESTING=False,
        ENABLE_LEGACY_SINGLE_TENANT_TRACKING_API=True,
    )
    app.register_blueprint(bp)

    response = getattr(app.test_client(), method)(path, json={})

    assert response.status_code == 503
    assert response.get_json() == {
        "success": False,
        "message": "租户物流服务尚未就绪",
    }
    assert response.headers["Cache-Control"] == "private, no-store"


def test_only_testing_config_enables_legacy_tracking_compatibility():
    assert Config.ENABLE_LEGACY_SINGLE_TENANT_TRACKING_API is False
    assert ProductionConfig.ENABLE_LEGACY_SINGLE_TENANT_TRACKING_API is False
    assert DockerConfig.ENABLE_LEGACY_SINGLE_TENANT_TRACKING_API is False
    assert TestingConfig.ENABLE_LEGACY_SINGLE_TENANT_TRACKING_API is True
