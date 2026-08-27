#!/usr/bin/env python3
"""Run mobile mock and real-backend Playwright suites on x86 containers."""

from __future__ import annotations

import base64
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator


AMD64_PLATFORM = "linux/amd64"
APP_IMAGE = os.environ.get(
    "E2E_APP_IMAGE", "inventory-manager:saas-main-lite"
)
MARIADB_IMAGE = os.environ.get("E2E_MARIADB_IMAGE", "mariadb:10.11")
PLAYWRIGHT_IMAGE = os.environ.get(
    "E2E_PLAYWRIGHT_IMAGE", "mcr.microsoft.com/playwright:v1.62.1-noble"
)
RESOURCE_PREFIX = "xianyu-mobile-e2e-"
E2E_LABEL_KEY = "com.xianyu.e2e"
E2E_LABEL_VALUE = "mobile-real-backend"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_RUNNER = PROJECT_ROOT / "scripts" / "mobile_e2e_backend.py"
GENERATED_FRONTEND_FILES = (
    Path("frontend/auto-imports.d.ts"),
    Path("frontend/components.d.ts"),
)
_ACTIVE_PROCESS: subprocess.Popen[str] | None = None


def docker_run_prefix() -> list[str]:
    return ["docker", "run", "--platform", AMD64_PLATFORM]


def assert_safe_resource_name(name: str) -> str:
    if (
        not isinstance(name, str)
        or not name.startswith(RESOURCE_PREFIX)
        or not name[len(RESOURCE_PREFIX):]
        or not all(char.isalnum() or char == "-" for char in name)
    ):
        raise ValueError("resource name must use the xianyu-mobile-e2e prefix")
    return name


def database_ping_command(name: str) -> list[str]:
    return [
        "docker", "exec", "-e", "MYSQL_PWD", name,
        "mariadb-admin", "ping", "-uroot",
        "--host=127.0.0.1", "--protocol=tcp", "--silent",
    ]


def writable_generated_file_mounts(
    source_root: Path,
    scratch_root: Path,
) -> list[str]:
    """Bind generated declarations from scratch over the read-only source tree."""
    scratch_root.mkdir(parents=True, exist_ok=True)
    mounts: list[str] = []
    for relative_path in GENERATED_FRONTEND_FILES:
        scratch_file = scratch_root / relative_path.name
        shutil.copyfile(source_root / relative_path, scratch_file)
        mounts.extend([
            "--mount",
            (
                f"type=bind,source={scratch_file},"
                f"target=/workspace/{relative_path}"
            ),
        ])
    return mounts


@dataclass(frozen=True)
class ResourceNames:
    run_id: str

    @property
    def network(self) -> str:
        return f"{RESOURCE_PREFIX}{self.run_id}-network"

    @property
    def database_container(self) -> str:
        return f"{RESOURCE_PREFIX}{self.run_id}-db"

    @property
    def app_container(self) -> str:
        return f"{RESOURCE_PREFIX}{self.run_id}-app"


def _run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    capture_output: bool = False,
    check: bool = True,
    quiet: bool = False,
) -> subprocess.CompletedProcess[str]:
    global _ACTIVE_PROCESS

    if capture_output and quiet:
        raise ValueError("capture_output and quiet cannot both be enabled")
    stdout_target = (
        subprocess.PIPE
        if capture_output
        else subprocess.DEVNULL if quiet else None
    )
    stderr_target = (
        subprocess.PIPE
        if capture_output
        else subprocess.DEVNULL if quiet else None
    )
    process = subprocess.Popen(
        command,
        text=True,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=stdout_target,
        stderr=stderr_target,
        start_new_session=True,
    )
    _ACTIVE_PROCESS = process
    try:
        stdout, stderr = process.communicate()
        completed = subprocess.CompletedProcess(
            command,
            process.returncode,
            stdout,
            stderr,
        )
        if check and process.returncode:
            raise subprocess.CalledProcessError(
                process.returncode,
                command,
                output=stdout,
                stderr=stderr,
            )
        return completed
    except BaseException:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
        raise
    finally:
        _ACTIVE_PROCESS = None


def _terminate_active_process() -> None:
    process = _ACTIVE_PROCESS
    if process is None or process.poll() is not None:
        return

    # Signal handlers run on the main thread and may interrupt Popen.wait().
    # Kill the isolated process group here, then let _run() reap the child
    # after the interrupted wait has released its internal lock.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (PermissionError, ProcessLookupError):
        try:
            process.kill()
        except ProcessLookupError:
            pass


def _wait_for_database(name: str, env: dict[str, str]) -> None:
    for attempt in range(300):
        result = _run(
            database_ping_command(name),
            env=env,
            check=False,
            quiet=True,
        )
        if result.returncode == 0:
            return
        if attempt and attempt % 30 == 0:
            print(
                f"waiting for emulated amd64 MariaDB ({attempt}s)",
                flush=True,
            )
        time.sleep(1)
    _run(["docker", "logs", name])
    raise RuntimeError("isolated MariaDB did not become ready")


def _wait_for_app(name: str) -> None:
    probe = (
        "import urllib.request; "
        "response=urllib.request.urlopen("
        "'http://127.0.0.1:5001/health', timeout=2); "
        "assert response.status == 200"
    )
    for _ in range(90):
        result = _run(
            ["docker", "exec", name, "python", "-c", probe],
            check=False,
            quiet=True,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    _run(["docker", "logs", name])
    raise RuntimeError("isolated E2E backend did not become healthy")


def _assert_amd64(container: str) -> None:
    result = _run(
        ["docker", "exec", container, "uname", "-m"],
        capture_output=True,
    )
    if result.stdout.strip() != "x86_64":
        raise RuntimeError(f"{container} is not running as x86_64")


def _assert_app_has_no_external_secrets(container: str) -> None:
    result = _run(
        [
            "docker", "inspect", "--format", "{{range .Config.Env}}{{println .}}{{end}}",
            container,
        ],
        capture_output=True,
    )
    forbidden = (
        "PROVISIONER_DATABASE_URL=",
        "TENCENTCLOUD_SECRET_ID=",
        "TENCENTCLOUD_SECRET_KEY=",
        "TENCENT_SMS_SDK_APP_ID=",
        "TENCENT_SMS_SIGN_NAME=",
        "TENCENT_SMS_TEMPLATE_ID=",
    )
    if any(item in result.stdout for item in forbidden):
        raise RuntimeError("E2E app unexpectedly contains external credentials")


def _e2e_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update({
        "E2E_DB_ROOT_PASSWORD": secrets.token_urlsafe(32),
        "E2E_TENANT_PASSWORD": secrets.token_urlsafe(32),
        "SAAS_MASTER_KEY": base64.b64encode(
            secrets.token_bytes(32)
        ).decode("ascii"),
        "SECRET_KEY": secrets.token_urlsafe(48),
        "E2E_SMS_CODE": "246810",
        "E2E_CONTROL_DATABASE": "xianyu_mobile_e2e_test_control",
        "E2E_TENANT_DATABASE": "xianyu_mobile_e2e_test_tenant",
        "E2E_TENANT_USER": "xianyu_mobile_e2e_test_user",
        "E2E_DB_HOST": "e2e-db",
        "E2E_DB_PORT": "3306",
        "PYTHONPATH": "/app",
    })
    return environment


def _container_environment_args(names: tuple[str, ...]) -> list[str]:
    args: list[str] = []
    for name in names:
        args.extend(["--env", name])
    return args


def _has_expected_label(kind: str, name: str) -> bool:
    if kind == "container":
        command = [
            "docker", "inspect", "--type", "container", "--format",
            f'{{{{index .Config.Labels "{E2E_LABEL_KEY}"}}}}', name,
        ]
    elif kind == "network":
        command = [
            "docker", "network", "inspect", "--format",
            f'{{{{index .Labels "{E2E_LABEL_KEY}"}}}}', name,
        ]
    else:
        raise ValueError("resource kind must be container or network")
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
    )
    return (
        result.returncode == 0
        and result.stdout.strip() == E2E_LABEL_VALUE
    )


def _cleanup(
    resources: ResourceNames,
    created_resources: set[str],
) -> None:
    for container in (
        resources.app_container,
        resources.database_container,
    ):
        assert_safe_resource_name(container)
        if (
            container not in created_resources
            or not _has_expected_label("container", container)
        ):
            continue
        subprocess.run(
            ["docker", "rm", "--force", container],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    assert_safe_resource_name(resources.network)
    if (
        resources.network in created_resources
        and _has_expected_label("network", resources.network)
    ):
        subprocess.run(
            ["docker", "network", "rm", resources.network],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


@contextmanager
def cleanup_on_termination(
    cleanup: Callable[[], None],
) -> Iterator[None]:
    watched_signals = (signal.SIGINT, signal.SIGTERM)
    previous_handlers = {
        signum: signal.getsignal(signum)
        for signum in watched_signals
    }

    def terminate(signum, _frame):
        _terminate_active_process()
        raise SystemExit(128 + signum)

    for signum in watched_signals:
        signal.signal(signum, terminate)
    try:
        yield
    finally:
        for signum in watched_signals:
            signal.signal(signum, previous_handlers[signum])
        cleanup()


def run() -> None:
    run_id = f"{os.getpid()}-{secrets.token_hex(3)}"
    resources = ResourceNames(run_id=run_id)
    created_resources: set[str] = set()
    environment = _e2e_environment()
    common_env_names = (
        "E2E_TENANT_PASSWORD",
        "SAAS_MASTER_KEY",
        "SECRET_KEY",
        "E2E_SMS_CODE",
        "E2E_CONTROL_DATABASE",
        "E2E_TENANT_DATABASE",
        "E2E_TENANT_USER",
        "E2E_DB_HOST",
        "E2E_DB_PORT",
        "PYTHONPATH",
    )

    with cleanup_on_termination(
        lambda: _cleanup(resources, created_resources)
    ):
        print("building application image for linux/amd64", flush=True)
        _run([
            "make", "build", f"IMAGE={APP_IMAGE}",
            f"PLATFORM={AMD64_PLATFORM}",
        ], env=environment)
        _run([
            "docker", "network", "create",
            "--label", f"{E2E_LABEL_KEY}={E2E_LABEL_VALUE}",
            resources.network,
        ])
        created_resources.add(resources.network)
        _run(
            docker_run_prefix() + [
                "--detach",
                "--name", resources.database_container,
                "--network", resources.network,
                "--network-alias", "e2e-db",
                "--label", f"{E2E_LABEL_KEY}={E2E_LABEL_VALUE}",
                "--tmpfs", "/var/lib/mysql:rw,nosuid,size=1g",
                "--env", "MARIADB_ROOT_PASSWORD",
                MARIADB_IMAGE,
            ],
            env={**environment, "MARIADB_ROOT_PASSWORD": environment["E2E_DB_ROOT_PASSWORD"]},
        )
        created_resources.add(resources.database_container)
        _wait_for_database(
            resources.database_container,
            {**environment, "MYSQL_PWD": environment["E2E_DB_ROOT_PASSWORD"]},
        )
        _assert_amd64(resources.database_container)

        runner_mount = (
            f"type=bind,source={BACKEND_RUNNER},"
            "target=/tmp/mobile_e2e_backend.py,readonly"
        )
        _run(
            docker_run_prefix() + [
                "--rm",
                "--network", resources.network,
                "--mount", runner_mount,
                *_container_environment_args(
                    common_env_names + ("E2E_DB_ROOT_PASSWORD",)
                ),
                APP_IMAGE,
                "python", "/tmp/mobile_e2e_backend.py", "prepare",
            ],
            env=environment,
        )
        _run(
            docker_run_prefix() + [
                "--detach",
                "--name", resources.app_container,
                "--network", resources.network,
                "--network-alias", "e2e-app",
                "--label", f"{E2E_LABEL_KEY}={E2E_LABEL_VALUE}",
                "--mount", runner_mount,
                *_container_environment_args(common_env_names),
                APP_IMAGE,
                "python", "/tmp/mobile_e2e_backend.py", "serve",
            ],
            env=environment,
        )
        created_resources.add(resources.app_container)
        _assert_amd64(resources.app_container)
        _assert_app_has_no_external_secrets(resources.app_container)
        _wait_for_app(resources.app_container)

        playwright_command = """
set -euo pipefail
test "$(uname -m)" = "x86_64"
cd /workspace/frontend
npm ci
cd /workspace/frontend-mobile
npm ci
npm run test:e2e 2>&1 | tee /tmp/mobile-e2e.log
grep -Eq '27 passed' /tmp/mobile-e2e.log
grep -Eq '52 passed' /tmp/mobile-e2e.log
! grep -Eq '[0-9]+ skipped' /tmp/mobile-e2e.log
""".strip()
        with tempfile.TemporaryDirectory(
            prefix=".xianyu-mobile-e2e-generated-",
            dir=PROJECT_ROOT,
        ) as scratch_directory:
            generated_mounts = writable_generated_file_mounts(
                PROJECT_ROOT,
                Path(scratch_directory),
            )
            _run(
                docker_run_prefix() + [
                    "--rm",
                    "--network", resources.network,
                    "--mount", f"type=bind,source={PROJECT_ROOT},target=/workspace,readonly",
                    *generated_mounts,
                    "--tmpfs", "/workspace/frontend/node_modules:rw,exec,size=1g",
                    "--tmpfs", "/workspace/frontend-mobile/node_modules:rw,exec,size=1g",
                    "--tmpfs", "/workspace/frontend-mobile/test-results:rw,size=512m",
                    "--env", "E2E_BACKEND_TARGET=http://e2e-app:5001",
                    "--env", "E2E_SMS_CODE=246810",
                    "--env", "E2E_OUTPUT_DIR=/tmp/playwright-results",
                    PLAYWRIGHT_IMAGE,
                    "bash", "-lc", playwright_command,
                ],
                env=environment,
            )
        print("x86 mobile E2E passed: 27 mock + 52 real-backend", flush=True)


if __name__ == "__main__":
    try:
        run()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
