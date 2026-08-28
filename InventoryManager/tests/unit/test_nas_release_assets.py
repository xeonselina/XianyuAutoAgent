import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


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


def test_deploy_existing_tag_requires_an_explicit_tag():
    result = run_make("deploy-nas", "IMAGE_TAG=")
    assert result.returncode != 0
    assert "IMAGE_TAG" in result.stdout + result.stderr
