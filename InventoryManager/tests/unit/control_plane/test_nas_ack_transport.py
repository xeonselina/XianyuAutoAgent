from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

import inventory_control.backups.nas_pull as nas_pull
from inventory_control.backups.acknowledgements import (
    AcknowledgementKind,
    AcknowledgementSafeResult,
    AcknowledgementSubmission,
    BackupAcknowledgementError,
    acknowledgement_request_digest,
)
from inventory_control.backups.domain import (
    BackupManifest,
    BackupStage,
    DatabaseKind,
    DatabaseSnapshot,
    RecoveryMarkerSnapshot,
)
from inventory_control.backups.filesystem import publish_verified_artifact
from inventory_control.backups.nas_ack_transport import (
    AcknowledgementDeliveryStatus,
    NasAcknowledgementTransport,
    NasAcknowledgementTransportError,
)
from inventory_control.backups.nas_pull import (
    CommandInvocation,
    CommandResult,
    NasPullError,
    NasPullResult,
    NasPullSshConfig,
    REMOTE_WRAPPER,
    SSH_EXECUTABLE,
    SubprocessCommandRunner,
    WrapperCommand,
    fixed_wrapper_ssh_argv,
)


UTC = timezone.utc
BASE = datetime(2026, 8, 22, 10, 0, 0, 123456, tzinfo=UTC)
UPSTREAM_STAGES = frozenset(
    {BackupStage.DUMP, BackupStage.COMPRESSION, BackupStage.TRANSFER}
)


def _id(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"inventory-manager-nas-ack/{label}")


def _digest(value: bytes | str) -> bytes:
    if isinstance(value, str):
        value = value.encode("ascii")
    return hashlib.sha256(value).digest()


def _manifest(label: str, content: bytes) -> BackupManifest:
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
    artifact_id = _id(f"artifact/{label}")
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
            marker_sha256=_digest("marker"),
        ),
    )


def _submission(
    manifest: BackupManifest,
    *,
    kind: AcknowledgementKind,
    generation: int = 5,
) -> AcknowledgementSubmission:
    result = (
        AcknowledgementSafeResult.VERIFIED
        if kind is AcknowledgementKind.BACKUP_STATUS
        else AcknowledgementSafeResult.SYNCED
    )
    key_prefix = "nas-pull" if kind is AcknowledgementKind.BACKUP_STATUS else "nas-sync"
    key = f"{key_prefix}:{manifest.artifact_id}:{generation}"
    reported_at = BASE + timedelta(minutes=3)
    request_digest = acknowledgement_request_digest(
        kind=kind,
        artifact_id=manifest.artifact_id,
        manifest_sha256=manifest.manifest_sha256,
        artifact_sha256=manifest.artifact_sha256,
        source_generation=generation,
        idempotency_key=key,
        safe_result=result,
        reported_at_utc=reported_at,
    )
    return AcknowledgementSubmission(
        kind=kind,
        artifact_id=manifest.artifact_id,
        manifest_sha256=manifest.manifest_sha256,
        artifact_sha256=manifest.artifact_sha256,
        source_generation=generation,
        idempotency_key=key,
        request_digest=request_digest,
        safe_result=result,
        reported_at_utc=reported_at,
    )


def _pull_result(
    tmp_path: Path,
    *,
    label: str = "verified",
) -> tuple[NasPullResult, BackupManifest, bytes]:
    content = (f"consistent-full-dump/{label}/" * 80).encode("ascii")
    manifest = _manifest(label, content)
    root = tmp_path / f"backups-{label}"
    root.mkdir()
    partial = root / f"{manifest.published_name}.partial"
    partial.write_bytes(content)
    publication = publish_verified_artifact(
        root=root,
        partial_artifact_path=partial,
        manifest=manifest,
        upstream_successful_stages=UPSTREAM_STAGES,
        database_now_utc=BASE + timedelta(minutes=3),
    )
    return (
        NasPullResult(
            publication=publication,
            backup_status_ack=_submission(
                manifest,
                kind=AcknowledgementKind.BACKUP_STATUS,
            ),
        ),
        manifest,
        content,
    )


def _config(tmp_path: Path) -> NasPullSshConfig:
    identity = tmp_path / "ack_identity"
    identity.write_bytes(b"test-private-key")
    identity.chmod(0o600)
    pinned = tmp_path / "ack_known_hosts"
    pinned.write_bytes(b"backup.internal ssh-ed25519 pinned-test-key")
    pinned.chmod(0o600)
    return NasPullSshConfig(
        host="backup.internal",
        user="backup_pull",
        port=2222,
        identity_file=identity,
        pinned_host_key_file=pinned,
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def _response(
    submission: AcknowledgementSubmission,
    *,
    status: str = "accepted",
    changes: dict[str, object] | None = None,
) -> bytes:
    payload: dict[str, object] = {
        "protocol_version": "inventory-manager-backup-ack-response/v1",
        "kind": submission.kind.value,
        "artifact_id": str(submission.artifact_id),
        "idempotency_key": submission.idempotency_key,
        "request_digest": submission.request_digest.hex(),
        "status": status,
    }
    if changes:
        payload.update(changes)
    return _canonical(payload)


class QueueRunner:
    def __init__(self, outcomes: list[CommandResult | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.invocations: list[CommandInvocation] = []

    def run(self, invocation: CommandInvocation) -> CommandResult:
        self.invocations.append(invocation)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _assert_code(code: str, call) -> NasAcknowledgementTransportError:
    with pytest.raises(NasAcknowledgementTransportError) as exc_info:
        call()
    assert exc_info.value.code == code
    assert str(exc_info.value) == code
    return exc_info.value


def test_verified_backup_ack_uses_fixed_wrapper_and_canonical_stdin(
    tmp_path: Path,
):
    pull_result, manifest, _ = _pull_result(tmp_path)
    submission = pull_result.backup_status_ack
    runner = QueueRunner([CommandResult(0, _response(submission))])
    transport = NasAcknowledgementTransport(
        config=_config(tmp_path),
        runner=runner,
    )

    receipt = transport.send_backup_status(pull_result=pull_result)

    assert receipt.kind is AcknowledgementKind.BACKUP_STATUS
    assert receipt.status is AcknowledgementDeliveryStatus.ACCEPTED
    assert receipt.idempotent_replay is False
    invocation = runner.invocations[0]
    assert invocation.operation == "ack"
    assert invocation.argv[-2:] == (REMOTE_WRAPPER, "backup-status-ack")
    assert str(manifest.artifact_id) not in invocation.argv
    assert submission.idempotency_key not in invocation.argv
    assert not hasattr(invocation, "shell")
    decoded = json.loads(invocation.stdin_bytes)
    assert invocation.stdin_bytes == _canonical(decoded)
    assert decoded["protocol_version"] == "inventory-manager-backup-ack/v1"
    assert decoded["acknowledgement"] == {
        "artifact_id": str(submission.artifact_id),
        "artifact_sha256": submission.artifact_sha256.hex(),
        "idempotency_key": submission.idempotency_key,
        "kind": "backup-status-ack",
        "manifest_sha256": submission.manifest_sha256.hex(),
        "reported_at_utc": submission.reported_at_utc.isoformat(
            timespec="microseconds"
        ),
        "request_digest": submission.request_digest.hex(),
        "safe_result": "verified",
        "source_generation": submission.source_generation,
    }
    serialized = invocation.stdin_bytes.decode("ascii").lower()
    assert "provider" not in serialized
    assert "customer" not in serialized
    assert "password" not in serialized
    assert "tombstone" not in serialized
    assert "drop" not in serialized
    assert str(pull_result.publication.artifact_path) not in serialized


def test_sync_ack_is_explicit_independent_and_uses_distinct_command(tmp_path: Path):
    _, manifest, _ = _pull_result(tmp_path)
    sync = _submission(manifest, kind=AcknowledgementKind.SYNC_STATUS)
    runner = QueueRunner([CommandResult(0, _response(sync))])
    transport = NasAcknowledgementTransport(
        config=_config(tmp_path),
        runner=runner,
    )

    receipt = transport.send_sync_status(submission=sync)

    assert receipt.kind is AcknowledgementKind.SYNC_STATUS
    assert receipt.status is AcknowledgementDeliveryStatus.ACCEPTED
    invocation = runner.invocations[0]
    assert invocation.argv[-2:] == (REMOTE_WRAPPER, "sync-status-ack")
    payload = json.loads(invocation.stdin_bytes)["acknowledgement"]
    assert payload["kind"] == "sync-status-ack"
    assert payload["safe_result"] == "synced"
    assert "backup-status-ack" not in invocation.stdin_bytes.decode("ascii")
    assert "tombstone" not in invocation.stdin_bytes.decode("ascii")


def test_response_loss_retries_identical_idempotent_request(tmp_path: Path):
    pull_result, _, _ = _pull_result(tmp_path, label="response-loss")
    submission = pull_result.backup_status_ack
    runner = QueueRunner(
        [
            CommandResult(returncode=None, timed_out=True),
            CommandResult(
                0,
                _response(submission, status="idempotent-replay"),
            ),
        ]
    )
    transport = NasAcknowledgementTransport(
        config=_config(tmp_path),
        runner=runner,
    )

    _assert_code(
        "NAS_ACK_TRANSPORT_TIMEOUT",
        lambda: transport.send_backup_status(pull_result=pull_result),
    )
    receipt = transport.send_backup_status(pull_result=pull_result)

    assert receipt.idempotent_replay is True
    assert runner.invocations[0].argv == runner.invocations[1].argv
    assert runner.invocations[0].stdin_bytes == runner.invocations[1].stdin_bytes
    assert json.loads(runner.invocations[0].stdin_bytes)["acknowledgement"][
        "idempotency_key"
    ] == submission.idempotency_key


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (CommandResult(returncode=17), "NAS_ACK_TRANSPORT_COMMAND_FAILED"),
        (CommandResult(returncode=0, stdout=b""), "NAS_ACK_RESPONSE_INVALID"),
        (CommandResult(returncode=0, stdout=b"not-json"), "NAS_ACK_RESPONSE_INVALID"),
        (
            CommandResult(returncode=0, stdout=b"x" * 4097),
            "NAS_ACK_RESPONSE_INVALID",
        ),
    ],
)
def test_command_and_response_failures_are_closed_and_redacted(
    tmp_path: Path,
    result: CommandResult,
    expected: str,
):
    _, manifest, _ = _pull_result(tmp_path, label=expected)
    sync = _submission(manifest, kind=AcknowledgementKind.SYNC_STATUS)
    runner = QueueRunner([result])
    transport = NasAcknowledgementTransport(
        config=_config(tmp_path),
        runner=runner,
    )

    error = _assert_code(
        expected,
        lambda: transport.send_sync_status(submission=sync),
    )

    assert str(tmp_path) not in str(error)
    assert "backup.internal" not in str(error)


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "backup-status-ack"},
        {"artifact_id": str(_id("different"))},
        {"idempotency_key": "different-slot"},
        {"request_digest": (b"x" * 32).hex()},
        {"path": "/private/nas/customer.sql.gz"},
    ],
)
def test_response_kind_identity_path_or_digest_anomaly_is_rejected(
    tmp_path: Path,
    changes: dict[str, object],
):
    _, manifest, _ = _pull_result(tmp_path, label=str(sorted(changes)))
    sync = _submission(manifest, kind=AcknowledgementKind.SYNC_STATUS)
    runner = QueueRunner(
        [CommandResult(returncode=0, stdout=_response(sync, changes=changes))]
    )
    transport = NasAcknowledgementTransport(
        config=_config(tmp_path),
        runner=runner,
    )

    _assert_code(
        "NAS_ACK_RESPONSE_INVALID"
        if "path" in changes
        else "NAS_ACK_RESPONSE_MISMATCH",
        lambda: transport.send_sync_status(submission=sync),
    )


def test_ack_kind_confusion_is_rejected_before_runner(tmp_path: Path):
    pull_result, _, _ = _pull_result(tmp_path, label="kind-confusion")
    runner = QueueRunner([])
    transport = NasAcknowledgementTransport(
        config=_config(tmp_path),
        runner=runner,
    )

    _assert_code(
        "NAS_ACK_KIND_MISMATCH",
        lambda: transport.send_sync_status(
            submission=pull_result.backup_status_ack,
        ),
    )
    _assert_code(
        "NAS_ACK_VERIFIED_BACKUP_PROOF_REQUIRED",
        lambda: transport.send_backup_status(pull_result=object()),
    )
    assert runner.invocations == []


@pytest.mark.parametrize(
    "damage",
    [
        "missing-artifact",
        "same-size-artifact-tamper",
        "corrupt-manifest",
        "symlink",
    ],
)
def test_backup_ack_requires_current_completed_artifact_and_canonical_manifest(
    tmp_path: Path,
    damage: str,
):
    pull_result, _, _ = _pull_result(tmp_path, label=damage)
    if damage == "missing-artifact":
        pull_result.publication.artifact_path.unlink()
    elif damage == "same-size-artifact-tamper":
        original = pull_result.publication.artifact_path.read_bytes()
        pull_result.publication.artifact_path.write_bytes(b"x" * len(original))
    elif damage == "corrupt-manifest":
        pull_result.publication.manifest_path.write_bytes(b"not-canonical")
    else:
        outside = tmp_path / "outside-manifest"
        outside.write_bytes(pull_result.publication.manifest_path.read_bytes())
        pull_result.publication.manifest_path.unlink()
        pull_result.publication.manifest_path.symlink_to(outside)
    runner = QueueRunner([])
    transport = NasAcknowledgementTransport(
        config=_config(tmp_path),
        runner=runner,
    )

    _assert_code(
        "NAS_ACK_VERIFIED_BACKUP_PROOF_INVALID",
        lambda: transport.send_backup_status(pull_result=pull_result),
    )

    assert runner.invocations == []


def test_free_remote_command_and_path_like_idempotency_are_rejected(
    tmp_path: Path,
):
    config = _config(tmp_path)
    with pytest.raises(NasPullError) as command_error:
        fixed_wrapper_ssh_argv(
            config,
            command="sync-status-ack; /bin/sh",  # type: ignore[arg-type]
        )
    assert command_error.value.code == "NAS_PULL_COMMAND_INVALID"

    manifest = _manifest("path-key", b"content")
    reported_at = BASE + timedelta(minutes=3)
    with pytest.raises(BackupAcknowledgementError):
        AcknowledgementSubmission(
            kind=AcknowledgementKind.SYNC_STATUS,
            artifact_id=manifest.artifact_id,
            manifest_sha256=manifest.manifest_sha256,
            artifact_sha256=manifest.artifact_sha256,
            source_generation=1,
            idempotency_key="../../private/customer;touch",
            request_digest=b"x" * 32,
            safe_result=AcknowledgementSafeResult.SYNCED,
            reported_at_utc=reported_at,
        )


def test_subprocess_runner_sends_stdin_without_shell(monkeypatch):
    recorded: dict[str, object] = {}

    class Completed:
        returncode = 0

    def fake_run(argv, **kwargs):
        recorded["argv"] = argv
        recorded.update(kwargs)
        kwargs["stdout"].write(b"response")
        return Completed()

    monkeypatch.setattr(nas_pull.subprocess, "run", fake_run)
    invocation = CommandInvocation(
        operation="ack",
        argv=(SSH_EXECUTABLE, "fixed"),
        timeout_seconds=5,
        max_stdout_bytes=1024,
        stdin_bytes=b"canonical-request",
    )

    result = SubprocessCommandRunner().run(invocation)

    assert result.stdout == b"response"
    assert recorded["input"] == b"canonical-request"
    assert "stdin" not in recorded
    assert recorded["shell"] is False


def test_receipt_and_invocation_repr_redact_identity_and_payload(tmp_path: Path):
    _, manifest, _ = _pull_result(tmp_path, label="repr")
    sync = _submission(manifest, kind=AcknowledgementKind.SYNC_STATUS)
    runner = QueueRunner([CommandResult(0, _response(sync))])
    receipt = NasAcknowledgementTransport(
        config=_config(tmp_path),
        runner=runner,
    ).send_sync_status(submission=sync)

    assert str(sync.artifact_id) not in repr(receipt)
    assert sync.idempotency_key not in repr(receipt)
    assert sync.request_digest.hex() not in repr(receipt)
    assert sync.idempotency_key not in repr(runner.invocations[0])
    assert "canonical-request" not in repr(runner.invocations[0])
