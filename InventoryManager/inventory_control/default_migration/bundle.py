"""Canonical, offline identity for the default-tenant migration bundle."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Final, Mapping

from alembic.config import Config
from alembic.script import ScriptDirectory

from .manifest import DefaultTenantMigrationManifest


MIGRATION_BUNDLE_EVIDENCE_VERSION: Final = 1
_MAX_BUNDLE_FILE_BYTES: Final = 4 * 1024 * 1024
_DIRECTORY_RULES: Final = (
    ("app/models", frozenset({".py"})),
    ("app/services/migration", frozenset({".py"})),
    ("control_migrations", frozenset({".ini", ".mako", ".py"})),
    ("inventory_control/default_migration", frozenset({".py"})),
    ("inventory_control/models", frozenset({".py"})),
    ("migrations", frozenset({".ini", ".mako", ".py"})),
)
_REQUIRED_FILES: Final = (
    "requirements.txt",
    "tests/conftest.py",
    "tests/support/default_backfill.py",
    "tests/support/default_expand.py",
    "tests/support/default_portability.py",
    "tests/support/tenant_migration.py",
    "tests/support/test_database.py",
)
_TEST_RULES: Final = (
    ("tests/integration", "test_default_*.py"),
    ("tests/unit", "test_default_*.py"),
    ("tests/unit/control_plane", "test_default_*.py"),
)


class MigrationBundleError(RuntimeError):
    code = "MIGRATION_BUNDLE_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class MigrationBundleInputError(MigrationBundleError):
    code = "MIGRATION_BUNDLE_INPUT_INVALID"


class MigrationBundleContentError(MigrationBundleError):
    code = "MIGRATION_BUNDLE_CONTENT_INVALID"


class MigrationBundleMismatchError(MigrationBundleError):
    code = "MIGRATION_BUNDLE_MISMATCH"


@dataclass(frozen=True, slots=True)
class MigrationBundleFileEvidence:
    relative_path: str
    byte_size: int
    sha256_digest: bytes

    def __post_init__(self) -> None:
        if (
            not isinstance(self.relative_path, str)
            or not _relative_path(self.relative_path)
            or isinstance(self.byte_size, bool)
            or not isinstance(self.byte_size, int)
            or not 0 <= self.byte_size <= _MAX_BUNDLE_FILE_BYTES
            or not isinstance(self.sha256_digest, bytes)
            or len(self.sha256_digest) != 32
        ):
            raise MigrationBundleContentError()


@dataclass(frozen=True, slots=True)
class DefaultMigrationBundleEvidence:
    control_schema_head: str
    tenant_schema_head: str
    files: tuple[MigrationBundleFileEvidence, ...]
    bundle_digest: bytes
    evidence_version: int = MIGRATION_BUNDLE_EVIDENCE_VERSION

    def __post_init__(self) -> None:
        if (
            self.evidence_version != MIGRATION_BUNDLE_EVIDENCE_VERSION
            or not _head(self.control_schema_head)
            or not _head(self.tenant_schema_head)
            or not isinstance(self.files, tuple)
            or not self.files
            or any(
                not isinstance(item, MigrationBundleFileEvidence)
                for item in self.files
            )
            or tuple(sorted(self.files, key=lambda item: item.relative_path))
            != self.files
            or len({item.relative_path for item in self.files})
            != len(self.files)
            or not isinstance(self.bundle_digest, bytes)
            or len(self.bundle_digest) != 32
            or self.bundle_digest != _bundle_digest(
                control_schema_head=self.control_schema_head,
                tenant_schema_head=self.tenant_schema_head,
                files=self.files,
            )
        ):
            raise MigrationBundleContentError()

    def require_manifest(
        self,
        manifest: DefaultTenantMigrationManifest,
    ) -> None:
        if (
            not isinstance(manifest, DefaultTenantMigrationManifest)
            or manifest.control_schema_head != self.control_schema_head
            or manifest.tenant_schema_head != self.tenant_schema_head
            or manifest.migration_bundle_digest != self.bundle_digest
        ):
            raise MigrationBundleMismatchError()

    def safe_summary(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "evidence_version": self.evidence_version,
                "control_schema_head": self.control_schema_head,
                "tenant_schema_head": self.tenant_schema_head,
                "file_count": len(self.files),
                "bundle_digest": self.bundle_digest.hex(),
            }
        )


def build_default_migration_bundle_evidence(
    repository_root: Path,
) -> DefaultMigrationBundleEvidence:
    if (
        not isinstance(repository_root, Path)
        or not repository_root.is_absolute()
        or not repository_root.is_dir()
        or repository_root.is_symlink()
    ):
        raise MigrationBundleInputError()
    root = repository_root.resolve(strict=True)
    selected: dict[str, Path] = {}

    for directory_name, suffixes in _DIRECTORY_RULES:
        directory = _safe_path(root, directory_name, directory=True)
        matches = tuple(
            path
            for path in directory.rglob("*")
            if path.is_file()
            and path.suffix in suffixes
            and "__pycache__" not in path.parts
        )
        if not matches:
            raise MigrationBundleContentError()
        for path in matches:
            _select_file(root, path, selected)

    for relative_path in _REQUIRED_FILES:
        _select_file(
            root,
            _safe_path(root, relative_path, directory=False),
            selected,
        )

    for directory_name, pattern in _TEST_RULES:
        directory = _safe_path(root, directory_name, directory=True)
        matches = tuple(path for path in directory.glob(pattern) if path.is_file())
        if not matches:
            raise MigrationBundleContentError()
        for path in matches:
            _select_file(root, path, selected)

    files = tuple(
        _file_evidence(relative_path, selected[relative_path])
        for relative_path in sorted(selected)
    )
    control_head = _alembic_head(root / "control_migrations")
    tenant_head = _alembic_head(root / "migrations")
    return DefaultMigrationBundleEvidence(
        control_schema_head=control_head,
        tenant_schema_head=tenant_head,
        files=files,
        bundle_digest=_bundle_digest(
            control_schema_head=control_head,
            tenant_schema_head=tenant_head,
            files=files,
        ),
    )


def migration_bundle_evidence_to_document(
    evidence: DefaultMigrationBundleEvidence,
) -> dict[str, object]:
    if not isinstance(evidence, DefaultMigrationBundleEvidence):
        raise TypeError("migration bundle evidence is invalid")
    return {
        "evidence_version": evidence.evidence_version,
        "control_schema_head": evidence.control_schema_head,
        "tenant_schema_head": evidence.tenant_schema_head,
        "files": [
            {
                "relative_path": item.relative_path,
                "byte_size": item.byte_size,
                "sha256_digest": item.sha256_digest.hex(),
            }
            for item in evidence.files
        ],
        "bundle_digest": evidence.bundle_digest.hex(),
    }


def migration_bundle_evidence_from_document(
    document: Mapping[str, object],
) -> DefaultMigrationBundleEvidence:
    if not isinstance(document, Mapping) or set(document) != {
        "evidence_version",
        "control_schema_head",
        "tenant_schema_head",
        "files",
        "bundle_digest",
    }:
        raise MigrationBundleContentError()
    raw_files = document.get("files")
    if not isinstance(raw_files, list) or any(
        not isinstance(item, Mapping)
        or set(item)
        != {"relative_path", "byte_size", "sha256_digest"}
        for item in raw_files
    ):
        raise MigrationBundleContentError()
    try:
        files = tuple(
            MigrationBundleFileEvidence(
                relative_path=_text(item, "relative_path"),
                byte_size=_integer(item, "byte_size"),
                sha256_digest=_digest(item, "sha256_digest"),
            )
            for item in raw_files
        )
        return DefaultMigrationBundleEvidence(
            evidence_version=_integer(document, "evidence_version"),
            control_schema_head=_text(document, "control_schema_head"),
            tenant_schema_head=_text(document, "tenant_schema_head"),
            files=files,
            bundle_digest=_digest(document, "bundle_digest"),
        )
    except (KeyError, TypeError, ValueError):
        raise MigrationBundleContentError() from None


def _safe_path(root: Path, relative: str, *, directory: bool) -> Path:
    candidate = root / relative
    if candidate.is_symlink() or (directory and not candidate.is_dir()) or (
        not directory and not candidate.is_file()
    ):
        raise MigrationBundleContentError()
    try:
        candidate.resolve(strict=True).relative_to(root)
    except (OSError, ValueError):
        raise MigrationBundleContentError() from None
    return candidate


def _select_file(root: Path, path: Path, selected: dict[str, Path]) -> None:
    if path.is_symlink() or not path.is_file():
        raise MigrationBundleContentError()
    resolved = path.resolve(strict=True)
    try:
        relative_path = resolved.relative_to(root).as_posix()
    except ValueError:
        raise MigrationBundleContentError() from None
    if relative_path in selected and selected[relative_path] != resolved:
        raise MigrationBundleContentError()
    selected[relative_path] = resolved


def _file_evidence(relative_path: str, path: Path) -> MigrationBundleFileEvidence:
    try:
        size = path.stat().st_size
        if size > _MAX_BUNDLE_FILE_BYTES:
            raise MigrationBundleContentError()
        value = path.read_bytes()
    except OSError:
        raise MigrationBundleContentError() from None
    if len(value) != size:
        raise MigrationBundleContentError()
    return MigrationBundleFileEvidence(
        relative_path=relative_path,
        byte_size=size,
        sha256_digest=hashlib.sha256(value).digest(),
    )


def _alembic_head(script_location: Path) -> str:
    try:
        config = Config(str(script_location / "alembic.ini"))
        config.set_main_option("script_location", str(script_location))
        heads = tuple(ScriptDirectory.from_config(config).get_heads())
    except Exception:
        raise MigrationBundleContentError() from None
    if len(heads) != 1 or not _head(heads[0]):
        raise MigrationBundleContentError()
    return heads[0]


def _bundle_digest(
    *,
    control_schema_head: str,
    tenant_schema_head: str,
    files: tuple[MigrationBundleFileEvidence, ...],
) -> bytes:
    payload = {
        "evidence_version": MIGRATION_BUNDLE_EVIDENCE_VERSION,
        "control_schema_head": control_schema_head,
        "tenant_schema_head": tenant_schema_head,
        "files": [
            {
                "relative_path": item.relative_path,
                "byte_size": item.byte_size,
                "sha256_digest": item.sha256_digest.hex(),
            }
            for item in files
        ],
    }
    return hashlib.sha256(
        b"inventory-manager/default-migration-bundle/v1\x00"
        + json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).digest()


def _head(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and value
        and value == value.strip()
        and len(value) <= 128
        and all(0x21 <= ord(character) <= 0x7E for character in value)
    )


def _relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(
        value
        and len(value.encode("utf-8")) <= 1_024
        and value == unicodedata.normalize("NFC", value)
        and not path.is_absolute()
        and path.as_posix() == value
        and path.parts
        and all(part not in {"", ".", ".."} for part in path.parts)
        and "\\" not in value
        and all(
            ord(character) >= 0x20 and ord(character) != 0x7F
            for character in value
        )
    )


def _text(mapping: Mapping[str, object], key: str) -> str:
    value = mapping[key]
    if not isinstance(value, str):
        raise ValueError
    return value


def _integer(mapping: Mapping[str, object], key: str) -> int:
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError
    return value


def _digest(mapping: Mapping[str, object], key: str) -> bytes:
    value = mapping[key]
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError
    return bytes.fromhex(value)


__all__ = [
    "DefaultMigrationBundleEvidence",
    "MIGRATION_BUNDLE_EVIDENCE_VERSION",
    "MigrationBundleContentError",
    "MigrationBundleError",
    "MigrationBundleFileEvidence",
    "MigrationBundleInputError",
    "MigrationBundleMismatchError",
    "build_default_migration_bundle_evidence",
    "migration_bundle_evidence_from_document",
    "migration_bundle_evidence_to_document",
]
