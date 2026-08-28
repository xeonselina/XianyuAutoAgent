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

args = sys.argv[1:]
mode = os.environ.get("FAKE_DOCKER_MODE", "success")
with open(os.environ["FAKE_DOCKER_CALLS"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps(args) + "\n")

if args[:2] == ["compose", "version"]:
    raise SystemExit(0)
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


def _release_env(image_ref, app_env, network):
    return (
        f"IMAGE_REF={image_ref}\n"
        f"APP_ENV_FILE={app_env}\n"
        f"FRPC_NETWORK={network}\n"
    )


def invoke(tmp_path, action, *, mode="success", backup="backup-verified", current=True,
           app_env_mode=0o600, log_tail=None):
    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir(parents=True)
    (deploy_dir / "docker-compose.yml").write_text("services: {}\n")

    app_env = tmp_path / "app.env"
    app_env.write_text("SECRET=value\n")
    app_env.chmod(app_env_mode)

    if current:
        (deploy_dir / "current.env").write_text(
            _release_env("registry.example/inventory:old", app_env, "frp-network")
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
    calls_file = tmp_path / "docker-calls.jsonl"

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
        "FAKE_DOCKER_MODE": mode,
    }
    if log_tail is not None:
        env["LOG_TAIL"] = log_tail

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


def test_pull_failure_never_stops_old_services(tmp_path):
    result, calls, deploy_dir = invoke(tmp_path, "deploy", mode="pull-fail")
    assert result.returncode != 0
    assert not any("stop" in call for call in calls)
    assert "registry.example/inventory:old" in (deploy_dir / "current.env").read_text()


def test_migration_failure_stops_without_starting_new_services(tmp_path):
    result, calls, deploy_dir = invoke(tmp_path, "deploy", mode="migration-fail")
    assert result.returncode != 0
    assert any("stop" in call for call in calls)
    assert not any("up" in call for call in calls)
    assert "registry.example/inventory:old" in (deploy_dir / "current.env").read_text()
    assert "registry.example/inventory:older" in (deploy_dir / "previous.env").read_text()
    assert "remain stopped" in result.stderr
    assert not list(deploy_dir.glob(".candidate.env.*"))


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
