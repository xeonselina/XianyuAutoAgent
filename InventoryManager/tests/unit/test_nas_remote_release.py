import json
import os
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy/nas/remote_release.sh"


FAKE_DOCKER = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
mode = os.environ.get("FAKE_DOCKER_MODE", "success")
with open(os.environ["FAKE_DOCKER_CALLS"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps(args) + "\n")
with open(os.environ["FAKE_DOCKER_ENVS"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps({
        "args": args,
        "env": {
            key: os.environ.get(key)
            for key in ("IMAGE_REF", "APP_ENV_FILE", "FRPC_NETWORK")
        },
    }) + "\n")

if args[:2] == ["compose", "version"]:
    raise SystemExit(0)
if "config" in args:
    raise SystemExit(1 if mode == "config-fail" else 0)
if "pull" in args:
    raise SystemExit(1 if mode == "pull-fail" else 0)
if args[:2] == ["network", "inspect"]:
    raise SystemExit(1 if mode == "network-absent" else 0)
if args[:2] == ["network", "create"]:
    raise SystemExit(0)
if args[:2] == ["network", "connect"]:
    raise SystemExit(0)
if args and args[0] == "inspect" and args[-1] == "frpc":
    print(
        "true"
        if "State.Running" in " ".join(args)
        else ("" if mode == "frpc-disconnected" else "connected")
    )
    raise SystemExit(0)
if "migrate-control" in args:
    raise SystemExit(1 if mode == "migration-fail" else 0)
if "migrate-tenants" in args:
    marker = os.environ.get("FAKE_TENANT_CURRENT")
    if marker:
        current = Path(os.environ["DEPLOY_DIR"]) / "current.env"
        Path(marker).write_text(current.read_text() if current.exists() else "<missing>")
    raise SystemExit(1 if mode == "tenant-migration-fail" else 0)
if args and args[0] == "inspect" and args[-1] == "app-id":
    print("unhealthy" if mode == "health-fail" else "healthy")
    raise SystemExit(0)
if "ps" in args and "app" in args:
    print("app-id")
    raise SystemExit(0)
if args and args[0] == "run":
    raise SystemExit(1 if mode == "probe-fail" else 0)
raise SystemExit(0)
'''


FAKE_MV = r'''#!/usr/bin/env python3
import os
import sys
from pathlib import Path

args = sys.argv[1:]
source = Path(args[-2])
destination = Path(args[-1])
if (
    os.environ.get("FAKE_FS_MODE") == "candidate-promote-fail"
    and source.name.startswith(".candidate.env.")
    and destination.name == "current.env"
):
    raise SystemExit(1)
os.execv("/bin/mv", ["/bin/mv", *args])
'''


def _release_env(image_ref, app_env, network):
    return (
        f"IMAGE_REF={image_ref}\n"
        f"APP_ENV_FILE={app_env}\n"
        f"FRPC_NETWORK={network}\n"
    )


def invoke(tmp_path, action, *, mode="success", backup="backup-verified", current=True,
           app_env_mode=0o600, log_tail=None, health_attempts=None,
           health_interval=None, fs_mode="success", current_metadata=None):
    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir(parents=True)
    (deploy_dir / "docker-compose.yml").write_text("services: {}\n")

    app_env = tmp_path / "app.env"
    app_env.write_text("SECRET=value\n")
    app_env.chmod(app_env_mode)

    if current:
        current_metadata = current_metadata or (
            "registry.example/inventory:old", str(app_env), "frp-network"
        )
        (deploy_dir / "current.env").write_text(
            _release_env(*current_metadata)
        )
        (deploy_dir / "current.env").chmod(0o600)
        (deploy_dir / "previous.env").write_text(
            _release_env("registry.example/inventory:older", app_env, "frp-network")
        )
        (deploy_dir / "previous.env").chmod(0o600)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    fake_mv = fake_bin / "mv"
    fake_mv.write_text(FAKE_MV)
    fake_mv.chmod(fake_mv.stat().st_mode | stat.S_IXUSR)
    calls_file = tmp_path / "docker-calls.jsonl"
    envs_file = tmp_path / "docker-envs.jsonl"
    tenant_current = tmp_path / "tenant-current.env"

    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "DEPLOY_DIR": str(deploy_dir),
        "APP_ENV_FILE": str(app_env),
        "IMAGE_REF": "registry.example/inventory:new",
        "FRPC_CONTAINER": "frpc",
        "FRPC_NETWORK": "frp-network",
        "BACKUP_VERIFIED": backup,
        "FAKE_DOCKER_CALLS": str(calls_file),
        "FAKE_DOCKER_ENVS": str(envs_file),
        "FAKE_DOCKER_MODE": mode,
        "FAKE_FS_MODE": fs_mode,
        "FAKE_TENANT_CURRENT": str(tenant_current),
    }
    if log_tail is not None:
        env["LOG_TAIL"] = log_tail
    if health_attempts is not None:
        env["HEALTH_ATTEMPTS"] = health_attempts
    if health_interval is not None:
        env["HEALTH_INTERVAL_SECONDS"] = health_interval

    result = subprocess.run(
        ["bash", str(SCRIPT), action],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    calls = []
    if calls_file.exists():
        calls = [json.loads(line) for line in calls_file.read_text().splitlines()]
    return result, calls, deploy_dir


def docker_environments(tmp_path):
    path = tmp_path / "docker-envs.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_pull_failure_never_stops_old_services(tmp_path):
    result, calls, deploy_dir = invoke(tmp_path, "deploy", mode="pull-fail")
    assert result.returncode != 0
    assert not any("stop" in call for call in calls)
    assert "registry.example/inventory:old" in (deploy_dir / "current.env").read_text()


def test_compose_uses_selected_release_metadata_instead_of_ambient_values(tmp_path):
    metadata = (
        "registry.example/inventory:selected",
        "/metadata-selected/app.env",
        "metadata-selected-network",
    )
    result, calls, deploy_dir = invoke(
        tmp_path, "status", current_metadata=metadata
    )
    assert result.returncode == 0, result.stderr
    ps_call = next(record for record in docker_environments(tmp_path) if "ps" in record["args"])
    assert ps_call["env"] == {
        "IMAGE_REF": metadata[0],
        "APP_ENV_FILE": metadata[1],
        "FRPC_NETWORK": metadata[2],
    }
    env_file = ps_call["args"][ps_call["args"].index("--env-file") + 1]
    assert env_file == str(deploy_dir / "current.env")
    assert not any(call and call[0] == "inspect" for call in calls)


def test_candidate_and_current_compose_calls_each_use_their_selected_metadata(tmp_path):
    result, _, _ = invoke(tmp_path, "deploy")
    assert result.returncode == 0, result.stderr
    records = docker_environments(tmp_path)
    config = next(record for record in records if "config" in record["args"])
    stop = next(record for record in records if "stop" in record["args"])
    assert config["env"]["IMAGE_REF"] == "registry.example/inventory:new"
    assert stop["env"]["IMAGE_REF"] == "registry.example/inventory:old"


def test_migration_failure_stops_without_starting_new_services(tmp_path):
    result, calls, deploy_dir = invoke(tmp_path, "deploy", mode="migration-fail")
    assert result.returncode != 0
    assert any("stop" in call for call in calls)
    assert not any("up" in call for call in calls)
    assert "registry.example/inventory:old" in (deploy_dir / "current.env").read_text()
    assert "registry.example/inventory:older" in (deploy_dir / "previous.env").read_text()
    assert "remain stopped" in result.stderr
    assert not list(deploy_dir.glob(".candidate.env.*"))


def test_tenant_migration_failure_preserves_metadata_and_never_starts(tmp_path):
    result, calls, deploy_dir = invoke(tmp_path, "deploy", mode="tenant-migration-fail")
    current_before = _release_env(
        "registry.example/inventory:old", tmp_path / "app.env", "frp-network"
    )
    previous_before = _release_env(
        "registry.example/inventory:older", tmp_path / "app.env", "frp-network"
    )
    assert result.returncode != 0
    assert any("migrate-tenants" in call for call in calls)
    assert not any("up" in call for call in calls)
    assert (deploy_dir / "current.env").read_text() == current_before
    assert (deploy_dir / "previous.env").read_text() == previous_before
    assert (tmp_path / "tenant-current.env").read_text() == current_before


def test_candidate_config_failure_preserves_metadata_without_stopping(tmp_path):
    result, calls, deploy_dir = invoke(tmp_path, "deploy", mode="config-fail")
    current_before = _release_env(
        "registry.example/inventory:old", tmp_path / "app.env", "frp-network"
    ).encode()
    previous_before = _release_env(
        "registry.example/inventory:older", tmp_path / "app.env", "frp-network"
    ).encode()
    assert result.returncode != 0
    assert not any("stop" in call or "up" in call for call in calls)
    assert not any("migrate-control" in call or "migrate-tenants" in call for call in calls)
    assert (deploy_dir / "current.env").read_bytes() == current_before
    assert (deploy_dir / "previous.env").read_bytes() == previous_before


def test_promotion_failure_restores_both_metadata_files_and_never_starts(tmp_path):
    result, calls, deploy_dir = invoke(
        tmp_path, "deploy", fs_mode="candidate-promote-fail"
    )
    current_before = _release_env(
        "registry.example/inventory:old", tmp_path / "app.env", "frp-network"
    ).encode()
    previous_before = _release_env(
        "registry.example/inventory:older", tmp_path / "app.env", "frp-network"
    ).encode()
    assert result.returncode != 0
    assert any("migrate-control" in call for call in calls)
    assert any("migrate-tenants" in call for call in calls)
    assert not any("up" in call for call in calls)
    assert (deploy_dir / "current.env").read_bytes() == current_before
    assert (deploy_dir / "previous.env").read_bytes() == previous_before


def test_disconnected_frpc_is_connected_before_service_stop(tmp_path):
    result, calls, _ = invoke(tmp_path, "deploy", mode="frpc-disconnected")
    assert result.returncode == 0
    connect = next(i for i, call in enumerate(calls) if call[:2] == ["network", "connect"])
    stop = next(i for i, call in enumerate(calls) if "stop" in call)
    assert connect < stop


def test_success_orders_candidate_checks_migrations_start_health_and_probe(tmp_path):
    result, calls, deploy_dir = invoke(tmp_path, "deploy")
    assert result.returncode == 0, result.stderr
    positions = {
        "config": next(i for i, call in enumerate(calls) if "config" in call),
        "pull": next(i for i, call in enumerate(calls) if "pull" in call),
        "stop": next(i for i, call in enumerate(calls) if "stop" in call),
        "control": next(
            i for i, call in enumerate(calls)
            if "run" in call and "migrate-control" in call
        ),
        "tenants": next(
            i for i, call in enumerate(calls)
            if "run" in call and "migrate-tenants" in call
        ),
        "up": next(i for i, call in enumerate(calls) if "up" in call),
        "health": next(
            i for i, call in enumerate(calls)
            if call and call[0] == "inspect" and call[-1] == "app-id"
        ),
        "probe": next(i for i, call in enumerate(calls) if call and call[0] == "run"),
    }
    assert list(positions.values()) == sorted(positions.values())
    assert "registry.example/inventory:new" in (deploy_dir / "current.env").read_text()
    assert "registry.example/inventory:old" in (deploy_dir / "previous.env").read_text()
    probe = calls[positions["probe"]]
    assert probe[probe.index("--network") + 1] == "frp-network"
    assert probe[probe.index("--entrypoint") + 1] == "python"
    assert "registry.example/inventory:new" in probe


def test_backup_confirmation_is_exact_and_blocks_stop_and_migrations(tmp_path):
    for value in ("", "yes", "backup_verified", " backup-verified"):
        result, calls, _ = invoke(tmp_path / (value.strip() or "empty"), "deploy", backup=value)
        assert result.returncode != 0
        assert not any("stop" in call for call in calls)
        assert not any("migrate-control" in call or "migrate-tenants" in call for call in calls)


def test_invalid_health_controls_fail_before_destructive_work(tmp_path):
    cases = (
        {"health_attempts": "0"},
        {"health_attempts": "three"},
        {"health_interval": "1.5"},
        {"health_interval": "-1"},
    )
    for index, values in enumerate(cases):
        result, calls, _ = invoke(tmp_path / str(index), "deploy", **values)
        assert result.returncode != 0
        assert not any("stop" in call or "up" in call for call in calls)
        assert not any(
            "migrate-control" in call or "migrate-tenants" in call for call in calls
        )


def test_deploy_creates_missing_network_before_stopping_services(tmp_path):
    result, calls, _ = invoke(tmp_path, "deploy", mode="network-absent")
    assert result.returncode == 0, result.stderr
    create = next(i for i, call in enumerate(calls) if call[:2] == ["network", "create"])
    connect = next(i for i, call in enumerate(calls) if call[:2] == ["network", "connect"])
    stop = next(i for i, call in enumerate(calls) if "stop" in call)
    assert create < connect < stop


def test_check_reports_missing_network_without_mutating_it(tmp_path):
    result, calls, _ = invoke(tmp_path, "check", mode="network-absent")
    assert result.returncode != 0
    assert "network" in result.stderr.lower()
    assert not any(call[:2] in (["network", "create"], ["network", "connect"]) for call in calls)
    assert not any("stop" in call or "up" in call for call in calls)


def test_check_reports_disconnected_frpc_without_connecting_it(tmp_path):
    result, calls, _ = invoke(tmp_path, "check", mode="frpc-disconnected")
    assert result.returncode != 0
    assert not any(call[:2] == ["network", "connect"] for call in calls)


def test_check_rejects_app_env_without_exact_0600_permissions(tmp_path):
    result, calls, _ = invoke(tmp_path, "check", app_env_mode=0o640)
    assert result.returncode != 0
    assert "0600" in result.stderr
    assert not any(call[:2] in (["network", "create"], ["network", "connect"]) for call in calls)


def test_check_validates_current_compose_without_mutating_runtime(tmp_path):
    result, calls, _ = invoke(tmp_path, "check")
    assert result.returncode == 0, result.stderr
    assert any("config" in call for call in calls)
    assert not any(call[:2] in (["network", "create"], ["network", "connect"]) for call in calls)
    assert not any("stop" in call or "up" in call for call in calls)


def test_probe_failure_keeps_promoted_release_metadata(tmp_path):
    result, calls, deploy_dir = invoke(tmp_path, "deploy", mode="probe-fail")
    assert result.returncode != 0
    assert any(call and call[0] == "run" for call in calls)
    assert "registry.example/inventory:new" in (deploy_dir / "current.env").read_text()
    assert "registry.example/inventory:old" in (deploy_dir / "previous.env").read_text()


def test_health_failure_keeps_promoted_release_metadata(tmp_path):
    result, calls, deploy_dir = invoke(tmp_path, "deploy", mode="health-fail")
    assert result.returncode != 0
    assert any(
        call and call[0] == "inspect" and call[-1] == "app-id" for call in calls
    )
    assert not any(call and call[0] == "run" for call in calls)
    assert "registry.example/inventory:new" in (deploy_dir / "current.env").read_text()
    assert "registry.example/inventory:old" in (deploy_dir / "previous.env").read_text()


def test_status_prints_only_release_image_metadata_and_compose_ps(tmp_path):
    result, calls, _ = invoke(tmp_path, "status")
    assert result.returncode == 0, result.stderr
    assert "current IMAGE_REF=registry.example/inventory:old" in result.stdout
    assert "previous IMAGE_REF=registry.example/inventory:older" in result.stdout
    assert "APP_ENV_FILE" not in result.stdout
    assert any("ps" in call for call in calls)
    assert not any(call and call[0] == "inspect" for call in calls)
    assert not any("stop" in call or "up" in call for call in calls)


def test_logs_validates_tail_before_calling_compose(tmp_path):
    result, calls, _ = invoke(tmp_path, "logs", log_tail="10;uname")
    assert result.returncode != 0
    assert "LOG_TAIL" in result.stderr
    assert calls == []


def test_logs_requests_only_app_and_worker(tmp_path):
    result, calls, _ = invoke(tmp_path, "logs", log_tail="75")
    assert result.returncode == 0, result.stderr
    log_call = next(call for call in calls if "logs" in call)
    assert log_call[-5:] == ["logs", "--tail", "75", "app", "worker"]


def test_unknown_action_fails_without_calling_docker(tmp_path):
    result, calls, _ = invoke(tmp_path, "destroy")
    assert result.returncode != 0
    assert calls == []
