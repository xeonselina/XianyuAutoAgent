import os
import json
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


FAKE_TOOL = r'''#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["MAKE_FAKE_LOG"], "a") as handle:
    handle.write(json.dumps({
        "tool": os.path.basename(sys.argv[0]),
        "argv": sys.argv[1:],
        "image_tag": os.environ.get("IMAGE_TAG"),
        "release_tag": os.environ.get("RELEASE_TAG"),
        "log_tail": os.environ.get("LOG_TAIL"),
    }) + "\n")
'''


def write_executable(path, text):
    path.write_text(text)
    path.chmod(0o755)


def run_make_with_fake_tools(tmp_path, *args):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    log = tmp_path / "fake-tools.jsonl"
    for name in ("bash", "docker"):
        write_executable(fake_bin / name, FAKE_TOOL)

    result = subprocess.run(
        ["make", "--no-print-directory", *args],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "MAKE_FAKE_LOG": str(log),
            "GIT_SHA": "abc123def456",
            "RELEASE_TIME": "20260828-120000",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    calls = [] if not log.exists() else [json.loads(line) for line in log.read_text().splitlines()]
    return result, calls


def test_release_tag_and_single_image_are_visible_in_dry_run():
    result = run_make("-n", "release-nas", "BACKUP_VERIFIED=backup-verified")
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "docker buildx build" in output
    assert '--platform "linux/amd64"' in output
    assert '"$IMAGE_REPOSITORY:$RELEASE_TAG"' in output
    assert 'IMAGE_TAG="$RELEASE_TAG"' in output


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


def test_make_values_are_environment_data_not_shell_source(tmp_path):
    log_tail_marker = tmp_path / "log-tail-marker"
    log_tail_payload = f'200"; touch {log_tail_marker}; echo "'
    result, calls = run_make_with_fake_tools(
        tmp_path,
        "nas-logs",
        f"LOG_TAIL={log_tail_payload}",
    )

    assert result.returncode == 0, result.stderr
    assert not log_tail_marker.exists()
    assert calls == [{
        "tool": "bash",
        "argv": ["scripts/deploy_nas.sh", "logs"],
        "image_tag": "",
        "release_tag": "20260828-120000-abc123def456",
        "log_tail": log_tail_payload,
    }]


def test_image_and_release_tags_cannot_inject_make_recipes(tmp_path):
    image_tag_marker = tmp_path / "image-tag-marker"
    image_tag_payload = f'tag"; touch {image_tag_marker}; echo "'
    result, calls = run_make_with_fake_tools(
        tmp_path / "release-tag",
        "deploy-nas",
        "BACKUP_VERIFIED=backup-verified",
        f"IMAGE_TAG={image_tag_payload}",
    )

    assert result.returncode == 0, result.stderr
    assert not image_tag_marker.exists()
    assert calls == [{
        "tool": "bash",
        "argv": ["scripts/deploy_nas.sh", "deploy"],
        "image_tag": image_tag_payload,
        "release_tag": "20260828-120000-abc123def456",
        "log_tail": "200",
    }]

    release_tag_marker = tmp_path / "release-tag-marker"
    release_tag_payload = f'release"; touch {release_tag_marker}; echo "'
    result, calls = run_make_with_fake_tools(
        tmp_path,
        "build-push",
        f"RELEASE_TAG={release_tag_payload}",
    )

    assert result.returncode == 0, result.stderr
    assert not release_tag_marker.exists()
    assert calls == [{
        "tool": "docker",
        "argv": [
            "buildx", "build", "--platform", "linux/amd64", "--tag",
            f"docker.cnb.cool/tdcc-demo/jimmy/inventory-manager:{release_tag_payload}",
            "--push", ".",
        ],
        "image_tag": "",
        "release_tag": release_tag_payload,
        "log_tail": "200",
    }]


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
