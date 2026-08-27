import base64
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from scripts.run_mobile_e2e_x86 import (
    AMD64_PLATFORM,
    E2E_LABEL_VALUE,
    PROJECT_ROOT,
    ResourceNames,
    _cleanup,
    _e2e_environment,
    _has_expected_label,
    _run,
    _wait_for_app,
    _wait_for_database,
    assert_safe_resource_name,
    cleanup_on_termination,
    database_ping_command,
    docker_run_prefix,
    writable_generated_file_mounts,
)


def test_npm_x86_entrypoint_uses_python3():
    project_root = Path(__file__).resolve().parents[2]
    package = json.loads(
        (project_root / "frontend-mobile" / "package.json").read_text(
            encoding="utf-8"
        )
    )

    assert package["scripts"]["test:e2e:x86"].startswith("python3 ")


def test_subprocesses_run_from_inventory_manager_root(monkeypatch):
    captured = {}

    class FakeProcess:
        returncode = 0

        def __init__(self, command, **kwargs):
            captured["command"] = command
            captured.update(kwargs)

        def communicate(self):
            return None, None

    monkeypatch.setattr(
        "scripts.run_mobile_e2e_x86.subprocess.Popen",
        FakeProcess,
    )

    _run(["make", "build"])

    assert captured["cwd"] == PROJECT_ROOT
    assert captured["start_new_session"] is True


def test_docker_run_prefix_forces_linux_amd64():
    assert docker_run_prefix() == [
        "docker",
        "run",
        "--platform",
        AMD64_PLATFORM,
    ]
    assert AMD64_PLATFORM == "linux/amd64"


def test_database_probe_waits_for_final_tcp_listener():
    command = database_ping_command("xianyu-mobile-e2e-unit-db")

    assert "--host=127.0.0.1" in command
    assert "--protocol=tcp" in command


def test_database_probe_uses_the_tracked_runner(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "scripts.run_mobile_e2e_x86._run",
        lambda command, **kwargs: calls.append((command, kwargs))
        or subprocess.CompletedProcess(command, 0),
    )
    monkeypatch.setattr(
        "scripts.run_mobile_e2e_x86.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("untracked subprocess.run"),
    )

    _wait_for_database("xianyu-mobile-e2e-unit-db", {})

    assert calls[0][1]["check"] is False
    assert calls[0][1]["quiet"] is True


def test_app_probe_is_tracked_and_has_an_http_timeout(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "scripts.run_mobile_e2e_x86._run",
        lambda command, **kwargs: calls.append((command, kwargs))
        or subprocess.CompletedProcess(command, 0),
    )
    monkeypatch.setattr(
        "scripts.run_mobile_e2e_x86.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("untracked subprocess.run"),
    )

    _wait_for_app("xianyu-mobile-e2e-unit-app")

    assert "timeout=2" in calls[0][0][-1]
    assert calls[0][1]["check"] is False
    assert calls[0][1]["quiet"] is True


def test_all_resource_names_are_scoped_to_mobile_e2e():
    resources = ResourceNames(run_id="unit")

    for name in (
        resources.network,
        resources.database_container,
        resources.app_container,
    ):
        assert assert_safe_resource_name(name) == name
        assert name.startswith("xianyu-mobile-e2e-")


def test_generated_master_key_is_standard_base64_for_exactly_32_bytes():
    encoded = _e2e_environment()["SAAS_MASTER_KEY"]

    assert len(base64.b64decode(encoded, validate=True)) == 32


def test_generated_frontend_declarations_are_writable_without_mutating_source(
    tmp_path,
):
    source_root = tmp_path / "source"
    scratch_root = tmp_path / "scratch"
    frontend = source_root / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "auto-imports.d.ts").write_text("source auto", encoding="utf-8")
    (frontend / "components.d.ts").write_text("source components", encoding="utf-8")

    mounts = writable_generated_file_mounts(source_root, scratch_root)

    assert mounts == [
        "--mount",
        (
            f"type=bind,source={scratch_root / 'auto-imports.d.ts'},"
            "target=/workspace/frontend/auto-imports.d.ts"
        ),
        "--mount",
        (
            f"type=bind,source={scratch_root / 'components.d.ts'},"
            "target=/workspace/frontend/components.d.ts"
        ),
    ]
    assert (scratch_root / "auto-imports.d.ts").read_text(encoding="utf-8") == "source auto"
    assert (scratch_root / "components.d.ts").read_text(encoding="utf-8") == "source components"


@pytest.mark.parametrize(
    "name",
    ["mariadb", "inventory-manager", "xianyu-mobile", "", "../e2e"],
)
def test_cleanup_guard_rejects_unscoped_resource_names(name):
    with pytest.raises(ValueError, match="xianyu-mobile-e2e"):
        assert_safe_resource_name(name)


def test_cleanup_only_removes_created_resources_with_expected_label(monkeypatch):
    resources = ResourceNames(run_id="unit")
    created = {
        resources.database_container,
        resources.app_container,
        resources.network,
    }
    removed = []

    monkeypatch.setattr(
        "scripts.run_mobile_e2e_x86._has_expected_label",
        lambda kind, name: name != resources.database_container,
    )
    monkeypatch.setattr(
        "scripts.run_mobile_e2e_x86.subprocess.run",
        lambda command, **_: removed.append(command),
    )

    _cleanup(resources, created)

    assert ["docker", "rm", "--force", resources.app_container] in removed
    assert ["docker", "rm", "--force", resources.database_container] not in removed
    assert ["docker", "network", "rm", resources.network] in removed


def test_resource_label_probe_requires_the_exact_e2e_label(monkeypatch):
    monkeypatch.setattr(
        "scripts.run_mobile_e2e_x86.subprocess.run",
        lambda *_, **__: subprocess.CompletedProcess(
            args=[], returncode=0, stdout=f"{E2E_LABEL_VALUE}\n"
        ),
    )
    assert _has_expected_label("container", "xianyu-mobile-e2e-unit-app")

    monkeypatch.setattr(
        "scripts.run_mobile_e2e_x86.subprocess.run",
        lambda *_, **__: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="some-other-label\n"
        ),
    )
    assert not _has_expected_label(
        "container", "xianyu-mobile-e2e-unit-app"
    )


def test_sigterm_unwinds_through_cleanup_and_restores_handlers(monkeypatch):
    handlers = {}
    installed = []

    monkeypatch.setattr(signal, "getsignal", lambda signum: f"old-{signum}")

    def fake_signal(signum, handler):
        handlers[signum] = handler
        installed.append((signum, handler))

    monkeypatch.setattr(signal, "signal", fake_signal)
    cleanup_calls = []

    with pytest.raises(SystemExit) as exc_info:
        with cleanup_on_termination(lambda: cleanup_calls.append("cleaned")):
            handlers[signal.SIGTERM](signal.SIGTERM, None)

    assert exc_info.value.code == 128 + signal.SIGTERM
    assert cleanup_calls == ["cleaned"]
    assert installed[-2:] == [
        (signal.SIGINT, f"old-{signal.SIGINT}"),
        (signal.SIGTERM, f"old-{signal.SIGTERM}"),
    ]


def test_sigterm_stops_a_blocking_child_before_cleanup():
    cleanup_calls = []
    started_at = time.monotonic()
    timer = threading.Timer(
        0.1,
        lambda: os.kill(os.getpid(), signal.SIGTERM),
    )

    try:
        with pytest.raises(SystemExit):
            with cleanup_on_termination(
                lambda: cleanup_calls.append("cleaned")
            ):
                timer.start()
                _run([
                    sys.executable,
                    "-c",
                    "import time; time.sleep(5)",
                ])
    finally:
        timer.cancel()

    assert time.monotonic() - started_at < 2
    assert cleanup_calls == ["cleaned"]
