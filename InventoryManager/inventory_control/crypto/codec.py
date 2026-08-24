"""Canonical byte encoding used by the version-one crypto protocols."""

from __future__ import annotations

import struct
import uuid
from typing import Union

from .errors import CryptoConfigurationError

UuidValue = Union[str, uuid.UUID]

_UINT32_MAX = (1 << 32) - 1
_UINT64_MAX = (1 << 64) - 1


class CryptoCodecV1:
    """Encode typed protocol fields as length-prefixed byte strings.

    Every field is encoded as ``uint32 big-endian length || value bytes``.
    UUIDs use RFC 4122 network-order bytes and numeric metadata uses unsigned
    64-bit big-endian bytes.
    """

    version = 1

    @staticmethod
    def encode_parts(*parts: bytes) -> bytes:
        encoded = bytearray()
        for part in parts:
            if not isinstance(part, bytes):
                raise CryptoConfigurationError("crypto protocol field must be bytes")
            if len(part) > _UINT32_MAX:
                raise CryptoConfigurationError("crypto protocol field is too large")
            encoded.extend(struct.pack(">I", len(part)))
            encoded.extend(part)
        return bytes(encoded)

    @staticmethod
    def domain(value: str) -> bytes:
        """Encode a fixed, versioned, lower-case ASCII purpose domain."""

        if not isinstance(value, str):
            raise CryptoConfigurationError("crypto purpose must be text")
        try:
            encoded = value.encode("ascii")
        except UnicodeEncodeError:
            raise CryptoConfigurationError("crypto purpose must be ASCII") from None
        if (
            not encoded
            or value != value.lower()
            or not value.startswith("inventory-manager/")
            or not value.endswith("/v1")
            or any(byte < 0x21 or byte > 0x7E for byte in encoded)
        ):
            raise CryptoConfigurationError(
                "crypto purpose must be a version-one lower-case ASCII domain"
            )
        return encoded

    @staticmethod
    def ascii_text(value: str) -> bytes:
        """Encode an exact, non-empty printable ASCII identifier."""

        if not isinstance(value, str):
            raise CryptoConfigurationError("crypto identifier must be text")
        try:
            encoded = value.encode("ascii")
        except UnicodeEncodeError:
            raise CryptoConfigurationError("crypto identifier must be ASCII") from None
        if not encoded or any(byte < 0x21 or byte > 0x7E for byte in encoded):
            raise CryptoConfigurationError(
                "crypto identifier must be non-empty printable ASCII"
            )
        return encoded

    @staticmethod
    def uuid_bytes(value: UuidValue) -> bytes:
        if isinstance(value, uuid.UUID):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = uuid.UUID(value)
            except (ValueError, AttributeError):
                raise CryptoConfigurationError("crypto UUID is invalid") from None
        else:
            raise CryptoConfigurationError("crypto UUID is invalid")
        return parsed.bytes

    @staticmethod
    def uint64(value: int) -> bytes:
        if isinstance(value, bool) or not isinstance(value, int):
            raise CryptoConfigurationError("crypto counter must be an integer")
        if value < 1 or value > _UINT64_MAX:
            raise CryptoConfigurationError("crypto counter is outside uint64 range")
        return struct.pack(">Q", value)
