"""Fixed, privacy-minimized NAS-to-host acknowledgement transport.

The module sends only versioned canonical acknowledgement facts through the
same restricted SSH identity and root-owned wrapper used by NAS pull.  It has
no database, tombstone, deletion, cloud-provider, or credential side effect.
In particular, a sync receipt can never stand in for a verified backup fact.
"""

from __future__ import annotations

import hmac
import json
import os
import stat
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, Mapping, Sequence
from uuid import UUID

from inventory_control.backups.acknowledgements import (
    AcknowledgementKind,
    AcknowledgementSafeResult,
    AcknowledgementSubmission,
)
from inventory_control.backups.domain import BackupStage
from inventory_control.backups.filesystem import (
    BackupFilesystemError,
    decode_manifest_json,
    stream_sha256_and_size,
)
from inventory_control.backups.nas_pull import (
    CommandInvocation,
    CommandResult,
    CommandRunner,
    NasPullResult,
    NasPullSshConfig,
    WrapperCommand,
    fixed_wrapper_ssh_argv,
)


_REQUEST_PROTOCOL: Final = "inventory-manager-backup-ack/v1"
_RESPONSE_PROTOCOL: Final = "inventory-manager-backup-ack-response/v1"
_MAX_REQUEST_BYTES: Final = 16 * 1024
_MAX_RESPONSE_BYTES: Final = 4096
_MAX_MANIFEST_BYTES: Final = 1024 * 1024
_MAX_TIMEOUT_SECONDS: Final = 300
_REQUEST_FIELDS: Final = frozenset({"protocol_version", "acknowledgement"})
_ACK_FIELDS: Final = frozenset(
    {
        "kind",
        "artifact_id",
        "manifest_sha256",
        "artifact_sha256",
        "source_generation",
        "idempotency_key",
        "request_digest",
        "safe_result",
        "reported_at_utc",
    }
)
_RESPONSE_FIELDS: Final = frozenset(
    {
        "protocol_version",
        "kind",
        "artifact_id",
        "idempotency_key",
        "request_digest",
        "status",
    }
)


class NasAcknowledgementTransportError(RuntimeError):
    """Stable failure that never includes endpoint, path, payload, or output."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AcknowledgementDeliveryStatus(str, Enum):
    ACCEPTED = "accepted"
    IDEMPOTENT_REPLAY = "idempotent-replay"


@dataclass(frozen=True, slots=True, repr=False)
class AcknowledgementDeliveryReceipt:
    kind: AcknowledgementKind
    artifact_id: UUID
    idempotency_key: str = field(repr=False)
    request_digest: bytes = field(repr=False)
    status: AcknowledgementDeliveryStatus

    def __post_init__(self) -> None:
        if (
            not isinstance(self.kind, AcknowledgementKind)
            or not isinstance(self.artifact_id, UUID)
            or self.artifact_id.int == 0
            or not isinstance(self.idempotency_key, str)
            or not self.idempotency_key
            or not isinstance(self.request_digest, bytes)
            or len(self.request_digest) != 32
            or not isinstance(self.status, AcknowledgementDeliveryStatus)
        ):
            _fail("NAS_ACK_RECEIPT_INVALID")

    @property
    def idempotent_replay(self) -> bool:
        return self.status is AcknowledgementDeliveryStatus.IDEMPOTENT_REPLAY

    def __repr__(self) -> str:
        return (
            "AcknowledgementDeliveryReceipt("
            f"kind={self.kind.value!r}, identity='<redacted>', "
            f"status={self.status.value!r})"
        )


class NasAcknowledgementTransport:
    """Deliver independent acknowledgement facts through the fixed wrapper."""

    __slots__ = ("_config", "_runner")

    def __init__(
        self,
        *,
        config: NasPullSshConfig,
        runner: CommandRunner,
    ) -> None:
        if not isinstance(config, NasPullSshConfig) or not callable(
            getattr(runner, "run", None)
        ):
            _fail("NAS_ACK_TRANSPORT_CONFIG_INVALID")
        self._config = config
        self._runner = runner

    def send_backup_status(
        self,
        *,
        pull_result: NasPullResult,
        timeout_seconds: int = 30,
    ) -> AcknowledgementDeliveryReceipt:
        """Send only a backup ack carrying a verified completed-local proof."""

        submission = _verified_backup_submission(pull_result)
        return self._send(
            submission=submission,
            expected_kind=AcknowledgementKind.BACKUP_STATUS,
            command=WrapperCommand.BACKUP_STATUS_ACK,
            timeout_seconds=timeout_seconds,
        )

    def send_sync_status(
        self,
        *,
        submission: AcknowledgementSubmission,
        timeout_seconds: int = 30,
    ) -> AcknowledgementDeliveryReceipt:
        """Send an explicit sync fact without producing a backup/drop proof."""

        selected = _validated_submission(
            submission,
            expected_kind=AcknowledgementKind.SYNC_STATUS,
        )
        return self._send(
            submission=selected,
            expected_kind=AcknowledgementKind.SYNC_STATUS,
            command=WrapperCommand.SYNC_STATUS_ACK,
            timeout_seconds=timeout_seconds,
        )

    def _send(
        self,
        *,
        submission: AcknowledgementSubmission,
        expected_kind: AcknowledgementKind,
        command: WrapperCommand,
        timeout_seconds: int,
    ) -> AcknowledgementDeliveryReceipt:
        timeout = _timeout(timeout_seconds)
        selected = _validated_submission(
            submission,
            expected_kind=expected_kind,
        )
        payload = _encode_submission(selected)
        try:
            invocation = CommandInvocation(
                operation="ack",
                argv=fixed_wrapper_ssh_argv(
                    self._config,
                    command=command,
                ),
                timeout_seconds=timeout,
                max_stdout_bytes=_MAX_RESPONSE_BYTES,
                stdin_bytes=payload,
            )
            result = self._runner.run(invocation)
        except NasAcknowledgementTransportError:
            raise
        except Exception:
            _fail("NAS_ACK_TRANSPORT_EXECUTION_FAILED")
        if not isinstance(result, CommandResult):
            _fail("NAS_ACK_TRANSPORT_RESULT_INVALID")
        if result.timed_out:
            _fail("NAS_ACK_TRANSPORT_TIMEOUT")
        if result.returncode != 0:
            _fail("NAS_ACK_TRANSPORT_COMMAND_FAILED")
        if not result.stdout or len(result.stdout) > _MAX_RESPONSE_BYTES:
            _fail("NAS_ACK_RESPONSE_INVALID")
        return _decode_receipt(result.stdout, expected=selected)


def _verified_backup_submission(
    pull_result: object,
) -> AcknowledgementSubmission:
    if not isinstance(pull_result, NasPullResult):
        _fail("NAS_ACK_VERIFIED_BACKUP_PROOF_REQUIRED")
    publication = pull_result.publication
    observation = publication.observation
    submission = _validated_submission(
        pull_result.backup_status_ack,
        expected_kind=AcknowledgementKind.BACKUP_STATUS,
    )
    if (
        not observation.atomic_publish_succeeded
        or observation.successful_stages != frozenset(BackupStage)
        or observation.artifact_id != submission.artifact_id
        or observation.observed_manifest_sha256 != submission.manifest_sha256
        or observation.observed_artifact_sha256 != submission.artifact_sha256
    ):
        _fail("NAS_ACK_VERIFIED_BACKUP_PROOF_INVALID")
    artifact_path = publication.artifact_path
    manifest_path = publication.manifest_path
    if (
        not isinstance(artifact_path, Path)
        or not isinstance(manifest_path, Path)
        or not artifact_path.is_absolute()
        or not manifest_path.is_absolute()
        or artifact_path.parent != manifest_path.parent
        or artifact_path.name != observation.published_name
        or manifest_path.name != f"{observation.published_name}.manifest.json"
    ):
        _fail("NAS_ACK_VERIFIED_BACKUP_PROOF_INVALID")
    artifact_state = _regular_file_state(artifact_path)
    if artifact_state.st_size != observation.observed_size_bytes:
        _fail("NAS_ACK_VERIFIED_BACKUP_PROOF_INVALID")
    try:
        current_artifact = stream_sha256_and_size(
            root=artifact_path.parent,
            path=artifact_path,
        )
    except BackupFilesystemError:
        _fail("NAS_ACK_VERIFIED_BACKUP_PROOF_INVALID")
    if (
        current_artifact.size_bytes != observation.observed_size_bytes
        or current_artifact.sha256 != observation.observed_artifact_sha256
        or current_artifact.sha256 != submission.artifact_sha256
    ):
        _fail("NAS_ACK_VERIFIED_BACKUP_PROOF_INVALID")
    encoded_manifest = _read_stable_manifest(manifest_path)
    try:
        manifest = decode_manifest_json(
            encoded_manifest,
            expected_manifest_sha256=submission.manifest_sha256,
        )
    except BackupFilesystemError:
        _fail("NAS_ACK_VERIFIED_BACKUP_PROOF_INVALID")
    if (
        manifest.artifact_id != observation.artifact_id
        or manifest.attempt_id != observation.attempt_id
        or manifest.published_name != observation.published_name
        or manifest.artifact_sha256 != observation.observed_artifact_sha256
        or manifest.size_bytes != observation.observed_size_bytes
        or manifest.databases != observation.observed_databases
        or manifest.root_key_versions != observation.observed_root_key_versions
        or manifest.recovery_marker != observation.observed_recovery_marker
    ):
        _fail("NAS_ACK_VERIFIED_BACKUP_PROOF_INVALID")
    return submission


def _validated_submission(
    submission: object,
    *,
    expected_kind: AcknowledgementKind,
) -> AcknowledgementSubmission:
    if not isinstance(submission, AcknowledgementSubmission):
        _fail("NAS_ACK_SUBMISSION_INVALID")
    try:
        selected = AcknowledgementSubmission(
            kind=submission.kind,
            artifact_id=submission.artifact_id,
            manifest_sha256=submission.manifest_sha256,
            artifact_sha256=submission.artifact_sha256,
            source_generation=submission.source_generation,
            idempotency_key=submission.idempotency_key,
            request_digest=submission.request_digest,
            safe_result=submission.safe_result,
            reported_at_utc=submission.reported_at_utc,
        )
    except Exception:
        _fail("NAS_ACK_SUBMISSION_INVALID")
    if selected.kind is not expected_kind:
        _fail("NAS_ACK_KIND_MISMATCH")
    expected_result = (
        AcknowledgementSafeResult.VERIFIED
        if expected_kind is AcknowledgementKind.BACKUP_STATUS
        else AcknowledgementSafeResult.SYNCED
    )
    if selected.safe_result is not expected_result:
        _fail("NAS_ACK_KIND_MISMATCH")
    return selected


def _encode_submission(submission: AcknowledgementSubmission) -> bytes:
    payload = {
        "protocol_version": _REQUEST_PROTOCOL,
        "acknowledgement": {
            "kind": submission.kind.value,
            "artifact_id": str(submission.artifact_id),
            "manifest_sha256": submission.manifest_sha256.hex(),
            "artifact_sha256": submission.artifact_sha256.hex(),
            "source_generation": submission.source_generation,
            "idempotency_key": submission.idempotency_key,
            "request_digest": submission.request_digest.hex(),
            "safe_result": submission.safe_result.value,
            "reported_at_utc": submission.reported_at_utc.isoformat(
                timespec="microseconds"
            ),
        },
    }
    encoded = _canonical_json(payload)
    if len(encoded) > _MAX_REQUEST_BYTES:
        _fail("NAS_ACK_REQUEST_TOO_LARGE")
    decoded = json.loads(encoded)
    if (
        not isinstance(decoded, dict)
        or frozenset(decoded) != _REQUEST_FIELDS
        or not isinstance(decoded["acknowledgement"], dict)
        or frozenset(decoded["acknowledgement"]) != _ACK_FIELDS
    ):
        _fail("NAS_ACK_REQUEST_INVALID")
    return encoded


def _decode_receipt(
    encoded: bytes,
    *,
    expected: AcknowledgementSubmission,
) -> AcknowledgementDeliveryReceipt:
    try:
        decoded = json.loads(
            encoded.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: _fail("NAS_ACK_RESPONSE_INVALID"),
        )
    except NasAcknowledgementTransportError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        _fail("NAS_ACK_RESPONSE_INVALID")
    if (
        not isinstance(decoded, Mapping)
        or frozenset(decoded) != _RESPONSE_FIELDS
        or decoded.get("protocol_version") != _RESPONSE_PROTOCOL
    ):
        _fail("NAS_ACK_RESPONSE_INVALID")
    raw_artifact_id = decoded.get("artifact_id")
    raw_request_digest = decoded.get("request_digest")
    try:
        kind = AcknowledgementKind(decoded["kind"])
        artifact_id = UUID(raw_artifact_id)
        status = AcknowledgementDeliveryStatus(decoded["status"])
        request_digest = bytes.fromhex(raw_request_digest)
    except (KeyError, TypeError, ValueError, AttributeError):
        _fail("NAS_ACK_RESPONSE_INVALID")
    idempotency_key = decoded["idempotency_key"]
    if (
        kind is not expected.kind
        or artifact_id != expected.artifact_id
        or raw_artifact_id != str(expected.artifact_id)
        or not isinstance(idempotency_key, str)
        or not hmac.compare_digest(idempotency_key, expected.idempotency_key)
        or not isinstance(raw_request_digest, str)
        or raw_request_digest != expected.request_digest.hex()
        or len(request_digest) != 32
        or not hmac.compare_digest(request_digest, expected.request_digest)
        or encoded != _canonical_json(dict(decoded))
    ):
        _fail("NAS_ACK_RESPONSE_MISMATCH")
    return AcknowledgementDeliveryReceipt(
        kind=kind,
        artifact_id=artifact_id,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        status=status,
    )


def _regular_file_state(path: Path) -> os.stat_result:
    try:
        state = os.lstat(path)
    except OSError:
        _fail("NAS_ACK_VERIFIED_BACKUP_PROOF_INVALID")
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISREG(state.st_mode):
        _fail("NAS_ACK_VERIFIED_BACKUP_PROOF_INVALID")
    return state


def _read_stable_manifest(path: Path) -> bytes:
    linked = _regular_file_state(path)
    if linked.st_size <= 0 or linked.st_size > _MAX_MANIFEST_BYTES:
        _fail("NAS_ACK_VERIFIED_BACKUP_PROOF_INVALID")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(
        os, "O_NOFOLLOW", 0
    )
    try:
        descriptor = os.open(path, flags)
    except OSError:
        _fail("NAS_ACK_VERIFIED_BACKUP_PROOF_INVALID")
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != linked.st_dev
            or opened.st_ino != linked.st_ino
        ):
            _fail("NAS_ACK_VERIFIED_BACKUP_PROOF_INVALID")
        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, min(65536, _MAX_MANIFEST_BYTES + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
            if total > _MAX_MANIFEST_BYTES:
                _fail("NAS_ACK_VERIFIED_BACKUP_PROOF_INVALID")
        after = os.fstat(descriptor)
        if (
            after.st_dev != opened.st_dev
            or after.st_ino != opened.st_ino
            or after.st_size != opened.st_size
            or after.st_mtime_ns != opened.st_mtime_ns
            or total != after.st_size
        ):
            _fail("NAS_ACK_VERIFIED_BACKUP_PROOF_INVALID")
        return b"".join(chunks)
    except NasAcknowledgementTransportError:
        raise
    except OSError:
        _fail("NAS_ACK_VERIFIED_BACKUP_PROOF_INVALID")
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _unique_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("NAS_ACK_RESPONSE_INVALID")
        result[key] = value
    return result


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError):
        _fail("NAS_ACK_PROTOCOL_INVALID")


def _timeout(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > _MAX_TIMEOUT_SECONDS
    ):
        _fail("NAS_ACK_TIMEOUT_INVALID")
    return value


def _fail(code: str):
    raise NasAcknowledgementTransportError(code)


__all__ = [
    "AcknowledgementDeliveryReceipt",
    "AcknowledgementDeliveryStatus",
    "NasAcknowledgementTransport",
    "NasAcknowledgementTransportError",
]
