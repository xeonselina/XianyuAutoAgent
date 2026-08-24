"""Fail-closed NAS pull boundary for D23 full-backup artifacts.

The boundary builds only fixed non-interactive OpenSSH argument vectors.  A
runner is injected for tests and deployments; this module never selects a
remote command, path, database, provider, or shell fragment from untrusted
input.  Cloud-drive sync and ``sync-status-ack`` remain outside this module.
"""

from __future__ import annotations

import ipaddress
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Final, Protocol
from uuid import UUID

from inventory_control.backups.acknowledgements import (
    AcknowledgementKind,
    AcknowledgementSafeResult,
    AcknowledgementSubmission,
    acknowledgement_request_digest,
)
from inventory_control.backups.domain import BackupManifest, BackupStage
from inventory_control.backups.filesystem import (
    BackupFilesystemError,
    BackupPublishResult,
    decode_manifest_json,
    publish_verified_artifact,
)


SSH_EXECUTABLE: Final = "/usr/bin/ssh"
REMOTE_WRAPPER: Final = "/usr/local/sbin/inventory-manager-backup-wrapper"
_REMOTE_MANIFEST_COMMAND: Final = "artifact-manifest"
_REMOTE_STREAM_COMMAND: Final = "artifact-stream"
_LOCK_NAME: Final = ".nas-pull.lock"
_MAX_MANIFEST_BYTES: Final = 1024 * 1024
_MAX_COMMAND_STDIN_BYTES: Final = 16 * 1024
_MAX_COMMAND_TIMEOUT_SECONDS: Final = 3600
_MAX_CONNECT_TIMEOUT_SECONDS: Final = 60
_DNS_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")
_SSH_USER = re.compile(r"[a-z_][a-z0-9_-]{0,31}", re.ASCII)
_SAFE_ABSOLUTE_PATH = re.compile(r"/[A-Za-z0-9._/-]+", re.ASCII)


class WrapperCommand(str, Enum):
    """Closed remote wrapper command set shared by pull and acknowledgements."""

    ARTIFACT_MANIFEST = _REMOTE_MANIFEST_COMMAND
    ARTIFACT_STREAM = _REMOTE_STREAM_COMMAND
    BACKUP_STATUS_ACK = "backup-status-ack"
    SYNC_STATUS_ACK = "sync-status-ack"


class NasPullError(RuntimeError):
    """Stable failure that never includes a host, path, or command output."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True, repr=False)
class NasPullSshConfig:
    """Validated SSH inputs; repr deliberately withholds endpoint and paths."""

    host: str = field(repr=False)
    user: str = field(repr=False)
    port: int
    identity_file: Path = field(repr=False)
    pinned_host_key_file: Path = field(repr=False)
    connect_timeout_seconds: int = 15

    def __post_init__(self) -> None:
        object.__setattr__(self, "host", _host(self.host))
        if not isinstance(self.user, str) or _SSH_USER.fullmatch(self.user) is None:
            _fail("NAS_PULL_SSH_CONFIG_INVALID")
        if (
            not isinstance(self.port, int)
            or isinstance(self.port, bool)
            or self.port < 1
            or self.port > 65535
        ):
            _fail("NAS_PULL_SSH_CONFIG_INVALID")
        identity = _credential_file(self.identity_file, private=True)
        pinned = _credential_file(self.pinned_host_key_file, private=False)
        object.__setattr__(self, "identity_file", identity)
        object.__setattr__(self, "pinned_host_key_file", pinned)
        if (
            not isinstance(self.connect_timeout_seconds, int)
            or isinstance(self.connect_timeout_seconds, bool)
            or self.connect_timeout_seconds < 1
            or self.connect_timeout_seconds > _MAX_CONNECT_TIMEOUT_SECONDS
        ):
            _fail("NAS_PULL_SSH_CONFIG_INVALID")

    def __repr__(self) -> str:
        return (
            "NasPullSshConfig(endpoint='<redacted>', credentials='<redacted>', "
            f"port_set={self.port > 0}, connect_timeout_seconds="
            f"{self.connect_timeout_seconds})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class CommandInvocation:
    """Structured runner request with no shell execution surface."""

    operation: str
    argv: tuple[str, ...] = field(repr=False)
    timeout_seconds: int
    stdout_fd: int | None = field(default=None, repr=False)
    max_stdout_bytes: int = 0
    stdin_bytes: bytes = field(default=b"", repr=False)

    def __post_init__(self) -> None:
        if self.operation not in {"manifest", "artifact", "ack"}:
            _fail("NAS_PULL_COMMAND_INVALID")
        if (
            not isinstance(self.argv, tuple)
            or not self.argv
            or self.argv[0] != SSH_EXECUTABLE
            or any(
                not isinstance(argument, str)
                or not argument
                or "\x00" in argument
                or "\n" in argument
                or "\r" in argument
                for argument in self.argv
            )
        ):
            _fail("NAS_PULL_COMMAND_INVALID")
        if (
            not isinstance(self.timeout_seconds, int)
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds < 1
            or self.timeout_seconds > _MAX_COMMAND_TIMEOUT_SECONDS
        ):
            _fail("NAS_PULL_COMMAND_INVALID")
        if self.stdout_fd is not None and (
            not isinstance(self.stdout_fd, int)
            or isinstance(self.stdout_fd, bool)
            or self.stdout_fd < 0
        ):
            _fail("NAS_PULL_COMMAND_INVALID")
        if (
            not isinstance(self.stdin_bytes, bytes)
            or len(self.stdin_bytes) > _MAX_COMMAND_STDIN_BYTES
        ):
            _fail("NAS_PULL_COMMAND_INVALID")
        if self.operation in {"manifest", "ack"}:
            if self.stdout_fd is not None or not (
                1 <= self.max_stdout_bytes <= _MAX_MANIFEST_BYTES
            ):
                _fail("NAS_PULL_COMMAND_INVALID")
            if self.operation == "manifest" and self.stdin_bytes:
                _fail("NAS_PULL_COMMAND_INVALID")
            if self.operation == "ack" and not self.stdin_bytes:
                _fail("NAS_PULL_COMMAND_INVALID")
        elif (
            self.stdout_fd is None
            or self.max_stdout_bytes != 0
            or self.stdin_bytes
        ):
            _fail("NAS_PULL_COMMAND_INVALID")

    def __repr__(self) -> str:
        return (
            "CommandInvocation("
            f"operation={self.operation!r}, argv='<redacted>', "
            f"timeout_seconds={self.timeout_seconds}, "
            f"streams_to_file={self.stdout_fd is not None}, "
            f"has_stdin={bool(self.stdin_bytes)})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class CommandResult:
    returncode: int | None
    stdout: bytes = field(default=b"", repr=False)
    timed_out: bool = False

    def __post_init__(self) -> None:
        if self.returncode is not None and (
            not isinstance(self.returncode, int)
            or isinstance(self.returncode, bool)
            or self.returncode < 0
            or self.returncode > 255
        ):
            _fail("NAS_PULL_RUNNER_RESULT_INVALID")
        if not isinstance(self.stdout, bytes):
            _fail("NAS_PULL_RUNNER_RESULT_INVALID")
        if not isinstance(self.timed_out, bool):
            _fail("NAS_PULL_RUNNER_RESULT_INVALID")
        if self.timed_out and self.returncode is not None:
            _fail("NAS_PULL_RUNNER_RESULT_INVALID")
        if not self.timed_out and self.returncode is None:
            _fail("NAS_PULL_RUNNER_RESULT_INVALID")

    def __repr__(self) -> str:
        return (
            "CommandResult("
            f"returncode={self.returncode!r}, stdout='<redacted>', "
            f"timed_out={self.timed_out})"
        )


class CommandRunner(Protocol):
    def run(self, invocation: CommandInvocation) -> CommandResult:
        """Run exactly one structured invocation without a shell."""


class SubprocessCommandRunner:
    """Minimal production runner; callers still supply all deployment facts."""

    def run(self, invocation: CommandInvocation) -> CommandResult:
        if not isinstance(invocation, CommandInvocation):
            _fail("NAS_PULL_COMMAND_INVALID")
        captured = None
        stdout_target: int | object
        if invocation.stdout_fd is None:
            captured = tempfile.SpooledTemporaryFile(
                max_size=invocation.max_stdout_bytes + 1,
            )
            stdout_target = captured
        else:
            stdout_target = invocation.stdout_fd
        run_options = {
            "stdout": stdout_target,
            "stderr": subprocess.DEVNULL,
            "timeout": invocation.timeout_seconds,
            "check": False,
            "shell": False,
            "close_fds": True,
            "env": {"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        }
        if invocation.stdin_bytes:
            run_options["input"] = invocation.stdin_bytes
        else:
            run_options["stdin"] = subprocess.DEVNULL
        try:
            completed = subprocess.run(
                list(invocation.argv),
                **run_options,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(returncode=None, timed_out=True)
        except (OSError, ValueError):
            _fail("NAS_PULL_COMMAND_EXECUTION_FAILED")
        finally:
            if captured is not None and "completed" not in locals():
                captured.close()
        stdout = b""
        if captured is not None:
            try:
                captured.seek(0, os.SEEK_END)
                size = captured.tell()
                if size > invocation.max_stdout_bytes:
                    _fail("NAS_PULL_STDOUT_PROTOCOL_INVALID")
                captured.seek(0)
                stdout = captured.read()
            finally:
                captured.close()
        return CommandResult(
            returncode=completed.returncode,
            stdout=stdout,
            timed_out=False,
        )


@dataclass(frozen=True, slots=True, repr=False)
class NasPullResult:
    publication: BackupPublishResult = field(repr=False)
    backup_status_ack: AcknowledgementSubmission = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.publication, BackupPublishResult)
            or not isinstance(self.backup_status_ack, AcknowledgementSubmission)
            or self.backup_status_ack.kind
            is not AcknowledgementKind.BACKUP_STATUS
            or self.backup_status_ack.artifact_id
            != self.publication.observation.artifact_id
        ):
            _fail("NAS_PULL_RESULT_INVALID")

    def __repr__(self) -> str:
        return (
            "NasPullResult("
            f"artifact_id={str(self.backup_status_ack.artifact_id)!r}, "
            "paths='<redacted>', ack_kind='backup-status-ack')"
        )


@dataclass(frozen=True, slots=True, repr=False)
class _OwnedPartial:
    path: Path = field(repr=False)
    descriptor: int = field(repr=False)
    device: int
    inode: int


Clock = Callable[[], datetime]


class NasPullService:
    """Pull one known artifact through the fixed wrapper and publish it."""

    __slots__ = ("_clock", "_config", "_runner")

    def __init__(
        self,
        *,
        config: NasPullSshConfig,
        runner: CommandRunner,
        clock: Clock,
    ) -> None:
        if not isinstance(config, NasPullSshConfig):
            _fail("NAS_PULL_CONFIG_INVALID")
        if not callable(getattr(runner, "run", None)) or not callable(clock):
            _fail("NAS_PULL_CONFIG_INVALID")
        self._config = config
        self._runner = runner
        self._clock = clock

    def pull(
        self,
        *,
        root: str | os.PathLike[str],
        artifact_id: UUID,
        source_generation: int,
        command_timeout_seconds: int = 1200,
    ) -> NasPullResult:
        selected_artifact = _artifact_id(artifact_id)
        selected_generation = _source_generation(source_generation)
        timeout = _command_timeout(command_timeout_seconds)
        canonical_root = _restricted_root(root)
        _validate_config_files(self._config)
        expected_name = f"backup-{selected_artifact}.sql.gz"
        partial_path = canonical_root / f"{expected_name}.partial"
        published_path = canonical_root / expected_name
        _reject_existing_target(partial_path, partial=True)
        _reject_existing_target(published_path, partial=False)

        lock = _acquire_overlap_lock(canonical_root)
        try:
            manifest = self._fetch_manifest(
                artifact_id=selected_artifact,
                timeout_seconds=timeout,
            )
            if (
                manifest.artifact_id != selected_artifact
                or manifest.published_name != expected_name
            ):
                _fail("NAS_PULL_MANIFEST_IDENTITY_MISMATCH")
            _reject_existing_target(partial_path, partial=True)
            _reject_existing_target(published_path, partial=False)
            owned_partial: _OwnedPartial | None = None
            try:
                owned_partial = _create_partial(partial_path)
                try:
                    self._stream_artifact(
                        artifact_id=selected_artifact,
                        owned_partial=owned_partial,
                        timeout_seconds=timeout,
                    )
                finally:
                    _close_partial(owned_partial)
                now = _utc(self._clock())
                try:
                    publication = publish_verified_artifact(
                        root=canonical_root,
                        partial_artifact_path=partial_path,
                        manifest=manifest,
                        upstream_successful_stages=frozenset(
                            {
                                BackupStage.DUMP,
                                BackupStage.COMPRESSION,
                                BackupStage.TRANSFER,
                            }
                        ),
                        database_now_utc=now,
                    )
                except BackupFilesystemError as exc:
                    _fail(exc.code)
                ack = _backup_status_ack(
                    manifest=manifest,
                    source_generation=selected_generation,
                    reported_at_utc=_utc(self._clock()),
                )
                return NasPullResult(
                    publication=publication,
                    backup_status_ack=ack,
                )
            except Exception:
                if owned_partial is not None:
                    _remove_owned_partial(canonical_root, owned_partial)
                raise
        finally:
            _release_overlap_lock(canonical_root, lock)

    def _fetch_manifest(
        self,
        *,
        artifact_id: UUID,
        timeout_seconds: int,
    ) -> BackupManifest:
        invocation = CommandInvocation(
            operation="manifest",
            argv=fixed_wrapper_ssh_argv(
                self._config,
                command=WrapperCommand.ARTIFACT_MANIFEST,
                artifact_id=artifact_id,
            ),
            timeout_seconds=timeout_seconds,
            max_stdout_bytes=_MAX_MANIFEST_BYTES,
        )
        result = _run(self._runner, invocation)
        if len(result.stdout) > _MAX_MANIFEST_BYTES or not result.stdout:
            _fail("NAS_PULL_STDOUT_PROTOCOL_INVALID")
        try:
            return decode_manifest_json(result.stdout)
        except BackupFilesystemError as exc:
            _fail(exc.code)

    def _stream_artifact(
        self,
        *,
        artifact_id: UUID,
        owned_partial: _OwnedPartial,
        timeout_seconds: int,
    ) -> None:
        invocation = CommandInvocation(
            operation="artifact",
            argv=fixed_wrapper_ssh_argv(
                self._config,
                command=WrapperCommand.ARTIFACT_STREAM,
                artifact_id=artifact_id,
            ),
            timeout_seconds=timeout_seconds,
            stdout_fd=owned_partial.descriptor,
            max_stdout_bytes=0,
        )
        result = _run(self._runner, invocation)
        if result.stdout:
            _fail("NAS_PULL_STDOUT_PROTOCOL_INVALID")
        try:
            os.fsync(owned_partial.descriptor)
        except OSError:
            _fail("NAS_PULL_PARTIAL_FSYNC_FAILED")
        _verify_open_partial(owned_partial)


def _run(runner: CommandRunner, invocation: CommandInvocation) -> CommandResult:
    try:
        result = runner.run(invocation)
    except NasPullError:
        raise
    except Exception:
        _fail("NAS_PULL_COMMAND_EXECUTION_FAILED")
    if not isinstance(result, CommandResult):
        _fail("NAS_PULL_RUNNER_RESULT_INVALID")
    if result.timed_out:
        _fail("NAS_PULL_COMMAND_TIMEOUT")
    if result.returncode != 0:
        _fail("NAS_PULL_COMMAND_FAILED")
    return result


def fixed_wrapper_ssh_argv(
    config: NasPullSshConfig,
    *,
    command: WrapperCommand,
    artifact_id: UUID | None = None,
) -> tuple[str, ...]:
    if not isinstance(command, WrapperCommand):
        _fail("NAS_PULL_COMMAND_INVALID")
    artifact_commands = {
        WrapperCommand.ARTIFACT_MANIFEST,
        WrapperCommand.ARTIFACT_STREAM,
    }
    if command in artifact_commands:
        selected_artifact = _artifact_id(artifact_id)
        remote_arguments = (str(selected_artifact),)
    elif artifact_id is not None:
        _fail("NAS_PULL_COMMAND_INVALID")
    else:
        remote_arguments = ()
    _validate_config_files(config)
    target = f"{config.user}@{config.host}"
    return (
        SSH_EXECUTABLE,
        "-F",
        "/dev/null",
        "-T",
        "-p",
        str(config.port),
        "-i",
        str(config.identity_file),
        "-o",
        "BatchMode=yes",
        "-o",
        "RequestTTY=no",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "KbdInteractiveAuthentication=no",
        "-o",
        "PreferredAuthentications=publickey",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={config.pinned_host_key_file}",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        f"HostName={config.host}",
        "-o",
        "CanonicalizeHostname=no",
        "-o",
        "ProxyCommand=none",
        "-o",
        "ProxyJump=none",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPath=none",
        "-o",
        f"ConnectTimeout={config.connect_timeout_seconds}",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "LogLevel=ERROR",
        "-o",
        "PermitLocalCommand=no",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "ForwardAgent=no",
        "-o",
        "ForwardX11=no",
        "-o",
        "UpdateHostKeys=no",
        "-o",
        "VerifyHostKeyDNS=no",
        target,
        REMOTE_WRAPPER,
        command.value,
        *remote_arguments,
    )


def _backup_status_ack(
    *,
    manifest: BackupManifest,
    source_generation: int,
    reported_at_utc: datetime,
) -> AcknowledgementSubmission:
    key = f"nas-pull:{manifest.artifact_id}:{source_generation}"
    digest = acknowledgement_request_digest(
        kind=AcknowledgementKind.BACKUP_STATUS,
        artifact_id=manifest.artifact_id,
        manifest_sha256=manifest.manifest_sha256,
        artifact_sha256=manifest.artifact_sha256,
        source_generation=source_generation,
        idempotency_key=key,
        safe_result=AcknowledgementSafeResult.VERIFIED,
        reported_at_utc=reported_at_utc,
    )
    return AcknowledgementSubmission(
        kind=AcknowledgementKind.BACKUP_STATUS,
        artifact_id=manifest.artifact_id,
        manifest_sha256=manifest.manifest_sha256,
        artifact_sha256=manifest.artifact_sha256,
        source_generation=source_generation,
        idempotency_key=key,
        request_digest=digest,
        safe_result=AcknowledgementSafeResult.VERIFIED,
        reported_at_utc=reported_at_utc,
    )


def _restricted_root(root: str | os.PathLike[str]) -> Path:
    try:
        selected = Path(root)
    except TypeError:
        _fail("NAS_PULL_ROOT_INVALID")
    if not selected.is_absolute():
        _fail("NAS_PULL_ROOT_INVALID")
    for component in _path_components(selected):
        try:
            state = os.lstat(component)
        except OSError:
            _fail("NAS_PULL_ROOT_INVALID")
        if stat.S_ISLNK(state.st_mode):
            _fail("NAS_PULL_ROOT_INVALID")
    try:
        state = os.lstat(selected)
    except OSError:
        _fail("NAS_PULL_ROOT_INVALID")
    if (
        not stat.S_ISDIR(state.st_mode)
        or state.st_uid != os.geteuid()
        or state.st_mode & 0o077
    ):
        _fail("NAS_PULL_ROOT_INVALID")
    return selected


def _credential_file(value: object, *, private: bool) -> Path:
    try:
        selected = Path(value)
    except TypeError:
        _fail("NAS_PULL_SSH_CONFIG_INVALID")
    if (
        not selected.is_absolute()
        or _SAFE_ABSOLUTE_PATH.fullmatch(str(selected)) is None
        or ".." in selected.parts
    ):
        _fail("NAS_PULL_SSH_CONFIG_INVALID")
    for component in _path_components(selected):
        try:
            state = os.lstat(component)
        except OSError:
            _fail("NAS_PULL_SSH_CONFIG_INVALID")
        if stat.S_ISLNK(state.st_mode):
            _fail("NAS_PULL_SSH_CONFIG_INVALID")
    state = os.lstat(selected)
    forbidden_mode = 0o077 if private else 0o022
    if (
        not stat.S_ISREG(state.st_mode)
        or state.st_uid != os.geteuid()
        or state.st_size <= 0
        or state.st_size > 64 * 1024
        or state.st_mode & forbidden_mode
    ):
        _fail("NAS_PULL_SSH_CONFIG_INVALID")
    return selected


def _validate_config_files(config: NasPullSshConfig) -> None:
    if (
        _credential_file(config.identity_file, private=True)
        != config.identity_file
        or _credential_file(config.pinned_host_key_file, private=False)
        != config.pinned_host_key_file
    ):
        _fail("NAS_PULL_SSH_CONFIG_INVALID")


def _host(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 253:
        _fail("NAS_PULL_SSH_CONFIG_INVALID")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        labels = value.rstrip(".").split(".")
        if not labels or any(_DNS_LABEL.fullmatch(label) is None for label in labels):
            _fail("NAS_PULL_SSH_CONFIG_INVALID")
        return ".".join(labels).lower()


def _artifact_id(value: object) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        _fail("NAS_PULL_ARTIFACT_ID_INVALID")
    return value


def _source_generation(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        _fail("NAS_PULL_SOURCE_GENERATION_INVALID")
    return value


def _command_timeout(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > _MAX_COMMAND_TIMEOUT_SECONDS
    ):
        _fail("NAS_PULL_TIMEOUT_INVALID")
    return value


def _reject_existing_target(path: Path, *, partial: bool) -> None:
    state = _lstat_optional(path)
    if state is None:
        return
    if stat.S_ISLNK(state.st_mode):
        _fail("NAS_PULL_EXISTING_SYMLINK_REJECTED")
    if not stat.S_ISREG(state.st_mode):
        _fail("NAS_PULL_EXISTING_NONREGULAR_REJECTED")
    _fail(
        "NAS_PULL_PARTIAL_ALREADY_EXISTS"
        if partial
        else "NAS_PULL_COMPLETED_ALREADY_EXISTS"
    )


def _create_partial(path: Path) -> _OwnedPartial:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        _fail("NAS_PULL_PARTIAL_ALREADY_EXISTS")
    except OSError:
        _fail("NAS_PULL_PARTIAL_CREATE_FAILED")
    try:
        state = os.fstat(descriptor)
        if not stat.S_ISREG(state.st_mode):
            _fail("NAS_PULL_PARTIAL_CREATE_FAILED")
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    return _OwnedPartial(
        path=path,
        descriptor=descriptor,
        device=state.st_dev,
        inode=state.st_ino,
    )


def _close_partial(owned: _OwnedPartial) -> None:
    try:
        os.close(owned.descriptor)
    except OSError:
        pass


def _verify_open_partial(owned: _OwnedPartial) -> None:
    try:
        opened = os.fstat(owned.descriptor)
        linked = os.lstat(owned.path)
    except OSError:
        _fail("NAS_PULL_PARTIAL_IDENTITY_CHANGED")
    if (
        not stat.S_ISREG(opened.st_mode)
        or stat.S_ISLNK(linked.st_mode)
        or not stat.S_ISREG(linked.st_mode)
        or opened.st_dev != owned.device
        or opened.st_ino != owned.inode
        or linked.st_dev != owned.device
        or linked.st_ino != owned.inode
    ):
        _fail("NAS_PULL_PARTIAL_IDENTITY_CHANGED")


def _remove_owned_partial(root: Path, owned: _OwnedPartial) -> None:
    try:
        linked = os.lstat(owned.path)
    except FileNotFoundError:
        _fsync_directory(root)
        return
    except OSError:
        _fail("NAS_PULL_PARTIAL_CLEANUP_FAILED")
    if (
        stat.S_ISLNK(linked.st_mode)
        or not stat.S_ISREG(linked.st_mode)
        or linked.st_dev != owned.device
        or linked.st_ino != owned.inode
    ):
        _fail("NAS_PULL_PARTIAL_CLEANUP_OWNERSHIP_CHANGED")
    try:
        os.unlink(owned.path)
    except OSError:
        _fail("NAS_PULL_PARTIAL_CLEANUP_FAILED")
    _fsync_directory(root)


def _acquire_overlap_lock(root: Path) -> tuple[int, int, int]:
    path = root / _LOCK_NAME
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        _fail("NAS_PULL_OVERLAP")
    except OSError:
        _fail("NAS_PULL_LOCK_FAILED")
    try:
        state = os.fstat(descriptor)
        if not stat.S_ISREG(state.st_mode):
            _fail("NAS_PULL_LOCK_FAILED")
        if os.write(descriptor, b"active\n") != len(b"active\n"):
            _fail("NAS_PULL_LOCK_FAILED")
        os.fsync(descriptor)
        _fsync_directory(root)
        return descriptor, state.st_dev, state.st_ino
    except Exception:
        try:
            linked = os.lstat(path)
            opened = os.fstat(descriptor)
            if (
                stat.S_ISREG(linked.st_mode)
                and linked.st_dev == opened.st_dev
                and linked.st_ino == opened.st_ino
            ):
                os.unlink(path)
        except OSError:
            pass
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _release_overlap_lock(root: Path, lock: tuple[int, int, int]) -> None:
    descriptor, device, inode = lock
    path = root / _LOCK_NAME
    failed = False
    try:
        linked = os.lstat(path)
        opened = os.fstat(descriptor)
        if (
            stat.S_ISLNK(linked.st_mode)
            or not stat.S_ISREG(linked.st_mode)
            or linked.st_dev != device
            or linked.st_ino != inode
            or opened.st_dev != device
            or opened.st_ino != inode
        ):
            failed = True
        else:
            os.unlink(path)
            _fsync_directory(root)
    except OSError:
        failed = True
    finally:
        try:
            os.close(descriptor)
        except OSError:
            failed = True
    if failed:
        _fail("NAS_PULL_LOCK_RELEASE_FAILED")


def _fsync_directory(root: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(
        os, "O_DIRECTORY", 0
    )
    try:
        descriptor = os.open(root, flags)
    except OSError:
        _fail("NAS_PULL_DIRECTORY_FSYNC_FAILED")
    try:
        os.fsync(descriptor)
    except OSError:
        _fail("NAS_PULL_DIRECTORY_FSYNC_FAILED")
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _lstat_optional(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        _fail("NAS_PULL_FILESYSTEM_METADATA_FAILED")


def _path_components(path: Path) -> tuple[Path, ...]:
    components = []
    current = path
    while True:
        components.append(current)
        if current == current.parent:
            break
        current = current.parent
    return tuple(reversed(components))


def _utc(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        _fail("NAS_PULL_CLOCK_INVALID")
    return value.astimezone(timezone.utc)


def _fail(code: str):
    raise NasPullError(code)


__all__ = [
    "CommandInvocation",
    "CommandResult",
    "CommandRunner",
    "NasPullError",
    "NasPullResult",
    "NasPullService",
    "NasPullSshConfig",
    "REMOTE_WRAPPER",
    "SSH_EXECUTABLE",
    "SubprocessCommandRunner",
    "WrapperCommand",
    "fixed_wrapper_ssh_argv",
]
