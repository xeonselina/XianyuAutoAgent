"""Registry-authoritative loading for versioned platform root keys."""

from __future__ import annotations

import hmac
import os
import re
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

from .codec import CryptoCodecV1
from .errors import CryptoConfigurationError, RootKeyLoadError
from .root_key import RootKey, load_root_key


_FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z")
_MOUNTED_NAME = re.compile(r"v([1-9][0-9]*)\Z")


class RootKeyLifecycle(str, Enum):
    ACTIVE = "active"
    LEGACY = "legacy"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class RootKeyVersionFact:
    """Non-secret registry row used to reconcile mounted key versions."""

    version: int
    fingerprint_sha256: str
    status: RootKeyLifecycle

    def __post_init__(self) -> None:
        CryptoCodecV1.uint64(self.version)
        if (
            not isinstance(self.fingerprint_sha256, str)
            or _FINGERPRINT.fullmatch(self.fingerprint_sha256) is None
        ):
            raise CryptoConfigurationError("root key registry fingerprint is invalid")
        if not isinstance(self.status, RootKeyLifecycle):
            raise CryptoConfigurationError("root key registry status is invalid")


class RootKeyRing:
    """Immutable in-memory view of the exact active and legacy registry rows."""

    __slots__ = ("_active_version", "_keys", "_statuses")

    def __init__(
        self,
        *,
        active_version: int,
        keys: Mapping[int, RootKey],
        statuses: Mapping[int, RootKeyLifecycle],
    ) -> None:
        CryptoCodecV1.uint64(active_version)
        materialized = dict(keys)
        selected_statuses = dict(statuses)
        if (
            not materialized
            or set(materialized) != set(selected_statuses)
            or selected_statuses.get(active_version) is not RootKeyLifecycle.ACTIVE
        ):
            raise CryptoConfigurationError("root key ring is inconsistent")
        for version, key in materialized.items():
            if key.version != version or selected_statuses[version] not in {
                RootKeyLifecycle.ACTIVE,
                RootKeyLifecycle.LEGACY,
            }:
                raise CryptoConfigurationError("root key ring is inconsistent")
        object.__setattr__(self, "_active_version", active_version)
        object.__setattr__(self, "_keys", MappingProxyType(materialized))
        object.__setattr__(self, "_statuses", MappingProxyType(selected_statuses))

    @property
    def active_version(self) -> int:
        return self._active_version

    @property
    def active_key(self) -> RootKey:
        """Return the sole key authorized for new derivation/encryption."""

        return self._keys[self._active_version]

    @property
    def loaded_versions(self) -> tuple[int, ...]:
        return tuple(sorted(self._keys))

    def key_for_existing_reference(self, version: int) -> RootKey:
        """Resolve only an explicitly registered active/legacy version."""

        try:
            CryptoCodecV1.uint64(version)
            key = self._keys[version]
        except (CryptoConfigurationError, KeyError):
            raise RootKeyLoadError("referenced root key version is unavailable") from None
        return key

    def __repr__(self) -> str:
        return (
            "RootKeyRing("
            f"active_version={self._active_version}, "
            f"loaded_versions={self.loaded_versions}, material=<redacted>)"
        )


def load_root_key_ring(
    directory: str | os.PathLike[str],
    *,
    registry: Iterable[RootKeyVersionFact],
) -> RootKeyRing:
    """Load exactly the active/legacy files declared by the registry.

    ``directory`` contains files named ``v<N>``.  Registry rows in ``retired``
    state must not be mounted, and unregistered files are rejected rather than
    tried as alternative decryption keys.
    """

    key_directory = _validated_directory(directory)
    facts = _validated_registry(registry)
    usable = {
        fact.version: fact
        for fact in facts
        if fact.status in {RootKeyLifecycle.ACTIVE, RootKeyLifecycle.LEGACY}
    }
    active = tuple(
        fact for fact in facts if fact.status is RootKeyLifecycle.ACTIVE
    )
    if len(active) != 1:
        raise RootKeyLoadError("root key registry must contain exactly one active version")

    mounted = _mounted_versions(key_directory)
    if mounted != set(usable):
        raise RootKeyLoadError("mounted root key versions do not match the registry")

    keys: dict[int, RootKey] = {}
    statuses: dict[int, RootKeyLifecycle] = {}
    for version in sorted(usable):
        fact = usable[version]
        key = load_root_key(
            key_directory / f"v{version}",
            version=version,
            expected_fingerprint_sha256=fact.fingerprint_sha256,
        )
        if not hmac.compare_digest(key.fingerprint_sha256, fact.fingerprint_sha256):
            raise RootKeyLoadError("root key registry fingerprint does not match")
        keys[version] = key
        statuses[version] = fact.status
    return RootKeyRing(
        active_version=active[0].version,
        keys=keys,
        statuses=statuses,
    )


def _validated_directory(value: str | os.PathLike[str]) -> Path:
    try:
        raw = os.fspath(value)
    except TypeError:
        raise RootKeyLoadError("root key directory is invalid") from None
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise RootKeyLoadError("root key directory is invalid")
    selected = Path(raw)
    if not selected.is_absolute():
        raise RootKeyLoadError("root key directory must be absolute")
    try:
        observed = os.lstat(selected)
    except OSError:
        raise RootKeyLoadError("root key directory is unavailable") from None
    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISDIR(observed.st_mode):
        raise RootKeyLoadError("root key directory is invalid")
    return selected


def _validated_registry(
    registry: Iterable[RootKeyVersionFact],
) -> tuple[RootKeyVersionFact, ...]:
    try:
        facts = tuple(registry)
    except TypeError:
        raise RootKeyLoadError("root key registry is invalid") from None
    if not facts or any(not isinstance(fact, RootKeyVersionFact) for fact in facts):
        raise RootKeyLoadError("root key registry is invalid")
    versions = {fact.version for fact in facts}
    fingerprints = {fact.fingerprint_sha256 for fact in facts}
    if len(versions) != len(facts) or len(fingerprints) != len(facts):
        raise RootKeyLoadError("root key registry contains duplicate identities")
    return facts


def _mounted_versions(directory: Path) -> set[int]:
    versions: set[int] = set()
    try:
        entries = tuple(os.scandir(directory))
    except OSError:
        raise RootKeyLoadError("root key directory cannot be read") from None
    for entry in entries:
        match = _MOUNTED_NAME.fullmatch(entry.name)
        if match is None or entry.is_symlink() or not entry.is_file(follow_symlinks=False):
            raise RootKeyLoadError("root key directory contains an invalid entry")
        version = int(match.group(1))
        try:
            CryptoCodecV1.uint64(version)
        except CryptoConfigurationError:
            raise RootKeyLoadError("root key directory contains an invalid entry") from None
        if version in versions:
            raise RootKeyLoadError("root key directory contains duplicate versions")
        versions.add(version)
    return versions


__all__ = [
    "RootKeyLifecycle",
    "RootKeyRing",
    "RootKeyVersionFact",
    "load_root_key_ring",
]
