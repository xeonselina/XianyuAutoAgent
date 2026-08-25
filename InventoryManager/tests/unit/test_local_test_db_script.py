import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/local_test_db.sh"
CONTAINER = "xianyu-saas-lite-mariadb-test"
VOLUME = "xianyu-saas-lite-mariadb-test-data"

FAKE_DOCKER = r"""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
s = Path(os.environ["FAKE_DOCKER_STATE"]); a = sys.argv[1:]
c, v = s / "container", s / "volume"
with (s / "calls").open("a") as log: log.write(json.dumps(a) + "\n")
if a[:2] == ["container", "inspect"]: raise SystemExit(0 if c.exists() else 1)
if a[:2] == ["volume", "inspect"]: raise SystemExit(0 if v.exists() else 1)
if a[:2] == ["volume", "create"]: v.touch(); print(a[2]); raise SystemExit
if a[0] == "inspect":
    mode, fmt = c.read_text(), a[2]
    if "Config.Image" in fmt: print("wrong:1" if mode == "bad-image" else "mariadb:10.11")
    elif "PortBindings" in fmt:
        if "json" not in fmt: print("0.0.0.0:33316" if mode == "bad-port" else "127.0.0.1:33316")
        else: print('{"3306/tcp":[{"HostIp":"0.0.0.0","HostPort":"33316"}]}' if mode == "bad-port" else '{"3306/tcp":[{"HostIp":"127.0.0.1","HostPort":"33316"},{"HostIp":"0.0.0.0","HostPort":"33316"}]}' if mode == "extra-binding" else '{"3306/tcp":[{"HostIp":"127.0.0.1","HostPort":"33316"}]}')
    elif "Mounts" in fmt: print("other-volume" if mode == "bad-volume" else "xianyu-saas-lite-mariadb-test-data")
    elif "State.Status" in fmt: print("running")
    raise SystemExit
if a[0] == "run":
    assert os.environ.get("MARIADB_ROOT_PASSWORD"); c.write_text("ok"); print("fake-id"); raise SystemExit
if a[0] == "start": raise SystemExit(0 if c.exists() else 1)
if a[0] == "exec": raise SystemExit(0 if c.exists() else 1)
if a[0] == "rm": c.unlink(missing_ok=True); raise SystemExit
if a[:2] == ["volume", "rm"]: v.unlink(missing_ok=True); raise SystemExit
raise SystemExit(9)
"""


def invoke(tmp_path, command, *, container=None, volume=False, password="silent-secret", trace=False):
    fake_bin, state = tmp_path / "bin", tmp_path / "state"
    fake_bin.mkdir(parents=True); state.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(FAKE_DOCKER); docker.chmod(0o755)
    if container: (state / "container").write_text(container)
    if volume: (state / "volume").touch()
    env = os.environ.copy()
    env.update(PATH=f"{fake_bin}:{env['PATH']}", FAKE_DOCKER_STATE=str(state))
    if password is None: env.pop("TEST_MARIADB_ROOT_PASSWORD", None)
    else: env["TEST_MARIADB_ROOT_PASSWORD"] = password
    result = subprocess.run(["bash", *(["-x"] if trace else []), SCRIPT, command], env=env, text=True,
                            capture_output=True, timeout=10, check=False)
    calls = [json.loads(line) for line in ((state / "calls").read_text() if (state / "calls").exists() else "").splitlines()]
    return result, calls, state


def test_xtraced_up_creates_exact_loopback_container_without_leaking_secret(tmp_path):
    result, calls, _ = invoke(tmp_path, "up", trace=True)
    assert result.returncode == 0
    assert "silent-secret" not in result.stdout + result.stderr + json.dumps(calls)
    assert ["volume", "create", VOLUME] in calls
    assert ["run", "--detach", "--name", CONTAINER, "--publish",
            "127.0.0.1:33316:3306", "--mount",
            f"source={VOLUME},target=/var/lib/mysql", "--env",
            "MARIADB_ROOT_PASSWORD", "mariadb:10.11"] in calls


def test_up_adopts_exact_container_without_recreating_it(tmp_path):
    result, calls, _ = invoke(tmp_path, "up", container="ok", volume=True)
    assert result.returncode == 0
    assert ["start", CONTAINER] in calls
    assert not any(call[0] in {"run", "rm"} or call[:2] == ["volume", "create"] for call in calls)


@pytest.mark.parametrize("command,container,volume", [
    ("up", None, False), ("up", None, True), ("reset", "ok", True),
])
def test_creation_requires_supplied_secret_before_mutation(tmp_path, command, container, volume):
    result, calls, _ = invoke(tmp_path, command, container=container, volume=volume, password=None)
    assert result.returncode != 0 and "requires TEST_MARIADB_ROOT_PASSWORD" in result.stderr
    assert not any(call[0] in {"run", "rm"} or call[:2] == ["volume", "rm"] for call in calls)


@pytest.mark.parametrize("mode", ["bad-image", "bad-port", "extra-binding", "bad-volume"])
def test_up_rejects_misconfigured_existing_container_without_mutation(tmp_path, mode):
    result, calls, _ = invoke(tmp_path, "up", container=mode, volume=True)
    assert result.returncode != 0
    assert "does not match" in result.stderr
    assert not any(call[0] in {"run", "start", "rm"} or call[:2] == ["volume", "rm"] for call in calls)


def test_status_is_read_only_and_down_preserves_volume(tmp_path):
    result, calls, _ = invoke(tmp_path, "status", container="ok", volume=True)
    assert result.returncode == 0
    assert not any(call[0] in {"run", "start", "rm"} or call[:2] == ["volume", "rm"] for call in calls)
    result, calls, state = invoke(tmp_path / "down", "down", container="ok", volume=True)
    assert result.returncode == 0 and ["rm", "--force", CONTAINER] in calls
    assert (state / "volume").exists() and not any(call[:2] == ["volume", "rm"] for call in calls)


def test_reset_deletes_only_literal_targets_then_recreates(tmp_path):
    result, calls, _ = invoke(tmp_path, "reset", container="ok", volume=True)
    assert result.returncode == 0
    destructive = [call for call in calls if call[0] == "rm" or call[:2] == ["volume", "rm"]]
    assert destructive == [["rm", "--force", CONTAINER], ["volume", "rm", VOLUME]]
    assert next(i for i, call in enumerate(calls) if call[0] == "run") > calls.index(destructive[-1])


def test_rejects_unknown_command_without_calling_docker(tmp_path):
    result, calls, _ = invoke(tmp_path, "destroy")
    assert result.returncode == 2 and calls == []


def test_dockerignore_excludes_credentials_dumps_and_restore_output():
    rules = (ROOT / ".dockerignore").read_text().splitlines()
    assert {".env", "*.sql", "xianyu-saas-lite-restore/"} <= set(rules)
