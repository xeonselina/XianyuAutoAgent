import re
from pathlib import Path

import pytest

from app import create_app
from config import ProductionConfig


ROOT = Path(__file__).resolve().parents[2]
MASTER_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="


def _production_config(tmp_path, **overrides):
    attributes = {
        "TESTING": True,
        "AUTH_BYPASS_FOR_TESTS": False,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'bootstrap.db'}",
        "SQLALCHEMY_ENGINE_OPTIONS": {},
        "CONTROL_DATABASE_URL": f"sqlite:///{tmp_path / 'control.db'}",
        "PROVISIONER_DATABASE_URL": f"sqlite:///{tmp_path / 'provisioner.db'}",
        "SAAS_MASTER_KEY": MASTER_KEY,
        "DEV_SMS_CODE": None,
        "TENANT_DB_HOST": "127.0.0.1",
        "TENANT_DB_PORT": 33316,
        "TENANT_DB_NAME_PREFIX": "inventory_tenant_",
        "TENANT_DB_USER_PREFIX": "im_t",
        "TENCENTCLOUD_SECRET_ID": "test-id",
        "TENCENTCLOUD_SECRET_KEY": "test-key",
        "TENCENT_SMS_SDK_APP_ID": "test-app",
        "TENCENT_SMS_SIGN_NAME": "test-sign",
        "TENCENT_SMS_TEMPLATE_ID": "test-template",
        "CORS_ORIGINS": ["https://inventory.example"],
        **overrides,
    }
    return type("Task4ProductionConfig", (ProductionConfig,), attributes)


@pytest.mark.parametrize("worker_mode", [False, True])
@pytest.mark.parametrize(
    "key,value,error",
    [
        ("SQLALCHEMY_DATABASE_URI", None, "DATABASE_URL"),
        ("TENANT_DB_HOST", None, "TENANT_DB_HOST"),
        ("TENANT_DB_PORT", 0, "TENANT_DB_PORT"),
        ("TENANT_DB_PORT", 65536, "TENANT_DB_PORT"),
    ],
)
def test_production_modes_fail_closed_for_database_boundary(
    tmp_path, worker_mode, key, value, error,
):
    config = _production_config(tmp_path, **{key: value})

    with pytest.raises(RuntimeError, match=error):
        create_app(config, worker_mode=worker_mode)


def test_production_config_has_no_local_root_or_tenant_host_fallback():
    assert ProductionConfig.SQLALCHEMY_DATABASE_URI is None
    assert ProductionConfig.TENANT_DB_HOST is None


def test_same_production_config_bootstraps_app_and_worker(tmp_path):
    config = _production_config(tmp_path)
    application = create_app(config)
    worker = create_app(config, worker_mode=True)
    try:
        assert application.extensions["tenant_provisioner"] is not None
        assert "tenant_provisioner" not in worker.extensions
        assert "sms_sender" not in worker.extensions
    finally:
        application.extensions["tenant_resource_finalizer"]()
        worker.extensions["tenant_resource_finalizer"]()


def test_runtime_template_has_only_safe_delivery_configuration():
    lines = (ROOT / ".env.example").read_text().splitlines()
    active = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in lines
        if line and not line.startswith("#") and "=" in line
    }
    assert {
        "FLASK_ENV", "DATABASE_URL", "CONTROL_DATABASE_URL",
        "PROVISIONER_DATABASE_URL", "SAAS_MASTER_KEY", "SECRET_KEY",
        "TENANT_DB_HOST", "TENANT_DB_PORT", "TENANT_DB_NAME_PREFIX",
        "TENANT_DB_USER_PREFIX", "CONTROL_DB_POOL_SIZE",
        "TENANT_DB_POOL_SIZE", "CORS_ORIGINS", "TRUSTED_PROXY_HOPS",
        "TENCENTCLOUD_SECRET_ID", "TENCENTCLOUD_SECRET_KEY",
        "TENCENT_SMS_SDK_APP_ID", "TENCENT_SMS_SIGN_NAME",
        "TENCENT_SMS_TEMPLATE_ID", "XIANYU_API_DOMAIN", "LOG_LEVEL",
    } <= active.keys()
    assert all(active[key] == "" for key in (
        "DATABASE_URL", "CONTROL_DATABASE_URL", "PROVISIONER_DATABASE_URL",
        "SAAS_MASTER_KEY", "SECRET_KEY", "TENCENTCLOUD_SECRET_ID",
        "TENCENTCLOUD_SECRET_KEY", "TENCENT_SMS_SDK_APP_ID",
        "TENCENT_SMS_SIGN_NAME", "TENCENT_SMS_TEMPLATE_ID",
    ))
    for legacy in (
        "SF_PARTNER_ID", "SF_CHECKWORD", "SF_MONTHLY_CARD",
        "KUAIMAI_APP_ID", "KUAIMAI_APP_SECRET", "KUAIMAI_PRINTER_SN",
        "XIANYU_APP_KEY", "XIANYU_APP_SECRET",
    ):
        assert legacy not in active
        assert any(line.startswith(f"# {legacy}=") for line in lines)


def test_one_image_and_parameterized_make_contract():
    dockerfile = (ROOT / "Dockerfile").read_text()
    makefile = (ROOT / "Makefile").read_text()
    targets = set(re.findall(r"^([a-z][a-z-]*):", makefile, re.MULTILINE))
    assert 'CMD ["gunicorn", "--config", "gunicorn_config.py", "run:app"]' in dockerfile
    assert "HEALTHCHECK" not in dockerfile and "curl" not in dockerfile
    assert "docker-compose" not in dockerfile.lower()
    assert targets == {"help", "build", "push", "run-app", "run-worker", "worker-once"}
    assert all(token not in makefile for token in (
        "NAS_", "sshpass", "docker-compose", "include .env", "REGISTRY :=",
    ))
    for key in (
        "PROVISIONER_DATABASE_URL", "TENCENTCLOUD_SECRET_ID",
        "TENCENTCLOUD_SECRET_KEY", "TENCENT_SMS_SDK_APP_ID",
        "TENCENT_SMS_SIGN_NAME", "TENCENT_SMS_TEMPLATE_ID",
    ):
        assert makefile.count(f'--env "{key}="') == 2


def test_handoff_and_retired_artifacts_are_sanitized():
    handoff = ROOT.parent / "docs/deployment/saas-main-lite.md"
    assert handoff.exists()
    text = handoff.read_text()
    assert all(token in text for token in (
        "control_alembic.ini", "migrate-default-tenant",
        "upgrade-tenant-databases", "python worker.py", "--once",
        "维护窗口", "完整备份", "NAS", "公网入口",
    ))
    assert "compose" not in text.lower()
    for path in (
        ROOT / ".env.docker", ROOT / "env.production", ROOT / "deploy.sh",
        ROOT / "templates/shipping_order2.html",
        ROOT / "templates/rental_contract2.html",
    ):
        assert not path.exists()
    legacy_phone = "135102" + "24947"
    legacy_address = "竹苑" + "9栋"
    for relative in (
        "docs/SF_OAUTH2_GUIDE.md", "docs/SF_SETUP.md",
        "openspec/changes/view-sf-shipment-tracking/proposal.md",
        "PROJECT_EXPLORATION.md",
    ):
        contents = (ROOT / relative).read_text()
        assert legacy_phone not in contents and legacy_address not in contents


def test_rental_contract_and_exclusive_ocr_surface_is_removed():
    removed = (
        "frontend/src/views/RentalContractView.vue",
        "templates/rental_contract2.html",
        "app/routes/ocr_api.py", "ocr_functions.py",
        "docs/租赁合同功能说明.md", "OCR测试说明.md",
        "docs/设备租赁合同模板.docx",
    )
    assert all(not (ROOT / relative).exists() for relative in removed)
    sources = {
        relative: (ROOT / relative).read_text()
        for relative in (
            "frontend/src/router/index.ts",
            "frontend/src/components/rental/RentalActionButtons.vue",
            "frontend/src/components/rental/EditRentalDialogNew.vue",
            "app/routes/web.py", "app/routes/web_pages.py",
            "app/routes/vue_app.py", "README.md", "docs/安装使用说明.md",
        )
    }
    assert all(token not in "\n".join(sources.values()) for token in (
        "RentalContractView", "rental-contract", "open-contract",
        "/contract/", "ocr_api", "/api/ocr/id-card",
        "_prepare_contract_data", "租赁合同", "ocr_functions", "阿里云OCR",
    ))
    application = create_app("testing")
    try:
        assert application.test_client().get("/contract/1").status_code == 404
    finally:
        application.extensions["tenant_resource_finalizer"]()
    bundles = "\n".join(
        path.read_text(errors="ignore")
        for path in (ROOT / "static/vue-dist/assets").glob("*.js")
    )
    assert "租赁合同" not in bundles and "/api/ocr/id-card" not in bundles
    assert "alibabacloud-ocr" not in (ROOT / "requirements.txt").read_text()
