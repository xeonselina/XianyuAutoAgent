"""Fail-closed local filesystem boundary for backup publication.

This module does not run dumps, compression, SSH, NAS, database, or provider
operations.  It verifies caller-produced files beneath one absolute root and
turns them into observations for :func:`backups.domain.complete_backup`.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from uuid import UUID

from inventory_control.backups.domain import (
    BackupDomainError,
    BackupManifest,
    BackupObservation,
    BackupStage,
    DatabaseKind,
    DatabaseSnapshot,
    RecoveryMarkerSnapshot,
)


_FORMAT_VERSION = "inventory-manager-backup-manifest/v1"
_MAX_MANIFEST_BYTES = 1024 * 1024
_DEFAULT_CHUNK_SIZE = 1024 * 1024
_UPSTREAM_STAGES = frozenset(
    {BackupStage.DUMP, BackupStage.COMPRESSION, BackupStage.TRANSFER}
)
_ALL_STAGES = frozenset(BackupStage)
_SENSITIVE_KEY_FRAGMENTS = (
    "secret",
    "password",
    "credential",
    "api_key",
    "private_key",
    "key_material",
    "phone",
    "address",
    "customer",
    "plaintext",
    "pii",
)
_ENVELOPE_FIELDS = frozenset(
    {"format_version", "manifest_sha256", "manifest"}
)
_MANIFEST_FIELDS = frozenset(
    {
        "artifact_id",
        "attempt_id",
        "published_name",
        "snapshot_at_utc",
        "completed_at_utc",
        "artifact_sha256",
        "size_bytes",
        "databases",
        "root_key_versions",
        "recovery_marker",
    }
)
_DATABASE_FIELDS = frozenset(
    {
        "database_id",
        "kind",
        "schema_generation",
        "schema_sha256",
        "required_root_key_versions",
    }
)
_MARKER_FIELDS = frozenset(
    {
        "installation_id",
        "recovery_run_id",
        "marker_generation",
        "marker_sha256",
    }
)


class BackupFilesystemError(ValueError):
    """Stable failure that never includes a local path or raw OS message."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class FileDigest:
    sha256: bytes
    size_bytes: int


@dataclass(frozen=True, slots=True)
class BackupPublishResult:
    observation: BackupObservation
    artifact_path: Path
    manifest_path: Path


def encode_manifest_json(manifest: BackupManifest) -> bytes:
    """Encode the immutable manifest in the one accepted canonical form."""

    if not isinstance(manifest, BackupManifest):
        _fail("INVALID_BACKUP_MANIFEST")
    payload = {
        "format_version": _FORMAT_VERSION,
        "manifest_sha256": manifest.manifest_sha256.hex(),
        "manifest": _manifest_payload(manifest),
    }
    return _canonical_json(payload)


def decode_manifest_json(
    encoded: bytes,
    *,
    expected_manifest_sha256: bytes | None = None,
) -> BackupManifest:
    """Decode, schema-check, digest-check, and canonical-form-check a manifest."""

    if not isinstance(encoded, bytes) or not encoded:
        _fail("INVALID_MANIFEST_JSON")
    if len(encoded) > _MAX_MANIFEST_BYTES:
        _fail("MANIFEST_JSON_TOO_LARGE")
    if expected_manifest_sha256 is not None:
        _require_sha256("INVALID_EXPECTED_MANIFEST_SHA256", expected_manifest_sha256)
    try:
        text = encoded.decode("utf-8", errors="strict")
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: _fail("INVALID_MANIFEST_JSON_CONSTANT"),
        )
    except BackupFilesystemError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        _fail("INVALID_MANIFEST_JSON")
    _reject_sensitive_keys(decoded)
    envelope = _exact_object(decoded, _ENVELOPE_FIELDS, "MANIFEST_ENVELOPE")
    if envelope["format_version"] != _FORMAT_VERSION:
        _fail("UNSUPPORTED_MANIFEST_FORMAT")
    declared_digest = _decode_sha256(
        envelope["manifest_sha256"], "INVALID_MANIFEST_SHA256"
    )
    try:
        manifest = _decode_manifest_payload(envelope["manifest"])
    except BackupDomainError as exc:
        _fail(exc.code)
    if declared_digest != manifest.manifest_sha256:
        _fail("MANIFEST_SHA256_MISMATCH")
    if (
        expected_manifest_sha256 is not None
        and declared_digest != expected_manifest_sha256
    ):
        _fail("EXPECTED_MANIFEST_SHA256_MISMATCH")
    if encoded != encode_manifest_json(manifest):
        _fail("NONCANONICAL_MANIFEST_JSON")
    return manifest


def stream_sha256_and_size(
    *,
    root: str | os.PathLike[str],
    path: str | os.PathLike[str],
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
) -> FileDigest:
    """Hash a stable, regular, non-symlink file without loading it into memory."""

    canonical_root = _validated_root(root)
    candidate = _validated_direct_child(canonical_root, path)
    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool):
        _fail("INVALID_HASH_CHUNK_SIZE")
    if chunk_size <= 0 or chunk_size > 64 * 1024 * 1024:
        _fail("INVALID_HASH_CHUNK_SIZE")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        file_descriptor = os.open(candidate, flags)
    except OSError:
        _fail("ARTIFACT_OPEN_FAILED")
    try:
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode):
            _fail("ARTIFACT_NOT_REGULAR_FILE")
        digest = hashlib.sha256()
        size = 0
        while True:
            block = os.read(file_descriptor, chunk_size)
            if not block:
                break
            digest.update(block)
            size += len(block)
        after = os.fstat(file_descriptor)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or size != after.st_size
        ):
            _fail("ARTIFACT_CHANGED_DURING_HASH")
        return FileDigest(sha256=digest.digest(), size_bytes=size)
    except BackupFilesystemError:
        raise
    except OSError:
        _fail("ARTIFACT_READ_FAILED")
    finally:
        try:
            os.close(file_descriptor)
        except OSError:
            pass


def publish_verified_artifact(
    *,
    root: str | os.PathLike[str],
    partial_artifact_path: str | os.PathLike[str],
    manifest: BackupManifest,
    upstream_successful_stages: Iterable[BackupStage],
    database_now_utc: datetime,
) -> BackupPublishResult:
    """Verify, fsync, and atomically publish one artifact beneath ``root``.

    The sidecar manifest is made durable first; the final artifact link is the
    completion marker.  Publication uses same-directory hard-link no-replace
    semantics, so even a target created after the preflight check is preserved.
    """

    if not isinstance(manifest, BackupManifest):
        _fail("INVALID_BACKUP_MANIFEST")
    now = _utc("INVALID_DATABASE_TIME", database_now_utc)
    if manifest.snapshot_at_utc > now or manifest.completed_at_utc > now:
        _fail("ARTIFACT_TIME_IN_FUTURE")
    try:
        stages = frozenset(BackupStage(stage) for stage in upstream_successful_stages)
    except (TypeError, ValueError):
        _fail("INVALID_UPSTREAM_BACKUP_STAGE")
    if stages != _UPSTREAM_STAGES:
        _fail("UPSTREAM_STAGE_PROOF_INCOMPLETE")

    canonical_root = _validated_root(root)
    published_artifact = canonical_root / manifest.published_name
    expected_partial = canonical_root / f"{manifest.published_name}.partial"
    supplied_partial = _validated_direct_child(
        canonical_root, partial_artifact_path, must_exist=False
    )
    if supplied_partial != expected_partial:
        _fail("PARTIAL_ARTIFACT_PATH_MISMATCH")
    published_manifest = canonical_root / f"{manifest.published_name}.manifest.json"
    partial_manifest = canonical_root / (
        f"{manifest.published_name}.manifest.json.partial"
    )

    _reject_existing_published_artifact(published_artifact)
    _reject_symlink_or_nonregular(expected_partial, missing_code="PARTIAL_ARTIFACT_MISSING")
    digest = stream_sha256_and_size(root=canonical_root, path=expected_partial)
    if digest.sha256 != manifest.artifact_sha256:
        _fail("ARTIFACT_SHA256_MISMATCH")
    if digest.size_bytes != manifest.size_bytes:
        _fail("ARTIFACT_SIZE_MISMATCH")

    encoded_manifest = encode_manifest_json(manifest)
    decoded_manifest = decode_manifest_json(
        encoded_manifest,
        expected_manifest_sha256=manifest.manifest_sha256,
    )
    _stage_or_verify_manifest(
        root=canonical_root,
        partial_path=partial_manifest,
        published_path=published_manifest,
        encoded=encoded_manifest,
        manifest=manifest,
    )

    _fsync_regular_file(expected_partial)
    _reject_existing_published_artifact(published_artifact)
    _publish_noreplace_within_root(
        root=canonical_root,
        source=expected_partial,
        destination=published_artifact,
        code="ARTIFACT_ATOMIC_PUBLISH_FAILED",
    )
    _fsync_directory(canonical_root)

    observation = BackupObservation(
        artifact_id=decoded_manifest.artifact_id,
        attempt_id=decoded_manifest.attempt_id,
        partial_name=expected_partial.name,
        published_name=published_artifact.name,
        successful_stages=_ALL_STAGES,
        atomic_publish_succeeded=True,
        observed_artifact_sha256=digest.sha256,
        observed_manifest_sha256=decoded_manifest.manifest_sha256,
        observed_size_bytes=digest.size_bytes,
        observed_databases=decoded_manifest.databases,
        observed_root_key_versions=decoded_manifest.root_key_versions,
        observed_recovery_marker=decoded_manifest.recovery_marker,
    )
    return BackupPublishResult(
        observation=observation,
        artifact_path=published_artifact,
        manifest_path=published_manifest,
    )


def _stage_or_verify_manifest(
    *,
    root: Path,
    partial_path: Path,
    published_path: Path,
    encoded: bytes,
    manifest: BackupManifest,
) -> None:
    published_state = _lstat_optional(published_path)
    if published_state is not None:
        if stat.S_ISLNK(published_state.st_mode):
            _fail("MANIFEST_SYMLINK_REJECTED")
        if not stat.S_ISREG(published_state.st_mode):
            _fail("PUBLISHED_MANIFEST_NOT_REGULAR_FILE")
        existing = _read_bounded_regular_file(root=root, path=published_path)
        decoded = decode_manifest_json(
            existing,
            expected_manifest_sha256=manifest.manifest_sha256,
        )
        if decoded != manifest or existing != encoded:
            _fail("PUBLISHED_MANIFEST_CONFLICT")
        return

    partial_state = _lstat_optional(partial_path)
    if partial_state is None:
        _write_exclusive_regular_file(partial_path, encoded)
    else:
        if stat.S_ISLNK(partial_state.st_mode):
            _fail("MANIFEST_SYMLINK_REJECTED")
        if not stat.S_ISREG(partial_state.st_mode):
            _fail("PARTIAL_MANIFEST_NOT_REGULAR_FILE")
        existing = _read_bounded_regular_file(root=root, path=partial_path)
        decoded = decode_manifest_json(
            existing,
            expected_manifest_sha256=manifest.manifest_sha256,
        )
        if decoded != manifest or existing != encoded:
            _fail("PARTIAL_MANIFEST_CONFLICT")

    _fsync_regular_file(partial_path)
    if _lstat_optional(published_path) is not None:
        _fail("PUBLISHED_MANIFEST_CONFLICT")
    _publish_noreplace_within_root(
        root=root,
        source=partial_path,
        destination=published_path,
        code="MANIFEST_ATOMIC_PUBLISH_FAILED",
    )
    _fsync_directory(root)


def _write_exclusive_regular_file(path: Path, encoded: bytes) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        file_descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        _fail("PARTIAL_MANIFEST_ALREADY_EXISTS")
    except OSError:
        _fail("PARTIAL_MANIFEST_CREATE_FAILED")
    try:
        view = memoryview(encoded)
        written = 0
        while written < len(view):
            count = os.write(file_descriptor, view[written:])
            if count <= 0:
                _fail("PARTIAL_MANIFEST_WRITE_FAILED")
            written += count
        os.fsync(file_descriptor)
    except BackupFilesystemError:
        raise
    except OSError:
        _fail("PARTIAL_MANIFEST_WRITE_FAILED")
    finally:
        try:
            os.close(file_descriptor)
        except OSError:
            pass


def _read_bounded_regular_file(*, root: Path, path: Path) -> bytes:
    digest_path = _validated_direct_child(root, path)
    state = _lstat_optional(digest_path)
    if state is None or not stat.S_ISREG(state.st_mode) or stat.S_ISLNK(state.st_mode):
        _fail("MANIFEST_READ_FAILED")
    if state.st_size <= 0 or state.st_size > _MAX_MANIFEST_BYTES:
        _fail("INVALID_MANIFEST_FILE_SIZE")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(digest_path, flags)
    except OSError:
        _fail("MANIFEST_READ_FAILED")
    try:
        before = os.fstat(file_descriptor)
        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(file_descriptor, min(65536, _MAX_MANIFEST_BYTES + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
            if total > _MAX_MANIFEST_BYTES:
                _fail("MANIFEST_JSON_TOO_LARGE")
        after = os.fstat(file_descriptor)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or total != after.st_size
        ):
            _fail("MANIFEST_CHANGED_DURING_READ")
        return b"".join(chunks)
    except BackupFilesystemError:
        raise
    except OSError:
        _fail("MANIFEST_READ_FAILED")
    finally:
        try:
            os.close(file_descriptor)
        except OSError:
            pass


def _fsync_regular_file(path: Path) -> None:
    state = _lstat_optional(path)
    if state is None:
        _fail("FSYNC_SOURCE_MISSING")
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISREG(state.st_mode):
        _fail("FSYNC_SOURCE_NOT_REGULAR_FILE")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(path, flags)
    except OSError:
        _fail("FILE_FSYNC_FAILED")
    try:
        opened = os.fstat(file_descriptor)
        if opened.st_dev != state.st_dev or opened.st_ino != state.st_ino:
            _fail("FILE_CHANGED_BEFORE_FSYNC")
        os.fsync(file_descriptor)
    except BackupFilesystemError:
        raise
    except OSError:
        _fail("FILE_FSYNC_FAILED")
    finally:
        try:
            os.close(file_descriptor)
        except OSError:
            pass


def _fsync_directory(root: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    try:
        file_descriptor = os.open(root, flags)
    except OSError:
        _fail("BACKUP_DIRECTORY_FSYNC_FAILED")
    try:
        os.fsync(file_descriptor)
    except OSError:
        _fail("BACKUP_DIRECTORY_FSYNC_FAILED")
    finally:
        try:
            os.close(file_descriptor)
        except OSError:
            pass


def _publish_noreplace_within_root(
    *, root: Path, source: Path, destination: Path, code: str
) -> None:
    if source.parent != root or destination.parent != root:
        _fail("CROSS_DIRECTORY_ATOMIC_PUBLISH_REJECTED")
    source_state = _lstat_optional(source)
    if source_state is None:
        _fail("ATOMIC_PUBLISH_SOURCE_MISSING")
    if stat.S_ISLNK(source_state.st_mode) or not stat.S_ISREG(source_state.st_mode):
        _fail("ATOMIC_PUBLISH_SOURCE_NOT_REGULAR_FILE")
    try:
        os.link(source, destination, follow_symlinks=False)
    except FileExistsError:
        if destination.name.endswith(".manifest.json"):
            _fail("PUBLISHED_MANIFEST_CONFLICT")
        _fail("PUBLISHED_ARTIFACT_ALREADY_EXISTS")
    except OSError:
        _fail(code)
    destination_state = _lstat_optional(destination)
    if (
        destination_state is None
        or stat.S_ISLNK(destination_state.st_mode)
        or not stat.S_ISREG(destination_state.st_mode)
        or destination_state.st_dev != source_state.st_dev
        or destination_state.st_ino != source_state.st_ino
    ):
        _fail("ATOMIC_PUBLISH_IDENTITY_CHANGED")
    _fsync_directory(root)
    try:
        os.unlink(source)
    except OSError:
        _fail("ATOMIC_PUBLISH_SOURCE_CLEANUP_FAILED")


def _reject_existing_published_artifact(path: Path) -> None:
    state = _lstat_optional(path)
    if state is None:
        return
    if stat.S_ISLNK(state.st_mode):
        _fail("PUBLISHED_ARTIFACT_SYMLINK_REJECTED")
    _fail("PUBLISHED_ARTIFACT_ALREADY_EXISTS")


def _reject_symlink_or_nonregular(path: Path, *, missing_code: str) -> None:
    state = _lstat_optional(path)
    if state is None:
        _fail(missing_code)
    if stat.S_ISLNK(state.st_mode):
        _fail("ARTIFACT_SYMLINK_REJECTED")
    if not stat.S_ISREG(state.st_mode):
        _fail("ARTIFACT_NOT_REGULAR_FILE")


def _lstat_optional(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        _fail("FILESYSTEM_METADATA_READ_FAILED")


def _validated_root(root: str | os.PathLike[str]) -> Path:
    try:
        candidate = Path(root)
    except TypeError:
        _fail("INVALID_BACKUP_ROOT")
    if not candidate.is_absolute():
        _fail("BACKUP_ROOT_NOT_ABSOLUTE")
    for component in _path_components(candidate):
        try:
            state = os.lstat(component)
        except OSError:
            _fail("INVALID_BACKUP_ROOT")
        if stat.S_ISLNK(state.st_mode):
            _fail("BACKUP_ROOT_SYMLINK_REJECTED")
    try:
        state = os.lstat(candidate)
    except OSError:
        _fail("INVALID_BACKUP_ROOT")
    if not stat.S_ISDIR(state.st_mode):
        _fail("BACKUP_ROOT_NOT_DIRECTORY")
    return candidate


def _validated_direct_child(
    root: Path,
    path: str | os.PathLike[str],
    *,
    must_exist: bool = True,
) -> Path:
    try:
        candidate = Path(path)
    except TypeError:
        _fail("INVALID_BACKUP_PATH")
    if not candidate.is_absolute():
        _fail("BACKUP_PATH_NOT_ABSOLUTE")
    if candidate.parent != root or candidate.name in ("", ".", ".."):
        _fail("BACKUP_PATH_OUTSIDE_ROOT")
    if must_exist and _lstat_optional(candidate) is None:
        _fail("BACKUP_PATH_MISSING")
    return candidate


def _path_components(path: Path) -> Sequence[Path]:
    components: list[Path] = []
    current = path
    while True:
        components.append(current)
        if current == current.parent:
            break
        current = current.parent
    return tuple(reversed(components))


def _manifest_payload(manifest: BackupManifest) -> dict[str, Any]:
    return {
        "artifact_id": str(manifest.artifact_id),
        "attempt_id": str(manifest.attempt_id),
        "published_name": manifest.published_name,
        "snapshot_at_utc": manifest.snapshot_at_utc.isoformat(),
        "completed_at_utc": manifest.completed_at_utc.isoformat(),
        "artifact_sha256": manifest.artifact_sha256.hex(),
        "size_bytes": manifest.size_bytes,
        "databases": [
            {
                "database_id": str(database.database_id),
                "kind": database.kind.value,
                "schema_generation": database.schema_generation,
                "schema_sha256": database.schema_sha256.hex(),
                "required_root_key_versions": list(
                    database.required_root_key_versions
                ),
            }
            for database in manifest.databases
        ],
        "root_key_versions": list(manifest.root_key_versions),
        "recovery_marker": {
            "installation_id": str(manifest.recovery_marker.installation_id),
            "recovery_run_id": str(manifest.recovery_marker.recovery_run_id),
            "marker_generation": manifest.recovery_marker.marker_generation,
            "marker_sha256": manifest.recovery_marker.marker_sha256.hex(),
        },
    }


def _decode_manifest_payload(value: object) -> BackupManifest:
    payload = _exact_object(value, _MANIFEST_FIELDS, "MANIFEST")
    databases_value = payload["databases"]
    if not isinstance(databases_value, list):
        _fail("INVALID_MANIFEST_DATABASES")
    databases = tuple(_decode_database(item) for item in databases_value)
    marker_payload = _exact_object(
        payload["recovery_marker"], _MARKER_FIELDS, "RECOVERY_MARKER"
    )
    return BackupManifest(
        artifact_id=_decode_uuid(payload["artifact_id"], "INVALID_ARTIFACT_ID"),
        attempt_id=_decode_uuid(payload["attempt_id"], "INVALID_ATTEMPT_ID"),
        published_name=_require_string(
            payload["published_name"], "INVALID_PUBLISHED_ARTIFACT_NAME"
        ),
        snapshot_at_utc=_decode_datetime(
            payload["snapshot_at_utc"], "INVALID_SNAPSHOT_TIME"
        ),
        completed_at_utc=_decode_datetime(
            payload["completed_at_utc"], "INVALID_COMPLETION_TIME"
        ),
        artifact_sha256=_decode_sha256(
            payload["artifact_sha256"], "INVALID_ARTIFACT_SHA256"
        ),
        size_bytes=_require_positive_int(
            payload["size_bytes"], "INVALID_ARTIFACT_SIZE"
        ),
        databases=databases,
        root_key_versions=_decode_positive_int_list(
            payload["root_key_versions"], "INVALID_ROOT_KEY_VERSION_SET"
        ),
        recovery_marker=RecoveryMarkerSnapshot(
            installation_id=_decode_uuid(
                marker_payload["installation_id"], "INVALID_INSTALLATION_ID"
            ),
            recovery_run_id=_decode_uuid(
                marker_payload["recovery_run_id"], "INVALID_RECOVERY_RUN_ID"
            ),
            marker_generation=_require_positive_int(
                marker_payload["marker_generation"], "INVALID_MARKER_GENERATION"
            ),
            marker_sha256=_decode_sha256(
                marker_payload["marker_sha256"], "INVALID_MARKER_SHA256"
            ),
        ),
    )


def _decode_database(value: object) -> DatabaseSnapshot:
    payload = _exact_object(value, _DATABASE_FIELDS, "DATABASE")
    try:
        kind = DatabaseKind(payload["kind"])
    except (TypeError, ValueError):
        _fail("INVALID_DATABASE_KIND")
    return DatabaseSnapshot(
        database_id=_decode_uuid(payload["database_id"], "INVALID_DATABASE_ID"),
        kind=kind,
        schema_generation=_require_positive_int(
            payload["schema_generation"], "INVALID_SCHEMA_GENERATION"
        ),
        schema_sha256=_decode_sha256(
            payload["schema_sha256"], "INVALID_SCHEMA_SHA256"
        ),
        required_root_key_versions=_decode_positive_int_list(
            payload["required_root_key_versions"],
            "INVALID_ROOT_KEY_VERSION_SET",
        ),
    )


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("DUPLICATE_MANIFEST_JSON_KEY")
        result[key] = value
    return result


def _reject_sensitive_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                _fail("INVALID_MANIFEST_JSON_KEY")
            lowered = key.casefold()
            if any(fragment in lowered for fragment in _SENSITIVE_KEY_FRAGMENTS):
                _fail("SENSITIVE_MANIFEST_KEY_REJECTED")
            _reject_sensitive_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_sensitive_keys(nested)


def _exact_object(
    value: object, expected: frozenset[str], label: str
) -> dict[str, object]:
    if not isinstance(value, dict):
        _fail(f"INVALID_{label}_OBJECT")
    keys = frozenset(value)
    if keys != expected:
        if expected - keys:
            _fail(f"MISSING_{label}_FIELD")
        _fail(f"UNKNOWN_{label}_FIELD")
    return value


def _decode_uuid(value: object, code: str) -> UUID:
    if not isinstance(value, str):
        _fail(code)
    try:
        decoded = UUID(value)
    except (ValueError, AttributeError):
        _fail(code)
    if str(decoded) != value:
        _fail(code)
    return decoded


def _decode_datetime(value: object, code: str) -> datetime:
    if not isinstance(value, str):
        _fail(code)
    try:
        decoded = datetime.fromisoformat(value)
    except ValueError:
        _fail(code)
    normalized = _utc(code, decoded)
    if normalized.isoformat() != value:
        _fail(code)
    return normalized


def _decode_sha256(value: object, code: str) -> bytes:
    if not isinstance(value, str) or len(value) != 64 or value != value.lower():
        _fail(code)
    try:
        decoded = bytes.fromhex(value)
    except ValueError:
        _fail(code)
    _require_sha256(code, decoded)
    return decoded


def _decode_positive_int_list(value: object, code: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        _fail(code)
    return tuple(_require_positive_int(item, code) for item in value)


def _require_positive_int(value: object, code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        _fail(code)
    return value


def _require_string(value: object, code: str) -> str:
    if not isinstance(value, str):
        _fail(code)
    return value


def _require_sha256(code: str, value: object) -> None:
    if not isinstance(value, bytes) or len(value) != 32:
        _fail(code)


def _utc(code: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        _fail(code)
    normalized = value.astimezone(timezone.utc)
    if normalized.utcoffset() != timedelta(0):
        _fail(code)
    return normalized


def _fail(code: str) -> None:
    raise BackupFilesystemError(code)
