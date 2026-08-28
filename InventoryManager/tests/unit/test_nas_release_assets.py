import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy/nas/docker-compose.yml"


def run_make(*args):
    return subprocess.run(
        ["make", "--no-print-directory", *args], cwd=ROOT,
        env={**os.environ, "GIT_SHA": "abc123def456", "RELEASE_TIME": "20260828-120000"},
        text=True, capture_output=True, check=False,
    )


def test_release_tag_and_single_image_are_visible_in_dry_run():
    result = run_make("-n", "release-nas", "BACKUP_VERIFIED=backup-verified")
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "docker buildx build" in output
    assert '--platform "linux/amd64"' in output
    assert "docker.cnb.cool/tdcc-demo/jimmy/inventory-manager:20260828-120000-abc123def456" in output
    assert output.count("20260828-120000-abc123def456") >= 2


def test_production_build_targets_ignore_platform_override():
    for target, arguments in (
        ("build-push", ()),
        ("release-nas", ("BACKUP_VERIFIED=backup-verified",)),
    ):
        result = run_make("-n", target, *arguments, "PLATFORM=linux/arm64")
        assert result.returncode == 0
        output = result.stdout + result.stderr
        assert '--platform "linux/amd64"' in output
        assert "linux/arm64" not in output


def test_deploy_existing_tag_requires_an_explicit_tag():
    result = run_make("deploy-nas", "IMAGE_TAG=")
    assert result.returncode != 0
    assert "IMAGE_TAG" in result.stdout + result.stderr


def test_nas_compose_uses_one_image_and_external_frp_network():
    text = COMPOSE.read_text()
    assert text.count('image: "${IMAGE_REF:?IMAGE_REF is required}"') == 4
    assert "migrate-control:" in text and "migrate-tenants:" in text
    assert 'name: "${FRPC_NETWORK:?FRPC_NETWORK is required}"' in text
    assert "external: true" in text
    assert "inventory-manager-app" in text
    assert "ports:" not in text


def test_worker_clears_every_app_only_secret():
    text = COMPOSE.read_text()
    for key in (
        "PROVISIONER_DATABASE_URL", "TENCENTCLOUD_SECRET_ID",
        "TENCENTCLOUD_SECRET_KEY", "TENCENT_SMS_SDK_APP_ID",
        "TENCENT_SMS_SIGN_NAME", "TENCENT_SMS_TEMPLATE_ID",
        "TENCENT_SMS_REGION",
    ):
        assert f'{key}: ""' in text


def test_app_healthcheck_uses_python_stdlib():
    text = COMPOSE.read_text()
    assert "urllib.request.urlopen" in text
    assert "http://127.0.0.1:5002/health" in text
