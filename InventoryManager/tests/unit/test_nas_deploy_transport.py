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
import shlex
import subprocess
import sys

argv = sys.argv[1:]
command = argv[-1] if argv else ""
tokens = shlex.split(command)
execute_root = (
    os.environ.get("FAKE_EXECUTE_REMOTE_ROOT") == "1"
    and tokens
    and tokens[0] == "sudo"
)
stdin_read = not execute_root
stdin_bytes = sys.stdin.buffer.read() if stdin_read else b""
with open(os.environ["FAKE_SSH_LOG"], "a") as handle:
    handle.write(json.dumps({
        "argv": argv,
        "stdin_size": len(stdin_bytes) if stdin_read else None,
        "stdin_read": stdin_read,
        "has_nas_pass_environment": "NAS_PASS" in os.environ,
        "has_sudo_pass_environment": "SUDO_PASS" in os.environ,
        "has_nas_password_environment": "NAS_PASSWORD" in os.environ,
        "has_sudo_password_environment": "SUDO_PASSWORD" in os.environ,
        "has_sshpass_environment": "SSHPASS" in os.environ,
    }) + "\n")

if command == "printf '%s\\n' \"$HOME\"":
    print("/volume1/homes/deployer")

if execute_root:
    completed = subprocess.run(
        ["/bin/sh", "-c", command],
        stdin=sys.stdin.buffer,
        capture_output=True,
        env=os.environ,
    )
    sys.stdout.buffer.write(completed.stdout)
    sys.stderr.buffer.write(completed.stderr)
    raise SystemExit(completed.returncode)

failure = os.environ.get("FAKE_SSH_FAIL_MATCH", "")
if failure and failure in command:
    sys.exit(41)
'''


FAKE_SUDO = r'''#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
mode = os.environ.get("FAKE_SUDO_MODE", "consume")
password_mode = "-S" in args
consumed = b""
if password_mode and mode == "consume":
    consumed = sys.stdin.buffer.readline()

index = 0
while index < len(args) and args[index].startswith("-"):
    if args[index] == "-p":
        index += 2
    else:
        index += 1
command = args[index:]

with open(os.environ["FAKE_SUDO_LOG"], "a") as handle:
    handle.write(json.dumps({
        "argv": args,
        "mode": mode,
        "password_mode": password_mode,
        "consumed_size": len(consumed),
        "credential_names": [
            name for name in (
                "NAS_PASS", "SUDO_PASS", "NAS_PASSWORD", "SUDO_PASSWORD", "SSHPASS",
            )
            if name in os.environ
        ],
    }) + "\n")

if mode == "auth-fail":
    raise SystemExit(73)
if not command or command[:2] != ["env", "-i"]:
    raise SystemExit(96)

wrapper_index = command.index("sh", 2)
if command[wrapper_index:wrapper_index + 4] != [
    "sh", "-c", 'exec </dev/null; exec "$@"', "sh",
]:
    raise SystemExit(95)
actual = command[wrapper_index + 4:]
action_prefix = []
if actual[:2] == ["sh", "-c"]:
    label = "install"
elif actual and actual[0] == "env" and any("remote_release.sh" in part for part in actual):
    label = "lifecycle"
    script_index = next(
        index for index, part in enumerate(actual) if "remote_release.sh" in part
    )
    action_prefix = actual[:script_index]
elif actual and actual[0] == "rm":
    label = "cleanup"
else:
    raise SystemExit(94)

exit_code = "41" if os.environ.get("FAKE_ROOT_FAIL_LABEL") == label else "0"
command[wrapper_index + 4:] = action_prefix + [
    sys.executable,
    os.environ["FAKE_ROOT_PROBE"],
    os.environ["FAKE_ROOT_PROBE_LOG"],
    label,
    exit_code,
]
os.execvpe(command[0], command, os.environ)
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


FAKE_ROOT_PROBE = r'''#!/usr/bin/env python3
import json
import os
import sys

stdin_bytes = sys.stdin.buffer.read()
with open(sys.argv[1], "a") as handle:
    json.dump({
        "label": sys.argv[2],
        "stdin_size": len(stdin_bytes),
        "path": os.environ.get("PATH"),
        "home": os.environ.get("HOME"),
        "min_free_space_mb": os.environ.get("MIN_FREE_SPACE_MB"),
        "credential_names": [
            name for name in (
                "NAS_PASS", "SUDO_PASS", "NAS_PASSWORD", "SUDO_PASSWORD", "SSHPASS",
            )
            if name in os.environ
        ],
        "make_names": [
            name for name in ("MAKEFLAGS", "MAKELEVEL", "MFLAGS")
            if name in os.environ
        ],
    }, handle)
    handle.write("\n")
raise SystemExit(int(sys.argv[3]))
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
    "MIN_FREE_SPACE_MB": "1024",
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
    execute_remote_root=False,
    fake_sudo_mode="consume",
    root_fail_label=None,
):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ssh_log = tmp_path / "ssh.jsonl"
    sshpass_log = tmp_path / "sshpass.jsonl"
    sudo_log = tmp_path / "sudo.jsonl"
    early_log = tmp_path / "early.jsonl"
    root_probe_log = tmp_path / "root-probe.json"
    root_probe = tmp_path / "root-probe.py"
    root_probe.write_text(FAKE_ROOT_PROBE)
    write_executable(fake_bin / "ssh", FAKE_SSH)
    write_executable(fake_bin / "sshpass", FAKE_SSHPASS)
    write_executable(fake_bin / "sudo", FAKE_SUDO)
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
        "FAKE_SUDO_LOG": str(sudo_log),
        "FAKE_EARLY_LOG": str(early_log),
        "FAKE_ROOT_PROBE": str(root_probe),
        "FAKE_ROOT_PROBE_LOG": str(root_probe_log),
        "IMAGE_REPOSITORY": "registry.example.test/team/inventory-manager",
        "IMAGE_TAG": "20260828-120000-abc123def456",
        "BACKUP_VERIFIED": "backup-verified",
        "FAKE_SUDO_MODE": fake_sudo_mode,
    })
    env.update(env_updates or {})
    if execute_remote_root:
        env["FAKE_EXECUTE_REMOTE_ROOT"] = "1"
    if root_fail_label is not None:
        env["FAKE_ROOT_FAIL_LABEL"] = root_fail_label

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
        "sudo": read_json_lines(sudo_log),
        "early": read_json_lines(early_log),
        "root_probe": read_json_lines(root_probe_log),
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
    assert all(
        "PubkeyAuthentication=no" in call["argv"]
        and "PreferredAuthentications=keyboard-interactive,password" in call["argv"]
        and "NumberOfPasswordPrompts=1" in call["argv"]
        for call in calls["ssh"]
    )
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
        ({"MIN_FREE_SPACE_MB": "08"}, ()),
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
    assert "chown root:root /volume1/docker/inventory-manager; chmod 0755" in commands[install_index]
    assert "chmod 0644" in commands[install_index]
    assert "chmod 0755" in commands[install_index]
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
    assert "mv -f -- /volume1/docker/inventory-manager/.xianyu-agent-release/.incoming-compose-" in commands[install_index]
    assert " /volume1/docker/inventory-manager/docker-compose.yml" in commands[install_index]
    assert "mv -f -- /volume1/docker/inventory-manager/.xianyu-agent-release/.incoming-remote_release-" in commands[install_index]
    assert " /volume1/docker/inventory-manager/.xianyu-agent-release/remote_release.sh" in commands[install_index]
    assert "install -o root -g root" not in commands[install_index]


@pytest.mark.parametrize(
    ("sudo_password", "fake_sudo_mode", "password_consumed"),
    (
        (None, "consume", False),
        ("synthetic-sudo-password", "consume", True),
        ("synthetic-sudo-password", "cached", False),
    ),
)
def test_single_sudo_root_wrapper_closes_stdin_and_executes_clean_actions(
    tmp_path, sudo_password, fake_sudo_mode, password_consumed
):
    result, calls = invoke(
        tmp_path,
        "deploy",
        sudo_password=sudo_password,
        execute_remote_root=True,
        fake_sudo_mode=fake_sudo_mode,
        env_updates={
            "MAKEFLAGS": "--eval=bad-target:;touch /tmp/never",
            "MAKELEVEL": "9",
            "MFLAGS": "-k",
        },
    )

    assert result.returncode == 0, result.stderr
    assert [record["label"] for record in calls["root_probe"]] == [
        "install", "lifecycle", "cleanup",
    ]
    for record in calls["root_probe"]:
        assert record["stdin_size"] == 0
        assert record["path"] == "/usr/local/bin:/usr/bin:/bin"
        assert record["home"] == "/root"
        assert record["credential_names"] == []
        assert record["make_names"] == []
    lifecycle_probe = next(
        record for record in calls["root_probe"] if record["label"] == "lifecycle"
    )
    assert lifecycle_probe["min_free_space_mb"] == "1024"

    root_calls = [
        call for call in calls["ssh"]
        if " env -i PATH='/usr/local/bin:/usr/bin:/bin' HOME='/root' sh -c "
        in call["argv"][-1]
    ]
    assert len(root_calls) == 3
    assert all(not call["stdin_read"] and call["stdin_size"] is None for call in root_calls)
    assert all(
        "PATH='/usr/local/bin:/usr/bin:/bin' HOME='/root'" in call["argv"][-1]
        for call in root_calls
    )
    assert all('sh -c \'exec </dev/null; exec "$@"\' sh' in call["argv"][-1] for call in root_calls)
    if sudo_password is None:
        assert all(call["argv"][-1].startswith("sudo -n env -i ") for call in root_calls)
    else:
        assert all(call["argv"][-1].startswith("sudo -S -p '' env -i ") for call in root_calls)

    assert len(calls["sudo"]) == 3
    assert all(record["credential_names"] == [] for record in calls["sudo"])
    assert all(record["password_mode"] == (sudo_password is not None) for record in calls["sudo"])
    if password_consumed:
        assert all(record["consumed_size"] > 0 for record in calls["sudo"])
    else:
        assert all(record["consumed_size"] == 0 for record in calls["sudo"])

    serialized = result.stdout + result.stderr + json.dumps(calls)
    if sudo_password is not None:
        assert sudo_password not in serialized
    assert "--eval=bad-target" not in json.dumps(calls["root_probe"])
    assert not any("NAS_PASS" in call["argv"][-1] for call in root_calls)
    assert not any("SUDO_PASS" in call["argv"][-1] for call in root_calls)


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
    assert root_cleanup.startswith(
        "sudo -n env -i PATH='/usr/local/bin:/usr/bin:/bin' HOME='/root' "
        "sh -c 'exec </dev/null; exec \"$@\"' sh "
    )
    assert "'rm' '-f' '--'" in root_cleanup
    assert ".xianyu-agent-release/.incoming-compose-" in root_cleanup
    assert ".xianyu-agent-release/.incoming-remote_release-" in root_cleanup


def test_sudo_password_is_sent_only_over_stdin(tmp_path):
    secret = "synthetic-sudo-password"
    result, calls = invoke(tmp_path, "deploy", sudo_password=secret)

    assert result.returncode == 0, result.stderr
    serialized = result.stdout + result.stderr + json.dumps(calls)
    assert secret not in serialized
    password_root_calls = [
        call for call in calls["ssh"]
        if call["argv"][-1].startswith(
            "sudo -S -p '' env -i PATH='/usr/local/bin:/usr/bin:/bin' "
        )
    ]
    assert len(password_root_calls) == 3
    assert all(
        call["stdin_read"] and call["stdin_size"] > 0
        for call in password_root_calls
    )
    assert all('sh -c \'exec </dev/null; exec "$@"\'' in call["argv"][-1] for call in password_root_calls)


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


def test_cached_password_sudo_cleanup_preserves_lifecycle_failure_status(tmp_path):
    result, calls = invoke(
        tmp_path,
        "check",
        sudo_password="synthetic-sudo-password",
        execute_remote_root=True,
        fake_sudo_mode="cached",
        root_fail_label="lifecycle",
    )

    assert result.returncode == 41
    root_calls = [
        call for call in calls["ssh"]
        if call["argv"][-1].startswith(
            "sudo -S -p '' env -i PATH='/usr/local/bin:/usr/bin:/bin' "
        )
    ]
    assert len(root_calls) == 3
    assert all(
        not call["stdin_read"] and call["stdin_size"] is None for call in root_calls
    )
    assert [record["label"] for record in calls["root_probe"]] == [
        "install", "lifecycle", "cleanup",
    ]
    assert all(record["stdin_size"] == 0 for record in calls["root_probe"])
    assert ssh_commands(calls)[-1].startswith("rm -f -- ")


def test_sudo_authentication_failure_blocks_root_action_and_runs_exact_cleanup(tmp_path):
    result, calls = invoke(
        tmp_path,
        "check",
        sudo_password="synthetic-sudo-password",
        execute_remote_root=True,
        fake_sudo_mode="auth-fail",
    )

    assert result.returncode == 73
    assert calls["root_probe"] == []
    assert len(calls["sudo"]) == 2
    assert all(record["password_mode"] for record in calls["sudo"])
    assert all(record["credential_names"] == [] for record in calls["sudo"])
    assert ssh_commands(calls)[-1].startswith("rm -f -- ")
