from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

import inventory_control.backups.nas_pull as nas_pull
from inventory_control.backups.acknowledgements import (
    AcknowledgementKind,
    AcknowledgementSafeResult,
    acknowledgement_request_digest,
)
from inventory_control.backups.domain import (
    BackupManifest,
    DatabaseKind,
    DatabaseSnapshot,
    RecoveryMarkerSnapshot,
)
from inventory_control.backups.filesystem import encode_manifest_json
from inventory_control.backups.nas_pull import (
    CommandInvocation,
    CommandResult,
    NasPullError,
    NasPullService,
    NasPullSshConfig,
    REMOTE_WRAPPER,
    SSH_EXECUTABLE,
    SubprocessCommandRunner,
)


UTC = timezone.utc
BASE = datetime(2026, 8, 22, 8, 0, 0, 123456, tzinfo=UTC)


def _id(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"inventory-manager-nas-pull/{label}")


def _digest(value: bytes | str) -> bytes:
    if isinstance(value, str):
        value = value.encode("ascii")
    return hashlib.sha256(value).digest()


def _manifest(label: str, content: bytes) -> BackupManifest:
    artifact_id = _id(f"artifact/{label}")
    databases = (
        DatabaseSnapshot(
            database_id=_id("control"),
            kind=DatabaseKind.CONTROL,
            schema_generation=23,
            schema_sha256=_digest("control-schema"),
            required_root_key_versions=(3,),
        ),
        DatabaseSnapshot(
            database_id=_id("tenant"),
            kind=DatabaseKind.TENANT,
            schema_generation=11,
            schema_sha256=_digest("tenant-schema"),
            required_root_key_versions=(3, 7),
        ),
    )
    return BackupManifest(
        artifact_id=artifact_id,
        attempt_id=_id(f"attempt/{label}"),
        published_name=f"backup-{artifact_id}.sql.gz",
        snapshot_at_utc=BASE + timedelta(minutes=1),
        completed_at_utc=BASE + timedelta(minutes=2),
        artifact_sha256=_digest(content),
        size_bytes=len(content),
        databases=databases,
        root_key_versions=(7, 3),
        recovery_marker=RecoveryMarkerSnapshot(
            installation_id=_id("installation"),
            recovery_run_id=_id("recovery-run"),
            marker_generation=9,
            marker_sha256=_digest("recovery-marker"),
        ),
    )


def _secure_root(tmp_path: Path, label: str = "backups") -> Path:
    root = tmp_path / label
    root.mkdir()
    root.chmod(0o700)
    return root


def _config(tmp_path: Path) -> NasPullSshConfig:
    identity = tmp_path / "nas_pull_identity"
    identity.write_bytes(b"test-private-key-material")
    identity.chmod(0o600)
    pinned = tmp_path / "known_hosts_pinned"
    pinned.write_bytes(b"nas.internal ssh-ed25519 test-pinned-key")
    pinned.chmod(0o600)
    return NasPullSshConfig(
        host="nas-source.internal",
        user="backup_pull",
        port=22022,
        identity_file=identity,
        pinned_host_key_file=pinned,
        connect_timeout_seconds=12,
    )


class FakeRunner:
    def __init__(
        self,
        *,
        manifest_bytes: bytes,
        artifact_bytes: bytes,
        manifest_result: CommandResult | None = None,
        artifact_result: CommandResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.manifest_bytes = manifest_bytes
        self.artifact_bytes = artifact_bytes
        self.manifest_result = manifest_result
        self.artifact_result = artifact_result
        self.error = error
        self.invocations: list[CommandInvocation] = []

    def run(self, invocation: CommandInvocation) -> CommandResult:
        self.invocations.append(invocation)
        if self.error is not None:
            raise self.error
        if invocation.operation == "manifest":
            if self.manifest_result is not None:
                return self.manifest_result
            return CommandResult(returncode=0, stdout=self.manifest_bytes)
        assert invocation.stdout_fd is not None
        os.write(invocation.stdout_fd, self.artifact_bytes)
        if self.artifact_result is not None:
            return self.artifact_result
        return CommandResult(returncode=0)


def _service(
    tmp_path: Path,
    runner: FakeRunner,
    *,
    clock_value: datetime = BASE + timedelta(minutes=3),
) -> NasPullService:
    return NasPullService(
        config=_config(tmp_path),
        runner=runner,
        clock=lambda: clock_value,
    )


def _assert_code(code: str, call) -> NasPullError:
    with pytest.raises(NasPullError) as exc_info:
        call()
    assert exc_info.value.code == code
    assert str(exc_info.value) == code
    return exc_info.value


def test_pull_uses_fixed_noninteractive_argv_publishes_then_builds_backup_ack(
    tmp_path: Path,
):
    content = b"consistent-compressed-full-dump" * 100
    manifest = _manifest("success", content)
    runner = FakeRunner(
        manifest_bytes=encode_manifest_json(manifest),
        artifact_bytes=content,
    )
    root = _secure_root(tmp_path)
    reported_at = BASE + timedelta(minutes=3)

    result = _service(tmp_path, runner, clock_value=reported_at).pull(
        root=root,
        artifact_id=manifest.artifact_id,
        source_generation=17,
        command_timeout_seconds=300,
    )

    assert result.publication.artifact_path.read_bytes() == content
    assert result.publication.manifest_path.read_bytes() == encode_manifest_json(
        manifest
    )
    assert not (root / f"{manifest.published_name}.partial").exists()
    assert not (root / ".nas-pull.lock").exists()
    acknowledgement = result.backup_status_ack
    assert acknowledgement.kind is AcknowledgementKind.BACKUP_STATUS
    assert acknowledgement.safe_result is AcknowledgementSafeResult.VERIFIED
    assert acknowledgement.artifact_id == manifest.artifact_id
    assert acknowledgement.manifest_sha256 == manifest.manifest_sha256
    assert acknowledgement.artifact_sha256 == manifest.artifact_sha256
    assert acknowledgement.source_generation == 17
    assert acknowledgement.idempotency_key == (
        f"nas-pull:{manifest.artifact_id}:17"
    )
    assert acknowledgement.reported_at_utc == reported_at
    assert acknowledgement.request_digest == acknowledgement_request_digest(
        kind=AcknowledgementKind.BACKUP_STATUS,
        artifact_id=manifest.artifact_id,
        manifest_sha256=manifest.manifest_sha256,
        artifact_sha256=manifest.artifact_sha256,
        source_generation=17,
        idempotency_key=acknowledgement.idempotency_key,
        safe_result=AcknowledgementSafeResult.VERIFIED,
        reported_at_utc=reported_at,
    )
    assert "sync-status-ack" not in repr(result)

    assert [call.operation for call in runner.invocations] == [
        "manifest",
        "artifact",
    ]
    for call, subcommand in zip(
        runner.invocations,
        ("artifact-manifest", "artifact-stream"),
        strict=True,
    ):
        assert call.argv[0] == SSH_EXECUTABLE
        assert call.argv[1:3] == ("-F", "/dev/null")
        assert call.argv[-3:] == (
            REMOTE_WRAPPER,
            subcommand,
            str(manifest.artifact_id),
        )
        assert call.argv[-4] == "backup_pull@nas-source.internal"
        assert "BatchMode=yes" in call.argv
        assert "RequestTTY=no" in call.argv
        assert "PasswordAuthentication=no" in call.argv
        assert "KbdInteractiveAuthentication=no" in call.argv
        assert "StrictHostKeyChecking=yes" in call.argv
        assert "ClearAllForwardings=yes" in call.argv
        assert "ProxyCommand=none" in call.argv
        assert "ProxyJump=none" in call.argv
        assert "ControlMaster=no" in call.argv
        assert "ControlPath=none" in call.argv
        assert "ForwardAgent=no" in call.argv
        assert "ForwardX11=no" in call.argv
        assert all(
            not any(character in argument for character in ";|&$`\n\r")
            for argument in call.argv[-4:]
        )
        assert not hasattr(call, "shell")


def test_subprocess_runner_passes_argv_with_shell_disabled(monkeypatch):
    recorded: dict[str, object] = {}

    class Completed:
        returncode = 0

    def fake_run(argv, **kwargs):
        recorded["argv"] = argv
        recorded.update(kwargs)
        kwargs["stdout"].write(b"canonical-manifest")
        return Completed()

    monkeypatch.setattr(nas_pull.subprocess, "run", fake_run)
    invocation = CommandInvocation(
        operation="manifest",
        argv=(SSH_EXECUTABLE, "fixed-argument"),
        timeout_seconds=5,
        max_stdout_bytes=1024,
    )

    result = SubprocessCommandRunner().run(invocation)

    assert result == CommandResult(returncode=0, stdout=b"canonical-manifest")
    assert recorded["argv"] == [SSH_EXECUTABLE, "fixed-argument"]
    assert recorded["shell"] is False
    assert recorded["stdin"] is subprocess.DEVNULL
    assert recorded["stderr"] is subprocess.DEVNULL
    assert recorded["check"] is False


@pytest.mark.parametrize(
    ("target", "kind", "expected"),
    [
        ("partial", "regular", "NAS_PULL_PARTIAL_ALREADY_EXISTS"),
        ("completed", "regular", "NAS_PULL_COMPLETED_ALREADY_EXISTS"),
        ("partial", "symlink", "NAS_PULL_EXISTING_SYMLINK_REJECTED"),
        ("completed", "directory", "NAS_PULL_EXISTING_NONREGULAR_REJECTED"),
    ],
)
def test_existing_targets_fail_before_any_remote_call(
    tmp_path: Path,
    target: str,
    kind: str,
    expected: str,
):
    content = b"target-preflight-content"
    manifest = _manifest(f"preflight-{target}-{kind}", content)
    runner = FakeRunner(
        manifest_bytes=encode_manifest_json(manifest),
        artifact_bytes=content,
    )
    root = _secure_root(tmp_path)
    suffix = ".partial" if target == "partial" else ""
    selected = root / f"{manifest.published_name}{suffix}"
    if kind == "regular":
        selected.write_bytes(b"must-remain")
    elif kind == "symlink":
        outside = tmp_path / "outside"
        outside.write_bytes(b"outside-must-remain")
        selected.symlink_to(outside)
    else:
        selected.mkdir()

    _assert_code(
        expected,
        lambda: _service(tmp_path, runner).pull(
            root=root,
            artifact_id=manifest.artifact_id,
            source_generation=1,
        ),
    )

    assert runner.invocations == []
    assert not (root / ".nas-pull.lock").exists()


def test_existing_overlap_lock_is_preserved_and_rejects_without_remote_call(
    tmp_path: Path,
):
    content = b"overlap-content"
    manifest = _manifest("overlap", content)
    runner = FakeRunner(
        manifest_bytes=encode_manifest_json(manifest),
        artifact_bytes=content,
    )
    root = _secure_root(tmp_path)
    lock = root / ".nas-pull.lock"
    lock.write_bytes(b"other-owner")

    _assert_code(
        "NAS_PULL_OVERLAP",
        lambda: _service(tmp_path, runner).pull(
            root=root,
            artifact_id=manifest.artifact_id,
            source_generation=1,
        ),
    )

    assert lock.read_bytes() == b"other-owner"
    assert runner.invocations == []


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (CommandResult(returncode=None, timed_out=True), "NAS_PULL_COMMAND_TIMEOUT"),
        (CommandResult(returncode=23), "NAS_PULL_COMMAND_FAILED"),
        (
            CommandResult(returncode=0, stdout=b"unexpected-protocol-output"),
            "NAS_PULL_STDOUT_PROTOCOL_INVALID",
        ),
    ],
)
def test_stream_failure_removes_owned_partial_and_owned_lock(
    tmp_path: Path,
    result: CommandResult,
    expected: str,
):
    content = b"stream-failure-content"
    manifest = _manifest(f"stream-{expected}", content)
    runner = FakeRunner(
        manifest_bytes=encode_manifest_json(manifest),
        artifact_bytes=content[:8],
        artifact_result=result,
    )
    root = _secure_root(tmp_path)

    error = _assert_code(
        expected,
        lambda: _service(tmp_path, runner).pull(
            root=root,
            artifact_id=manifest.artifact_id,
            source_generation=2,
        ),
    )

    partial = root / f"{manifest.published_name}.partial"
    assert not partial.exists()
    assert not (root / manifest.published_name).exists()
    assert not (root / ".nas-pull.lock").exists()
    assert str(root) not in str(error)


@pytest.mark.parametrize(
    ("manifest_bytes", "expected"),
    [
        (b"not-json", "INVALID_MANIFEST_JSON"),
        (b"", "NAS_PULL_STDOUT_PROTOCOL_INVALID"),
    ],
)
def test_manifest_protocol_failure_creates_no_partial_and_releases_lock(
    tmp_path: Path,
    manifest_bytes: bytes,
    expected: str,
):
    content = b"manifest-failure-content"
    manifest = _manifest(f"manifest-{expected}", content)
    runner = FakeRunner(
        manifest_bytes=manifest_bytes,
        artifact_bytes=content,
    )
    root = _secure_root(tmp_path)

    _assert_code(
        expected,
        lambda: _service(tmp_path, runner).pull(
            root=root,
            artifact_id=manifest.artifact_id,
            source_generation=1,
        ),
    )

    assert [call.operation for call in runner.invocations] == ["manifest"]
    assert not (root / f"{manifest.published_name}.partial").exists()
    assert not (root / ".nas-pull.lock").exists()


def test_manifest_identity_mismatch_fails_before_artifact_stream(tmp_path: Path):
    content = b"identity-mismatch-content"
    requested = _manifest("requested", content)
    returned = _manifest("returned", content)
    runner = FakeRunner(
        manifest_bytes=encode_manifest_json(returned),
        artifact_bytes=content,
    )
    root = _secure_root(tmp_path)

    _assert_code(
        "NAS_PULL_MANIFEST_IDENTITY_MISMATCH",
        lambda: _service(tmp_path, runner).pull(
            root=root,
            artifact_id=requested.artifact_id,
            source_generation=4,
        ),
    )

    assert [call.operation for call in runner.invocations] == ["manifest"]
    assert list(root.iterdir()) == []


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("checksum", "ARTIFACT_SHA256_MISMATCH"),
        ("size", "ARTIFACT_SIZE_MISMATCH"),
    ],
)
def test_canonical_checksum_and_size_failure_removes_owned_partial(
    tmp_path: Path,
    mutation: str,
    expected: str,
):
    expected_content = b"verified-content" * 30
    actual_content = (
        b"corrupted-content" * 30
        if mutation == "checksum"
        else expected_content
    )
    manifest = _manifest(f"verification-{mutation}", expected_content)
    if mutation == "size":
        manifest = replace(manifest, size_bytes=len(expected_content) + 1)
    runner = FakeRunner(
        manifest_bytes=encode_manifest_json(manifest),
        artifact_bytes=actual_content,
    )
    root = _secure_root(tmp_path)

    _assert_code(
        expected,
        lambda: _service(tmp_path, runner).pull(
            root=root,
            artifact_id=manifest.artifact_id,
            source_generation=5,
        ),
    )

    assert not (root / f"{manifest.published_name}.partial").exists()
    assert not (root / manifest.published_name).exists()
    assert not (root / ".nas-pull.lock").exists()


def test_failed_pull_can_retry_same_artifact_to_success(tmp_path: Path):
    content = b"retryable-full-dump" * 80
    manifest = _manifest("retry-same-artifact", content)
    runner = FakeRunner(
        manifest_bytes=encode_manifest_json(manifest),
        artifact_bytes=content[:31],
        artifact_result=CommandResult(returncode=None, timed_out=True),
    )
    root = _secure_root(tmp_path)
    service = _service(tmp_path, runner)

    _assert_code(
        "NAS_PULL_COMMAND_TIMEOUT",
        lambda: service.pull(
            root=root,
            artifact_id=manifest.artifact_id,
            source_generation=8,
        ),
    )
    assert not (root / f"{manifest.published_name}.partial").exists()
    assert not (root / manifest.published_name).exists()

    runner.artifact_bytes = content
    runner.artifact_result = None
    result = service.pull(
        root=root,
        artifact_id=manifest.artifact_id,
        source_generation=8,
    )

    assert result.publication.artifact_path.read_bytes() == content
    assert result.backup_status_ack.artifact_id == manifest.artifact_id
    assert [call.operation for call in runner.invocations] == [
        "manifest",
        "artifact",
        "manifest",
        "artifact",
    ]


def test_cleanup_never_deletes_replaced_partial_inode(tmp_path: Path):
    content = b"owned-stream-content"
    manifest = _manifest("partial-replaced", content)
    root = _secure_root(tmp_path)
    partial = root / f"{manifest.published_name}.partial"

    class ReplacingRunner:
        def run(self, invocation: CommandInvocation) -> CommandResult:
            if invocation.operation == "manifest":
                return CommandResult(
                    returncode=0,
                    stdout=encode_manifest_json(manifest),
                )
            assert invocation.stdout_fd is not None
            os.write(invocation.stdout_fd, content)
            partial.unlink()
            partial.write_bytes(b"replacement-must-remain")
            return CommandResult(returncode=19)

    service = NasPullService(
        config=_config(tmp_path),
        runner=ReplacingRunner(),
        clock=lambda: BASE + timedelta(minutes=3),
    )

    _assert_code(
        "NAS_PULL_PARTIAL_CLEANUP_OWNERSHIP_CHANGED",
        lambda: service.pull(
            root=root,
            artifact_id=manifest.artifact_id,
            source_generation=3,
        ),
    )

    assert partial.read_bytes() == b"replacement-must-remain"
    assert not (root / manifest.published_name).exists()
    assert not (root / ".nas-pull.lock").exists()


def test_runner_exception_is_redacted_and_preserves_no_unstarted_partial(
    tmp_path: Path,
):
    secret = "/restricted/customer/acme/backup.sql.gz"
    content = b"exception-content"
    manifest = _manifest("runner-exception", content)
    runner = FakeRunner(
        manifest_bytes=encode_manifest_json(manifest),
        artifact_bytes=content,
        error=RuntimeError(f"provider failed at {secret}"),
    )
    root = _secure_root(tmp_path)

    error = _assert_code(
        "NAS_PULL_COMMAND_EXECUTION_FAILED",
        lambda: _service(tmp_path, runner).pull(
            root=root,
            artifact_id=manifest.artifact_id,
            source_generation=1,
        ),
    )

    assert secret not in str(error)
    assert not (root / f"{manifest.published_name}.partial").exists()
    assert not (root / ".nas-pull.lock").exists()


def test_config_and_repr_do_not_echo_endpoint_user_or_paths(tmp_path: Path):
    config = _config(tmp_path)
    config_repr = repr(config)
    assert "nas-source.internal" not in config_repr
    assert "backup_pull" not in config_repr
    assert str(config.identity_file) not in config_repr
    assert str(config.pinned_host_key_file) not in config_repr

    invocation = CommandInvocation(
        operation="manifest",
        argv=(SSH_EXECUTABLE, "secret-host-and-path"),
        timeout_seconds=5,
        max_stdout_bytes=1024,
    )
    assert "secret-host-and-path" not in repr(invocation)
    result = CommandResult(returncode=0, stdout=b"customer-output")
    assert "customer-output" not in repr(result)

    injected_host = "nas.internal; touch /tmp/injected"
    error = _assert_code(
        "NAS_PULL_SSH_CONFIG_INVALID",
        lambda: NasPullSshConfig(
            host=injected_host,
            user="backup_pull",
            port=22,
            identity_file=config.identity_file,
            pinned_host_key_file=config.pinned_host_key_file,
        ),
    )
    assert injected_host not in str(error)


def test_key_files_are_revalidated_and_symlink_swap_fails_closed(tmp_path: Path):
    config = _config(tmp_path)
    content = b"credential-revalidation-content"
    manifest = _manifest("credential-revalidation", content)
    runner = FakeRunner(
        manifest_bytes=encode_manifest_json(manifest),
        artifact_bytes=content,
    )
    outside = tmp_path / "outside_identity"
    outside.write_bytes(b"other-key")
    outside.chmod(0o600)
    config.identity_file.unlink()
    config.identity_file.symlink_to(outside)
    root = _secure_root(tmp_path)

    error = _assert_code(
        "NAS_PULL_SSH_CONFIG_INVALID",
        lambda: NasPullService(
            config=config,
            runner=runner,
            clock=lambda: BASE + timedelta(minutes=3),
        ).pull(
            root=root,
            artifact_id=manifest.artifact_id,
            source_generation=1,
        ),
    )

    assert str(config.identity_file) not in str(error)
    assert runner.invocations == []


@pytest.mark.parametrize("root_problem", ["relative", "open-mode", "symlink"])
def test_root_must_be_restricted_absolute_owned_directory(
    tmp_path: Path,
    root_problem: str,
):
    content = b"restricted-root-content"
    manifest = _manifest(f"root-{root_problem}", content)
    runner = FakeRunner(
        manifest_bytes=encode_manifest_json(manifest),
        artifact_bytes=content,
    )
    real = _secure_root(tmp_path, "real-root")
    if root_problem == "relative":
        selected: str | Path = "relative-backups"
    elif root_problem == "open-mode":
        real.chmod(0o755)
        selected = real
    else:
        selected = tmp_path / "linked-root"
        selected.symlink_to(real, target_is_directory=True)

    error = _assert_code(
        "NAS_PULL_ROOT_INVALID",
        lambda: _service(tmp_path, runner).pull(
            root=selected,
            artifact_id=manifest.artifact_id,
            source_generation=1,
        ),
    )

    assert str(selected) not in str(error)
    assert runner.invocations == []
