from app import create_app
from config import TestingConfig


class LegacyKeyStillPresentConfig(TestingConfig):
    API_KEY = "legacy-value-must-have-no-authority"


def test_legacy_external_api_is_unreachable_even_when_old_key_is_configured():
    app = create_app(LegacyKeyStillPresentConfig)
    client = app.test_client()

    for path, method in (
        ("/external-api/health", "get"),
        ("/external-api/docs", "get"),
        ("/external-api/devices", "get"),
        ("/external-api/inventory/check", "post"),
    ):
        response = getattr(client, method)(
            path,
            headers={"X-API-Key": LegacyKeyStillPresentConfig.API_KEY},
        )
        assert response.status_code == 404


def test_base_config_no_longer_loads_api_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "ignored-legacy-value")

    assert not hasattr(TestingConfig, "API_KEY")
