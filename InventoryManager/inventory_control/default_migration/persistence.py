"""Crash-safe local persistence for a default-migration journal.

This adapter deliberately knows nothing about application or database
configuration.  It gives the migration executor a small, process-safe compare
and-swap boundary so a completed phase cannot be lost, rewritten, or appended
twice after a crash or response loss.
"""

from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .manifest import (
    DefaultTenantMigrationManifest,
    MigrationEvidenceError,
    MigrationJournal,
    MigrationManifestError,
    MigrationManifestMismatchError,
)
from .serde import journal_from_document, journal_to_document


_MAX_JOURNAL_BYTES = 1_048_576


class MigrationJournalPersistenceError(MigrationEvidenceError):
    """The durable journal is missing, malformed, stale, or non-monotonic."""


class MigrationJournalFileStore:
    """Persist one journal with an advisory lock and atomic replacement."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        if not self._path.name or self._path.name in {".", ".."}:
            raise MigrationJournalPersistenceError("journal path is invalid")

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> MigrationJournal:
        """Load one strict JSON journal without following a final symlink."""

        try:
            descriptor = os.open(self._path, _read_flags())
        except FileNotFoundError:
            raise MigrationJournalPersistenceError("journal does not exist") from None
        except OSError:
            raise MigrationJournalPersistenceError("journal cannot be opened") from None
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise MigrationJournalPersistenceError(
                    "journal must be a regular file"
                )
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(_MAX_JOURNAL_BYTES + 1)
        finally:
            os.close(descriptor)
        if not raw or len(raw) > _MAX_JOURNAL_BYTES:
            raise MigrationJournalPersistenceError("journal size is invalid")
        try:
            document = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_unique_object,
            )
            return journal_from_document(document)
        except (
            UnicodeError,
            json.JSONDecodeError,
            MigrationManifestError,
            TypeError,
            ValueError,
        ):
            raise MigrationJournalPersistenceError("journal is invalid") from None

    def initialize(
        self,
        manifest: DefaultTenantMigrationManifest,
    ) -> MigrationJournal:
        """Create an empty journal, or return the exact existing one on replay."""

        if not isinstance(manifest, DefaultTenantMigrationManifest):
            raise TypeError("manifest is invalid")
        with self._exclusive_lock():
            if self._path.exists():
                existing = self.load()
                _require_manifest(existing, manifest)
                return existing
            journal = MigrationJournal.for_manifest(manifest)
            self._atomic_write(journal)
            return journal

    def compare_and_swap(
        self,
        manifest: DefaultTenantMigrationManifest,
        *,
        expected: MigrationJournal,
        replacement: MigrationJournal,
    ) -> MigrationJournal:
        """Persist exactly one immutable journal transition.

        Retrying an already-persisted replacement is an idempotent success.
        Otherwise the current journal must equal ``expected`` and the
        replacement may only append one phase or add the one-way authoritative
        write marker.  Existing phase evidence can never be edited or removed.
        """

        if not isinstance(manifest, DefaultTenantMigrationManifest):
            raise TypeError("manifest is invalid")
        if not isinstance(expected, MigrationJournal) or not isinstance(
            replacement, MigrationJournal
        ):
            raise TypeError("journal is invalid")
        _require_manifest(expected, manifest)
        _require_manifest(replacement, manifest)
        with self._exclusive_lock():
            current = self.load()
            _require_manifest(current, manifest)
            if current == replacement:
                return current
            if current != expected:
                raise MigrationJournalPersistenceError(
                    "journal compare-and-swap is stale"
                )
            _require_single_transition(current, replacement)
            self._atomic_write(replacement)
            return replacement

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        parent = self._path.parent
        if not parent.is_dir():
            raise MigrationJournalPersistenceError(
                "journal parent directory does not exist"
            )
        lock_path = parent / f".{self._path.name}.lock"
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = -1
        try:
            descriptor = os.open(lock_path, flags, 0o600)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise MigrationJournalPersistenceError(
                    "journal lock must be a regular file"
                )
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError:
            if descriptor >= 0:
                os.close(descriptor)
            raise MigrationJournalPersistenceError(
                "journal lock cannot be acquired"
            ) from None
        except MigrationJournalPersistenceError:
            if descriptor >= 0:
                os.close(descriptor)
            raise
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _atomic_write(self, journal: MigrationJournal) -> None:
        parent = self._path.parent
        encoded = (
            json.dumps(
                journal_to_document(journal),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
            + b"\n"
        )
        descriptor = -1
        temporary_path: str | None = None
        try:
            descriptor, temporary_path = tempfile.mkstemp(
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                dir=parent,
            )
            os.fchmod(descriptor, 0o600)
            _write_all(descriptor, encoded)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary_path, self._path)
            temporary_path = None
            directory = os.open(
                parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            raise MigrationJournalPersistenceError(
                "journal cannot be persisted"
            ) from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass


def _require_manifest(
    journal: MigrationJournal,
    manifest: DefaultTenantMigrationManifest,
) -> None:
    if journal.manifest_digest != manifest.digest:
        raise MigrationManifestMismatchError(
            "journal belongs to another immutable manifest"
        )


def _require_single_transition(
    current: MigrationJournal,
    replacement: MigrationJournal,
) -> None:
    phase_appended = (
        len(replacement.completed) == len(current.completed) + 1
        and replacement.completed[:-1] == current.completed
        and replacement.tenant_aware_writes_enabled_at
        == current.tenant_aware_writes_enabled_at
    )
    marker_added = (
        replacement.completed == current.completed
        and current.tenant_aware_writes_enabled_at is None
        and replacement.tenant_aware_writes_enabled_at is not None
    )
    if phase_appended == marker_added:
        raise MigrationJournalPersistenceError(
            "journal replacement must be one immutable transition"
        )


def _read_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )


def _write_all(descriptor: int, value: bytes) -> None:
    offset = 0
    while offset < len(value):
        written = os.write(descriptor, value[offset:])
        if written <= 0:
            raise OSError("short journal write")
        offset += written


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise json.JSONDecodeError("duplicate object key", key, 0)
        value[key] = item
    return value
