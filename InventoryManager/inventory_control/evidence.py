"""Canonical JSON evidence primitives shared across control-plane domains.

Domain modules remain responsible for payload shape, normalization, domain
separation, and error types. This module only owns the byte-level JSON
contract and the optional SHA-256 operation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable


ErrorFactory = Callable[[], BaseException]


def canonical_json_bytes(
    value: object,
    *,
    ensure_ascii: bool = True,
    allow_nan: bool = False,
    invalid_error: ErrorFactory | None = None,
) -> bytes:
    """Encode one compact, key-sorted JSON representation."""

    encoding = "ascii" if ensure_ascii else "utf-8"
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=ensure_ascii,
            allow_nan=allow_nan,
        ).encode(encoding)
    except (TypeError, ValueError, UnicodeEncodeError):
        if invalid_error is None:
            raise
        raise invalid_error() from None


def canonical_json_sha256(
    value: object,
    *,
    ensure_ascii: bool = True,
    allow_nan: bool = False,
    invalid_error: ErrorFactory | None = None,
) -> bytes:
    """Return SHA-256 over :func:`canonical_json_bytes`."""

    return hashlib.sha256(
        canonical_json_bytes(
            value,
            ensure_ascii=ensure_ascii,
            allow_nan=allow_nan,
            invalid_error=invalid_error,
        )
    ).digest()


def require_sha256_digest(value: object, invalid_error: ErrorFactory) -> bytes:
    """Return one exact SHA-256 digest or raise the caller's stable error."""

    if not isinstance(value, bytes) or len(value) != 32:
        raise invalid_error()
    return value


__all__ = [
    "canonical_json_bytes",
    "canonical_json_sha256",
    "require_sha256_digest",
]
