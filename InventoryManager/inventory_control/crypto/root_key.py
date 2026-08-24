"""Versioned platform root-key representation and strict file loading."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from .codec import CryptoCodecV1
from .errors import CryptoConfigurationError, RootKeyLoadError

PathValue = Union[str, os.PathLike[str]]

_ROOT_KEY_BYTES = 32
_MAX_ENCODED_FILE_BYTES = 128
_ALLOWED_FILE_MODES = frozenset((0o400, 0o440))
_SHA256_HEX = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True, slots=True, init=False)
class RootKey:
    """A validated root-key version and its 256-bit secret material."""

    version: int
    _material: bytes = field(repr=False)

    def __init__(self, *, version: int, material: bytes) -> None:
        # Reuse the protocol's strict positive uint64 validation.
        CryptoCodecV1.uint64(version)
        if not isinstance(material, bytes) or len(material) != _ROOT_KEY_BYTES:
            raise CryptoConfigurationError("root key must contain exactly 32 bytes")
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "_material", bytes(material))

    @property
    def fingerprint_sha256(self) -> str:
        """Return the non-secret lowercase SHA-256 fingerprint."""

        return hashlib.sha256(self._material).hexdigest()

    def _material_bytes(self) -> bytes:
        """Return key material for this package's short-lived crypto objects."""

        return self._material


def root_key_fingerprint_sha256(root_key: RootKey) -> str:
    if not isinstance(root_key, RootKey):
        raise CryptoConfigurationError("root key is invalid")
    return root_key.fingerprint_sha256


def load_root_key(
    path: PathValue,
    *,
    version: int,
    expected_fingerprint_sha256: Optional[str] = None,
) -> RootKey:
    """Load one root-key version from an explicit, non-symlink file path.

    The file must be an absolute regular-file path with mode 0400 or 0440. Its
    content must be one canonical standard-Base64 line, optionally followed by
    one ``\n``, which decodes to exactly 32 bytes.
    """

    CryptoCodecV1.uint64(version)
    try:
        raw_path = os.fspath(path)
    except TypeError:
        raise RootKeyLoadError("root key path is invalid") from None
    if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
        raise RootKeyLoadError("root key path is invalid")

    key_path = Path(raw_path)
    if not key_path.is_absolute():
        raise RootKeyLoadError("root key path must be absolute")

    try:
        before_open = os.lstat(key_path)
    except OSError:
        raise RootKeyLoadError("root key file is unavailable") from None
    if stat.S_ISLNK(before_open.st_mode):
        raise RootKeyLoadError("root key file must not be a symbolic link")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(key_path, flags)
    except OSError:
        raise RootKeyLoadError("root key file cannot be opened safely") from None

    try:
        opened = os.fstat(file_descriptor)
        if (
            before_open.st_dev != opened.st_dev
            or before_open.st_ino != opened.st_ino
        ):
            raise RootKeyLoadError("root key file changed while opening")
        if not stat.S_ISREG(opened.st_mode):
            raise RootKeyLoadError("root key path must name a regular file")
        if stat.S_IMODE(opened.st_mode) not in _ALLOWED_FILE_MODES:
            raise RootKeyLoadError("root key file permissions are too broad")

        encoded_file = os.read(file_descriptor, _MAX_ENCODED_FILE_BYTES + 1)
        if len(encoded_file) > _MAX_ENCODED_FILE_BYTES:
            raise RootKeyLoadError("root key file content is invalid")
    finally:
        os.close(file_descriptor)

    if encoded_file.endswith(b"\n"):
        encoded_key = encoded_file[:-1]
    else:
        encoded_key = encoded_file
    if not encoded_key or b"\n" in encoded_key or b"\r" in encoded_key:
        raise RootKeyLoadError("root key file content is invalid")

    try:
        material = base64.b64decode(encoded_key, validate=True)
    except (ValueError, base64.binascii.Error):
        raise RootKeyLoadError("root key file content is invalid") from None
    if (
        len(material) != _ROOT_KEY_BYTES
        or base64.b64encode(material) != encoded_key
    ):
        raise RootKeyLoadError("root key file must decode to exactly 32 bytes")

    root_key = RootKey(version=version, material=material)
    if expected_fingerprint_sha256 is not None:
        if (
            not isinstance(expected_fingerprint_sha256, str)
            or _SHA256_HEX.fullmatch(expected_fingerprint_sha256) is None
        ):
            raise RootKeyLoadError("expected root key fingerprint is invalid")
        if not hmac.compare_digest(
            root_key.fingerprint_sha256,
            expected_fingerprint_sha256.lower(),
        ):
            raise RootKeyLoadError("root key fingerprint does not match")
    return root_key
