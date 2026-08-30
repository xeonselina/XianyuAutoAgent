from pathlib import Path

from flask import Flask

from app.routes.web_pages import bp as web_pages_bp
from app.routes.vue_app import bp as vue_app_bp


def test_legacy_devices_route_serves_spa_with_production_registration_order(
    tmp_path: Path,
):
    app_root = tmp_path / "app"
    desktop = tmp_path / "static" / "vue-dist"
    app_root.mkdir()
    desktop.mkdir(parents=True)
    (desktop / "index.html").write_text("desktop-spa", encoding="utf-8")

    app = Flask(__name__, root_path=str(app_root))
    app.register_blueprint(web_pages_bp)
    app.register_blueprint(vue_app_bp)

    response = app.test_client().get("/devices")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "desktop-spa"
