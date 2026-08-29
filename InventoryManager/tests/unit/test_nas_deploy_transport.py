import json
import os
import hashlib
import stat
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/deploy_nas.sh"


FAKE_SSH = r'''#!/usr/bin/env python3
import json
import os
import sys

argv = sys.argv[1:]
stdin_bytes = sys.stdin.buffer.read()
with open(os.environ["FAKE_SSH_LOG"], "a") as handle:
    handle.write(json.dumps({
        "argv": argv,
        "stdin_size": len(stdin_bytes),
        "has_nas_pass_environment": "NAS_PASS" in os.environ,
        "has_sudo_pass_environment": "SUDO_PASS" in os.environ,
        "has_nas_password_environment": "NAS_PASSWORD" in os.environ,
        "has_sudo_password_environment": "SUDO_PASSWORD" in os.environ,
        "has_sshpass_environment": "SSHPASS" in os.environ,
    }) + "\n")

command = argv[-1] if argv else ""
if command == "printf '%s\\n' \"$HOME\"":
    print("/volume1/homes/deployer")

failure = os.environ.get("FAKE_SSH_FAIL_MATCH", "")
if failure and failure in command:
    sys.exit(41)
'''


FAKE_STAT = r'''#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["FAKE_EARLY_LOG"], "a") as handle:
    handle.write(json.dumps({
        "credential_environment": {
            name: name in os.environ
            for name in (
                "NAS_PASS", "SUDO_PASS", "NAS_PASSWORD", "SUDO_PASSWORD", "SSHPASS",
            )
        },
    }) + "\n")

if sys.argv[1:3] == ["-c", "%a"] or sys.argv[1:3] == ["-f", "%Lp"]:
    print("600")
    sys.exit(0)
sys.exit(1)
'''


FAKE_SSHPASS = r'''#!/usr/bin/env python3
import json
import os
import sys

argv = sys.argv[1:]
with open(os.environ["FAKE_SSHPASS_LOG"], "a") as handle:
    handle.write(json.dumps({
        "argv": argv,
        "has_sshpass_environment": bool(os.environ.get("SSHPASS")),
    }) + "\n")

if not argv or argv[0] != "-e":
    sys.exit(42)
os.execvpe(argv[1], argv[1:], os.environ)
'''


BASE_CONFIG = {
    "NAS_HOST": "nas.example.test",
    "NAS_USER": "deployer",
    "NAS_PORT": "2222",
    "NAS_DEPLOY_DIR": "/volume1/docker/inventory-manager",
    "APP_ENV_FILE": "/volume1/docker/inventory-manager/app.env",
    "FRPC_CONTAINER": "frpc-client",
    "FRPC_NETWORK": "xianyu-frp",
    "LOG_TAIL": "200",
}


def write_executable(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def read_json_lines(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def invoke(
    tmp_path,
    action="check",
    *,
    config_updates=None,
    extra_lines=(),
    env_updates=None,
    trace=False,
    password=None,
    sudo_password=None,
):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ssh_log = tmp_path / "ssh.jsonl"
    sshpass_log = tmp_path / "sshpass.jsonl"
    early_log = tmp_path / "early.jsonl"
    write_executable(fake_bin / "ssh", FAKE_SSH)
    write_executable(fake_bin / "sshpass", FAKE_SSHPASS)
    write_executable(fake_bin / "stat", FAKE_STAT)

    config = dict(BASE_CONFIG)
    config.update(config_updates or {})
    if password is not None:
        config["NAS_PASS"] = password
    if sudo_password is not None:
        config["SUDO_PASS"] = sudo_password

    config_home = tmp_path / "config"
    config_file = config_home / "xianyu-agent/nas.env"
    config_file.parent.mkdir(parents=True)
    lines = [f"{key}={value}" for key, value in config.items()]
    lines.extend(extra_lines)
    config_file.write_text("\n".join(lines) + "\n")
    config_file.chmod(0o600)

    env = dict(os.environ)
    for key in (
        *BASE_CONFIG,
        "NAS_PASS",
        "SUDO_PASS",
        "NAS_PASSWORD",
        "SUDO_PASSWORD",
        "SSH_KEY",
        "SSHPASS",
    ):
        env.pop(key, None)
    env.update({
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "XDG_CONFIG_HOME": str(config_home),
        "FAKE_SSH_LOG": str(ssh_log),
        "FAKE_SSHPASS_LOG": str(sshpass_log),
        "FAKE_EARLY_LOG": str(early_log),
        "IMAGE_REPOSITORY": "registry.example.test/team/inventory-manager",
        "IMAGE_TAG": "20260828-120000-abc123def456",
        "BACKUP_VERIFIED": "backup-verified",
    })
    env.update(env_updates or {})

    command = ["bash"]
    if trace:
        command.append("-x")
    command.extend((str(SCRIPT), action))
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, {
        "ssh": read_json_lines(ssh_log),
        "sshpass": read_json_lines(sshpass_log),
        "early": read_json_lines(early_log),
    }


def ssh_commands(calls):
    return [call["argv"][-1] for call in calls["ssh"]]


def test_password_never_appears_in_xtrace_or_process_arguments(tmp_path):
    password = "transport-secret=with spaces"
    sudo_password = "sudo-secret=with spaces"
    result, calls = invoke(
        tmp_path,
        "check",
        trace=True,
        password=password,
        sudo_password=sudo_password,
    )

    assert result.returncode == 0, result.stderr
    serialized = result.stdout + result.stderr + json.dumps(calls)
    assert password not in serialized
    assert sudo_password not in serialized
    assert calls["sshpass"]
    assert all(call["argv"][0] == "-e" for call in calls["sshpass"])
    assert all(call["has_sshpass_environment"] for call in calls["sshpass"])
    assert not any(call["has_nas_pass_environment"] for call in calls["ssh"])
    assert not any(call["has_sudo_pass_environment"] for call in calls["ssh"])
    assert not any(call["has_nas_password_environment"] for call in calls["ssh"])
    assert not any(call["has_sudo_password_environment"] for call in calls["ssh"])


def test_credentials_are_unexported_before_the_first_external_process(tmp_path):
    public_password = "public-transport-secret"
    public_sudo_password = "public-sudo-secret"
    inherited_alias = "inherited-private-alias"
    inherited_sshpass = "inherited-sshpass"
    result, calls = invoke(
        tmp_path,
        "check",
        env_updates={
            "NAS_PASS": public_password,
            "SUDO_PASS": public_sudo_password,
            "NAS_PASSWORD": inherited_alias,
            "SUDO_PASSWORD": inherited_alias,
            "SSHPASS": inherited_sshpass,
        },
    )

    assert result.returncode == 0, result.stderr
    assert calls["early"]
    assert all(
        not present
        for present in calls["early"][0]["credential_environment"].values()
    )
    assert all(not call["has_nas_pass_environment"] for call in calls["ssh"])
    assert all(not call["has_sudo_pass_environment"] for call in calls["ssh"])
    assert all(not call["has_nas_password_environment"] for call in calls["ssh"])
    assert all(not call["has_sudo_password_environment"] for call in calls["ssh"])
    serialized = result.stdout + result.stderr + json.dumps(calls)
    for secret in (
        public_password,
        public_sudo_password,
        inherited_alias,
        inherited_sshpass,
    ):
        assert secret not in serialized


def test_upload_uses_ssh_stdin_instead_of_sftp_scp_or_rsync(tmp_path):
    result, calls = invoke(tmp_path, "check")

    assert result.returncode == 0, result.stderr
    flattened = json.dumps(calls)
    assert "scp" not in flattened
    assert "sftp" not in flattened
    assert "rsync" not in flattened
    uploads = [call for call in calls["ssh"] if "cat >" in call["argv"][-1]]
    assert len(uploads) == 2
    assert all(call["stdin_size"] > 0 for call in uploads)
    assert all("/volume1/homes/deployer/.xianyu-agent-" in call["argv"][-1] for call in uploads)
    assert all("set -C; cat >" in call["argv"][-1] for call in uploads)


def test_unknown_action_fails_before_ssh(tmp_path):
    result, calls = invoke(tmp_path, "destroy")

    assert result.returncode == 2
    assert calls["ssh"] == []
    assert "check|deploy|status|logs" in result.stderr


def test_explicit_environment_overrides_file_values(tmp_path):
    result, calls = invoke(
        tmp_path,
        "status",
        config_updates={"NAS_HOST": "ignored.example.test", "NAS_PORT": "22"},
        env_updates={"NAS_HOST": "override.example.test", "NAS_PORT": "2200"},
    )

    assert result.returncode == 0, result.stderr
    for call in calls["ssh"]:
        assert any(part.endswith("@override.example.test") for part in call["argv"])
        assert not any(part.endswith("@ignored.example.test") for part in call["argv"])
        assert call["argv"][call["argv"].index("-p") + 1] == "2200"


def test_config_values_are_literal_and_split_only_on_first_equals(tmp_path):
    marker = tmp_path / "must-not-exist"
    password = f"literal=$(touch {marker})=tail"
    result, calls = invoke(tmp_path, password=password)

    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert password not in result.stdout + result.stderr + json.dumps(calls)


@pytest.mark.parametrize(
    ("updates", "extra_lines"),
    (
        ({}, ("UNEXPECTED_KEY=value",)),
        ({"NAS_HOST": "nas.example.test;touch-bad"}, ()),
        ({"NAS_USER": "deployer$(bad)"}, ()),
        ({"NAS_PORT": "22;bad"}, ()),
        ({"NAS_PORT": "70000"}, ()),
        ({"NAS_DEPLOY_DIR": "relative/deploy"}, ()),
        ({"NAS_DEPLOY_DIR": "/volume1/docker/../bad"}, ()),
        ({"APP_ENV_FILE": "/volume1/docker/app env"}, ()),
        ({"FRPC_CONTAINER": "frpc;bad"}, ()),
        ({"FRPC_NETWORK": "frp network"}, ()),
        ({"LOG_TAIL": "200;bad"}, ()),
    ),
)
def test_unsafe_configuration_fails_before_ssh(tmp_path, updates, extra_lines):
    result, calls = invoke(
        tmp_path,
        "logs",
        config_updates=updates,
        extra_lines=extra_lines,
    )

    assert result.returncode != 0
    assert calls["ssh"] == []


def test_actions_install_verified_root_assets_then_run_root_release_script(tmp_path):
    result, calls = invoke(tmp_path, "deploy")

    assert result.returncode == 0, result.stderr
    commands = ssh_commands(calls)
    install_index = next(i for i, command in enumerate(commands) if "install -d -o root" in command)
    lifecycle_index = next(
        i for i, command in enumerate(commands)
        if ".xianyu-agent-release/remote_release.sh' 'deploy'" in command
    )
    assert install_index < lifecycle_index
    assert "sudo -n" in commands[install_index]
    assert "/volume1/docker/inventory-manager/docker-compose.yml" in commands[install_index]
    assert "/volume1/docker/inventory-manager/.xianyu-agent-release/remote_release.sh" in commands[install_index]
    assert "install -o root -g root -m 0644" in commands[install_index]
    assert "install -o root -g root -m 0755" in commands[install_index]
    assert "[ ! -L /volume1/homes/deployer/.xianyu-agent-compose-" in commands[install_index]
    assert "[ ! -L /volume1/homes/deployer/.xianyu-agent-remote_release-" in commands[install_index]
    assert "/volume1/docker/inventory-manager/.xianyu-agent-release/remote_release.sh" in commands[lifecycle_index]
    assert ".xianyu-agent-remote_release-" not in commands[lifecycle_index]
    assert "registry.example.test/team/inventory-manager:20260828-120000-abc123def456" in commands[lifecycle_index]

    compose_hash = hashlib.sha256((ROOT / "deploy/nas/docker-compose.yml").read_bytes()).hexdigest()
    release_hash = hashlib.sha256((ROOT / "deploy/nas/remote_release.sh").read_bytes()).hexdigest()
    assert commands[install_index].count(compose_hash) == 2
    assert commands[install_index].count(release_hash) == 2
    assert "hash_file()" in commands[install_index]
    assert commands[install_index].count("hash_file ") == 4
    assert "mv /volume1/homes/deployer/.xianyu-agent-compose-" in commands[install_index]
    assert "chown root:root" in commands[install_index]


@pytest.mark.parametrize("action", ("check", "status", "logs"))
def test_read_only_actions_refresh_verified_assets_but_only_run_read_only_action(action, tmp_path):
    result, calls = invoke(tmp_path, action)

    assert result.returncode == 0, result.stderr
    commands = ssh_commands(calls)
    install_index = next(i for i, command in enumerate(commands) if "install -d -o root" in command)
    lifecycle_index = next(
        i for i, command in enumerate(commands)
        if f".xianyu-agent-release/remote_release.sh' '{action}'" in command
    )
    assert install_index < lifecycle_index
    assert ".xianyu-agent-remote_release-" not in commands[lifecycle_index]
    assert "'deploy'" not in commands[lifecycle_index]
    assert "docker " not in commands[lifecycle_index]
    cleanup = commands[-1]
    assert cleanup.startswith("rm -f -- ")
    assert "/volume1/homes/deployer/.xianyu-agent-" in cleanup
    assert "rm -r" not in cleanup
    assert "/volume1/docker/inventory-manager" not in cleanup
    root_cleanup = commands[-2]
    assert "sudo -n rm -f -- " in root_cleanup
    assert ".xianyu-agent-release/.incoming-compose-" in root_cleanup
    assert ".xianyu-agent-release/.incoming-remote_release-" in root_cleanup


def test_sudo_password_is_sent_only_over_stdin(tmp_path):
    secret = "synthetic-sudo-password"
    result, calls = invoke(tmp_path, "deploy", sudo_password=secret)

    assert result.returncode == 0, result.stderr
    serialized = result.stdout + result.stderr + json.dumps(calls)
    assert secret not in serialized
    sudo_calls = [call for call in calls["ssh"] if "sudo -S -p ''" in call["argv"][-1]]
    assert len(sudo_calls) == 3
    assert all(call["stdin_size"] > 0 for call in sudo_calls)
    assert not any("sudo -n" in call["argv"][-1] for call in sudo_calls)


def test_ssh_key_and_required_options_are_argv_elements(tmp_path):
    key = tmp_path / "id_ed25519"
    key.write_text("synthetic key placeholder")
    key.chmod(0o600)
    result, calls = invoke(tmp_path, config_updates={"SSH_KEY": str(key)})

    assert result.returncode == 0, result.stderr
    first = calls["ssh"][0]["argv"]
    assert first[:8] == [
        "-p", "2222", "-o", "ConnectTimeout=10", "-o",
        "StrictHostKeyChecking=accept-new", "-i", str(key),
    ]
    assert "deployer@nas.example.test" in first


def test_deploy_requires_backup_acknowledgement_before_ssh(tmp_path):
    result, calls = invoke(
        tmp_path,
        "deploy",
        env_updates={"BACKUP_VERIFIED": "not-verified"},
    )

    assert result.returncode != 0
    assert calls["ssh"] == []
    assert "BACKUP_VERIFIED" in result.stderr


def test_cleanup_runs_after_remote_failure_without_masking_status(tmp_path):
    result, calls = invoke(
        tmp_path,
        "check",
        env_updates={"FAKE_SSH_FAIL_MATCH": ".sh' 'check'"},
    )

    assert result.returncode == 41
    assert ssh_commands(calls)[-1].startswith("rm -f -- ")
