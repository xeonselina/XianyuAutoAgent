from pathlib import Path

from flask import Flask

from app.routes.vue_app import bp


def _spa_test_app(tmp_path: Path) -> Flask:
    app_root = tmp_path / "app"
    desktop = tmp_path / "static" / "vue-dist"
    mobile = tmp_path / "static" / "vue-mobile-dist"
    app_root.mkdir()
    desktop.mkdir(parents=True)
    mobile.mkdir(parents=True)
    (desktop / "index.html").write_text("desktop-spa", encoding="utf-8")
    (mobile / "index.html").write_text("mobile-spa", encoding="utf-8")
    app = Flask(__name__, root_path=str(app_root))
    app.register_blueprint(bp)
    return app


def test_named_auth_and_platform_pages_use_desktop_spa_fallback(tmp_path):
    client = _spa_test_app(tmp_path).test_client()

    for path in (
        "/login",
        "/access-restricted",
        "/settings",
        "/platform/login",
        "/platform/tenants",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.get_data(as_text=True) == "desktop-spa"


def test_spa_fallback_does_not_capture_api_paths(tmp_path):
    client = _spa_test_app(tmp_path).test_client()

    assert client.get("/api/not-a-route").status_code == 404
    assert client.get("/platform/api/not-a-route").status_code == 404
