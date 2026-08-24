"""Fail-closed NAS filesystem executor for the fixed D23 retention plan.

The control-side planner decides which verified recovery points are retained.
This boundary only applies that immutable plan to one restricted NAS directory.
It re-verifies the newest successful trigger and every present cleanup pair,
preflights the complete plan before unlinking anything, and shares the pull
lock so publication and retention cannot overlap.

An artifact is the completion marker for its manifest.  Cleanup therefore
unlinks the artifact first, fsyncs the directory, then unlinks the manifest.
A crash between those operations leaves a manifest-only orphan which an exact
replay can safely validate and remove.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from inventory_control.backups.domain import RetentionPlan
from inventory_control.backups.filesystem import (
    BackupFilesystemError,
    decode_manifest_json,
    stream_sha256_and_size,
)


_LOCK_NAME = ".nas-pull.lock"
_MAX_MANIFEST_BYTES = 1024 * 1024


class NasRetentionError(RuntimeError):
    """Stable retention failure that never exposes a local path."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class NasRetentionResult:
    triggered_by_artifact_id: UUID
    deleted_artifact_ids: tuple[UUID, ...]
    already_absent_artifact_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True, repr=False)
class _ValidatedFile:
    path: Path
    device: int
    inode: int


@dataclass(frozen=True, slots=True, repr=False)
class _CleanupPair:
    artifact_id: UUID
    artifact: _ValidatedFile | None
    manifest: _ValidatedFile | None


def apply_nas_retention_plan(
    *,
    root: str | os.PathLike[str],
    plan: RetentionPlan,
) -> NasRetentionResult:
    """Apply one verified successful-point retention plan to a NAS directory.

    The function is deliberately filesystem-only.  It never computes policy,
    queries a database, acknowledges a backup, or invokes cloud sync.
    """

    canonical_root = _restricted_root(root)
    _require_plan(plan)
    lock = _acquire_overlap_lock(canonical_root)
    try:
        _validate_completed_pair(
            canonical_root,
            plan.triggered_by_artifact_id,
            required=True,
        )
        pairs = tuple(
            _validate_completed_pair(canonical_root, artifact_id, required=False)
            for artifact_id in plan.cleanup_candidate_ids
        )

        deleted: list[UUID] = []
        absent: list[UUID] = []
        for pair in pairs:
            if pair.artifact is None and pair.manifest is None:
                absent.append(pair.artifact_id)
                continue
            if pair.artifact is not None:
                _unlink_exact(pair.artifact)
                _fsync_directory(canonical_root)
            if pair.manifest is not None:
                _unlink_exact(pair.manifest)
                _fsync_directory(canonical_root)
            deleted.append(pair.artifact_id)
        return NasRetentionResult(
            triggered_by_artifact_id=plan.triggered_by_artifact_id,
            deleted_artifact_ids=tuple(deleted),
            already_absent_artifact_ids=tuple(absent),
        )
    finally:
        _release_overlap_lock(canonical_root, lock)


def _require_plan(plan: object) -> None:
    if not isinstance(plan, RetentionPlan):
        _fail("NAS_RETENTION_PLAN_INVALID")
    tiers = (
        plan.hourly_artifact_ids,
        plan.daily_artifact_ids,
        plan.monthly_artifact_ids,
    )
    sequences = (*tiers, plan.retained_artifact_ids, plan.cleanup_candidate_ids)
    if any(not _valid_id_sequence(value) for value in sequences):
        _fail("NAS_RETENTION_PLAN_INVALID")
    retained = set(plan.retained_artifact_ids)
    cleanup = set(plan.cleanup_candidate_ids)
    if (
        retained != set().union(*(set(value) for value in tiers))
        or retained & cleanup
        or plan.triggered_by_artifact_id not in retained
        or plan.triggered_by_artifact_id in cleanup
    ):
        _fail("NAS_RETENTION_PLAN_INVALID")


def _valid_id_sequence(value: object) -> bool:
    return (
        isinstance(value, tuple)
        and all(isinstance(item, UUID) and item.int != 0 for item in value)
        and len(value) == len(set(value))
    )


def _validate_completed_pair(
    root: Path,
    artifact_id: UUID,
    *,
    required: bool,
) -> _CleanupPair:
    name = f"backup-{artifact_id}.sql.gz"
    artifact_path = root / name
    manifest_path = root / f"{name}.manifest.json"
    artifact = _regular_file(artifact_path)
    manifest_file = _regular_file(manifest_path)
    if artifact is None and manifest_file is None:
        if required:
            _fail("NAS_RETENTION_TRIGGER_MISSING")
        return _CleanupPair(artifact_id, None, None)
    if artifact is not None and manifest_file is None:
        _fail("NAS_RETENTION_MANIFEST_MISSING")

    encoded = _read_stable_manifest(manifest_file)
    try:
        manifest = decode_manifest_json(encoded)
    except BackupFilesystemError:
        _fail("NAS_RETENTION_MANIFEST_INVALID")
    if manifest.artifact_id != artifact_id or manifest.published_name != name:
        _fail("NAS_RETENTION_MANIFEST_IDENTITY_MISMATCH")

    if artifact is not None:
        try:
            digest = stream_sha256_and_size(root=root, path=artifact.path)
        except BackupFilesystemError:
            _fail("NAS_RETENTION_ARTIFACT_INVALID")
        if (
            digest.sha256 != manifest.artifact_sha256
            or digest.size_bytes != manifest.size_bytes
        ):
            _fail("NAS_RETENTION_ARTIFACT_INVALID")
        _require_same_file(artifact)
    _require_same_file(manifest_file)
    return _CleanupPair(artifact_id, artifact, manifest_file)


def _regular_file(path: Path) -> _ValidatedFile | None:
    try:
        state = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        _fail("NAS_RETENTION_METADATA_FAILED")
    if stat.S_ISLNK(state.st_mode) or not stat.S_ISREG(state.st_mode):
        _fail("NAS_RETENTION_NONREGULAR_REJECTED")
    return _ValidatedFile(path=path, device=state.st_dev, inode=state.st_ino)


def _read_stable_manifest(file: _ValidatedFile | None) -> bytes:
    if file is None:
        _fail("NAS_RETENTION_MANIFEST_MISSING")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(
        os,
        "O_NOFOLLOW",
        0,
    )
    try:
        descriptor = os.open(file.path, flags)
    except OSError:
        _fail("NAS_RETENTION_MANIFEST_INVALID")
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_dev != file.device
            or before.st_ino != file.inode
            or before.st_size <= 0
            or before.st_size > _MAX_MANIFEST_BYTES
        ):
            _fail("NAS_RETENTION_MANIFEST_INVALID")
        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, min(65536, _MAX_MANIFEST_BYTES + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
            if total > _MAX_MANIFEST_BYTES:
                _fail("NAS_RETENTION_MANIFEST_INVALID")
        after = os.fstat(descriptor)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or total != after.st_size
        ):
            _fail("NAS_RETENTION_MANIFEST_INVALID")
        return b"".join(chunks)
    except NasRetentionError:
        raise
    except OSError:
        _fail("NAS_RETENTION_MANIFEST_INVALID")
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _require_same_file(file: _ValidatedFile | None) -> None:
    if file is None:
        _fail("NAS_RETENTION_METADATA_FAILED")
    try:
        current = os.lstat(file.path)
    except OSError:
        _fail("NAS_RETENTION_FILE_CHANGED")
    if (
        stat.S_ISLNK(current.st_mode)
        or not stat.S_ISREG(current.st_mode)
        or current.st_dev != file.device
        or current.st_ino != file.inode
    ):
        _fail("NAS_RETENTION_FILE_CHANGED")


def _unlink_exact(file: _ValidatedFile) -> None:
    _require_same_file(file)
    try:
        os.unlink(file.path)
    except OSError:
        _fail("NAS_RETENTION_CLEANUP_FAILED")


def _restricted_root(value: str | os.PathLike[str]) -> Path:
    try:
        root = Path(value)
    except TypeError:
        _fail("NAS_RETENTION_ROOT_INVALID")
    if not root.is_absolute():
        _fail("NAS_RETENTION_ROOT_INVALID")
    for component in _path_components(root):
        try:
            state = os.lstat(component)
        except OSError:
            _fail("NAS_RETENTION_ROOT_INVALID")
        if stat.S_ISLNK(state.st_mode):
            _fail("NAS_RETENTION_ROOT_INVALID")
    try:
        state = os.lstat(root)
    except OSError:
        _fail("NAS_RETENTION_ROOT_INVALID")
    if (
        not stat.S_ISDIR(state.st_mode)
        or state.st_uid != os.geteuid()
        or state.st_mode & 0o077
    ):
        _fail("NAS_RETENTION_ROOT_INVALID")
    return root


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
        _fail("NAS_RETENTION_OVERLAP")
    except OSError:
        _fail("NAS_RETENTION_LOCK_FAILED")
    try:
        state = os.fstat(descriptor)
        if not stat.S_ISREG(state.st_mode):
            _fail("NAS_RETENTION_LOCK_FAILED")
        if os.write(descriptor, b"retention\n") != len(b"retention\n"):
            _fail("NAS_RETENTION_LOCK_FAILED")
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
                _fsync_directory(root)
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
        _fail("NAS_RETENTION_LOCK_RELEASE_FAILED")


def _fsync_directory(root: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(
        os,
        "O_DIRECTORY",
        0,
    )
    try:
        descriptor = os.open(root, flags)
    except OSError:
        _fail("NAS_RETENTION_DIRECTORY_FSYNC_FAILED")
    try:
        os.fsync(descriptor)
    except OSError:
        _fail("NAS_RETENTION_DIRECTORY_FSYNC_FAILED")
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _path_components(path: Path) -> tuple[Path, ...]:
    components = []
    current = path
    while True:
        components.append(current)
        if current == current.parent:
            break
        current = current.parent
    return tuple(reversed(components))


def _fail(code: str) -> None:
    raise NasRetentionError(code)


__all__ = [
    "NasRetentionError",
    "NasRetentionResult",
    "apply_nas_retention_plan",
]
